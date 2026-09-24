# ingest/  -  getting raw files into `LEAK_DB.RAW`

**Owner:** Wayne · **Role:** `LEAK_ENGINEER` · **Query tag:** `ingest`

What goes here: every SQL statement that loads data, in the order it runs.

```
01_file_formats.sql     CREATE FILE FORMAT ...
02_stages.sql           CREATE STAGE ...
03_load_<source>.sql    CREATE TABLE ... + COPY INTO ... (one file per source)
```

Rules
- Load files **as-is** into `RAW` (no cleaning here; that happens in `transform/`).
- Start each file with `ALTER SESSION SET QUERY_TAG = 'ingest';`
- Don't commit the data files themselves (they're git-ignored). Instead, note in this README where each file came from (URL + download date + licence).

## Sources

| Table | Source | Downloaded | Licence |
|---|---|---|---|
| | City of Kitchener: water mains | | Open Government Licence – Kitchener |
| | City of Kitchener: water main breaks | | Open Government Licence – Kitchener |
| | Christchurch City Council: water supply network | | CC BY 4.0 |
