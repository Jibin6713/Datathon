output "warehouse" {
  value = snowflake_warehouse.project[local.warehouse].name
}

output "resource_monitor" {
  value = snowflake_resource_monitor.project[local.monitor].name
}

output "database" {
  value = snowflake_database.project[local.database].name
}

output "account_roles" {
  value = { for k, r in snowflake_account_role.this : k => r.name }
}

output "users" {
  value = { for k, u in snowflake_user.team : k => u.default_role }
}
