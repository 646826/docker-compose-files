#!/usr/bin/env python3
"""Unit tests for encrypted remote snapshot backups."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from remote_backup import (
    RemoteBackupError,
    build_docker_command,
    parse_environment,
    retention_arguments,
)


class EnvironmentParsingTests(unittest.TestCase):
    def test_parses_comments_and_literal_values_without_shell_evaluation(self) -> None:
        values = parse_environment(
            "# provider settings\nAWS_ACCESS_KEY_ID=example\nENDPOINT=https://s3.example.test/a?b=c\n"
        )
        self.assertEqual(
            values,
            {
                "AWS_ACCESS_KEY_ID": "example",
                "ENDPOINT": "https://s3.example.test/a?b=c",
            },
        )

    def test_rejects_invalid_or_duplicate_keys(self) -> None:
        for text in (
            "lower=value\n",
            "A-B=value\n",
            "DUP=one\nDUP=two\n",
            "MISSING_SEPARATOR\n",
        ):
            with self.subTest(text=text):
                with self.assertRaises(RemoteBackupError):
                    parse_environment(text)


class DockerCommandTests(unittest.TestCase):
    def test_upload_uses_verified_snapshot_and_file_backed_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot = root / "snapshot"
            snapshot.mkdir()
            repository = root / "repository"
            password = root / "password"
            environment = root / "environment"
            repository.write_text("s3:https://example.invalid/bucket\n", encoding="utf-8")
            password.write_text("secret\n", encoding="utf-8")
            environment.write_text("AWS_ACCESS_KEY_ID=not-in-command\n", encoding="utf-8")

            command = build_docker_command(
                "upload",
                project="homelab",
                repository_file=repository,
                password_file=password,
                environment_file=environment,
                snapshot=snapshot,
            )

        rendered = " ".join(command)
        self.assertIn("--env-file", command)
        self.assertNotIn("not-in-command", rendered)
        self.assertNotIn("secret", rendered)
        self.assertIn(f"{snapshot.resolve()}:/snapshot:ro", command)
        self.assertEqual(command[-6:], [
            "backup",
            "/snapshot",
            "--tag",
            "docker-compose-files",
            "--host",
            "homelab",
        ])

    def test_non_upload_actions_reject_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repository"
            password = root / "password"
            snapshot = root / "snapshot"
            repository.write_text("rest:http://example.invalid\n", encoding="utf-8")
            password.write_text("secret\n", encoding="utf-8")
            snapshot.mkdir()
            with self.assertRaises(RemoteBackupError):
                build_docker_command(
                    "check",
                    project="homelab",
                    repository_file=repository,
                    password_file=password,
                    environment_file=None,
                    snapshot=snapshot,
                )

    def test_retention_is_explicit_and_stable(self) -> None:
        self.assertEqual(
            retention_arguments(),
            [
                "forget",
                "--keep-daily", "7",
                "--keep-weekly", "5",
                "--keep-monthly", "12",
                "--keep-yearly", "3",
                "--prune",
            ],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
