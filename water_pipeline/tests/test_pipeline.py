"""Regression tests for temporal features and independently reconciled outputs.

Run from the water_pipeline directory:
    python -m unittest discover -s tests -v

The synthetic tests deliberately put distinct incident IDs on temporal boundaries.
They protect the definition of a recorded/repaired future break, rather than
testing whether a pipe was physically free of leaks.
"""

from __future__ import annotations

import sys
import os
import unittest
import csv
import hashlib
from bisect import bisect_left
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline import ASSET_MAP, EVENT_MAP, MODEL_INPUTS, build_features, standardize  # noqa: E402


def source_path(table):
    environment_name = "WATER_PIPELINE_ASSETS" if table == "assets" else "WATER_PIPELINE_EVENTS"
    if os.environ.get(environment_name):
        return Path(os.environ[environment_name])
    basename = "Water_Mains_5473643541506873803.csv" if table == "assets" else "Water_Main_Breaks_-8394745777553033727.csv"
    return next((PROJECT_ROOT.parent / "DataSet").glob(f"*{basename}"))


def output_directory():
    return Path(os.environ.get("WATER_PIPELINE_OUTPUT", str(PROJECT_ROOT / "outputs")))


def assets(*rows: dict) -> pd.DataFrame:
    """Create properly typed asset input without relying on import code."""
    defaults = {
        "asset_id": "p1",
        "installation_date": "2010-01-01",
        "material": "CI",
        "pipe_size": 100.0,
        "length_m": 50.0,
        "pressure_zone": "zone1",
        "model_asset_eligible": True,
    }
    result = pd.DataFrame([{**defaults, **row} for row in (rows or ({},))])
    result["installation_date"] = pd.to_datetime(result["installation_date"], format="ISO8601")
    return result


def events(*rows: dict) -> pd.DataFrame:
    """Create event input with an explicitly typed empty case."""
    columns = ["event_id", "related_asset_id", "incident_date", "reliable_event"]
    records = []
    for index, row in enumerate(rows):
        records.append(
            {
                "event_id": f"e{index}",
                "related_asset_id": "p1",
                "reliable_event": True,
                **row,
            }
        )
    result = pd.DataFrame(records, columns=columns)
    result["incident_date"] = pd.to_datetime(result["incident_date"], format="ISO8601")
    result["reliable_event"] = result["reliable_event"].astype(bool)
    return result


def raw_tables(asset_overrides=None, event_overrides=None):
    asset_default = {**dict.fromkeys(ASSET_MAP, ""), "OBJECTID": "999", "WATMAINID": "p1", "INSTALLATION_DATE": "1/1/2010 12:00:00 AM", "PIPE_SIZE": "100", "MATERIAL": "CI", "PRESSURE_ZONE": "zone1", "Shape__Length": "50", "CRITICALITY": "5", "Condition Score": "7"}
    event_default = {**dict.fromkeys(EVENT_MAP, ""), "OBJECTID": "999", "Wat Break Incident ID": "e1", "Related Asset ID": "p1", "Incident date": "7/4/2025 1:12:40 PM", "Type of Asset Broken": "MAIN", "Current status of the break": "REPAIR COMPLETED", "Asset Size (cm)": "450"}
    return (pd.DataFrame([{**asset_default, **row} for row in (asset_overrides or [{}])]),
            pd.DataFrame([{**event_default, **row} for row in (event_overrides or [{}])]))


