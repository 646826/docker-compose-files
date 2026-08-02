#!/usr/bin/env python3
"""Unit tests for pinned image scanning and expiring exceptions."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path

from security import (
    SecurityPolicyError,
    active_exceptions,
    build_trivy_command,
    collect_fixable_critical,
    exception_key,
    image_slug,
)

ROOT = Path(__file__).resolve().parents[1]


class SecurityExceptionTests(unittest.TestCase):
    def test_active_exceptions_require_exact_image_id_owner_reason_and_future_date(self) -> None:
        document = {
            "exceptions": [
                {
                    "id": "CVE-2099-0001",
                    "image": "example/image:1.0.0",
                    "reason": "upstream fix is not yet released",
                    "owner": "homelab-maintainers",
                    "expires": "2099-12-31",
                }
            ]
        }
        exceptions = active_exceptions(document, today=date(2099, 1, 1))
        self.assertEqual(
            exceptions,
            {("CVE-2099-0001", "example/image:1.0.0")},
        )

    def test_expired_duplicate_or_incomplete_exceptions_fail(self) -> None:
        cases = (
            {
                "exceptions": [
                    {
                        "id": "CVE-2020-0001",
                        "image": "example/image:1",
                        "reason": "expired",
                        "owner": "owner",
                        "expires": "2020-01-02",
                    }
                ]
            },
            {
                "exceptions": [
                    {
                        "id": "CVE-2099-0001",
                        "image": "example/image:1",
                        "reason": "one",
                        "owner": "owner",
                        "expires": "2099-12-31",
                    },
                    {
                        "id": "CVE-2099-0001",
                        "image": "example/image:1",
                        "reason": "two",
                        "owner": "owner",
                        "expires": "2099-12-31",
                    },
                ]
            },
            {
                "exceptions": [
                    {
                        "id": "CVE-2099-0001",
                        "image": "example/image:1",
                        "reason": "",
                        "owner": "owner",
                        "expires": "2099-12-31",
                    }
                ]
            },
        )
        for document in cases:
            with self.subTest(document=document):
                with self.assertRaises(SecurityPolicyError):
                    active_exceptions(document, today=date(2026, 8, 2))


class VulnerabilityParsingTests(unittest.TestCase):
    def test_only_fixable_critical_vulnerabilities_are_returned(self) -> None:
        report = {
            "Results": [
                {
                    "Target": "example",
                    "Vulnerabilities": [
                        {
                            "VulnerabilityID": "CVE-1",
                            "Severity": "CRITICAL",
                            "PkgName": "openssl",
                            "InstalledVersion": "1",
                            "FixedVersion": "2",
                            "Title": "fixable",
                        },
                        {
                            "VulnerabilityID": "CVE-2",
                            "Severity": "CRITICAL",
                            "PkgName": "busybox",
                            "InstalledVersion": "1",
                            "FixedVersion": "",
                        },
                        {
                            "VulnerabilityID": "CVE-3",
                            "Severity": "HIGH",
                            "PkgName": "curl",
                            "InstalledVersion": "1",
                            "FixedVersion": "2",
                        },
                    ],
                }
            ]
        }
        findings = collect_fixable_critical("example/image:1", report)
        self.assertEqual(len(findings), 1)
        self.assertEqual(exception_key(findings[0]), ("CVE-1", "example/image:1"))

    def test_image_slug_is_path_safe_and_deterministic(self) -> None:
        self.assertEqual(
            image_slug("ghcr.io/example/image:1.2.3@sha256:abcd"),
            "ghcr.io_example_image_1.2.3_sha256_abcd",
        )


class TrivyCommandTests(unittest.TestCase):
    def test_command_uses_pinned_container_and_report_mount(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "report.json"
            command = build_trivy_command(
                "scan",
                image="example/image:1.0.0",
                output=output,
            )
        rendered = " ".join(command)
        self.assertIn("ghcr.io/aquasecurity/trivy:0.70.0", command)
        self.assertNotIn("trivy-action", rendered)
        self.assertNotIn("setup-trivy", rendered)
        self.assertIn("--ignore-unfixed", command)
        self.assertEqual(command[-1], "example/image:1.0.0")

    def test_command_runs_as_calling_user_with_user_owned_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "report.json"
            command = build_trivy_command(
                "scan",
                image="example/image:1.0.0",
                output=output,
            )
        self.assertIn("--user", command)
        self.assertIn(f"{os.getuid()}:{os.getgid()}", command)
        cache_mounts = [
            command[index + 1]
            for index, argument in enumerate(command[:-1])
            if argument == "--volume" and command[index + 1].endswith(":/cache")
        ]
        self.assertEqual(len(cache_mounts), 1)
        self.assertIn("--cache-dir", command)
        self.assertIn("/cache", command)

    def test_sbom_uses_cyclonedx(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "report.cdx.json"
            command = build_trivy_command(
                "sbom",
                image="example/image:1.0.0",
                output=output,
            )
        self.assertIn("cyclonedx", command)
        self.assertNotIn("--ignore-unfixed", command)

    def test_trivy_helper_is_in_multiarch_image_inventory(self) -> None:
        source = (ROOT / "scripts/check_images_community.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'TRIVY_IMAGE = "ghcr.io/aquasecurity/trivy:0.70.0"',
            source,
        )
        self.assertIn("images.add(TRIVY_IMAGE)", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
