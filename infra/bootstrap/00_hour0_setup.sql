-- =====================================================================
-- 00_hour0_setup.sql  -  unblock-the-team setup, run BY HAND at hour 0
--
-- Run in ONE Snowsight SQL worksheet as ACCOUNTADMIN (~5 min), in 2 steps:
--   STEP 1: run the statements in STEP 1 below ONE AT A TIME (put the cursor
--           in each statement, press Ctrl+Enter). They create the warehouse
--           that the rest of the script runs on.
--   STEP 2: choose Run All (arrow next to the Run button, or Ctrl+Shift+Enter).
-- Safe to re-run: everything uses IF NOT EXISTS.
--
-- Later, Terraform will ADOPT (import) these exact objects, so
-- DO NOT RENAME anything below once the team has started.
--
-- BEFORE RUNNING:
--   1. Verify your email in Snowsight (profile > email > verify), or the
--      credit-limit warnings at 50% / 75% will not reach you.
--   2. In the WORKSHEET ONLY, replace the 5 placeholder emails and the
--      temporary password in section 6 (search for example.com and CHANGE_ME).
--      Never commit real values: this repo is public.
--
-- Terraform (infra/terraform) later ADOPTS the objects below using these
-- exact names. See infra/README.md, Part B.
--
-- NOTE: keep apostrophes out of comments in this file. Snowsight can
-- mistake them for the start of a text value and then fail with the error
-- Actual statement count ... did not match the desired statement count 1.
-- =====================================================================

-- =====================================================================
-- STEP 1 - run these one at a time with Ctrl+Enter
-- =====================================================================

-- Lets Run All send the whole script at once (without it Snowsight fails with
-- Actual statement count ... did not match the desired statement count 1).
ALTER SESSION SET MULTI_STATEMENT_COUNT = 0;

USE ROLE ACCOUNTADMIN;

-- ---------------------------------------------------------------------
-- 1. COST GUARDRAIL FIRST - resource monitor (hard stop on credits)
--    40 credits for the whole trial. Notify at 50/75%, suspend at 80%,
--    kill running queries and suspend at 95%.
-- ---------------------------------------------------------------------
CREATE RESOURCE MONITOR IF NOT EXISTS LEAK_RM
  WITH CREDIT_QUOTA = 40
       FREQUENCY = NEVER
       START_TIMESTAMP = IMMEDIATELY
  TRIGGERS ON 50 PERCENT DO NOTIFY
           ON 75 PERCENT DO NOTIFY
           ON 80 PERCENT DO SUSPEND
           ON 95 PERCENT DO SUSPEND_IMMEDIATE;

-- ---------------------------------------------------------------------
-- 2. ONE shared warehouse (optimised for a trial)
-- ---------------------------------------------------------------------
CREATE WAREHOUSE IF NOT EXISTS LEAK_WH
  WAREHOUSE_SIZE = XSMALL
  AUTO_SUSPEND = 60                         -- switch off after 60 s idle
  AUTO_RESUME = TRUE
  INITIALLY_SUSPENDED = TRUE
  MIN_CLUSTER_COUNT = 1
  MAX_CLUSTER_COUNT = 1                     -- no multi-cluster
  STATEMENT_TIMEOUT_IN_SECONDS = 600        -- kill runaway queries after 10 min
  STATEMENT_QUEUED_TIMEOUT_IN_SECONDS = 300
  RESOURCE_MONITOR = LEAK_RM
  COMMENT = 'Shared project warehouse. Use QUERY_TAG for cost attribution; resize temporarily instead of creating new warehouses.';

-- Run All needs a running warehouse from its very first statement, and this
-- is the one we just created.
USE WAREHOUSE LEAK_WH;

-- =====================================================================
-- STEP 2 - now choose Run All (STEP 1 is skipped, it already exists)
-- =====================================================================

