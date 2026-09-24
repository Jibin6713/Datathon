-- =====================================================================
-- 02_staging.sql  |  Owner: Wayne  |  Run as LEAK_ENGINEER
-- Turns the RAW tables loaded by Wayne (RAW.WATER_MAINS and
-- RAW.WATER_BREAKS) into typed, standardised staging tables.
-- Design choice: bad rows are FLAGGED, not deleted, so every
-- exclusion is visible and auditable.
-- Column names below match the RAW tables exactly. Names with spaces
-- or symbols must stay in double quotes.
-- =====================================================================

ALTER SESSION SET MULTI_STATEMENT_COUNT = 0;
ALTER SESSION SET QUERY_TAG = 'staging';
USE ROLE LEAK_ENGINEER;
USE WAREHOUSE LEAK_WH;
USE DATABASE LEAK_DB;

-- Kitchener dates look like: 12/1/2017 3:15:00 PM
SET ts_fmt = 'MM/DD/YYYY HH12:MI:SS AM';

-- ---------------------------------------------------------------------
-- STG_WATER_MAINS: one row per pipe segment in the current register
-- ---------------------------------------------------------------------
CREATE OR REPLACE TABLE STAGING.STG_WATER_MAINS AS
WITH typed AS (
    SELECT
        watmainid AS watmain_id,
        UPPER(TRIM(status)) AS status,
        UPPER(TRIM(pressure_zone)) AS pressure_zone,
        NULLIF(pipe_size, 0) AS pipe_size_mm,
        CASE
            WHEN UPPER(TRIM(material)) IN ('XXX', '') OR material IS NULL THEN 'UNKNOWN'
            ELSE UPPER(TRIM(material))
        END AS material,
        lined AS is_lined,
        TRY_TO_TIMESTAMP_NTZ(lined_date, $ts_fmt)::DATE AS lined_date,
        TRY_TO_TIMESTAMP_NTZ(installation_date, $ts_fmt)::DATE AS install_date,
        UPPER(TRIM(ownership)) AS pipe_owner,
        bridge_main AS is_bridge_main,
        shallow_main AS is_shallow_main,
        undersized AS is_undersized,
        -- City consequence rating 0-10; -1 means unknown
        NULLIF(criticality, -1) AS criticality,
        -- Current condition score from the city. BENCHMARK ONLY - never a
        -- model feature: it is the value as of today
        NULLIF(condition_score, -1) AS benchmark_condition_score,
        shape__length AS length_m,
        'RAW.WATER_MAINS' AS _source_table
    FROM RAW.WATER_MAINS
)

SELECT
    *,
    YEAR(install_date) AS install_year,
    -- Group rare material codes so each group has enough pipes
    CASE
        WHEN material = 'CI' THEN 'CAST IRON'
        WHEN material = 'DI' THEN 'DUCTILE IRON'
        WHEN material IN ('PVC', 'PVCO', 'PVCB', 'PVCF') THEN 'PVC'
        WHEN material = 'AC' THEN 'ASBESTOS CEMENT'
        WHEN material IN ('HDPE', 'HDPE IN CI') THEN 'HDPE'
        WHEN material = 'CPP' THEN 'CONCRETE'
        WHEN material IN ('COP', 'ST') THEN 'OTHER METAL'
        ELSE 'UNKNOWN'
    END AS material_group,
    criticality IS NULL AS dq_criticality_unknown
FROM typed;

-- ---------------------------------------------------------------------
-- STG_WATER_MAIN_BREAKS: one row per reported break, with DQ flags
-- ---------------------------------------------------------------------
CREATE OR REPLACE TABLE STAGING.STG_WATER_MAIN_BREAKS AS
WITH typed AS (
    SELECT
        wat_break_incident_id AS break_id,
        TRY_TO_TIMESTAMP_NTZ(incident_date, $ts_fmt) AS incident_ts,
        UPPER(TRIM(type_of_asset_broken)) AS asset_type_broken,
        UPPER(TRIM(current_status_of_the_break)) AS break_status,
        related_asset_id AS watmain_id,
        asset_exists AS asset_still_exists,
        -- Source header says cm but the values (150, 200, 300) are mm
        NULLIF("Asset Size (cm)", 0) AS pipe_size_mm_at_break,
        year_asset_installed AS install_year_at_break,
        CASE
            WHEN UPPER(TRIM(asset_material)) IN ('XXX', '') OR asset_material IS NULL THEN 'UNKNOWN'
            ELSE UPPER(TRIM(asset_material))
        END AS material_at_break,
        -- Known only AFTER a break: reporting and consequence only,
        -- never a likelihood feature
        estimated_hours_for_repair AS est_hours_for_repair,
        estimated_number_of_units_impacted AS est_units_impacted,
        does_the_road_need_to_be_closed AS road_closed,
        UPPER(TRIM(nature_of_break)) AS nature_of_break,
        UPPER(TRIM(apparent_cause_of_break)) AS apparent_cause,
        UPPER(TRIM(street)) AS street,
        x AS x_utm,
        y AS y_utm,
        'RAW.WATER_BREAKS' AS _source_table
    FROM RAW.WATER_BREAKS
),

flagged AS (
    SELECT
        *,
        COALESCE(asset_type_broken <> 'MAIN', TRUE) AS dq_is_service_break,
        COALESCE(break_status <> 'REPAIR COMPLETED', TRUE) AS dq_not_completed,
        incident_ts IS NULL AS dq_bad_date,
        -- 49 rows share this bulk-load timestamp: flagged for review only
        COALESCE(incident_ts = '2011-12-15 15:38:26'::TIMESTAMP_NTZ, FALSE) AS dq_placeholder_date,
        COALESCE(watmain_id, 0) = 0 AS dq_unlinked
    FROM typed
)

SELECT
    *,
    -- Simple validity flag for quick checks. The model uses the stricter
    -- reliable_event rules in CURATED.FACT_FAILURE instead.
    NOT dq_is_service_break
    AND NOT dq_not_completed
    AND NOT dq_bad_date
    AND NOT dq_unlinked AS is_valid_break
FROM flagged;

-- Quick check. Expect mains = rows in RAW.WATER_MAINS (16,214),
-- all_breaks = 3,020, bad_dates = 0
SELECT
    (SELECT COUNT(*) FROM STAGING.STG_WATER_MAINS) AS mains,
    (SELECT COUNT(*) FROM STAGING.STG_WATER_MAIN_BREAKS) AS all_breaks,
    (SELECT COUNT_IF(dq_bad_date) FROM STAGING.STG_WATER_MAIN_BREAKS) AS bad_dates,
    (SELECT COUNT_IF(install_date IS NULL) FROM STAGING.STG_WATER_MAINS) AS bad_install_dates;
