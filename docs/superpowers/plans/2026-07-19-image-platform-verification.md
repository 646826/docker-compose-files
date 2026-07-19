# Image Platform Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reject pinned container images that are unavailable or lack `linux/amd64` or `linux/arm64` registry manifests.

**Architecture:** A dependency-free Python checker renders the full Compose image list, adds helper images declared in `scripts/init.sh`, queries raw registry manifests through Docker Buildx, and validates the documented platform set. Pure parser functions are unit tested; a separate GitHub Actions job performs the network-backed integration check.

**Tech Stack:** Python 3.11 standard library, Docker Compose v2, Docker Buildx imagetools, Make, GitHub Actions.

## Global Constraints

- Keep `make check` fast and do not make ordinary local validation depend on registry availability.
- Required platforms are exactly `linux/amd64` and `linux/arm64`.
- Do not pull all image layers or start application services.
- Do not add Python packages, YAML parsers, registry SDKs, or another task runner.
- Inspect every rendered Compose image and the `HTPASSWD_IMAGE` and `MOSQUITTO_IMAGE` helpers from `scripts/init.sh`.
- Retry transient registry inspection failures three times, then fail with the image reference and stderr.

---

### Task 1: Add failing parser and policy tests

**Files:**
- Create: `scripts/test_check_images.py`
- Modify: `scripts/check.sh`

**Interfaces:**
- Consumes: a future `scripts.check_images` module.
- Produces: executable unit tests covering the public pure functions.

- [ ] **Step 1: Create tests before implementation**

Create `scripts/test_check_images.py` with `unittest` cases for:

```python
from scripts.check_images import (
    compose_images,
    helper_images,
    manifest_platforms,
    missing_platforms,
)
```

Assertions must cover sorted/de-duplicated Compose images, exact extraction of `HTPASSWD_IMAGE` and `MOSQUITTO_IMAGE`, Docker manifest-list and OCI-index descriptors, ignoring `unknown/unknown` attestations, returning an empty set for a single-platform manifest, malformed JSON raising `ValueError`, and required-platform differences.

- [ ] **Step 2: Wire the new test into the existing suite**

Add this line after the bootstrap test in `scripts/check.sh`:

```sh
python3 scripts/test_check_images.py
```

- [ ] **Step 3: Verify the test fails for the intended reason**

Run:

```bash
python3 scripts/test_check_images.py
```

Expected: non-zero exit with `ModuleNotFoundError: No module named 'scripts.check_images'`.

- [ ] **Step 4: Commit the red test**

```bash
git add scripts/test_check_images.py scripts/check.sh
git commit -m "test: define image platform verification"
```

### Task 2: Implement the dependency-free checker

**Files:**
- Create: `scripts/check_images.py`

**Interfaces:**
- Produces:
  - `compose_images(stdout: str) -> set[str]`
  - `helper_images(init_script: str) -> set[str]`
  - `manifest_platforms(raw_manifest: str) -> set[str]`
  - `missing_platforms(platforms: set[str], required: set[str]) -> set[str]`
  - `main() -> int`

- [ ] **Step 1: Implement pure parsing functions**

Use `json.loads`, line-based image normalization, and an anchored regular expression for exactly these shell assignments:

```python
HELPER_KEYS = ("HTPASSWD_IMAGE", "MOSQUITTO_IMAGE")
REQUIRED_PLATFORMS = {"linux/amd64", "linux/arm64"}
```

For manifest indexes, read `manifests[*].platform.os`, `.architecture`, and optional `.variant`. Normalize `linux/arm64/v8` to `linux/arm64`; ignore descriptors with unknown OS or architecture. A raw single-image manifest has no `manifests` array and therefore returns an empty platform set.

- [ ] **Step 2: Implement external command execution**

Render images with:

```bash
docker compose --env-file .env --profile monitoring --profile tools --profile iot --profile netdata --profile test config --images
```

Inspect each reference with:

```bash
docker buildx imagetools inspect --raw IMAGE
```

Use `subprocess.run(..., check=False, capture_output=True, text=True)`. Retry inspection up to three times with delays of 1 and 3 seconds before the final attempt. Do not retry parser or policy failures.

- [ ] **Step 3: Implement CLI diagnostics**

Check `docker compose version` and `docker buildx version` first. Print one `Checking IMAGE` line per unique sorted image. On success print:

```text
Image manifest checks passed: N images support linux/amd64 and linux/arm64
```

On failure print a concise message to stderr and return `1`; return `0` only after all images pass.

- [ ] **Step 4: Verify green unit tests**

Run:

```bash
python3 scripts/test_check_images.py
```

Expected: all tests pass with exit code `0`.

- [ ] **Step 5: Verify the existing static suite**

Run:

```bash
python3 scripts/check_static.py
python3 scripts/test_init.py
sh -n scripts/init.sh scripts/check.sh
python3 -m py_compile scripts/check_images.py scripts/test_check_images.py
```

Expected: all commands exit `0`.

- [ ] **Step 6: Commit the implementation**

```bash
git add scripts/check_images.py
git commit -m "feat: verify image platform manifests"
```

### Task 3: Expose the check and run it in CI

**Files:**
- Modify: `Makefile`
- Create: `.github/workflows/images.yml`
- Modify: `README.md`
- Modify: `scripts/check_static.py`

**Interfaces:**
- Produces: `make check-images` and a network-backed CI status check.

- [ ] **Step 1: Add the Make target**

Add `check-images` to `.PHONY` and define:

```make
check-images: init ## Verify pinned image tags and amd64/arm64 registry manifests
	@python3 scripts/check_images.py
```

Do not add this dependency to `make check`.

- [ ] **Step 2: Add the dedicated workflow**

Create `.github/workflows/images.yml` with read-only permissions, concurrency cancellation, a 15-minute timeout, and triggers for `workflow_dispatch`, weekly schedule, pushes to `main`, and pull requests changing image-related files. Steps are checkout, `docker buildx version`, `make init`, and `make check-images`.

- [ ] **Step 3: Extend static acceptance checks**

Make `scripts/check_static.py` require the new Make target, test file, checker file, and workflow. Require the workflow command `make check-images`, while preserving existing destructive-command and secret checks.

- [ ] **Step 4: Document the distinction**

Add `make check-images` to the command table and explain that `make check` validates local configuration while `make check-images` contacts registries and verifies tag availability plus both supported architectures.

- [ ] **Step 5: Run all non-network checks**

```bash
python3 scripts/check_static.py
python3 scripts/test_init.py
python3 scripts/test_check_images.py
sh -n scripts/init.sh scripts/check.sh
python3 -m py_compile scripts/*.py
```

Expected: all commands exit `0`.

- [ ] **Step 6: Commit integration and documentation**

```bash
git add Makefile .github/workflows/images.yml README.md scripts/check_static.py
git commit -m "ci: validate pinned multi-platform images"
```

### Task 4: Verify the real registry integration

**Files:**
- No production changes unless verification exposes an invalid tag or missing architecture.

- [ ] **Step 1: Open a pull request**

The PR description must separate unit/static validation from the registry-backed GitHub Actions result.

- [ ] **Step 2: Confirm the original CI job passes**

Expected: `Validate Compose project` succeeds.

- [ ] **Step 3: Confirm image verification passes**

Expected: every Compose and helper image resolves and reports both `linux/amd64` and `linux/arm64`. If a tag or architecture fails, correct the pinned version only after checking the upstream release and image publication source; then rerun both jobs.

- [ ] **Step 4: Review the final diff**

Verify no image layers are pulled by the checker, no credentials are printed, `make check` remains registry-independent, and no third-party Python dependency was introduced.

- [ ] **Step 5: Merge only after both checks pass**

Use squash merge and retain the branch until GitHub reports the merge commit on `main`.