class NormalizationTests(unittest.TestCase):
    def test_invalid_sizes_defaults_and_suspect_units_remain_traceable(self):
        raw_a, raw_e = raw_tables(
            [{"WATMAINID": "zero", "PIPE_SIZE": "0", "CRITICALITY": "-1", "Condition Score": "-1"},
             {"WATMAINID": "negative", "PIPE_SIZE": "-10"}],
            [{"Related Asset ID": "zero"}],
        )
        a, e, q = standardize(raw_a, raw_e, "a.csv", "e.csv")
        self.assertEqual(len(a), 2)
        self.assertTrue(a.invalid_pipe_size.all())
        self.assertTrue(a.pipe_size.isna().all())
        self.assertTrue(a.model_asset_eligible.all())
        self.assertEqual(a.raw__pipe_size.tolist(), ["0", "-10"])
        self.assertTrue(pd.isna(a.iloc[0].criticality))
        self.assertTrue(pd.isna(a.iloc[0].condition_score))
        self.assertEqual(a.iloc[0].raw__criticality, "-1")
        self.assertEqual(a.iloc[0].raw__condition_score, "-1")
        self.assertEqual(float(e.iloc[0].asset_size_reported), 450)
        self.assertEqual(e.iloc[0].raw__asset_size_reported, "450")
        counts = q.issue_code.value_counts()
        self.assertEqual(int(counts["invalid_pipe_size"]), 2)
        self.assertEqual(int(counts["default_minus_one"]), 2)
        self.assertEqual(int(counts["asset_size_unit_unverified"]), 1)
        self.assertIsNone(a.installation_date.dt.tz)
        self.assertIsNone(e.incident_date.dt.tz)

    def test_link_uses_asset_identifier_not_equal_object_ids(self):
        raw_a, raw_e = raw_tables(event_overrides=[{"Related Asset ID": "other"}])
        self.assertEqual(raw_a.iloc[0].OBJECTID, raw_e.iloc[0].OBJECTID)
        _, e, q = standardize(raw_a, raw_e, "a.csv", "e.csv")
        self.assertTrue(bool(e.iloc[0].unmatched_asset))
        self.assertFalse(bool(e.iloc[0].matched_asset))
        self.assertFalse(bool(e.iloc[0].reliable_event))
        self.assertIn("unmatched_asset", q.issue_code.tolist())

    def test_event_before_install_and_noneligible_events_are_preserved_excluded(self):
        raw_a, raw_e = raw_tables(event_overrides=[
            {"Wat Break Incident ID": "early", "Incident date": "1/1/2009 12:00:00 AM"},
            {"Wat Break Incident ID": "not_main", "Type of Asset Broken": "SERVICE"},
            {"Wat Break Incident ID": "unfinished", "Current status of the break": "REPAIR REQUIRED"},
        ])
        _, e, q = standardize(raw_a, raw_e, "a.csv", "e.csv")
        self.assertEqual(len(e), 3)
        self.assertFalse(e.reliable_event.any())
        self.assertEqual(e.eligible_event.tolist(), [True, False, False])
        self.assertEqual(e.event_before_install.tolist(), [True, False, False])
        self.assertEqual(int(q.issue_code.eq("event_before_install").sum()), 1)

    def test_duplicate_keys_are_retained_and_excluded_without_arbitrary_choice(self):
        raw_a, raw_e = raw_tables(asset_overrides=[{}, {"MATERIAL": "PVC"}])
        a, e, q = standardize(raw_a, raw_e, "a.csv", "e.csv")
        self.assertEqual(len(a), 2)
        self.assertFalse(a.model_asset_eligible.any())
        self.assertTrue(bool(e.iloc[0].ambiguous_asset))
        self.assertFalse(e.reliable_event.any())
        self.assertEqual(int(q.issue_code.eq("duplicate_primary_key").sum()), 2)
        raw_a, raw_e = raw_tables(event_overrides=[{}, {"Incident date": "7/5/2025 1:12:40 PM"}])
        _, e, q = standardize(raw_a, raw_e, "a.csv", "e.csv")
        self.assertEqual(len(e), 2)
        self.assertTrue(e.invalid_primary_key.all())
        self.assertFalse(e.reliable_event.any())
        self.assertEqual(int(q.issue_code.eq("duplicate_primary_key").sum()), 2)

    def test_bad_required_dates_are_reported_not_silently_accepted(self):
        raw_a, raw_e = raw_tables(
            [{"WATMAINID": "bad_install", "INSTALLATION_DATE": "2/30/2010 12:00:00 AM"}, {"WATMAINID": "p1"}],
            [{"Incident date": "invalid-date"}],
        )
        a, e, q = standardize(raw_a, raw_e, "a.csv", "e.csv")
        self.assertEqual(a.model_asset_eligible.tolist(), [False, True])
        self.assertFalse(e.reliable_event.any())
        self.assertEqual(int(q.issue_code.eq("date_parse_failed").sum()), 2)
        self.assertEqual(a.iloc[0].raw__installation_date, "2/30/2010 12:00:00 AM")
        self.assertEqual(e.iloc[0].raw__incident_date, "invalid-date")

    def test_same_day_distinct_ids_are_flagged_and_both_remain_reliable(self):
        raw_a, raw_e = raw_tables(event_overrides=[
            {"Wat Break Incident ID": "morning", "Incident date": "7/4/2025 9:00:00 AM"},
            {"Wat Break Incident ID": "evening", "Incident date": "7/4/2025 9:00:00 PM"},
        ])
        _, e, q = standardize(raw_a, raw_e, "a.csv", "e.csv")
        self.assertEqual(len(e), 2)
        self.assertTrue(e.reliable_event.all())
        self.assertEqual(e.same_pipe_day_event_count.tolist(), [2, 2])
        self.assertEqual(int(q.issue_code.eq("same_pipe_same_day_multiple_events").sum()), 2)

    def test_same_day_audit_includes_cancelled_records_but_history_does_not(self):
        raw_a, raw_e = raw_tables(event_overrides=[
            {"Wat Break Incident ID": "completed", "Incident date": "7/4/2025 9:00:00 AM"},
            {"Wat Break Incident ID": "cancelled", "Incident date": "7/4/2025 9:00:00 PM", "Current status of the break": "CANCELLED"},
        ])
        _, e, q = standardize(raw_a, raw_e, "a.csv", "e.csv")
        self.assertEqual(len(e), 2)
        self.assertEqual(e.reliable_event.tolist(), [True, False])
        self.assertEqual(e.same_pipe_day_event_count.tolist(), [2, 2])
        self.assertEqual(int(q.issue_code.eq("same_pipe_same_day_multiple_events").sum()), 2)


