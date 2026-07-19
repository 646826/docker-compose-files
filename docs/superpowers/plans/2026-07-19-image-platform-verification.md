# Image Platform Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reject pinned container images that are unavailable or lack `linux/amd64` or `linux/arm64` registry manifests.

**Architecture:** A dependency-free Python checker renders the complete Compose image list with reversible placeholder secret files, adds helper images declared in `scripts/init.sh`, and queries raw registry manifests through Docker Buildx. Unit tests cover pure parsing and local-file lifecycle behavior; a dedicated GitHub Actions job performs the network-backed integration check without pulling image layers or starting containers.

**Tech Stack:** Python 3.11 standard library, Docker Compose v2, Docker Buildx imagetools, Make, GitHub Actions.

## Global Constraints

- Keep `make check` fast and independent of registry availability.
- Required platforms are exactly `linux/amd64` and `linux/arm64`.
- Do not run `make init`, pull image layers, start services, rotate credentials, or mutate volumes during image verification.
- Preserve existing `.env` and `.secrets` files; create and remove only missing temporary placeholders.
- Do not add Python packages, YAML parsers, registry SDKs, or another task runner.
- Inspect every image rendered from all Compose profiles and both helper images from `scripts/init.sh`.
- Retry transient registry inspection failures three times and name the affected image in diagnostics.

---

### Task 1: Define image and manifest policy with failing tests

**Files:**
- Create: `scripts/test_check_images.py`
- Modify: `scripts/check.sh`

**Interfaces:**
- Consumes: a future `scripts.check_images` module.
- Produces: standard-library tests for image discovery, manifest parsing, environment selection, and temporary-file cleanup.

- [x] Add tests importing `compose_images`, `helper_images`, `manifest_platforms`, and `missing_platforms` before the module exists.
- [x] Add tests for selecting `.env` over `.env.example`.
- [x] Add tests proving temporary secret placeholders preserve existing files, remove created files, and remove a directory they created.
- [x] Connect the test module to `scripts/check.sh`.
- [x] Observe the intended RED result in GitHub Actions: the validation job fails because the required module or newly specified functions are absent.

### Task 2: Implement the dependency-free checker

**Files:**
- Create: `scripts/check_images.py`

**Interfaces:**
- Produces:
  - `compose_images(stdout: str) -> set[str]`
  - `helper_images(init_script: str) -> set[str]`
  - `select_env_file(root: Path) -> Path`
  - `temporary_secret_placeholders(root: Path) -> Iterator[None]`
  - `manifest_platforms(raw_manifest: str) -> set[str]`
  - `missing_platforms(platforms: set[str], required: set[str]) -> set[str]`
  - `main() -> int`

- [x] Parse and de-duplicate `docker compose ... config --images` output.
- [x] Extract exactly `HTPASSWD_IMAGE` and `MOSQUITTO_IMAGE` from `scripts/init.sh`.
- [x] Prefer `.env` when present and otherwise use `.env.example`.
- [x] Create only missing secret-source placeholders with private permissions and clean them in a `finally` path.
- [x] Parse Docker manifest lists and OCI indexes; normalize `linux/arm64/v8` to `linux/arm64`; ignore `unknown/unknown` attestations.
- [x] Inspect each image with `docker buildx imagetools inspect --raw IMAGE` and retry failed registry calls three times with 1- and 3-second delays.
- [x] Fail with the exact image and missing platform; return success only when every image has both required platforms.
- [x] Observe the unit/static suite become GREEN in GitHub Actions.

### Task 3: Expose a separate registry-backed command

**Files:**
- Modify: `Makefile`
- Create: `.github/workflows/images.yml`
- Modify: `README.md`
- Modify: `scripts/check_static.py`

**Interfaces:**
- Produces: `make check-images` and a reviewable `Image platforms` GitHub status check.

- [x] Add `check-images` to `.PHONY` without an `init` prerequisite.
- [x] Keep `make check` registry-independent.
- [x] Add a read-only workflow for relevant pull requests, pushes to `main`, manual dispatch, and weekly revalidation.
- [x] Run only checkout, Buildx availability verification, and `make check-images`; do not initialize credentials.
- [x] Preserve a three-day diagnostic artifact only when the network-backed step fails.
- [x] Extend static acceptance checks to reject `make init`, `docker pull`, or `docker run` in the manifest-only path.
- [x] Document the distinction between local configuration checks and registry-backed manifest checks.

### Task 4: Validate real published tags and platforms

**Files:**
- Modify: `compose.yaml` only when registry evidence proves a pin is invalid.

- [x] Open draft pull request #2 before completing implementation.
- [x] Run ordinary CI and confirm Compose/static/bootstrap validation passes.
- [x] Run real Buildx inspection across every Compose and helper image.
- [x] Diagnose the first failure from an uploaded log artifact instead of guessing.
- [x] Confirm `ghcr.io/tecnativa/docker-socket-proxy:0.4.2` and `tecnativa/docker-socket-proxy:0.4.2` are not published.
- [x] Verify upstream publishes the release as `tecnativa/docker-socket-proxy:v0.4.2` with multi-architecture manifests.
- [x] Replace only that invalid image reference.
- [x] Re-run both jobs on the same head and confirm `CI` and `Image platforms` succeed.

### Task 5: Review and integrate

**Files:**
- No production changes unless review finds a concrete defect.

- [ ] Update the pull request description with the final behavior and verification evidence.
- [ ] Review the final diff for credential disclosure, hidden layer pulls, service startup, third-party Python dependencies, and accidental coupling between `make check` and registries.
- [ ] Mark the pull request ready only after both current-head checks succeed.
- [ ] Squash merge with the expected head SHA.
- [ ] Confirm GitHub reports the pull request merged and the merge commit is present on `main`.
