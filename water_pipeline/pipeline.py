"""Reproducible, source-preserving water-main annual risk dataset builder."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import platform
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow

HERE = Path(__file__).resolve().parent
DATE_FORMAT = "%m/%d/%Y %I:%M:%S %p"
YEAR_SECONDS = 365.2425 * 86400
DEFAULT_YEARS = tuple(range(2015, 2026))
ASSET_FILE = "Water_Mains_5473643541506873803.csv"
EVENT_FILE = "Water_Main_Breaks_-8394745777553033727.csv"

ASSET_MAP = {
    "OBJECTID": "source_object_id", "WATMAINID": "asset_id", "STATUS": "status",
    "PRESSURE_ZONE": "pressure_zone", "ROADSEGMENTID": "road_segment_id",
    "MAP_LABEL": "map_label", "CATEGORY": "category", "PIPE_SIZE": "pipe_size",
    "MATERIAL": "material", "LINED": "lined", "LINED_DATE": "lined_date",
    "LINED_MATERIAL": "lined_material", "INSTALLATION_DATE": "installation_date",
    "ACQUISITION": "acquisition", "CONSULTANT": "consultant", "OWNERSHIP": "ownership",
    "BRIDGE_MAIN": "bridge_main", "BRIDGE_DETAILS": "bridge_details",
    "CRITICALITY": "criticality", "REL_CLEANING_AREA": "rel_cleaning_area",
    "REL_CLEANING_SUBAREA": "rel_cleaning_subarea", "Undersized": "undersized",
    "Shallow Main": "shallow_main", "Condition Score": "condition_score",
    "OVERSIZED": "oversized", "CLEANED": "cleaned", "Shape__Length": "length_m",
}
EVENT_MAP = {
    "OBJECTID": "source_object_id", "Wat Break Incident ID": "event_id",
    "Incident date": "incident_date", "Type of Asset Broken": "asset_type",
    "Does the road need to be closed?": "road_closure",
    "Does the sidewalk need to be closed?": "sidewalk_closure",
    "Estimated Hours for Repair": "estimated_repair_hours",
    "Estimated Number of Units Impacted": "estimated_units_impacted",
    "CW Service Request Number": "cw_service_request_number",
    "Current status of the break": "break_status",
    "Status last updated date": "status_updated_date", "CW Workorder #": "cw_workorder_number",
    "Date operations was returned to normal service": "normal_service_date",
    "Nature of Break": "break_nature", "Apparent cause of break": "break_cause",
    "Repair Type": "repair_type", "Type of Planned Maintenance": "planned_maintenance_type",
    "List Valves Closed": "valves_closed", "List Valves Opened": "valves_opened",
    "List Hydrants Called Out": "hydrants_called_out",
    "List Hydrants Called Back In": "hydrants_called_back_in",
    "Categorization of the Break": "break_category", "Road Segment ID": "road_segment_id",
    "Closest Civic Number": "closest_civic_number", "Street": "street",
    "Related Asset ID": "related_asset_id", "Related Asset Depth (m)": "asset_depth_m",
    "Depth of Frost (m)": "frost_depth_m", "Asset Size (cm)": "asset_size_reported",
    "Year Asset Installed": "reported_installation_year", "Asset Material": "asset_material",
    "Asset Exists": "asset_exists", "GLOBALID": "global_id", "UPDATE_BY": "update_by",
    "UPDATE_DATE": "update_date", "x": "x", "y": "y",
}
DATE_COLUMNS = {"assets": ["installation_date", "lined_date"],
                "events": ["incident_date", "status_updated_date", "normal_service_date", "update_date"]}
NUMERIC_COLUMNS = {"assets": ["pipe_size", "length_m", "criticality", "condition_score"],
                   "events": ["asset_depth_m", "frost_depth_m",
                              "asset_size_reported", "reported_installation_year", "x", "y"]}
ISSUE_COLUMNS = ["table", "source_file", "source_row_number", "record_id", "asset_id",
                 "field", "issue_code", "severity", "raw_value", "reason", "action"]
MODEL_INPUTS = ["age_years", "material", "pipe_size", "length_m", "pressure_zone",
                "past_break_count", "breaks_last_3y", "years_since_last_break", "had_prior_break"]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def save_json(value, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def save_csv(df: pd.DataFrame, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    text_buffer = io.StringIO(newline="")
    df.to_csv(text_buffer, index=False, lineterminator="\n",
              date_format="%Y-%m-%dT%H:%M:%S", float_format="%.12g")
    payload = text_buffer.getvalue().encode("utf-8-sig")
    # A user may have an unchanged output open in Excel on Windows. Reuse its
    # identical bytes rather than requesting an unnecessary replacement lock.
    if path.is_file() and path.read_bytes() == payload:
        return
    path.write_bytes(payload)


def find_source(input_dir: Path, basename: str, explicit: str | None) -> Path:
    if explicit:
        path = Path(explicit).resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        return path
    pattern = re.compile(r"^(?:\d+-)?" + re.escape(basename) + "$", re.IGNORECASE)
    candidates = sorted(p.resolve() for p in input_dir.rglob("*.csv") if pattern.match(p.name))
    if len(candidates) != 1:
        raise ValueError(f"Expected one {basename} under {input_dir}; found {candidates}. Use explicit --assets/--events.")
    return candidates[0]


def import_source(path: Path, raw_dir: Path, table: str):
    """Read strings losslessly (including literal N/A); archive byte-for-byte."""
    before = sha256(path)
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)
    if len(set(header)) != len(header) or any(len(r) != len(header) for r in rows):
        raise ValueError(f"Invalid CSV header/record width: {path}")
    df = pd.read_csv(path, dtype="string", keep_default_na=False, na_filter=False, encoding="utf-8-sig")
    if len(df) != len(rows):
        raise ValueError("CSV reader and pandas import row counts disagree")
    raw_dir.mkdir(parents=True, exist_ok=True)
    dest = raw_dir / path.name
    if path.resolve() == dest.resolve():
        raise ValueError("Source must be outside generated raw directory")
    # An existing archive with different bytes requires a separate output directory.
    if dest.exists() and sha256(dest) != before:
        raise ValueError(f"Raw archive differs from source: {dest}; use a new --output directory.")
    if not dest.exists():
        shutil.copyfile(path, dest)
    if sha256(path) != before or sha256(dest) != before:
        raise RuntimeError("Source/archive checksum changed during import")
    meta = {"table": table, "file_name": path.name, "source_path": str(path),
            "archive_path": f"raw/{path.name}", "row_count": len(df),
            "csv_record_count": len(rows), "column_count": len(header),
            "sha256": before, "size_bytes": path.stat().st_size,
            "encoding": "UTF-8 (BOM accepted)", "date_input_format": DATE_FORMAT,
            "timezone": "unspecified; retained as naive local wall time", "columns": header}
    return df, meta


def add_issue(items, df, mask, table, field, code, reason, action, severity="warning"):
    idcol = "asset_id" if table == "assets" else "event_id"
    assetcol = "asset_id" if table == "assets" else "related_asset_id"
    rawcol = "raw__" + field
    for idx in df.index[pd.Series(mask, index=df.index).fillna(False)]:
        row = df.loc[idx]
        items.append({"table": table, "source_file": row["source_file"],
                      "source_row_number": int(row["source_row_number"]),
                      "record_id": row[idcol], "asset_id": row[assetcol], "field": field,
                      "issue_code": code, "severity": severity,
                      "raw_value": row[rawcol] if rawcol in row else str(row.get(field, "")),
                      "reason": reason, "action": action})


def normalize_table(raw, mapping, table, source_file, issues):
    if set(raw.columns) != set(mapping):
        raise ValueError(f"Schema version mismatch for {table}: missing={set(mapping)-set(raw.columns)}, extra={set(raw.columns)-set(mapping)}")
    df = pd.DataFrame(index=raw.index)
    df["source_file"] = source_file
    # Logical CSV record index + header, NOT physical line number (quoted records may span lines).
    df["source_row_number"] = np.arange(2, len(raw) + 2)
    for old, new in mapping.items():
        df["raw__" + new] = raw[old].astype("string")
        df[new] = raw[old].astype("string").str.strip().replace("", pd.NA)
    uppercase = ["material", "status", "pressure_zone"] if table == "assets" else ["asset_type", "break_status", "asset_material"]
    for c in uppercase:
        df[c] = df[c].str.upper()
    for c in DATE_COLUMNS[table]:
        original = df[c].copy()
        df[c] = pd.to_datetime(original, format=DATE_FORMAT, errors="coerce")
        add_issue(issues, df, original.notna() & df[c].isna(), table, c, "date_parse_failed",
                  "Nonempty value is not a valid month/day/year timestamp", "Keep raw value; normalized date missing; exclude if required", "error")
    for c in NUMERIC_COLUMNS[table]:
        original = df[c].copy()
        df[c] = pd.to_numeric(original, errors="coerce").astype("Float64")
        add_issue(issues, df, original.notna() & df[c].isna(), table, c, "numeric_parse_failed",
                  "Nonempty value is not numeric", "Keep raw value; normalized number missing", "error")
    key = "asset_id" if table == "assets" else "event_id"
    df["invalid_primary_key"] = df[key].isna() | df[key].duplicated(keep=False)
    add_issue(issues, df, df[key].isna(), table, key, "missing_primary_key", "Primary key missing", "Retain record; exclude from model", "error")
    add_issue(issues, df, df[key].notna() & df[key].duplicated(keep=False), table, key, "duplicate_primary_key", "Ambiguous duplicate primary key", "Retain ALL records; exclude from model", "error")
    required = ["installation_date", "material", "pipe_size", "length_m", "pressure_zone"] if table == "assets" else ["incident_date", "related_asset_id", "asset_type", "break_status"]
    for c in required:
        add_issue(issues, df, df[c].isna(), table, c, "missing_key_field", "Required field is missing or failed parsing",
                  "Retain record; exclude only if identifier/date required for model")
    return df


def standardize(raw_assets, raw_events, asset_name, event_name):
    issues = []
    a = normalize_table(raw_assets, ASSET_MAP, "assets", asset_name, issues)
    e = normalize_table(raw_events, EVENT_MAP, "events", event_name, issues)
    for c in ["criticality", "condition_score"]:
        mask = a[c].eq(-1).fillna(False)
        add_issue(issues, a, mask, "assets", c, "default_minus_one", "-1 is a default/unknown score", "Set normalized value missing; retain raw value")
        a.loc[mask, c] = pd.NA
    a["invalid_pipe_size"] = a["pipe_size"].le(0).fillna(False)
    add_issue(issues, a, a["invalid_pipe_size"], "assets", "pipe_size", "invalid_pipe_size",
              "PIPE_SIZE is zero or negative", "Set pipe_size missing; keep the pipe and its annual records")
    a.loc[a["invalid_pipe_size"], "pipe_size"] = pd.NA
    mask = a["length_m"].le(0).fillna(False)
    add_issue(issues, a, mask, "assets", "length_m", "invalid_length", "Length is zero or negative", "Set length missing; keep pipe")
    a.loc[mask, "length_m"] = pd.NA
    mask = a["material"].isin(["XXX", "UNKNOWN", "UNK", "N/A"])
    add_issue(issues, a, mask, "assets", "material", "unknown_material", "Material is an unknown placeholder", "Set normalized material missing; keep pipe")
    a.loc[mask, "material"] = pd.NA
    add_issue(issues, a, a["lined"].eq("YES") & a["lined_date"].isna(), "assets", "lined_date", "lined_date_missing",
              "Pipe marked lined but no lining date", "Do not use lining fields in historical model")
    a["model_asset_eligible"] = ~a["invalid_primary_key"] & a["installation_date"].notna()

    eligible = e["asset_type"].eq("MAIN") & e["break_status"].eq("REPAIR COMPLETED")
    e["eligible_event"] = eligible.fillna(False)
    unique_assets = a.loc[~a["invalid_primary_key"]].set_index("asset_id")
    e["matched_asset"] = e["related_asset_id"].isin(unique_assets.index)
    duplicate_assets = a.loc[a["asset_id"].notna() & a["asset_id"].duplicated(keep=False), "asset_id"]
    e["ambiguous_asset"] = e["related_asset_id"].isin(duplicate_assets)
    e["unmatched_asset"] = ~e["matched_asset"] & ~e["ambiguous_asset"]
    e["placeholder_related_asset_id"] = e["related_asset_id"].eq("0").fillna(False)
    if unique_assets.empty:
        e["matched_installation_date"] = pd.Series(pd.NaT, index=e.index, dtype="datetime64[us]")
    else:
        e["matched_installation_date"] = e["related_asset_id"].map(unique_assets["installation_date"])
    e["event_before_install"] = (e["matched_asset"] & e["incident_date"].lt(e["matched_installation_date"])).fillna(False)
    e["reliable_event"] = (e["eligible_event"] & e["matched_asset"] & ~e["invalid_primary_key"]
                           & e["incident_date"].notna() & e["matched_installation_date"].notna()
                           & ~e["event_before_install"])
    # Mutually exclusive dispositions reconcile all imported records. Additional flags may overlap.
    e["event_disposition"] = np.select([
        ~e["asset_type"].eq("MAIN").fillna(False),
        ~e["break_status"].eq("REPAIR COMPLETED").fillna(False), e["invalid_primary_key"],
        e["incident_date"].isna(), e["ambiguous_asset"], e["unmatched_asset"],
        e["matched_installation_date"].isna(), e["event_before_install"],
    ], ["not_main", "repair_not_completed", "invalid_event_id", "invalid_event_date", "ambiguous_asset",
        "unmatched_asset", "invalid_installation_date", "event_before_install"], default="reliable_event")
    add_issue(issues, e, e["unmatched_asset"], "events", "related_asset_id", "unmatched_asset",
              "Related Asset ID is absent from current unique WATMAINID values", "Keep event; do not guess a pipe; exclude from features/targets")
    add_issue(issues, e, e["placeholder_related_asset_id"], "events", "related_asset_id", "placeholder_related_asset_id",
              "Related Asset ID=0 is a suspected unknown placeholder, not evidence of a shared physical pipe", "Keep original identifier; do not infer association between these events")
    add_issue(issues, e, e["ambiguous_asset"], "events", "related_asset_id", "ambiguous_asset",
              "Related Asset ID matches multiple asset records", "Retain; exclude from features/targets", "error")
    add_issue(issues, e, e["event_before_install"], "events", "incident_date", "event_before_install",
              "Incident precedes current matched pipe installation", "Retain; exclude from reliable features/targets")
    add_issue(issues, e, e["asset_size_reported"].notna(), "events", "asset_size_reported", "asset_size_unit_unverified",
              "Header says cm but examples resemble main PIPE_SIZE millimetres; no authoritative unit metadata", "Keep numeric value unchanged; no conversion or modeling")
    for c in ["normal_service_date", "status_updated_date"]:
        add_issue(issues, e, e[c].notna() & e[c].lt(e["incident_date"]), "events", c,
                  c + "_before_incident", "Administrative date precedes incident date", "Retain for audit; not used to date historical availability")
    e["incident_day"] = e["incident_date"].dt.normalize()
    groupable = e["related_asset_id"].notna() & e["incident_day"].notna()
    counts = e.loc[groupable].groupby(["related_asset_id", "incident_day"])["event_id"].transform("nunique")
    e["same_pipe_day_event_count"] = counts.reindex(e.index).fillna(0).astype("int64")
    e["same_pipe_day_multiple_events"] = e["same_pipe_day_event_count"].gt(1)
    eligible_counts = e.loc[groupable & e["eligible_event"]].groupby(["related_asset_id", "incident_day"])["event_id"].transform("nunique")
    e["eligible_same_pipe_day_event_count"] = eligible_counts.reindex(e.index).fillna(0).astype("int64")
    e["eligible_same_pipe_day_multiple_events"] = e["eligible_same_pipe_day_event_count"].gt(1)
    add_issue(issues, e, e["same_pipe_day_multiple_events"], "events", "incident_date", "same_pipe_same_day_multiple_events",
              "Events share reported related asset ID and calendar day but have distinct event IDs", "Keep every event; review; do not automatically deduplicate")
    quality = pd.DataFrame(issues, columns=ISSUE_COLUMNS).sort_values(["table", "source_row_number", "issue_code", "field"], kind="stable").reset_index(drop=True)
    quality.insert(0, "issue_id", [f"DQ{i:06d}" for i in range(1, len(quality) + 1)])
    return a, e, quality


def build_features(assets, events, years=DEFAULT_YEARS, observation_end=pd.Timestamp("2026-01-01")):
    """Aggregate each event window BEFORE a one-to-one join to installed pipes."""
    base = assets.loc[assets["model_asset_eligible"]].copy()
    if base["asset_id"].isna().any() or base["asset_id"].duplicated().any():
        raise ValueError("Eligible asset_id must be nonmissing and unique")
    reliable = events.loc[events["reliable_event"]].copy()
    if reliable["event_id"].isna().any() or reliable["event_id"].duplicated().any():
        raise ValueError("Reliable event_id must be nonmissing and unique")
    if reliable["incident_date"].isna().any():
        raise ValueError("Reliable events require parseable incident dates")
    if len(set(years)) != len(years):
        raise ValueError("Prediction years must be unique")
    frames = []
    for year in sorted(years):
        start = pd.Timestamp(year=year, month=1, day=1)
        end = start + pd.DateOffset(months=12)
        if end > pd.Timestamp(observation_end):
            continue
        p = base.loc[base["installation_date"].lt(start),
                     ["asset_id", "installation_date", "material", "pipe_size", "length_m", "pressure_zone"]].copy()
        prior = reliable.loc[reliable["incident_date"].lt(start)]
        past = prior.groupby("related_asset_id").agg(past_break_count=("event_id", "size"), last_break_date=("incident_date", "max"))
        recent = prior.loc[prior["incident_date"].ge(start - pd.DateOffset(years=3))].groupby("related_asset_id").size().rename("breaks_last_3y")
        future = reliable.loc[reliable["incident_date"].ge(start) & reliable["incident_date"].lt(end)].groupby("related_asset_id").size().rename("target_event_count")
        p = p.merge(past, how="left", left_on="asset_id", right_index=True, validate="one_to_one")
        p = p.merge(recent, how="left", left_on="asset_id", right_index=True, validate="one_to_one")
        p = p.merge(future, how="left", left_on="asset_id", right_index=True, validate="one_to_one")
        p["as_of_date"] = start
        p["age_years"] = (start - p["installation_date"]).dt.total_seconds() / YEAR_SECONDS
        p["years_since_last_break"] = (start - p["last_break_date"]).dt.total_seconds() / YEAR_SECONDS
        for c in ["past_break_count", "breaks_last_3y"]:
            p[c] = p[c].fillna(0).astype("int64")
        p["had_prior_break"] = p["past_break_count"].gt(0).astype("int8")
        p["break_next_12m"] = p["target_event_count"].fillna(0).gt(0).astype("int8")
        p["split"] = "train" if year <= 2021 else ("validation" if year <= 2023 else "test")
        frames.append(p[["asset_id", "as_of_date", *MODEL_INPUTS, "break_next_12m", "split"]])
    cols = ["asset_id", "as_of_date", *MODEL_INPUTS, "break_next_12m", "split"]
    if not frames:
        return pd.DataFrame(columns=cols)
    result = pd.concat(frames, ignore_index=True).sort_values(["as_of_date", "asset_id"], kind="stable").reset_index(drop=True)
    if result.duplicated(["asset_id", "as_of_date"]).any():
        raise AssertionError("Annual feature key is not unique")
    return result


def reconciliation(assets, events):
    eligible = events["eligible_event"]
    return {"assets": len(assets), "events": len(events), "eligible_main_completed": int(eligible.sum()),
            "eligible_matched": int((eligible & events["matched_asset"]).sum()),
            "eligible_unmatched": int((eligible & events["unmatched_asset"]).sum()),
            "eligible_ambiguous": int((eligible & events["ambiguous_asset"]).sum()),
            "eligible_event_before_install": int((eligible & events["event_before_install"]).sum()),
            "reliable_events": int(events["reliable_event"].sum()),
            "dispositions": {str(k): int(v) for k, v in events["event_disposition"].value_counts().sort_index().items()}}


def annual_summary(features, years=DEFAULT_YEARS):
    rows = []
    for year in years:
        f = features.loc[features["as_of_date"].dt.year.eq(year)]
        positives = int(f["break_next_12m"].sum())
        rows.append({"year": year, "split": "train" if year <= 2021 else "validation" if year <= 2023 else "test",
                     "sample_count": len(f), "positive_count": positives,
                     "positive_rate": positives / len(f) if len(f) else None})
    return pd.DataFrame(rows)


def field_mapping(assets, events):
    rows = []
    for table, mapping, df in [("assets", ASSET_MAP, assets), ("events", EVENT_MAP, events)]:
        for old, new in mapping.items():
            rule = "trim outer whitespace; blank to missing; raw value preserved"
            if new in DATE_COLUMNS[table]:
                rule = f"parse {DATE_FORMAT}; naive timestamp; never convert to UTC"
            elif new in NUMERIC_COLUMNS[table]:
                rule = "parse numeric; invalid to missing; raw value preserved"
            if new in ["criticality", "condition_score"]:
                rule += "; -1 to missing"
            if new == "pipe_size":
                rule += "; <=0 to missing; no pipe deletion; mm inferred from MAP_LABEL"
            if new == "asset_size_reported":
                rule += "; unit unresolved; NO centimetre conversion"
            if new == "length_m":
                rule += "; metres inferred from MAP_LABEL; no geometry/CRS metadata"
            rows.append({"table": table, "original_field": old, "normalized_field": new,
                         "raw_field": "raw__" + new, "dtype": str(df[new].dtype), "rule": rule})
    return pd.DataFrame(rows)


def markdown_table(df):
    def fmt(value):
        if pd.isna(value):
            return ""
        return str(value).replace("|", "\\|").replace("\n", " ")
    return "\n".join(["| " + " | ".join(df.columns) + " |", "| " + " | ".join(["---"] * len(df.columns)) + " |"] +
                     ["| " + " | ".join(fmt(v) for v in row) + " |" for row in df.itertuples(index=False, name=None)])


def write_reports(out, assets, events, quality, features, manifest):
    reports = out / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    rec = reconciliation(assets, events)
    save_json(rec, reports / "event_reconciliation.json")
    quality_summary = quality.groupby(["table", "issue_code", "field"], dropna=False).agg(
        issue_count=("issue_id", "size"), affected_records=("source_row_number", "nunique")).reset_index()
    save_csv(quality_summary, reports / "data_quality_summary.csv")
    per_year = annual_summary(features)
    save_csv(per_year, reports / "annual_summary.csv")
    save_csv(field_mapping(assets, events), reports / "field_mapping.csv")
    missing = []
    for table, mapping, df in [("assets", ASSET_MAP, assets), ("events", EVENT_MAP, events)]:
        for old, new in mapping.items():
            missing.append({"table": table, "original_field": old, "field": new, "rows": len(df),
                            "raw_blank_count": int(df["raw__" + new].str.strip().eq("").sum()),
                            "normalized_missing_count": int(df[new].isna().sum())})
    save_csv(pd.DataFrame(missing), reports / "field_completeness.csv")
    duplicates = events.loc[events["same_pipe_day_multiple_events"]].sort_values(["related_asset_id", "incident_date", "event_id"])
    save_csv(duplicates, reports / "same_pipe_same_day_events.csv")
    save_csv(events.loc[events["unmatched_asset"]], reports / "unmatched_events.csv")
    save_csv(events.loc[events["event_before_install"]], reports / "event_before_install.csv")
    save_csv(assets.loc[assets["invalid_pipe_size"]], reports / "invalid_pipe_size.csv")
    save_csv(events.loc[events["related_asset_id"].eq("134292")], reports / "asset_134292_events.csv")
    save_csv(features.loc[features["asset_id"].eq("134292")], reports / "asset_134292_features.csv")
    groups = duplicates.groupby(["related_asset_id", "incident_day"]).ngroups
    eligible_duplicates = events.loc[events["eligible_same_pipe_day_multiple_events"]]
    eligible_groups = eligible_duplicates.groupby(["related_asset_id", "incident_day"]).ngroups
    reliable_duplicates = events.loc[events["reliable_event"]].copy()
    reliable_duplicates = reliable_duplicates.loc[reliable_duplicates.groupby(["related_asset_id", "incident_day"])["event_id"].transform("nunique").gt(1)]
    display_year = per_year.copy()
    display_year["positive_rate"] = display_year["positive_rate"].map(lambda v: f"{v:.4%}")
    selected = features.loc[features["asset_id"].eq("134292") & features["as_of_date"].dt.year.isin([2017, 2018, 2025]),
                            ["asset_id", "as_of_date", "past_break_count", "breaks_last_3y", "years_since_last_break", "break_next_12m"]]
    report = f"""# Water main risk data processing report

