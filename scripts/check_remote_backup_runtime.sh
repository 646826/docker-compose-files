#!/bin/sh
set -eu

RESTIC_IMAGE=restic/restic:0.18.1
WORKDIR=

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    printf 'Required command not found: %s\n' "$1" >&2
    exit 1
  }
}

cleanup() {
  status=$?
  trap - EXIT HUP INT TERM
  if [ -n "$WORKDIR" ] && [ -d "$WORKDIR" ]; then
    rm -rf "$WORKDIR"
  fi
  exit "$status"
}

restic_base() {
  docker run --rm \
    --user "$(id -u):$(id -g)" \
    --volume "$WORKDIR/repository:/repository" \
    --volume "$WORKDIR/password:/run/secrets/restic_password:ro" \
    --env RESTIC_REPOSITORY=/repository \
    --env RESTIC_PASSWORD_FILE=/run/secrets/restic_password \
    "$@"
}

restic() {
  restic_base "$RESTIC_IMAGE" "$@"
}

restic_source() {
  restic_base \
    --volume "$WORKDIR/source:/source:ro" \
    "$RESTIC_IMAGE" \
    "$@"
}

restic_restore() {
  restic_base \
    --volume "$WORKDIR/restore:/restore" \
    "$RESTIC_IMAGE" \
    "$@"
}

for command in docker python3 openssl id; do
  require_command "$command"
done
docker version >/dev/null

WORKDIR=$(mktemp -d "${TMPDIR:-/tmp}/homelab-restic-runtime.XXXXXX")
chmod 700 "$WORKDIR"
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
mkdir -p "$WORKDIR/repository" "$WORKDIR/source/nested" "$WORKDIR/restore"
chmod 700 "$WORKDIR/repository" "$WORKDIR/source" "$WORKDIR/restore"
openssl rand -hex 32 >"$WORKDIR/password"
chmod 600 "$WORKDIR/password"
printf 'remote backup fixture\n' >"$WORKDIR/source/nested/message.txt"
python3 - "$WORKDIR/source/nested/binary.bin" <<'PY'
from pathlib import Path
import sys
Path(sys.argv[1]).write_bytes(bytes(range(256)) * 8)
PY
ln -s nested/message.txt "$WORKDIR/source/message-link"
chmod 640 "$WORKDIR/source/nested/message.txt"

restic init
restic_source backup /source --tag docker-compose-files --host runtime
restic snapshots --json --tag docker-compose-files >"$WORKDIR/snapshots.json"
python3 - "$WORKDIR/snapshots.json" <<'PY'
import json
from pathlib import Path
import sys
snapshots = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if not isinstance(snapshots, list) or len(snapshots) != 1:
    raise SystemExit("expected exactly one restic snapshot")
PY
restic check --read-data
restic_restore restore latest --target /restore
python3 - "$WORKDIR/source" "$WORKDIR/restore/source" <<'PY'
from pathlib import Path
import os
import stat
import sys

source = Path(sys.argv[1])
restored = Path(sys.argv[2])
if not restored.is_dir():
    raise SystemExit("restored source directory is missing")

def inventory(root: Path):
    result = {}
    for path in sorted(root.rglob("*")):
        relative = str(path.relative_to(root))
        metadata = path.lstat()
        if path.is_symlink():
            result[relative] = ("symlink", os.readlink(path), stat.S_IMODE(metadata.st_mode))
        elif path.is_file():
            result[relative] = ("file", path.read_bytes(), stat.S_IMODE(metadata.st_mode))
        elif path.is_dir():
            result[relative] = ("directory", stat.S_IMODE(metadata.st_mode))
    return result

if inventory(source) != inventory(restored):
    raise SystemExit("restored bytes or metadata differ from source")
PY

cp "$WORKDIR/password" "$WORKDIR/correct-password"
printf 'wrong-password\n' >"$WORKDIR/password"
if restic snapshots >/dev/null 2>&1; then
  printf 'Wrong restic password unexpectedly succeeded\n' >&2
  exit 1
fi
mv "$WORKDIR/correct-password" "$WORKDIR/password"
chmod 600 "$WORKDIR/password"
restic snapshots --tag docker-compose-files >/dev/null

printf 'Remote backup runtime test passed\n'
