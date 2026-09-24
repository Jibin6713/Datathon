# Water main risk data processing report

## Data and prediction definition

Only the two CSV files in manifest.json are used. The source files are unchanged; outputs/raw contains byte-for-byte copies.
The target is whether a current water main has a recorded, repaired break in the 12 calendar months after a prediction date. Eligible events must be MAIN and REPAIR COMPLETED, match a current asset ID, and occur no earlier than its current installation date.
A label of 0 means that no qualifying record matched the window. It does not prove that the pipe had no leak. This dataset does not assess whether a pipe is currently leaking.

An asset is included only when installation_date is strictly before as_of_date. History uses incident_date < as_of_date; the three-year window is [as_of_date - 3 years, as_of_date); the target uses [as_of_date, as_of_date + 12 months).
Events are aggregated by asset and prediction window before one-to-one joins. No event is arbitrarily selected with drop_duplicates.
Dates are parsed explicitly as month/day/year. Source timestamps remain timezone-naive and are not converted to UTC. source_row_number is a logical CSV record number that includes the header, not necessarily a physical line number when a quoted record spans lines.

## Import and event reconciliation

| table | file_name | row_count | sha256 |
| --- | --- | --- | --- |
| assets | Water_Mains_5473643541506873803.csv | 16214 | b369f143b345002805cf6ee15c59b5576d1fd09fd86d7246e0369d020d68bc03 |
| events | Water_Main_Breaks_-8394745777553033727.csv | 3020 | d6367b4234d22462e62f0c567a210fc4a23b10e068d31996645a1e24ac8d2d04 |

| metric | count |
| --- | --- |
| assets | 16214 |
| events | 3020 |
| eligible_main_completed | 2925 |
| eligible_matched | 2417 |
| eligible_unmatched | 508 |
| eligible_ambiguous | 0 |
| eligible_event_before_install | 325 |
| reliable_events | 2092 |

| disposition | count |
| --- | --- |
| event_before_install | 325 |
| not_main | 76 |
| reliable_event | 2092 |
| repair_not_completed | 19 |
| unmatched_asset | 508 |

The mutually exclusive event_disposition values cover every event; flags such as unmatched_asset are separate. The supplied baseline is 16,214/3,020/2,925/2,417/508/325. See validation_report.md for the check against each value.
There are 2092 reliable events. Events from 2026 remain in the event table, but no 2026 samples or censored zero labels are produced.

## Data quality

| table | issue_code | field | issue_count | affected_records |
| --- | --- | --- | --- | --- |
| assets | default_minus_one | condition_score | 484 | 484 |
| assets | default_minus_one | criticality | 3049 | 3049 |
| assets | invalid_pipe_size | pipe_size | 2 | 2 |
| assets | lined_date_missing | lined_date | 4 | 4 |
| assets | unknown_material | material | 1 | 1 |
| events | asset_size_unit_unverified | asset_size_reported | 2697 | 2697 |
| events | event_before_install | incident_date | 325 | 325 |
| events | normal_service_date_before_incident | normal_service_date | 2 | 2 |
| events | placeholder_related_asset_id | related_asset_id | 13 | 13 |
| events | same_pipe_same_day_multiple_events | incident_date | 53 | 53 |
| events | unmatched_asset | related_asset_id | 589 | 589 |

The quality table has one row per issue. A source record may have several issues, so issue_count is not a count of distinct problematic records. Interpret each count by table, issue_code, and field.
The unmatched_asset issue covers all 589 unmatched events. The reconciliation count of 508 includes only MAIN events with completed repairs. The difference is 81 events outside the target scope.
Different event IDs on the same reported asset ID and calendar day: 23 groups/53 records across all events; 18 groups/41 records among eligible events; 9 groups/18 records among reliable events. All remain available for review.
Same-day grouping uses the calendar day, even when timestamps differ. Different event IDs are not automatically classified as duplicates. Grouping uses the literal Related Asset ID; ID 0 appears to be a placeholder and does not establish a shared physical pipe.
unmatched_events.csv, event_before_install.csv, invalid_pipe_size.csv, and same_pipe_same_day_events.csv retain the original values and source record numbers.
field_completeness.csv gives raw blank and normalized missing counts for every field. A literal N/A is not silently treated as a blank on import.
PIPE_SIZE <= 0 makes the normalized diameter missing while retaining the asset and its annual records. -1 in CRITICALITY or Condition Score is treated as unknown.
Every nonblank Asset Size (cm) value is flagged for unresolved units and retained without centimetre conversion. Millimetres for PIPE_SIZE and metres for Shape__Length are inferred from MAP_LABEL and still need authoritative metadata.
Administrative status or service-restoration dates preceding an incident are flagged. They do not alter the incident date or establish when an event first became knowable.

