"""Core functions for the XGBoost time-to-next-break pipeline.

The model uses an accelerated failure time objective. Historical asset snapshots
are landmarks; the outcome is the time from each landmark to the next reliable
break, right-censored at the documented observation cutoff.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import joblib
import numpy as np
import pandas as pd
import xgboost as xgb
from scipy.special import ndtr
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    log_loss,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.linear_model import LogisticRegression


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PIPELINE_OUTPUT = REPOSITORY_ROOT / "water_pipeline" / "outputs"
DEFAULT_FEATURES = PIPELINE_OUTPUT / "processed" / "pipe_risk_features.parquet"
DEFAULT_ASSETS = PIPELINE_OUTPUT / "processed" / "assets_standardized.parquet"
DEFAULT_EVENTS = PIPELINE_OUTPUT / "processed" / "events_standardized.parquet"
DEFAULT_CONTRACT = PIPELINE_OUTPUT / "model_contract.json"
DEFAULT_MANIFEST = PIPELINE_OUTPUT / "manifest.json"
DEFAULT_OUTPUT = REPOSITORY_ROOT / "ml" / "artifacts" / "xgboost_survival"
DEFAULT_SURVIVAL_DATA = DEFAULT_OUTPUT / "survival_training_data.parquet"

YEAR_DAYS = 365.2425
MONTH_DAYS = YEAR_DAYS / 12.0
MIN_DURATION_DAYS = 1.0 / 1440.0
HORIZON_MONTHS = (12, 24, 36)
TOP_FRACTIONS = (0.01, 0.02, 0.05)
CATEGORICAL_FEATURES = ("material", "pressure_zone")


def read_json(path: Path) -> dict:
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, value: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def observation_end_from_manifest(path: Path) -> pd.Timestamp:
    value = read_json(path).get("observation_end_exclusive")
    if not value:
        raise ValueError("manifest is missing observation_end_exclusive")
    result = pd.Timestamp(value)
    if pd.isna(result):
        raise ValueError("manifest observation_end_exclusive is invalid")
    return result


def model_inputs_from_contract(path: Path) -> list[str]:
    contract = read_json(path)
    inputs = list(contract.get("inputs", []))
    if not inputs or len(inputs) != len(set(inputs)):
        raise ValueError("model contract inputs must be nonempty and unique")
    forbidden = set(contract.get("prohibited_inputs", []))
    forbidden.update(contract.get("identifiers", []))
    forbidden.update([contract.get("target"), contract.get("split")])
    invalid = sorted(set(inputs).intersection(forbidden))
    if invalid:
        raise ValueError(f"contract contains prohibited model inputs: {invalid}")
    return inputs


def reliable_event_table(events: pd.DataFrame, cutoff: pd.Timestamp) -> pd.DataFrame:
    required = {"related_asset_id", "incident_date", "reliable_event"}
    missing = sorted(required.difference(events.columns))
    if missing:
        raise ValueError(f"events table is missing columns: {missing}")
    result = events.loc[events["reliable_event"].fillna(False), ["related_asset_id", "incident_date"]].copy()
    result["related_asset_id"] = result["related_asset_id"].astype("string")
    result["incident_date"] = pd.to_datetime(result["incident_date"], errors="coerce")
    result = result.loc[
        result["related_asset_id"].notna()
        & result["incident_date"].notna()
        & result["incident_date"].lt(cutoff)
    ]
    return result.sort_values(["related_asset_id", "incident_date"], kind="stable").reset_index(drop=True)


def build_survival_dataset(
    features: pd.DataFrame,
    events: pd.DataFrame,
    *,
    observation_end: pd.Timestamp,
    inputs: list[str],
) -> pd.DataFrame:
    """Attach next-break time and AFT censoring bounds to landmark rows."""
    required = {"asset_id", "as_of_date", "split", *inputs}
    missing = sorted(required.difference(features.columns))
    if missing:
        raise ValueError(f"feature table is missing columns: {missing}")

    result = features[["asset_id", "as_of_date", "split", *inputs]].copy().reset_index(drop=True)
    result["asset_id"] = result["asset_id"].astype("string")
    result["as_of_date"] = pd.to_datetime(result["as_of_date"], errors="coerce")
    if result[["asset_id", "as_of_date"]].isna().any().any():
        raise ValueError("survival landmarks require nonmissing asset_id and as_of_date")
    if result.duplicated(["asset_id", "as_of_date"]).any():
        raise ValueError("survival landmarks must be unique by asset_id and as_of_date")
    if result["as_of_date"].ge(observation_end).any():
        raise ValueError("all landmark dates must precede the observation cutoff")

    reliable = reliable_event_table(events, observation_end)
    event_arrays = {
        str(asset_id): group["incident_date"].to_numpy(dtype="datetime64[ns]")
        for asset_id, group in reliable.groupby("related_asset_id", sort=False)
    }

    next_values = np.full(len(result), np.datetime64("NaT"), dtype="datetime64[ns]")
    for asset_id, index in result.groupby("asset_id", sort=False).groups.items():
        event_dates = event_arrays.get(str(asset_id))
        if event_dates is None or not len(event_dates):
            continue
        positions = np.asarray(list(index), dtype=int)
        reference_dates = result.loc[positions, "as_of_date"].to_numpy(dtype="datetime64[ns]")
        matches = np.searchsorted(event_dates, reference_dates, side="left")
        found = matches < len(event_dates)
        next_values[positions[found]] = event_dates[matches[found]]

    result["next_break_date"] = pd.to_datetime(next_values)
    result["event_observed"] = result["next_break_date"].notna()
    end_dates = result["next_break_date"].fillna(observation_end)
    duration = (end_dates - result["as_of_date"]).dt.total_seconds() / 86400.0
    if duration.lt(0).any():
        raise ValueError("next-break durations cannot be negative")
    # A break recorded exactly at the landmark belongs to the future target
    # window, but AFT optimises log(time) and therefore requires time > 0.
    result["event_at_reference_time"] = result["event_observed"] & duration.eq(0)
    result["duration_days"] = duration.clip(lower=MIN_DURATION_DAYS).astype(float)
    result["followup_days"] = (
        (observation_end - result["as_of_date"]).dt.total_seconds() / 86400.0
    ).astype(float)
    result["label_lower_bound"] = result["duration_days"]
    result["label_upper_bound"] = np.where(
        result["event_observed"], result["duration_days"], np.inf
    )
    return result


def build_preprocessor(inputs: list[str]) -> tuple[ColumnTransformer, list[str], list[str]]:
    categorical = [name for name in inputs if name in CATEGORICAL_FEATURES]
    numeric = [name for name in inputs if name not in categorical]
    transformer = ColumnTransformer(
        transformers=[
            (
                "numeric",
                Pipeline(
                    steps=[
                        ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
                        ("scaler", StandardScaler()),
                    ]
                ),
                numeric,
            ),
            (
                "categorical",
                Pipeline(
                    steps=[
                        ("imputer", SimpleImputer(strategy="most_frequent")),
                        ("one_hot", OneHotEncoder(handle_unknown="ignore")),
                    ]
                ),
                categorical,
            ),
        ],
        remainder="drop",
        sparse_threshold=1.0,
    )
    return transformer, numeric, categorical


def safe_feature_names(preprocessor: ColumnTransformer) -> tuple[list[str], list[str]]:
    original = [str(value) for value in preprocessor.get_feature_names_out()]
    safe = []
    seen: dict[str, int] = {}
    for name in original:
        candidate = re.sub(r"[\[\]<>]", "_", name)
        count = seen.get(candidate, 0)
        seen[candidate] = count + 1
        safe.append(candidate if count == 0 else f"{candidate}__{count}")
    return original, safe


def make_dmatrix(
    matrix,
    feature_names: list[str],
    frame: pd.DataFrame | None = None,
) -> xgb.DMatrix:
    result = xgb.DMatrix(matrix, feature_names=feature_names)
    if frame is not None:
        result.set_float_info("label_lower_bound", frame["label_lower_bound"].to_numpy(float))
        result.set_float_info("label_upper_bound", frame["label_upper_bound"].to_numpy(float))
    return result


def default_xgboost_parameters() -> dict:
    return {
        "objective": "survival:aft",
        "eval_metric": "aft-nloglik",
        "aft_loss_distribution": "normal",
        "aft_loss_distribution_scale": 1.0,
        "tree_method": "hist",
        "max_depth": 4,
        "eta": 0.035,
        "min_child_weight": 10.0,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "lambda": 2.0,
        "alpha": 0.1,
        "seed": 42,
        "nthread": 0,
    }


def predict_margin(booster: xgb.Booster, matrix: xgb.DMatrix, rounds: int | None = None) -> np.ndarray:
    kwargs = {"output_margin": True}
    if rounds is not None:
        kwargs["iteration_range"] = (0, int(rounds))
    return np.asarray(booster.predict(matrix, **kwargs), dtype=float)


def horizon_days(reference_dates: pd.Series, months: int) -> np.ndarray:
    dates = pd.to_datetime(reference_dates)
    future = dates + pd.DateOffset(months=int(months))
    return ((future - dates).dt.total_seconds() / 86400.0).to_numpy(float)


def aft_predictions(
    margins: np.ndarray,
    reference_dates: pd.Series,
    *,
    distribution_scale: float,
    horizons: Iterable[int] = HORIZON_MONTHS,
) -> pd.DataFrame:
    margins = np.asarray(margins, dtype=float)
    if distribution_scale <= 0:
        raise ValueError("distribution_scale must be positive")
    result = pd.DataFrame(index=reference_dates.index)
    result["predicted_median_days"] = np.exp(np.clip(margins, -20.0, 20.0))
    result["predicted_median_months"] = result["predicted_median_days"] / MONTH_DAYS
    for months in horizons:
        days = horizon_days(reference_dates, int(months))
        z_value = (np.log(days) - margins) / distribution_scale
        result[f"risk_probability_{int(months)}m"] = ndtr(z_value)
    return result


class FenwickTree:
    def __init__(self, size: int):
        self.values = np.zeros(size + 1, dtype=np.int64)

    def add(self, index: int, amount: int = 1) -> None:
        position = index + 1
        while position < len(self.values):
            self.values[position] += amount
            position += position & -position

    def prefix(self, index: int) -> int:
        if index < 0:
            return 0
        total = 0
        position = index + 1
        while position:
            total += int(self.values[position])
            position -= position & -position
        return total


def harrell_concordance_index(
    duration_days: np.ndarray,
    event_observed: np.ndarray,
    predicted_median_days: np.ndarray,
) -> float | None:
    """Exact Harrell C-index in O(n log n), with half credit for prediction ties."""
    duration = np.asarray(duration_days, dtype=float)
    event = np.asarray(event_observed, dtype=bool)
    prediction = np.asarray(predicted_median_days, dtype=float)
    if not (len(duration) == len(event) == len(prediction)):
        raise ValueError("concordance arrays must have equal length")

    unique_prediction = np.unique(prediction)
    prediction_rank = np.searchsorted(unique_prediction, prediction)
    order = np.argsort(-duration, kind="mergesort")
    tree = FenwickTree(len(unique_prediction))
    active = 0
    comparable = 0
    concordant = 0.0
    cursor = 0
    while cursor < len(order):
        end = cursor + 1
        while end < len(order) and duration[order[end]] == duration[order[cursor]]:
            end += 1
        group = order[cursor:end]
        for row in group[event[group]]:
            rank = int(prediction_rank[row])
            lower = tree.prefix(rank - 1)
            equal = tree.prefix(rank) - lower
            greater = active - lower - equal
            comparable += active
            concordant += greater + 0.5 * equal
        for row in group:
            tree.add(int(prediction_rank[row]))
            active += 1
        cursor = end
    return float(concordant / comparable) if comparable else None


def known_horizon_outcomes(
    frame: pd.DataFrame,
    months: int,
    observation_end: pd.Timestamp,
) -> tuple[np.ndarray, np.ndarray]:
    reference = pd.to_datetime(frame["as_of_date"])
    horizon_date = reference + pd.DateOffset(months=int(months))
    next_break = pd.to_datetime(frame["next_break_date"])
    event = frame["event_observed"].to_numpy(bool)
    positive = event & next_break.lt(horizon_date).fillna(False).to_numpy(bool)
    complete_window = horizon_date.le(observation_end).to_numpy(bool)
    # Only fully observed landmark windows support unbiased horizon metrics.
    # Early events from incomplete cohorts are not mixed with unknown negatives.
    known = complete_window
    return known, positive.astype(int)


def _logit_probability(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(np.asarray(values, dtype=float), 1e-9, 1 - 1e-9)
    return np.log(clipped / (1.0 - clipped))


def fit_probability_calibrators(
    frame: pd.DataFrame,
    raw_predictions: pd.DataFrame,
    *,
    observation_end: pd.Timestamp,
    horizons: Iterable[int] = HORIZON_MONTHS,
) -> dict[str, LogisticRegression]:
    """Fit horizon-specific Platt mappings on complete validation windows."""
    calibrators: dict[str, LogisticRegression] = {}
    for months in horizons:
        known, labels = known_horizon_outcomes(frame, int(months), observation_end)
        known_labels = labels[known]
        if len(known_labels) == 0 or np.unique(known_labels).size != 2:
            raise ValueError(f"cannot calibrate {months} months without both classes")
        raw = raw_predictions.loc[known, f"risk_probability_{int(months)}m"].to_numpy(float)
        model = LogisticRegression(C=1.0, solver="lbfgs", max_iter=1_000, random_state=42)
        model.fit(_logit_probability(raw).reshape(-1, 1), known_labels)
        calibrators[f"{int(months)}m"] = model
    return calibrators


def apply_probability_calibrators(
    predictions: pd.DataFrame,
    calibrators: dict[str, LogisticRegression],
    *,
    horizons: Iterable[int] = HORIZON_MONTHS,
) -> pd.DataFrame:
    """Apply Platt mappings and enforce cumulative probability monotonicity."""
    result = predictions.copy()
    calibrated_columns = []
    for months in horizons:
        key = f"{int(months)}m"
        column = f"risk_probability_{key}"
        raw_column = f"raw_{column}"
        result[raw_column] = result[column].to_numpy(float)
        raw_logit = _logit_probability(result[column].to_numpy(float)).reshape(-1, 1)
        result[column] = calibrators[key].predict_proba(raw_logit)[:, 1]
        calibrated_columns.append(column)
    calibrated = np.maximum.accumulate(result[calibrated_columns].to_numpy(float), axis=1)
    result.loc[:, calibrated_columns] = calibrated
    return result


def fraction_label(fraction: float) -> str:
    return f"top_{fraction * 100:g}pct".replace(".", "_")


def inspection_budget_metrics(
    frame: pd.DataFrame,
    scores: np.ndarray,
    labels: np.ndarray,
    fractions: Iterable[float] = TOP_FRACTIONS,
) -> dict:
    ranked = frame[["asset_id", "as_of_date"]].copy()
    ranked["score"] = np.asarray(scores, dtype=float)
    ranked["label"] = np.asarray(labels, dtype=int)
    ranked = ranked.sort_values(
        ["as_of_date", "score", "asset_id"],
        ascending=[True, False, True],
        kind="mergesort",
    )
    ranked["rank"] = ranked.groupby("as_of_date", sort=False).cumcount() + 1
    ranked["count"] = ranked.groupby("as_of_date", sort=False)["asset_id"].transform("size")
    positives = int(ranked["label"].sum())
    base_rate = float(ranked["label"].mean()) if len(ranked) else 0.0
    result = {}
    for fraction in fractions:
        selected = ranked.loc[ranked["rank"].le(np.ceil(ranked["count"] * fraction))]
        inspected = int(len(selected))
        hits = int(selected["label"].sum())
        precision = hits / inspected if inspected else 0.0
        result[fraction_label(float(fraction))] = {
            "fraction": float(fraction),
            "inspected": inspected,
            "hits": hits,
            "precision": precision,
            "recall": hits / positives if positives else 0.0,
            "lift": precision / base_rate if base_rate else None,
        }
    return result


def evaluate_survival_predictions(
    frame: pd.DataFrame,
    predictions: pd.DataFrame,
    *,
    observation_end: pd.Timestamp,
    horizons: Iterable[int] = HORIZON_MONTHS,
) -> dict:
    result = {
        "sample_count": int(len(frame)),
        "observed_event_count": int(frame["event_observed"].sum()),
        "observed_event_rate": float(frame["event_observed"].mean()),
        "harrell_c_index": harrell_concordance_index(
            frame["duration_days"].to_numpy(float),
            frame["event_observed"].to_numpy(bool),
            predictions["predicted_median_days"].to_numpy(float),
        ),
        "event_only_median_time_mae_months": None,
        "horizons": {},
    }
    observed = frame["event_observed"].to_numpy(bool)
    if observed.any():
        absolute_error = np.abs(
            predictions.loc[observed, "predicted_median_days"].to_numpy(float)
            - frame.loc[observed, "duration_days"].to_numpy(float)
        )
        result["event_only_median_time_mae_months"] = float(np.mean(absolute_error) / MONTH_DAYS)

    for months in horizons:
        known, labels = known_horizon_outcomes(frame, int(months), observation_end)
        scores = predictions[f"risk_probability_{int(months)}m"].to_numpy(float)[known]
        known_labels = labels[known]
        known_frame = frame.loc[known]
        metrics = {
            "eligible_count": int(known.sum()),
            "positive_count": int(known_labels.sum()),
            "positive_rate": float(known_labels.mean()) if len(known_labels) else None,
            "mean_predicted_probability": float(scores.mean()) if len(scores) else None,
            "pr_auc": None,
            "roc_auc": None,
            "brier_score": None,
            "log_loss": None,
            "inspection_budgets": {},
        }
        if len(scores):
            metrics["brier_score"] = float(brier_score_loss(known_labels, scores))
            metrics["log_loss"] = float(log_loss(known_labels, np.clip(scores, 1e-15, 1 - 1e-15), labels=[0, 1]))
            if known_labels.sum():
                metrics["pr_auc"] = float(average_precision_score(known_labels, scores))
            if np.unique(known_labels).size == 2:
                metrics["roc_auc"] = float(roc_auc_score(known_labels, scores))
            metrics["inspection_budgets"] = inspection_budget_metrics(
                known_frame,
                scores,
                known_labels,
            )
        result["horizons"][f"{int(months)}m"] = metrics
    return result


def prediction_output_table(
    frame: pd.DataFrame,
    predictions: pd.DataFrame,
) -> pd.DataFrame:
    columns = [
        "asset_id",
        "as_of_date",
        "split",
        "event_observed",
        "next_break_date",
        "duration_days",
        "followup_days",
    ]
    result = frame[columns].copy()
    result = pd.concat([result.reset_index(drop=True), predictions.reset_index(drop=True)], axis=1)
    score_column = "risk_probability_12m"
    result = result.sort_values(
        ["as_of_date", score_column, "asset_id"],
        ascending=[True, False, True],
        kind="mergesort",
    )
    result["risk_rank_within_reference_date"] = result.groupby("as_of_date", sort=False).cumcount() + 1
    result["assets_within_reference_date"] = result.groupby("as_of_date", sort=False)["asset_id"].transform("size")
    return result.reset_index(drop=True)


def source_feature_for_transformed(name: str, numeric: list[str], categorical: list[str]) -> str:
    if name.startswith("numeric__missingindicator_"):
        return name.removeprefix("numeric__missingindicator_")
    if name.startswith("numeric__"):
        return name.removeprefix("numeric__")
    remainder = name.removeprefix("categorical__")
    for feature in sorted(categorical, key=len, reverse=True):
        if remainder == feature or remainder.startswith(feature + "_"):
            return feature
    for feature in numeric:
        if remainder == feature:
            return feature
    raise ValueError(f"cannot map transformed feature to source: {name}")


def aggregate_shap_drivers(
    contributions: np.ndarray,
    transformed_names: list[str],
    score_frame: pd.DataFrame,
    *,
    inputs: list[str],
    numeric: list[str],
    categorical: list[str],
    top_n: int = 3,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Aggregate TreeSHAP log-time contributions to source features.

    XGBoost explains the AFT location (log time). Negating a contribution makes
    positive values mean a shorter predicted time and therefore higher risk.
    """
    contributions = np.asarray(contributions, dtype=float)
    if contributions.shape[1] != len(transformed_names) + 1:
        raise ValueError("SHAP contribution width does not match transformed features plus bias")
    source_names = [source_feature_for_transformed(name, numeric, categorical) for name in transformed_names]
    grouped = np.zeros((len(score_frame), len(inputs)), dtype=float)
    input_positions = {name: index for index, name in enumerate(inputs)}
    for transformed_index, source_name in enumerate(source_names):
        grouped[:, input_positions[source_name]] += -contributions[:, transformed_index]

    long_rows = []
    wide_rows = []
    for row_position, (_, row) in enumerate(score_frame.reset_index(drop=True).iterrows()):
        order = np.argsort(-np.abs(grouped[row_position]), kind="stable")[:top_n]
        wide = {"asset_id": row["asset_id"]}
        for rank, feature_position in enumerate(order, start=1):
            feature = inputs[int(feature_position)]
            contribution = float(grouped[row_position, feature_position])
            raw_value = row.get(feature)
            if pd.isna(raw_value):
                value = "missing"
            elif isinstance(raw_value, (float, np.floating)):
                value = f"{float(raw_value):.6g}"
            else:
                value = str(raw_value)
            direction = "raises risk" if contribution > 0 else "reduces risk"
            long_rows.append(
                {
                    "asset_id": row["asset_id"],
                    "driver_rank": rank,
                    "feature": feature,
                    "feature_value": value,
                    "risk_contribution_log_time": contribution,
                    "direction": direction,
                }
            )
            wide[f"driver_{rank}_feature"] = feature
            wide[f"driver_{rank}_value"] = value
            wide[f"driver_{rank}_direction"] = direction
            wide[f"driver_{rank}_contribution"] = contribution
        wide_rows.append(wide)

    long = pd.DataFrame(long_rows)
    wide = pd.DataFrame(wide_rows)
    top_counts = long["feature"].value_counts()
    global_importance = pd.DataFrame(
        {
            "feature": inputs,
            "mean_absolute_risk_contribution": np.mean(np.abs(grouped), axis=0),
            "mean_signed_risk_contribution": np.mean(grouped, axis=0),
            "top_driver_occurrences": [int(top_counts.get(feature, 0)) for feature in inputs],
        }
    )
    global_importance = global_importance.sort_values(
        "mean_absolute_risk_contribution", ascending=False, kind="stable"
    ).reset_index(drop=True)
    return long, wide, global_importance


