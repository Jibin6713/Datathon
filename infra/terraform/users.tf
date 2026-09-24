# =====================================================================
# Users (section 6 of the hour-0 script)
#
# Teammates come from var.team_users. The trial owner (Jibin) is NOT
# managed here - that login existed before the project - but gets
# LEAK_ADMIN via var.trial_owner_user.
# TF_ADMIN (Terraform's own login) is created by bootstrap SQL.
# =====================================================================

resource "snowflake_user" "team" {
  for_each = var.team_users

  name       = each.key
  email      = each.value.email
  first_name = each.value.first_name

  default_role      = snowflake_account_role.this[each.value.role].name
  default_warehouse = snowflake_warehouse.project[local.warehouse].name
  default_namespace = each.value.default_namespace

  # Only used if Terraform CREATES a user (e.g. a new teammate). Adopted users
  # keep the password they already chose.
  password             = var.initial_password
  must_change_password = "true"

  lifecycle {
    # IMPORTANT: Snowflake never reveals passwords, and must_change_password
    # flips to false once someone changes theirs. Without this, the first
    # apply after adoption would reset everyone's password.
    ignore_changes = [password, must_change_password]
  }
}

resource "snowflake_grant_account_role" "team" {
  for_each = var.team_users

  role_name = snowflake_account_role.this[each.value.role].name
  user_name = snowflake_user.team[each.key].name
}

resource "snowflake_grant_account_role" "trial_owner_admin" {
  count = var.trial_owner_user != null ? 1 : 0

  role_name = snowflake_account_role.this["ADMIN"].name
  user_name = var.trial_owner_user
}
