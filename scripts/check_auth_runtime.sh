#!/bin/sh
set -eu

ROOT=$(CDPATH= cd "$(dirname "$0")/.." && pwd)
WORKDIR=
PROJECT_NAME=
HTTP_PORT=
BASE_DOMAIN=auth-runtime.example.test
RESPONSE_BODY=
RESPONSE_HEADERS=
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
    --profile auth \
    --profile dashboard \
    "$@"
}

diagnostics() {
  printf '\nAuth runtime diagnostics\n'
  printf '%s\n' '========================'
  compose ps --all || true
  printf '\nMerged services:\n'
  compose config --services || true
  printf '\nLast 200 log lines:\n'
  compose logs --no-color --tail=200 || true
  if [ -n "$RESPONSE_HEADERS" ] && [ -s "$RESPONSE_HEADERS" ]; then
    printf '\nLast HTTP response headers:\n'
    head -c 2000 "$RESPONSE_HEADERS" || true
    printf '\n'
  fi
  if [ -n "$RESPONSE_BODY" ] && [ -s "$RESPONSE_BODY" ]; then
    printf '\nLast HTTP response body bytes:\n'
    head -c 1000 "$RESPONSE_BODY" || true
    printf '\n'
  fi
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

request() {
  host=$1
  : >"$RESPONSE_HEADERS"
  : >"$RESPONSE_BODY"
  curl \
    --silent \
    --show-error \
    --max-time 10 \
    --dump-header "$RESPONSE_HEADERS" \
    --output "$RESPONSE_BODY" \
    --write-out '%{http_code}' \
    --header "Host: $host" \
    --header 'Accept: text/html,application/xhtml+xml' \
    "http://127.0.0.1:$HTTP_PORT/"
}

wait_portal() {
  host=$1
  attempt=1
  code=000
  while [ "$attempt" -le 90 ]; do
    if code=$(request "$host" 2>/dev/null); then
      if [ "$code" = "200" ] && grep -qi 'authelia' "$RESPONSE_BODY"; then
        printf 'OK: Authelia portal is reachable through Traefik\n'
        return 0
      fi
    else
      code=000
    fi
    attempt=$((attempt + 1))
    sleep 2
  done
  printf 'FAILED: Authelia portal returned HTTP %s\n' "$code" >&2
  return 1
}

wait_forwardauth_redirect() {
  host=$1
  attempt=1
  code=000
  expected="https://auth.$BASE_DOMAIN"
  while [ "$attempt" -le 90 ]; do
    if code=$(request "$host" 2>/dev/null); then
      if [ "$code" = "302" ] && grep -Fiq "location: $expected" "$RESPONSE_HEADERS"; then
        printf 'OK: Traefik ForwardAuth redirects to the Authelia portal\n'
        return 0
      fi
    else
      code=000
    fi
    attempt=$((attempt + 1))
    sleep 2
  done
  printf 'FAILED: protected route returned HTTP %s without redirect to %s\n' "$code" "$expected" >&2
  return 1
}

for command in docker curl python3 openssl; do
  require_command "$command"
done
docker version >/dev/null
docker compose version >/dev/null

WORKDIR=$(mktemp -d "${TMPDIR:-/tmp}/homelab-auth-runtime.XXXXXX")
chmod 700 "$WORKDIR"
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

PROJECT_NAME="homelab-auth-runtime-$$-$(openssl rand -hex 4)"
HTTP_PORT=$(free_port)
RESPONSE_BODY="$WORKDIR/response.body"
RESPONSE_HEADERS="$WORKDIR/response.headers"

cp "$ROOT/compose.yaml" "$WORKDIR/compose.yaml"
cp -R "$ROOT/modules" "$WORKDIR/modules"
cp -R "$ROOT/config" "$WORKDIR/config"
mkdir "$WORKDIR/scripts" "$WORKDIR/.secrets"
chmod 700 "$WORKDIR/.secrets"
cp "$ROOT/scripts/init_community.py" "$WORKDIR/scripts/init_community.py"
cp "$ROOT/scripts/doctor.py" "$WORKDIR/scripts/doctor.py"

cat >"$WORKDIR/.env" <<EOF
HOMELAB_PROJECT_NAME=$PROJECT_NAME
HOMELAB_HOST_ADDRESS=127.0.0.1
BASE_DOMAIN=$BASE_DOMAIN
HTTP_HOST_IP=127.0.0.1
HTTP_PORT=$HTTP_PORT
AUTH_MIDDLEWARE=authelia@docker
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
NETDATA_HOSTNAME=auth-runtime
AUTHELIA_USERNAME=runtime
AUTHELIA_DISPLAY_NAME=Runtime User
AUTHELIA_EMAIL=runtime@$BASE_DOMAIN
K6_TARGET_URL=http://whoami
EOF
chmod 600 "$WORKDIR/.env"

printf '%s' runtime >"$WORKDIR/.secrets/influxdb_username"
printf '%s' runtime-password >"$WORKDIR/.secrets/influxdb_password"
printf '%s' runtime-token >"$WORKDIR/.secrets/influxdb_token"
printf '%s' runtime-password >"$WORKDIR/.secrets/grafana_admin_password"
printf '%s\n' 'runtime:$7$220000$placeholder$placeholder' >"$WORKDIR/.secrets/mosquitto_passwords"

HTPASSWD_IMAGE=$(sed -n 's/^HTPASSWD_IMAGE=//p' "$ROOT/scripts/init.sh" | tail -n 1)
if [ -z "$HTPASSWD_IMAGE" ]; then
  printf 'HTPASSWD_IMAGE is missing from scripts/init.sh\n' >&2
  exit 1
fi
TRAEFIK_PASSWORD=$(openssl rand -hex 18)
traefik_record=$(
  printf '%s\n' "$TRAEFIK_PASSWORD" |
    docker run --rm -i \
      --entrypoint htpasswd \
      "$HTPASSWD_IMAGE" \
      -n -i -B -C 12 runtime
)
case "$traefik_record" in
  runtime:'$2y$12$'*) ;;
  *)
    printf 'Unexpected htpasswd output for Traefik runtime credentials\n' >&2
    exit 1
    ;;
