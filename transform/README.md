# transform/  -  `RAW` → `STAGING` → `CURATED`

**Owner:** Wayne (staging), Aritha + Sun (curated) · **Role:** `LEAK_ENGINEER` · **Query tag:** `transform` (or `dbt`)

What goes here: the SQL that cleans, joins and reshapes data.

```
staging/01_stg_water_mains.sql      cleaned, typed, deduplicated copies of RAW tables
staging/02_stg_main_breaks.sql
curated/01_asset_features.sql       one row per asset with model features
curated/02_asset_risk.sql           risk scores + priority ranking (dashboard reads this)
```

Rules
- `STAGING` = one cleaned table per raw source. `CURATED` = business-ready tables the model and dashboard use.
- Use `CREATE OR REPLACE` so every file can be re-run safely.
- **If we switch to dbt**, put the dbt project in `dbt/` instead and delete this folder.
