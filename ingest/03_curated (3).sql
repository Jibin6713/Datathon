-- =====================================================================
-- 03_curated.sql  |  Owner: Khalid (with Wayne)  |  Run as LEAK_ENGINEER
-- Builds the CURATED layer inside Snowflake, following the rules in
-- water_pipeline/DATA_DICTIONARY.md and model_contract.json (Wayne).
-- The output ASSET_FEATURES_YEARLY is the Snowflake version of
-- pipe_risk_features.parquet and must give the same numbers.
--
-- Reads:  STAGING.STG_WATER_MAINS, STAGING.STG_WATER_MAIN_BREAKS
-- Writes: CURATED.DIM_ASSET, CURATED.FACT_FAILURE,
--         CURATED.ASSET_FEATURES_YEARLY
-- =====================================================================

ALTER SESSION SET MULTI_STATEMENT_COUNT = 0;
ALTER SESSION SET QUERY_TAG = 'curated';
USE ROLE LEAK_ENGINEER;
USE WAREHOUSE LEAK_WH;
USE DATABASE LEAK_DB;

-- ---------------------------------------------------------------------
-- DIM_ASSET: one row per current water main
-- ---------------------------------------------------------------------
CREATE OR REPLACE TABLE CURATED.DIM_ASSET AS
WITH id_counts AS (
    SELECT
        watmain_id,
        COUNT(*) AS n
    FROM STAGING.STG_WATER_MAINS
    GROUP BY watmain_id
)

SELECT
    TO_VARCHAR(m.watmain_id) AS asset_id,
    m.install_date::TIMESTAMP_NTZ AS installation_date,
    -- Unknown placeholders become missing, never guessed
    CASE
        WHEN m.material IN ('UNKNOWN', 'UNK', 'N/A') THEN NULL
        ELSE m.material
    END AS material,
    m.material_group,
    CASE WHEN m.pipe_size_mm > 0 THEN m.pipe_size_mm END AS pipe_size,
    CASE WHEN m.length_m > 0 THEN m.length_m END AS length_m,
    NULLIF(m.pressure_zone, '') AS pressure_zone,
    -- Not model inputs in version 1: consequence and benchmark only
    m.criticality,
    m.benchmark_condition_score,
    m.status,
    (m.watmain_id IS NOT NULL AND c.n = 1) AS asset_id_unique,
    -- Eligible for modelling: unique ID and a parseable install date
    (m.watmain_id IS NOT NULL AND c.n = 1 AND m.install_date IS NOT NULL) AS model_asset_eligible
FROM STAGING.STG_WATER_MAINS AS m
LEFT JOIN id_counts AS c
    ON m.watmain_id = c.watmain_id;

-- ---------------------------------------------------------------------
-- FACT_FAILURE: every break record, with one exclusive disposition.
-- Only rows with reliable_event = TRUE are used for features and target.
-- Disposition order follows DATA_DICTIONARY.md (first rule that applies).
-- ---------------------------------------------------------------------
CREATE OR REPLACE TABLE CURATED.FACT_FAILURE AS
WITH event_id_counts AS (
    SELECT
        break_id,
        COUNT(*) AS n
    FROM STAGING.STG_WATER_MAIN_BREAKS
    GROUP BY break_id
),

matched AS (
    SELECT
        b.break_id,
        TO_VARCHAR(b.break_id) AS event_id,
        TO_VARCHAR(b.watmain_id) AS related_asset_id,
        b.incident_ts AS incident_date,
        b.asset_type_broken AS asset_type,
        b.break_status,
        b.material_at_break,
        b.est_hours_for_repair,
        b.est_units_impacted,
        b.nature_of_break,
        b.apparent_cause,
        b.street,
        b.x_utm,
        b.y_utm,
        e.n AS event_id_count,
        a.asset_id AS matched_asset_id,
        a.installation_date AS matched_installation_date,
        a.asset_id_unique
    FROM STAGING.STG_WATER_MAIN_BREAKS AS b
    LEFT JOIN event_id_counts AS e
        ON b.break_id = e.break_id
    LEFT JOIN CURATED.DIM_ASSET AS a
        ON TO_VARCHAR(b.watmain_id) = a.asset_id
),

disposed AS (
    SELECT
        *,
        CASE
            WHEN asset_type IS NULL OR asset_type <> 'MAIN' THEN 'not_main'
            WHEN break_status IS NULL OR break_status <> 'REPAIR COMPLETED' THEN 'repair_not_completed'
            WHEN break_id IS NULL OR event_id_count > 1 THEN 'invalid_event_id'
            WHEN incident_date IS NULL THEN 'invalid_event_date'
            WHEN matched_asset_id IS NOT NULL AND NOT asset_id_unique THEN 'ambiguous_asset'
            WHEN matched_asset_id IS NULL THEN 'unmatched_asset'
            WHEN matched_installation_date IS NULL THEN 'invalid_installation_date'
            WHEN incident_date < matched_installation_date THEN 'event_before_install'
            ELSE 'reliable_event'
        END AS event_disposition
    FROM matched
)

