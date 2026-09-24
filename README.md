# Water leak risk: infrastructure leak forecasting

Predicts which water mains are most at risk of leaks or failures and helps a maintenance planner decide which to fix first, and why.

Built on **Snowflake** (data, ML, Cortex AI, Streamlit), with **AWS** for ingestion and complex AI (Amazon Bedrock). **Terraform** and **GitHub Actions** handle infrastructure and releases.

## Repository layout

```
ingest/       load raw files into LEAK_DB.RAW (Wayne)                  -> ingest/README.md
transform/    RAW -> STAGING -> CURATED SQL (Wayne, Aritha, Sun)        -> transform/README.md
ml/           notebooks (.ipynb) + features, risk model (Aritha, Sun)  -> ml/README.md
app/          Streamlit dashboard for the planner (Aritha, Sun)        -> app/README.md
docs/         decision log (Karlo), plan, architecture, screenshots, results
infra/        Platform: Snowflake setup, Terraform, RBAC, cost monitoring (Jibin, Khalid) -> infra/README.md
  bootstrap/    hour-0 setup script (run by hand), Terraform user + key generation
  terraform/    adopts the hour-0 setup: warehouse, database, schemas, roles, users, resource monitor + tests
  sql/          cost monitoring views (+ optional budgets and alerts)
.github/      CI/CD workflows
requirements.txt  shared Python packages for local work
```

## How we work

- **Snowflake**: log in to the team account with your own user. Build as `LEAK_ENGINEER`, only use warehouse `LEAK_WH`, and tag your queries (`ALTER SESSION SET QUERY_TAG = 'ingest'`, `'transform'`, `'ml'`, `'streamlit'`).
- **GitHub**: judges only see the repo. Every working piece of SQL/Python goes into a file in the right folder, numbered in run order.
- **Branches**: one per person/task (e.g. `wayne-ingest`), small commits under your own name, Pull Request into `main` (CI checks run automatically).
- **Never commit** passwords, keys, `.tfvars` or data files. The repo is public.

## Python setup (only for work on your laptop)

Python **3.11**. Keep the virtual environment **outside OneDrive** (syncing thousands of files breaks installs).

```
python -m venv .venv
.venv\Scripts\activate            (Mac/Linux: source .venv/bin/activate)
pip install -r requirements.txt
```

## Platform setup

See [`infra/README.md`](infra/README.md) for how the Snowflake platform was built (hour-0 script, then Terraform).

## Data sources

- City of Kitchener Open Data: water mains and water main breaks (Open Government Licence – City of Kitchener)
- Christchurch City Council Open Data: water supply network (CC BY 4.0)
