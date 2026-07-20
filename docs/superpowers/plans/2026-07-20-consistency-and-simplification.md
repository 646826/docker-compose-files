# Consistency and Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove verified drift between runtime behavior, policies, documentation, image placeholders, Renovate discovery, and backup regression-test layout without changing any service behavior or persistent-data format.

**Architecture:** Keep the existing specialized policy boundaries and make each contract have one owner. Apply five focused RED→GREEN cycles: Mosquitto hashing ownership, placeholder format, README/policy ownership, Renovate helper discovery, and backup-test consolidation. Finish by running every existing local and GitHub-hosted verification layer on one exact commit.

**Tech Stack:** Python 3.11 standard library, POSIX shell, JSON, Docker Compose V2 validation, Renovate regex custom managers, GitHub Actions.

## Global Constraints

- Do not modify `compose.yaml` or any service runtime configuration.
- Do not change any image version, network exposure, credential value, named volume, or backup format.
- Keep the production Mosquitto command exactly `mosquitto_passwd -H sha512-pbkdf2 -I 220000 -c`.
- Keep the backup helper exactly `alpine:3.24.1`.
- Keep all five existing Make commands and workflows independent.
- Use only the Python standard library and existing shell tooling.
- Do not introduce a general-purpose validation framework or unrelated refactor.
- Remove `mosquitto_passwd -U` from operational scripts and reject it through the specialized IoT policy.
- Keep historical design documentation intact when it explains the earlier `-U` experiment.
- The final diff must contain no temporary workflow, generated payload, or transport helper.

---

## File map

- Modify `scripts/check_iot_runtime_policy.py`: sole static owner of the exact Mosquitto hashing contract and forbidden alternatives.
- Modify `scripts/check_static.py`: remove the contradictory `-U` requirement; own the five-level README model and structured Renovate coverage.
- Modify `scripts/init.sh`: replace the stale command-bearing comment without changing executable code.
- Modify `scripts/test_init.py`: reject `-U` in captured bootstrap Docker commands.
- Modify `scripts/test_iot_runtime.py`: reject `-U` in captured IoT-runtime Docker commands.
- Modify `scripts/check_images.py`: use a PBKDF2-shaped Mosquitto placeholder.
- Modify `scripts/test_check_images.py`: permanently enforce the supported placeholder shape.
- Modify `README.md`: document five verification levels and the backup helper version.
- Modify `scripts/check_runtime_policy.py`: require only its own default-runtime section.
- Modify `scripts/check_backup_policy.py`: require the fifth README section and consolidated regression tests.
- Modify `renovate.json`: discover the backup helper declaration in `scripts/backup.py`.
- Modify `scripts/test_backup.py`: absorb the two late backup regression tests.
- Modify `scripts/check.sh`: remove the redundant test-file invocation.
- Delete `scripts/test_backup_tar_root.py`.

---

### Task 1: Make the IoT policy the sole Mosquitto hashing owner

**Files:**
- Modify: `scripts/check_iot_runtime_policy.py`
- Modify: `scripts/test_init.py`
- Modify: `scripts/test_iot_runtime.py`
- Modify: `scripts/init.sh`
- Modify: `scripts/check_static.py`

**Interfaces:**
- Consumes the existing `PBKDF2_COMMAND` constant and `check_hashing_contract(label: str, script: str) -> None`.
- Produces one authoritative rule: operational hashing scripts must contain `PBKDF2_COMMAND` and must not contain Argon2id, batch mode, or `mosquitto_passwd -U`.

- [ ] **Step 1: Strengthen the specialized policy before changing production files**

Replace the forbidden loop and remove the old executable-line-only `-U` regex in `scripts/check_iot_runtime_policy.py`:

```python
def check_hashing_contract(label: str, script: str) -> None:
    if PBKDF2_COMMAND not in script:
        error(f"{label} must explicitly create a 220000-iteration SHA512-PBKDF2 record")
    for forbidden in (
        "mosquitto_passwd -H argon2id",
        "mosquitto_passwd -b",
        "mosquitto_passwd -U",
    ):
        if forbidden in script:
            error(f"{label} contains unsupported or unsafe password hashing behavior: {forbidden}")
```

- [ ] **Step 2: Add behavioral assertions against the stale command**

In `scripts/test_init.py`, immediately after the existing `-b` assertion, add:

```python
        if "mosquitto_passwd -U" in docker_calls:
            fail("bootstrap still carries the obsolete Mosquitto plaintext-conversion command")
```

