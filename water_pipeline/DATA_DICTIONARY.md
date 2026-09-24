# Fields and calculation rules

This document describes the processing rules. `outputs/schema.json` contains the complete field types and missing-value counts from this run. The machine-readable mapping for **all 64 source fields** is `outputs/reports/field_mapping.csv`, with `table`, `original_field`, `normalized_field`, `raw_field`, `dtype`, and `rule` columns.

## Shared conventions

- Source fields are imported as strings, including the literal value `N/A`. Standardized strings are generally stripped of surrounding whitespace; an empty standardized string becomes missing.
- Every original field is also saved as `raw__<normalized_field>` with its original cell text. The untouched `raw/*.csv` files remain the byte-level source evidence.
- `source_file` is the source CSV name. `source_row_number` starts at `2` because the header counts as record 1. It is a **logical CSV record number**, which may differ from a physical text line when quoted fields contain line breaks.
- IDs remain strings. `source_object_id` is the table's original `OBJECTID` and is used only for auditing; it is never a cross-table join key.
- Dates are parsed with `%m/%d/%Y %I:%M:%S %p` (month/day/year, 12-hour clock, AM/PM). They remain timezone-naive. A nonempty invalid date becomes missing and receives a quality issue.
- Designated numeric fields become nullable numbers. Nonempty invalid numeric values become missing, with the original value retained for auditing. Unknown values are not silently imputed.
- Parquet preserves timestamp, numeric, integer, string, and Boolean types. CSV is text; missing values appear as empty cells. Prefer Parquet for modeling.

## `pipe_risk_features`

Each row represents a currently listed asset at one prediction date. `(asset_id, as_of_date)` is the composite key. An asset needs a unique nonmissing ID, a parseable installation date, and `installation_date < as_of_date`.

| Field | Type and unit | Rule and missing-value meaning | Role |
| --- | --- | --- | --- |
| `asset_id` | String | Original `WATMAINID`; never treated as a continuous number | Identifier |
| `as_of_date` | Timezone-naive timestamp | January 1 at midnight in each year 2015-2025 | Time identifier |
| `age_years` | Decimal years | Actual elapsed seconds since installation divided by `365.2425 × 86400`; not simple integer-year subtraction | Model input |
| `material` | String/category | Current `MATERIAL`, trimmed and uppercased; explicit unknown placeholders `XXX`, `UNKNOWN`, `UNK`, and `N/A` become missing | Model input |
| `pipe_size` | Nullable number; inferred mm | Current `PIPE_SIZE`; `<= 0` becomes missing without deleting the asset. Millimetres are inferred from `MAP_LABEL`, not independently confirmed | Model input |
| `length_m` | Nullable number; inferred m | Current `Shape__Length`; `<= 0` becomes missing. Metres are inferred from `MAP_LABEL`; geometry/CRS metadata are unavailable | Model input |
| `pressure_zone` | String/category | Current `PRESSURE_ZONE`, trimmed and uppercased; blank becomes missing | Model input |
| `past_break_count` | Nonnegative integer | Number of reliable events with `incident_date < as_of_date`; zero means no matching earlier record | Model input |
| `breaks_last_3y` | Nonnegative integer | Reliable events in `[as_of_date - 3 calendar years, as_of_date)`; zero means no matching record in that window | Model input |
| `years_since_last_break` | Nullable decimal years | Time since the most recent strictly prior reliable event, using actual elapsed seconds divided by `365.2425 × 86400`; missing when no prior record exists | Model input |
| `had_prior_break` | Integer 0/1 | One when `past_break_count > 0`, otherwise zero | Model input / display |
| `break_next_12m` | Integer 0/1 | One when at least one reliable event falls in `[as_of_date, as_of_date + 12 calendar months)`; zero means no qualifying matched record | **Target; never an input** |
| `split` | String | `train`: 2015-2021; `validation`: 2022-2023; `test`: 2024-2025 | Partition; never an input |

Reliable events are defined below. Event counts use distinct source event records rather than deduplicating dates. Different event IDs on the same asset and day remain counted and are flagged for review. Events are aggregated by asset and time window before one-to-one joins to the annual asset rows. An event exactly on `as_of_date` enters the future target, not history. An event exactly on the next year's `as_of_date` is excluded from the prior year's target.

The default exclusive observation cutoff is `2026-01-01`. A prediction year is generated only if its complete 12-calendar-month target window ends no later than that cutoff. The elapsed calendar period does not prove that the source registry is complete.

Only the nine fields designated **Model input** above are approved for the first model version; use the `inputs` array in `model_contract.json`. Identifiers, splits, current condition or cleaning fields, and future event outcome fields must not enter the model by accident.

## `assets_standardized`: source-field mapping