-- ---------------------------------------------------------------------
-- 3. Database + schemas
--    RAW        files loaded as-is (Wayne)
--    STAGING    cleaned / joined data (Wayne, dbt)
--    CURATED    features, risk scores, dashboard tables (Aritha, Sun)
--    MONITORING cost + usage views (Jibin, Khalid)
-- ---------------------------------------------------------------------
CREATE DATABASE IF NOT EXISTS LEAK_DB
  DATA_RETENTION_TIME_IN_DAYS = 1           -- Time Travel / UNDROP safety net, cheap
  COMMENT = 'Water leak risk project';

CREATE SCHEMA IF NOT EXISTS LEAK_DB.RAW;
CREATE SCHEMA IF NOT EXISTS LEAK_DB.STAGING;
CREATE SCHEMA IF NOT EXISTS LEAK_DB.CURATED;
CREATE SCHEMA IF NOT EXISTS LEAK_DB.MONITORING;

-- ---------------------------------------------------------------------
-- 4. RBAC  -  objects -> DATABASE roles -> ACCOUNT roles -> SYSADMIN
--
--    Database roles (live inside LEAK_DB, hold the object privileges):
--      <SCHEMA>_RW  read + write + create in that schema (all 4 schemas)
--      CURATED_R, MONITORING_R   read-only
--
--    Account (functional) roles (what people actually log in with):
--      LEAK_ENGINEER  builds everything: RAW, STAGING, CURATED, MONITORING
--      LEAK_ANALYST   reads CURATED + MONITORING (dashboard / planner view)
--      LEAK_ADMIN     owns the project; inherits ENGINEER + ANALYST
-- ---------------------------------------------------------------------

-- 4a. Database roles
CREATE DATABASE ROLE IF NOT EXISTS LEAK_DB.RAW_RW;
CREATE DATABASE ROLE IF NOT EXISTS LEAK_DB.STAGING_RW;
CREATE DATABASE ROLE IF NOT EXISTS LEAK_DB.CURATED_RW;
CREATE DATABASE ROLE IF NOT EXISTS LEAK_DB.MONITORING_RW;
CREATE DATABASE ROLE IF NOT EXISTS LEAK_DB.CURATED_R;
CREATE DATABASE ROLE IF NOT EXISTS LEAK_DB.MONITORING_R;

-- 4b. Read roles: use the database + schema, SELECT everything now AND in the future
GRANT USAGE ON DATABASE LEAK_DB                  TO DATABASE ROLE LEAK_DB.CURATED_R;
GRANT USAGE ON SCHEMA   LEAK_DB.CURATED          TO DATABASE ROLE LEAK_DB.CURATED_R;
GRANT SELECT ON ALL TABLES    IN SCHEMA LEAK_DB.CURATED TO DATABASE ROLE LEAK_DB.CURATED_R;
GRANT SELECT ON ALL VIEWS     IN SCHEMA LEAK_DB.CURATED TO DATABASE ROLE LEAK_DB.CURATED_R;
GRANT SELECT ON FUTURE TABLES IN SCHEMA LEAK_DB.CURATED TO DATABASE ROLE LEAK_DB.CURATED_R;
GRANT SELECT ON FUTURE VIEWS  IN SCHEMA LEAK_DB.CURATED TO DATABASE ROLE LEAK_DB.CURATED_R;
GRANT SELECT ON FUTURE DYNAMIC TABLES IN SCHEMA LEAK_DB.CURATED TO DATABASE ROLE LEAK_DB.CURATED_R;
-- Streamlit app: once Aritha/Sun create it, share it with analysts directly:
--   GRANT USAGE ON STREAMLIT LEAK_DB.CURATED.<APP_NAME> TO ROLE LEAK_ANALYST;

GRANT USAGE ON DATABASE LEAK_DB                     TO DATABASE ROLE LEAK_DB.MONITORING_R;
GRANT USAGE ON SCHEMA   LEAK_DB.MONITORING          TO DATABASE ROLE LEAK_DB.MONITORING_R;
GRANT SELECT ON ALL VIEWS     IN SCHEMA LEAK_DB.MONITORING TO DATABASE ROLE LEAK_DB.MONITORING_R;
GRANT SELECT ON FUTURE VIEWS  IN SCHEMA LEAK_DB.MONITORING TO DATABASE ROLE LEAK_DB.MONITORING_R;
GRANT SELECT ON FUTURE TABLES IN SCHEMA LEAK_DB.MONITORING TO DATABASE ROLE LEAK_DB.MONITORING_R;

