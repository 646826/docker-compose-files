#!/bin/sh
set -eu

ROOT=$(CDPATH= cd "$(dirname "$0")/.." && pwd)
WORKDIR=
PROJECT_NAME=
HTTP_PORT=
MQTT_PORT=
BASE_DOMAIN=iot-runtime.localhost
OPENHAB_HOST="openhab.$BASE_DOMAIN"
MOSQUITTO_USERNAME=runtime
HTPASSWD_IMAGE=
MOSQUITTO_IMAGE=
MQTT_STATUS=
OPENHAB_BODY=

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
    --profile iot \
    "$@"
}

record_mqtt_status() {
  label=$1
  status=$2
  if [ -n "$MQTT_STATUS" ]; then
    printf '%s=%s\n' "$label" "$status" >>"$MQTT_STATUS"
  fi
}

diagnostics() {
  printf '\nIoT runtime diagnostics\n'
  printf '%s\n' '======================='
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
  if [ -n "$MQTT_STATUS" ] && [ -s "$MQTT_STATUS" ]; then
    printf '\nMQTT operation statuses:\n'
    cat "$MQTT_STATUS"
  fi
  if [ -n "$OPENHAB_BODY" ] && [ -s "$OPENHAB_BODY" ]; then
    printf '\nLast openHAB response bytes:\n'
    head -c 500 "$OPENHAB_BODY" || true
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

mqtt_pub_authenticated() {
  docker run --rm --network host \
    --volume "$WORKDIR/mosquitto-client.conf:/run/mosquitto-client.conf:ro" \
    --entrypoint mosquitto_pub \
    "$MOSQUITTO_IMAGE" \
    -o /run/mosquitto-client.conf \
    -h 127.0.0.1 \
    -p "$MQTT_PORT" \
    "$@"
}

mqtt_sub_authenticated() {
  docker run --rm --network host \
    --volume "$WORKDIR/mosquitto-client.conf:/run/mosquitto-client.conf:ro" \
    --entrypoint mosquitto_sub \
    "$MOSQUITTO_IMAGE" \
    -o /run/mosquitto-client.conf \
    -h 127.0.0.1 \
    -p "$MQTT_PORT" \
    "$@"
}

mqtt_pub_anonymous() {
  docker run --rm --network host \
    --entrypoint mosquitto_pub \
    "$MOSQUITTO_IMAGE" \
    -h 127.0.0.1 \
    -p "$MQTT_PORT" \
    "$@"
}

wait_for_broker() {
  label=$1
  topic=$2
  attempt=1
  last_status=1
  while [ "$attempt" -le 60 ]; do
    if mqtt_pub_authenticated \
      -t "$topic" \
      -m ready \
      >"$WORKDIR/mqtt-ready.out" 2>"$WORKDIR/mqtt-ready.err"; then
      record_mqtt_status "$label" 0
      printf 'OK: %s\n' "$label"
      return 0
    else
      last_status=$?
    fi
    attempt=$((attempt + 1))
    sleep 2
  done
  record_mqtt_status "$label" "$last_status"
  printf 'FAILED: %s did not become ready within 120 seconds\n' "$label" >&2
  return 1
}

subscribe_exact() {
  label=$1
  topic=$2
  expected=$3
  output=
  if output=$(mqtt_sub_authenticated \
    -t "$topic" \
    -C 1 \
    -W 20 \
    2>"$WORKDIR/mqtt-sub.err"); then
    record_mqtt_status "$label" 0
  else
    status=$?
    record_mqtt_status "$label" "$status"
    printf 'FAILED: %s exited with status %s\n' "$label" "$status" >&2
    return 1
  fi
  if [ "$output" != "$expected" ]; then
    record_mqtt_status "${label}_payload_match" 1
    printf 'FAILED: %s returned an unexpected payload\n' "$label" >&2
    return 1
  fi
  record_mqtt_status "${label}_payload_match" 0
  printf 'OK: %s\n' "$label"
}

wait_for_openhab() {
  attempt=1
  code=000
  while [ "$attempt" -le 120 ]; do
    : >"$OPENHAB_BODY"
    if code=$(
      curl \
        --silent \
        --show-error \
        --location \
        --max-redirs 5 \
        --max-time 15 \
        --resolve "$OPENHAB_HOST:$HTTP_PORT:127.0.0.1" \
        --output "$OPENHAB_BODY" \
        --write-out '%{http_code}' \
        "http://$OPENHAB_HOST:$HTTP_PORT/" \
        2>"$WORKDIR/openhab.curl.err"
    ); then
      if [ "$code" = "200" ] && grep -qi 'openhab' "$OPENHAB_BODY"; then
        printf 'OK: openHAB is ready through Traefik\n'
        return 0
      fi
    else
      code=000
    fi
    attempt=$((attempt + 1))
    sleep 5
  done
  printf 'FAILED: openHAB did not become ready within 600 seconds; final HTTP %s\n' "$code" >&2
  return 1
}

for command in docker curl python3 openssl; do
  require_command "$command"
done

docker version >/dev/null
docker compose version >/dev/null

WORKDIR=$(mktemp -d "${TMPDIR:-/tmp}/homelab-iot-runtime.XXXXXX")
chmod 700 "$WORKDIR"
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

PROJECT_NAME="homelab-iot-runtime-$$-$(openssl rand -hex 4)"
HTTP_PORT=$(free_port)
MQTT_PORT=$(free_port)
while [ "$MQTT_PORT" = "$HTTP_PORT" ]; do
  MQTT_PORT=$(free_port)
done
TRAEFIK_PASSWORD=$(openssl rand -hex 18)
MQTT_PASSWORD=$(openssl rand -hex 18)
RETAINED_PAYLOAD=$(openssl rand -hex 12)
PROBE_TOPIC="homelab/runtime/$PROJECT_NAME/probe"
RETAINED_TOPIC="homelab/runtime/$PROJECT_NAME/retained"
MQTT_STATUS="$WORKDIR/mqtt-status.log"
OPENHAB_BODY="$WORKDIR/openhab.body"
: >"$MQTT_STATUS"

HTPASSWD_IMAGE=$(sed -n 's/^HTPASSWD_IMAGE=//p' "$ROOT/scripts/init.sh" | tail -n 1)
MOSQUITTO_IMAGE=$(sed -n 's/^MOSQUITTO_IMAGE=//p' "$ROOT/scripts/init.sh" | tail -n 1)
if [ -z "$HTPASSWD_IMAGE" ] || [ -z "$MOSQUITTO_IMAGE" ]; then
  printf 'Pinned bootstrap helper image assignments are missing from scripts/init.sh\n' >&2
  exit 1
fi

cp "$ROOT/compose.yaml" "$WORKDIR/compose.yaml"
cp -R "$ROOT/config" "$WORKDIR/config"
mkdir "$WORKDIR/.secrets"
chmod 700 "$WORKDIR/.secrets"

cat >"$WORKDIR/.env" <<EOF
HOMELAB_PROJECT_NAME=$PROJECT_NAME
BASE_DOMAIN=$BASE_DOMAIN
HTTP_HOST_IP=127.0.0.1
HTTP_PORT=$HTTP_PORT
MQTT_HOST_IP=127.0.0.1
MQTT_PORT=$MQTT_PORT
TZ=Etc/UTC
TRAEFIK_LOG_LEVEL=INFO
TRAEFIK_USERNAME=runtime
GRAFANA_ADMIN_USER=runtime
INFLUXDB_USERNAME=runtime
INFLUXDB_ORG=runtime-org
INFLUXDB_BUCKET=runtime-bucket
INFLUXDB_RETENTION=1h
MOSQUITTO_USERNAME=$MOSQUITTO_USERNAME
OPENHAB_UID=9001
OPENHAB_GID=9001
NETDATA_HOSTNAME=iot-runtime
K6_TARGET_URL=http://whoami
EOF
chmod 600 "$WORKDIR/.env"

printf '%s' runtime >"$WORKDIR/.secrets/influxdb_username"
printf '%s' runtime-password >"$WORKDIR/.secrets/influxdb_password"
printf '%s' runtime-token >"$WORKDIR/.secrets/influxdb_token"
printf '%s' runtime-password >"$WORKDIR/.secrets/grafana_admin_password"

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
    printf 'Unexpected htpasswd output; IoT runtime credentials were not accepted.\n' >&2
    exit 1
    ;;
esac
printf '%s\n' "$traefik_record" >"$WORKDIR/.secrets/traefik_users"

mosquitto_record=$(
  printf '%s\n' "$MQTT_PASSWORD" |
    docker run --rm -i \
      --env MOSQUITTO_USERNAME="$MOSQUITTO_USERNAME" \
      --entrypoint /bin/ash \
      "$MOSQUITTO_IMAGE" \
      -euc '
        umask 077
        IFS= read -r password
        printf "%s:%s\n" "$MOSQUITTO_USERNAME" "$password" >/tmp/mosquitto_passwords
        mosquitto_passwd -U /tmp/mosquitto_passwords
        cat /tmp/mosquitto_passwords
      '
)
case "$mosquitto_record" in
  "$MOSQUITTO_USERNAME":'$argon2id$'*) ;;
  *)
    printf 'Unexpected mosquitto_passwd output; IoT runtime credentials were not accepted.\n' >&2
    exit 1
    ;;