In addition to shared conventions, `material`, `status`, and `pressure_zone` are uppercased. Other fields without a specified numeric/date type stay as standardized strings. Every field has a corresponding `raw__` field.

| Original field | Standardized field | Meaning or special rule |
| --- | --- | --- |
| `OBJECTID` | `source_object_id` | Source-table object number, audit only |
| `WATMAINID` | `asset_id` | Current asset key and event join target; string |
| `STATUS` | `status` | Current status; no extra status filter on the current assets |
| `PRESSURE_ZONE` | `pressure_zone` | Current pressure zone |
| `ROADSEGMENTID` | `road_segment_id` | Road-segment identifier, string |
| `MAP_LABEL` | `map_label` | Original map label, available to review unit inference |
| `CATEGORY` | `category` | Original asset category |
| `PIPE_SIZE` | `pipe_size` | Numeric; `<= 0` becomes missing; unit inferred as mm |
| `MATERIAL` | `material` | Material code; explicit unknown placeholders become missing |
| `LINED` | `lined` | Original lining flag; not a historical model input |
| `LINED_DATE` | `lined_date` | Timezone-naive lining date; not used as a first-version input |
| `LINED_MATERIAL` | `lined_material` | Original lining material; not a first-version input |
| `INSTALLATION_DATE` | `installation_date` | Timezone-naive date used for eligibility, age, and incident-installation conflict checks |
| `ACQUISITION` | `acquisition` | Original acquisition text or code |
| `CONSULTANT` | `consultant` | Original consultant field |
| `OWNERSHIP` | `ownership` | Original ownership field |
| `BRIDGE_MAIN` | `bridge_main` | Original bridge-main flag |
| `BRIDGE_DETAILS` | `bridge_details` | Original bridge details |
| `CRITICALITY` | `criticality` | Numeric; `-1` means unknown/default and becomes missing; not a first-version input |
| `REL_CLEANING_AREA` | `rel_cleaning_area` | Original cleaning-area code |
| `REL_CLEANING_SUBAREA` | `rel_cleaning_subarea` | Original cleaning-subarea code |
| `Undersized` | `undersized` | Current flag; not a first-version input |
| `Shallow Main` | `shallow_main` | Current flag; not a first-version input |
| `Condition Score` | `condition_score` | Numeric; `-1` means unknown/default and becomes missing; current value is excluded from historical inputs |
| `OVERSIZED` | `oversized` | Current flag; not a first-version input |
| `CLEANED` | `cleaned` | Current cleaning flag without an event date; excluded from historical inputs |
| `Shape__Length` | `length_m` | Numeric; `<= 0` becomes missing; unit inferred as m |

Additional asset audit fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `source_file`, `source_row_number` | String, integer | Source and logical CSV record number |
| `raw__*` | String | Original text for every source field |
| `invalid_primary_key` | Boolean | `asset_id` is missing or duplicated; every row in a duplicate group is retained and excluded from modeling |
| `invalid_pipe_size` | Boolean | A numeric `PIPE_SIZE <= 0`; excludes raw blanks and numeric parse failures |
| `model_asset_eligible` | Boolean | Asset ID is valid and installation date parses; eligibility at a particular prediction date is checked separately |

## `events_standardized`: source-field mapping

`asset_type`, `break_status`, and `asset_material` are uppercased. Causes, repairs, closures, and other event outcomes are retained for auditing only and never enter historical model inputs.

