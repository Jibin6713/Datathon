-- =====================================================================
-- dq_tests.sql  |  Owner: P3 (Data engineer)
-- Convention: every test SELECTs the rows that FAIL.
--   0 rows returned  = PASS
--   any rows         = FAIL (severity: error) or WARNING (severity: warn)
-- AWS CodeBuild runs each block and fails the build on any error test.
-- =====================================================================

USE DATABASE LEAK_DB;

-- T01 [error] Pipe ID must be present and unique
SELECT watmain_id, COUNT(*) AS n
FROM STAGING.STG_WATER_MAINS
GROUP BY watmain_id
HAVING watmain_id IS NULL OR COUNT(*) > 1;

-- T02 [error] Install date must parse and be plausible
SELECT watmain_id, install_date
FROM STAGING.STG_WATER_MAINS
WHERE install_date IS NULL
   OR install_year < 1850
   OR install_date > CURRENT_DATE();

-- T03 [error] Material must be a known code
SELECT watmain_id, material
FROM STAGING.STG_WATER_MAINS
WHERE material NOT IN ('AC','CI','COP','CPP','DI','HDPE','HDPE IN CI',
                       'PVC','PVCB','PVCF','PVCO','ST','UNKNOWN');

-- T04 [error] Every pipe needs a positive length
SELECT watmain_id, length_m
FROM STAGING.STG_WATER_MAINS
WHERE length_m IS NULL OR length_m <= 0;

-- T05 [error] Break ID must be present and unique
SELECT break_id, COUNT(*) AS n
FROM STAGING.STG_WATER_MAIN_BREAKS
GROUP BY break_id
HAVING break_id IS NULL OR COUNT(*) > 1;

-- T06 [error] Incident dates must parse and not be in the future
SELECT break_id, incident_ts
FROM STAGING.STG_WATER_MAIN_BREAKS
WHERE dq_bad_date OR incident_ts > CURRENT_TIMESTAMP();

-- T07 [error] A valid break on a pipe that still exists must join to the inventory
SELECT b.break_id, b.watmain_id
FROM STAGING.STG_WATER_MAIN_BREAKS AS b
LEFT JOIN STAGING.STG_WATER_MAINS AS m
  ON b.watmain_id = m.watmain_id
WHERE b.is_valid_break
  AND b.asset_still_exists
  AND m.watmain_id IS NULL;

-- T08 [error] Staging must not lose rows versus RAW
WITH counts AS (
  SELECT 'breaks' AS tbl,
         (SELECT COUNT(*) FROM RAW.WATER_BREAKS) AS raw_rows,
         (SELECT COUNT(*) FROM STAGING.STG_WATER_MAIN_BREAKS) AS staging_rows
  UNION ALL
  SELECT 'mains' AS tbl,
         (SELECT COUNT(*) FROM RAW.WATER_MAINS) AS raw_rows,
         (SELECT COUNT(*) FROM STAGING.STG_WATER_MAINS) AS staging_rows
)

SELECT tbl, raw_rows, staging_rows
FROM counts
WHERE raw_rows <> staging_rows;

-- T09 [warn] Material recorded at the break should match the inventory
SELECT b.break_id, b.watmain_id, b.material_at_break, m.material
FROM STAGING.STG_WATER_MAIN_BREAKS AS b
INNER JOIN STAGING.STG_WATER_MAINS AS m
  ON b.watmain_id = m.watmain_id
WHERE b.is_valid_break
  AND b.material_at_break <> 'UNKNOWN'
  AND b.material_at_break <> m.material;
-- Mismatches usually mean the pipe was replaced but kept its ID.

-- T10 [error] Feature table key (asset_id, as_of_date) must be unique
SELECT asset_id, as_of_date, COUNT(*) AS n
FROM CURATED.ASSET_FEATURES_YEARLY
GROUP BY asset_id, as_of_date
HAVING COUNT(*) > 1;

-- T11 [error] A pipe can only be scored after it was installed
SELECT f.asset_id, f.as_of_date, a.installation_date
FROM CURATED.ASSET_FEATURES_YEARLY AS f
INNER JOIN CURATED.DIM_ASSET AS a
    ON f.asset_id = a.asset_id
WHERE a.installation_date >= f.as_of_date;

-- T12 [error] History counts must be consistent with each other
SELECT asset_id, as_of_date, past_break_count, breaks_last_3y, had_prior_break
FROM CURATED.ASSET_FEATURES_YEARLY
WHERE breaks_last_3y > past_break_count
   OR had_prior_break <> IFF(past_break_count > 0, 1, 0)
   OR (past_break_count = 0 AND years_since_last_break IS NOT NULL);

-- T13 [error] Split must follow whole years (train to 2021, validation 2022-2023, test 2024-2025)
SELECT asset_id, as_of_date, split
FROM CURATED.ASSET_FEATURES_YEARLY
WHERE split <> CASE
        WHEN YEAR(as_of_date) <= 2021 THEN 'train'
        WHEN YEAR(as_of_date) <= 2023 THEN 'validation'
        ELSE 'test'
    END;

-- T14 [error] Only reliable breaks may feed features and target
SELECT break_id, event_disposition, reliable_event
FROM CURATED.FACT_FAILURE
WHERE reliable_event <> (event_disposition = 'reliable_event');

-- =====================================================================
-- DQ SUMMARY (not a test) - use this table in the deck / dashboard
-- =====================================================================
SELECT
  COUNT(*)                                        AS total_break_records,
  COUNT_IF(dq_is_service_break)                   AS service_line_breaks,
  COUNT_IF(dq_not_completed)                      AS cancelled_or_open,
  COUNT_IF(dq_placeholder_date)                   AS placeholder_dates,
  COUNT_IF(dq_unlinked)                           AS unlinked_to_pipe,
  COUNT_IF(is_valid_break)                        AS valid_breaks,
  ROUND(100 * COUNT_IF(is_valid_break) / COUNT(*), 1) AS pct_valid
FROM STAGING.STG_WATER_MAIN_BREAKS;
