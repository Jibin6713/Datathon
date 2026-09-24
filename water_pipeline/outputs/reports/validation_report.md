# Executed validation results

| check | status | detail |
| --- | --- | --- |
| 01_source_unchanged_and_archive_identical | PASS | Source SHA-256 checked before and after BOTH full runs; archives match byte-for-byte |
| 01_import_record_counts | PASS | stdlib CSV/pandas/standardized rows: assets=16214, events=3020; no dropped source records |
| 01_expected_file_version | PASS | Checksums compared to independently recorded source version; any difference is a version discrepancy, never corrected by changing data |
| 01_all_original_cells_and_record_numbers_preserved | PASS | Every cell from 27 asset fields and 37 event fields equals the mapped raw__ field |
| 02_primary_keys_present_unique | PASS | WATMAINID and Wat Break Incident ID; OBJECTID is never a join key |
| 02_key_dates_parse | PASS | All installation/incident dates and all nonempty optional dates parsed with explicit month-first format |
| 02_no_timezone_conversion | PASS | Naive timestamps preserved in Parquet; source timezone not inferred |
| 02_invalid_pipe_size_retained_as_missing | PASS | PIPE_SIZE=0: assets 158898 and 159294 remain in assets and eligible annual samples |
| 02_default_values_unknown | PASS | CRITICALITY:3049 and Condition Score:484 defaults set missing; originals preserved |
| 02_key_field_missingness_reported | PASS | {'asset_id': 0, 'installation_date': 0, 'pipe_size': 2, 'material': 1, 'length_m': 0, 'pressure_zone': 0} |
| 03_expected_funnel | PASS | 2925 eligible = 2417 matched + 508 unmatched; 2417 = 325 before installation + 2092 reliable; no difference from baseline |
| 03_dispositions_reconcile_all_events | PASS | {'event_before_install': 325, 'not_main': 76, 'reliable_event': 2092, 'repair_not_completed': 19, 'unmatched_asset': 508} |
| 04_quality_rows_traceable | PASS | 7219 issue rows with source file, logical row, record ID, raw value, reason and action |
| 04_same_id_day_distinct_events_retained | PASS | All ID/day groups:23 groups/53 rows; eligible:18 groups/41 rows; reliable:9 groups/18 rows. ID=0 group is a placeholder, not a known pipe |
| 04_event_asset_size_not_converted | PASS | Numeric values kept in their reported unresolved unit, no cm/mm scaling |
| 05_unique_installed_asset_year_keys | PASS | All 159994 expected keys match; installation strictly before prediction; joins did not multiply rows |
| 05_independent_recalculation_all_feature_rows | PASS | Recomputed every age/count/3-year/recency/prior flag/target from original CSV using datetime and bisect; mismatches=0 |
| 05_forbidden_inputs_absent | PASS | Only model input allowlist + identifiers + split + target; current condition/cleaned/future causes and repair details absent |
| 06_real_january_first_boundary | PASS | Real event 2416 on pipe 41030 at 2018-01-01 00:00 is excluded from 2017 target and 2018 history, included in 2018 target |
| 07_asset_134292 | PASS | 2025-01-01: past=1, last3y=0, since=7.083963622342, target=1; 2025 event never included in history |
| 08_idempotent_full_rerun | PASS | Two complete runs; 19 deterministic artifact SHA-256 values compared, changed=[]; all tables exactly equal; run_metadata timestamp excluded |
| 09_disjoint_complete_year_splits | PASS | {'test': [2024, 2025], 'train': [2015, 2016, 2017, 2018, 2019, 2020, 2021], 'validation': [2022, 2023]} |
| 09_per_year_counts_and_rates | PASS | Annual denominators/positive counts/rates checked independently; see annual_summary.csv |
| 09_no_2026_censored_zero_labels | PASS | No 2026 samples; cutoff 2026-01-01; completeness of registry is separately unverified |
| 06_automated_boundary_and_regression_tests | PASS | Executed unittest suite including synthetic exact boundaries, leap years, no-history missingness, duplicate keys, unobserved windows, normalization and actual data; see unit_tests.txt |
| historical_asset_membership_and_attribute_validity | UNVERIFIABLE | No retired/replaced/split asset histories or attribute validity periods; current snapshot backfill cannot be proven leakage-free |
| historical_event_availability_and_repair_status | UNVERIFIABLE | No trustworthy first-recorded time or full status history; current repair-completed filter is retrospective |
| registry_coverage_and_reporting_delay | UNVERIFIABLE | Calendar windows have elapsed; CSV alone does not prove complete recording or finalization of all breaks |
| authoritative_units_and_date_precision | UNVERIFIABLE | Asset units inferred from MAP_LABEL; event Asset Size units unresolved; source CRS and installation date precision unavailable |

PASS means the executed rule check passed; it does not certify the source records as error-free. UNVERIFIABLE means the two CSV files lack the needed historic evidence. It must not be interpreted as proof of a leakage-free backtest.

Data-quality issues were retained and handled according to the rules; see processed/data_quality_issues.csv for the complete issue list. See manual_review.md for the separate manual record check.

| year | split | sample_count | positive_count | positive_rate |
| --- | --- | --- | --- | --- |
| 2015 | train | 12669 | 91 | 0.007182887362854211 |
| 2016 | train | 12996 | 53 | 0.004078177900892582 |
| 2017 | train | 13231 | 64 | 0.004837124933867433 |
| 2018 | train | 13701 | 76 | 0.005547040362017371 |
| 2019 | train | 13993 | 67 | 0.004788108339884228 |
| 2020 | train | 14827 | 51 | 0.003439670870708842 |
| 2021 | train | 15218 | 66 | 0.004336969378367722 |
| 2022 | validation | 15504 | 79 | 0.00509545923632611 |
| 2023 | validation | 15792 | 40 | 0.0025329280648429585 |
| 2024 | test | 15961 | 48 | 0.003007330367771443 |
| 2025 | test | 16102 | 70 | 0.004347286051422184 |