In `scripts/test_iot_runtime.py`, in the successful-command-log assertions next to the existing PBKDF2, Argon2id, and batch-mode checks, add:

```python
        if "mosquitto_passwd -U" in docker_log:
            fail("IoT runtime harness still carries the obsolete Mosquitto conversion command")
```

Use the existing variable holding the fake Docker command log in that test; do not add a second command-log reader.

- [ ] **Step 3: Run focused checks and confirm RED**

Run:

```bash
python3 scripts/check_iot_runtime_policy.py
python3 scripts/test_init.py
python3 scripts/test_iot_runtime.py
```

Expected:

```text
check_iot_runtime_policy.py: FAIL mentioning normal bootstrap and mosquitto_passwd -U
test_init.py: FAIL because the captured shell payload contains mosquitto_passwd -U
```

The IoT behavioral test may fail for the same reason depending on its fake-Docker logging boundary. At least the specialized policy must fail against the current comment in `scripts/init.sh`.

- [ ] **Step 4: Remove the stale operational comment literal**

Replace this comment in `scripts/init.sh`:

```sh
# mosquitto_passwd -U is intentionally not executed: the official Mosquitto
# 2.1.2 images do not compile Argon2 support, so create a supported PBKDF2 file.
```

with:

```sh
# The official Mosquitto 2.1.2 images do not compile Argon2 support, so create
# a supported SHA512-PBKDF2 password file directly with an explicit work factor.
```

Do not alter the command below it.

- [ ] **Step 5: Remove the contradictory general-static requirement**

Delete only this rule from `scripts/check_static.py`:

```python
        if "mosquitto_passwd -U" not in init_script:
            error("Mosquitto bootstrap must convert plaintext input with mosquitto_passwd -U")
```

Keep the pinned image check and the `mosquitto_passwd -b` prohibition.

- [ ] **Step 6: Run focused and fast checks and confirm GREEN**

Run:

```bash
python3 scripts/check_iot_runtime_policy.py
python3 scripts/test_init.py
python3 scripts/test_iot_runtime.py
python3 scripts/check_static.py
```

Expected:

```text
IoT runtime policy checks passed
Bootstrap tests passed
IoT runtime behavioral tests passed
Static checks passed
```

- [ ] **Step 7: Commit the ownership correction**

```bash
git add scripts/check_iot_runtime_policy.py scripts/test_init.py scripts/test_iot_runtime.py scripts/init.sh scripts/check_static.py
git commit -m "fix: make IoT policy own Mosquitto hashing"
```

---

### Task 2: Align the image-rendering placeholder with PBKDF2

**Files:**
- Modify: `scripts/test_check_images.py`
- Modify: `scripts/check_images.py`

**Interfaces:**
- Consumes `PLACEHOLDER_SECRETS: dict[str, str]` and `temporary_secret_placeholders(root: Path)`.
- Produces a deterministic non-secret Mosquitto placeholder beginning with `manifest-check:$7$220000$`.

- [ ] **Step 1: Import the placeholder map into the image tests**

Extend the existing import block in `scripts/test_check_images.py`:

```python
from scripts.check_images import (  # noqa: E402
    PLACEHOLDER_SECRETS,
    compose_images,
    helper_images,
    manifest_platforms,
    missing_platforms,
    select_env_file,
    temporary_secret_placeholders,
)
```

- [ ] **Step 2: Add a failing placeholder-format test**

Add this method to `LocalComposeInputTests`:

```python
    def test_mosquitto_placeholder_matches_supported_pbkdf2_shape(self) -> None:
        value = PLACEHOLDER_SECRETS["mosquitto_passwords"]
        self.assertTrue(value.startswith("manifest-check:$7$220000$"))
        self.assertNotIn("argon2id", value.lower())
```

Also extend `test_temporary_placeholders_remove_a_created_directory` inside its context manager:

```python
                generated = (root / ".secrets" / "mosquitto_passwords").read_text(
                    encoding="utf-8"
                ).strip()
                self.assertEqual(generated, PLACEHOLDER_SECRETS["mosquitto_passwords"])
```

- [ ] **Step 3: Run the image unit test and confirm RED**

Run:

```bash
python3 scripts/test_check_images.py
```

Expected: FAIL because the current placeholder contains `$argon2id$` instead of `$7$220000$`.

- [ ] **Step 4: Change only the placeholder value**

