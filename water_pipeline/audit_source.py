"""Independent, read-only stdlib audit of the two water source CSVs.

Run: python water_pipeline/audit_source.py
No source files or pipeline artifacts are modified.
"""
from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = {
    "assets": ROOT / "DataSet" / "Water_Mains_5473643541506873803.csv",
    "events": ROOT / "DataSet" / "Water_Main_Breaks_-8394745777553033727.csv",
}


def date(value):
    return datetime.strptime(value, "%m/%d/%Y %I:%M:%S %p") if value.strip() else None


def norm(value):
    return value.strip().upper()


def audit():
    sources = {}
    tables = {}
    for name, path in FILES.items():
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            tables[name] = list(reader)
            sources[name] = {
                "file": path.name,
                "rows": len(tables[name]),
                "columns": reader.fieldnames,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
    assets, events = tables["assets"], tables["events"]
    report = {"sources": sources}
    for name, rows, key in (("assets", assets, "WATMAINID"), ("events", events, "Wat Break Incident ID")):
        ids = Counter(r[key].strip() for r in rows)
        report[name + "_ids"] = {
            "missing": ids.get("", 0),
            "duplicate_ids": {k: n for k, n in ids.items() if n > 1},
        }
    dates = {}
    for name, columns in (("assets", ["INSTALLATION_DATE", "LINED_DATE"]), ("events", ["Incident date", "Status last updated date", "Date operations was returned to normal service", "UPDATE_DATE"])):
        for column in columns:
            parsed, failures = [], []
            for n, row in enumerate(tables[name], 2):
                try:
                    parsed.append(date(row[column]))
                except ValueError:
                    failures.append({"row": n, "value": row[column]})
            nonempty = [x for x in parsed if x is not None]
            dates[name + "." + column] = {
                "missing": sum(x is None for x in parsed),
                "parse_failures": failures,
                "min": min(nonempty).isoformat() if nonempty else None,
                "max": max(nonempty).isoformat() if nonempty else None,
            }
    report["dates"] = dates
    report["asset_statuses"] = dict(Counter(r["STATUS"] for r in assets))
    report["asset_missing_fields"] = {k: sum(not r[k].strip() for r in assets) for k in sources["assets"]["columns"]}
    report["invalid_pipe_size"] = [{"asset_id": r["WATMAINID"], "pipe_size": r["PIPE_SIZE"]} for r in assets if not r["PIPE_SIZE"].strip() or float(r["PIPE_SIZE"]) <= 0]
    report["default_minus_one"] = {k: sum(r[k].strip() == "-1" for r in assets) for k in ("CRITICALITY", "Condition Score")}
    report["event_type_status"] = [{"asset_type": k[0], "status": k[1], "count": n} for k, n in Counter((norm(r["Type of Asset Broken"]), norm(r["Current status of the break"])) for r in events).items()]
    by_asset = {r["WATMAINID"].strip(): r for r in assets}
    eligible = [r for r in events if norm(r["Type of Asset Broken"]) == "MAIN" and norm(r["Current status of the break"]) == "REPAIR COMPLETED"]
    matched = [r for r in eligible if r["Related Asset ID"].strip() in by_asset]
    unmatched = [r for r in eligible if r["Related Asset ID"].strip() not in by_asset]
    conflicts = [r for r in matched if date(r["Incident date"]) < date(by_asset[r["Related Asset ID"].strip()]["INSTALLATION_DATE"])]
    conflict_ids = {r["Wat Break Incident ID"] for r in conflicts}
    reliable = [r for r in matched if r["Wat Break Incident ID"] not in conflict_ids]
    report["event_reconciliation"] = {"total": len(events), "main_repair_completed": len(eligible), "matched": len(matched), "unmatched": len(unmatched), "before_install": len(conflicts), "reliable": len(reliable)}
    report["additional_quality"] = {
        "eligible_related_asset_id_zero": sum(r["Related Asset ID"].strip() == "0" for r in eligible),
        "eligible_related_asset_id_missing": sum(not r["Related Asset ID"].strip() for r in eligible),
        "matched_size_nonmissing": sum(bool(r["Asset Size (cm)"].strip()) for r in matched),
        "matched_size_same_numeric_value": sum(bool(r["Asset Size (cm)"].strip()) and float(r["Asset Size (cm)"]) == float(by_asset[r["Related Asset ID"].strip()]["PIPE_SIZE"]) for r in matched),
        "asset_material_counts": dict(Counter(r["MATERIAL"] for r in assets)),
        "asset_pressure_zone_counts": dict(Counter(r["PRESSURE_ZONE"] for r in assets)),
        "asset_nonpositive_length": [{"asset_id": r["WATMAINID"], "value": r["Shape__Length"]} for r in assets if float(r["Shape__Length"]) <= 0],
        "month_day_format_evidence": next(r["Incident date"] for r in events if int(r["Incident date"].split("/")[1]) > 12),
    }
    report["before_install_examples"] = [{"event_id": r["Wat Break Incident ID"], "asset_id": r["Related Asset ID"], "incident": r["Incident date"], "install": by_asset[r["Related Asset ID"].strip()]["INSTALLATION_DATE"]} for r in conflicts[:5]]
    for label, rows in (("all", events), ("eligible", eligible), ("reliable", reliable)):
        groups = defaultdict(list)
        for r in rows:
            groups[(r["Related Asset ID"].strip(), date(r["Incident date"]).date().isoformat())].append(r["Wat Break Incident ID"])
        repeated = [{"asset_id": k[0], "date": k[1], "event_ids": ids} for k, ids in groups.items() if k[0] and len(set(ids)) > 1]
        report["same_asset_day_" + label] = {"groups": len(repeated), "rows": sum(len(x["event_ids"]) for x in repeated), "examples": repeated[:10]}
    report["reliable_event_years"] = dict(sorted(Counter(date(r["Incident date"]).year for r in reliable).items()))
    report["completion_date_anomalies"] = {}
    for column in ("Status last updated date", "Date operations was returned to normal service", "UPDATE_DATE"):
        bad = [r for r in eligible if date(r[column]) is not None and date(r[column]) < date(r["Incident date"])]
        report["completion_date_anomalies"][column] = {"count": len(bad), "examples": [{"event_id": r["Wat Break Incident ID"], "incident": r["Incident date"], "value": r[column]} for r in bad[:5]]}
    target_asset = "134292"
    report["asset_134292"] = by_asset[target_asset]
    report["events_134292"] = [r for r in events if r["Related Asset ID"].strip() == target_asset]
    target_history = sorted(date(r["Incident date"]) for r in reliable if r["Related Asset ID"].strip() == target_asset)
    as_of = datetime(2025, 1, 1)
    past = [x for x in target_history if x < as_of]
    report["features_134292_2025"] = {
        "age_years": (as_of - date(by_asset[target_asset]["INSTALLATION_DATE"])).total_seconds() / (365.2425 * 86400),
        "past_break_count": len(past),
        "breaks_last_3y": sum(datetime(2022, 1, 1) <= x < as_of for x in target_history),
        "years_since_last_break": (as_of - max(past)).total_seconds() / (365.2425 * 86400) if past else None,
        "break_next_12m": int(any(as_of <= x < datetime(2026, 1, 1) for x in target_history)),
        "past_dates": [x.isoformat() for x in past],
        "target_dates": [x.isoformat() for x in target_history if as_of <= x < datetime(2026, 1, 1)],
    }
    annual = []
    for year in range(2015, 2026):
        as_of, end = datetime(year, 1, 1), datetime(year + 1, 1, 1)
        known_assets = {r["WATMAINID"].strip() for r in assets if date(r["INSTALLATION_DATE"]) < as_of}
        positives = {r["Related Asset ID"].strip() for r in reliable if r["Related Asset ID"].strip() in known_assets and as_of <= date(r["Incident date"]) < end}
        annual.append({"year": year, "n": len(known_assets), "positives": len(positives), "rate": len(positives) / len(known_assets)})
    report["annual"] = annual
    report["midnight_jan1_events"] = [{"event_id": r["Wat Break Incident ID"], "asset_id": r["Related Asset ID"], "incident": r["Incident date"]} for r in reliable if (date(r["Incident date"]).month, date(r["Incident date"]).day, date(r["Incident date"]).hour, date(r["Incident date"]).minute, date(r["Incident date"]).second) == (1, 1, 0, 0, 0)]
    return report


if __name__ == "__main__":
    print(json.dumps(audit(), indent=2, ensure_ascii=False))
