#!/bin/sh
set -eu

ROOT=$(CDPATH= cd "$(dirname "$0")/.." && pwd)
SECRETS_DIR="$ROOT/.secrets"
CREATED_DIR=0
CREATED_FILES=""

cleanup() {
  for path in $CREATED_FILES; do
    rm -f "$path"
  done
  if [ "$CREATED_DIR" -eq 1 ]; then
    rmdir "$SECRETS_DIR" 2>/dev/null || true
  fi
}
trap cleanup EXIT HUP INT TERM

cd "$ROOT"
python3 scripts/check_static.py
python3 scripts/check_runtime_policy.py
python3 scripts/check_iot_runtime_policy.py
python3 scripts/check_backup_policy.py
python3 scripts/test_init.py
python3 scripts/test_check_images.py
python3 scripts/test_runtime.py
python3 scripts/test_iot_runtime.py
python3 scripts/test_backup.py

for script in scripts/*.sh; do
  sh -n "$script"
done

if ! command -v docker >/dev/null 2>&1; then
  printf 'Docker is required for Compose validation.\n' >&2
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  printf 'The Docker Compose plugin (`docker compose`) is required.\n' >&2
  exit 1
fi

umask 077
if [ ! -d "$SECRETS_DIR" ]; then
  mkdir "$SECRETS_DIR"
  CREATED_DIR=1
fi

create_placeholder() {
  name=$1
  value=$2
  path="$SECRETS_DIR/$name"
  if [ ! -f "$path" ]; then
    printf '%s\n' "$value" >"$path"
    CREATED_FILES="$CREATED_FILES $path"
  fi
}

create_placeholder influxdb_username ci-user
create_placeholder influxdb_password ci-password
create_placeholder influxdb_token ci-token
create_placeholder grafana_admin_password ci-password
create_placeholder traefik_users 'ci:$2y$12$placeholder'
create_placeholder mosquitto_passwords 'ci:$argon2id$v=19$m=19456,t=2,p=1$placeholder$placeholder'

PROFILES="--profile monitoring --profile tools --profile iot --profile netdata --profile test"
docker compose --env-file .env.example $PROFILES config --quiet

for image in $(docker compose --env-file .env.example $PROFILES config --images); do
  final_component=${image##*/}
  case "$final_component" in
    *:latest)
      printf 'Image uses latest: %s\n' "$image" >&2
      exit 1
      ;;
    *:*)
      ;;
    *)
      printf 'Image has an implicit tag: %s\n' "$image" >&2
      exit 1
      ;;
  esac
done

printf 'All checks passed\n'
