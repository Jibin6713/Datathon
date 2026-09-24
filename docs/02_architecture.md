## Overview

Public pipe and break data from the City of Kitchener lands in Snowflake untouched gets cleaned and quality-checked, is turned into one row per pipe per year, is scored and ranked for failure risk, and is shown to a maintenance planner on a dashboard.
All inside Snowflake on AWS, with roles, cost limits and CI/CD wrapped around it.

## Diagram
![Architecture diagram](architecture_diagram.png)

## 1. Sources

- **Water Mains** (16,213 active pipes): material, size, install date, criticality
- **Water Main Breaks** (3,020 records, 1985–Sept 2026): break date, pipe ID, location

Both are CSVs pulled from Kitchener's open data portal and loaded into Snowflake as-is. No cleaning happens before they land.

## 2. Snowflake layers

| Layer | Purpose |
|---|---|
| **RAW** | Files loaded exactly as received. Nothing is fixed or dropped here, so we can always trace a value back to the source file. |
| **STAGING** | Typed columns, joins between the two source tables, and data quality flags (e.g. a break dated before its pipe's install date is flagged, not deleted). |
| **CURATED** | The asset data model: one row per pipe per year, engineered features (age, material, break count, days since last break), the risk score, and the top 3 drivers per pipe. |

Bad or unexpected data is **flagged, not deleted**, so we can explain what was excluded and why.

## 3. Risk scoring
