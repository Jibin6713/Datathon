# =====================================================================
# Database + schemas (section 3 of the hour-0 script)
#   RAW        files loaded as-is (Wayne)
#   STAGING    cleaned / joined data (Wayne, dbt)
#   CURATED    features, risk scores, dashboard tables (Aritha, Sun)
#   MONITORING cost + usage views (Jibin, Khalid)
#
# Terraform manages the containers, never the data: tables the team
# creates inside these schemas are not in Terraform and are never touched.
# =====================================================================

resource "snowflake_database" "project" {
  for_each = toset([local.database])

  name                        = each.key
  comment                     = "Water leak risk project"
  data_retention_time_in_days = 1 # Time Travel / UNDROP safety net, cheap

  lifecycle {
    prevent_destroy = true # everyone's data lives in here
  }
}

resource "snowflake_schema" "this" {
  for_each = toset(local.schemas)

  database = snowflake_database.project[local.database].name
  name     = each.key

  # Must match what Snowflake reports for the schemas the hour-0 script made.
  # is_transient can only be set at creation, so leaving it at "default" makes
  # Terraform plan to DESTROY and recreate every schema (and their tables).
  is_transient = "false"

  lifecycle {
    prevent_destroy = true
  }
}
