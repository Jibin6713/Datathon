# XGBoost time to next break pipeline

This self-contained pipeline predicts the time from a reference date to each
pipe's next reliable break. It uses the XGBoost accelerated failure time
objective so pipes without a later recorded break are treated as right-censored
rather than as permanent non-failures.

Run the complete pipeline from the repository root:

```powershell
python ml/xgboost_survival_pipeline/run_all.py
```

The default reference date is the source manifest's complete observation
cutoff, `2026-01-01`. The command reads existing `water_pipeline/outputs`
tables without changing them and writes generated artifacts to
`ml/artifacts/xgboost_survival`.

The same work can be run step by step:

```powershell
python ml/xgboost_survival_pipeline/01_build_training_data.py
python ml/xgboost_survival_pipeline/02_train_model.py
python ml/xgboost_survival_pipeline/03_score_and_prioritize.py
```

Primary outputs:

- `pipe_repair_priority.csv`: probabilities, predicted median time, service
  criticality, priority score, rank, band, action, and top three drivers.
- `pipe_risk_drivers.csv`: long-form per-pipe TreeSHAP explanations.
- `metrics.json`: survival discrimination, probability quality, and
  maintenance-budget metrics.
- `test_survival_predictions.csv`: untouched 2024-2025 backtest predictions.
- `xgboost_aft_model.json` and `preprocessor.joblib`: reusable model bundle.

The repair policy applies service criticality after risk estimation. It is not
an input to the physical failure model. The default urgency score weights
12-, 24-, and 36-month cumulative probabilities at 60%, 30%, and 10%, so an
earlier predicted break receives more priority. Criticality modifies 20% of the
final score and can be changed with `--criticality-weight` after agreement with
maintenance planners.
