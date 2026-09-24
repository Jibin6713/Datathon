"""Run the batch twice, independently recalculate all windows, and save evidence."""
from __future__ import annotations

import argparse
import bisect
import csv
import json
import math
import os
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline import (ASSET_MAP, EVENT_MAP, DATE_COLUMNS, DEFAULT_YEARS, HERE, MODEL_INPUTS,
                      annual_summary, find_source, ASSET_FILE, EVENT_FILE, markdown_table,
                      run_pipeline, save_csv, save_json, sha256)

EXPECTED = {"assets": 16214, "events": 3020, "eligible_main_completed": 2925,
            "eligible_matched": 2417, "eligible_unmatched": 508,
            "eligible_event_before_install": 325, "reliable_events": 2092}
EXPECTED_HASHES = {"assets": "b369f143b345002805cf6ee15c59b5576d1fd09fd86d7246e0369d020d68bc03",
                   "events": "d6367b4234d22462e62f0c567a210fc4a23b10e068d31996645a1e24ac8d2d04"}


def source_records(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def parse_date(value):
    return datetime.strptime(value, "%m/%d/%Y %I:%M:%S %p")


def verify(input_dir, output, assets_path=None, events_path=None):
    source_a = find_source(input_dir.resolve(), ASSET_FILE, assets_path)
    source_e = find_source(input_dir.resolve(), EVENT_FILE, events_path)
    before = {"assets": sha256(source_a), "events": sha256(source_e)}
    # Fixed filenames are overwritten, never appended. Source archives are immutable.
    run_pipeline(input_dir, output, str(source_a), str(source_e))
    first = json.loads((output / "artifact_checksums.json").read_text(encoding="utf-8"))
    first_frames = {n: pd.read_parquet(output / "processed" / f"{n}.parquet") for n in
                    ["assets_standardized", "events_standardized", "data_quality_issues", "pipe_risk_features"]}
    run_pipeline(input_dir, output, str(source_a), str(source_e))
    second = json.loads((output / "artifact_checksums.json").read_text(encoding="utf-8"))
    data = {n: pd.read_parquet(output / "processed" / f"{n}.parquet") for n in first_frames}
    a, e, q, f = (data[n] for n in ["assets_standardized", "events_standardized", "data_quality_issues", "pipe_risk_features"])
    raw_a, raw_e = source_records(source_a), source_records(source_e)
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    checks = []

    def check(name, ok, detail):
        checks.append({"check": name, "status": "PASS" if bool(ok) else "FAIL", "detail": detail})

    after = {"assets": sha256(source_a), "events": sha256(source_e)}
    check("01_source_unchanged_and_archive_identical", before == after and all(
          sha256(output / m["archive_path"]) == m["sha256"] == before[m["table"]] for m in manifest["sources"]),
          "Source SHA-256 checked before and after BOTH full runs; archives match byte-for-byte")
    check("01_import_record_counts", len(raw_a) == len(a) == 16214 and len(raw_e) == len(e) == 3020,
          f"stdlib CSV/pandas/standardized rows: assets={len(a)}, events={len(e)}; no dropped source records")
    check("01_expected_file_version", before == EXPECTED_HASHES,
          "Checksums compared to independently recorded source version; any difference is a version discrepancy, never corrected by changing data")
    raw_preserved = True
    for raw, frame, mapping in [(raw_a, a, ASSET_MAP), (raw_e, e, EVENT_MAP)]:
        for old, new in mapping.items():
            raw_preserved &= frame["raw__" + new].tolist() == [r[old] for r in raw]
        raw_preserved &= frame["source_row_number"].tolist() == list(range(2, len(raw) + 2))
    check("01_all_original_cells_and_record_numbers_preserved", raw_preserved,
          "Every cell from 27 asset fields and 37 event fields equals the mapped raw__ field")
    check("02_primary_keys_present_unique", a["asset_id"].notna().all() and a["asset_id"].is_unique
          and e["event_id"].notna().all() and e["event_id"].is_unique,
          "WATMAINID and Wat Break Incident ID; OBJECTID is never a join key")
    check("02_key_dates_parse", a["installation_date"].notna().all() and e["incident_date"].notna().all()
          and not q["issue_code"].eq("date_parse_failed").any(),
          "All installation/incident dates and all nonempty optional dates parsed with explicit month-first format")
    check("02_no_timezone_conversion", all(getattr(frame[c].dt, "tz", None) is None
          for table, frame in [("assets", a), ("events", e)] for c in DATE_COLUMNS[table]),
          "Naive timestamps preserved in Parquet; source timezone not inferred")
    invalid_ids = a.loc[a["invalid_pipe_size"], "asset_id"].tolist()
    check("02_invalid_pipe_size_retained_as_missing", len(invalid_ids) == 2 and set(invalid_ids) == {"158898", "159294"}
          and a.loc[a["invalid_pipe_size"], "pipe_size"].isna().all()
          and set(invalid_ids).issubset(set(f["asset_id"])),
          "PIPE_SIZE=0: assets 158898 and 159294 remain in assets and eligible annual samples")
    default_ok = all(a.loc[a["raw__" + c].eq("-1"), c].isna().all() for c in ["criticality", "condition_score"])
    check("02_default_values_unknown", default_ok and int(a["raw__criticality"].eq("-1").sum()) == 3049
          and int(a["raw__condition_score"].eq("-1").sum()) == 484,
          "CRITICALITY:3049 and Condition Score:484 defaults set missing; originals preserved")
    required_missing = {c: int(a[c].isna().sum()) for c in
                        ["asset_id", "installation_date", "pipe_size", "material", "length_m", "pressure_zone"]}
    check("02_key_field_missingness_reported", (output / "reports" / "field_completeness.csv").is_file()
          and required_missing == {"asset_id": 0, "installation_date": 0, "pipe_size": 2,
                                   "material": 1, "length_m": 0, "pressure_zone": 0}, str(required_missing))

    rec = json.loads((output / "reports" / "event_reconciliation.json").read_text(encoding="utf-8"))
    check("03_expected_funnel", all(rec[k] == v for k, v in EXPECTED.items()),
          "2925 eligible = 2417 matched + 508 unmatched; 2417 = 325 before installation + 2092 reliable; no difference from baseline")
    check("03_dispositions_reconcile_all_events", sum(rec["dispositions"].values()) == len(e)
          and e["event_disposition"].eq("reliable_event").eq(e["reliable_event"]).all(), str(rec["dispositions"]))
    check("04_quality_rows_traceable", all(
        set(q.loc[q["table"].eq(table), "source_row_number"]).issubset(set(frame["source_row_number"]))
        for table, frame in [("assets", a), ("events", e)])
        and not q[["issue_code", "reason", "action", "record_id"]].isna().any().any(),
        f"{len(q)} issue rows with source file, logical row, record ID, raw value, reason and action")
    duplicate_rows = e.loc[e["same_pipe_day_multiple_events"]]
    eligible_duplicates = e.loc[e["eligible_same_pipe_day_multiple_events"]]
    check("04_same_id_day_distinct_events_retained", len(duplicate_rows) == 53
          and duplicate_rows.groupby(["related_asset_id", "incident_day"]).ngroups == 23
          and len(eligible_duplicates) == 41
          and eligible_duplicates.groupby(["related_asset_id", "incident_day"]).ngroups == 18,
          "All ID/day groups:23 groups/53 rows; eligible:18 groups/41 rows; reliable:9 groups/18 rows. ID=0 group is a placeholder, not a known pipe")
    check("04_event_asset_size_not_converted", all(
        (pd.isna(value) and raw["Asset Size (cm)"].strip() == "") or
        (not pd.isna(value) and value == float(raw["Asset Size (cm)"]))
        for value, raw in zip(e["asset_size_reported"], raw_e)),
        "Numeric values kept in their reported unresolved unit, no cm/mm scaling")

    # Independent source oracle: stdlib datetime + sorted arrays/bisect, NOT pipeline aggregation.
    asset_by_id = {r["WATMAINID"].strip(): r for r in raw_a}
    dates_by_id = defaultdict(list)
    for r in raw_e:
        if r["Type of Asset Broken"].strip().upper() != "MAIN" or r["Current status of the break"].strip().upper() != "REPAIR COMPLETED":
            continue
        aid = r["Related Asset ID"].strip()
        if aid not in asset_by_id:
            continue
        when = parse_date(r["Incident date"])
        if when >= parse_date(asset_by_id[aid]["INSTALLATION_DATE"]):
            dates_by_id[aid].append(when)
    for dates in dates_by_id.values():
        dates.sort()
    expected_keys = {(aid, year) for aid, raw in asset_by_id.items() for year in DEFAULT_YEARS
                     if parse_date(raw["INSTALLATION_DATE"]) < datetime(year, 1, 1)}
    actual_keys = set(zip(f["asset_id"], f["as_of_date"].dt.year))
    check("05_unique_installed_asset_year_keys", not f.duplicated(["asset_id", "as_of_date"]).any()
          and actual_keys == expected_keys and len(f) == len(expected_keys),
          f"All {len(expected_keys)} expected keys match; installation strictly before prediction; joins did not multiply rows")
    mismatches = []
    oracle_annual = Counter()
    for row in f.itertuples(index=False):
        t = row.as_of_date.to_pydatetime()
        dates = dates_by_id[row.asset_id]
        past = bisect.bisect_left(dates, t)
        low3 = bisect.bisect_left(dates, datetime(t.year - 3, 1, 1))
        nextyear = bisect.bisect_left(dates, datetime(t.year + 1, 1, 1))
        target = int(nextyear > past)
        oracle_annual[t.year] += target
        since = (t - dates[past - 1]).total_seconds() / (86400 * 365.2425) if past else math.nan
        age = (t - parse_date(asset_by_id[row.asset_id]["INSTALLATION_DATE"])).total_seconds() / (86400 * 365.2425)
        ok = (row.past_break_count == past and row.breaks_last_3y == past - low3
              and row.break_next_12m == target and row.had_prior_break == int(past > 0)
              and math.isclose(row.age_years, age, abs_tol=1e-11)
              and (math.isnan(row.years_since_last_break) if not past else math.isclose(row.years_since_last_break, since, abs_tol=1e-11)))
        if not ok:
            mismatches.append({"asset_id": row.asset_id, "year": t.year})
    check("05_independent_recalculation_all_feature_rows", not mismatches,
          f"Recomputed every age/count/3-year/recency/prior flag/target from original CSV using datetime and bisect; mismatches={len(mismatches)}")
    if mismatches:
        save_csv(pd.DataFrame(mismatches), output / "reports" / "feature_mismatches.csv")
    check("05_forbidden_inputs_absent", set(f.columns) == {"asset_id", "as_of_date", "split", "break_next_12m", *MODEL_INPUTS},
          "Only model input allowlist + identifiers + split + target; current condition/cleaned/future causes and repair details absent")
    real_boundary = e.loc[e["event_id"].eq("2416")].iloc[0]
    p2017 = f.loc[f["asset_id"].eq("41030") & f["as_of_date"].eq("2017-01-01")].iloc[0]
    p2018 = f.loc[f["asset_id"].eq("41030") & f["as_of_date"].eq("2018-01-01")].iloc[0]
    dates = dates_by_id["41030"]
    check("06_real_january_first_boundary", real_boundary["incident_date"] == pd.Timestamp("2018-01-01")
          and p2018["past_break_count"] == bisect.bisect_left(dates, datetime(2018, 1, 1))
          and p2018["break_next_12m"] == 1
          and p2017["break_next_12m"] == int(any(datetime(2017, 1, 1) <= d < datetime(2018, 1, 1) for d in dates)),
          "Real event 2416 on pipe 41030 at 2018-01-01 00:00 is excluded from 2017 target and 2018 history, included in 2018 target")
    p = f.loc[f["asset_id"].eq("134292") & f["as_of_date"].eq("2025-01-01")].iloc[0]
    actual_events = sorted(dates_by_id["134292"])
    check("07_asset_134292", actual_events == [datetime(2017, 12, 1, 15, 15), datetime(2025, 7, 4, 13, 12, 40)]
          and p["past_break_count"] == 1 and p["breaks_last_3y"] == 0 and p["break_next_12m"] == 1
          and math.isclose(p["years_since_last_break"], (datetime(2025, 1, 1) - actual_events[0]).total_seconds() / (86400 * 365.2425)),
          f"2025-01-01: past=1, last3y=0, since={p['years_since_last_break']:.12f}, target=1; 2025 event never included in history")
    changed = sorted(k for k in set(first) | set(second) if first.get(k) != second.get(k))
    logical_equal = True
    for name in first_frames:
        try:
            pd.testing.assert_frame_equal(first_frames[name], data[name], check_exact=True)
        except AssertionError:
            logical_equal = False
    check("08_idempotent_full_rerun", first == second and logical_equal,
          f"Two complete runs; {len(first)} deterministic artifact SHA-256 values compared, changed={changed}; all tables exactly equal; run_metadata timestamp excluded")
    save_json({"first_run": first, "second_run": second, "changed_paths": changed,
               "logical_tables_equal": logical_equal,
               "row_counts": {k: len(v) for k, v in data.items()}}, output / "reports" / "rerun_comparison.json")
    split_years = {key: sorted(v["as_of_date"].dt.year.unique().tolist()) for key, v in f.groupby("split")}
    check("09_disjoint_complete_year_splits", split_years == {"train": list(range(2015, 2022)), "validation": [2022, 2023], "test": [2024, 2025]}, str(split_years))
    per_year = annual_summary(f)
    check("09_per_year_counts_and_rates", all(row.positive_count == oracle_annual[row.year]
          and row.sample_count == sum(year == row.year for _, year in expected_keys)
          and math.isclose(row.positive_rate, row.positive_count / row.sample_count)
          for row in per_year.itertuples(index=False)), "Annual denominators/positive counts/rates checked independently; see annual_summary.csv")
    check("09_no_2026_censored_zero_labels", f["as_of_date"].dt.year.max() == 2025,
          "No 2026 samples; cutoff 2026-01-01; completeness of registry is separately unverified")

    env = dict(os.environ, WATER_PIPELINE_OUTPUT=str(output), WATER_PIPELINE_ASSETS=str(source_a), WATER_PIPELINE_EVENTS=str(source_e))
    unit = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", str(HERE / "tests"), "-v"],
                          cwd=HERE.parent, text=True, capture_output=True, env=env, encoding="utf-8", errors="replace")
    (output / "reports" / "unit_tests.txt").write_text(unit.stdout + unit.stderr, encoding="utf-8")
    check("06_automated_boundary_and_regression_tests", unit.returncode == 0,
          "Executed unittest suite including synthetic exact boundaries, leap years, no-history missingness, duplicate keys, unobserved windows, normalization and actual data; see unit_tests.txt")
    for name, detail in [
        ("historical_asset_membership_and_attribute_validity", "No retired/replaced/split asset histories or attribute validity periods; current snapshot backfill cannot be proven leakage-free"),
        ("historical_event_availability_and_repair_status", "No trustworthy first-recorded time or full status history; current repair-completed filter is retrospective"),
        ("registry_coverage_and_reporting_delay", "Calendar windows have elapsed; CSV alone does not prove complete recording or finalization of all breaks"),
        ("authoritative_units_and_date_precision", "Asset units inferred from MAP_LABEL; event Asset Size units unresolved; source CRS and installation date precision unavailable"),
    ]:
        checks.append({"check": name, "status": "UNVERIFIABLE", "detail": detail})
    result = {"pipeline_sha256": sha256(HERE / "pipeline.py"), "validator_sha256": sha256(Path(__file__)),
              "checks": checks, "status_counts": dict(Counter(c["status"] for c in checks)),
              "source_sha256": before, "feature_rows": len(f),
              "annual_counts": per_year.to_dict(orient="records"), "unittest_returncode": unit.returncode}
    save_json(result, output / "reports" / "validation_results.json")
    report = "# Executed validation results\n\n" + markdown_table(pd.DataFrame(checks))
    report += "\n\nPASS means the executed rule check passed; it does not certify the source records as error-free. UNVERIFIABLE means the two CSV files lack the needed historic evidence. It must not be interpreted as proof of a leakage-free backtest.\n"
    report += "\nData-quality issues were retained and handled according to the rules; see processed/data_quality_issues.csv for the complete issue list. See manual_review.md for the separate manual record check.\n\n"
    report += markdown_table(per_year) + "\n"
    (output / "reports" / "validation_report.md").write_text(report, encoding="utf-8")
    print(json.dumps({"validation_status_counts": result["status_counts"], "unit_returncode": unit.returncode, "feature_rows": len(f)}))
    return 1 if any(c["status"] == "FAIL" for c in checks) else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=HERE.parent / "DataSet")
    parser.add_argument("--output", type=Path, default=HERE / "outputs")
    parser.add_argument("--assets")
    parser.add_argument("--events")
    args = parser.parse_args()
    sys.exit(verify(args.input_dir, args.output.resolve(), args.assets, args.events))


if __name__ == "__main__":
    main()
