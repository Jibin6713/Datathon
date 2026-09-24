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

- Start with a **rule-based score** that is easy to explain to a planner — this is the baseline we have to beat, not a placeholder.
- Only add an ML model if it demonstrably outperforms the rule-based score on held-out years.
- Features are built so that scoring a pipe at time *t* only uses data available **before** *t* — no future breaks leak into the features used to predict them.
- Each pipe's score comes with its **top 3 drivers**, not just a number, so the ranking is explainable.

## 4. Serving layer

A **Streamlit-in-Snowflake** app reads directly from the CURATED tables and shows planners the ranked list of pipes, each with its score and top drivers, with filters (e.g. by material or ward).

## 5. Platform, security and cost

- **RBAC**: all objects are built and accessed through a dedicated `LEAK_ENGINEER` role rather than personal or default roles, mapped up to an account-level role.
- **Warehouse strategy**: a single **XSMALL** warehouse shared across the pipeline, not one warehouse per task, to stay inside trial credits.
- **Monitoring**: a resource monitor with a credit cap so the warehouse suspends before the trial account runs out of credits.
- **CI/CD & IaC**: the Snowflake setup (database, warehouse, roles, monitor) is defined in **Terraform**, and changes are deployed through a pipeline rather than made by hand in the UI, so the environment can be rebuilt if credits are exhausted.
- **Code**: everything (Terraform, SQL, dbt models, Streamlit app) lives in **GitHub**, and every team member can explain the code they pushed.

## 6. Design principles behind the architecture

1. **Explainable first** — a simple, defensible score beats a complex one nobody can justify to a planner.
2. **No future leakage** — features for a given point in time only ever use information that existed before that point.
3. **Flag, don't delete** — questionable data stays visible with a flag rather than silently disappearing, so decisions are auditable.