class RawInputSnapshotTests(unittest.TestCase):
    """Source-side checks use csv/datetime, separately from pandas transforms."""

    @classmethod
    def setUpClass(cls):
        cls.asset_path = source_path("assets")
        cls.event_path = source_path("events")
        with cls.asset_path.open(encoding="utf-8-sig", newline="") as handle:
            cls.raw_assets = list(csv.DictReader(handle))
        with cls.event_path.open(encoding="utf-8-sig", newline="") as handle:
            cls.raw_events = list(csv.DictReader(handle))
        cls.installation = {
            row["WATMAINID"]: datetime.strptime(row["INSTALLATION_DATE"], "%m/%d/%Y %I:%M:%S %p")
            for row in cls.raw_assets
        }

    def test_supplied_snapshot_checksums_and_csv_record_counts(self):
        # These hashes were measured before processing and identify this input version.
        self.assertEqual(hashlib.sha256(self.asset_path.read_bytes()).hexdigest(), "b369f143b345002805cf6ee15c59b5576d1fd09fd86d7246e0369d020d68bc03")
        self.assertEqual(hashlib.sha256(self.event_path.read_bytes()).hexdigest(), "d6367b4234d22462e62f0c567a210fc4a23b10e068d31996645a1e24ac8d2d04")
        self.assertEqual(len(self.raw_assets), 16214)
        self.assertEqual(len(self.raw_events), 3020)

    def test_source_identifiers_are_present_and_unique(self):
        for table, field in [(self.raw_assets, "WATMAINID"), (self.raw_events, "Wat Break Incident ID")]:
            identifiers = [row[field].strip() for row in table]
            self.assertNotIn("", identifiers)
            self.assertEqual(len(identifiers), len(set(identifiers)))

    def test_every_key_date_parses_as_naive_month_first_datetime(self):
        self.assertEqual(len(self.installation), 16214)
        for row in self.raw_events:
            parsed = datetime.strptime(row["Incident date"], "%m/%d/%Y %I:%M:%S %p")
            self.assertIsNone(parsed.tzinfo)

    def test_source_event_funnel_matches_all_expected_counts(self):
        eligible = [row for row in self.raw_events if row["Type of Asset Broken"].strip().upper() == "MAIN" and row["Current status of the break"].strip().upper() == "REPAIR COMPLETED"]
        matched = [row for row in eligible if row["Related Asset ID"].strip() in self.installation]
        before_install = [row for row in matched if datetime.strptime(row["Incident date"], "%m/%d/%Y %I:%M:%S %p") < self.installation[row["Related Asset ID"].strip()]]
        self.assertEqual(len(eligible), 2925)
        self.assertEqual(len(matched), 2417)
        self.assertEqual(len(eligible) - len(matched), 508)
        self.assertEqual(len(before_install), 325)
        self.assertEqual(len(matched) - len(before_install), 2092)

    def test_real_pipe_134292_has_both_expected_events(self):
        selected = {row["Wat Break Incident ID"]: row for row in self.raw_events if row["Related Asset ID"] == "134292"}
        self.assertEqual(set(selected), {"2252", "155653"})
        self.assertEqual(self.installation["134292"], datetime(1937, 1, 1))
        self.assertEqual(datetime.strptime(selected["2252"]["Incident date"], "%m/%d/%Y %I:%M:%S %p"), datetime(2017, 12, 1, 15, 15))
        self.assertEqual(datetime.strptime(selected["155653"]["Incident date"], "%m/%d/%Y %I:%M:%S %p"), datetime(2025, 7, 4, 13, 12, 40))