| Original field | Standardized field | Meaning or special rule |
| --- | --- | --- |
| `OBJECTID` | `source_object_id` | Source-table object number; not a join key |
| `Wat Break Incident ID` | `event_id` | Event key, string |
| `Incident date` | `incident_date` | Timezone-naive incident timestamp used for all history and target windows |
| `Type of Asset Broken` | `asset_type` | Only MAIN qualifies for reliable history and targets |
| `Does the road need to be closed?` | `road_closure` | Closure information, audit only |
| `Does the sidewalk need to be closed?` | `sidewalk_closure` | Sidewalk closure, audit only |
| `Estimated Hours for Repair` | `estimated_repair_hours` | Text may contain ranges or words; retained without numeric inference |
| `Estimated Number of Units Impacted` | `estimated_units_impacted` | Original values often are ranges; retained as strings, not forced to a single number |
| `CW Service Request Number` | `cw_service_request_number` | Service-request identifier, string |
| `Current status of the break` | `break_status` | Current repair status; only REPAIR COMPLETED qualifies |
| `Status last updated date` | `status_updated_date` | Timezone-naive administrative date; not a substitute for incident or first-availability time |
| `CW Workorder #` | `cw_workorder_number` | Work-order identifier, string |
| `Date operations was returned to normal service` | `normal_service_date` | Timezone-naive service-restoration date, audit only |
| `Nature of Break` | `break_nature` | Break description, audit only |
| `Apparent cause of break` | `break_cause` | Reported apparent cause, audit only |
| `Repair Type` | `repair_type` | Reported repair method, audit only |
| `Type of Planned Maintenance` | `planned_maintenance_type` | Original planned-maintenance type, audit only |
| `List Valves Closed` | `valves_closed` | Original list text |
| `List Valves Opened` | `valves_opened` | Original list text |
| `List Hydrants Called Out` | `hydrants_called_out` | Original list text |
| `List Hydrants Called Back In` | `hydrants_called_back_in` | Original list text |
| `Categorization of the Break` | `break_category` | Original break category |
| `Road Segment ID` | `road_segment_id` | Road identifier, string |
| `Closest Civic Number` | `closest_civic_number` | Address number, string |
| `Street` | `street` | Original street text |
| `Related Asset ID` | `related_asset_id` | Exact string match to asset `asset_id`; no guessed assignment |
| `Related Asset Depth (m)` | `asset_depth_m` | Nullable number; source header says m, audit only |
| `Depth of Frost (m)` | `frost_depth_m` | Nullable number from the supplied incident CSV; no outside soil data were added |
| `Asset Size (cm)` | `asset_size_reported` | Nullable number with unresolved unit; **keep reported numeric value without centimetre conversion**; not a model input |
| `Year Asset Installed` | `reported_installation_year` | Nullable value reported in the event table; does not replace current asset installation date |
| `Asset Material` | `asset_material` | Event-reported material; does not replace current asset material |
| `Asset Exists` | `asset_exists` | Original flag; match status is calculated from IDs, not guessed from this flag |
| `GLOBALID` | `global_id` | Original global identifier, string |
| `UPDATE_BY` | `update_by` | Original update account or person, source audit only |
| `UPDATE_DATE` | `update_date` | Timezone-naive update time, not proof of first event availability |
| `x` | `x` | Nullable coordinate number; CRS unconfirmed, never used to guess an asset match |
| `y` | `y` | Nullable coordinate number; CRS unconfirmed, never used to guess an asset match |

Additional event audit and calculated fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `source_file`, `source_row_number`, `raw__*` | As for assets | Source and all original values |
| `invalid_primary_key` | Boolean | Missing or duplicated `event_id`; retain all rows but exclude affected events from reliable history |
| `eligible_event` | Boolean | MAIN with REPAIR COMPLETED; matching and dates have not yet been checked |
| `placeholder_related_asset_id` | Boolean | `related_asset_id == "0"`; suspected placeholder, kept without guessing a physical asset |
| `matched_asset` | Boolean | Related ID matches one unique, valid current asset key |
| `ambiguous_asset` | Boolean | Related ID occurs on more than one asset row and cannot identify one pipe |
| `unmatched_asset` | Boolean | Neither a unique match nor an ambiguous duplicate; retain the event without guessed assignment |
| `matched_installation_date` | Timezone-naive timestamp | Current installation date from the unique asset match; missing if no match or invalid source date |
| `event_before_install` | Boolean | Matched incident predates current installation; calculated independently of asset type and repair status |
| `reliable_event` | Boolean | Eligible event with valid unique event ID, unique asset match, parseable incident/installation dates, and incident no earlier than installation |
| `event_disposition` | String | One exclusive disposition per imported event; see below |
| `incident_day` | Timezone-naive timestamp | Incident date normalized to midnight for same-day review only |
| `same_pipe_day_event_count` | Integer | Distinct nonmissing event IDs on the same reported asset ID and day across all events; zero if grouping is unavailable |
| `same_pipe_day_multiple_events` | Boolean | The preceding all-event count is greater than one; does not trigger automatic deduplication |
| `eligible_same_pipe_day_event_count` | Integer | Distinct event IDs on the same reported asset ID and day among MAIN/completed events only; zero outside that scope |
| `eligible_same_pipe_day_multiple_events` | Boolean | The preceding eligible-event count is greater than one; no automatic deduplication |

Same-day groups may include events with shared placeholder ID `0`; that is a shared reported value, not proof of a shared physical pipe. Reports distinguish all-event, eligible-event, and reliable-event scopes.

`event_disposition` uses the first matching rule below, so its values are exclusive and cover all imported events. Independent Boolean flags may overlap and must not be summed as if they were disjoint.

| Disposition | Reason |
| --- | --- |
| `not_main` | Asset type is not MAIN or is missing |
| `repair_not_completed` | MAIN event without REPAIR COMPLETED status, including missing status |
| `invalid_event_id` | Eligible type/status but missing or duplicated event ID |
| `invalid_event_date` | Missing or unparseable incident date |
| `ambiguous_asset` | Related ID refers to duplicate asset keys |
| `unmatched_asset` | No unique current asset match |
| `invalid_installation_date` | Matched asset lacks a valid installation date |
| `event_before_install` | Incident predates current installation |
| `reliable_event` | None of the exclusion rules applies; usable in its proper date windows |

