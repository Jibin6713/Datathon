# Water main break-risk forecasting (Team 9, Data Nerds)

**UoA Datathon 2026, use case 1.** We predict which water mains are most likely to break in the next 12 to 36 months, so a maintenance planner can decide which pipes to inspect or repair first, and see why each one is on the list.

## The problem

Utilities cannot inspect every pipe every year. Breaks are rare (about 3,000 over the history of a 16,000-pipe network), so checking pipes at random wastes crews. We rank every pipe by risk so a limited inspection budget goes where breaks are most likely.

## Results

We held out 2024 and 2025 (118 real breaks) and asked: if crews inspect only the highest-ranked pipes, how many of those breaks would they have found?

| If crews inspect... | XGBoost survival model | Logistic regression | Rule-based score (SQL) |
| --- | --- | --- | --- |
| Top 1% of pipes | **35 breaks (30%)** | 27 (23%) | _not measured_ |
| Top 2% of pipes | **55 breaks (47%)** | 47 (40%) | _not measured_ |
| Top 5% of pipes | **94 breaks (80%)** | 74 (63%) | 73 (62%) |
| Top 10% of pipes | _not measured_ | _not measured_ | 86 (73%) |

The simple rules already catch 6 in 10 breaks in the top 5% of pipes; the model raises that to 8 in 10. Inspecting the top 5% by model score finds breaks about 16 times more often than inspecting at random.

_Rule-based figures are ranked within each test year; model figures are ranked across both test years combined. Source: [`ml/artifacts/model_comparison/`](ml/artifacts/model_comparison/)._

## Data

- **City of Kitchener Open Data** (Open Government Licence, City of Kitchener): 16,214 water mains (material, diameter, install year, length, location) and 3,020 recorded main breaks.
- The brief mentions CCTV and inspection records. No public dataset for this network has them, so we use the asset register and break history, which carry the strongest early indicators (age, material, previous breaks). See [limitations](docs/06_limitations_learnings.md).
- Raw data files are not committed to this public repo.

## Architecture

![Architecture](docs/architecture_diagram.png)

Everything runs in one Snowflake database, `LEAK_DB`, with one schema per stage:

| Step | What happens | Where |
| --- | --- | --- |
| 1. Load | Kitchener CSVs loaded as-is into `RAW.WATER_MAINS` and `RAW.WATER_BREAKS` | Snowflake stage, `RAW` |
| 2. Clean | Types, dates, material codes standardised; breaks matched to pipes | [`ingest/02_staging.sql`](ingest/02_staging.sql) -> `STAGING` |
| 3. Test | 14 data quality tests (T01-T14): unique IDs, valid dates, no rows lost between layers, breaks join to pipes, no scoring before a pipe was installed, whole-year train/test split | [`ingest/dq_tests.sql`](ingest/dq_tests.sql) |
| 4. Model | Pipe and failure tables plus one row per pipe per year (`CURATED.ASSET_FEATURES_YEARLY`, 159,994 rows). Rule-based score in SQL (`CURATED.ASSET_RISK_SCORE`), then an XGBoost survival model trained in Python on the same features, with scores written to `CURATED.PIPE_REPAIR_PRIORITY` | [`ingest/03_curated (3).sql`](<ingest/03_curated (3).sql>), [`ml/`](ml/) |
| 5. Prioritise | Each pipe gets a 12, 24 and 36-month break probability, its top 3 risk drivers, and a priority score that weights urgency by how critical the pipe is | `CURATED.PIPE_REPAIR_PRIORITY` |
| 6. Use | Streamlit app in Snowflake reads `CURATED.PIPE_REPAIR_PRIORITY` (code to be added to [`app/`](app/)) | `CURATED` |

Priority score: `urgency x (0.8 + 0.2 x criticality / 10)`, so a likely break on a critical main ranks above an equally likely break on a minor one.

## Engineering decisions

- **Infrastructure as code.** A one-off setup script creates the platform in minutes; Terraform then adopts it so every later change is reviewed in code. See [`infra/README.md`](infra/README.md).
- **CI + gated deploy.** Every pull request runs `terraform fmt`, `validate` and unit tests against a mocked Snowflake provider ([`.github/workflows/terraform.yml`](.github/workflows/terraform.yml)). Applying changes to Snowflake is a manual, reviewed step.
- **Least privilege.** Engineers write to all four schemas; analysts can only read `CURATED` and `MONITORING`. Tests fail the build if this changes.
- **Cost control.** One extra-small warehouse that suspends after 60 seconds, a 10-minute query timeout, and a 40-credit resource monitor that stops the warehouse at 95%. Cost views live in [`infra/sql/`](infra/sql/).
- **Honest evaluation.** Train and test are split by whole years, so the model never sees the future; only confirmed, repaired breaks are used as targets.

## Responsible AI

- Every ranked pipe comes with its top 3 drivers, so planners can check the reasoning instead of trusting a black box.
- The model supports a planner's decision; it does not replace field inspection.
- A "no break recorded" label means no repair was logged, not that the pipe is sound. We say this wherever scores are shown.
- AI coding assistants helped write parts of the code. Every result in this README was produced by running the code and checked by the team.

## Limitations

No CCTV or condition data, one city's network, and break records only where a repair was completed. Full list: [`docs/06_limitations_learnings.md`](docs/06_limitations_learnings.md).

## Repository layout

```
ingest/          staging and curated SQL, data quality tests
ml/              risk models (XGBoost survival, logistic baseline), results, tests
water_pipeline/  local Python data audit and feature pipeline, with tests
app/             Streamlit planner dashboard
docs/            project plan, architecture, decision log, limitations
infra/           Snowflake setup script, Terraform, cost monitoring
.github/         CI workflow
```

## Deliverables

- Project plan: [`docs/01_project_plan.md`](docs/01_project_plan.md)
- Architecture: [`docs/02_architecture.md`](docs/02_architecture.md)
- Decision log: [`docs/decision_log.md`](docs/decision_log.md)
- Limitations and learnings: [`docs/06_limitations_learnings.md`](docs/06_limitations_learnings.md)
- Roadmap: [`docs/08_roadmap.md`](docs/08_roadmap.md)

## Team

| Name | Role |
| --- | --- |
| Jibin | Cloud engineer: Snowflake platform, Terraform, CI/CD, cost monitoring |
| Khalid | Project coordinator: curated data layer |
| Wayne | Data ingestion and staging |
| Aritha | Streamlit App |
| Sun | Survival model and repair priority |
| Karlo | Project Coordinator: Analysis and decision log |

<details>
<summary>For contributors</summary>

- Log in to Snowflake with your own user, build as `LEAK_ENGINEER`, use only warehouse `LEAK_WH`, and tag queries (`ALTER SESSION SET QUERY_TAG = 'ingest'`).
- One branch per task, pull request into `main`; CI runs automatically.
- Never commit passwords, keys, `.tfvars`, Terraform state or data files. The repo is public.
- Local Python: 3.11, virtual environment outside OneDrive, then `pip install -r requirements.txt`.

</details>
