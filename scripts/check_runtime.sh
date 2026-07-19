#!/bin/sh
set -eu

ROOT=$(CDPATH= cd "$(dirname "$0")/.." && pwd)
WORKDIR=
PROJECT_NAME=
HTTP_PORT=
BASE_DOMAIN=runtime.localhost
TRAEFIK_USERNAME=runtime
GRAFANA_ADMIN_USER=runtime
INFLUXDB_USERNAME=runtime
INFLUXDB_ORG=runtime-org
INFLUXDB_BUCKET=runtime-bucket
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
    -f "$WORKDIR/compose.runtime.yaml" \
    --profile monitoring \
    --profile tools \
    "$@"
}

diagnostics() {
  printf '\nRuntime diagnostics\n'
  printf '%s\n' '===================' 
  compose ps --all || true
  printf '\nMerged services:\n'
  compose config --services || true
  printf '\nContainer states:\n'
  ids=$(compose ps -q 2>/dev/null || true)
  for id in $ids; do
    docker inspect \
      --format '{{.Name}} status={{.State.Status}} health={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' \
      "$id" || true
  done
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
      compose down --volumes --remove-orphans --timeout 20 >/dev/null 2>&1 || true
    fi
    rm -rf "$WORKDIR"
  fi
  exit "$status"
}

http_request() {
  host=$1
  path=$2
  config=$3
  : >"$RESPONSE_BODY"
  set -- \
    --silent \
    --show-error \
    --max-time 10 \
    --output "$RESPONSE_BODY" \
    --write-out '%{http_code}' \
    --header "Host: $host"
  if [ "$config" != "-" ]; then
    set -- "$@" --config "$config"
  fi
  curl "$@" "http://127.0.0.1:$HTTP_PORT$path"
}

wait_http() {
  label=$1
  host=$2
  path=$3
  config=$4
  expected_code=$5
  expected_pattern=$6
  attempt=1
  code=000
  while [ "$attempt" -le 60 ]; do
    if code=$(http_request "$host" "$path" "$config" 2>/dev/null); then
      if [ "$code" = "$expected_code" ]; then
        if [ -z "$expected_pattern" ] || grep -Eq "$expected_pattern" "$RESPONSE_BODY"; then
          printf 'OK: %s\n' "$label"
          return 0
        fi
      fi
    else
      code=000
    fi
    attempt=$((attempt + 1))
    sleep 2
  done
  printf 'FAILED: %s returned HTTP %s\n' "$label" "$code" >&2
  head -c 500 "$RESPONSE_BODY" >&2 || true
  printf '\n' >&2
  return 1
}

wait_for_metrics() {
  attempt=1
  code=000
  while [ "$attempt" -le 60 ]; do
    : >"$RESPONSE_BODY"
    if code=$(
      curl \
        --silent \
        --show-error \
        --max-time 10 \
        --output "$RESPONSE_BODY" \
        --write-out '%{http_code}' \
        --config "$WORKDIR/influx.curl" \
        --header "Host: influxdb.$BASE_DOMAIN" \
        --data-binary "@$WORKDIR/query.flux" \
        "http://127.0.0.1:$HTTP_PORT/api/v2/query?org=$INFLUXDB_ORG" \
        2>/dev/null
    ); then
      if [ "$code" = "200" ] && grep -q 'system' "$RESPONSE_BODY"; then
        printf 'OK: Telegraf metrics reached InfluxDB\n'
        return 0
      fi
    else
      code=000
    fi
    attempt=$((attempt + 1))
    sleep 2
  done
  printf 'FAILED: InfluxDB query returned HTTP %s without a system measurement\n' "$code" >&2
  head -c 500 "$RESPONSE_BODY" >&2 || true
  printf '\n' >&2
  return 1
}

for command in docker curl python3 openssl; do
  require_command "$command"
done

docker version >/dev/null
docker compose version >/dev/null

WORKDIR=$(mktemp -d "${TMPDIR:-/tmp}/homelab-runtime.XXXXXX")
chmod 700 "$WORKDIR"
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

PROJECT_NAME="homelab-runtime-$$-$(openssl rand -hex 4)"
HTTP_PORT=$(
  python3 -c 'import socket; sock = socket.socket(); sock.bind(("127.0.0.1", 0)); print(sock.getsockname()[1]); sock.close()'
)
TRAEFIK_PASSWORD=$(openssl rand -hex 18)
GRAFANA_ADMIN_PASSWORD=$(openssl rand -hex 24)
INFLUXDB_PASSWORD=$(openssl rand -hex 24)
INFLUXDB_TOKEN=$(openssl rand -hex 32)
RESPONSE_BODY="$WORKDIR/response.body"

cp "$ROOT/compose.yaml" "$WORKDIR/compose.yaml"
cp "$ROOT/compose.runtime.yaml" "$WORKDIR/compose.runtime.yaml"
cp -R "$ROOT/config" "$WORKDIR/config"
mkdir "$WORKDIR/.secrets"
chmod 700 "$WORKDIR/.secrets"

