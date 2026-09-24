"""Build landmark time-to-next-break training data with right-censoring."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from pipeline_core import (
    DEFAULT_CONTRACT,
    DEFAULT_EVENTS,
    DEFAULT_FEATURES,
    DEFAULT_MANIFEST,
    DEFAULT_SURVIVAL_DATA,
    build_survival_dataset,
    model_inputs_from_contract,
    observation_end_from_manifest,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features", type=Path, default=DEFAULT_FEATURES)
    parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_SURVIVAL_DATA)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    observation_end = observation_end_from_manifest(args.manifest)
    result = build_survival_dataset(
        pd.read_parquet(args.features),
        pd.read_parquet(args.events),
        observation_end=observation_end,
        inputs=model_inputs_from_contract(args.contract),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_parquet(args.output, index=False)
    print(f"Wrote {len(result):,} survival landmarks to {args.output.resolve()}")
    print(
        f"Observed next breaks: {int(result['event_observed'].sum()):,}; "
        f"right-censored: {int((~result['event_observed']).sum()):,}"
    )


if __name__ == "__main__":
    main()