## Data and prediction definition

Only the two CSV files in manifest.json are used. The source files are unchanged; outputs/raw contains byte-for-byte copies.
The target is whether a current water main has a recorded, repaired break in the 12 calendar months after a prediction date. Eligible events must be MAIN and REPAIR COMPLETED, match a current asset ID, and occur no earlier than its current installation date.
A label of 0 means that no qualifying record matched the window. It does not prove that the pipe had no leak. This dataset does not assess whether a pipe is currently leaking.

An asset is included only when installation_date is strictly before as_of_date. History uses incident_date < as_of_date; the three-year window is [as_of_date - 3 years, as_of_date); the target uses [as_of_date, as_of_date + 12 months).
Events are aggregated by asset and prediction window before one-to-one joins. No event is arbitrarily selected with drop_duplicates.
Dates are parsed explicitly as month/day/year. Source timestamps remain timezone-naive and are not converted to UTC. source_row_number is a logical CSV record number that includes the header, not necessarily a physical line number when a quoted record spans lines.

## Import and event reconciliation

{markdown_table(pd.DataFrame([{k: m[k] for k in ['table', 'file_name', 'row_count', 'sha256']} for m in manifest['sources']]))}

{markdown_table(pd.DataFrame([{'metric': k, 'count': v} for k, v in rec.items() if k != 'dispositions']))}