esac
printf '%s\n' "$mosquitto_record" >"$WORKDIR/.secrets/mosquitto_passwords"
chmod 644 "$WORKDIR/.secrets/"*

cat >"$WORKDIR/mosquitto-client.conf" <<EOF
-u $MOSQUITTO_USERNAME
-P $MQTT_PASSWORD
EOF
chmod 600 "$WORKDIR/mosquitto-client.conf"

compose config --quiet
printf 'Starting isolated IoT project %s on HTTP 127.0.0.1:%s and MQTT 127.0.0.1:%s\n' \
  "$PROJECT_NAME" "$HTTP_PORT" "$MQTT_PORT"
compose up -d

expected_services=$(
  printf '%s\n' docker-socket-proxy traefik whoami mosquitto openhab | LC_ALL=C sort
)
actual_services=$(compose ps --services --all | LC_ALL=C sort)
if [ "$actual_services" != "$expected_services" ]; then
  printf 'FAILED: IoT runtime service set does not match the expected core + iot scope\n' >&2
  exit 1
fi

wait_for_broker "Mosquitto authenticated readiness" "$PROBE_TOPIC"

if mqtt_pub_anonymous \
  -t "$PROBE_TOPIC/anonymous" \
  -m anonymous \
  >"$WORKDIR/mqtt-anonymous.out" 2>"$WORKDIR/mqtt-anonymous.err"; then
  record_mqtt_status anonymous_publish 0
  printf 'FAILED: anonymous MQTT publish unexpectedly succeeded\n' >&2
  exit 1
else
  anonymous_status=$?
  record_mqtt_status anonymous_publish "$anonymous_status"
  printf 'OK: Mosquitto rejected anonymous publish\n'
fi

if mqtt_pub_authenticated \
  -t "$RETAINED_TOPIC" \
  -m "$RETAINED_PAYLOAD" \
  -q 1 \
  -r \
  >"$WORKDIR/mqtt-retained-pub.out" 2>"$WORKDIR/mqtt-retained-pub.err"; then
  record_mqtt_status retained_publish 0
  printf 'OK: authenticated retained publish\n'
else
  publish_status=$?
  record_mqtt_status retained_publish "$publish_status"
  printf 'FAILED: authenticated retained publish exited with status %s\n' "$publish_status" >&2
  exit 1
fi

subscribe_exact "retained subscribe before restart" "$RETAINED_TOPIC" "$RETAINED_PAYLOAD"
sleep 6
compose restart --timeout 20 mosquitto
wait_for_broker "Mosquitto readiness after restart" "$PROBE_TOPIC/restarted"
subscribe_exact "retained subscribe after restart" "$RETAINED_TOPIC" "$RETAINED_PAYLOAD"
wait_for_openhab

printf 'IoT runtime smoke test passed\n'
