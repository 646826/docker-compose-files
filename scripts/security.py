#!/usr/bin/env python3
"""Generate SBOMs and enforce fixable-critical container vulnerability policy."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
TRIVY_IMAGE = "ghcr.io/aquasecurity/trivy:0.70.0"
REPORT_ROOT = ROOT / "security-reports"
SBOM_ROOT = ROOT / "sbom"
EXCEPTIONS_FILE = ROOT / "security" / "exceptions.json"
IMAGE_RE = re.compile(r"(?m)^\s{4}image:\s*['\"]?([^'\"#\s]+)")
ASSIGNMENT_RE = re.compile(
    r"(?m)^(?:HTPASSWD_IMAGE|MOSQUITTO_IMAGE|HELPER_IMAGE|RESTIC_IMAGE)\s*=\s*[\"']?([^\s\"']+)"
)


class SecurityPolicyError(RuntimeError):
    """Raised when scanner inputs or results violate repository policy."""


@dataclass(frozen=True)
class Finding:
    vulnerability_id: str
    image: str
    target: str
    package: str
    installed_version: str
    fixed_version: str
    title: str


def image_slug(image: str) -> str:
    """Return a deterministic path-safe image identifier."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", image).strip("_")


def discover_images(root: Path = ROOT) -> set[str]:
    """Discover all module and helper images without starting Docker."""
    images: set[str] = set()
    for path in sorted((root / "modules").glob("*/compose.yaml")):
        images.update(IMAGE_RE.findall(path.read_text(encoding="utf-8")))
    for relative in (
        "scripts/init.sh",
        "scripts/backup.py",
        "scripts/remote_backup.py",
    ):
        path = root / relative
        if path.is_file():
            images.update(ASSIGNMENT_RE.findall(path.read_text(encoding="utf-8")))
    images.add(TRIVY_IMAGE)
    if not images:
        raise SecurityPolicyError("no container images were discovered")
    for image in images:
        final = image.rsplit("/", 1)[-1]
        if ":" not in final or final.endswith(":latest"):
            raise SecurityPolicyError(f"unversioned image cannot be scanned: {image}")
    return images


def build_trivy_command(action: str, *, image: str, output: Path) -> list[str]:
    """Build a direct pinned-container Trivy invocation."""
    if action not in {"scan", "sbom"}:
        raise SecurityPolicyError(f"unsupported Trivy action: {action}")
    output = output.resolve()
    command = [
        "docker",
        "run",
        "--rm",
        "--volume",
        "docker-compose-files_trivy_cache:/root/.cache/trivy",
        "--volume",
        f"{output.parent}:/reports",
        TRIVY_IMAGE,
        "image",
        "--quiet",
        "--output",
        f"/reports/{output.name}",
    ]
    if action == "scan":
        command.extend(
            (
                "--format",
                "json",
                "--scanners",
                "vuln",
                "--severity",
                "HIGH,CRITICAL",
                "--ignore-unfixed",
            )
        )
    else:
        command.extend(("--format", "cyclonedx"))
    command.append(image)
    return command


def exception_key(finding: Finding) -> tuple[str, str]:
    return finding.vulnerability_id, finding.image


def active_exceptions(
    document: Mapping[str, object],
    *,
    today: date | None = None,
) -> set[tuple[str, str]]:
    """Validate and return non-expired exact CVE/image exceptions."""
    today = today or date.today()
    raw = document.get("exceptions")
    if not isinstance(raw, list):
        raise SecurityPolicyError("security exceptions document must contain an exceptions list")
    active: set[tuple[str, str]] = set()
    required = {"id", "image", "reason", "owner", "expires"}
    for index, item in enumerate(raw):
        if not isinstance(item, dict) or set(item) != required:
            raise SecurityPolicyError(f"security exception {index} has an invalid schema")
        values = {key: item[key] for key in required}
        if any(not isinstance(value, str) or not value.strip() for value in values.values()):
            raise SecurityPolicyError(f"security exception {index} contains an empty value")
        try:
            expires = date.fromisoformat(values["expires"])
        except ValueError as exc:
            raise SecurityPolicyError(
                f"security exception {index} has an invalid expiration date"
            ) from exc
        if expires <= today:
            raise SecurityPolicyError(
                f"security exception is expired: {values['id']} for {values['image']}"
            )
        key = (values["id"], values["image"])
        if key in active:
            raise SecurityPolicyError(
                f"security exception is duplicated: {values['id']} for {values['image']}"
            )
        active.add(key)
    return active


