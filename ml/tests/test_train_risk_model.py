"""Tests for the leakage-safe logistic-regression baseline."""

from __future__ import annotations

import json
import importlib.util
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

MODEL_PATH = Path(__file__).resolve().parents[1] / "02_train_risk_model.py"
SPEC = importlib.util.spec_from_file_location("train_risk_model", MODEL_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Cannot load model module from {MODEL_PATH}")
MODEL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODEL)

build_model = MODEL.build_model
evaluate_predictions = MODEL.evaluate_predictions
prediction_table = MODEL.prediction_table
run_baseline = MODEL.run_baseline
validate_data = MODEL.validate_data


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


def contract() -> dict:
    return {
        "identifiers": ["asset_id", "as_of_date"],
        "inputs": INPUTS,
        "target": "break_next_12m",
        "split": "split",
        "split_years": {"train": [2019], "validation": [2020], "test": [2021]},
        "prohibited_inputs": ["condition_score", "target", "asset_id", "split"],
    }


def sample_data(rows_per_split: int = 24) -> pd.DataFrame:
    records = []
    for split_name, year in [("train", 2019), ("validation", 2020), ("test", 2021)]:
        for index in range(rows_per_split):
            positive = int(index in {0, 7})
            prior = int(index % 7 == 0)
            records.append(
                {
                    "asset_id": f"{split_name}-{index:03d}",
                    "as_of_date": pd.Timestamp(year, 1, 1),
                    "age_years": float(20 + index),
                    "material": "CI" if index % 2 else "DI",
                    "pipe_size": np.nan if index == 3 else float(100 + 10 * (index % 4)),
                    "length_m": float(10 + index * 2),
                    "pressure_zone": f"zone-{index % 3}",
                    "past_break_count": prior,
                    "breaks_last_3y": prior,
                    "years_since_last_break": 1.0 if prior else np.nan,
                    "had_prior_break": prior,
                    "break_next_12m": positive,
                    "split": split_name,
                }
            )
    return pd.DataFrame(records)


class ContractTests(unittest.TestCase):
    def test_contract_controls_features_and_year_splits(self):
        checked, numeric, categorical = validate_data(sample_data(), contract())
        self.assertEqual(set(numeric + categorical), set(INPUTS))
        self.assertEqual(categorical, ["material", "pressure_zone"])
        self.assertTrue(pd.api.types.is_datetime64_any_dtype(checked.as_of_date))

        bad = sample_data()
        bad.loc[bad.split.eq("test"), "as_of_date"] = pd.Timestamp(2022, 1, 1)
        with self.assertRaisesRegex(ValueError, "do not match contract years"):
            validate_data(bad, contract())

    def test_pipeline_handles_missing_values_and_unseen_categories(self):
        checked, numeric, categorical = validate_data(sample_data(), contract())
        train = checked.loc[checked.split.eq("train")]
        model = build_model(numeric, categorical)
        model.fit(train[INPUTS], train.break_next_12m)
        unknown = train.iloc[[1]][INPUTS].copy()
        unknown.loc[:, "material"] = "NEW_MATERIAL"
        unknown.loc[:, "pressure_zone"] = "NEW_ZONE"
        unknown.loc[:, "pipe_size"] = np.nan
        probability = float(model.predict_proba(unknown)[0, 1])
        self.assertGreaterEqual(probability, 0.0)
        self.assertLessEqual(probability, 1.0)


class RankingTests(unittest.TestCase):
    def test_inspection_budget_is_applied_separately_to_each_year(self):
        rows = []
        scores = []
        for year in (2024, 2025):
            for index in range(100):
                rows.append(
                    {
                        "asset_id": f"{year}-{index:03d}",
                        "as_of_date": pd.Timestamp(year, 1, 1),
                        "break_next_12m": int(index == 0),
                    }
                )
                scores.append(0.9 if index == 0 else 0.1 - index / 10_000)
        frame = pd.DataFrame(rows)
        metrics = evaluate_predictions(
            frame,
            np.asarray(scores),
            target="break_next_12m",
            asset_column="asset_id",
            fractions=(0.01,),
        )
        top = metrics["inspection_budgets"]["top_1pct"]
        self.assertEqual(top["inspected"], 2)
        self.assertEqual(top["hits"], 2)
        self.assertEqual(top["recall"], 1.0)

    def test_year_without_failures_returns_null_ranking_metrics(self):
        frame = pd.DataFrame(
            {
                "asset_id": [f"p-{index}" for index in range(10)],
                "as_of_date": [pd.Timestamp(2025, 1, 1)] * 10,
                "break_next_12m": [0] * 10,
            }
        )
        metrics = evaluate_predictions(
            frame,
            np.linspace(0.2, 0.01, 10),
            target="break_next_12m",
            asset_column="asset_id",
            fractions=(0.1,),
        )
        self.assertIsNone(metrics["pr_auc"])
        self.assertIsNone(metrics["roc_auc"])
        self.assertEqual(metrics["inspection_budgets"]["top_10pct"]["recall"], 0.0)

    def test_prediction_rank_resets_each_year(self):
        data = sample_data(10)
        test = data.loc[data.split.eq("test")].copy()
        scores = np.linspace(0.9, 0.1, len(test))
        output = prediction_table(
            test,
            scores,
            contract=contract(),
            fractions=(0.1,),
            fitted_on="train+validation",
        )
        self.assertEqual(output.annual_rank.tolist(), list(range(1, 11)))
        self.assertEqual(int(output.is_top_10pct.sum()), 1)


class EndToEndTests(unittest.TestCase):
    def test_run_writes_reusable_model_and_holdout_outputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            feature_path = root / "features.parquet"
            contract_path = root / "contract.json"
            output_dir = root / "baseline"
            sample_data().to_parquet(feature_path, index=False)
            contract_path.write_text(json.dumps(contract()), encoding="utf-8")

            metrics = run_baseline(
                feature_path=feature_path,
                contract_path=contract_path,
                output_dir=output_dir,
            )

            self.assertIn("development_validation", metrics)
            self.assertIn("final_test", metrics)
            for name in [
                "logistic_pipeline.joblib",
                "metrics.json",
                "validation_predictions.csv",
                "test_predictions.csv",
                "coefficients.csv",
                "run_metadata.json",
            ]:
                self.assertTrue((output_dir / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