esac
printf '%s\n' "$traefik_record" >"$WORKDIR/.secrets/traefik_users"
chmod 644 "$WORKDIR/.secrets/"*

(
  cd "$WORKDIR"
  python3 "$WORKDIR/scripts/init_community.py"
)

AUTHELIA_IMAGE=$(sed -n 's/^    image: //p' "$WORKDIR/modules/auth/compose.yaml" | head -n 1)
if [ -z "$AUTHELIA_IMAGE" ]; then
  printf 'Pinned Authelia image is missing from the auth module\n' >&2
  exit 1
fi

docker run --rm \
  --volume "$WORKDIR/.secrets/authelia_configuration.yml:/config/configuration.yml:ro" \
  --volume "$WORKDIR/.secrets/authelia_users.yml:/config/users_database.yml:ro" \
  --volume "$WORKDIR/.secrets/authelia_jwt_secret:/run/secrets/authelia_jwt_secret:ro" \
  --volume "$WORKDIR/.secrets/authelia_session_secret:/run/secrets/authelia_session_secret:ro" \
  --volume "$WORKDIR/.secrets/authelia_storage_encryption_key:/run/secrets/authelia_storage_encryption_key:ro" \
  --env AUTHELIA_IDENTITY_VALIDATION_RESET_PASSWORD_JWT_SECRET_FILE=/run/secrets/authelia_jwt_secret \
  --env AUTHELIA_SESSION_SECRET_FILE=/run/secrets/authelia_session_secret \
  --env AUTHELIA_STORAGE_ENCRYPTION_KEY_FILE=/run/secrets/authelia_storage_encryption_key \
  "$AUTHELIA_IMAGE" \
  authelia config validate --config /config/configuration.yml

compose config --quiet
printf 'Starting isolated auth project %s on 127.0.0.1:%s\n' "$PROJECT_NAME" "$HTTP_PORT"
compose up -d --wait --wait-timeout 300

expected_services=$(
  printf '%s\n' authelia docker-socket-proxy homepage traefik whoami | LC_ALL=C sort
)
actual_services=$(compose ps --services --all | LC_ALL=C sort)
if [ "$actual_services" != "$expected_services" ]; then
  printf 'FAILED: auth runtime service set is not core + dashboard + auth\n' >&2
  exit 1
fi

wait_portal "auth.$BASE_DOMAIN"
wait_forwardauth_redirect "home.$BASE_DOMAIN"

printf 'Auth runtime smoke test passed\n'