-- 4c. Write roles: usage + create objects + change data, one block per schema
GRANT USAGE ON DATABASE LEAK_DB TO DATABASE ROLE LEAK_DB.RAW_RW;
GRANT USAGE ON DATABASE LEAK_DB TO DATABASE ROLE LEAK_DB.STAGING_RW;
GRANT USAGE ON DATABASE LEAK_DB TO DATABASE ROLE LEAK_DB.CURATED_RW;
GRANT USAGE ON DATABASE LEAK_DB TO DATABASE ROLE LEAK_DB.MONITORING_RW;

GRANT USAGE, CREATE TABLE, CREATE VIEW, CREATE STAGE, CREATE FILE FORMAT, CREATE PIPE,
      CREATE TASK, CREATE DYNAMIC TABLE, CREATE FUNCTION, CREATE PROCEDURE
  ON SCHEMA LEAK_DB.RAW TO DATABASE ROLE LEAK_DB.RAW_RW;
GRANT USAGE, CREATE TABLE, CREATE VIEW, CREATE STAGE, CREATE FILE FORMAT,
      CREATE TASK, CREATE DYNAMIC TABLE, CREATE FUNCTION, CREATE PROCEDURE
  ON SCHEMA LEAK_DB.STAGING TO DATABASE ROLE LEAK_DB.STAGING_RW;
GRANT USAGE, CREATE TABLE, CREATE VIEW, CREATE STAGE, CREATE FILE FORMAT,
      CREATE TASK, CREATE DYNAMIC TABLE, CREATE FUNCTION, CREATE PROCEDURE, CREATE STREAMLIT
  ON SCHEMA LEAK_DB.CURATED TO DATABASE ROLE LEAK_DB.CURATED_RW;
GRANT USAGE, CREATE TABLE, CREATE VIEW, CREATE TASK
  ON SCHEMA LEAK_DB.MONITORING TO DATABASE ROLE LEAK_DB.MONITORING_RW;

-- Write roles can also read/change data in tables created later
GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON FUTURE TABLES IN SCHEMA LEAK_DB.RAW        TO DATABASE ROLE LEAK_DB.RAW_RW;
GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON FUTURE TABLES IN SCHEMA LEAK_DB.STAGING    TO DATABASE ROLE LEAK_DB.STAGING_RW;
GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON FUTURE TABLES IN SCHEMA LEAK_DB.CURATED    TO DATABASE ROLE LEAK_DB.CURATED_RW;
GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON FUTURE TABLES IN SCHEMA LEAK_DB.MONITORING TO DATABASE ROLE LEAK_DB.MONITORING_RW;
GRANT SELECT ON FUTURE VIEWS IN SCHEMA LEAK_DB.RAW        TO DATABASE ROLE LEAK_DB.RAW_RW;
GRANT SELECT ON FUTURE VIEWS IN SCHEMA LEAK_DB.STAGING    TO DATABASE ROLE LEAK_DB.STAGING_RW;
GRANT SELECT ON FUTURE VIEWS IN SCHEMA LEAK_DB.CURATED    TO DATABASE ROLE LEAK_DB.CURATED_RW;
GRANT SELECT ON FUTURE VIEWS IN SCHEMA LEAK_DB.MONITORING TO DATABASE ROLE LEAK_DB.MONITORING_RW;

-- CURATED_RW / MONITORING_RW include their read roles
GRANT DATABASE ROLE LEAK_DB.CURATED_R    TO DATABASE ROLE LEAK_DB.CURATED_RW;
GRANT DATABASE ROLE LEAK_DB.MONITORING_R TO DATABASE ROLE LEAK_DB.MONITORING_RW;

-- 4d. Account (functional) roles
CREATE ROLE IF NOT EXISTS LEAK_ENGINEER COMMENT = 'Builds the pipeline, models and app (Wayne, Aritha, Sun)';
CREATE ROLE IF NOT EXISTS LEAK_ANALYST  COMMENT = 'Reads curated results + monitoring (Karlo, dashboard users)';
CREATE ROLE IF NOT EXISTS LEAK_ADMIN    COMMENT = 'Project owner (Jibin, Khalid)';

