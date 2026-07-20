#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def replace_exact(path: str, old: str, new: str, *, count: int = 1) -> None:
    text = read(path)
    actual = text.count(old)
    if actual != count:
        raise SystemExit(f"{path}: expected {count} exact match(es), found {actual}: {old!r}")
    write(path, text.replace(old, new, count))


def run(command: list[str], *, success: bool, contains: str | None = None) -> str:
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    output = result.stdout + result.stderr
    print(f"$ {' '.join(command)}")
    print(output, end="")
    if success and result.returncode != 0:
        raise SystemExit(f"expected success, got {result.returncode}: {' '.join(command)}")
    if not success and result.returncode == 0:
        raise SystemExit(f"expected RED failure, command succeeded: {' '.join(command)}")
    if contains is not None and contains not in output:
        raise SystemExit(f"expected output fragment {contains!r}: {' '.join(command)}")
    return output


def mosquitto_green() -> None:
    replace_exact(
        "scripts/check_static.py",
        "        if \"mosquitto_passwd -U\" not in init_script:\n"
        "            error(\"Mosquitto bootstrap must convert plaintext input with mosquitto_passwd -U\")\n",
        "",
    )
    for command in (
        ["python3", "scripts/test_init.py"],
        ["python3", "scripts/test_iot_runtime.py"],
        ["python3", "scripts/check_iot_runtime_policy.py"],
        ["python3", "scripts/check_static.py"],
    ):
        run(command, success=True)


def placeholder_red_green() -> None:
    replace_exact(
        "scripts/test_check_images.py",
        "from scripts.check_images import (  # noqa: E402\n"
        "    BACKUP_HELPER_IMAGE,\n"
        "    compose_images,\n",
        "from scripts.check_images import (  # noqa: E402\n"
        "    PLACEHOLDER_SECRETS,\n"
        "    BACKUP_HELPER_IMAGE,\n"
        "    compose_images,\n",
    )
    replace_exact(
        "scripts/test_check_images.py",
        "class LocalComposeInputTests(unittest.TestCase):\n"
        "    def test_prefers_local_env_and_falls_back_to_example(self) -> None:\n",
        "class LocalComposeInputTests(unittest.TestCase):\n"
        "    def test_mosquitto_placeholder_matches_supported_pbkdf2_shape(self) -> None:\n"
        "        value = PLACEHOLDER_SECRETS[\"mosquitto_passwords\"]\n"
        "        self.assertEqual(\n"
        "            value,\n"
        "            \"manifest-check:$7$220000$placeholder$placeholder\",\n"
        "        )\n"
        "        self.assertNotIn(\"argon2id\", value.lower())\n"
        "\n"
        "    def test_prefers_local_env_and_falls_back_to_example(self) -> None:\n",
    )
    replace_exact(
        "scripts/test_check_images.py",
        "            with temporary_secret_placeholders(root):\n"
        "                self.assertTrue((root / \".secrets\").is_dir())\n"
        "\n"
        "            self.assertFalse((root / \".secrets\").exists())\n",
        "            with temporary_secret_placeholders(root):\n"
        "                self.assertTrue((root / \".secrets\").is_dir())\n"
        "                generated = (root / \".secrets\" / \"mosquitto_passwords\").read_text(\n"
        "                    encoding=\"utf-8\"\n"
        "                ).strip()\n"
        "                self.assertEqual(\n"
        "                    generated,\n"
        "                    PLACEHOLDER_SECRETS[\"mosquitto_passwords\"],\n"
        "                )\n"
        "\n"
        "            self.assertFalse((root / \".secrets\").exists())\n",
    )
    run(["python3", "scripts/test_check_images.py"], success=False, contains="manifest-check:$7$220000$")
    replace_exact(
        "scripts/check_images.py",
        "    \"mosquitto_passwords\": (\n"
        "        \"manifest-check:$argon2id$v=19$m=19456,t=2,p=1$placeholder$placeholder\"\n"
        "    ),\n",
        "    \"mosquitto_passwords\": \"manifest-check:$7$220000$placeholder$placeholder\",\n",
    )
    run(["python3", "scripts/test_check_images.py"], success=True)


