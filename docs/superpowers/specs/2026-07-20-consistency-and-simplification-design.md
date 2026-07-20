# Consistency and Simplification Design

## Goal

Remove verified drift between the repository's real behavior, documentation, static policies, image placeholders, dependency automation, and backup regression-test layout without changing any service runtime behavior, persistent-data format, network exposure, credential value, or operator command.

The result must make each important contract have one clear owner and must prevent comments or stale placeholders from accidentally satisfying policy checks.

## Current verified drift

The current `main` branch has five independent operator checks:

1. `make check`;
2. `make check-images`;
3. `make check-runtime`;
4. `make check-iot-runtime`;
5. `make check-backup-runtime`.

However, the README still presents a heading named `Четыре уровня проверки` and documents only the first four checks in that numbered section. The backup runtime command exists in the command table and Makefile, but the conceptual verification model is stale.

The Mosquitto password-generation contract has a more serious policy inconsistency:

- the supported implementation explicitly creates a SHA512-PBKDF2 record with 220000 iterations;
- `scripts/check_iot_runtime_policy.py` correctly owns and checks that contract;
- `scripts/check_static.py` still requires the literal string `mosquitto_passwd -U`;
- `scripts/init.sh` contains that literal only in a comment explaining that it is not executed.

Therefore the general static checker currently passes because of commentary that describes forbidden historical behavior, not because it validates the production command.

The image-platform checker also creates an Argon2id-shaped placeholder for `mosquitto_passwords`, although the official Mosquitto 2.1.2 images and all current runtime/bootstrap code use the supported `$7$220000$` SHA512-PBKDF2 record contract.

Finally, Renovate discovers helper images in `scripts/init.sh`, but it does not discover the backup helper declaration:

```python
HELPER_IMAGE = "alpine:3.24.1"
```

This leaves a pinned image covered by image-platform verification but outside automated dependency-update proposals.

Two late backup regression tests are stored in `scripts/test_backup_tar_root.py`, while the subsystem's public and behavioral tests live in `scripts/test_backup.py`. The split adds a separate runner entry and policy surface without representing a separate component.

## Scope

This change modifies only consistency, policy, documentation, test organization, and dependency automation.

It includes:

- correcting the README verification count and adding the fifth check section;
- listing the backup helper image in the pinned-version table;
- making the specialized IoT policy the sole owner of the Mosquitto hashing algorithm and work factor;
- removing the obsolete `mosquitto_passwd -U` requirement from the general static checker;
- removing the stale `mosquitto_passwd -U` commentary from operational scripts;
- changing the image-check placeholder to the supported PBKDF2-shaped record;
- adding focused tests that prevent the placeholder from returning to Argon2id;
- adding Renovate discovery for the backup helper image;
- adding static acceptance for the Renovate manager and the five-level README model;
- moving the two late backup regression tests into `scripts/test_backup.py`;
- deleting `scripts/test_backup_tar_root.py` and its separate runner entry;
- running all existing verification workflows on the same final head.

## Non-goals

This stage does not:

- change `compose.yaml`;
- change any service image version;
- change the backup snapshot format or restore behavior;
- change Mosquitto password files already generated on a host;
- rotate any credential;
- add Netdata runtime verification;
- pin images or GitHub Actions by digest;
- redesign the validation framework;
- split `scripts/backup.py` or other large existing modules;
- add a new dependency or testing framework;
- change workflow schedules, permissions, or supported platforms.

## Design principles

### One contract, one owner

A specialized policy checker owns domain-specific behavior. The general static checker owns repository-wide structure and cross-cutting consistency.

The ownership after this change is:

| Contract | Owner |
| --- | --- |
| Exact Mosquitto hashing command, algorithm, iteration count, record prefix, and documentation claims | `scripts/check_iot_runtime_policy.py` plus behavioral tests |
| General helper image pinning and absence of unsafe batch-mode arguments | `scripts/check_static.py` |
| Backup helper value, backup mechanics, backup documentation, and backup runtime test | `scripts/check_backup_policy.py` |
| Five-level README verification model and Renovate coverage for all helper-image declaration styles | `scripts/check_static.py` |
| Registry manifest coverage for all service and helper images | `scripts/check_images.py` and `scripts/test_check_images.py` |

