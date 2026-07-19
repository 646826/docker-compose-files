#!/bin/sh
set -eu

ROOT=$(CDPATH= cd "$(dirname "$0")/.." && pwd)
ENV_FILE="$ROOT/.env"
SECRETS_DIR="$ROOT/.secrets"
HTPASSWD_IMAGE=httpd:2.4.68-alpine
MOSQUITTO_IMAGE=eclipse-mosquitto:2.1.2-alpine
DOCKER_READY=0

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'Required command not found: %s\n' "$1" >&2
    exit 1
  fi
}

ensure_docker() {
  if [ "$DOCKER_READY" -eq 1 ]; then
    return
  fi
  require_command docker
  if ! docker version >/dev/null 2>&1; then
    printf 'A working Docker daemon is required to create password hashes.\n' >&2
    exit 1
  fi
  DOCKER_READY=1
}

read_setting() {
  key=$1
  fallback=$2
  value=$(sed -n "s/^${key}=//p" "$ENV_FILE" | tail -n 1 | tr -d '\r')
  if [ -n "$value" ]; then
    printf '%s' "$value"
  else
    printf '%s' "$fallback"
  fi
}

validate_username() {
  name=$1
  value=$2
  case "$value" in
    ''|*[!A-Za-z0-9._-]*)
      printf '%s must contain only letters, digits, dot, underscore, or hyphen.\n' "$name" >&2
      exit 1
      ;;
  esac
}

write_random_hex() {
  path=$1
  bytes=$2
  if [ ! -f "$path" ]; then
    value=$(openssl rand -hex "$bytes")
    printf '%s' "$value" >"$path"
  fi
}

write_text_if_missing() {
  path=$1
  value=$2
  if [ ! -f "$path" ]; then
    printf '%s\n' "$value" >"$path"
  fi
}

normalize_single_line_secret() {
  path=$1
  label=$2
  [ -f "$path" ] || return 0

  # Command substitution removes only trailing newlines. Embedded line endings
  # remain and are rejected, while an old generated token ending in LF/CRLF is
  # normalized without changing the credential value.
  value=$(cat "$path")
  carriage_return=$(printf '\r')
  case "$value" in
    *"$carriage_return") value=${value%"$carriage_return"} ;;
  esac
  case "$value" in
    ''|*"$carriage_return"*|*'
'*)
      printf '%s must contain exactly one non-empty line; refusing to modify it.\n' "$label" >&2
      exit 1
      ;;
  esac
  printf '%s' "$value" >"$path"
}

require_value_match() {
  setting=$1
  path=$2
  expected=$3
  if [ -f "$path" ]; then
    actual=$(sed -n '1p' "$path" | tr -d '\r')
    if [ "$actual" != "$expected" ]; then
      printf '%s no longer matches %s. Restore the setting or remove the related local secret files before reinitializing a fresh deployment.\n' \
        "$setting" "${path#"$ROOT"/}" >&2
      exit 1
    fi
  fi
}

require_record_username_match() {
  setting=$1
  path=$2
  expected=$3
  if [ -f "$path" ]; then
    record=$(sed -n '1p' "$path" | tr -d '\r')
    actual=${record%%:*}
    if [ "$actual" != "$expected" ]; then
      printf '%s no longer matches %s. Restore the setting or remove the related local secret files before reinitializing a fresh deployment.\n' \
        "$setting" "${path#"$ROOT"/}" >&2
      exit 1
    fi
  fi
}

require_command openssl

if [ ! -f "$ENV_FILE" ]; then
  cp "$ROOT/.env.example" "$ENV_FILE"
  printf 'Created %s from .env.example\n' "$ENV_FILE"
fi

umask 077
mkdir -p "$SECRETS_DIR"
chmod 700 "$SECRETS_DIR"

influxdb_username=$(read_setting INFLUXDB_USERNAME admin)
traefik_username=$(read_setting TRAEFIK_USERNAME admin)
mosquitto_username=$(read_setting MOSQUITTO_USERNAME home)
validate_username INFLUXDB_USERNAME "$influxdb_username"
validate_username TRAEFIK_USERNAME "$traefik_username"
validate_username MOSQUITTO_USERNAME "$mosquitto_username"

