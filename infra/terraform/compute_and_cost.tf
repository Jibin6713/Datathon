# =====================================================================
# Compute + cost controls (sections 1-2 of the hour-0 script)
#
# One shared warehouse for the whole project (workload attribution is
# done with query tags, not extra warehouses). The resource monitor is
# the hard stop so the team can't burn the trial credits.
# =====================================================================

# for_each over a single name (not a plain resource) so the conditional
# import in imports.tf is valid on every Terraform version >= 1.7.
resource "snowflake_resource_monitor" "project" {
  for_each = toset([local.monitor])

  name         = each.key
  credit_quota = var.credit_quota

  notify_triggers           = [50, 75]
  suspend_trigger           = 80 # finish running queries, then suspend
  suspend_immediate_trigger = 95 # kill running queries and suspend

  lifecycle {
    # The hour-0 script set FREQUENCY = NEVER, START_TIMESTAMP = IMMEDIATELY
    # (quota covers the whole trial, never resets). Snowflake stores the real
    # start time rather than "IMMEDIATELY", so Terraform leaves the schedule
    # alone instead of fighting over it.
    ignore_changes = [frequency, start_timestamp]
  }
}

resource "snowflake_warehouse" "project" {
  for_each = toset([local.warehouse])

  name                = each.key
  warehouse_size      = var.warehouse_size
  auto_suspend        = 60 # seconds idle before it switches off (billing stops)
  auto_resume         = "true"
  initially_suspended = true
  min_cluster_count   = 1
  max_cluster_count   = 1 # no multi-cluster on a trial

  statement_timeout_in_seconds        = 600 # kill runaway queries after 10 min
  statement_queued_timeout_in_seconds = 300

  resource_monitor = snowflake_resource_monitor.project[local.monitor].name
  comment          = "Shared project warehouse. Use QUERY_TAG for cost attribution; resize temporarily instead of creating new warehouses."
}