No checker may require a forbidden command merely as a substring. Policy checks must describe executable behavior or structured configuration.

### No runtime behavior change

The supported production Mosquitto command remains exactly:

```text
mosquitto_passwd -H sha512-pbkdf2 -I 220000 -c
```

The backup helper remains exactly:

```text
alpine:3.24.1
```

The existing five Make commands and workflows remain independent and retain their current implementation.

### Smallest useful simplification

The change removes one redundant test file and one duplicate algorithm check. It does not introduce a new general-purpose consistency framework, parse shell syntax, or refactor unrelated validation code.

## Mosquitto policy ownership

### General static checker

`scripts/check_static.py` continues to require:

- pinned `eclipse-mosquitto:2.1.2-alpine` in `scripts/init.sh`;
- absence of `mosquitto_passwd -b` in the bootstrap;
- the expected Mosquitto 2.1 password-file and SQLite plugin configuration.

It removes this obsolete rule:

```python
if "mosquitto_passwd -U" not in init_script:
    error("Mosquitto bootstrap must convert plaintext input with mosquitto_passwd -U")
```

The general checker does not replace it with another exact hashing-command assertion. Exact hashing behavior already belongs to the specialized IoT policy and bootstrap behavior tests.

### Specialized IoT checker

`scripts/check_iot_runtime_policy.py` remains the authoritative static owner of:

```text
mosquitto_passwd -H sha512-pbkdf2 -I 220000 -c
```

It must reject all of these literals in the operational bootstrap and IoT runtime harness:

```text
mosquitto_passwd -H argon2id
mosquitto_passwd -b
mosquitto_passwd -U
```

The `-U` rule becomes a direct substring rejection for these scripts rather than only a regular expression matching an executable line. This prevents a stale comment from masquerading as required policy evidence.

Historical design documentation may continue to mention `-U` when explaining the upstream limitation; only operational scripts are forbidden from carrying the stale command literal.

### Bootstrap comment

The comment in `scripts/init.sh` becomes implementation-focused and does not mention the obsolete command:

```text
The official Mosquitto 2.1.2 images do not compile Argon2 support, so create a supported PBKDF2 password file directly.
```

No command behavior changes.

### Behavioral evidence

`scripts/test_init.py` already proves that the fake Docker invocation contains the exact PBKDF2 command and does not contain `-b` or Argon2id. It will additionally assert that the captured invocation does not contain `mosquitto_passwd -U`.

`scripts/test_iot_runtime.py` continues to prove the same contract for disposable IoT credentials. Its assertions will explicitly reject `mosquitto_passwd -U` in Docker command logs.

## Image placeholder consistency

`scripts/check_images.py` currently needs only placeholder files so Compose can render all profiles. These placeholders are not used for authentication, but they must still represent the supported format to avoid contradictory examples in executable repository code.

The Mosquitto placeholder changes from an Argon2id-shaped value to:

```text
manifest-check:$7$220000$placeholder$placeholder
```

The value remains deterministic, non-secret, and intentionally not a usable production hash.

`scripts/test_check_images.py` adds a focused assertion that:

- `PLACEHOLDER_SECRETS["mosquitto_passwords"]` starts with `manifest-check:$7$220000$`;
- the value does not contain `argon2id`;
- temporary placeholder creation writes this exact supported-format value when the file is absent;
- an existing user file remains untouched as before.

The image checker remains manifest-only and does not validate or execute the placeholder.

## README verification model

The README heading changes from:

```text
## Четыре уровня проверки
```

To:

```text
## Пять уровней проверки
```

The first four numbered sections keep their current meaning and order. A fifth section is added:

```text
### 5. Изолированная backup/restore runtime-проверка
```

It documents:

```bash
make check-backup-runtime
```

The section states that the test:

- creates uniquely named disposable local volumes;
- writes nested text and binary fixtures, modes, an empty file, and a safe relative symlink;
- performs create, offline verify, source deletion, and side-by-side restore;
- compares bytes and relevant metadata;
- proves tamper rejection;
- proves refusal of a non-empty target before unrelated target creation;
- performs scoped cleanup;
- does not start the homelab applications;
- does not read production `.env` or `.secrets/`.