def documentation_red_green() -> None:
    replace_exact(
        "scripts/check_runtime_policy.py",
        '            "## Четыре уровня проверки",\n',
        '            "### 3. Изолированная runtime-проверка default stack",\n',
    )
    replace_exact(
        "scripts/check_backup_policy.py",
        "    if \"docs/BACKUP.md\" not in readme:\n"
        "        error(\"README must link to docs/BACKUP.md\")\n"
        "    if \"docs/BACKUP.md\" not in migration:\n"
        "        error(\"migration guide must link to docs/BACKUP.md\")\n",
        "    if \"docs/BACKUP.md\" not in readme:\n"
        "        error(\"README must link to docs/BACKUP.md\")\n"
        "    if \"docs/BACKUP.md\" not in migration:\n"
        "        error(\"migration guide must link to docs/BACKUP.md\")\n"
        "    for fragment in (\n"
        "        \"### 5. Изолированная backup/restore runtime-проверка\",\n"
        "        \"make check-backup-runtime\",\n"
        "    ):\n"
        "        if fragment not in readme:\n"
        "            error(f\"README backup verification documentation is missing: {fragment}\")\n",
    )
    replace_exact(
        "scripts/check_static.py",
        "    readme = read_required(\"README.md\")\n"
        "    if readme:\n"
        "        if \"mosquitto:1883\" not in readme:\n"
        "            error(\"README must document the internal MQTT broker address for openHAB\")\n"
        "        if \"make check-images\" not in readme:\n"
        "            error(\"README must document registry-backed image verification\")\n"
        "        if \"linux/amd64\" not in readme or \"linux/arm64\" not in readme:\n"
        "            error(\"README must name both maintained image platforms\")\n"
        "        if \"docs/BACKUP.md\" not in readme or \"make backup\" not in readme:\n"
        "            error(\"README must document the verified backup workflow\")\n",
        "    readme = read_required(\"README.md\")\n"
        "    if readme:\n"
        "        if \"mosquitto:1883\" not in readme:\n"
        "            error(\"README must document the internal MQTT broker address for openHAB\")\n"
        "        if \"make check-images\" not in readme:\n"
        "            error(\"README must document registry-backed image verification\")\n"
        "        if \"linux/amd64\" not in readme or \"linux/arm64\" not in readme:\n"
        "            error(\"README must name both maintained image platforms\")\n"
        "        if \"docs/BACKUP.md\" not in readme or \"make backup\" not in readme:\n"
        "            error(\"README must document the verified backup workflow\")\n"
        "        required_verification_docs = (\n"
        "            \"## Пять уровней проверки\",\n"
        "            \"make check\",\n"
        "            \"make check-images\",\n"
        "            \"make check-runtime\",\n"
        "            \"make check-iot-runtime\",\n"
        "            \"make check-backup-runtime\",\n"
        "            \"| Backup helper Alpine | `3.24.1` |\",\n"
        "        )\n"
        "        for fragment in required_verification_docs:\n"
        "            if fragment not in readme:\n"
        "                error(f\"README verification model is missing: {fragment}\")\n",
    )
    run(["python3", "scripts/check_runtime_policy.py"], success=True)
    run(["python3", "scripts/check_backup_policy.py"], success=False, contains="README backup verification documentation")
    run(["python3", "scripts/check_static.py"], success=False, contains="## Пять уровней проверки")
    replace_exact(
        "README.md",
        "| Bootstrap helper Apache httpd | `2.4.68` |\n",
        "| Bootstrap helper Apache httpd | `2.4.68` |\n| Backup helper Alpine | `3.24.1` |\n",
    )
    replace_exact("README.md", "## Четыре уровня проверки\n", "## Пять уровней проверки\n")
    section = """

### 5. Изолированная backup/restore runtime-проверка

```bash
make check-backup-runtime
```

Создаёт уникальные одноразовые local volumes с вложенными текстовыми и бинарными файлами, пустым файлом, нестандартными permissions и безопасным относительным symlink. Затем выполняет cold backup, офлайн-проверку, удаление source volumes и side-by-side restore в другой project name.

Проверка сравнивает bytes и существенные filesystem metadata, подтверждает отказ для повреждённого snapshot и непустого target volume, а затем удаляет только собственные fixture-ресурсы. Она не запускает приложения homelab и не читает рабочие `.env` или `.secrets/`; подробная процедура восстановления находится в [`docs/BACKUP.md`](docs/BACKUP.md).
"""
    readme = read("README.md")
    if "### 5. Изолированная backup/restore runtime-проверка" in readme:
        raise SystemExit("README already contains fifth verification section")
    write("README.md", readme.rstrip() + section + "\n")
    for command in (
        ["python3", "scripts/check_runtime_policy.py"],
        ["python3", "scripts/check_iot_runtime_policy.py"],
        ["python3", "scripts/check_backup_policy.py"],
        ["python3", "scripts/check_static.py"],
    ):
        run(command, success=True)


