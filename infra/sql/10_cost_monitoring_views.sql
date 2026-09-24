-- =====================================================================
-- 10_cost_monitoring_views.sql
-- Cost + usage views for the "Platform health" tab in Streamlit.
-- Run after infra/bootstrap/00_hour0_setup.sql, as LEAK_ADMIN (it can read SNOWFLAKE.ACCOUNT_USAGE).
-- Readers get access automatically via MONITORING_R future grants.
--
-- Note: ACCOUNT_USAGE has latency (roughly 45 min to 3 hours), so run a
-- few queries early on the build day so these views have data by demo time.
-- =====================================================================

USE ROLE LEAK_ADMIN;
USE WAREHOUSE LEAK_WH;
USE SCHEMA LEAK_DB.MONITORING;

-- 1. Credits per warehouse per day (compute + cloud services).
CREATE OR REPLACE VIEW V_WAREHOUSE_CREDITS_DAILY AS
SELECT
    DATE_TRUNC('day', start_time)::DATE AS usage_date,
    warehouse_name,
    ROUND(SUM(credits_used_compute), 4)        AS compute_credits,
    ROUND(SUM(credits_used_cloud_services), 4) AS cloud_services_credits,
    ROUND(SUM(credits_used), 4)                AS total_credits
FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
WHERE start_time >= DATEADD('day', -30, CURRENT_DATE())
GROUP BY 1, 2;

-- 2. Credits per service type per day. Includes serverless + AI, which
--    resource monitors do NOT cover (which is why we also use Budgets).
CREATE OR REPLACE VIEW V_SERVICE_CREDITS_DAILY AS
SELECT
    usage_date,
    service_type,                       -- WAREHOUSE_METERING, AI_SERVICES, PIPE, SERVERLESS_TASK, ...
    ROUND(SUM(credits_used), 4)   AS credits_used,
    ROUND(SUM(credits_billed), 4) AS credits_billed
FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY
WHERE usage_date >= DATEADD('day', -30, CURRENT_DATE())
GROUP BY 1, 2;

-- 3. Cost by workload, using QUERY_TAG (dbt, streamlit, ml, ingest ...).
--    This is how one shared warehouse still gives per-workload cost.
CREATE OR REPLACE VIEW V_CREDITS_BY_QUERY_TAG AS
SELECT
    DATE_TRUNC('day', start_time)::DATE        AS usage_date,
    COALESCE(NULLIF(query_tag, ''), 'untagged') AS query_tag,
    warehouse_name,
    COUNT(*)                                    AS queries,
    ROUND(SUM(credits_attributed_compute), 6)   AS credits_attributed
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_ATTRIBUTION_HISTORY
WHERE start_time >= DATEADD('day', -30, CURRENT_DATE())
GROUP BY 1, 2, 3;

-- 4. Slowest / most expensive queries (optimisation evidence for judges).
CREATE OR REPLACE VIEW V_TOP_QUERIES AS
SELECT
    query_id,
    user_name,
    role_name,
    warehouse_name,
    query_tag,
    LEFT(query_text, 200)                   AS query_preview,
    ROUND(total_elapsed_time / 1000, 1)     AS elapsed_s,
    ROUND(bytes_scanned / POWER(1024, 3), 3) AS gb_scanned,
    start_time
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE start_time >= DATEADD('day', -7, CURRENT_TIMESTAMP())
  AND warehouse_name IS NOT NULL
QUALIFY ROW_NUMBER() OVER (ORDER BY total_elapsed_time DESC) <= 50;

-- 5. Task failures (pipeline health).
CREATE OR REPLACE VIEW V_TASK_FAILURES AS
SELECT
    database_name,
    schema_name,
    name AS task_name,
    state,
    error_message,
    scheduled_time,
    completed_time
FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY
WHERE state = 'FAILED'
  AND scheduled_time >= DATEADD('day', -7, CURRENT_TIMESTAMP());

-- 6. Headline number for the dashboard: credits used so far vs the trial quota.
CREATE OR REPLACE VIEW V_CREDIT_SUMMARY AS
SELECT
    ROUND(SUM(credits_used), 2)                              AS credits_used_30d,
    ROUND(SUM(IFF(service_type = 'AI_SERVICES', credits_used, 0)), 2) AS ai_credits_30d,
    ROUND(SUM(IFF(usage_date = CURRENT_DATE(), credits_used, 0)), 2)  AS credits_today
FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY
WHERE usage_date >= DATEADD('day', -30, CURRENT_DATE());

-- Quick check
SELECT * FROM V_CREDIT_SUMMARY;
