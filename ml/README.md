# ml/  -  features and the risk model

**Owners:** Aritha, Sun · **Role:** `LEAK_ENGINEER` · **Query tag:** `ml`

What goes here
- **Notebooks**: build and run them in Snowsight, then **download as `.ipynb` and commit** here (GitHub shows them with outputs, which is great evidence for judges).
- **Feature SQL** that the notebooks rely on, if it isn't already in `transform/curated/`.

```
01_explore.ipynb          data exploration
02_train_risk_model.ipynb features, training, evaluation (metrics!)
03_score_assets.ipynb     writes scores to LEAK_DB.CURATED
```

Rules
- First cell: `session.sql("ALTER SESSION SET QUERY_TAG = 'ml'").collect()`
- Save trained models to the model registry in `LEAK_DB.CURATED` (`LEAK_ENGINEER` can create models there).
- Put key results (metrics, feature importance chart) in `docs/` as screenshots too.