-- database roles -> account roles
GRANT DATABASE ROLE LEAK_DB.RAW_RW        TO ROLE LEAK_ENGINEER;
GRANT DATABASE ROLE LEAK_DB.STAGING_RW    TO ROLE LEAK_ENGINEER;
GRANT DATABASE ROLE LEAK_DB.CURATED_RW    TO ROLE LEAK_ENGINEER;
GRANT DATABASE ROLE LEAK_DB.MONITORING_RW TO ROLE LEAK_ENGINEER;

GRANT DATABASE ROLE LEAK_DB.CURATED_R     TO ROLE LEAK_ANALYST;
GRANT DATABASE ROLE LEAK_DB.MONITORING_R  TO ROLE LEAK_ANALYST;

-- ML model registry (Aritha, Sun): lets engineers save trained models.
-- There is deliberately NO GRANT CREATE NOTEBOOK here: this account rejects it
-- (Unsupported feature GRANT/REVOKE CREATE NOTEBOOK ON SCHEMA), for database
-- roles and account roles alike.
GRANT CREATE MODEL ON SCHEMA LEAK_DB.CURATED TO ROLE LEAK_ENGINEER;

-- account role hierarchy: ENGINEER + ANALYST -> ADMIN -> SYSADMIN
GRANT ROLE LEAK_ENGINEER TO ROLE LEAK_ADMIN;
GRANT ROLE LEAK_ANALYST  TO ROLE LEAK_ADMIN;
GRANT ROLE LEAK_ADMIN    TO ROLE SYSADMIN;

-- 4e. Warehouse access (account-level object, so granted to account roles)
GRANT USAGE ON WAREHOUSE LEAK_WH TO ROLE LEAK_ENGINEER;
GRANT USAGE ON WAREHOUSE LEAK_WH TO ROLE LEAK_ANALYST;
GRANT USAGE, OPERATE, MONITOR, MODIFY ON WAREHOUSE LEAK_WH TO ROLE LEAK_ADMIN;  -- only admins can resize

-- 4f. Cortex AI (explicit, rather than relying on the PUBLIC default)
GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO ROLE LEAK_ENGINEER;
GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO ROLE LEAK_ANALYST;

-- 4g. Admin can read SNOWFLAKE.ACCOUNT_USAGE (for the cost-monitoring views)
GRANT IMPORTED PRIVILEGES ON DATABASE SNOWFLAKE TO ROLE LEAK_ADMIN;

-- ---------------------------------------------------------------------
-- 5. Optional: allow Cortex to use models from other regions
--    (uncomment only if an AI_COMPLETE call says the model is not available)
-- ---------------------------------------------------------------------
-- ALTER ACCOUNT SET CORTEX_ENABLED_CROSS_REGION = 'ANY_REGION';

-- ---------------------------------------------------------------------
-- 6. Users
--    Replace the emails and the temporary password first.
--    Everyone must change the password on first login.
-- ---------------------------------------------------------------------

-- You (the trial owner) get the project admin role too, and it becomes your
-- default so you do not create things as ACCOUNTADMIN by accident (objects
-- owned by ACCOUNTADMIN cannot be replaced or dropped by the team or dbt).
-- Rule for everyone: build data tables as LEAK_ENGINEER; use LEAK_ADMIN
-- only for platform work (cost views, warehouse resizing).
-- Wrapped in double quotes because trial sign-up names can be lower case
-- (e.g. jjoy283) and Snowflake upper-cases unquoted names, which then
-- fails with User JJOY283 does not exist.
SET me = '"' || CURRENT_USER() || '"';   -- you, the trial owner
GRANT ROLE LEAK_ADMIN TO USER IDENTIFIER($me);
ALTER USER IDENTIFIER($me) SET DEFAULT_ROLE = LEAK_ADMIN DEFAULT_WAREHOUSE = LEAK_WH;