class DeliveredFeatureTests(unittest.TestCase):
    """Check every delivered feature row against a separate raw-source oracle."""

    @classmethod
    def setUpClass(cls):
        path = output_directory() / "processed" / "pipe_risk_features.parquet"
        if not path.exists():
            raise FileNotFoundError(f"Run the pipeline before artifact tests: {path}")
        cls.features = pd.read_parquet(path)
        with source_path("assets").open(encoding="utf-8-sig", newline="") as handle:
            cls.raw_assets = list(csv.DictReader(handle))
        with source_path("events").open(encoding="utf-8-sig", newline="") as handle:
            cls.raw_events = list(csv.DictReader(handle))
        parse = lambda value: datetime.strptime(value, "%m/%d/%Y %I:%M:%S %p")
        cls.installation = {row["WATMAINID"]: parse(row["INSTALLATION_DATE"]) for row in cls.raw_assets}
        cls.history = defaultdict(list)
        for row in cls.raw_events:
            identifier = row["Related Asset ID"].strip()
            when = parse(row["Incident date"])
            if (row["Type of Asset Broken"].strip().upper() == "MAIN"
                    and row["Current status of the break"].strip().upper() == "REPAIR COMPLETED"
                    and identifier in cls.installation
                    and when >= cls.installation[identifier]):
                cls.history[identifier].append(when)
        for dates in cls.history.values():
            dates.sort()

    def test_delivered_keys_equal_the_independently_expected_asset_year_set(self):
        expected = {(identifier, datetime(year, 1, 1)) for year in range(2015, 2026) for identifier, installed in self.installation.items() if installed < datetime(year, 1, 1)}
        actual = set(zip(self.features.asset_id.astype(str), self.features.as_of_date))
        self.assertEqual(len(self.features), len(expected))
        self.assertEqual(actual, expected)
        self.assertFalse(self.features.duplicated(["asset_id", "as_of_date"]).any())

    def test_every_history_and_target_value_against_independent_raw_oracle(self):
        errors = []
        for row in self.features.itertuples(index=False):
            identifier = str(row.asset_id)
            as_of = row.as_of_date.to_pydatetime()
            dates = self.history.get(identifier, [])
            before = bisect_left(dates, as_of)
            lower = bisect_left(dates, datetime(as_of.year - 3, 1, 1))
            after = bisect_left(dates, datetime(as_of.year + 1, 1, 1))
            expected_recency = (as_of - dates[before - 1]).total_seconds() / (86400 * 365.2425) if before else None
            expected_age = (as_of - self.installation[identifier]).total_seconds() / (86400 * 365.2425)
            actual_counts = (int(row.past_break_count), int(row.breaks_last_3y), int(row.break_next_12m), bool(row.had_prior_break))
            expected_counts = (before, before - lower, int(after > before), bool(before))
            recency_correct = pd.isna(row.years_since_last_break) if expected_recency is None else np.isclose(row.years_since_last_break, expected_recency, rtol=0, atol=1e-9)
            age_correct = np.isclose(row.age_years, expected_age, rtol=0, atol=1e-9)
            if actual_counts != expected_counts or not recency_correct or not age_correct:
                errors.append((identifier, str(as_of), actual_counts, expected_counts, row.years_since_last_break, expected_recency))
                if len(errors) == 10:
                    break
        self.assertEqual(errors, [], f"First mismatches: {errors}")

    def test_actual_pipe_134292_features_do_not_use_the_2025_break_as_history(self):
        selected = self.features.loc[(self.features.asset_id.astype(str) == "134292") & (self.features.as_of_date == pd.Timestamp("2025-01-01"))]
        self.assertEqual(len(selected), 1)
        row = selected.iloc[0]
        self.assertEqual(int(row.past_break_count), 1)
        self.assertEqual(int(row.breaks_last_3y), 0)
        self.assertEqual(int(row.break_next_12m), 1)
        self.assertAlmostEqual(row.years_since_last_break, (datetime(2025, 1, 1) - datetime(2017, 12, 1, 15, 15)).total_seconds() / (86400 * 365.2425))

    def test_actual_year_counts_and_positive_labels_match_raw_oracle(self):
        expected = {2015: (12669, 91), 2016: (12996, 53), 2017: (13231, 64), 2018: (13701, 76), 2019: (13993, 67), 2020: (14827, 51), 2021: (15218, 66), 2022: (15504, 79), 2023: (15792, 40), 2024: (15961, 48), 2025: (16102, 70)}
        actual = {int(year): (len(frame), int(frame.break_next_12m.sum())) for year, frame in self.features.groupby(self.features.as_of_date.dt.year)}
        self.assertEqual(actual, expected)

    def test_actual_split_years_are_disjoint_and_targets_are_not_model_features(self):
        expected = {"train": set(range(2015, 2022)), "validation": {2022, 2023}, "test": {2024, 2025}}
        actual = {split: set(frame.as_of_date.dt.year) for split, frame in self.features.groupby("split")}
        self.assertEqual(actual, expected)
        self.assertTrue(self.features.break_next_12m.isin([0, 1]).all())
        self.assertNotIn("break_next_12m", MODEL_INPUTS)
        forbidden = {"condition_score", "cleaned", "repair_type", "apparent_cause_of_break", "nature_of_break", "road_closed", "does_the_road_need_to_be_closed"}
        self.assertFalse(forbidden.intersection(self.features.columns))


