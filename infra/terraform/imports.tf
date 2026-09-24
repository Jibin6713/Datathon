# =====================================================================
# Adopt the objects created by infra/bootstrap/00_hour0_setup.sql.
#
# Each block says "this already exists in Snowflake - take it over,
# don't create it". After the first successful apply they are no-ops.
#
# Only objects are imported (about 20). Grants are simply re-issued by
# Terraform, which is harmless because Snowflake GRANTs are idempotent.
#
# Switched off with adopt_existing = false (fresh account / unit tests).
# =====================================================================

import {
  for_each = var.adopt_existing ? toset([local.monitor]) : toset([])
  to       = snowflake_resource_monitor.project[each.key]
  id       = "\"${each.key}\""
}

import {
  for_each = var.adopt_existing ? toset([local.warehouse]) : toset([])
  to       = snowflake_warehouse.project[each.key]
  id       = "\"${each.key}\""
}

import {
  for_each = var.adopt_existing ? toset([local.database]) : toset([])
  to       = snowflake_database.project[each.key]
  id       = "\"${each.key}\""
}

import {
  for_each = var.adopt_existing ? toset(local.schemas) : toset([])
  to       = snowflake_schema.this[each.key]
  id       = "\"${local.database}\".\"${each.key}\""
}

import {
  for_each = var.adopt_existing ? toset(local.write_schemas) : toset([])
  to       = snowflake_database_role.rw[each.key]
  id       = "\"${local.database}\".\"${each.key}_RW\""
}

import {
  for_each = var.adopt_existing ? toset(local.read_schemas) : toset([])
  to       = snowflake_database_role.r[each.key]
  id       = "\"${local.database}\".\"${each.key}_R\""
}

import {
  for_each = var.adopt_existing ? local.account_roles : {}
  to       = snowflake_account_role.this[each.key]
  id       = "\"LEAK_${each.key}\""
}

import {
  for_each = var.adopt_existing ? var.team_users : {}
  to       = snowflake_user.team[each.key]
  id       = "\"${each.key}\""
}