The detailed operator procedure remains in `docs/BACKUP.md`; the README section stays a concise explanation of the fifth quality gate.

## Pinned-version table

The README image table adds:

```text
| Backup helper Alpine | `3.24.1` |
```

This row describes the image used by `scripts/backup.py`, not a persistent service.

No other listed version changes.

## README policy ownership

`scripts/check_runtime_policy.py` stops owning the global verification-count heading. It replaces the required fragment `## Четыре уровня проверки` with the runtime-specific heading:

```text
### 3. Изолированная runtime-проверка default stack
```

`scripts/check_iot_runtime_policy.py` continues to require `make check-iot-runtime` and its IoT-specific documentation.

`scripts/check_backup_policy.py` requires:

```text
### 5. Изолированная backup/restore runtime-проверка
make check-backup-runtime
```

`scripts/check_static.py` owns the global README model and requires:

- `## Пять уровней проверки`;
- each of the five Make commands;
- the backup helper version row.

This division prevents a default-runtime policy from knowing that the repository has exactly four or five total quality gates while still detecting missing global documentation.

## Renovate support for the backup helper

The existing custom manager for `scripts/init.sh` remains unchanged.

A second regex custom manager is added to `renovate.json`:

```json
{
  "description": "Update the backup helper container image used by scripts/backup.py",
  "customType": "regex",
  "managerFilePatterns": [
    "/^scripts\\/backup\\.py$/"
  ],
  "matchStrings": [
    "HELPER_IMAGE\\s*=\\s*\"(?<depName>[^:\\s\"]+):(?<currentValue>[^\\s\"]+)\""
  ],
  "datasourceTemplate": "docker"
}
```

The existing package rule already groups `custom.regex` managers under `container images`; no additional package rule is needed.

The manager intentionally matches only the exact `HELPER_IMAGE = "name:tag"` declaration in `scripts/backup.py`. It does not broadly scan all Python strings.

`scripts/check_static.py` parses `renovate.json` as JSON and verifies structurally that at least one custom manager:

- includes a manager file pattern for `scripts/backup.py`;
- includes a match string containing the named captures `depName` and `currentValue` and the literal `HELPER_IMAGE`;
- uses `datasourceTemplate` equal to `docker`.

This check does not duplicate Renovate's schema validation; it only protects repository-specific helper coverage.

The image workflow already includes `scripts/backup.py` in its path filters and continues to verify the resulting helper tag for both maintained architectures.

## Backup regression-test consolidation

The tests currently in `scripts/test_backup_tar_root.py` move into `scripts/test_backup.py`:

```text
test_regular_root_member_is_rejected
test_later_failure_reports_already_populated_preexisting_volume
```

They may be renamed for clarity while preserving their exact assertions:

```text
test_tar_rejects_non_directory_root_member
test_later_restore_failure_reports_populated_preexisting_volume
```

After the move:

- `scripts/test_backup_tar_root.py` is deleted;
- `scripts/check.sh` invokes only `python3 scripts/test_backup.py` for backup unit/behavior coverage;
- `scripts/check_backup_policy.py` requires both regression-test names in the main test file;
- no workflow invokes the removed file directly.

This is a layout simplification only. The red-green history of both defect fixes remains represented by permanent regression tests.

## Static acceptance changes

### `scripts/check_static.py`

Add repository-wide consistency assertions for:

- the five-level README heading;
- all five verification commands in the README;
- the `Backup helper Alpine` version-table row with `3.24.1`;
- structured Renovate discovery of `scripts/backup.py`'s helper image.

Remove the obsolete requirement for `mosquitto_passwd -U`.

### `scripts/check_iot_runtime_policy.py`

Strengthen the forbidden hashing list so operational scripts cannot contain the stale `mosquitto_passwd -U` literal even in comments.

### `scripts/check_backup_policy.py`

Require the fifth README section and require both consolidated backup regression tests in `scripts/test_backup.py`.

### `scripts/check_runtime_policy.py`

Require only the default-runtime section heading rather than the global verification-count heading.

## TDD sequence

Implementation follows focused red-green cycles.