{markdown_table(pd.DataFrame([{'disposition': k, 'count': v} for k, v in rec['dispositions'].items()]))}

The mutually exclusive event_disposition values cover every event; flags such as unmatched_asset are separate. The supplied baseline is 16,214/3,020/2,925/2,417/508/325. See validation_report.md for the check against each value.
There are {rec['reliable_events']} reliable events. Events from 2026 remain in the event table, but no 2026 samples or censored zero labels are produced.

## Data quality

{markdown_table(quality_summary)}

The quality table has one row per issue. A source record may have several issues, so issue_count is not a count of distinct problematic records. Interpret each count by table, issue_code, and field.
The unmatched_asset issue covers all {int(events['unmatched_asset'].sum())} unmatched events. The reconciliation count of {rec['eligible_unmatched']} includes only MAIN events with completed repairs. The difference is {int((events['unmatched_asset'] & ~events['eligible_event']).sum())} events outside the target scope.
Different event IDs on the same reported asset ID and calendar day: {groups} groups/{len(duplicates)} records across all events; {eligible_groups} groups/{len(eligible_duplicates)} records among eligible events; {reliable_duplicates.groupby(['related_asset_id', 'incident_day']).ngroups} groups/{len(reliable_duplicates)} records among reliable events. All remain available for review.
Same-day grouping uses the calendar day, even when timestamps differ. Different event IDs are not automatically classified as duplicates. Grouping uses the literal Related Asset ID; ID 0 appears to be a placeholder and does not establish a shared physical pipe.
unmatched_events.csv, event_before_install.csv, invalid_pipe_size.csv, and same_pipe_same_day_events.csv retain the original values and source record numbers.
field_completeness.csv gives raw blank and normalized missing counts for every field. A literal N/A is not silently treated as a blank on import.
PIPE_SIZE <= 0 makes the normalized diameter missing while retaining the asset and its annual records. -1 in CRITICALITY or Condition Score is treated as unknown.
Every nonblank Asset Size (cm) value is flagged for unresolved units and retained without centimetre conversion. Millimetres for PIPE_SIZE and metres for Shape__Length are inferred from MAP_LABEL and still need authoritative metadata.
Administrative status or service-restoration dates preceding an incident are flagged. They do not alter the incident date or establish when an event first became knowable.

