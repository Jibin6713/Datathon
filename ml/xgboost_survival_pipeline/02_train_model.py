"""Train and evaluate the chronological XGBoost AFT survival model."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from pipeline_core import (
    DEFAULT_CONTRACT,
    DEFAULT_MANIFEST,
    DEFAULT_OUTPUT,
    DEFAULT_SURVIVAL_DATA,
    model_inputs_from_contract,
    observation_end_from_manifest,
    train_xgboost_aft,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_SURVIVAL_DATA)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--num-boost-round", type=int, default=2_500)
    parser.add_argument("--early-stopping-rounds", type=int, default=100)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    metrics = train_xgboost_aft(
        pd.read_parquet(args.dataset),
        inputs=model_inputs_from_contract(args.contract),
        output_dir=args.output_dir,
        observation_end=observation_end_from_manifest(args.manifest),
        num_boost_round=args.num_boost_round,
        early_stopping_rounds=args.early_stopping_rounds,
    )
    print(f"Wrote trained XGBoost AFT model to {args.output_dir.resolve()}")
    print(
        "Validation C-index: "
        f"{metrics['validation_raw']['harrell_c_index']:.6f}; "
        "Test C-index: "
        f"{metrics['test']['harrell_c_index']:.6f}"
    )
    test_12m = metrics["test"]["horizons"]["12m"]
    print(
        "Test 12-month risk: "
        f"PR-AUC={test_12m['pr_auc']:.6f}, "
        f"ROC-AUC={test_12m['roc_auc']:.6f}, "
        f"Brier={test_12m['brier_score']:.6f}"
    )


if __name__ == "__main__":
    main()
