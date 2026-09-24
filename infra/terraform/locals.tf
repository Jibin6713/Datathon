# =====================================================================
# Names and privileges - copied from infra/bootstrap/00_hour0_setup.sql.
#
# These MUST stay identical to the hour-0 script: Terraform adopts
# (imports) the objects that script created. If a name here differs,
# Terraform will try to create a second object instead of adopting.
# =====================================================================

locals {
  database  = "LEAK_DB"
  warehouse = "LEAK_WH"
  monitor   = "LEAK_RM"

  schemas = ["RAW", "STAGING", "CURATED", "MONITORING"]

  # Account (functional) roles people log in with. Comments match the script.
  account_roles = {
    ENGINEER = "Builds the pipeline, models and app (Wayne, Aritha, Sun)"
    ANALYST  = "Reads curated results + monitoring (Karlo, dashboard users)"
    ADMIN    = "Project owner (Jibin, Khalid)"
  }

  # ---- Database roles (live inside LEAK_DB) ----
  # <SCHEMA>_RW for every schema; read-only roles only where analysts need them.
  write_schemas = local.schemas
  read_schemas  = ["CURATED", "MONITORING"]

  common_create = [
    "USAGE",
    "CREATE TABLE",
    "CREATE VIEW",
    "CREATE STAGE",
    "CREATE FILE FORMAT",
    "CREATE TASK",
    "CREATE DYNAMIC TABLE",
    "CREATE FUNCTION",
    "CREATE PROCEDURE",
  ]

  # Schema-level privileges per write role (section 4c of the script).
  write_schema_privileges = {
    RAW        = concat(local.common_create, ["CREATE PIPE"])
    STAGING    = local.common_create
    CURATED    = concat(local.common_create, ["CREATE STREAMLIT"])
    MONITORING = ["USAGE", "CREATE TABLE", "CREATE VIEW", "CREATE TASK"]
  }

  # Model registry (section 4d of the script), granted straight to
  # LEAK_ENGINEER. No CREATE NOTEBOOK anywhere: the account rejects it with
  # "Unsupported feature GRANT/REVOKE CREATE NOTEBOOK ON SCHEMA".
  engineer_schema_privileges = {
    CURATED = ["CREATE MODEL"]
  }

  # Future SELECT grants per read role (section 4b of the script).
  read_future_types = {
    CURATED    = ["TABLES", "VIEWS", "DYNAMIC TABLES"]
    MONITORING = ["TABLES", "VIEWS"]
  }

  # Which database roles each account role receives (section 4d).
  engineer_database_roles = [for s in local.write_schemas : "${s}_RW"]
  analyst_database_roles  = [for s in local.read_schemas : "${s}_R"]

  # Roles that call Cortex AI functions (ADMIN inherits both).
  cortex_roles = ["ENGINEER", "ANALYST"]

  # ---- Flattened maps so for_each has stable keys ----
  read_future_grants = merge([
    for s, types in local.read_future_types : {
      for t in types : "${s}__${t}" => { schema = s, object_type = t }
    }
  ]...)
}
