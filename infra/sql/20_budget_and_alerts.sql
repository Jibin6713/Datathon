-- =====================================================================
-- 20_budget_and_alerts.sql   (OPTIONAL - nice to have, not required)
--
-- The resource monitor LEAK_RM (hour-0 setup) already hard-stops warehouse spend.
-- Run this only if you have spare time on the day. If you do, section 5
-- (email test) and section 4 (hourly alert) are the most useful parts.
-- Spend controls that resource monitors cannot provide:
--   * Budgets cover serverless + AI (Cortex) spend, not just warehouses.
--   * An alert emails the cost owner if the daily spend gets too high.
--
-- Run once as ACCOUNTADMIN after infra/bootstrap/00_hour0_setup.sql.
-- Replace YOUR_EMAIL@example.com everywhere below (3 places). The address must
-- be VERIFIED on a Snowflake user (Snowsight > profile > email > verify).
--
-- Trial note: if any Budget statement fails on the trial account, keep going
-- and record it under Limitations (resource monitor + alert still protect you).
-- =====================================================================

USE ROLE ACCOUNTADMIN;

-- 1. Email integration (used by Budgets and the alert).
CREATE NOTIFICATION INTEGRATION IF NOT EXISTS LEAK_EMAIL_INT
  TYPE = EMAIL
  ENABLED = TRUE
  ALLOWED_RECIPIENTS = ('YOUR_EMAIL@example.com');

-- 2. Account budget: monthly spending limit in credits for the whole account.
CALL SNOWFLAKE.LOCAL.ACCOUNT_ROOT_BUDGET!ACTIVATE();
CALL SNOWFLAKE.LOCAL.ACCOUNT_ROOT_BUDGET!SET_SPENDING_LIMIT(60);
CALL SNOWFLAKE.LOCAL.ACCOUNT_ROOT_BUDGET!SET_EMAIL_NOTIFICATIONS(
  'LEAK_EMAIL_INT', 'YOUR_EMAIL@example.com');

-- 3. Project budget: tracks only the project warehouse.
CREATE SNOWFLAKE.CORE.BUDGET IF NOT EXISTS LEAK_DB.MONITORING.LEAK_PROJECT_BUDGET();
CALL LEAK_DB.MONITORING.LEAK_PROJECT_BUDGET!SET_SPENDING_LIMIT(40);
CALL LEAK_DB.MONITORING.LEAK_PROJECT_BUDGET!ADD_RESOURCE(
  SYSTEM$REFERENCE('WAREHOUSE', 'LEAK_WH', 'SESSION', 'APPLYBUDGET'));

-- 4. Serverless alert (no WAREHOUSE = no warehouse kept awake just to check).
--    Fires if the project warehouse has used more than 5 credits today.
--    Uses the INFORMATION_SCHEMA table function because it has much lower
--    latency than ACCOUNT_USAGE.
CREATE OR REPLACE ALERT LEAK_DB.MONITORING.LEAK_DAILY_CREDIT_ALERT
  SCHEDULE = '60 MINUTE'
  IF (EXISTS (
        SELECT 1
        FROM TABLE(LEAK_DB.INFORMATION_SCHEMA.WAREHOUSE_METERING_HISTORY(
               DATE_RANGE_START => CURRENT_DATE()::TIMESTAMP_LTZ,
               WAREHOUSE_NAME   => 'LEAK_WH'))
        HAVING SUM(credits_used) > 5
  ))
  THEN CALL SYSTEM$SEND_EMAIL(
         'LEAK_EMAIL_INT',
         'YOUR_EMAIL@example.com',
         'Snowflake: LEAK_WH used more than 5 credits today',
         'Check the Platform health tab / V_CREDITS_BY_QUERY_TAG for which workload is responsible.');

ALTER ALERT LEAK_DB.MONITORING.LEAK_DAILY_CREDIT_ALERT RESUME;

-- 5. Test that email works (you should get this within a minute).
CALL SYSTEM$SEND_EMAIL('LEAK_EMAIL_INT', 'YOUR_EMAIL@example.com',
  'Snowflake email test', 'Cost alerts are wired up.');

-- 6. Check everything.
SHOW RESOURCE MONITORS;
SHOW ALERTS IN SCHEMA LEAK_DB.MONITORING;
CALL SNOWFLAKE.LOCAL.ACCOUNT_ROOT_BUDGET!GET_SPENDING_LIMIT();
