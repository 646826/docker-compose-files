#!/usr/bin/env python3
"""Validate that TLS remains explicit, external, and free of tracked key material."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ERRORS: list[str] = []


def read_required(path: str) -> str:
    target = ROOT / path
    if not target.is_file():
        ERRORS.append(f"{path} is missing")
        return ""
    return target.read_text(encoding="utf-8")


def main() -> int:
    root = read_required("compose.yaml")
    modules = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((ROOT / "modules").glob("*/compose.yaml"))
    )
    override = read_required("examples/tls/compose.tls.yaml")
    dynamic = read_required("examples/tls/traefik-dynamic.template.yaml")
    lan = read_required("docs/TLS-LAN.md")
    public = read_required("docs/TLS-PUBLIC.md")
    gitignore = read_required(".gitignore")

    default_model = f"{root}\n{modules}"
    for fragment in (
        "--entrypoints.websecure.address=:443",
        "certificatesresolvers.",
        "acme.storage",
        ":443:443",
    ):
        if fragment in default_model:
            ERRORS.append(f"default Compose must not enable public TLS: {fragment}")

    for label, text in (("TLS override", override), ("dynamic TLS template", dynamic)):
        if "-----BEGIN" in text or "PRIVATE KEY" in text:
            ERRORS.append(f"{label} must not contain certificate or private-key material")

    for fragment in (
        "${TLS_DYNAMIC_DIR:?",
        "${TLS_CERT_DIR:?",
        "--providers.file.directory=/etc/traefik/dynamic",
        "--entrypoints.websecure.address=:443",
    ):
        if fragment not in override:
            ERRORS.append(f"TLS override is missing: {fragment}")

    for fragment in (
        "certFile: /etc/traefik/certs/fullchain.pem",
        "keyFile: /etc/traefik/certs/privkey.pem",
        "replace-with-your-domain.invalid",
    ):
        if fragment not in dynamic:
            ERRORS.append(f"dynamic TLS template is missing: {fragment}")

    if "/local/" not in gitignore:
        ERRORS.append(".gitignore must exclude /local/ TLS material")

    for label, document, fragments in (
        (
            "LAN TLS documentation",
            lan,
            (
                "root-ca.key",
                "examples/tls/compose.tls.yaml",
                "AUTH_MIDDLEWARE=local-auth@docker",
                "Rollback",
            ),
        ),
        (
            "public TLS documentation",
            public,
            (
                "ACME DNS-01",
                "staging",
                "least-privilege",
                "AUTH_MIDDLEWARE=local-auth@docker",
                "Rollback",
            ),
        ),
    ):
        for fragment in fragments:
            if fragment not in document:
                ERRORS.append(f"{label} is missing: {fragment}")

    tracked_key_patterns = (
        "*.key",
        "*.pem",
        "acme.json",
    )
    for path in ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        relative = path.relative_to(ROOT)
        if relative.parts and relative.parts[0] in {"docs", "examples"}:
            continue
        if path.suffix.lower() in {".key", ".pem", ".crt", ".p12", ".pfx"}:
            ERRORS.append(f"tracked TLS material is forbidden: {relative}")
        if path.name == "acme.json":
            ERRORS.append(f"tracked ACME storage is forbidden: {relative}")

    if re.search(r"(?m)^\s*(?:CF_DNS_API_TOKEN|AWS_SECRET_ACCESS_KEY|DNS_PROVIDER_API_TOKEN)=\S+", default_model):
        ERRORS.append("default Compose contains a DNS-provider credential value")

    if ERRORS:
        for message in ERRORS:
            print(f"ERROR: {message}", file=sys.stderr)
        return 1
    print("TLS example policy checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
