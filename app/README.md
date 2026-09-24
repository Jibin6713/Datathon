# app/  -  Streamlit dashboard for the maintenance planner

**Owners:** Aritha, Sun · **Runs as:** Streamlit in Snowflake, in `LEAK_DB.CURATED` · **Query tag:** `streamlit`

What goes here
```
streamlit_app.py     the app (copy it here from Snowsight whenever it changes)
environment.yml      extra packages the app needs in Snowflake (if any)
```

Rules
- Read from `CURATED` only, so the planner (`LEAK_ANALYST`) can use it.
- First line after creating the session:
  `session.sql("ALTER SESSION SET QUERY_TAG = 'streamlit'").collect()`
- Share the app with analysts once it exists (ask Jibin/Khalid):
  `GRANT USAGE ON STREAMLIT LEAK_DB.CURATED.<APP_NAME> TO ROLE LEAK_ANALYST;`
