#!/usr/bin/env python3
"""Unit tests for image discovery and multi-platform manifest validation."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.check_images import (  # noqa: E402
    compose_images,
    helper_images,
    manifest_platforms,
    missing_platforms,
    select_env_file,
    temporary_secret_placeholders,
)


class ComposeImagesTests(unittest.TestCase):
    def test_normalizes_and_deduplicates_rendered_images(self) -> None:
        rendered = "\n traefik:v3.7.8\n\ngrafana/grafana:13.1.0\ntraefik:v3.7.8\n"

        self.assertEqual(
            compose_images(rendered),
            {"traefik:v3.7.8", "grafana/grafana:13.1.0"},
        )

    def test_rejects_an_empty_rendered_image_list(self) -> None:
        with self.assertRaisesRegex(ValueError, "no images"):
            compose_images(" \n\t\n")


class HelperImagesTests(unittest.TestCase):
    def test_extracts_exact_bootstrap_helper_assignments(self) -> None:
        script = """
ROOT=/tmp/example
HTPASSWD_IMAGE=httpd:2.4.68-alpine
MOSQUITTO_IMAGE=eclipse-mosquitto:2.1.2-alpine
OTHER_IMAGE=ignored:1
"""

        self.assertEqual(
            helper_images(script),
            {"httpd:2.4.68-alpine", "eclipse-mosquitto:2.1.2-alpine"},
        )

    def test_rejects_a_missing_helper_assignment(self) -> None:
        with self.assertRaisesRegex(ValueError, "MOSQUITTO_IMAGE"):
            helper_images("HTPASSWD_IMAGE=httpd:2.4.68-alpine\n")


class LocalComposeInputTests(unittest.TestCase):
    def test_prefers_local_env_and_falls_back_to_example(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            example = root / ".env.example"
            example.write_text("BASE_DOMAIN=localhost\n", encoding="utf-8")

            self.assertEqual(select_env_file(root), example)

            local = root / ".env"
            local.write_text("BASE_DOMAIN=home.arpa\n", encoding="utf-8")
            self.assertEqual(select_env_file(root), local)

    def test_temporary_placeholders_preserve_existing_files_and_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            secrets = root / ".secrets"
            secrets.mkdir()
            existing = secrets / "influxdb_token"
            existing.write_text("keep-me\n", encoding="utf-8")

            with temporary_secret_placeholders(root):
                self.assertEqual(existing.read_text(encoding="utf-8"), "keep-me\n")
                for name in (
                    "influxdb_username",
                    "influxdb_password",
                    "influxdb_token",
                    "grafana_admin_password",
                    "traefik_users",
                    "mosquitto_passwords",
                ):
                    self.assertTrue((secrets / name).is_file(), name)

            self.assertEqual(existing.read_text(encoding="utf-8"), "keep-me\n")
            self.assertEqual(
                {path.name for path in secrets.iterdir()},
                {"influxdb_token"},
            )

    def test_temporary_placeholders_remove_a_created_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            with temporary_secret_placeholders(root):
                self.assertTrue((root / ".secrets").is_dir())

            self.assertFalse((root / ".secrets").exists())


class ManifestPlatformsTests(unittest.TestCase):
    def test_parses_docker_manifest_list_and_normalizes_arm64_variant(self) -> None:
        raw = json.dumps(
            {
                "schemaVersion": 2,
                "mediaType": "application/vnd.docker.distribution.manifest.list.v2+json",
                "manifests": [
                    {"platform": {"os": "linux", "architecture": "amd64"}},
                    {
                        "platform": {
                            "os": "linux",
                            "architecture": "arm64",
                            "variant": "v8",
                        }
                    },
                    {"platform": {"os": "unknown", "architecture": "unknown"}},
                ],
            }
        )

        self.assertEqual(
            manifest_platforms(raw),
            {"linux/amd64", "linux/arm64"},
        )

    def test_parses_oci_index_and_ignores_non_linux_descriptors(self) -> None:
        raw = json.dumps(
            {
                "schemaVersion": 2,
                "mediaType": "application/vnd.oci.image.index.v1+json",
                "manifests": [
                    {"platform": {"os": "linux", "architecture": "amd64"}},
                    {"platform": {"os": "linux", "architecture": "arm64"}},
                    {"platform": {"os": "windows", "architecture": "amd64"}},
                ],
            }
        )

        self.assertEqual(
            manifest_platforms(raw),
            {"linux/amd64", "linux/arm64"},
        )

    def test_single_platform_manifest_has_no_multi_platform_descriptors(self) -> None:
        raw = json.dumps(
            {
                "schemaVersion": 2,
                "mediaType": "application/vnd.oci.image.manifest.v1+json",
                "config": {"digest": "sha256:example"},
                "layers": [],
            }
        )

        self.assertEqual(manifest_platforms(raw), set())

    def test_rejects_malformed_json(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid manifest JSON"):
            manifest_platforms("not-json")


class MissingPlatformsTests(unittest.TestCase):
    def test_reports_only_required_platforms_that_are_absent(self) -> None:
        self.assertEqual(
            missing_platforms(
                {"linux/amd64", "linux/arm/v7"},
                {"linux/amd64", "linux/arm64"},
            ),
            {"linux/arm64"},
        )

    def test_reports_no_gap_when_all_required_platforms_exist(self) -> None:
        self.assertEqual(
            missing_platforms(
                {"linux/amd64", "linux/arm64", "linux/s390x"},
                {"linux/amd64", "linux/arm64"},
            ),
            set(),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
