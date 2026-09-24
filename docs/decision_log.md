# Decision log

**Owner:** Karlo. Add a row whenever the team makes a choice a judge might ask "why?" about.

| When | Decision | Why | Alternatives considered | Who |
|---|---|---|---|---|
| Hour 0 | Set up Snowflake by hand, adopt it with Terraform later | Unblock the whole team immediately; codify once stable | Terraform first (team blocked ~1h) | Jibin |
| Hour 0 | One database (`LEAK_DB`), one XSMALL warehouse | 1-day build, trial credits; cost attributed with query tags | DEV/PROD split, warehouse per workload | Jibin |
| Hour 0 | 3 roles: ENGINEER / ANALYST / ADMIN | Least privilege without slowing anyone down | Per-person or per-schema roles | Jibin |
| Day 2, 3:16 PM | Pick a reference date and predict when each pipe is likely to leak after it | Lets us rank pipes by how soon they are expected to fail, so the sooner a leak is predicted, the higher the priority | One-off yes/no prediction (simple binary classification) | Wayne, Sujay |
| Day 2 | Data scientists (Aritha, Sun) work under the `LEAK_ENGINEER` role | The role name only describes privileges: they need to build features, the model and the app in CURATED | A separate data scientist role | Jibin |
| Day 2 | Karlo's `LEAK_ANALYST` role is read-only on CURATED and MONITORING and cannot see RAW or STAGING | Least privilege is part of the judging, so RBAC is demonstrated on purpose | Give everyone full access | Jibin |
| Day 2, 4:31 PM | Build the CURATED layer as `dim_asset`, `fact_failure` and a yearly snapshot table | Gives the risk model one clean table per pipe per year | Model directly from the Parquet output | Khalid |