def train_xgboost_aft(
    dataset: pd.DataFrame,
    *,
    inputs: list[str],
    output_dir: Path,
    observation_end: pd.Timestamp,
    parameters: dict | None = None,
    num_boost_round: int = 2_500,
    early_stopping_rounds: int = 100,
) -> dict:
    """Train development and final chronological XGBoost AFT models."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    required_splits = {"train", "validation", "test"}
    if set(dataset["split"].unique()) != required_splits:
        raise ValueError("survival dataset must contain train, validation, and test splits")
    train = dataset.loc[dataset["split"].eq("train")].copy()
    validation = dataset.loc[dataset["split"].eq("validation")].copy()
    test = dataset.loc[dataset["split"].eq("test")].copy()
    params = default_xgboost_parameters()
    if parameters:
        params.update(parameters)

    development_preprocessor, numeric, categorical = build_preprocessor(inputs)
    train_matrix = development_preprocessor.fit_transform(train[inputs])
    validation_matrix = development_preprocessor.transform(validation[inputs])
    transformed_names, safe_names = safe_feature_names(development_preprocessor)
    dtrain = make_dmatrix(train_matrix, safe_names, train)
    dvalidation = make_dmatrix(validation_matrix, safe_names, validation)
    evals_result: dict = {}
    development_booster = xgb.train(
        params,
        dtrain,
        num_boost_round=int(num_boost_round),
        evals=[(dtrain, "train"), (dvalidation, "validation")],
        early_stopping_rounds=int(early_stopping_rounds),
        evals_result=evals_result,
        verbose_eval=False,
    )
    best_rounds = int(development_booster.best_iteration) + 1
    validation_margin = predict_margin(development_booster, dvalidation, best_rounds)
    scale = float(params["aft_loss_distribution_scale"])
    validation_predictions = aft_predictions(
        validation_margin,
        validation["as_of_date"],
        distribution_scale=scale,
    )
    calibrators = fit_probability_calibrators(
        validation,
        validation_predictions,
        observation_end=observation_end,
    )
    calibrated_validation_predictions = apply_probability_calibrators(
        validation_predictions,
        calibrators,
    )

    train_validation = pd.concat([train, validation], ignore_index=True)
    final_preprocessor, final_numeric, final_categorical = build_preprocessor(inputs)
    train_validation_matrix = final_preprocessor.fit_transform(train_validation[inputs])
    test_matrix = final_preprocessor.transform(test[inputs])
    final_transformed_names, final_safe_names = safe_feature_names(final_preprocessor)
    dtrain_validation = make_dmatrix(train_validation_matrix, final_safe_names, train_validation)
    dtest = make_dmatrix(test_matrix, final_safe_names, test)
    final_booster = xgb.train(
        params,
        dtrain_validation,
        num_boost_round=best_rounds,
        evals=[(dtrain_validation, "train_validation")],
        verbose_eval=False,
    )
    test_margin = predict_margin(final_booster, dtest, best_rounds)
    test_predictions = aft_predictions(
        test_margin,
        test["as_of_date"],
        distribution_scale=scale,
    )
    calibrated_test_predictions = apply_probability_calibrators(test_predictions, calibrators)

    metrics = {
        "model": "xgboost_accelerated_failure_time",
        "objective": params["objective"],
        "aft_distribution": params["aft_loss_distribution"],
        "aft_distribution_scale": scale,
        "best_boosting_rounds": best_rounds,
        "development_best_validation_aft_nloglik": float(
            evals_result["validation"]["aft-nloglik"][best_rounds - 1]
        ),
        "probability_calibration": (
            "Horizon-specific Platt calibration fitted on complete validation windows; "
            "cumulative probabilities are adjusted to be nondecreasing by horizon"
        ),
        "validation_raw": evaluate_survival_predictions(
            validation,
            validation_predictions,
            observation_end=observation_end,
        ),
        "validation_calibrated_in_sample": evaluate_survival_predictions(
            validation,
            calibrated_validation_predictions,
            observation_end=observation_end,
        ),
        "test": evaluate_survival_predictions(
            test,
            calibrated_test_predictions,
            observation_end=observation_end,
        ),
    }

    model_path = output_dir / "xgboost_aft_model.json"
    preprocessor_path = output_dir / "preprocessor.joblib"
    calibrator_path = output_dir / "probability_calibrators.joblib"
    metrics_path = output_dir / "metrics.json"
    final_booster.save_model(model_path)
    joblib.dump(final_preprocessor, preprocessor_path)
    joblib.dump(calibrators, calibrator_path)
    write_json(metrics_path, metrics)
    prediction_output_table(validation, calibrated_validation_predictions).to_csv(
        output_dir / "validation_survival_predictions.csv", index=False, encoding="utf-8-sig"
    )
    prediction_output_table(test, calibrated_test_predictions).to_csv(
        output_dir / "test_survival_predictions.csv", index=False, encoding="utf-8-sig"
    )

    transformed_to_source = {
        safe: source_feature_for_transformed(original, final_numeric, final_categorical)
        for original, safe in zip(final_transformed_names, final_safe_names)
    }
    gain = final_booster.get_score(importance_type="gain")
    gain_table = pd.DataFrame(
        [
            {
                "transformed_feature": name,
                "source_feature": transformed_to_source[name],
                "gain": float(gain.get(name, 0.0)),
            }
            for name in final_safe_names
        ]
    )
    gain_table = (
        gain_table.groupby("source_feature", as_index=False)["gain"].sum()
        .sort_values("gain", ascending=False, kind="stable")
    )
    gain_table.to_csv(output_dir / "training_feature_gain.csv", index=False, encoding="utf-8-sig")

    metadata = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "inputs": inputs,
        "numeric_features": final_numeric,
        "categorical_features": final_categorical,
        "transformed_feature_names": final_transformed_names,
        "safe_feature_names": final_safe_names,
        "observation_end_exclusive": observation_end.strftime("%Y-%m-%d"),
        "horizon_months": list(HORIZON_MONTHS),
        "best_boosting_rounds": best_rounds,
        "xgboost_parameters": params,
        "row_counts": {
            "train": int(len(train)),
            "validation": int(len(validation)),
            "test": int(len(test)),
        },
        "files": {
            "model": model_path.name,
            "preprocessor": preprocessor_path.name,
            "calibrators": calibrator_path.name,
            "metrics": metrics_path.name,
        },
    }
    write_json(output_dir / "model_metadata.json", metadata)
    return metrics


def build_scoring_snapshot(
    assets: pd.DataFrame,
    events: pd.DataFrame,
    *,
    reference_date: pd.Timestamp,
) -> pd.DataFrame:
    """Build point-in-time model features for every eligible current pipe."""
    required_assets = {
        "asset_id",
        "installation_date",
        "material",
        "pipe_size",
        "length_m",
        "pressure_zone",
        "criticality",
        "model_asset_eligible",
    }
    missing = sorted(required_assets.difference(assets.columns))
    if missing:
        raise ValueError(f"asset table is missing columns: {missing}")
    base = assets.loc[assets["model_asset_eligible"].fillna(False)].copy()
    base["asset_id"] = base["asset_id"].astype("string")
    base["installation_date"] = pd.to_datetime(base["installation_date"], errors="coerce")
    base = base.loc[base["installation_date"].lt(reference_date)].copy()
    if base["asset_id"].isna().any() or base["asset_id"].duplicated().any():
        raise ValueError("eligible scoring assets require unique nonmissing asset_id")

    history = reliable_event_table(events, reference_date)
    all_counts = history.groupby("related_asset_id").size()
    recent_start = reference_date - pd.DateOffset(years=3)
    recent_counts = history.loc[history["incident_date"].ge(recent_start)].groupby("related_asset_id").size()
    last_dates = history.groupby("related_asset_id")["incident_date"].max()

    result = pd.DataFrame(
        {
            "asset_id": base["asset_id"],
            "as_of_date": reference_date,
            "age_years": (
                (reference_date - base["installation_date"]).dt.total_seconds() / (YEAR_DAYS * 86400.0)
            ),
            "material": base["material"],
            "pipe_size": base["pipe_size"],
            "length_m": base["length_m"],
            "pressure_zone": base["pressure_zone"],
            "past_break_count": base["asset_id"].map(all_counts).fillna(0).astype(int),
            "breaks_last_3y": base["asset_id"].map(recent_counts).fillna(0).astype(int),
            "criticality": pd.to_numeric(base["criticality"], errors="coerce"),
        },
        index=base.index,
    )
    last = base["asset_id"].map(last_dates)
    result["years_since_last_break"] = (
        (reference_date - last).dt.total_seconds() / (YEAR_DAYS * 86400.0)
    )
    result["had_prior_break"] = result["past_break_count"].gt(0).astype(int)
    return result.reset_index(drop=True)


def load_model_bundle(
    model_dir: Path,
) -> tuple[xgb.Booster, ColumnTransformer, dict[str, LogisticRegression], dict]:
    model_dir = Path(model_dir)
    metadata = read_json(model_dir / "model_metadata.json")
    preprocessor = joblib.load(model_dir / metadata["files"]["preprocessor"])
    calibrators = joblib.load(model_dir / metadata["files"]["calibrators"])
    booster = xgb.Booster()
    booster.load_model(model_dir / metadata["files"]["model"])
    return booster, preprocessor, calibrators, metadata


def apply_priority_policy(
    scored: pd.DataFrame,
    *,
    criticality_weight: float = 0.20,
) -> pd.DataFrame:
    if not 0 <= criticality_weight <= 1:
        raise ValueError("criticality_weight must be between zero and one")
    result = scored.copy()
    criticality = pd.to_numeric(result["criticality"], errors="coerce")
    median_criticality = float(criticality.dropna().median()) if criticality.notna().any() else 5.0
    result["criticality_was_imputed"] = criticality.isna()
    result["criticality_used"] = criticality.fillna(median_criticality).clip(0, 10)
    result["criticality_normalized"] = result["criticality_used"] / 10.0
    result["urgency_score"] = 100.0 * (
        0.60 * result["risk_probability_12m"]
        + 0.30 * result["risk_probability_24m"]
        + 0.10 * result["risk_probability_36m"]
    )
    service_factor = (1.0 - criticality_weight) + criticality_weight * result["criticality_normalized"]
    result["priority_score"] = result["urgency_score"] * service_factor
    result = result.sort_values(
        ["priority_score", "risk_probability_12m", "asset_id"],
        ascending=[False, False, True],
        kind="mergesort",
    ).reset_index(drop=True)
    result["priority_rank"] = np.arange(1, len(result) + 1)
    result["priority_percentile"] = 100.0 * (
        len(result) - result["priority_rank"] + 1
    ) / len(result)
    fraction = result["priority_rank"] / len(result)
    result["priority_band"] = np.select(
        [fraction.le(0.01), fraction.le(0.05), fraction.le(0.20)],
        ["IMMEDIATE", "HIGH", "PLANNED"],
        default="MONITOR",
    )
    result["recommended_action"] = result["priority_band"].map(
        {
            "IMMEDIATE": "engineering review and inspection planning now",
            "HIGH": "inspect within 3 months",
            "PLANNED": "include in 12 month maintenance plan",
            "MONITOR": "routine monitoring",
        }
    )
    return result


def score_and_prioritize(
    *,
    model_dir: Path,
    assets: pd.DataFrame,
    events: pd.DataFrame,
    reference_date: pd.Timestamp,
    output_dir: Path,
    criticality_weight: float = 0.20,
) -> pd.DataFrame:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    booster, preprocessor, calibrators, metadata = load_model_bundle(model_dir)
    inputs = list(metadata["inputs"])
    snapshot = build_scoring_snapshot(assets, events, reference_date=reference_date)
    matrix = preprocessor.transform(snapshot[inputs])
    _, safe_names = safe_feature_names(preprocessor)
    dscore = make_dmatrix(matrix, safe_names)
    rounds = int(metadata["best_boosting_rounds"])
    margins = predict_margin(booster, dscore, rounds)
    probabilities = aft_predictions(
        margins,
        snapshot["as_of_date"],
        distribution_scale=float(metadata["xgboost_parameters"]["aft_loss_distribution_scale"]),
        horizons=metadata["horizon_months"],
    )
    probabilities = apply_probability_calibrators(
        probabilities,
        calibrators,
        horizons=metadata["horizon_months"],
    )
    scored = pd.concat([snapshot.reset_index(drop=True), probabilities.reset_index(drop=True)], axis=1)
    contributions = booster.predict(dscore, pred_contribs=True, iteration_range=(0, rounds))
    driver_long, driver_wide, global_importance = aggregate_shap_drivers(
        contributions,
        list(metadata["transformed_feature_names"]),
        snapshot,
        inputs=inputs,
        numeric=list(metadata["numeric_features"]),
        categorical=list(metadata["categorical_features"]),
    )
    scored = scored.merge(driver_wide, on="asset_id", how="left", validate="one_to_one")
    prioritized = apply_priority_policy(scored, criticality_weight=criticality_weight)

    prioritized.to_csv(output_dir / "pipe_repair_priority.csv", index=False, encoding="utf-8-sig")
    driver_long.to_csv(output_dir / "pipe_risk_drivers.csv", index=False, encoding="utf-8-sig")
    global_importance.to_csv(
        output_dir / "current_global_driver_importance.csv", index=False, encoding="utf-8-sig"
    )
    policy = {
        "reference_date": reference_date.strftime("%Y-%m-%d"),
        "probability_horizons_months": list(metadata["horizon_months"]),
        "urgency_formula": "100 * (0.60 * P12 + 0.30 * P24 + 0.10 * P36)",
        "priority_formula": (
            "urgency_score * ((1 - criticality_weight) + "
            "criticality_weight * clip(criticality, 0, 10) / 10)"
        ),
        "criticality_weight": criticality_weight,
        "criticality_missing_strategy": "median of current eligible scoring population",
        "priority_bands": {
            "IMMEDIATE": "top 1 percent",
            "HIGH": "next 4 percent through top 5 percent",
            "PLANNED": "next 15 percent through top 20 percent",
            "MONITOR": "remaining assets",
        },
        "asset_count": int(len(prioritized)),
    }
    write_json(output_dir / "priority_policy.json", policy)
    return prioritized


def run_complete_pipeline(
    *,
    output_dir: Path = DEFAULT_OUTPUT,
    reference_date: pd.Timestamp | None = None,
    criticality_weight: float = 0.20,
) -> dict:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    observation_end = observation_end_from_manifest(DEFAULT_MANIFEST)
    if reference_date is None:
        reference_date = observation_end
    reference_date = pd.Timestamp(reference_date)
    if reference_date > observation_end:
        raise ValueError(
            "reference date exceeds the documented complete observation cutoff; "
            "refresh and validate source data before scoring a later date"
        )
    inputs = model_inputs_from_contract(DEFAULT_CONTRACT)
    features = pd.read_parquet(DEFAULT_FEATURES)
    events = pd.read_parquet(DEFAULT_EVENTS)
    assets = pd.read_parquet(DEFAULT_ASSETS)
    survival = build_survival_dataset(
        features,
        events,
        observation_end=observation_end,
        inputs=inputs,
    )
    survival_path = output_dir / "survival_training_data.parquet"
    survival.to_parquet(survival_path, index=False)
    metrics = train_xgboost_aft(
        survival,
        inputs=inputs,
        output_dir=output_dir,
        observation_end=observation_end,
    )
    priority = score_and_prioritize(
        model_dir=output_dir,
        assets=assets,
        events=events,
        reference_date=reference_date,
        output_dir=output_dir,
        criticality_weight=criticality_weight,
    )
    manifest = {
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "reference_date": reference_date.strftime("%Y-%m-%d"),
        "observation_end_exclusive": observation_end.strftime("%Y-%m-%d"),
        "input_hashes": {
            "features": sha256_file(DEFAULT_FEATURES),
            "assets": sha256_file(DEFAULT_ASSETS),
            "events": sha256_file(DEFAULT_EVENTS),
            "contract": sha256_file(DEFAULT_CONTRACT),
            "source_manifest": sha256_file(DEFAULT_MANIFEST),
        },
        "row_counts": {
            "survival_landmarks": int(len(survival)),
            "prioritized_assets": int(len(priority)),
        },
        "primary_outputs": [
            "pipe_repair_priority.csv",
            "pipe_risk_drivers.csv",
            "metrics.json",
            "xgboost_aft_model.json",
            "preprocessor.joblib",
        ],
    }
    write_json(output_dir / "run_manifest.json", manifest)
    return {"metrics": metrics, "manifest": manifest}
