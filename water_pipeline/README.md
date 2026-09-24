# Annual water main break-risk data pipeline

This project reads only the two supplied CSV files. It produces traceable standardized tables, a record-level quality table, annual 2015-2025 modeling samples, and executed validation evidence. The target is whether a currently listed water main has a recorded MAIN break with REPAIR COMPLETED status within the next 12 calendar months. It does not assess a current leak. A zero label means no qualifying record matched that period; it does not establish that the pipe was leak-free.

## Run

From PowerShell in `D:\Datathon`, use the existing project environment:

```powershell
Set-Location 'D:\Datathon'
& '.\agentic-ai-workshop\.venv\Scripts\python.exe' '.\water_pipeline\pipeline.py'
& '.\agentic-ai-workshop\.venv\Scripts\python.exe' '.\water_pipeline\validate.py'
& '.\agentic-ai-workshop\.venv\Scripts\python.exe' -m unittest discover -s '.\water_pipeline\tests' -v
```

The tested environment uses Python 3.14.5, pandas 3.0.6, NumPy 2.5.3, and PyArrow 25.0.1. Exact runtime package versions are in `requirements.txt`. A separate environment can be created without changing the workshop application's dependencies:

```powershell
& '.\agentic-ai-workshop\.venv\Scripts\python.exe' -m venv '.\water_pipeline\.venv'
& '.\water_pipeline\.venv\Scripts\python.exe' -m pip install -r '.\water_pipeline\requirements.txt'
& '.\water_pipeline\.venv\Scripts\python.exe' '.\water_pipeline\pipeline.py'
& '.\water_pipeline\.venv\Scripts\python.exe' '.\water_pipeline\validate.py'
```

Installing dependencies needs a package source. Normal processing and validation use no external data or network service.

If this folder was unpacked separately, run the following from inside `water_pipeline` to rebuild from the included raw copies into a new output directory:

```powershell
python validate.py --input-dir '.\outputs\raw' --output '.\outputs_rebuilt'
```

That command runs the complete pipeline twice and verifies the results. The existing `outputs` directory contains this delivery's evidence. A manual record check must be repeated for a different source version; automated runs do not claim to redo human review.

## Inputs and version control

By default, the scripts search `D:\Datathon\DataSet` recursively for exactly one file of each type:

- `Water_Mains_5473643541506873803.csv`: current asset snapshot; numeric prefixes such as `02-` are accepted.
- `Water_Main_Breaks_-8394745777553033727.csv`: event records; numeric prefixes such as `01-` are accepted.

If multiple versions match, the run stops and requires explicit paths. `outputs/manifest.json` records actual file names, full source paths, row and column counts, file sizes, and SHA-256 checksums. Both Python's CSV parser and pandas count imported records, including records containing quoted line breaks.

The input directory, explicit source paths, and output location can be set with `--input-dir`, `--assets`, `--events`, and `--output`. For example:

```powershell
& '.\agentic-ai-workshop\.venv\Scripts\python.exe' '.\water_pipeline\pipeline.py' --input-dir 'D:\Datathon\DataSet' --output 'D:\Datathon\water_pipeline\outputs'
```

The original source files are never overwritten. `outputs/raw` contains byte-for-byte copies verified by SHA-256. If a raw copy in an existing output directory differs from the selected source, the run refuses to overwrite it; use a new `--output` for a new source version. Processed tables and reports are rebuilt rather than appended. `run_metadata.json` records each run's timestamp; deterministic tables and core reports can be compared by keys, values, and checksums.

## Output files

The default output directory is `D:\Datathon\water_pipeline\outputs`.

| Path | Contents |
| --- | --- |
| `raw/*.csv` | Byte-for-byte copies of the two source files |
| `manifest.json` | Import version, counts, source hashes, prediction years, and observation cutoff assumption |
| `processed/assets_standardized.csv` / `.parquet` | All current assets, standardized fields, original values, and quality flags |
| `processed/events_standardized.csv` / `.parquet` | All events, match flags, and mutually exclusive dispositions |
| `processed/data_quality_issues.csv` / `.parquet` | One row per issue, with source location, raw value, reason, and action |
| `processed/pipe_risk_features.csv` / `.parquet` | One row per `(asset_id, as_of_date)` |
| `reports/data_report.md` | Quality counts, event reconciliation, annual counts, and modeling limitations |
| `reports/validation_report.md` / `validation_results.json` | Executed checks and individual results from `validate.py` |
| `reports/rerun_comparison.json` | Two complete runs compared by checksums, table contents, and row counts |
| `reports/unit_tests.txt` | Executed unit-test results |
| `reports/manual_review.md` | A separate manual spot check of real source records and model rows |
| `reports/independent_source_audit.json` | Independent standard-library audit of the original CSV files |
| `reports/event_reconciliation.json` | Event selection, matching, installation conflicts, and reliable-event count |
| `reports/data_quality_summary.csv` | Counts by table, issue type, and field |
| `reports/field_completeness.csv` | Raw blanks and normalized missing values for every source field |
| `reports/field_mapping.csv` | Every original field's standardized and `raw__` name, type, and rule |
| `reports/annual_summary.csv` | Split, sample count, positive count, and positive rate by year |
| `reports/unmatched_events.csv` | All unmatched events, including events outside the target scope |
| `reports/event_before_install.csv` | All matched events with incidents before current installation |
| `reports/invalid_pipe_size.csv` | Assets with invalid diameter and their original values |
| `reports/same_pipe_same_day_events.csv` | Distinct event IDs with the same reported asset ID and day across all events |
| `reports/asset_134292_events.csv` / `asset_134292_features.csv` | Real-asset event and annual-sample spot-check records |
| `model_contract.json` | Approved model inputs, target, identifiers, and full-year splits |
| `schema.json` | Output field names, types, missing counts, and roles |
| `artifact_checksums.json` | SHA-256 values for raw copies, processed data, and core reports |
| `run_metadata.json` | Run time, interpreter and package versions, and pipeline script hash |