require_value_match \
  INFLUXDB_USERNAME \
  "$SECRETS_DIR/influxdb_username" \
  "$influxdb_username"
require_record_username_match \
  TRAEFIK_USERNAME \
  "$SECRETS_DIR/traefik_users" \
  "$traefik_username"
require_record_username_match \
  MOSQUITTO_USERNAME \
  "$SECRETS_DIR/mosquitto_passwords" \
  "$mosquitto_username"

write_text_if_missing "$SECRETS_DIR/influxdb_username" "$influxdb_username"
write_random_hex "$SECRETS_DIR/influxdb_password" 24
write_random_hex "$SECRETS_DIR/influxdb_token" 32
write_random_hex "$SECRETS_DIR/grafana_admin_password" 24
write_random_hex "$SECRETS_DIR/traefik_password" 18
write_random_hex "$SECRETS_DIR/mosquitto_password" 18
normalize_single_line_secret "$SECRETS_DIR/influxdb_token" influxdb_token

if [ ! -f "$SECRETS_DIR/traefik_users" ]; then
  ensure_docker
  traefik_record=$(
    printf '%s\n' "$(cat "$SECRETS_DIR/traefik_password")" |
      docker run --rm -i \
        --entrypoint htpasswd \
        "$HTPASSWD_IMAGE" \
        -n -i -B -C 12 "$traefik_username"
  )
  case "$traefik_record" in
    "$traefik_username":'$2y$12$'*)
      printf '%s\n' "$traefik_record" >"$SECRETS_DIR/traefik_users"
      ;;
    *)
      printf 'Unexpected htpasswd output; Traefik credentials were not written.\n' >&2
      exit 1
      ;;
  esac
fi

if [ ! -f "$SECRETS_DIR/mosquitto_passwords" ]; then
  ensure_docker
  mosquitto_record=$(
    printf '%s\n' "$(cat "$SECRETS_DIR/mosquitto_password")" |
      docker run --rm -i \
        --env MOSQUITTO_USERNAME="$mosquitto_username" \
        --entrypoint /bin/ash \
        "$MOSQUITTO_IMAGE" \
        -euc '
          umask 077
          IFS= read -r password
          printf "%s\n%s\n" "$password" "$password" |
            mosquitto_passwd -H sha512-pbkdf2 -I 220000 -c /tmp/mosquitto_passwords "$MOSQUITTO_USERNAME" >/tmp/mosquitto-passwd.log
          cat /tmp/mosquitto_passwords
        '
  )
  case "$mosquitto_record" in
    "$mosquitto_username":'$7$220000$'*)
      printf '%s\n' "$mosquitto_record" >"$SECRETS_DIR/mosquitto_passwords"
      ;;
    *)
      printf 'Unexpected mosquitto_passwd output; MQTT credentials were not written.\n' >&2
      exit 1
      ;;
  esac
fi

# Docker Compose implements file-backed secrets as bind mounts and cannot remap
# their ownership. Keep the directory private to this host user, while allowing
# non-root service users to read only the individual files mounted into them.
chmod 600 \
  "$SECRETS_DIR/traefik_password" \
  "$SECRETS_DIR/mosquitto_password"
chmod 644 \
  "$SECRETS_DIR/influxdb_username" \
  "$SECRETS_DIR/influxdb_password" \
  "$SECRETS_DIR/influxdb_token" \
  "$SECRETS_DIR/grafana_admin_password" \
  "$SECRETS_DIR/traefik_users" \
  "$SECRETS_DIR/mosquitto_passwords"

cat <<EOF_MESSAGE
Initialization complete.

Configuration: $ENV_FILE
Generated credentials: $SECRETS_DIR

Read a credential only when needed, for example:
  cat .secrets/grafana_admin_password
  cat .secrets/traefik_password
  cat .secrets/mosquitto_password
EOF_MESSAGE
