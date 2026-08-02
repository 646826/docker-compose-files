#!/usr/bin/env python3
"""Unit tests for the guarded AdGuard Home DNS preflight."""

from __future__ import annotations

import unittest

from dns_preflight import diagnose_dns_port, parse_port, validate_bind_address


class DNSPreflightTests(unittest.TestCase):
    def test_free_port_has_no_blocking_errors(self) -> None:
        issues = diagnose_dns_port("0.0.0.0", 53, set(), "")
        self.assertEqual(issues, [])

    def test_wildcard_and_specific_listeners_conflict(self) -> None:
        for bind, listeners in (
            ("127.0.0.1", {("0.0.0.0", 53)}),
            ("0.0.0.0", {("127.0.0.1", 53)}),
            ("::1", {("::", 53)}),
        ):
            with self.subTest(bind=bind):
                issues = diagnose_dns_port(bind, 53, listeners, "dnsmasq")
                self.assertEqual(len(issues), 1)
                self.assertIn("already in use", issues[0])

    def test_systemd_resolved_receives_exact_remediation(self) -> None:
        issues = diagnose_dns_port(
            "0.0.0.0",
            53,
            {("127.0.0.53", 53)},
            "systemd-resolved pid=611",
        )
        self.assertEqual(len(issues), 1)
        self.assertIn("systemd-resolved", issues[0])
        self.assertIn("do not disable it automatically", issues[0])

    def test_address_and_port_validation(self) -> None:
        self.assertEqual(validate_bind_address("127.0.0.1"), "127.0.0.1")
        self.assertEqual(validate_bind_address("::"), "::")
        for value in ("localhost", "999.1.1.1", ""):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_bind_address(value)
        self.assertEqual(parse_port("53"), 53)
        for value in ("0", "65536", "dns"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_port(value)


if __name__ == "__main__":
    unittest.main(verbosity=2)