### Cycle 1: Mosquitto policy ownership

1. Strengthen the specialized policy and behavioral assertions to reject the stale `-U` literal.
2. Run the focused policy/tests and confirm failure because `scripts/init.sh` still contains the comment.
3. Remove the stale comment literal and remove the contradictory general static requirement.
4. Run the focused checks and full fast suite.

### Cycle 2: Placeholder format

1. Add an assertion for the `$7$220000$` placeholder and absence of Argon2id.
2. Confirm failure against the current placeholder.
3. Change only the placeholder value.
4. Run image unit tests and manifest-independent static checks.

### Cycle 3: README and ownership

1. Update policy expectations first: five-level global model, runtime-specific heading, backup fifth section, and helper version row.
2. Confirm the policies fail against the current README.
3. Update the README with the smallest complete documentation change.
4. Run all focused policies.

### Cycle 4: Renovate manager

1. Add structured static acceptance for the backup helper custom manager.
2. Confirm failure against current `renovate.json`.
3. Add the exact regex manager.
4. Parse the JSON and run static checks.

### Cycle 5: Test consolidation

1. Update backup policy to require the two regression names in `scripts/test_backup.py`.
2. Confirm failure while they remain in the separate file.
3. Move the tests, delete the redundant file, and remove its runner entry.
4. Run backup tests and the full fast suite.

## Verification commands

Focused local verification:

```bash
python3 scripts/test_init.py
python3 scripts/test_iot_runtime.py
python3 scripts/test_check_images.py
python3 scripts/test_backup.py
python3 scripts/check_iot_runtime_policy.py
python3 scripts/check_runtime_policy.py
python3 scripts/check_backup_policy.py
python3 scripts/check_static.py
python3 -m json.tool renovate.json >/dev/null
./scripts/check.sh
```

No command in the focused phase performs a production backup, changes a volume, or starts the homelab project.

Final pull-request verification must complete successfully on one exact head for:

```text
CI
Image platforms
Runtime smoke
IoT runtime smoke
Backup runtime
```

## Compatibility and migration

There is no operator migration.

Existing `.env`, `.secrets/`, named volumes, backups, Compose networks, and containers are unaffected. Previously generated `$7$220000$` Mosquitto password files remain valid. Backup format version 1 remains unchanged.

The only user-visible changes are more accurate documentation and future Renovate pull requests for the backup helper.

## Failure handling

If any focused policy exposes another ownership contradiction, implementation stops and the design is amended rather than adding another substring workaround.

No code path may be made to pass by inserting a required command into a comment.

If the Renovate manager cannot be expressed narrowly enough to match only `HELPER_IMAGE`, it is omitted and the limitation is documented rather than using an overly broad Python-string regex. The exact proposed pattern is expected to be sufficiently narrow.

## Rollback

The complete change is one non-runtime pull request. Reverting its squash commit restores the prior documentation, policy, placeholder, Renovate configuration, and test layout without touching service state.

## Acceptance criteria

The stage is complete only when all of the following are true on the same final head:

1. README says `Пять уровней проверки` and documents all five commands in numbered sections.
2. README lists `Backup helper Alpine` version `3.24.1`.
3. `scripts/check_static.py` contains no rule requiring `mosquitto_passwd -U`.
4. Operational bootstrap and IoT runtime scripts contain no `mosquitto_passwd -U` literal.
5. The specialized IoT policy requires exact SHA512-PBKDF2 with 220000 iterations and rejects Argon2id, `-b`, and `-U`.
6. Image placeholders use a `$7$220000$` Mosquitto record shape and contain no Argon2id claim.
7. Renovate structurally discovers `HELPER_IMAGE` in `scripts/backup.py` through the Docker datasource.
8. The default-runtime policy no longer owns the global number of verification levels.
9. Both late backup regressions live in `scripts/test_backup.py`.
10. `scripts/test_backup_tar_root.py` no longer exists and is not invoked.
11. The full fast suite succeeds.
12. CI, Image platforms, Runtime smoke, IoT runtime smoke, and Backup runtime all succeed on the exact final PR head.
13. The final diff contains no temporary transport workflow, generated payload, or unrelated refactor.