## Model samples and a real-record spot check

{markdown_table(display_year)}

There are {len(features):,} asset-year samples. Splits use full years: train 2015-2021, validation 2022-2023, and test 2024-2025. An asset may appear in more than one year.
No prediction model was trained. Overall accuracy is not a suitable standalone measure for these rare break records. Later evaluations should report PR-AUC, precision/recall, recall at a chosen inspection budget, and probability calibration alongside annual base rates.

Asset 134292 (see asset_134292_*.csv for its complete source events and annual rows):

{markdown_table(selected)}

## Observation and timing limits

- This is a current asset snapshot. Historic pipes that were replaced, retired, split, merged, or renumbered may be absent. The {rec['eligible_unmatched']} unmatched eligible events cannot be assigned by guesswork. Pre-installation incidents may reflect replacements or reused IDs; excluding them can understate history.
- Current material, pipe_size, length_m, and pressure_zone are used in earlier years because there are no effective-date histories. These data describe retrospective samples of currently surviving assets, not a fully leakage-free historical backtest or the historic entire network.
- Current Condition Score, undated CLEANED, CRITICALITY, Shallow Main, Undersized, and LINED_DATE are excluded from the first model input set. Future event causes, repair methods, closures, and other outcomes are also excluded.
- History uses final repair status in this export. There is no complete status-change or entry log proving that an event was recorded and repaired as of each past prediction date. Status last updated date and UPDATE_DATE are not reliable first-availability times.
- The exclusive label observation cutoff is 2026-01-01, as requested. The latest event date is {events['incident_date'].max()}, but a latest record does not prove registry completeness. Calendar windows for 2015-2025 have elapsed; labels still depend on an unverified assumption that delayed reports and completed repairs are represented in this export.
- Early history may be left-censored. past_break_count=0 means no reliable earlier event was found in these files, not that the pipe never broke. years_since_last_break remains missing when no earlier record exists.
- Installation-date precision or defaults, authoritative length units and CRS, actual completion timing, and underreporting cannot be checked using only the two CSV files. No pressure-sensor, weather, or soil data were added.