CREATE USER IF NOT EXISTS KHALID
  PASSWORD = 'CHANGE_ME_Temp#2026' MUST_CHANGE_PASSWORD = TRUE
  EMAIL = 'khalid@example.com' FIRST_NAME = 'Khalid'
  DEFAULT_ROLE = LEAK_ADMIN DEFAULT_WAREHOUSE = LEAK_WH DEFAULT_NAMESPACE = 'LEAK_DB';

CREATE USER IF NOT EXISTS WAYNE
  PASSWORD = 'CHANGE_ME_Temp#2026' MUST_CHANGE_PASSWORD = TRUE
  EMAIL = 'wayne@example.com' FIRST_NAME = 'Wayne'
  DEFAULT_ROLE = LEAK_ENGINEER DEFAULT_WAREHOUSE = LEAK_WH DEFAULT_NAMESPACE = 'LEAK_DB.RAW';

CREATE USER IF NOT EXISTS ARITHA
  PASSWORD = 'CHANGE_ME_Temp#2026' MUST_CHANGE_PASSWORD = TRUE
  EMAIL = 'aritha@example.com' FIRST_NAME = 'Aritha'
  DEFAULT_ROLE = LEAK_ENGINEER DEFAULT_WAREHOUSE = LEAK_WH DEFAULT_NAMESPACE = 'LEAK_DB.CURATED';

CREATE USER IF NOT EXISTS SUN
  PASSWORD = 'CHANGE_ME_Temp#2026' MUST_CHANGE_PASSWORD = TRUE
  EMAIL = 'sun@example.com' FIRST_NAME = 'Sun'
  DEFAULT_ROLE = LEAK_ENGINEER DEFAULT_WAREHOUSE = LEAK_WH DEFAULT_NAMESPACE = 'LEAK_DB.CURATED';

CREATE USER IF NOT EXISTS KARLO
  PASSWORD = 'CHANGE_ME_Temp#2026' MUST_CHANGE_PASSWORD = TRUE
  EMAIL = 'karlo@example.com' FIRST_NAME = 'Karlo'
  DEFAULT_ROLE = LEAK_ANALYST DEFAULT_WAREHOUSE = LEAK_WH DEFAULT_NAMESPACE = 'LEAK_DB.CURATED';

GRANT ROLE LEAK_ADMIN    TO USER KHALID;
GRANT ROLE LEAK_ENGINEER TO USER WAYNE;
GRANT ROLE LEAK_ENGINEER TO USER ARITHA;
GRANT ROLE LEAK_ENGINEER TO USER SUN;
GRANT ROLE LEAK_ANALYST  TO USER KARLO;

-- ---------------------------------------------------------------------
-- 7. Check it worked (each should return rows, no errors)
-- ---------------------------------------------------------------------
SHOW RESOURCE MONITORS LIKE 'LEAK_RM';
SHOW WAREHOUSES LIKE 'LEAK_WH';            -- auto_suspend = 60, resource_monitor = LEAK_RM
SHOW SCHEMAS IN DATABASE LEAK_DB;
SHOW DATABASE ROLES IN DATABASE LEAK_DB;
SHOW GRANTS TO ROLE LEAK_ENGINEER;
SHOW GRANTS TO ROLE LEAK_ANALYST;
SHOW USERS LIKE '%';

-- Smoke test as an engineer: create, read, drop a table
USE ROLE LEAK_ENGINEER;
USE WAREHOUSE LEAK_WH;
CREATE OR REPLACE TABLE LEAK_DB.RAW.SMOKE_TEST (id INT);
INSERT INTO LEAK_DB.RAW.SMOKE_TEST VALUES (1);
SELECT * FROM LEAK_DB.RAW.SMOKE_TEST;
DROP TABLE LEAK_DB.RAW.SMOKE_TEST;

-- Smoke test as an analyst: least privilege
USE ROLE LEAK_ANALYST;
SHOW SCHEMAS IN DATABASE LEAK_DB;          -- sees CURATED, MONITORING, INFORMATION_SCHEMA only
-- Once Wayne has loaded a table, this should FAIL (good demo moment):
--   SELECT * FROM LEAK_DB.RAW.<any_table> LIMIT 1;

USE ROLE ACCOUNTADMIN;