"""Compare XGBoost AFT and logistic baseline on the identical 12-month test rows."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    log_loss,
    roc_auc_score,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASELINE = REPOSITORY_ROOT / "ml" / "artifacts" / "logistic_baseline"
DEFAULT_XGBOOST = REPOSITORY_ROOT / "ml" / "artifacts" / "xgboost_survival"
DEFAULT_OUTPUT = REPOSITORY_ROOT / "ml" / "artifacts" / "model_comparison"
FRACTIONS = (0.01, 0.02, 0.05)


def read_json(path: Path) -> dict:
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, value: dict) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def scalar_metrics(labels: np.ndarray, scores: np.ndarray) -> dict[str, float]:
    labels = np.asarray(labels, dtype=int)
    scores = np.asarray(scores, dtype=float)
    return {
        "pr_auc": float(average_precision_score(labels, scores)),
        "roc_auc": float(roc_auc_score(labels, scores)),
        "brier_score": float(brier_score_loss(labels, scores)),
        "log_loss": float(
            log_loss(labels, np.clip(scores, 1e-15, 1 - 1e-15), labels=[0, 1])
        ),
        "mean_predicted_probability": float(scores.mean()),
    }


def load_common_test_rows(
    baseline_dir: Path,
    xgboost_dir: Path,
) -> pd.DataFrame:
    baseline = pd.read_csv(
        baseline_dir / "test_predictions.csv",
        parse_dates=["as_of_date"],
    ).rename(columns={"model_score": "baseline_probability"})
    xgboost = pd.read_csv(
        xgboost_dir / "test_survival_predictions.csv",
        parse_dates=["as_of_date", "next_break_date"],
    ).rename(
        columns={
            "risk_probability_12m": "xgboost_probability",
            "risk_rank_within_reference_date": "xgboost_annual_rank",
            "assets_within_reference_date": "xgboost_annual_asset_count",
        }
    )
    xgboost_label = (
        xgboost["event_observed"].astype(bool)
        & xgboost["next_break_date"].lt(
            xgboost["as_of_date"] + pd.DateOffset(months=12)
        ).fillna(False)
    ).astype(int)
    xgboost["xgboost_break_next_12m"] = xgboost_label
    keep_baseline = [
        "asset_id",
        "as_of_date",
        "break_next_12m",
        "baseline_probability",
        "annual_rank",
        "annual_asset_count",
    ]
    keep_xgboost = [
        "asset_id",
        "as_of_date",
        "xgboost_break_next_12m",
        "xgboost_probability",
        "xgboost_annual_rank",
        "xgboost_annual_asset_count",
        "predicted_median_months",
    ]
    merged = baseline[keep_baseline].merge(
        xgboost[keep_xgboost],
        on=["asset_id", "as_of_date"],
        how="inner",
        validate="one_to_one",
    )
    if len(merged) != len(baseline) or len(merged) != len(xgboost):
        raise ValueError("baseline and XGBoost test rows do not match one-to-one")
    if not merged["break_next_12m"].astype(int).equals(
        merged["xgboost_break_next_12m"].astype(int)
    ):
        raise ValueError("baseline and XGBoost 12-month test labels do not match")
    if not merged["annual_asset_count"].equals(merged["xgboost_annual_asset_count"]):
        raise ValueError("annual asset counts differ between model outputs")
    return merged.sort_values(["as_of_date", "asset_id"], kind="stable").reset_index(drop=True)


def budget_comparison(frame: pd.DataFrame, fraction: float) -> dict:
    labels = frame["break_next_12m"].to_numpy(int)
    positives = int(labels.sum())
    base_rate = float(labels.mean())
    annual_count = frame["annual_asset_count"]
    cutoff = np.ceil(annual_count * fraction)
    baseline_selected = frame["annual_rank"].le(cutoff)
    xgboost_selected = frame["xgboost_annual_rank"].le(cutoff)

    def model_values(mask: pd.Series) -> dict:
        inspected = int(mask.sum())
        hits = int(frame.loc[mask, "break_next_12m"].sum())
        precision = hits / inspected if inspected else 0.0
        return {
            "inspected": inspected,
            "hits": hits,
            "precision": precision,
            "recall": hits / positives if positives else 0.0,
            "lift": precision / base_rate if base_rate else None,
        }

    intersection = baseline_selected & xgboost_selected
    union = baseline_selected | xgboost_selected
    xgb_only = xgboost_selected & ~baseline_selected
    baseline_only = baseline_selected & ~xgboost_selected
    baseline_values = model_values(baseline_selected)
    xgboost_values = model_values(xgboost_selected)
    return {
        "fraction": fraction,
        "baseline": baseline_values,
        "xgboost": xgboost_values,
        "xgboost_minus_baseline_hits": xgboost_values["hits"] - baseline_values["hits"],
        "selected_overlap_count": int(intersection.sum()),
        "selected_union_count": int(union.sum()),
        "selected_jaccard": float(intersection.sum() / union.sum()) if union.any() else None,
        "xgboost_only_true_positives": int(frame.loc[xgb_only, "break_next_12m"].sum()),
        "baseline_only_true_positives": int(frame.loc[baseline_only, "break_next_12m"].sum()),
    }


def metric_table(
    baseline_metrics: dict,
    xgboost_metrics: dict,
    actual_rate: float,
) -> pd.DataFrame:
    definitions = [
        ("pr_auc", True),
        ("roc_auc", True),
        ("brier_score", False),
        ("log_loss", False),
        ("mean_predicted_probability", None),
        ("absolute_calibration_gap", False),
    ]
    baseline_values = dict(baseline_metrics)
    xgboost_values = dict(xgboost_metrics)
    baseline_values["absolute_calibration_gap"] = abs(
        baseline_values["mean_predicted_probability"] - actual_rate
    )
    xgboost_values["absolute_calibration_gap"] = abs(
        xgboost_values["mean_predicted_probability"] - actual_rate
    )
    rows = []
    for metric, higher_is_better in definitions:
        baseline_value = float(baseline_values[metric])
        xgboost_value = float(xgboost_values[metric])
        difference = xgboost_value - baseline_value
        if higher_is_better is True:
            improvement = difference / baseline_value if baseline_value else None
        elif higher_is_better is False:
            improvement = (baseline_value - xgboost_value) / baseline_value if baseline_value else None
        else:
            improvement = None
        rows.append(
            {
                "metric": metric,
                "baseline": baseline_value,
                "xgboost_aft": xgboost_value,
                "xgboost_minus_baseline": difference,
                "relative_improvement": improvement,
                "higher_is_better": higher_is_better,
            }
        )
    return pd.DataFrame(rows)


def flatten_budget_rows(comparisons: list[dict]) -> pd.DataFrame:
    rows = []
    for item in comparisons:
        for model in ("baseline", "xgboost"):
            rows.append(
                {
                    "fraction": item["fraction"],
                    "model": model,
                    **item[model],
                    "selected_overlap_count": item["selected_overlap_count"],
                    "selected_jaccard": item["selected_jaccard"],
                    "xgboost_minus_baseline_hits": item["xgboost_minus_baseline_hits"],
                    "xgboost_only_true_positives": item["xgboost_only_true_positives"],
                    "baseline_only_true_positives": item["baseline_only_true_positives"],
                }
            )
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-dir", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--xgboost-dir", type=Path, default=DEFAULT_XGBOOST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    common = load_common_test_rows(args.baseline_dir, args.xgboost_dir)
    labels = common["break_next_12m"].to_numpy(int)
    baseline_scores = common["baseline_probability"].to_numpy(float)
    xgboost_scores = common["xgboost_probability"].to_numpy(float)
    baseline_metrics = scalar_metrics(labels, baseline_scores)
    xgboost_metrics = scalar_metrics(labels, xgboost_scores)
    budgets = [budget_comparison(common, fraction) for fraction in FRACTIONS]
    rank_correlation = float(
        common["annual_rank"].astype(float).corr(
            common["xgboost_annual_rank"].astype(float),
            method="pearson",
        )
    )
    probability_correlation = float(
        common["baseline_probability"].corr(common["xgboost_probability"])
    )
    actual_rate = float(labels.mean())
    summary = {
        "comparison_scope": "identical 2024-2025 rows and identical break_next_12m label",
        "sample_count": int(len(common)),
        "positive_count": int(labels.sum()),
        "positive_rate": actual_rate,
        "baseline": baseline_metrics,
        "xgboost_aft": xgboost_metrics,
        "annual_rank_correlation": rank_correlation,
        "probability_correlation": probability_correlation,
        "mean_absolute_probability_difference": float(
            np.mean(np.abs(baseline_scores - xgboost_scores))
        ),
        "inspection_budgets": {
            f"top_{fraction * 100:g}pct": item
            for fraction, item in zip(FRACTIONS, budgets)
        },
    }
    write_json(args.output_dir / "comparison_summary.json", summary)
    metric_table(baseline_metrics, xgboost_metrics, actual_rate).to_csv(
        args.output_dir / "model_metric_comparison.csv",
        index=False,
        encoding="utf-8-sig",
    )
    flatten_budget_rows(budgets).to_csv(
        args.output_dir / "inspection_budget_comparison.csv",
        index=False,
        encoding="utf-8-sig",
    )
    common.to_csv(
        args.output_dir / "test_prediction_comparison.csv",
        index=False,
        encoding="utf-8-sig",
    )

    top_5 = budgets[-1]
    print(f"Compared {len(common):,} identical test rows with {int(labels.sum()):,} positives")
    print(
        f"PR-AUC: baseline={baseline_metrics['pr_auc']:.6f}, "
        f"XGBoost={xgboost_metrics['pr_auc']:.6f}"
    )
    print(
        f"Top 5% hits: baseline={top_5['baseline']['hits']}, "
        f"XGBoost={top_5['xgboost']['hits']}; "
        f"rank correlation={rank_correlation:.4f}"
    )
    print(f"Wrote comparison artifacts to {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
