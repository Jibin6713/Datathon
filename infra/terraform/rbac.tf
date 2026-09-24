# =====================================================================
# RBAC (section 4 of the hour-0 script)
#
#   objects -> DATABASE roles -> ACCOUNT roles -> LEAK_ADMIN -> SYSADMIN
#
#   Database roles (inside LEAK_DB, hold the object privileges):
#     <SCHEMA>_RW              read + write + create, all 4 schemas
#     CURATED_R, MONITORING_R  read-only
#   Account roles (what people log in with):
#     LEAK_ENGINEER  builds everything (all *_RW)
#     LEAK_ANALYST   reads CURATED + MONITORING
#     LEAK_ADMIN     inherits both, controls the warehouse, reads usage data
#
# Grants are not imported: Snowflake GRANTs are idempotent, so Terraform
# simply re-issues the ones the script already made (a harmless no-op).
# =====================================================================

# ---------------- Database roles ----------------
resource "snowflake_database_role" "rw" {
  for_each = toset(local.write_schemas)

  database = snowflake_database.project[local.database].name
  name     = "${each.key}_RW"
}

resource "snowflake_database_role" "r" {
  for_each = toset(local.read_schemas)

  database = snowflake_database.project[local.database].name
  name     = "${each.key}_R"
}

# CURATED_RW / MONITORING_RW include their read roles.
resource "snowflake_grant_database_role" "r_to_rw" {
  for_each = toset(local.read_schemas)

  database_role_name        = snowflake_database_role.r[each.key].fully_qualified_name
  parent_database_role_name = snowflake_database_role.rw[each.key].fully_qualified_name
}

# ---------------- Read roles: usage + future SELECT ----------------
resource "snowflake_grant_privileges_to_database_role" "r_db_usage" {
  for_each = toset(local.read_schemas)

  database_role_name = snowflake_database_role.r[each.key].fully_qualified_name
  privileges         = ["USAGE"]
  on_database        = snowflake_database.project[local.database].name
}

resource "snowflake_grant_privileges_to_database_role" "r_schema_usage" {
  for_each = toset(local.read_schemas)

  database_role_name = snowflake_database_role.r[each.key].fully_qualified_name
  privileges         = ["USAGE"]
  on_schema {
    schema_name = snowflake_schema.this[each.key].fully_qualified_name
  }
}

resource "snowflake_grant_privileges_to_database_role" "r_future_select" {
  for_each = local.read_future_grants

  database_role_name = snowflake_database_role.r[each.value.schema].fully_qualified_name
  privileges         = ["SELECT"]
  on_schema_object {
    future {
      object_type_plural = each.value.object_type
      in_schema          = snowflake_schema.this[each.value.schema].fully_qualified_name
    }
  }
}

# ---------------- Write roles: usage + create + future DML ----------------
resource "snowflake_grant_privileges_to_database_role" "rw_db_usage" {
  for_each = toset(local.write_schemas)

  database_role_name = snowflake_database_role.rw[each.key].fully_qualified_name
  privileges         = ["USAGE"]
  on_database        = snowflake_database.project[local.database].name
}

resource "snowflake_grant_privileges_to_database_role" "rw_schema" {
  for_each = local.write_schema_privileges

  database_role_name = snowflake_database_role.rw[each.key].fully_qualified_name
  privileges         = each.value
  on_schema {
    schema_name = snowflake_schema.this[each.key].fully_qualified_name
  }
}

resource "snowflake_grant_privileges_to_database_role" "rw_future_tables" {
  for_each = toset(local.write_schemas)

  database_role_name = snowflake_database_role.rw[each.key].fully_qualified_name
  privileges         = ["SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE"]
  on_schema_object {
    future {
      object_type_plural = "TABLES"
      in_schema          = snowflake_schema.this[each.key].fully_qualified_name
    }
  }
}

resource "snowflake_grant_privileges_to_database_role" "rw_future_views" {
  for_each = toset(local.write_schemas)

  database_role_name = snowflake_database_role.rw[each.key].fully_qualified_name
  privileges         = ["SELECT"]
  on_schema_object {
    future {
      object_type_plural = "VIEWS"
      in_schema          = snowflake_schema.this[each.key].fully_qualified_name
    }
  }
}

# ---------------- Account (functional) roles ----------------
resource "snowflake_account_role" "this" {
  for_each = local.account_roles

  name    = "LEAK_${each.key}"
  comment = each.value
}

# database roles -> account roles
resource "snowflake_grant_database_role" "to_engineer" {
  for_each = toset(local.write_schemas)

  database_role_name = snowflake_database_role.rw[each.key].fully_qualified_name
  parent_role_name   = snowflake_account_role.this["ENGINEER"].name
}

resource "snowflake_grant_database_role" "to_analyst" {
  for_each = toset(local.read_schemas)

  database_role_name = snowflake_database_role.r[each.key].fully_qualified_name
  parent_role_name   = snowflake_account_role.this["ANALYST"].name
}

# Model registry, granted to the account role (matches the hour-0 script).
resource "snowflake_grant_privileges_to_account_role" "engineer_schema" {
  for_each = local.engineer_schema_privileges

  account_role_name = snowflake_account_role.this["ENGINEER"].name
  privileges        = each.value
  on_schema {
    schema_name = snowflake_schema.this[each.key].fully_qualified_name
  }
}

# account role hierarchy: ENGINEER + ANALYST -> ADMIN -> SYSADMIN
resource "snowflake_grant_account_role" "to_admin" {
  for_each = toset(["ENGINEER", "ANALYST"])

  role_name        = snowflake_account_role.this[each.key].name
  parent_role_name = snowflake_account_role.this["ADMIN"].name
}

resource "snowflake_grant_account_role" "admin_to_sysadmin" {
  role_name        = snowflake_account_role.this["ADMIN"].name
  parent_role_name = "SYSADMIN"
}

# ---------------- Warehouse access ----------------
resource "snowflake_grant_privileges_to_account_role" "warehouse_usage" {
  for_each = toset(["ENGINEER", "ANALYST"])

  account_role_name = snowflake_account_role.this[each.key].name
  privileges        = ["USAGE"]
  on_account_object {
    object_type = "WAREHOUSE"
    object_name = snowflake_warehouse.project[local.warehouse].name
  }
}

# Only admins can resize / suspend the warehouse.
resource "snowflake_grant_privileges_to_account_role" "warehouse_admin" {
  account_role_name = snowflake_account_role.this["ADMIN"].name
  privileges        = ["USAGE", "OPERATE", "MONITOR", "MODIFY"]
  on_account_object {
    object_type = "WAREHOUSE"
    object_name = snowflake_warehouse.project[local.warehouse].name
  }
}

# ---------------- Cortex AI + usage data ----------------
resource "snowflake_grant_database_role" "cortex_user" {
  for_each = toset(local.cortex_roles)

  database_role_name = "\"SNOWFLAKE\".\"CORTEX_USER\""
  parent_role_name   = snowflake_account_role.this[each.key].name
}

# Lets LEAK_ADMIN read SNOWFLAKE.ACCOUNT_USAGE (cost-monitoring views).
resource "snowflake_grant_privileges_to_account_role" "admin_account_usage" {
  account_role_name = snowflake_account_role.this["ADMIN"].name
  privileges        = ["IMPORTED PRIVILEGES"]
  on_account_object {
    object_type = "DATABASE"
    object_name = "SNOWFLAKE"
  }
}
