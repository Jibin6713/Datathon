# Unit tests for the Snowflake platform config.
# Uses a MOCKED provider, so it needs no Snowflake account or credentials:
#   terraform test        (Terraform >= 1.7)
# Runs in CI on every pull request.
#
# All runs are `plan` only: the database and schemas have prevent_destroy,
# and nothing is imported (adopt_existing = false).

mock_provider "snowflake" {}

variables {
  snowflake_organization_name = "TESTORG"
  snowflake_account_name      = "TESTACC"
  adopt_existing              = false

  team_users = {
    KHALID = { email = "a@example.com", first_name = "Khalid", role = "ADMIN" }
    WAYNE  = { email = "b@example.com", first_name = "Wayne", role = "ENGINEER", default_namespace = "LEAK_DB.RAW" }
    KARLO  = { email = "c@example.com", first_name = "Karlo", role = "ANALYST", default_namespace = "LEAK_DB.CURATED" }
  }
}

# Names must match infra/bootstrap/00_hour0_setup.sql exactly, or Terraform
# would create duplicates instead of adopting what the script made.
run "names_match_hour0_script" {
  command = plan

  assert {
    condition     = snowflake_database.project["LEAK_DB"].name == "LEAK_DB"
    error_message = "Database must be LEAK_DB."
  }

  assert {
    condition     = toset([for s in snowflake_schema.this : s.name]) == toset(["RAW", "STAGING", "CURATED", "MONITORING"])
    error_message = "Schemas must be RAW, STAGING, CURATED, MONITORING."
  }

  assert {
    condition     = toset([for r in snowflake_account_role.this : r.name]) == toset(["LEAK_ENGINEER", "LEAK_ANALYST", "LEAK_ADMIN"])
    error_message = "Account roles must be LEAK_ENGINEER, LEAK_ANALYST, LEAK_ADMIN."
  }

  assert {
    condition     = toset([for r in snowflake_database_role.rw : r.name]) == toset(["RAW_RW", "STAGING_RW", "CURATED_RW", "MONITORING_RW"])
    error_message = "Write database roles must be <SCHEMA>_RW for all four schemas."
  }

  assert {
    condition     = toset([for r in snowflake_database_role.r : r.name]) == toset(["CURATED_R", "MONITORING_R"])
    error_message = "Read database roles must be CURATED_R and MONITORING_R only."
  }
}

run "cost_guardrails" {
  command = plan

  assert {
    condition     = snowflake_warehouse.project["LEAK_WH"].auto_suspend == 60
    error_message = "Warehouse must auto-suspend after 60 seconds."
  }

  assert {
    condition     = snowflake_warehouse.project["LEAK_WH"].warehouse_size == "XSMALL"
    error_message = "Warehouse should default to XSMALL on a trial."
  }

  assert {
    condition     = snowflake_warehouse.project["LEAK_WH"].max_cluster_count == 1
    error_message = "No multi-cluster warehouses on a trial."
  }

  assert {
    condition     = snowflake_warehouse.project["LEAK_WH"].statement_timeout_in_seconds == 600
    error_message = "Runaway queries must be killed after 10 minutes."
  }

  assert {
    condition     = snowflake_warehouse.project["LEAK_WH"].resource_monitor == "LEAK_RM"
    error_message = "Warehouse must be attached to the LEAK_RM resource monitor."
  }

  assert {
    condition     = snowflake_resource_monitor.project["LEAK_RM"].credit_quota == 40 && snowflake_resource_monitor.project["LEAK_RM"].suspend_immediate_trigger == 95
    error_message = "Resource monitor must allow 40 credits and hard-stop at 95%."
  }
}

run "least_privilege" {
  command = plan

  # Analysts only get the read roles for CURATED and MONITORING - no RAW, no STAGING, no write.
  assert {
    condition     = toset(keys(snowflake_grant_database_role.to_analyst)) == toset(["CURATED", "MONITORING"])
    error_message = "LEAK_ANALYST must only receive CURATED_R and MONITORING_R."
  }

  # Engineers get read-write on every schema.
  assert {
    condition     = toset(keys(snowflake_grant_database_role.to_engineer)) == toset(["RAW", "STAGING", "CURATED", "MONITORING"])
    error_message = "LEAK_ENGINEER must receive all four *_RW roles."
  }

  # Model registry allowed where the ML work happens.
  assert {
    condition     = contains(snowflake_grant_privileges_to_account_role.engineer_schema["CURATED"].privileges, "CREATE MODEL")
    error_message = "LEAK_ENGINEER must be able to register models in CURATED."
  }

  # The account rejects CREATE NOTEBOOK on schemas entirely, so it must never appear.
  assert {
    condition     = alltrue(concat([for g in snowflake_grant_privileges_to_database_role.rw_schema : !contains(g.privileges, "CREATE NOTEBOOK")], [for g in snowflake_grant_privileges_to_account_role.engineer_schema : !contains(g.privileges, "CREATE NOTEBOOK")]))
    error_message = "CREATE NOTEBOOK must not be granted (Snowflake: Unsupported feature on this account)."
  }

  # Only admins can resize the warehouse.
  assert {
    condition     = !contains(snowflake_grant_privileges_to_account_role.warehouse_usage["ENGINEER"].privileges, "MODIFY")
    error_message = "Engineers must not be able to resize the warehouse."
  }

  # One role per teammate, and default role = that role.
  assert {
    condition     = length(snowflake_grant_account_role.team) == 3
    error_message = "Expected one role grant per teammate."
  }

  assert {
    condition     = snowflake_user.team["KARLO"].default_role == "LEAK_ANALYST"
    error_message = "Karlo should default to LEAK_ANALYST."
  }
}

run "rejects_unknown_role" {
  command = plan

  variables {
    team_users = {
      BAD = { email = "x@example.com", first_name = "Bad", role = "SUPERUSER" }
    }
  }

  expect_failures = [var.team_users]
}