## Deliverables and checks

The processed assets_standardized, events_standardized, and pipe_risk_features datasets are supplied as both CSV and Parquet. Parquet preserves date, numeric, and Boolean types; CSV contains ISO-formatted timestamp text.
model_contract.json specifies approved inputs, the target, identifiers, and year splits. schema.json lists all output fields, types, missing counts, and roles. field_mapping.csv records every source-field mapping.
See validation_report.md and validation_results.json for automated checks, independent recalculation of all event windows, boundary tests, and two-run comparison. See manual_review.md for the real-record manual spot check.
"""
    (reports / "data_report.md").write_text(report, encoding="utf-8")


def run_pipeline(input_dir: Path, output: Path, assets_path=None, events_path=None):
    input_dir, output = input_dir.resolve(), output.resolve()
    source_assets = find_source(input_dir, ASSET_FILE, assets_path)
    source_events = find_source(input_dir, EVENT_FILE, events_path)
    if source_assets == source_events:
        raise ValueError("Assets and events must be different files")
    for source in [source_assets, source_events]:
        if output == source.parent or output in source.parents:
            raise ValueError("Output directory must not contain the source files")
    ra, ma = import_source(source_assets, output / "raw", "assets")
    re_, me = import_source(source_events, output / "raw", "events")
    assets, events, quality = standardize(ra, re_, ma["file_name"], me["file_name"])
    features = build_features(assets, events)
    processed = output / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    dataframes = {"assets_standardized": assets, "events_standardized": events,
                  "data_quality_issues": quality, "pipe_risk_features": features}
    for name, df in dataframes.items():
        save_csv(df, processed / f"{name}.csv")
        df.to_parquet(processed / f"{name}.parquet", index=False, engine="pyarrow", compression="snappy")
    manifest = {"pipeline_version": "1.0.0", "sources": [ma, me],
                "observation_end_exclusive": "2026-01-01", "prediction_years": list(DEFAULT_YEARS),
                "event_date_min": str(events["incident_date"].min()), "event_date_max": str(events["incident_date"].max()),
                "observation_completeness": "calendar cutoff per task; source coverage/completeness not independently proven",
                "raw_files_unchanged": all(sha256(Path(m["source_path"])) == m["sha256"] for m in [ma, me])}
    save_json(manifest, output / "manifest.json")
    save_json({"identifiers": ["asset_id", "as_of_date"], "inputs": MODEL_INPUTS, "target": "break_next_12m",
               "split": "split", "split_years": {"train": list(range(2015, 2022)), "validation": [2022, 2023], "test": [2024, 2025]},
               "target_definition": "Any reliable recorded MAIN/REPAIR COMPLETED break in [as_of_date, as_of_date + 12 calendar months)",
               "zero_definition": "No matching eligible break record in window; NOT proven leak-free",
               "years_denominator_days": 365.2425,
               "prohibited_inputs": ["condition_score", "cleaned", "future event attributes", "target", "asset_id", "split"],
               "historical_snapshot_warning": "Current asset attributes and final repair status lack point-in-time histories"}, output / "model_contract.json")
    schema = {}
    for name, df in dataframes.items():
        schema[name] = [{"field": c, "dtype": str(df[c].dtype), "missing_count": int(df[c].isna().sum()),
                         "role": "raw_audit_only" if c.startswith("raw__") else
                         ("model_input" if name == "pipe_risk_features" and c in MODEL_INPUTS else
                          "target_not_input" if c == "break_next_12m" else "identifier_or_audit")}
                        for c in df.columns]
    save_json(schema, output / "schema.json")
    write_reports(output, assets, events, quality, features, manifest)
    output_hashes = {str(p.relative_to(output)).replace("\\", "/"): sha256(p) for p in sorted(output.rglob("*"))
                     if p.is_file() and (p.parent.name in ["raw", "processed"] or p.name in
                        ["manifest.json", "schema.json", "model_contract.json", "annual_summary.csv", "event_reconciliation.json", "field_mapping.csv", "field_completeness.csv", "data_quality_summary.csv", "data_report.md"])}
    save_json(output_hashes, output / "artifact_checksums.json")
    save_json({"executed_at_utc": datetime.now(timezone.utc).isoformat(),
               "note": "UTC only for job execution timestamp, not source incidents",
               "python": platform.python_version(), "pandas": pd.__version__, "numpy": np.__version__,
               "pyarrow": pyarrow.__version__, "interpreter": sys.executable,
               "pipeline_sha256": sha256(Path(__file__)), "output": str(output)}, output / "run_metadata.json")
    print(json.dumps({"output": str(output), **reconciliation(assets, events), "feature_rows": len(features)}, ensure_ascii=False))
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=HERE.parent / "DataSet")
    parser.add_argument("--output", type=Path, default=HERE / "outputs")
    parser.add_argument("--assets", help="Explicit assets file (optional)")
    parser.add_argument("--events", help="Explicit events file (optional)")
    args = parser.parse_args()
    run_pipeline(args.input_dir, args.output, args.assets, args.events)


if __name__ == "__main__":
    main()
