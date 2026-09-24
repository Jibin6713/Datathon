# Decision log

**Owner:** Karlo. Add a row whenever the team makes a choice a judge might ask "why?" about.

| When | Decision | Why | Alternatives considered | Who |
|---|---|---|---|---|
| Day 1 | Chose Kitchener open data over other candidate datasets | Real, public, and has both a pipe register and a break history in one place | Synthetic datasets, datasets missing either pipes or breaks | Khalid |
| Day 1 | Excluded CCTV/inspection data from scope | Not available for Kitchener, and full CCTV defect analysis (e.g. Sewer-ML) is far too heavy for a 2-day build | Generate a synthetic inspection table | Everyone |
| Hour 0 | Set up Snowflake by hand, adopt it with Terraform later | Unblock the whole team immediately; codify once stable | Terraform first (team blocked ~1h) | Jibin |
| Hour 0 | One database (`LEAK_DB`), one XSMALL warehouse | 1-day build, trial credits; cost attributed with query tags | DEV/PROD split, warehouse per workload | Jibin |
| Hour 0 | 3 roles: ENGINEER / ANALYST / ADMIN | Least privilege without slowing anyone down | Per-person or per-schema roles | Jibin |
| Hour 4 | Pick a reference date and predict when each pipe is likely to leak after it | Lets us rank pipes by how soon they are expected to fail, so the sooner a leak is predicted, the higher the priority | One-off yes/no prediction (simple binary classification) | Wayne, Sujay |
| Hour 4 | Data scientists (Aritha, Sun) work under the `LEAK_ENGINEER` role | The role name only describes privileges: they need to build features, the model and the app in CURATED | A separate data scientist role | Jibin |
| Hour 4 | Karlo's `LEAK_ANALYST` role is read-only on CURATED and MONITORING and cannot see RAW or STAGING | Least privilege is part of the judging, so RBAC is demonstrated on purpose | Give everyone full access | Jibin |
| Hour 4 | Build the CURATED layer as `dim_asset`, `fact_failure` and a yearly snapshot table | Gives the risk model one clean table per pipe per year | Model directly from the Parquet output | Khalid |
| Hour 6| Excluded the Smart Water Leak Detection Dataset from training | It's synthetic and its break labels come from the authors' own prediction method, not recorded breaks — training on it would just teach the model to copy their method, not predict real breaks | Use it to pad out training data | Wayne |
| Hour 7 | Each output shipped as both Parquet (for code) and CSV (for Excel) | Lets non-coders on the team inspect the data without tooling, while code still gets a fast typed format | Parquet only | Wayne |
| Hour 7 | Split outputs into separate standardized files (assets, events, pipe-year features) instead of one combined file | Source data has many records/variables and wasn't collected as a continuous time series, so forcing it into one file would misrepresent it | One combined dataset | Wayne |
