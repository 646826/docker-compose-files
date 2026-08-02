#!/usr/bin/env python3
"""Unit tests for community service initialization."""

from __future__ import annotations

import unittest

from init_community import (
    CommunityInitError,
    hash_command,
    render_authelia_configuration,
    render_authelia_users,
    validate_auth_domain,
)


class AutheliaConfigurationTests(unittest.TestCase):
    def test_auth_domain_requires_normal_tls_capable_domain(self) -> None:
        self.assertEqual(validate_auth_domain("home.example.com"), "home.example.com")
        self.assertEqual(validate_auth_domain("example.com"), "example.com")
        for value in ("localhost", "bad domain", "http://example.com", "com", ""):
            with self.subTest(value=value):
                with self.assertRaises(CommunityInitError):
                    validate_auth_domain(value)

    def test_configuration_uses_modern_cookie_and_forwardauth_endpoint(self) -> None:
        config = render_authelia_configuration("home.example.com", "Etc/UTC")
        self.assertIn("implementation: ForwardAuth", config)
        self.assertIn("domain: home.example.com", config)
        self.assertIn("authelia_url: https://auth.home.example.com", config)
        self.assertIn("default_redirection_url: https://home.home.example.com", config)
        self.assertIn("path: /data/db.sqlite3", config)
        self.assertNotIn("session_secret", config)
        self.assertNotIn("encryption_key:", config)

    def test_users_database_contains_only_hash_and_profile(self) -> None:
        users = render_authelia_users(
            username="admin",
            display_name="Homelab Administrator",
            email="admin@example.com",
            password_hash="$2y$12$example",
        )
        self.assertIn("password: '$2y$12$example'", users)
        self.assertIn("displayname: 'Homelab Administrator'", users)
        self.assertNotIn("plaintext", users)
        with self.assertRaises(CommunityInitError):
            render_authelia_users(
                username="Bad User",
                display_name="Bad",
                email="bad@example.com",
                password_hash="$2y$12$example",
            )

    def test_hash_command_never_contains_plaintext_password(self) -> None:
        password = "plain-value-must-not-be-in-command"
        command = hash_command("admin")
        self.assertNotIn(password, " ".join(command))
        self.assertEqual(command[-6:], ["-n", "-i", "-B", "-C", "12", "admin"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
