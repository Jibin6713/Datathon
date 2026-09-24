"""Score current pipes, explain risk drivers, and rank repair priorities."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from pipeline_core import (
    DEFAULT_ASSETS,
    DEFAULT_EVENTS,
    DEFAULT_MANIFEST,
    DEFAULT_OUTPUT,
    observation_end_from_manifest,
    score_and_prioritize,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--assets", type=Path, default=DEFAULT_ASSETS)
    parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--reference-date", type=pd.Timestamp)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--criticality-weight", type=float, default=0.20)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    observation_end = observation_end_from_manifest(args.manifest)
    reference_date = args.reference_date or observation_end
    if reference_date > observation_end:
        raise ValueError(
            "reference date is after the documented observation cutoff; refresh the data first"
        )
    result = score_and_prioritize(
        model_dir=args.model_dir,
        assets=pd.read_parquet(args.assets),
        events=pd.read_parquet(args.events),
        reference_date=reference_date,
        output_dir=args.output_dir,
        criticality_weight=args.criticality_weight,
    )
    print(f"Scored and prioritised {len(result):,} pipes for {reference_date.date()}")
    print(f"Wrote repair ranking to {(args.output_dir / 'pipe_repair_priority.csv').resolve()}")


if __name__ == "__main__":
    main()