def renovate_red_green() -> None:
    replace_exact(
        "scripts/check_static.py",
        "    renovate_path = ROOT / \"renovate.json\"\n"
        "    if renovate_path.is_file():\n"
        "        try:\n"
        "            json.loads(renovate_path.read_text(encoding=\"utf-8\"))\n"
        "        except json.JSONDecodeError as exc:\n"
        "            error(f\"renovate.json is invalid: {exc}\")\n",
        "    renovate_path = ROOT / \"renovate.json\"\n"
        "    if renovate_path.is_file():\n"
        "        try:\n"
        "            renovate = json.loads(renovate_path.read_text(encoding=\"utf-8\"))\n"
        "        except json.JSONDecodeError as exc:\n"
        "            error(f\"renovate.json is invalid: {exc}\")\n"
        "        else:\n"
        "            managers = renovate.get(\"customManagers\", [])\n"
        "            covered = False\n"
        "            if isinstance(managers, list):\n"
        "                for manager in managers:\n"
        "                    if not isinstance(manager, dict):\n"
        "                        continue\n"
        "                    patterns = manager.get(\"managerFilePatterns\", [])\n"
        "                    matches = manager.get(\"matchStrings\", [])\n"
        "                    if (\n"
        "                        manager.get(\"datasourceTemplate\") == \"docker\"\n"
        "                        and isinstance(patterns, list)\n"
        "                        and any(\"scripts\\\\/backup\\\\.py\" in value for value in patterns if isinstance(value, str))\n"
        "                        and isinstance(matches, list)\n"
        "                        and any(\n"
        "                            \"HELPER_IMAGE\" in value and \"depName\" in value and \"currentValue\" in value\n"
        "                            for value in matches if isinstance(value, str)\n"
        "                        )\n"
        "                    ):\n"
        "                        covered = True\n"
        "                        break\n"
        "            if not covered:\n"
        "                error(\"Renovate must discover HELPER_IMAGE in scripts/backup.py through the Docker datasource\")\n",
    )
    run(["python3", "scripts/check_static.py"], success=False, contains="Renovate must discover HELPER_IMAGE")
    path = ROOT / "renovate.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["customManagers"].append(
        {
            "description": "Update the backup helper container image used by scripts/backup.py",
            "customType": "regex",
            "managerFilePatterns": [r"/^scripts\/backup\.py$/"],
            "matchStrings": [r'HELPER_IMAGE\s*=\s*"(?<depName>[^:\s"]+):(?<currentValue>[^\s"]+)"'],
            "datasourceTemplate": "docker",
        }
    )
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    run(["python3", "-m", "json.tool", "renovate.json"], success=True)
    run(["python3", "scripts/check_static.py"], success=True)