In `scripts/check_images.py`, replace the Mosquitto entry with:

```python
    "mosquitto_passwords": "manifest-check:$7$220000$placeholder$placeholder",
```

- [ ] **Step 5: Run the image tests and policy checks and confirm GREEN**

Run:

```bash
python3 scripts/test_check_images.py
python3 scripts/check_static.py
python3 scripts/check_backup_policy.py
```

Expected: all three commands exit `0`.

- [ ] **Step 6: Commit the placeholder correction**

```bash
git add scripts/check_images.py scripts/test_check_images.py
git commit -m "fix: align Mosquitto image placeholder"
```

---

### Task 3: Document and enforce all five verification levels

**Files:**
- Modify: `scripts/check_static.py`
- Modify: `scripts/check_runtime_policy.py`
- Modify: `scripts/check_backup_policy.py`
- Modify: `README.md`

**Interfaces:**
- Produces the global README heading `## Пять уровней проверки`.
- Produces the runtime-specific heading `### 3. Изолированная runtime-проверка default stack`.
- Produces the backup-specific heading `### 5. Изолированная backup/restore runtime-проверка`.

- [ ] **Step 1: Make policies require the intended documentation before editing README**

In `scripts/check_runtime_policy.py`, replace the global heading fragment:

```python
            "## Четыре уровня проверки",
```

with:

```python
            "### 3. Изолированная runtime-проверка default stack",
```

In `scripts/check_backup_policy.py`, after the existing `docs/BACKUP.md` and migration checks, add:

```python
    for fragment in (
        "### 5. Изолированная backup/restore runtime-проверка",
        "make check-backup-runtime",
    ):
        if fragment not in readme:
            error(f"README backup verification documentation is missing: {fragment}")
```

In `scripts/check_static.py`, extend the README block with:

```python
        required_verification_docs = (
            "## Пять уровней проверки",
            "make check",
            "make check-images",
            "make check-runtime",
            "make check-iot-runtime",
            "make check-backup-runtime",
            "| Backup helper Alpine | `3.24.1` |",
        )
        for fragment in required_verification_docs:
            if fragment not in readme:
                error(f"README verification model is missing: {fragment}")
```

- [ ] **Step 2: Run the policy checks and confirm RED**

Run:

```bash
python3 scripts/check_runtime_policy.py
python3 scripts/check_backup_policy.py
python3 scripts/check_static.py
```

Expected failures:

```text
README runtime documentation is missing: ### 3. ...
README backup verification documentation is missing: ### 5. ...
README verification model is missing: ## Пять уровней проверки
README verification model is missing: | Backup helper Alpine | `3.24.1` |
```

- [ ] **Step 3: Update the pinned-version table**

In `README.md`, add this row directly after the bootstrap helper row:

```markdown
| Backup helper Alpine | `3.24.1` |
```

Do not change any other version.

- [ ] **Step 4: Rename the verification heading and add the fifth section**

Replace:

```markdown
## Четыре уровня проверки
```

with:

```markdown
## Пять уровней проверки
```

Append this section immediately after the current IoT runtime section:

```markdown
### 5. Изолированная backup/restore runtime-проверка

```bash
make check-backup-runtime
```

Создаёт уникальные одноразовые local volumes с вложенными текстовыми и бинарными файлами, пустым файлом, нестандартными permissions и безопасным относительным symlink. Затем выполняет cold backup, офлайн-проверку, удаление source volumes и side-by-side restore в другой project name.

Проверка сравнивает bytes и существенные filesystem metadata, подтверждает отказ для повреждённого snapshot и непустого target volume, а затем удаляет только собственные fixture-ресурсы. Она не запускает приложения homelab и не читает рабочие `.env` или `.secrets/`; подробная процедура восстановления находится в [`docs/BACKUP.md`](docs/BACKUP.md).
```

- [ ] **Step 5: Run all focused documentation policies and confirm GREEN**

Run:

```bash
python3 scripts/check_runtime_policy.py
python3 scripts/check_iot_runtime_policy.py
python3 scripts/check_backup_policy.py
python3 scripts/check_static.py
```

Expected: all commands exit `0` with their respective `... checks passed` messages.

- [ ] **Step 6: Commit the documentation ownership correction**

```bash
git add README.md scripts/check_static.py scripts/check_runtime_policy.py scripts/check_backup_policy.py
git commit -m "docs: describe all five verification levels"
```

