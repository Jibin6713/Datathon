"""Unit tests for the XGBoost time-to-next-break pipeline."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

MODULE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE_DIR))

from pipeline_core import (  # noqa: E402
    aft_predictions,
    apply_probability_calibrators,
    apply_priority_policy,
    build_scoring_snapshot,
    build_survival_dataset,
    harrell_concordance_index,
    known_horizon_outcomes,
)


INPUTS = [
    "age_years",
    "material",
    "pipe_size",
    "length_m",
    "pressure_zone",
    "past_break_count",
    "breaks_last_3y",
    "years_since_last_break",
    "had_prior_break",
]


def feature_rows() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "asset_id": ["A", "B"],
            "as_of_date": pd.to_datetime(["2020-01-01", "2020-01-01"]),
            "split": ["train", "train"],
            "age_years": [20.0, 30.0],
            "material": ["CI", "DI"],
            "pipe_size": [100.0, 150.0],
            "length_m": [10.0, 20.0],
            "pressure_zone": ["Z1", "Z2"],
            "past_break_count": [0, 0],
            "breaks_last_3y": [0, 0],
            "years_since_last_break": [np.nan, np.nan],
            "had_prior_break": [0, 0],
        }
    )


def event_rows() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "related_asset_id": ["A", "A", "B"],
            "incident_date": pd.to_datetime(["2020-06-01", "2022-01-01", "2022-03-01"]),
            "reliable_event": [True, True, True],
        }
    )


class SurvivalTargetTests(unittest.TestCase):
    def test_next_event_is_observed_and_missing_event_is_censored(self):
        result = build_survival_dataset(
            feature_rows(),
            event_rows(),
            observation_end=pd.Timestamp("2021-01-01"),
            inputs=INPUTS,
        ).set_index("asset_id")
        self.assertTrue(bool(result.loc["A", "event_observed"]))
        self.assertEqual(result.loc["A", "next_break_date"], pd.Timestamp("2020-06-01"))
        self.assertFalse(bool(result.loc["B", "event_observed"]))
        self.assertTrue(np.isinf(result.loc["B", "label_upper_bound"]))

    def test_event_at_landmark_is_retained_with_positive_aft_duration(self):
        events = event_rows().copy()
        events.loc[0, "incident_date"] = pd.Timestamp("2020-01-01")
        result = build_survival_dataset(
            feature_rows().iloc[[0]],
            events,
            observation_end=pd.Timestamp("2021-01-01"),
            inputs=INPUTS,
        ).iloc[0]
        self.assertTrue(bool(result["event_at_reference_time"]))
        self.assertGreater(float(result["duration_days"]), 0.0)

    def test_aft_probabilities_increase_with_horizon_and_earlier_model_time(self):
        reference = pd.Series(pd.to_datetime(["2026-01-01", "2026-01-01"]))
        predictions = aft_predictions(
            np.log(np.asarray([100.0, 1_000.0])),
            reference,
            distribution_scale=1.0,
        )
        self.assertTrue((predictions.risk_probability_12m <= predictions.risk_probability_24m).all())
        self.assertTrue((predictions.risk_probability_24m <= predictions.risk_probability_36m).all())
        self.assertGreater(predictions.loc[0, "risk_probability_12m"], predictions.loc[1, "risk_probability_12m"])

    def test_concordance_is_one_for_correct_time_order(self):
        value = harrell_concordance_index(
            np.asarray([10.0, 20.0, 30.0]),
            np.asarray([True, True, False]),
            np.asarray([8.0, 22.0, 40.0]),
        )
        self.assertEqual(value, 1.0)

    def test_incomplete_horizon_is_excluded_from_probability_metrics(self):
        frame = pd.DataFrame(
            {
                "as_of_date": pd.to_datetime(["2025-01-01"]),
                "next_break_date": pd.to_datetime(["2025-06-01"]),
                "event_observed": [True],
            }
        )
        known, labels = known_horizon_outcomes(
            frame,
            24,
            pd.Timestamp("2026-01-01"),
        )
        self.assertFalse(bool(known[0]))
        self.assertTrue(bool(labels[0]))


class ScoringTests(unittest.TestCase):
    def test_scoring_snapshot_excludes_future_events(self):
        assets = pd.DataFrame(
            {
                "asset_id": ["A"],
                "installation_date": pd.to_datetime(["2000-01-01"]),
                "material": ["CI"],
                "pipe_size": [100.0],
                "length_m": [10.0],
                "pressure_zone": ["Z1"],
                "criticality": [8.0],
                "model_asset_eligible": [True],
            }
        )
        events = pd.DataFrame(
            {
                "related_asset_id": ["A", "A"],
                "incident_date": pd.to_datetime(["2025-01-01", "2027-01-01"]),
                "reliable_event": [True, True],
            }
        )
        result = build_scoring_snapshot(
            assets,
            events,
            reference_date=pd.Timestamp("2026-01-01"),
        )
        self.assertEqual(int(result.loc[0, "past_break_count"]), 1)

    def test_priority_rewards_earlier_risk_and_service_criticality(self):
        scored = pd.DataFrame(
            {
                "asset_id": ["early", "late", "important", "ordinary"],
                "criticality": [5.0, 5.0, 10.0, 0.0],
                "risk_probability_12m": [0.6, 0.1, 0.3, 0.3],
                "risk_probability_24m": [0.7, 0.6, 0.4, 0.4],
                "risk_probability_36m": [0.8, 0.8, 0.5, 0.5],
            }
        )
        result = apply_priority_policy(scored).set_index("asset_id")
        self.assertGreater(result.loc["early", "priority_score"], result.loc["late", "priority_score"])
        self.assertGreater(result.loc["important", "priority_score"], result.loc["ordinary", "priority_score"])


if __name__ == "__main__":
    unittest.main()
