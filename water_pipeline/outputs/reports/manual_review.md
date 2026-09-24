# Manual review of real records

Review date: 2026-09-24. This is the actual manual spot check of source CSV records and generated rows from this run. It is not presented as a human review performed by future automated reruns. Source SHA-256 values are in manifest.json; a new source version needs a new spot check. The identifiers and dates below were reread directly from the original CSV files with Python's standard-library CSV parser. No other dataset was used.

`source_row_number` is a logical CSV record number including the header, not necessarily a physical text line number. Dates use month/day/year and have no UTC conversion.

| Item | Original record evidence | Observed result |
| --- | --- | --- |
| Asset 134292 | Asset record 12764; installation `1/1/1937 12:00:00 AM`; CI, 450, KIT 4 | Installation parses to 1937-01-01; one annual row in each year 2015-2025 |
| Event 2252 on asset 134292 | Event record 2; `12/1/2017 3:15:00 PM`; MAIN, REPAIR COMPLETED | Parses to 2017-12-01 15:15. The 2017 sample has `past=0`, `target=1`; the incident enters history from 2018 onward |
| Event 155653 on asset 134292 | Event record 2904; `7/4/2025 1:12:40 PM`; MAIN, REPAIR COMPLETED | Parses to 2025-07-04 13:12:40. At 2025-01-01, `past=1`, `last3y=0`, `since=7.08396362234` years, and `target=1`. History contains only the 2017 event |
| Administrative-date conflict on asset 134292 | Event 2252 has service-restoration time `1/31/2017 11:30:00 PM`, before its December 2017 incident | `normal_service_date_before_incident` is flagged. The incident date is not changed. Service-restoration time is not a history input. Because the incident is after installation, it still passes the stated reliable-event rule |
| January 1 boundary: asset 41030 / event 2416 | Event record 2240; `1/1/2018 12:00:00 AM`; asset installation 1952-01-01 | At 2017-01-01, `past=7`, `target=0`; at 2018-01-01, `past` is still 7 and `target=1`. The boundary event is neither 2018 history nor the 2017 target |
| Pre-installation incident: asset 76420 / event 73 | Event record 26; incident `12/19/2004`; current asset installation `11/27/2009` | Event retained and flagged `event_before_install`. The 2015 and 2025 samples have `past=0`, `last3y=0`, and missing `since`. The older incident is excluded from reliable current-asset history |
| Unmatched event 702 / reported asset 18210 | Event record 22; `4/9/1997`; MAIN, REPAIR COMPLETED | No matching current asset ID. The event remains with `unmatched_asset`; no pipe is guessed |
| Same-day events 1862 and 1865 on asset 88430 | Event records 71 and 73; both `2/1/2013 12:00:00 AM`, with different IDs; asset installation 1988-01-01 | Both are retained and listed for same-day review. The 2015 sample has `past=2`, `last3y=2`; no arbitrary deduplication |
| Invalid diameter: asset 158898 | Asset record 16181; installation `9/1/2022`; `PIPE_SIZE=0`; both score fields are `-1` | Normalized diameter and scores are missing while raw values remain. The 2025 annual sample remains, with `past=0` and missing `since` |
| Invalid diameter: asset 159294 | Asset record 16215; installation `6/21/2019`; `PIPE_SIZE=0`; both score fields are `-1` | Asset remains. No 2019-01-01 sample exists because it was not yet installed; its 2025 sample has missing `pipe_size` |

Decimal years are actual elapsed seconds divided by `365.2425 × 86400`; asset 134292 is therefore about 88.001807 years old at the 2025 prediction date rather than exactly 88 years by integer-year subtraction.

These rows satisfy the processing rules. The spot check cannot establish that source claims are correct in the physical world, especially administrative dates, older asset identity, historical repair status, or registry coverage.