## Model samples and a real-record spot check

| year | split | sample_count | positive_count | positive_rate |
| --- | --- | --- | --- | --- |
| 2015 | train | 12669 | 91 | 0.7183% |
| 2016 | train | 12996 | 53 | 0.4078% |
| 2017 | train | 13231 | 64 | 0.4837% |
| 2018 | train | 13701 | 76 | 0.5547% |
| 2019 | train | 13993 | 67 | 0.4788% |
| 2020 | train | 14827 | 51 | 0.3440% |
| 2021 | train | 15218 | 66 | 0.4337% |
| 2022 | validation | 15504 | 79 | 0.5095% |
| 2023 | validation | 15792 | 40 | 0.2533% |
| 2024 | test | 15961 | 48 | 0.3007% |
| 2025 | test | 16102 | 70 | 0.4347% |

There are 159,994 asset-year samples. Splits use full years: train 2015-2021, validation 2022-2023, and test 2024-2025. An asset may appear in more than one year.
No prediction model was trained. Overall accuracy is not a suitable standalone measure for these rare break records. Later evaluations should report PR-AUC, precision/recall, recall at a chosen inspection budget, and probability calibration alongside annual base rates.

Asset 134292 (see asset_134292_*.csv for its complete source events and annual rows):

| asset_id | as_of_date | past_break_count | breaks_last_3y | years_since_last_break | break_next_12m |
| --- | --- | --- | --- | --- | --- |
| 134292 | 2017-01-01 00:00:00 | 0 | 0 |  | 1 |
| 134292 | 2018-01-01 00:00:00 | 1 | 1 | 0.08313540547261979 | 0 |
| 134292 | 2025-01-01 00:00:00 | 1 | 0 | 7.0839636223422335 | 1 |

## Observation and timing limits

- This is a current asset snapshot. Historic pipes that were replaced, retired, split, merged, or renumbered may be absent. The 508 unmatched eligible events cannot be assigned by guesswork. Pre-installation incidents may reflect replacements or reused IDs; excluding them can understate history.
- Current material, pipe_size, length_m, and pressure_zone are used in earlier years because there are no effective-date histories. These data describe retrospective samples of currently surviving assets, not a fully leakage-free historical backtest or the historic entire network.
- Current Condition Score, undated CLEANED, CRITICALITY, Shallow Main, Undersized, and LINED_DATE are excluded from the first model input set. Future event causes, repair methods, closures, and other outcomes are also excluded.
- History uses final repair status in this export. There is no complete status-change or entry log proving that an event was recorded and repaired as of each past prediction date. Status last updated date and UPDATE_DATE are not reliable first-availability times.
- The exclusive label observation cutoff is 2026-01-01, as requested. The latest event date is 2026-09-19 18:25:59, but a latest record does not prove registry completeness. Calendar windows for 2015-2025 have elapsed; labels still depend on an unverified assumption that delayed reports and completed repairs are represented in this export.
- Early history may be left-censored. past_break_count=0 means no reliable earlier event was found in these files, not that the pipe never broke. years_since_last_break remains missing when no earlier record exists.
- Installation-date precision or defaults, authoritative length units and CRS, actual completion timing, and underreporting cannot be checked using only the two CSV files. No pressure-sensor, weather, or soil data were added.

## Deliverables and checks

The processed assets_standardized, events_standardized, and pipe_risk_features datasets are supplied as both CSV and Parquet. Parquet preserves date, numeric, and Boolean types; CSV contains ISO-formatted timestamp text.
model_contract.json specifies approved inputs, the target, identifiers, and year splits. schema.json lists all output fields, types, missing counts, and roles. field_mapping.csv records every source-field mapping.
See validation_report.md and validation_results.json for automated checks, independent recalculation of all event windows, boundary tests, and two-run comparison. See manual_review.md for the real-record manual spot check.