---

### Task 4: Add Renovate discovery for the backup helper

**Files:**
- Modify: `scripts/check_static.py`
- Modify: `renovate.json`

**Interfaces:**
- Consumes `renovate.json` as a JSON object.
- Produces a second regex custom manager aimed only at `scripts/backup.py` and `HELPER_IMAGE`.

- [ ] **Step 1: Add structured acceptance before changing Renovate**

In `scripts/check_static.py`, read the existing file near the other required repository inputs:

```python
    renovate_text = read_required("renovate.json")
```

After the README checks, add:

```python
    if renovate_text:
        try:
            renovate = json.loads(renovate_text)
        except json.JSONDecodeError as exc:
            error(f"renovate.json is invalid JSON: {exc}")
        else:
            managers = renovate.get("customManagers", [])
            covered = False
            if isinstance(managers, list):
                for manager in managers:
                    if not isinstance(manager, dict):
                        continue
                    patterns = manager.get("managerFilePatterns", [])
                    matches = manager.get("matchStrings", [])
                    if (
                        manager.get("datasourceTemplate") == "docker"
                        and isinstance(patterns, list)
                        and any("scripts\\/backup\\.py" in value for value in patterns if isinstance(value, str))
                        and isinstance(matches, list)
                        and any(
                            "HELPER_IMAGE" in value
                            and "depName" in value
                            and "currentValue" in value
                            for value in matches
                            if isinstance(value, str)
                        )
                    ):
                        covered = True
                        break
            if not covered:
                error("Renovate must discover HELPER_IMAGE in scripts/backup.py through the Docker datasource")
```

`json` is already imported by `scripts/check_static.py`; do not add a duplicate import.

- [ ] **Step 2: Run static checks and confirm RED**

Run:

```bash
python3 scripts/check_static.py
```

Expected: FAIL with `Renovate must discover HELPER_IMAGE...`.

- [ ] **Step 3: Add the narrow Renovate manager**

Append this object to `customManagers` in `renovate.json` after the existing `scripts/init.sh` manager:

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

Leave the existing package rules unchanged because `custom.regex` is already grouped under `container images`.

- [ ] **Step 4: Validate JSON and confirm GREEN**

Run:

```bash
python3 -m json.tool renovate.json >/dev/null
python3 scripts/check_static.py
python3 scripts/check_images.py --help >/dev/null 2>&1 || true
```

The first two commands must exit `0`. The third command is informational only because `check_images.py` has no dedicated help interface and must not be used as proof of correctness.

- [ ] **Step 5: Commit dependency-discovery coverage**

```bash
git add renovate.json scripts/check_static.py
git commit -m "chore: let Renovate update backup helper"
```

---

### Task 5: Consolidate the late backup regression tests

**Files:**
- Modify: `scripts/test_backup.py`
- Modify: `scripts/check_backup_policy.py`
- Modify: `scripts/check.sh`
- Delete: `scripts/test_backup_tar_root.py`

**Interfaces:**
- Consumes existing `build_snapshot(...)`, `FakeDocker`, `backup.inspect_archive(...)`, and `backup.restore_snapshot(...)` helpers in `scripts/test_backup.py`.
- Produces the permanent test names `test_tar_rejects_non_directory_root_member` and `test_later_restore_failure_reports_populated_preexisting_volume` in the main backup test module.

- [ ] **Step 1: Make backup policy require the consolidated names**

Add these names to `required_test_names` in `scripts/check_backup_policy.py`:

```python
        "test_tar_rejects_non_directory_root_member",
        "test_later_restore_failure_reports_populated_preexisting_volume",
```

Also reject the redundant file directly:

```python
    if (ROOT / "scripts/test_backup_tar_root.py").exists():
        error("backup regressions must live in scripts/test_backup.py, not a separate test file")
```

- [ ] **Step 2: Run backup policy and confirm RED**

Run:

```bash
python3 scripts/check_backup_policy.py
```

Expected: FAIL because both names are absent from `scripts/test_backup.py` and the separate file still exists.

- [ ] **Step 3: Move the tar-root regression into the main test module**

Add this method to the existing tar-safety test class in `scripts/test_backup.py`:

```python
    def test_tar_rejects_non_directory_root_member(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "regular-root.tar.gz"
            member = tarfile.TarInfo("./")
            member.size = 1
            with tarfile.open(archive_path, "w:gz") as archive:
                archive.addfile(member, io.BytesIO(b"x"))
            with self.assertRaisesRegex(backup.BackupError, "root member"):
                backup.inspect_archive(archive_path)
```

