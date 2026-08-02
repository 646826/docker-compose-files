#!/usr/bin/env python3
"""Regression tests for the isolated Authelia runtime harness."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "scripts" / "check_auth_runtime.sh"
MODULE = ROOT / "modules" / "auth" / "compose.yaml"
MAKEFILE = ROOT / "Makefile"


class AuthRuntimeContractTests(unittest.TestCase):
    def test_harness_generates_disposable_configuration_and_validates_it(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")
        for fragment in (
            'BASE_DOMAIN=auth-runtime.example.test',
            'AUTH_MIDDLEWARE=authelia@docker',
            'python3 "$WORKDIR/scripts/init_community.py"',
            'authelia config validate --config /config/configuration.yml',
            '--profile auth',
            '--profile dashboard',
        ):
            self.assertIn(fragment, source)

    def test_harness_verifies_portal_and_forwardauth_redirect(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")
        self.assertIn('wait_portal "auth.$BASE_DOMAIN"', source)
        self.assertIn('wait_forwardauth_redirect "home.$BASE_DOMAIN"', source)
        self.assertIn('https://auth.$BASE_DOMAIN', source)
        self.assertIn("Auth runtime smoke test passed", source)

    def test_harness_is_isolated_and_cleanup_is_scoped(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")
        self.assertIn('mktemp -d "${TMPDIR:-/tmp}/homelab-auth-runtime.XXXXXX"', source)
        self.assertIn("down --volumes --remove-orphans --timeout 30", source)
        for forbidden in (
            '"$ROOT/.env"',
            '"$ROOT/.secrets',
            "--profile dns",
            "docker system " + "prune",
        ):
            self.assertNotIn(forbidden, source)

    def test_authelia_has_an_explicit_bounded_healthcheck(self) -> None:
        module = MODULE.read_text(encoding="utf-8")
        self.assertIn("healthcheck:", module)
        self.assertIn('/app/healthcheck.sh', module)
        self.assertIn("start_period: 20s", module)

    def test_general_commands_include_auth_only_after_initialization(self) -> None:
        makefile = MAKEFILE.read_text(encoding="utf-8")
        self.assertIn(
            "AUTH_PROFILE := $(if $(wildcard .secrets/authelia_configuration.yml),--profile auth,)",
            makefile,
        )
        all_profiles = makefile.split("ALL_PROFILES :=", 1)[1].splitlines()[0]
        self.assertIn("$(AUTH_PROFILE)", all_profiles)


if __name__ == "__main__":
    unittest.main(verbosity=2)
