-- =====================================================================
-- 01_snowflake_bootstrap.sql
-- Run ONCE, by hand, in a Snowsight worksheet as ACCOUNTADMIN,
-- AFTER 00_hour0_setup.sql, when you are ready to bring Terraform in.
--
-- Why this exists: Terraform needs a user to log in as. This file creates
-- that one user (TF_ADMIN). Terraform then adopts everything the hour-0
-- script created (warehouse, database, roles, users, monitor).
-- =====================================================================

USE ROLE ACCOUNTADMIN;

-- 1. Service user for Terraform (key-pair auth, no password, no MFA prompts).
--    Paste the contents of tf_admin.pub WITHOUT the
--    "-----BEGIN PUBLIC KEY-----" / "-----END PUBLIC KEY-----" lines,
--    as one single line.
CREATE USER IF NOT EXISTS TF_ADMIN
  TYPE = SERVICE
  RSA_PUBLIC_KEY = '<PASTE_TF_ADMIN_PUBLIC_KEY_HERE>'
  DEFAULT_ROLE = ACCOUNTADMIN
  COMMENT = 'Terraform service user. Managed manually (bootstrap).';

-- Trial simplification: Terraform runs as ACCOUNTADMIN because resource
-- monitors and some account-level grants require it.
-- Production: use a dedicated role with only CREATE DATABASE, CREATE ROLE,
-- CREATE USER, CREATE WAREHOUSE, MANAGE GRANTS (documented in Limitations).
GRANT ROLE ACCOUNTADMIN TO USER TF_ADMIN;

-- 2. Optional: let Cortex use models hosted in other regions if your
--    region is missing a model (e.g. Sydney). Uncomment if AI_COMPLETE errors.
-- ALTER ACCOUNT SET CORTEX_ENABLED_CROSS_REGION = 'ANY_REGION';

-- 3. Values you need for terraform.tfvars:
SELECT CURRENT_ORGANIZATION_NAME() AS organization_name,
       CURRENT_ACCOUNT_NAME()      AS account_name;

-- 4. Quick smoke tests (should all succeed before the build day):
-- SELECT AI_COMPLETE('mistral-large2', 'Say hello in one word');   -- Cortex enabled? (needs card on trial)
-- SHOW WAREHOUSES;