The module already imports `io`, `tarfile`, `tempfile`, `unittest`, and `Path`; do not duplicate imports.

- [ ] **Step 4: Move the restore-diagnostics regression into the main module**

Add this method to the existing restore test class:

```python
    def test_later_restore_failure_reports_populated_preexisting_volume(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            snapshot = build_snapshot(
                Path(directory),
                declared=("grafana_data", "mosquitto_data"),
                archived=("grafana_data", "mosquitto_data"),
            )
            docker = FakeDocker()
            preexisting = "recovery_grafana_data"
            failing_created = "recovery_mosquitto_data"
            docker.volumes[preexisting] = {
                "Name": preexisting,
                "Driver": "local",
                "Options": {},
                "Labels": {},
            }
            docker.empty[preexisting] = True
            docker.fail_restore_for = failing_created
            with self.assertRaisesRegex(
                backup.BackupError,
                "pre-existing volumes may be partially populated: recovery_grafana_data",
            ):
                backup.restore_snapshot(snapshot, "recovery", docker)
            self.assertIn(preexisting, docker.volumes)
            self.assertNotIn(failing_created, docker.volumes)
```

- [ ] **Step 5: Remove the redundant runner and file**

Delete this line from `scripts/check.sh`:

```sh
python3 scripts/test_backup_tar_root.py
```

Delete `scripts/test_backup_tar_root.py` entirely.

- [ ] **Step 6: Run backup tests and policies and confirm GREEN**

Run:

```bash
python3 scripts/test_backup.py
python3 scripts/check_backup_policy.py
python3 scripts/check_static.py
```

Expected: all commands exit `0`; only `scripts/test_backup.py` is invoked for backup unit/behavior coverage.

- [ ] **Step 7: Commit the test-layout simplification**

```bash
git add scripts/test_backup.py scripts/check_backup_policy.py scripts/check.sh
git rm scripts/test_backup_tar_root.py
git commit -m "test: consolidate backup regressions"
```

---

### Task 6: Full verification, review, and integration

**Files:**
- Review all changed files.
- No new production file is introduced in this task.

**Interfaces:**
- Produces one exact head SHA that has passed every local check and all five GitHub Actions workflows.

- [ ] **Step 1: Run the complete focused suite**

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
```

Expected: every command exits `0`.

- [ ] **Step 2: Run the full fast repository suite**

```bash
./scripts/check.sh
```

Expected final line:

```text
All checks passed
```

- [ ] **Step 3: Inspect the final diff for scope and transport residue**

```bash
git diff --check main...HEAD
git diff --name-status main...HEAD
```

Expected changed paths are limited to:

```text
README.md
renovate.json
scripts/check_backup_policy.py
scripts/check_images.py
scripts/check_iot_runtime_policy.py
scripts/check_runtime_policy.py
scripts/check_static.py
scripts/init.sh
scripts/test_backup.py
scripts/test_check_images.py
scripts/test_init.py
scripts/test_iot_runtime.py
scripts/check.sh
docs/superpowers/specs/2026-07-20-consistency-and-simplification-design.md
docs/superpowers/plans/2026-07-20-consistency-and-simplification.md
```

`scripts/test_backup_tar_root.py` appears only as deleted. No `.github/workflows/*` file, payload, generated artifact, or helper under `tools/` may appear.

- [ ] **Step 4: Open or update the pull request**

Create a PR from `feat/consistency-and-simplification` to `main` describing the five corrected drift classes and explicitly stating that runtime behavior is unchanged.

- [ ] **Step 5: Wait for one exact head to complete every workflow**

Require success for:

```text
CI
Image platforms
Runtime smoke
IoT runtime smoke
Backup runtime
```

Do not combine results from different head SHAs.

- [ ] **Step 6: Perform final review**

Confirm:

```text
- no open review threads;
- no accidental image-version change;
- no compose.yaml change;
- no backup-format or restore-code change;
- no stale operational mosquitto_passwd -U literal;
- README contains five numbered verification sections;
- Renovate manager is narrow and valid JSON;
- the redundant backup test file is absent.
```

- [ ] **Step 7: Merge the exact verified head**

Merge with squash only after all five workflows are green and the PR remains mergeable. Record the verified head SHA and resulting squash commit in the PR comment.
