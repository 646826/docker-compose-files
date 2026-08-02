#!/usr/bin/env python3
"""Regression tests for the isolated community-service runtime harness."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "scripts" / "check_community_runtime.sh"


class CommunityRuntimeContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = RUNTIME.read_text(encoding="utf-8")

    def test_uptime_kuma_first_run_redirect_is_accepted(self) -> None:
        self.assertIn(
            'wait_http "uptime rejects anonymous requests" "$UPTIME_HOST" - 401 ""',
            self.source,
        )
        self.assertIn(
            'wait_http "uptime accepts generated Basic Auth" "$UPTIME_HOST" '
            '"$WORKDIR/auth.curl" 302 "/setup-database"',
            self.source,
        )

    def test_homepage_and_dozzle_still_require_success_responses(self) -> None:
        for label, variable in (
            ("Homepage", "$HOMEPAGE_HOST"),
            ("Dozzle", "$DOZZLE_HOST"),
        ):
            with self.subTest(label=label):
                self.assertIn(
                    f'wait_http "{label} rejects anonymous requests" '
                    f'"{variable}" - 401 ""',
                    self.source,
                )
                self.assertIn(
                    f'wait_http "{label} accepts generated Basic Auth" '
                    f'"{variable}" "$WORKDIR/auth.curl" 200 ""',
                    self.source,
                )

    def test_wait_http_validates_an_optional_response_pattern(self) -> None:
        self.assertIn("expected_pattern=$5", self.source)
        self.assertIn('grep -Fq "$expected_pattern" "$RESPONSE_BODY"', self.source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
