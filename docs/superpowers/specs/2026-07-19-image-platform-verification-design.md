# Image Platform Verification Design

## Goal

Prevent a syntactically valid Compose change from being merged when a pinned container tag is missing or does not support both maintained target architectures: `linux/amd64` and `linux/arm64`.

## Scope

The check covers every image rendered by the full Compose model and every helper image used by `scripts/init.sh`. It verifies registry manifests only; it does not pull layers, start services, rotate credentials, mutate volumes, or claim that application-level startup succeeds.

The existing fast `make check` remains offline apart from the Docker Compose parser. Registry verification is exposed separately as `make check-images` and runs in a dedicated GitHub Actions job on relevant pull requests, pushes to `main`, manual dispatches, and a weekly schedule.

## Architecture

`scripts/check_images.py` contains small pure functions for:

1. parsing image references from `docker compose ... config --images` output;
2. extracting the pinned helper-image assignments from `scripts/init.sh`;
3. selecting `.env` when present and otherwise using `.env.example`;
4. creating only missing temporary Compose secret-source files and cleaning up exactly those files;
5. parsing an OCI image index or Docker manifest list returned by `docker buildx imagetools inspect --raw`;
6. comparing available Linux platforms with the required set.

The command-line entry point renders the complete Compose model, combines and de-duplicates its images with helper images, and inspects each registry reference. Registry calls are retried three times for transient failures. Any missing tag, malformed manifest, or absent maintained architecture exits non-zero and names the affected image and missing platform.

The Make target does not depend on `make init`. Real `.env` and `.secrets` values are preserved when present; a clean checkout uses `.env.example` plus reversible placeholder secret files solely to satisfy Compose model validation.

## Interfaces

- `compose_images(stdout: str) -> set[str]`
- `helper_images(init_script: str) -> set[str]`
- `select_env_file(root: Path) -> Path`
- `temporary_secret_placeholders(root: Path) -> ContextManager[None]`
- `manifest_platforms(raw_manifest: str) -> set[str]`
- `missing_platforms(platforms: set[str], required: set[str]) -> set[str]`
- CLI: `python3 scripts/check_images.py`

The required platform set is fixed to `linux/amd64` and `linux/arm64`, matching the repository support statement.

## Error handling

The checker fails clearly when Docker, Compose, or Buildx is unavailable; when neither environment file exists; when the rendered image list is empty; when a helper assignment is missing; when a required secret path has an incompatible type; when registry inspection fails after retries; when JSON is invalid; or when either maintained platform is absent. Attestation descriptors reported as `unknown/unknown` are ignored.

Temporary files are cleaned in a `finally` path. Existing local files are never overwritten or removed.

## Testing

`scripts/test_check_images.py` uses only the Python standard library. It covers image-list normalization, helper assignment extraction, environment-file selection, preservation and cleanup of temporary secret placeholders, Docker and OCI index parsing, attestation filtering, single-platform manifests, missing-platform calculation, and malformed JSON. Tests were introduced before the corresponding implementation and observed failing in GitHub Actions before the green implementation commit.

GitHub Actions then provides the integration proof by running the actual Buildx registry inspection against every pinned tag.

## Non-goals

- pulling image layers;
- starting containers in shared CI;
- creating or rotating deployment credentials;
- vulnerability scanning or SBOM policy enforcement;
- digest pinning;
- supporting additional architectures beyond the two documented targets;
- adding a custom registry client or third-party Python dependencies.
