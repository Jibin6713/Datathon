terraform {
  required_version = ">= 1.7.0" # `terraform test` with mock providers needs 1.7+

  required_providers {
    snowflake = {
      source  = "snowflakedb/snowflake"
      version = "~> 2.9"
    }
  }

  # STATE: local file (terraform.tfstate) on the laptop of the ONE person who
  # runs `terraform apply`. Don't commit it (it's git-ignored) and don't lose it.
  # Next step after the hackathon: an S3 backend so CI can plan/apply.
}