def collect_fixable_critical(image: str, report: Mapping[str, object]) -> list[Finding]:
    """Extract fixable CRITICAL findings from a Trivy JSON report."""
    findings: list[Finding] = []
    results = report.get("Results")
    if results is None:
        return findings
    if not isinstance(results, list):
        raise SecurityPolicyError(f"Trivy report has invalid Results for {image}")
    for result in results:
        if not isinstance(result, dict):
            continue
        target = str(result.get("Target", ""))
        vulnerabilities = result.get("Vulnerabilities") or []
        if not isinstance(vulnerabilities, list):
            raise SecurityPolicyError(f"Trivy report has invalid vulnerabilities for {image}")
        for vulnerability in vulnerabilities:
            if not isinstance(vulnerability, dict):
                continue
            if vulnerability.get("Severity") != "CRITICAL":
                continue
            fixed_version = str(vulnerability.get("FixedVersion", "")).strip()
            if not fixed_version:
                continue
            vulnerability_id = str(vulnerability.get("VulnerabilityID", "")).strip()
            if not vulnerability_id:
                raise SecurityPolicyError(f"Trivy CRITICAL finding has no ID for {image}")
            findings.append(
                Finding(
                    vulnerability_id=vulnerability_id,
                    image=image,
                    target=target,
                    package=str(vulnerability.get("PkgName", "")),
                    installed_version=str(vulnerability.get("InstalledVersion", "")),
                    fixed_version=fixed_version,
                    title=str(vulnerability.get("Title", "")),
                )
            )
    return findings


def run(command: Sequence[str]) -> None:
    try:
        result = subprocess.run(
            list(command),
            cwd=ROOT,
            check=False,
            text=True,
            timeout=900,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise SecurityPolicyError(f"scanner execution failed: {exc}") from exc
    if result.returncode != 0:
        raise SecurityPolicyError(
            f"scanner command failed with status {result.returncode}: {command[-1]}"
        )


def generate(action: str, images: Iterable[str], output_root: Path) -> list[Path]:
    output_root.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    suffix = ".vulnerabilities.json" if action == "scan" else ".cdx.json"
    for image in sorted(images):
        output = output_root / f"{image_slug(image)}{suffix}"
        print(f"Trivy {action}: {image}", flush=True)
        run(build_trivy_command(action, image=image, output=output))
        outputs.append(output)
    return outputs


def load_json(path: Path) -> Mapping[str, object]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SecurityPolicyError(f"cannot parse JSON file {path}: {exc}") from exc
    if not isinstance(document, dict):
        raise SecurityPolicyError(f"JSON document must be an object: {path}")
    return document


def enforce(reports: Iterable[Path], exceptions: set[tuple[str, str]]) -> list[Finding]:
    blocked: list[Finding] = []
    all_findings: list[Finding] = []
    for report_path in reports:
        document = load_json(report_path)
        artifact = str(document.get("ArtifactName", "")).strip()
        if not artifact:
            raise SecurityPolicyError(f"Trivy report has no ArtifactName: {report_path}")
        findings = collect_fixable_critical(artifact, document)
        all_findings.extend(findings)
        blocked.extend(finding for finding in findings if exception_key(finding) not in exceptions)

    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    summary = {
        "policy": "fail on fixable CRITICAL vulnerabilities",
        "findings": [asdict(finding) for finding in all_findings],
        "blocked": [asdict(finding) for finding in blocked],
    }
    (REPORT_ROOT / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return blocked


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("images", "scan", "sbom", "check"))
    parser.add_argument("--exceptions", type=Path, default=EXCEPTIONS_FILE)
    args = parser.parse_args()

    try:
        images = discover_images()
        if args.action == "images":
            print("\n".join(sorted(images)))
            return 0
        if args.action == "sbom":
            outputs = generate("sbom", images, SBOM_ROOT)
            print(f"Generated {len(outputs)} CycloneDX SBOM files")
            return 0

        reports = generate("scan", images, REPORT_ROOT)
        if args.action == "scan":
            print(f"Generated {len(reports)} vulnerability reports")
            return 0

        exceptions = active_exceptions(load_json(args.exceptions))
        blocked = enforce(reports, exceptions)
        if blocked:
            for finding in blocked:
                print(
                    f"BLOCKED: {finding.vulnerability_id} in {finding.image} "
                    f"{finding.package} {finding.installed_version} -> {finding.fixed_version}",
                    file=sys.stderr,
                )
            return 1
        print("Security policy passed: no unexcepted fixable CRITICAL vulnerabilities")
        return 0
    except SecurityPolicyError as exc:
        print(f"Security check failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
