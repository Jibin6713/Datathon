"""Run survival-data construction, XGBoost AFT training, and repair ranking."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from pipeline_core import DEFAULT_OUTPUT, run_complete_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--reference-date", type=pd.Timestamp)
    parser.add_argument("--criticality-weight", type=float, default=0.20)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    result = run_complete_pipeline(
        output_dir=args.output_dir,
        reference_date=args.reference_date,
        criticality_weight=args.criticality_weight,
    )
    metrics = result["metrics"]
    test_12m = metrics["test"]["horizons"]["12m"]
    print(f"Completed XGBoost survival pipeline in {args.output_dir.resolve()}")
    print(
        f"Test C-index={metrics['test']['harrell_c_index']:.6f}; "
        f"12m PR-AUC={test_12m['pr_auc']:.6f}; "
        f"12m Brier={test_12m['brier_score']:.6f}"
    )
    print(
        f"Prioritised {result['manifest']['row_counts']['prioritized_assets']:,} "
        "pipes with probabilities, drivers, and repair actions"
    )


if __name__ == "__main__":
    main()
