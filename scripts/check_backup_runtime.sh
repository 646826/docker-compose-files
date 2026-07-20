#!/bin/sh
set -eu

ROOT=$(CDPATH= cd "$(dirname "$0")/.." && pwd)
HELPER_IMAGE=alpine:3.24.1
PROJECT="backup-runtime-$$-$(openssl rand -hex 4)"
RESTORE_PROJECT="${PROJECT}-restore"
NONEMPTY_PROJECT="${PROJECT}-nonempty"
WORKDIR=$(mktemp -d "${TMPDIR:-/tmp}/homelab-backup-runtime.XXXXXX")
BACKUP_ROOT="$WORKDIR/backups"
SOURCE_LOGICAL="grafana_data mosquitto_data openhab_conf"
ALL_LOGICAL="influxdb_data influxdb_config grafana_data portainer_data netdata_config netdata_lib netdata_cache mosquitto_data openhab_addons openhab_conf openhab_userdata"

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    printf 'Required command not found: %s\n' "$1" >&2
    exit 1
  }
}

remove_project_volumes() {
  project=$1
  for logical in $ALL_LOGICAL; do
    docker volume rm -f "${project}_${logical}" >/dev/null 2>&1 || true
  done
}

cleanup() {
  status=$?
  trap - EXIT HUP INT TERM
  remove_project_volumes "$PROJECT"
  remove_project_volumes "$RESTORE_PROJECT"
  remove_project_volumes "$NONEMPTY_PROJECT"
  rm -rf "$WORKDIR"
  exit "$status"
}

trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

for command_name in docker python3 openssl find cp; do
  require_command "$command_name"
done

docker version >/dev/null
docker compose version >/dev/null

create_volume() {
  project=$1
  logical=$2
  name="${project}_${logical}"
  docker volume create \
    --driver local \
    --label "com.docker.compose.project=$project" \
    --label "com.docker.compose.volume=$logical" \
    "$name" >/dev/null
}

for logical in $SOURCE_LOGICAL; do
  create_volume "$PROJECT" "$logical"
done

# Grafana fixture: nested text/binary data, empty file, modes, and safe symlink.
docker run --rm \
  --mount "type=volume,src=${PROJECT}_grafana_data,dst=/volume,volume-nocopy" \
  "$HELPER_IMAGE" sh -euc '
    mkdir -p /volume/nested
    printf "runtime-backup-fixture\n" >/volume/nested/message.txt
    printf "\000\001\002\377binary\n" >/volume/nested/data.bin
    : >/volume/empty
    chmod 0750 /volume/nested
    chmod 0640 /volume/nested/message.txt /volume/nested/data.bin
    chmod 0600 /volume/empty
    ln -s message.txt /volume/nested/message-link
  '

# Other fixtures ensure multiple archives and different directory layouts.
docker run --rm \
  --mount "type=volume,src=${PROJECT}_mosquitto_data,dst=/volume,volume-nocopy" \
  "$HELPER_IMAGE" sh -euc '
    mkdir -p /volume/db
    printf "retained-state\n" >/volume/db/mosquitto.db
    chmod 0700 /volume/db
    chmod 0600 /volume/db/mosquitto.db
  '

docker run --rm \
  --mount "type=volume,src=${PROJECT}_openhab_conf,dst=/volume,volume-nocopy" \
  "$HELPER_IMAGE" sh -euc '
    mkdir -p /volume/items
    printf "String Runtime_Test\n" >/volume/items/runtime.items
    chmod 0750 /volume/items
    chmod 0640 /volume/items/runtime.items
  '

printf 'Creating disposable backup for %s\n' "$PROJECT"
HOMELAB_PROJECT_NAME="$PROJECT" BACKUP_ROOT="$BACKUP_ROOT" \
  python3 "$ROOT/scripts/backup.py" create

SNAPSHOT=$(find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -print -quit)
[ -n "$SNAPSHOT" ] || {
  printf 'Backup runtime did not create a snapshot directory\n' >&2
  exit 1
}
python3 "$ROOT/scripts/backup.py" verify "$SNAPSHOT"

