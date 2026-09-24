"""Train and evaluate the annual pipe-break logistic-regression baseline.

The script follows water_pipeline/outputs/model_contract.json. The development model is
trained on contract training years and evaluated on validation years. A fresh
final model is then trained on train + validation and evaluated on test years.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    log_loss,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FEATURE_PIPELINE_OUTPUT = REPOSITORY_ROOT / "water_pipeline" / "outputs"
DEFAULT_FEATURES = FEATURE_PIPELINE_OUTPUT / "processed" / "pipe_risk_features.parquet"
DEFAULT_CONTRACT = FEATURE_PIPELINE_OUTPUT / "model_contract.json"
DEFAULT_OUTPUT = REPOSITORY_ROOT / "ml" / "artifacts" / "logistic_baseline"
DEFAULT_TOP_FRACTIONS = (0.01, 0.02, 0.05)
CATEGORICAL_FEATURES = ("material", "pressure_zone")
REQUIRED_SPLITS = ("train", "validation", "test")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_contract(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        contract = json.load(handle)
    required = {"identifiers", "inputs", "target", "split", "split_years"}
    missing = required.difference(contract)
    if missing:
        raise ValueError(f"Model contract is missing keys: {sorted(missing)}")
    return contract


def validate_data(data: pd.DataFrame, contract: dict) -> tuple[pd.DataFrame, list[str], list[str]]:
    """Validate the feature allowlist, keys, labels, and full-year splits."""
    identifiers = list(contract["identifiers"])
    inputs = list(contract["inputs"])
    target = contract["target"]
    split_column = contract["split"]

    if len(inputs) != len(set(inputs)):
        raise ValueError("Model contract contains duplicate input names")
    blocked = set(contract.get("prohibited_inputs", []))
    blocked.update(identifiers + [target, split_column])
    forbidden = sorted(set(inputs).intersection(blocked))
    if forbidden:
        raise ValueError(f"Forbidden columns are present in model inputs: {forbidden}")

    required_columns = set(identifiers + inputs + [target, split_column])
    missing_columns = sorted(required_columns.difference(data.columns))
    if missing_columns:
        raise ValueError(f"Feature table is missing required columns: {missing_columns}")
    if "as_of_date" not in identifiers:
        raise ValueError("The baseline requires as_of_date as a model identifier")

    result = data.copy()
    result["as_of_date"] = pd.to_datetime(result["as_of_date"], errors="coerce")
    if result["as_of_date"].isna().any():
        raise ValueError("as_of_date contains missing or invalid values")
    if result[identifiers].isna().any().any():
        raise ValueError("Model identifiers contain missing values")
    if result.duplicated(identifiers).any():
        raise ValueError(f"Feature table contains duplicate keys: {identifiers}")

    label_values = set(pd.unique(result[target].dropna()))
    if not label_values.issubset({0, 1, False, True}) or result[target].isna().any():
        raise ValueError(f"{target} must contain only non-missing binary labels")
    result[target] = result[target].astype(int)

    configured_splits = set(contract["split_years"])
    missing_splits = sorted(set(REQUIRED_SPLITS).difference(configured_splits))
    if missing_splits:
        raise ValueError(f"Model contract is missing required splits: {missing_splits}")
    observed_splits = set(result[split_column].dropna().unique())
    if observed_splits != configured_splits:
        raise ValueError(
            f"Observed splits {sorted(observed_splits)} do not match contract "
            f"splits {sorted(configured_splits)}"
        )

    for split_name, expected_years in contract["split_years"].items():
        split_rows = result.loc[result[split_column].eq(split_name)]
        observed_years = set(split_rows["as_of_date"].dt.year.unique())
        if observed_years != set(expected_years):
            raise ValueError(
                f"{split_name} years {sorted(observed_years)} do not match contract "
                f"years {sorted(expected_years)}"
            )
        if split_rows[target].nunique() != 2:
            raise ValueError(f"{split_name} must contain both target classes")

    train_years = set(contract["split_years"]["train"])
    validation_years = set(contract["split_years"]["validation"])
    test_years = set(contract["split_years"]["test"])
    if not max(train_years) < min(validation_years) or not max(validation_years) < min(test_years):
        raise ValueError("Model splits must be strictly chronological")

    categorical = [name for name in inputs if name in CATEGORICAL_FEATURES]
    numeric = [name for name in inputs if name not in categorical]
    for name in numeric:
        if not pd.api.types.is_numeric_dtype(result[name]):
            raise ValueError(f"Numeric model input {name!r} has dtype {result[name].dtype}")
    return result, numeric, categorical


def build_model(
    numeric_features: list[str],
    categorical_features: list[str],
    *,
    regularization_c: float = 1.0,
    class_weight: str | None = None,
) -> Pipeline:
    """Build preprocessing and logistic regression as one leakage-safe pipeline."""
    if regularization_c <= 0:
        raise ValueError("regularization_c must be positive")
    numeric_pipeline = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
            ("scaler", StandardScaler()),
        ]
    )
    categorical_pipeline = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="most_frequent")),
            ("one_hot", OneHotEncoder(handle_unknown="ignore")),
        ]
    )
    preprocessor = ColumnTransformer(
        transformers=[
            ("numeric", numeric_pipeline, numeric_features),
            ("categorical", categorical_pipeline, categorical_features),
        ],
        remainder="drop",
    )
    classifier = LogisticRegression(
        C=regularization_c,
        class_weight=class_weight,
        max_iter=2_000,
        random_state=42,
        solver="liblinear",
    )
    return Pipeline(steps=[("preprocessor", preprocessor), ("classifier", classifier)])


def fraction_label(fraction: float) -> str:
    percent = f"{fraction * 100:g}".replace(".", "_")
    return f"top_{percent}pct"


def validate_top_fractions(fractions: tuple[float, ...] | list[float]) -> tuple[float, ...]:
    result = tuple(float(value) for value in fractions)
    if not result or any(value <= 0 or value >= 1 for value in result):
        raise ValueError("Top fractions must be between 0 and 1")
    if len(set(result)) != len(result):
        raise ValueError("Top fractions must be unique")
    return tuple(sorted(result))


def ranked_rows(
    frame: pd.DataFrame,
    scores: np.ndarray,
    *,
    asset_column: str,
) -> pd.DataFrame:
    ranked = frame[[asset_column, "as_of_date"]].copy()
    ranked["model_score"] = np.asarray(scores, dtype=float)
    ranked = ranked.sort_values(
        ["as_of_date", "model_score", asset_column],
        ascending=[True, False, True],
        kind="mergesort",
    )
    ranked["annual_rank"] = ranked.groupby("as_of_date", sort=False).cumcount() + 1
    ranked["annual_asset_count"] = ranked.groupby("as_of_date", sort=False)[asset_column].transform("size")
    ranked["annual_risk_percentile"] = (
        100.0
        * (ranked["annual_asset_count"] - ranked["annual_rank"] + 1)
        / ranked["annual_asset_count"]
    )
    return ranked.sort_index()


def budget_metrics(
    frame: pd.DataFrame,
    scores: np.ndarray,
    *,
    target: str,
    asset_column: str,
    fractions: tuple[float, ...],
) -> dict:
    ranked = ranked_rows(frame, scores, asset_column=asset_column)
    ranked[target] = frame[target].astype(int)
    positives = int(ranked[target].sum())
    base_rate = float(ranked[target].mean())
    output = {}
    for fraction in fractions:
        budget = np.ceil(ranked["annual_asset_count"] * fraction).astype(int)
        selected = ranked.loc[ranked["annual_rank"].le(budget)]
        inspected = len(selected)
        hits = int(selected[target].sum())
        precision = hits / inspected if inspected else 0.0
        recall = hits / positives if positives else 0.0
        output[fraction_label(fraction)] = {
            "fraction": fraction,
            "inspected": inspected,
            "hits": hits,
            "precision": precision,
            "recall": recall,
            "lift": precision / base_rate if base_rate else None,
        }
    return output


def scalar_metrics(labels: np.ndarray, scores: np.ndarray) -> dict:
    labels = np.asarray(labels, dtype=int)
    scores = np.asarray(scores, dtype=float)
    clipped = np.clip(scores, 1e-15, 1 - 1e-15)
    has_positive = bool(labels.sum())
    has_both_classes = np.unique(labels).size == 2
    return {
        "sample_count": int(len(labels)),
        "positive_count": int(labels.sum()),
        "positive_rate": float(labels.mean()),
        "mean_model_score": float(scores.mean()),
        "pr_auc": float(average_precision_score(labels, scores)) if has_positive else None,
        "roc_auc": float(roc_auc_score(labels, scores)) if has_both_classes else None,
        "brier_score": float(brier_score_loss(labels, scores)),
        "log_loss": float(log_loss(labels, clipped, labels=[0, 1])),
    }


def evaluate_predictions(
    frame: pd.DataFrame,
    scores: np.ndarray,
    *,
    target: str,
    asset_column: str,
    fractions: tuple[float, ...],
) -> dict:
    result = scalar_metrics(frame[target].to_numpy(), scores)
    result["inspection_budgets"] = budget_metrics(
        frame,
        scores,
        target=target,
        asset_column=asset_column,
        fractions=fractions,
    )
    result["by_year"] = {}
    years = frame["as_of_date"].dt.year
    for year in sorted(years.unique()):
        mask = years.eq(year).to_numpy()
        year_frame = frame.loc[mask]
        year_scores = np.asarray(scores)[mask]
        year_result = scalar_metrics(year_frame[target].to_numpy(), year_scores)
        year_result["inspection_budgets"] = budget_metrics(
            year_frame,
            year_scores,
            target=target,
            asset_column=asset_column,
            fractions=fractions,
        )
        result["by_year"][str(year)] = year_result
    return result


def prediction_table(
    frame: pd.DataFrame,
    scores: np.ndarray,
    *,
    contract: dict,
    fractions: tuple[float, ...],
    fitted_on: str,
) -> pd.DataFrame:
    asset_column = contract["identifiers"][0]
    target = contract["target"]
    split_column = contract["split"]
    ranked = ranked_rows(frame, scores, asset_column=asset_column)
    output = frame[[asset_column, "as_of_date", split_column, target]].copy()
    output["model_score"] = np.asarray(scores, dtype=float)
    output["annual_rank"] = ranked["annual_rank"]
    output["annual_asset_count"] = ranked["annual_asset_count"]
    output["annual_risk_percentile"] = ranked["annual_risk_percentile"]
    for fraction in fractions:
        budget = np.ceil(output["annual_asset_count"] * fraction).astype(int)
        output[f"is_{fraction_label(fraction)}"] = output["annual_rank"].le(budget)
    output["model_fitted_on"] = fitted_on
    output["as_of_date"] = output["as_of_date"].dt.strftime("%Y-%m-%d")
    return output.sort_values(["as_of_date", "annual_rank"], kind="mergesort").reset_index(drop=True)


def coefficient_table(model: Pipeline) -> pd.DataFrame:
    preprocessor = model.named_steps["preprocessor"]
    classifier = model.named_steps["classifier"]
    names = preprocessor.get_feature_names_out()
    coefficients = classifier.coef_[0]
    result = pd.DataFrame(
        {
            "transformed_feature": names,
            "coefficient": coefficients,
            "odds_ratio": np.exp(coefficients),
            "absolute_coefficient": np.abs(coefficients),
        }
    )
    return result.sort_values("absolute_coefficient", ascending=False, kind="mergesort").reset_index(drop=True)


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_baseline(
    *,
    feature_path: Path,
    contract_path: Path,
    output_dir: Path,
    regularization_c: float = 1.0,
    class_weight: str | None = None,
    top_fractions: tuple[float, ...] = DEFAULT_TOP_FRACTIONS,
) -> dict:
    top_fractions = validate_top_fractions(top_fractions)
    contract = read_contract(contract_path)
    data = pd.read_parquet(feature_path)
    data, numeric_features, categorical_features = validate_data(data, contract)

    inputs = list(contract["inputs"])
    target = contract["target"]
    split_column = contract["split"]
    asset_column = contract["identifiers"][0]
    train = data.loc[data[split_column].eq("train")].copy()
    validation = data.loc[data[split_column].eq("validation")].copy()
    test = data.loc[data[split_column].eq("test")].copy()

    development_model = build_model(
        numeric_features,
        categorical_features,
        regularization_c=regularization_c,
        class_weight=class_weight,
    )
    development_model.fit(train[inputs], train[target])
    validation_scores = development_model.predict_proba(validation[inputs])[:, 1]

    train_validation = pd.concat([train, validation], ignore_index=True)
    final_model = build_model(
        numeric_features,
        categorical_features,
        regularization_c=regularization_c,
        class_weight=class_weight,
    )
    final_model.fit(train_validation[inputs], train_validation[target])
    test_scores = final_model.predict_proba(test[inputs])[:, 1]

    metrics = {
        "baseline": "logistic_regression",
        "target": target,
        "inputs": inputs,
        "score_interpretation": (
            "Logistic model probability without a separate calibration step"
            if class_weight is None
            else "Ranking score from a class-weighted fit; do not interpret as observed probability"
        ),
        "configuration": {
            "regularization_c": regularization_c,
            "class_weight": class_weight,
            "solver": "liblinear",
            "numeric_imputation": "training median with missing indicators",
            "categorical_imputation": "training most-frequent value",
            "categorical_encoding": "one-hot with unknown categories ignored",
            "top_fractions": list(top_fractions),
        },
        "development_validation": {
            "fitted_on": "train",
            "evaluated_on": "validation",
            **evaluate_predictions(
                validation,
                validation_scores,
                target=target,
                asset_column=asset_column,
                fractions=top_fractions,
            ),
        },
        "final_test": {
            "fitted_on": "train+validation",
            "evaluated_on": "test",
            **evaluate_predictions(
                test,
                test_scores,
                target=target,
                asset_column=asset_column,
                fractions=top_fractions,
            ),
        },
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    model_path = output_dir / "logistic_pipeline.joblib"
    metrics_path = output_dir / "metrics.json"
    validation_path = output_dir / "validation_predictions.csv"
    test_path = output_dir / "test_predictions.csv"
    coefficients_path = output_dir / "coefficients.csv"

    joblib.dump(final_model, model_path)
    write_json(metrics_path, metrics)
    prediction_table(
        validation,
        validation_scores,
        contract=contract,
        fractions=top_fractions,
        fitted_on="train",
    ).to_csv(validation_path, index=False, encoding="utf-8-sig")
    prediction_table(
        test,
        test_scores,
        contract=contract,
        fractions=top_fractions,
        fitted_on="train+validation",
    ).to_csv(test_path, index=False, encoding="utf-8-sig")
    coefficient_table(final_model).to_csv(coefficients_path, index=False, encoding="utf-8-sig")

    metadata = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "pandas": pd.__version__,
        "numpy": np.__version__,
        "scikit_learn": sklearn.__version__,
        "feature_file": str(feature_path.resolve()),
        "feature_file_sha256": sha256_file(feature_path),
        "contract_file": str(contract_path.resolve()),
        "contract_file_sha256": sha256_file(contract_path),
        "row_counts": {
            "train": len(train),
            "validation": len(validation),
            "test": len(test),
        },
        "artifacts": {
            path.name: sha256_file(path)
            for path in [model_path, metrics_path, validation_path, test_path, coefficients_path]
        },
    }
    write_json(output_dir / "run_metadata.json", metadata)
    return metrics


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features", type=Path, default=DEFAULT_FEATURES)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--c", type=float, default=1.0, dest="regularization_c")
    parser.add_argument(
        "--class-weight",
        choices=("none", "balanced"),
        default="none",
        help="Default 'none' preserves the observed class prior; 'balanced' is a ranking-only alternative.",
    )
    parser.add_argument(
        "--top-fractions",
        type=float,
        nargs="+",
        default=list(DEFAULT_TOP_FRACTIONS),
        help="Annual inspection-budget fractions, for example 0.01 0.02 0.05.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    metrics = run_baseline(
        feature_path=args.features,
        contract_path=args.contract,
        output_dir=args.output,
        regularization_c=args.regularization_c,
        class_weight=None if args.class_weight == "none" else args.class_weight,
        top_fractions=tuple(args.top_fractions),
    )
    validation = metrics["development_validation"]
    test = metrics["final_test"]
    print(f"Wrote logistic baseline artifacts to: {args.output.resolve()}")
    print(
        "Validation: "
        f"PR-AUC={validation['pr_auc']:.6f}, ROC-AUC={validation['roc_auc']:.6f}; "
        "Test: "
        f"PR-AUC={test['pr_auc']:.6f}, ROC-AUC={test['roc_auc']:.6f}"
    )


if __name__ == "__main__":
    main()
