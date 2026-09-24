# ---------------- Connection ----------------
variable "snowflake_organization_name" {
  description = "Output of SELECT CURRENT_ORGANIZATION_NAME()."
  type        = string
}

variable "snowflake_account_name" {
  description = "Output of SELECT CURRENT_ACCOUNT_NAME()."
  type        = string
}

variable "snowflake_tf_user" {
  description = "Service user Terraform logs in as (created by bootstrap/01_snowflake_bootstrap.sql)."
  type        = string
  default     = "TF_ADMIN"
}

variable "snowflake_private_key_path" {
  description = "Path to TF_ADMIN's private key (.p8). Empty = read SNOWFLAKE_PRIVATE_KEY env var (CI)."
  type        = string
  default     = ""
}

# ---------------- Adoption ----------------
variable "adopt_existing" {
  description = "true = the hour-0 script already created the platform, so import (adopt) it. false = create everything (fresh account or unit tests)."
  type        = bool
  default     = true
}

# ---------------- Compute + cost ----------------
variable "warehouse_size" {
  description = "Keep XSMALL on a trial. Resize temporarily if a job is slow, don't create new warehouses."
  type        = string
  default     = "XSMALL"
}

variable "credit_quota" {
  description = "Credits the resource monitor allows before suspending the warehouse. Must match the hour-0 script."
  type        = number
  default     = 40
}

# ---------------- People ----------------
variable "team_users" {
  description = "Teammates, keyed by Snowflake user name (must match the hour-0 script). role is one of ADMIN, ENGINEER, ANALYST."

  type = map(object({
    email             = string
    first_name        = string
    role              = string
    default_namespace = optional(string, "LEAK_DB")
  }))
  default = {}

  validation {
    condition     = alltrue([for u in values(var.team_users) : contains(["ADMIN", "ENGINEER", "ANALYST"], u.role)])
    error_message = "team_users[*].role must be one of ADMIN, ENGINEER, ANALYST."
  }
}

variable "trial_owner_user" {
  description = "Your own (trial owner) Snowflake user name, exactly as SELECT CURRENT_USER() shows it (case matters), to grant LEAK_ADMIN. null = skip."
  type        = string
  default     = null
}

variable "initial_password" {
  description = "Temporary password, used ONLY when Terraform creates a new user. Stored in state - trial only."
  type        = string
  sensitive   = true
  default     = null
}