def consolidate_backup_tests() -> None:
    replace_exact(
        "scripts/check_backup_policy.py",
        "        \"test_cli_verify_has_no_traceback\",\n",
        "        \"test_cli_verify_has_no_traceback\",\n"
        "        \"test_tar_rejects_non_directory_root_member\",\n"
        "        \"test_later_restore_failure_reports_populated_preexisting_volume\",\n",
    )
    replace_exact(
        "scripts/check_backup_policy.py",
        "    for name in required_test_names:\n"
        "        if name not in tests:\n"
        "            error(f\"backup behavioral contract is missing: {name}\")\n",
        "    for name in required_test_names:\n"
        "        if name not in tests:\n"
        "            error(f\"backup behavioral contract is missing: {name}\")\n"
        "    if (ROOT / \"scripts/test_backup_tar_root.py\").exists():\n"
        "        error(\"backup regressions must live in scripts/test_backup.py, not a separate test file\")\n",
    )
    run(["python3", "scripts/check_backup_policy.py"], success=False, contains="backup behavioral contract is missing")
    marker = '\n\nif __name__ == "__main__":\n    unittest.main(verbosity=2)\n'
    tests = read("scripts/test_backup.py")
    regression_class = r'''

class ConsolidatedBackupRegressionTests(unittest.TestCase):
    def test_tar_rejects_non_directory_root_member(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "regular-root.tar.gz"
            member = tarfile.TarInfo("./")
            member.size = 1
            with tarfile.open(archive_path, "w:gz") as archive:
                archive.addfile(member, io.BytesIO(b"x"))
            with self.assertRaisesRegex(backup.BackupError, "root member"):
                backup.inspect_archive(archive_path)

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
'''
    if tests.count(marker) != 1:
        raise SystemExit("scripts/test_backup.py main marker is missing or duplicated")
    write("scripts/test_backup.py", tests.replace(marker, regression_class + marker, 1))
    replace_exact(
        "scripts/check.sh",
        "python3 scripts/test_backup.py\npython3 scripts/test_backup_tar_root.py\n",
        "python3 scripts/test_backup.py\n",
    )
    (ROOT / "scripts/test_backup_tar_root.py").unlink()
    for command in (
        ["python3", "scripts/test_backup.py"],
        ["python3", "scripts/check_backup_policy.py"],
        ["python3", "scripts/check_static.py"],
    ):
        run(command, success=True)


def final_verification_and_cleanup() -> None:
    for command in (
        ["python3", "scripts/test_init.py"],
        ["python3", "scripts/test_iot_runtime.py"],
        ["python3", "scripts/test_check_images.py"],
        ["python3", "scripts/test_backup.py"],
        ["python3", "scripts/check_iot_runtime_policy.py"],
        ["python3", "scripts/check_runtime_policy.py"],
        ["python3", "scripts/check_backup_policy.py"],
        ["python3", "scripts/check_static.py"],
        ["python3", "-m", "json.tool", "renovate.json"],
        ["./scripts/check.sh"],
        ["git", "diff", "--check"],
    ):
        run(command, success=True)
    for path in (
        ".github/workflows/apply-consistency.yml",
        "tools/apply_consistency_changes.py",
        "tools/apply_consistency_v2.py",
    ):
        (ROOT / path).unlink()
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, text=True, capture_output=True, check=True
    ).stdout
    print(status)
    forbidden = ("tools/", "apply-consistency.yml")
    final_diff = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True
    ).stdout
    if any(value in final_diff for value in forbidden):
        raise SystemExit("transport paths remain in the working-tree diff")


def main() -> int:
    mosquitto_green()
    placeholder_red_green()
    documentation_red_green()
    renovate_red_green()
    consolidate_backup_tests()
    final_verification_and_cleanup()
    print("Consistency and simplification applicator v2 completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