class TemporalFeatureTests(unittest.TestCase):
    def test_as_of_event_is_target_not_history(self):
        frame = build_features(
            assets(), events({"incident_date": "2025-01-01"}), years=[2025]
        )
        row = frame.iloc[0]
        self.assertEqual(int(row.past_break_count), 0)
        self.assertEqual(int(row.breaks_last_3y), 0)
        self.assertTrue(pd.isna(row.years_since_last_break))
        self.assertFalse(bool(row.had_prior_break))
        self.assertEqual(int(row.break_next_12m), 1)

    def test_next_year_start_excluded_from_previous_target(self):
        frame = build_features(
            assets(), events({"incident_date": "2025-01-01"}), years=[2024, 2025]
        ).set_index("as_of_date")
        self.assertEqual(int(frame.loc[pd.Timestamp("2024-01-01"), "break_next_12m"]), 0)
        self.assertEqual(int(frame.loc[pd.Timestamp("2025-01-01"), "break_next_12m"]), 1)

    def test_subday_boundary_and_half_open_window(self):
        frame = build_features(
            assets(),
            events(
                {"incident_date": "2023-12-31 23:59:59"},
                {"incident_date": "2024-01-01 00:00:00"},
                {"incident_date": "2024-12-31 23:59:59"},
                {"incident_date": "2025-01-01 00:00:00"},
            ),
            years=[2024],
        )
        row = frame.iloc[0]
        self.assertEqual(int(row.past_break_count), 1)
        self.assertEqual(int(row.breaks_last_3y), 1)
        self.assertEqual(int(row.break_next_12m), 1)
        self.assertAlmostEqual(float(row.years_since_last_break), 1 / (86400 * 365.2425))

    def test_three_calendar_year_lower_bound_is_inclusive(self):
        row = build_features(
            assets(),
            events(
                {"incident_date": "2019-12-31 23:59:59"},
                {"incident_date": "2020-01-01 00:00:00"},
                {"incident_date": "2022-12-31 23:59:59"},
                {"incident_date": "2023-01-01 00:00:00"},
            ),
            years=[2023],
        ).iloc[0]
        self.assertEqual(int(row.past_break_count), 3)
        self.assertEqual(int(row.breaks_last_3y), 2)

    def test_calendar_year_target_covers_leap_year_end(self):
        row = build_features(
            assets(), events({"incident_date": "2020-12-31 12:00:00"}), years=[2020]
        ).iloc[0]
        self.assertEqual(int(row.break_next_12m), 1)

    def test_leap_day_history_uses_exact_elapsed_time(self):
        row = build_features(
            assets(), events({"incident_date": "2020-02-29"}), years=[2022]
        ).iloc[0]
        elapsed_days = (pd.Timestamp("2022-01-01") - pd.Timestamp("2020-02-29")).days
        self.assertAlmostEqual(float(row.years_since_last_break), elapsed_days / 365.2425)
        self.assertEqual(int(row.breaks_last_3y), 1)

    def test_installation_must_be_strictly_before_as_of(self):
        frame = build_features(
            assets(
                {"asset_id": "old", "installation_date": "2024-12-31 23:59:59"},
                {"asset_id": "same_day", "installation_date": "2025-01-01"},
                {"asset_id": "future", "installation_date": "2025-01-02"},
                {"asset_id": "unknown", "installation_date": None, "model_asset_eligible": False},
            ),
            events(),
            years=[2025],
        )
        self.assertEqual(frame.asset_id.tolist(), ["old"])
        self.assertGreater(float(frame.iloc[0].age_years), 0)

    def test_ineligible_asset_excluded_even_with_valid_installation_date(self):
        frame = build_features(
            assets({"asset_id": "eligible"}, {"asset_id": "excluded", "model_asset_eligible": False}),
            events(), years=[2025],
        )
        self.assertEqual(frame.asset_id.tolist(), ["eligible"])

    def test_no_events_keep_unknown_recency_and_zero_record_count(self):
        row = build_features(assets(), events(), years=[2025]).iloc[0]
        self.assertEqual(int(row.past_break_count), 0)
        self.assertEqual(int(row.breaks_last_3y), 0)
        self.assertEqual(int(row.break_next_12m), 0)
        self.assertFalse(bool(row.had_prior_break))
        self.assertTrue(pd.isna(row.years_since_last_break))

    def test_distinct_same_day_event_ids_are_both_counted(self):
        row = build_features(
            assets(),
            events(
                {"event_id": "first", "incident_date": "2024-08-15"},
                {"event_id": "second", "incident_date": "2024-08-15"},
            ),
            years=[2025],
        ).iloc[0]
        self.assertEqual(int(row.past_break_count), 2)
        self.assertEqual(int(row.breaks_last_3y), 2)
        self.assertTrue(bool(row.had_prior_break))

    def test_unreliable_events_and_unmatched_assets_not_counted(self):
        row = build_features(
            assets(),
            events(
                {"incident_date": "2017-01-01", "reliable_event": False},
                {"incident_date": "2025-06-01", "reliable_event": False},
                {"related_asset_id": "absent", "incident_date": "2024-06-01"},
                {"related_asset_id": "absent", "incident_date": "2025-06-01"},
            ),
            years=[2025],
        ).iloc[0]
        self.assertEqual(int(row.past_break_count), 0)
        self.assertEqual(int(row.breaks_last_3y), 0)
        self.assertEqual(int(row.break_next_12m), 0)

    def test_future_incidents_do_not_change_any_history_feature(self):
        historic = events({"event_id": "old", "incident_date": "2017-06-01"})
        with_future = pd.concat(
            [historic, events({"event_id": "new", "incident_date": "2025-04-01"})],
            ignore_index=True,
        )
        baseline = build_features(assets(), historic, years=[2025])
        changed = build_features(assets(), with_future, years=[2025])
        history_columns = [
            "asset_id", "as_of_date", "past_break_count", "breaks_last_3y",
            "years_since_last_break", "had_prior_break",
        ]
        pd.testing.assert_frame_equal(baseline[history_columns], changed[history_columns])
        self.assertEqual(int(baseline.iloc[0].break_next_12m), 0)
        self.assertEqual(int(changed.iloc[0].break_next_12m), 1)

    def test_multiple_incidents_do_not_multiply_asset_year_rows(self):
        frame = build_features(
            assets({"asset_id": "p1"}, {"asset_id": "p2"}),
            events(*({"incident_date": f"2024-0{month}-15"} for month in range(1, 7))),
            years=[2024, 2025],
        )
        self.assertEqual(len(frame), 4)
        self.assertFalse(frame.duplicated(["asset_id", "as_of_date"]).any())
        self.assertEqual(
            int(frame.loc[(frame.asset_id == "p1") & (frame.as_of_date == pd.Timestamp("2025-01-01")), "past_break_count"].iloc[0]),
            6,
        )

    def test_duplicate_asset_ids_raise_instead_of_multiplying_rows(self):
        with self.assertRaises(ValueError):
            build_features(assets({}, {}), events(), years=[2025])

    def test_incomplete_future_window_is_never_zero_label(self):
        frame = build_features(
            assets(), events(), years=[2025, 2026], observation_end=pd.Timestamp("2026-09-24")
        )
        self.assertEqual(frame.as_of_date.dt.year.tolist(), [2025])

    def test_observation_boundary_requires_entire_twelve_months(self):
        complete = build_features(
            assets(), events(), years=[2025], observation_end=pd.Timestamp("2026-01-01")
        )
        incomplete = build_features(
            assets(), events(), years=[2025], observation_end=pd.Timestamp("2025-12-31 23:59:59")
        )
        self.assertEqual(len(complete), 1)
        self.assertEqual(len(incomplete), 0)

    def test_temporal_splits_have_disjoint_whole_years(self):
        frame = build_features(assets(), events())
        expected = {**dict.fromkeys(range(2015, 2022), "train"), 2022: "validation", 2023: "validation", 2024: "test", 2025: "test"}
        self.assertEqual(dict(zip(frame.as_of_date.dt.year, frame.split)), expected)
        self.assertEqual(len(frame), 11)
        self.assertTrue(frame.groupby(frame.as_of_date.dt.year)["split"].nunique().eq(1).all())

    def test_all_count_features_are_nonnegative_and_target_binary(self):
        frame = build_features(
            assets(), events({"incident_date": "2017-06-01"}, {"incident_date": "2025-04-01"})
        )
        self.assertTrue(frame[["past_break_count", "breaks_last_3y"]].ge(0).all().all())
        self.assertTrue(frame.breaks_last_3y.le(frame.past_break_count).all())
        self.assertTrue(frame.break_next_12m.isin([0, 1]).all())
        self.assertTrue(np.isfinite(frame.age_years).all())


if __name__ == "__main__":
    unittest.main(verbosity=2)