## `data_quality_issues`

One source record can generate multiple issue rows, so total issues are not distinct affected-record counts. `issue_id` is stable for the same inputs and rules but can change if new source records or issue rules are added; use source location and issue type for durable traceability.

| Field | Meaning |
| --- | --- |
| `issue_id` | Sequential `DQ` issue-table key |
| `table` | `assets` or `events` |
| `source_file` | Source filename |
| `source_row_number` | Logical CSV record number including the header offset |
| `record_id` | Asset or event primary key; missing when absent in source |
| `asset_id` | Asset key or event's `related_asset_id` for lookup |
| `field` | Standardized field with the issue |
| `issue_code` | Machine-readable issue type |
| `severity` | `warning` or `error`; issues may be retained while usable output is produced |
| `raw_value` | Associated original `raw__` value |
| `reason` | Per-record explanation |
| `action` | Applied handling or pending review action |

Issue codes and handling:

| `issue_code` | Trigger and handling |
| --- | --- |
| `missing_primary_key`, `duplicate_primary_key` | Retain all source records; exclude the affected asset from modeling or event from reliable history |
| `date_parse_failed`, `numeric_parse_failed` | Nonempty parse failure; normalized value missing, original retained |
| `missing_key_field` | Specified key field missing or invalid; exclude only when the needed ID/date is unavailable, and allow missing nonkey inputs |
| `invalid_pipe_size` | `PIPE_SIZE <= 0`; normalized diameter missing, asset retained |
| `invalid_length` | Length `<= 0`; normalized length missing, asset retained |
| `default_minus_one` | `criticality` or `condition_score` equals `-1`; normalized value missing |
| `unknown_material` | Explicit unknown material placeholder; normalized material missing |
| `lined_date_missing` | Source lining flag is YES without a valid date; lining omitted from first-version inputs |
| `placeholder_related_asset_id` | Related ID appears to be placeholder `0`; keep raw ID without inferring one physical pipe |
| `unmatched_asset` | No matching unique current asset; retain event, exclude it from reliable history and targets |
| `ambiguous_asset` | Match to duplicate asset keys; retain and exclude event |
| `event_before_install` | Incident predates current installation; retain and exclude event |
| `asset_size_unit_unverified` | Every nonblank numeric `asset_size_reported` has unresolved units; keep the number, do not convert or model it |
| `normal_service_date_before_incident` | Service-restoration date precedes incident; retain without changing incident date |
| `status_updated_date_before_incident` | Status update precedes incident; retain without changing incident date |
| `same_pipe_same_day_multiple_events` | Across all events, same reported asset ID/day has different event IDs; retain and list for review |

Asset key fields are installation date, material, pipe size, length, and pressure zone. Event key fields are incident date, related asset ID, asset type, and repair status. General missing-field checks run before special-value handling. Invalid `<= 0`, unknown `-1`, and unknown material have their own issue codes; see `field_completeness.csv` for final normalized missing counts.

## Summaries and import metadata

- Each `sources` entry in `manifest.json` records the table name, original filename and path, raw-copy relative path, pandas and CSV record counts, column count, SHA-256, file size, encoding, date format, timezone policy, and original column names. Top-level fields document the observation cutoff, prediction years, incident date range, coverage assumption, and source-integrity check.
- `data_quality_summary.csv` gives `issue_count` and distinct logical `affected_records` for each table/issue/field. Summing across issue types can count one source record more than once.
- `field_completeness.csv` counts trimmed raw blanks in `raw_blank_count`. `normalized_missing_count` also includes parse failures, invalid/default values, and unknown placeholders.
- `annual_summary.csv` gives `sample_count`, `positive_count`, and `positive_rate = positive_count / sample_count` by year. Several incidents on one pipe in one target window still contribute one positive asset-year.
- `event_reconciliation.json` uses `eligible_*` for MAIN/completed events; `dispositions` cover all events. An all-event unmatched detail file can be larger than `eligible_unmatched`.
- `schema.json` lists all dataset columns, pandas types, missing counts, and roles. `model_contract.json` separately defines approved final model inputs.
- `run_metadata.json` uses UTC only for `executed_at_utc`, the job timestamp. Source incident dates are not converted to UTC. `pipeline_sha256` identifies the code version that generated the artifacts.

## Interpretation limit

`reliable_event` means an event passed this project's consistency checks. It does not establish a complete source registry, absence of late reporting, or historical availability of the record. Current assets and final repair statuses lack effective-date histories, so complete point-in-time validity cannot be verified. Historic-year results should be interpreted as retrospective analysis of currently listed pipes.