cat >"$WORKDIR/.env" <<EOF
HOMELAB_PROJECT_NAME=$PROJECT_NAME
BASE_DOMAIN=$BASE_DOMAIN
HTTP_HOST_IP=127.0.0.1
HTTP_PORT=$HTTP_PORT
MQTT_PORT=1883
TZ=Etc/UTC
TRAEFIK_LOG_LEVEL=INFO
TRAEFIK_USERNAME=$TRAEFIK_USERNAME
GRAFANA_ADMIN_USER=$GRAFANA_ADMIN_USER
INFLUXDB_USERNAME=$INFLUXDB_USERNAME
INFLUXDB_ORG=$INFLUXDB_ORG
INFLUXDB_BUCKET=$INFLUXDB_BUCKET
INFLUXDB_RETENTION=1h
MOSQUITTO_USERNAME=runtime
OPENHAB_UID=9001
OPENHAB_GID=9001
NETDATA_HOSTNAME=runtime
K6_TARGET_URL=http://whoami
EOF
chmod 600 "$WORKDIR/.env"

printf '%s\n' "$INFLUXDB_USERNAME" >"$WORKDIR/.secrets/influxdb_username"
printf '%s\n' "$INFLUXDB_PASSWORD" >"$WORKDIR/.secrets/influxdb_password"
printf '%s\n' "$INFLUXDB_TOKEN" >"$WORKDIR/.secrets/influxdb_token"
printf '%s\n' "$GRAFANA_ADMIN_PASSWORD" >"$WORKDIR/.secrets/grafana_admin_password"
printf '%s\n' 'runtime:$argon2id$v=19$m=19456,t=2,p=1$placeholder$placeholder' \
  >"$WORKDIR/.secrets/mosquitto_passwords"

HTPASSWD_IMAGE=$(sed -n 's/^HTPASSWD_IMAGE=//p' "$ROOT/scripts/init.sh" | tail -n 1)
if [ -z "$HTPASSWD_IMAGE" ]; then
  printf 'HTPASSWD_IMAGE is missing from scripts/init.sh\n' >&2
  exit 1
fi
traefik_record=$(
  printf '%s\n' "$TRAEFIK_PASSWORD" |
    docker run --rm -i \
      --entrypoint htpasswd \
      "$HTPASSWD_IMAGE" \
      -n -i -B -C 12 "$TRAEFIK_USERNAME"
)
case "$traefik_record" in
  "$TRAEFIK_USERNAME":'$2y$12$'*)
    ;;
  *)
    printf 'Unexpected htpasswd output; runtime credentials were not accepted.\n' >&2
    exit 1
    ;;
esac
printf '%s\n' "$traefik_record" >"$WORKDIR/.secrets/traefik_users"
chmod 644 "$WORKDIR/.secrets/"*

cat >"$WORKDIR/traefik.curl" <<EOF
user = "$TRAEFIK_USERNAME:$TRAEFIK_PASSWORD"
EOF
cat >"$WORKDIR/grafana.curl" <<EOF
user = "$GRAFANA_ADMIN_USER:$GRAFANA_ADMIN_PASSWORD"
EOF
cat >"$WORKDIR/influx.curl" <<EOF
header = "Authorization: Token $INFLUXDB_TOKEN"
header = "Content-Type: application/vnd.flux"
header = "Accept: application/csv"
EOF
chmod 600 "$WORKDIR/traefik.curl" "$WORKDIR/grafana.curl" "$WORKDIR/influx.curl"

cat >"$WORKDIR/query.flux" <<EOF
from(bucket: "$INFLUXDB_BUCKET")
  |> range(start: -5m)
  |> filter(fn: (r) => r._measurement == "system")
  |> limit(n: 1)
EOF
chmod 600 "$WORKDIR/query.flux"

compose config --quiet
printf 'Starting isolated runtime project %s on 127.0.0.1:%s\n' "$PROJECT_NAME" "$HTTP_PORT"
compose up --wait --wait-timeout 240

actual_services=$(compose ps --services --all)
for service in docker-socket-proxy traefik whoami influxdb telegraf grafana portainer; do
  if ! printf '%s\n' "$actual_services" | grep -qx "$service"; then
    printf 'FAILED: expected service is missing: %s\n' "$service" >&2
    exit 1
  fi
done

wait_http \
  "whoami rejects anonymous requests" \
  "whoami.$BASE_DOMAIN" \
  "/" \
  "-" \
  "401" \
  ""
wait_http \
  "whoami accepts generated Basic Auth" \
  "whoami.$BASE_DOMAIN" \
  "/" \
  "$WORKDIR/traefik.curl" \
  "200" \
  ""
wait_http \
  "Traefik dashboard rejects anonymous requests" \
  "traefik.$BASE_DOMAIN" \
  "/dashboard/" \
  "-" \
  "401" \
  ""
wait_http \
  "Traefik dashboard accepts generated Basic Auth" \
  "traefik.$BASE_DOMAIN" \
  "/dashboard/" \
  "$WORKDIR/traefik.curl" \
  "200" \
  ""
wait_http \
  "InfluxDB health route" \
  "influxdb.$BASE_DOMAIN" \
  "/health" \
  "-" \
  "200" \
  '"status"[[:space:]]*:[[:space:]]*"pass"'
wait_http \
  "Grafana database health" \
  "grafana.$BASE_DOMAIN" \
  "/api/health" \
  "-" \
  "200" \
  '"database"[[:space:]]*:[[:space:]]*"ok"'
wait_http \
  "Portainer status route" \
  "portainer.$BASE_DOMAIN" \
  "/api/status" \
  "-" \
  "200" \
  ""
wait_http \
  "Grafana provisioned InfluxDB datasource" \
  "grafana.$BASE_DOMAIN" \
  "/api/datasources/uid/influxdb" \
  "$WORKDIR/grafana.curl" \
  "200" \
  '"uid"[[:space:]]*:[[:space:]]*"influxdb"'
wait_for_metrics

printf 'Runtime smoke test passed\n'
