#!/usr/bin/env bash
# Generates the key pair Terraform's TF_ADMIN user logs in with and prints
# the one-line public key you paste into 01_snowflake_bootstrap.sql.
#
# The key is written to ~/.snowflake (OUTSIDE the repo). Never commit .p8 files.
#
# Usage:  bash infra/bootstrap/generate_keys.sh
set -euo pipefail

KEY_DIR="${HOME}/.snowflake"
mkdir -p "$KEY_DIR"
chmod 700 "$KEY_DIR"

name=tf_admin
priv="$KEY_DIR/${name}.p8"
pub="$KEY_DIR/${name}.pub"

if [[ -f "$priv" ]]; then
  echo "• $priv already exists - skipping (delete it to regenerate)."
else
  openssl genrsa 2048 2>/dev/null | openssl pkcs8 -topk8 -inform PEM -out "$priv" -nocrypt
  openssl rsa -in "$priv" -pubout -out "$pub" 2>/dev/null
  chmod 600 "$priv"
  echo "• Created $priv"
fi

echo
echo "================ One-line public key (tf_admin) ================"
grep -v -- "-----" "$pub" | tr -d '\n'
echo
echo
echo "-> paste into infra/bootstrap/01_snowflake_bootstrap.sql"
