# Snowflake provider - logs in as TF_ADMIN using a key pair.
#
# Locally: set private_key_path in terraform.tfvars.
# In CI:   leave private_key_path empty and set the SNOWFLAKE_PRIVATE_KEY
#          environment variable from a GitHub secret instead.
provider "snowflake" {
  organization_name = var.snowflake_organization_name
  account_name      = var.snowflake_account_name
  user              = var.snowflake_tf_user
  role              = "ACCOUNTADMIN"
  authenticator     = "SNOWFLAKE_JWT"
  private_key       = var.snowflake_private_key_path != "" ? file(pathexpand(var.snowflake_private_key_path)) : null
}
