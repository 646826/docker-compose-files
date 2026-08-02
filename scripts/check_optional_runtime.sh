#!/bin/sh
set -eu

ROOT=$(CDPATH= cd "$(dirname "$0")/.." && pwd)
WORKDIR=
PROJECT_NAME=
NETDATA_PORT=
RESPONSE_BODY=

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'Required command not found: %s\n' "$1" >&2
    exit 1
  fi
}

compose() {
  docker compose \
    --project-name "$PROJECT_NAME" \
    --env-file "$WORKDIR/.env" \
    -f "$WORKDIR/compose.yaml" \
    --profile netdata \
    --profile test \
    "$@"
}

diagnostics() {
  printf '\nOptional runtime diagnostics\n'
  printf '%s\n' '============================'
  compose ps --all || true
  printf '\nLast 200 log lines:\n'
  compose logs --no-color --tail=200 || true
}

cleanup() {
  status=$?
  trap - EXIT HUP INT TERM
  if [ -n "$WORKDIR" ] && [ -d "$WORKDIR" ]; then
    if [ -n "$PROJECT_NAME" ] && [ -f "$WORKDIR/.env" ]; then
      if [ "$status" -ne 0 ]; then
        diagnostics || true
      fi
      compose down --volumes --remove-orphans --timeout 30 >/dev/null 2>&1 || true
    fi
    rm -rf "$WORKDIR"
  fi
  exit "$status"
}

valid_info_response() {
  python3 - "$RESPONSE_BODY" <<'PY'
import json
from pathlib import Path
import sys

try:
    document = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except (OSError, UnicodeDecodeError, json.JSONDecodeError):
    raise SystemExit(1)

if not isinstance(document, dict):
    raise SystemExit(1)
PY
}

valid_cpu_response() {
  python3 - "$RESPONSE_BODY" <<'PY'
import json
from pathlib import Path
import sys

try:
    document = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except (OSError, UnicodeDecodeError, json.JSONDecodeError):
    raise SystemExit(1)

if not isinstance(document, dict):
    raise SystemExit(1)
identity = " ".join(
    str(document.get(field, ""))
    for field in ("id", "name")
)
if "system.cpu" not in identity:
    raise SystemExit(1)
result = document.get("result")
if not isinstance(result, dict):
    raise SystemExit(1)
data = result.get("data")
if not isinstance(data, list) or not data:
    raise SystemExit(1)
PY
}

wait_for_netdata() {
  attempt=1
  while [ "$attempt" -le 60 ]; do
    : >"$RESPONSE_BODY"
    if curl \
      --fail \
      --silent \
      --show-error \
      --max-time 5 \
      --output "$RESPONSE_BODY" \
      "http://127.0.0.1:$NETDATA_PORT/api/v1/info" \
      2>/dev/null && valid_info_response; then
      printf 'OK: Netdata API is ready\n'
      return 0
    fi
    attempt=$((attempt + 1))
    sleep 2
  done

  printf 'FAILED: Netdata API did not become ready on 127.0.0.1:%s\n' "$NETDATA_PORT" >&2
  head -c 500 "$RESPONSE_BODY" >&2 || true
  printf '\n' >&2
  return 1
}

wait_for_cpu_metrics() {
  attempt=1
  while [ "$attempt" -le 60 ]; do
    : >"$RESPONSE_BODY"
    if curl \
      --fail \
      --silent \
      --show-error \
      --max-time 5 \
      --output "$RESPONSE_BODY" \
      "http://127.0.0.1:$NETDATA_PORT/api/v1/data?chart=system.cpu&points=1&after=-10&format=json&options=jsonwrap" \
      2>/dev/null && valid_cpu_response; then
      printf 'OK: Netdata collected a system.cpu sample\n'
      return 0
    fi
    attempt=$((attempt + 1))
    sleep 2
  done

  printf 'FAILED: Netdata returned no system.cpu sample\n' >&2
  head -c 500 "$RESPONSE_BODY" >&2 || true
  printf '\n' >&2
  return 1
}

for command in docker curl python3 openssl; do
  require_command "$command"
done

docker version >/dev/null
docker compose version >/dev/null

WORKDIR=$(mktemp -d "${TMPDIR:-/tmp}/homelab-optional-runtime.XXXXXX")
chmod 700 "$WORKDIR"
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

PROJECT_NAME="homelab-optional-runtime-$$-$(openssl rand -hex 4)"
NETDATA_PORT=$(
  python3 -c 'import socket; sock = socket.socket(); sock.bind(("127.0.0.1", 0)); print(sock.getsockname()[1]); sock.close()'
)
RESPONSE_BODY="$WORKDIR/response.body"

cp "$ROOT/compose.yaml" "$WORKDIR/compose.yaml"
cp -R "$ROOT/config" "$WORKDIR/config"
mkdir "$WORKDIR/.secrets"
chmod 700 "$WORKDIR/.secrets"

cat >"$WORKDIR/.env" <<EOF
HOMELAB_PROJECT_NAME=$PROJECT_NAME
BASE_DOMAIN=optional-runtime.localhost
HTTP_HOST_IP=127.0.0.1
HTTP_PORT=0
MQTT_HOST_IP=127.0.0.1
MQTT_PORT=0
NETDATA_PORT=$NETDATA_PORT
TZ=Etc/UTC
TRAEFIK_LOG_LEVEL=INFO
TRAEFIK_USERNAME=runtime
GRAFANA_ADMIN_USER=runtime
INFLUXDB_USERNAME=runtime
INFLUXDB_ORG=runtime-org
INFLUXDB_BUCKET=runtime-bucket
INFLUXDB_RETENTION=1h
MOSQUITTO_USERNAME=runtime
OPENHAB_UID=9001
OPENHAB_GID=9001
NETDATA_HOSTNAME=optional-runtime
K6_TARGET_URL=http://whoami
EOF
chmod 600 "$WORKDIR/.env"

printf '%s\n' runtime >"$WORKDIR/.secrets/influxdb_username"
printf '%s\n' runtime-password >"$WORKDIR/.secrets/influxdb_password"
printf '%s\n' runtime-token >"$WORKDIR/.secrets/influxdb_token"
printf '%s\n' runtime-password >"$WORKDIR/.secrets/grafana_admin_password"
printf '%s\n' 'runtime:$2y$12$placeholder' >"$WORKDIR/.secrets/traefik_users"
printf '%s\n' 'runtime:$7$220000$placeholder$placeholder' \
  >"$WORKDIR/.secrets/mosquitto_passwords"
chmod 600 "$WORKDIR/.secrets/"*

compose config --quiet
printf 'Starting isolated Netdata on 127.0.0.1:%s\n' "$NETDATA_PORT"
compose up -d netdata
wait_for_netdata
wait_for_cpu_metrics

printf 'Starting isolated whoami target for k6\n'
compose up -d whoami
compose run --rm k6
printf 'OK: k6 smoke thresholds passed\n'

actual_services=$(compose ps --services --all)
for service in netdata whoami; do
  if ! printf '%s\n' "$actual_services" | grep -qx "$service"; then
    printf 'FAILED: expected service is missing: %s\n' "$service" >&2
    exit 1
  fi
done
for service in docker-socket-proxy traefik influxdb telegraf grafana portainer mosquitto openhab; do
  if printf '%s\n' "$actual_services" | grep -qx "$service"; then
    printf 'FAILED: unexpected service was started: %s\n' "$service" >&2
    exit 1
  fi
done

printf 'Optional runtime smoke test passed\n'
