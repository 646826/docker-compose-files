#!/bin/sh
set -eu

ROOT=$(CDPATH= cd "$(dirname "$0")/.." && pwd)
WORKDIR=
PROJECT_NAME=
HTTP_PORT=
BASE_DOMAIN=community-runtime.localhost
RESPONSE_BODY=
HTPASSWD_IMAGE=

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    printf 'Required command not found: %s\n' "$1" >&2
    exit 1
  }
}

compose() {
  docker compose \
    --project-name "$PROJECT_NAME" \
    --env-file "$WORKDIR/.env" \
    -f "$WORKDIR/compose.yaml" \
    --profile uptime \
    --profile dashboard \
    --profile logs \
    "$@"
}

diagnostics() {
  printf '\nCommunity runtime diagnostics\n'
  printf '%s\n' '============================='
  compose ps --all || true
  printf '\nMerged services:\n'
  compose config --services || true
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

free_port() {
  python3 -c 'import socket; sock = socket.socket(); sock.bind(("127.0.0.1", 0)); print(sock.getsockname()[1]); sock.close()'
}

http_request() {
  host=$1
  config=$2
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
  curl "$@" "http://127.0.0.1:$HTTP_PORT/"
}

wait_http() {
  label=$1
  host=$2
  config=$3
  expected=$4
  attempt=1
  code=000
  while [ "$attempt" -le 90 ]; do
    if code=$(http_request "$host" "$config" 2>/dev/null); then
      if [ "$code" = "$expected" ]; then
        printf 'OK: %s\n' "$label"
        return 0
      fi
    else
      code=000
    fi
    attempt=$((attempt + 1))
    sleep 2
  done
  printf 'FAILED: %s returned HTTP %s, expected %s\n' "$label" "$code" "$expected" >&2
  head -c 500 "$RESPONSE_BODY" >&2 || true
  printf '\n' >&2
  return 1
}

for command in docker curl python3 openssl; do
  require_command "$command"
done
docker version >/dev/null
docker compose version >/dev/null

WORKDIR=$(mktemp -d "${TMPDIR:-/tmp}/homelab-community-runtime.XXXXXX")
chmod 700 "$WORKDIR"
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

PROJECT_NAME="homelab-community-runtime-$$-$(openssl rand -hex 4)"
HTTP_PORT=$(free_port)
PASSWORD=$(openssl rand -hex 18)
RESPONSE_BODY="$WORKDIR/response.body"

cp "$ROOT/compose.yaml" "$WORKDIR/compose.yaml"
cp -R "$ROOT/modules" "$WORKDIR/modules"
cp -R "$ROOT/config" "$WORKDIR/config"
mkdir "$WORKDIR/.secrets"
chmod 700 "$WORKDIR/.secrets"

cat >"$WORKDIR/.env" <<EOF
HOMELAB_PROJECT_NAME=$PROJECT_NAME
HOMELAB_HOST_ADDRESS=127.0.0.1
BASE_DOMAIN=$BASE_DOMAIN
HTTP_HOST_IP=127.0.0.1
HTTP_PORT=$HTTP_PORT
AUTH_MIDDLEWARE=local-auth@docker
MQTT_HOST_IP=127.0.0.1
MQTT_PORT=0
NETDATA_PORT=0
DNS_HOST_IP=127.0.0.1
DNS_PORT=0
ADGUARD_SETUP_HOST_IP=127.0.0.1
ADGUARD_SETUP_PORT=0
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
NETDATA_HOSTNAME=community-runtime
AUTHELIA_USERNAME=runtime
AUTHELIA_DISPLAY_NAME=Runtime User
AUTHELIA_EMAIL=runtime@example.test
K6_TARGET_URL=http://whoami
EOF
chmod 600 "$WORKDIR/.env"

printf '%s' runtime >"$WORKDIR/.secrets/influxdb_username"
printf '%s' runtime-password >"$WORKDIR/.secrets/influxdb_password"
printf '%s' runtime-token >"$WORKDIR/.secrets/influxdb_token"
printf '%s' runtime-password >"$WORKDIR/.secrets/grafana_admin_password"
printf '%s\n' 'runtime:$7$220000$placeholder$placeholder' >"$WORKDIR/.secrets/mosquitto_passwords"
printf '%s' runtime-jwt >"$WORKDIR/.secrets/authelia_jwt_secret"
printf '%s' runtime-session >"$WORKDIR/.secrets/authelia_session_secret"
printf '%s' runtime-storage >"$WORKDIR/.secrets/authelia_storage_encryption_key"
printf '%s\n' 'server: {address: tcp4://0.0.0.0:9091}' >"$WORKDIR/.secrets/authelia_configuration.yml"
printf '%s\n' 'users: {}' >"$WORKDIR/.secrets/authelia_users.yml"

HTPASSWD_IMAGE=$(sed -n 's/^HTPASSWD_IMAGE=//p' "$ROOT/scripts/init.sh" | tail -n 1)
if [ -z "$HTPASSWD_IMAGE" ]; then
  printf 'HTPASSWD_IMAGE is missing from scripts/init.sh\n' >&2
  exit 1
fi
record=$(
  printf '%s\n' "$PASSWORD" |
    docker run --rm -i \
      --entrypoint htpasswd \
      "$HTPASSWD_IMAGE" \
      -n -i -B -C 12 runtime
)
case "$record" in
  runtime:'$2y$12$'*) ;;
  *)
    printf 'Unexpected htpasswd output\n' >&2
    exit 1
    ;;
esac
printf '%s\n' "$record" >"$WORKDIR/.secrets/traefik_users"
chmod 644 "$WORKDIR/.secrets/"*

cat >"$WORKDIR/auth.curl" <<EOF
user = "runtime:$PASSWORD"
EOF
chmod 600 "$WORKDIR/auth.curl"

compose config --quiet
printf 'Starting isolated community project %s on 127.0.0.1:%s\n' "$PROJECT_NAME" "$HTTP_PORT"
compose up -d --wait --wait-timeout 300

expected_services=$(
  printf '%s\n' docker-socket-proxy traefik whoami uptime-kuma homepage dozzle | LC_ALL=C sort
)
actual_services=$(compose ps --services --all | LC_ALL=C sort)
if [ "$actual_services" != "$expected_services" ]; then
  printf 'FAILED: community runtime service set is not core + uptime + dashboard + logs\n' >&2
  exit 1
fi

for host in \
  uptime.community-runtime.localhost \
  home.community-runtime.localhost \
  logs.community-runtime.localhost
do
  wait_http "$host rejects anonymous requests" "$host" - 401
  wait_http "$host accepts generated Basic Auth" "$host" "$WORKDIR/auth.curl" 200
done

printf 'Community runtime smoke test passed\n'