# Tampering must fail offline, before a restore can touch Docker resources.
mkdir -m 0700 "$WORKDIR/tampered"
cp -a "$SNAPSHOT" "$WORKDIR/tampered/"
TAMPERED="$WORKDIR/tampered/$(basename "$SNAPSHOT")"
printf 'tamper' >>"$TAMPERED/volumes/grafana_data.tar.gz"
if python3 "$ROOT/scripts/backup.py" verify "$TAMPERED" >"$WORKDIR/tamper.out" 2>"$WORKDIR/tamper.err"; then
  printf 'Tampered snapshot unexpectedly passed verification\n' >&2
  exit 1
fi

for logical in $SOURCE_LOGICAL; do
  docker volume rm "${PROJECT}_${logical}" >/dev/null
done

printf 'Restoring snapshot into %s\n' "$RESTORE_PROJECT"
HOMELAB_PROJECT_NAME="$RESTORE_PROJECT" \
  python3 "$ROOT/scripts/backup.py" restore "$SNAPSHOT"

# Validate bytes, modes, directories, and symlink target after restore.
docker run --rm \
  --mount "type=volume,src=${RESTORE_PROJECT}_grafana_data,dst=/volume,readonly,volume-nocopy" \
  "$HELPER_IMAGE" sh -euc '
    test "$(cat /volume/nested/message.txt)" = runtime-backup-fixture
    test "$(stat -c %a /volume/nested)" = 750
    test "$(stat -c %a /volume/nested/message.txt)" = 640
    test "$(stat -c %a /volume/nested/data.bin)" = 640
    test "$(stat -c %a /volume/empty)" = 600
    test "$(readlink /volume/nested/message-link)" = message.txt
    expected=$(printf "\000\001\002\377binary\n" | sha256sum | cut -d" " -f1)
    actual=$(sha256sum /volume/nested/data.bin | cut -d" " -f1)
    test "$actual" = "$expected"
  '

docker run --rm \
  --mount "type=volume,src=${RESTORE_PROJECT}_mosquitto_data,dst=/volume,readonly,volume-nocopy" \
  "$HELPER_IMAGE" sh -euc '
    test "$(cat /volume/db/mosquitto.db)" = retained-state
    test "$(stat -c %a /volume/db)" = 700
    test "$(stat -c %a /volume/db/mosquitto.db)" = 600
  '

docker run --rm \
  --mount "type=volume,src=${RESTORE_PROJECT}_openhab_conf,dst=/volume,readonly,volume-nocopy" \
  "$HELPER_IMAGE" sh -euc '
    grep -qx "String Runtime_Test" /volume/items/runtime.items
    test "$(stat -c %a /volume/items/runtime.items)" = 640
  '

# A volume recorded as missing must stay absent after restore.
if docker volume inspect "${RESTORE_PROJECT}_portainer_data" >/dev/null 2>&1; then
  printf 'Restore created a volume that was recorded missing\n' >&2
  exit 1
fi

# Non-empty target refusal must happen before any other target volume is created.
create_volume "$NONEMPTY_PROJECT" grafana_data
docker run --rm \
  --mount "type=volume,src=${NONEMPTY_PROJECT}_grafana_data,dst=/volume,volume-nocopy" \
  "$HELPER_IMAGE" sh -euc 'printf blocker >/volume/blocker'
if HOMELAB_PROJECT_NAME="$NONEMPTY_PROJECT" \
  python3 "$ROOT/scripts/backup.py" restore "$SNAPSHOT" >"$WORKDIR/nonempty.out" 2>"$WORKDIR/nonempty.err"; then
  printf 'Restore unexpectedly accepted a non-empty target volume\n' >&2
  exit 1
fi
for logical in mosquitto_data openhab_conf; do
  if docker volume inspect "${NONEMPTY_PROJECT}_${logical}" >/dev/null 2>&1; then
    printf 'Restore created %s before completing global preflight\n' "${NONEMPTY_PROJECT}_${logical}" >&2
    exit 1
  fi
done

printf 'Backup runtime round trip passed\n'