Generated CSV files use UTF-8 with a BOM for spreadsheet compatibility. Dates are ISO-formatted text without a timezone. CSV does not retain date, numeric, or Boolean types; use Parquet for modeling. Source IDs are read as strings so leading zeros and other identifier text are not treated as numbers.

```python
import json
from pathlib import Path
import pandas as pd

out = Path("water_pipeline/outputs")
data = pd.read_parquet(out / "processed/pipe_risk_features.parquet")
contract = json.loads((out / "model_contract.json").read_text(encoding="utf-8"))
train = data.loc[data[contract["split"]].eq("train")]
X_train = train[contract["inputs"]]
y_train = train[contract["target"]]
```

Always use `model_contract.json` as the feature allowlist. Asset IDs, prediction dates, splits, and the target are not direct model inputs in this version. Any imputation, encoding, or scaling for a later model must be fitted using training years only.

## Processing rules

1. Join `Related Asset ID` to `WATMAINID`. `Wat Break Incident ID` identifies events. The two tables' `OBJECTID` values are kept only for source auditing.
2. Restrict history and target calculations to MAIN events with REPAIR COMPLETED status, then exclude events without reliable keys, dates, unique matching assets, or incidents on or after current installation. Keep every source event in the standardized table.
3. Create samples on January 1 for installed current assets only (`installation_date < as_of_date`). `PIPE_SIZE <= 0` becomes missing without removing the asset or its annual samples.
4. History uses `incident_date < as_of_date`; the recent-history window is `[as_of_date - 3 calendar years, as_of_date)`; the target window is `[as_of_date, as_of_date + 12 calendar months)`. Aggregate by asset and window before one-to-one joins.
5. The default exclusive observation cutoff is `2026-01-01`; no 2026 samples or partially observed zero labels are made.
6. With no recorded reliable history, `past_break_count`, `breaks_last_3y`, and `had_prior_break` are zero, while `years_since_last_break` remains missing.
7. Distinct event IDs with the same reported asset ID and calendar day are retained and listed for review. `Related Asset ID = 0` is flagged as a suspected placeholder; shared zero values do not establish a shared physical pipe.
8. Splits use whole years: train 2015-2021, validation 2022-2023, and test 2024-2025. An asset can appear in several years. There is no random split of asset-year rows.

See [DATA_DICTIONARY.md](DATA_DICTIONARY.md) for field definitions, flags, units, and missing-value rules.

## Validation and interpretation

`validate.py` accepts the same input/output options as the pipeline. It runs the pipeline twice, verifies that source bytes are unchanged, reconciles source and output counts, checks IDs and dates, independently recalculates every feature row, checks asset 134292, compares reruns, checks year splits, and runs unit tests. Synthetic dates test exact prediction-day, next-year, and three-year boundaries; test fixtures never enter the delivered datasets.

The supplied reference counts are 16,214 assets and 3,020 events, with 2,925 MAIN/completed events, 2,417 matched, 508 unmatched, and 325 matched incidents before installation. The pipeline recalculates these counts and reports differences if a source version changes. Repairable quality issues are marked and handled while usable outputs continue to be produced.

No prediction model was fitted. `annual_summary.csv` reports positive rates by year. Later model evaluation should include PR-AUC, precision and recall, recall at a specified inspection budget, and calibration, with annual base rates for context.

## Limits of these two CSV files

- This is a retrospective dataset of currently listed assets. Older pipes that were replaced, retired, split, merged, or renumbered may be absent. Unmatched incidents cannot be assigned to current assets without a relationship history. Excluding pre-installation incidents avoids obvious conflicts but may omit earlier physical-pipe history.
- Current material, diameter, length, and pressure zone have no effective dates. Using them for past predictions cannot establish their historical values. This is not a fully leakage-free historical backtest.
- Current Condition Score, undated CLEANED, CRITICALITY, Shallow Main, Undersized, lining fields, and future event causes, repairs, and closures are excluded from first-version model inputs.
- Completed repair is the final status in this export. Complete status-change and entry logs are unavailable, so whether an event was already recorded and completed at each past prediction date cannot be verified.
- Calendar target windows for 2015-2025 have elapsed, but the latest event date does not prove complete historical reporting or inclusion of late reports and delayed closures. The 2025 label depends on an unverified registry-completeness assumption.
- Earlier history may be left-censored. A history count of zero means no matching reliable earlier record in these files. A target of zero means no qualifying record in the target window; neither proves no break or leak ever occurred.
- Source timezone is unspecified. Incident and installation timestamps remain timezone-naive and are never converted to UTC. Only the job-execution timestamp uses UTC.
- Millimetres for PIPE_SIZE and metres for Shape__Length are inferred from MAP_LABEL and need authoritative confirmation. The event field `Asset Size (cm)` has unresolved units; its reported numeric value is kept without conversion and is excluded from the model.
- No pressure-sensor, weather, or soil data were invented or added. `Depth of Frost (m)` is only a field already present in the supplied incident CSV.