SELECT
    *,
    event_disposition = 'reliable_event' AS reliable_event
FROM disposed;

-- ---------------------------------------------------------------------
-- ASSET_FEATURES_YEARLY: one row per (asset_id, as_of_date).
-- Features use only breaks BEFORE as_of_date. The target uses only
-- breaks in the 12 months FROM as_of_date. An event exactly on
-- as_of_date counts as target, not history.
-- ---------------------------------------------------------------------
CREATE OR REPLACE TABLE CURATED.ASSET_FEATURES_YEARLY AS
WITH years AS (
    -- Every target window must end by the 2026-01-01 cutoff
    SELECT column1::TIMESTAMP_NTZ AS as_of_date
    FROM VALUES
        ('2015-01-01'), ('2016-01-01'), ('2017-01-01'), ('2018-01-01'),
        ('2019-01-01'), ('2020-01-01'), ('2021-01-01'), ('2022-01-01'),
        ('2023-01-01'), ('2024-01-01'), ('2025-01-01')
),

asset_years AS (
    SELECT
        a.asset_id,
        a.installation_date,
        a.material,
        a.pipe_size,
        a.length_m,
        a.pressure_zone,
        y.as_of_date
    FROM CURATED.DIM_ASSET AS a
    INNER JOIN years AS y
        ON a.installation_date < y.as_of_date
    WHERE a.model_asset_eligible
),

reliable AS (
    SELECT
        matched_asset_id AS asset_id,
        incident_date
    FROM CURATED.FACT_FAILURE
    WHERE reliable_event
),

windows AS (
    SELECT
        ay.asset_id,
        ay.as_of_date,
        COUNT_IF(r.incident_date < ay.as_of_date) AS past_break_count,
        COUNT_IF(
            r.incident_date >= DATEADD(YEAR, -3, ay.as_of_date)
            AND r.incident_date < ay.as_of_date
        ) AS breaks_last_3y,
        MAX(CASE WHEN r.incident_date < ay.as_of_date THEN r.incident_date END) AS last_break_date,
        COUNT_IF(
            r.incident_date >= ay.as_of_date
            AND r.incident_date < DATEADD(MONTH, 12, ay.as_of_date)
        ) AS breaks_next_12m
    FROM asset_years AS ay
    LEFT JOIN reliable AS r
        ON ay.asset_id = r.asset_id
    GROUP BY ay.asset_id, ay.as_of_date
)

SELECT
    ay.asset_id,
    ay.as_of_date,
    -- Elapsed seconds divided by an average year, as in the Python pipeline
    DATEDIFF(SECOND, ay.installation_date, ay.as_of_date) / (365.2425 * 86400) AS age_years,
    ay.material,
    ay.pipe_size,
    ay.length_m,
    ay.pressure_zone,
    w.past_break_count,
    w.breaks_last_3y,
    DATEDIFF(SECOND, w.last_break_date, ay.as_of_date) / (365.2425 * 86400) AS years_since_last_break,
    IFF(w.past_break_count > 0, 1, 0) AS had_prior_break,
    IFF(w.breaks_next_12m > 0, 1, 0) AS break_next_12m,
    CASE
        WHEN YEAR(ay.as_of_date) <= 2021 THEN 'train'
        WHEN YEAR(ay.as_of_date) <= 2023 THEN 'validation'
        ELSE 'test'
    END AS split
FROM asset_years AS ay
INNER JOIN windows AS w
    ON ay.asset_id = w.asset_id
    AND ay.as_of_date = w.as_of_date;

-- ---------------------------------------------------------------------
-- RECONCILIATION with the Python pipeline. Expected values:
--   dispositions: reliable_event 2092, unmatched_asset 508,
--                 event_before_install 325, not_main 76,
--                 repair_not_completed 19
--   feature rows 159994, positives 705 (16,214-pipe snapshot)
-- ---------------------------------------------------------------------
SELECT
    event_disposition,
    COUNT(*) AS n
FROM CURATED.FACT_FAILURE
GROUP BY event_disposition
ORDER BY n DESC;

SELECT
    YEAR(as_of_date) AS year,
    split,
    COUNT(*) AS samples,
    SUM(break_next_12m) AS positives,
    ROUND(SUM(break_next_12m) / COUNT(*), 4) AS positive_rate
FROM CURATED.ASSET_FEATURES_YEARLY
GROUP BY YEAR(as_of_date), split
ORDER BY year;
