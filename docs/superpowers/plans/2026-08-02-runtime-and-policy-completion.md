# Runtime and Policy Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct Mosquitto validation drift, enforce an English-only tracked tree, and add isolated runtime verification for Netdata and k6.

**Architecture:** Keep each contract with one focused owner. The IoT policy owns Mosquitto record shapes, a dependency-free Python checker owns tracked-file language validation, and one disposable POSIX-shell harness verifies the remaining optional runtime profiles. Existing commands, images, volumes, and default service scope remain unchanged.

**Tech Stack:** Docker Compose V2, POSIX shell, Python 3.11 standard library, k6 JavaScript, GitHub Actions.

## Global Constraints

- Keep all repository content in English.
- Keep `make check` free of application-container startup and registry access.
- Keep `make up` scoped to core + monitoring + Portainer.
- Keep Netdata and k6 opt-in.
- Preserve `NETDATA_PORT=19999` as the default.
- Keep the Mosquitto operational contract at SHA512-PBKDF2 with exactly 220000 iterations.
- Do not modify image versions, persistent volume names, backup format, or production credentials.
- Use only the Python standard library and existing shell tooling.
- Never run host-wide prune, reset, recursive permission, or volume-deletion commands.

---

### Task 1: Make the IoT policy reject stale Mosquitto placeholders

**Files:**
- Modify: `scripts/check_iot_runtime_policy.py`
- Modify: `scripts/check.sh`
- Modify: `scripts/check_runtime.sh`

**Interfaces:**
- Consumes: the existing `PBKDF2_COMMAND` and `check_hashing_contract()` policy.
- Produces: `check_placeholder_contract(label: str, text: str) -> None` and PBKDF2-shaped placeholders in every operational Compose-rendering path.

- [ ] **Step 1: Add failing policy assertions**

Add a helper that requires `$7$220000$` and rejects `$argon2id$`, then call it for `scripts/check.sh`, `scripts/check_runtime.sh`, and `scripts/check_images.py`.

```python
def check_placeholder_contract(label: str, text: str) -> None:
    if "$7$220000$" not in text:
        error(f"{label} must use a SHA512-PBKDF2 placeholder with 220000 iterations")
    if "$argon2id$" in text:
        error(f"{label} must not use an Argon2id-shaped placeholder")
```

- [ ] **Step 2: Run the focused policy and confirm RED**

Run:

```bash
python3 scripts/check_iot_runtime_policy.py
```

Expected: non-zero with errors naming `scripts/check.sh` and `scripts/check_runtime.sh`.

- [ ] **Step 3: Replace only the two stale placeholder values**

Use these exact non-secret values:

```text
ci:$7$220000$placeholder$placeholder
runtime:$7$220000$placeholder$placeholder
```

- [ ] **Step 4: Run focused tests and confirm GREEN**

Run:

```bash
python3 scripts/check_iot_runtime_policy.py
python3 scripts/test_runtime.py
```

Expected: both commands exit `0`.

- [ ] **Step 5: Commit the correction**

```bash
git add scripts/check_iot_runtime_policy.py scripts/check.sh scripts/check_runtime.sh
git commit -m "fix: enforce PBKDF2 validation placeholders"
```

---

### Task 2: Add a permanent English-only tracked-file gate

**Files:**
- Create: `scripts/check_english_only.py`
- Create: `scripts/test_english_only.py`
- Modify: `scripts/check.sh`

**Interfaces:**
- Produces:
  - `Finding(path: str, line: int, column: int, character: str)`;
  - `find_cyrillic(path: str, text: str) -> list[Finding]`;
  - `scan_paths(root: Path, paths: Iterable[str]) -> list[Finding]`;
  - `tracked_paths(root: Path) -> list[str]`;
  - `main() -> int`.

- [ ] **Step 1: Write unit tests before the checker exists**

Cover:

```python
find_cyrillic("clean.md", "English only\n") == []
```

and exact line/column reporting for characters from the base Cyrillic and Cyrillic Supplement blocks. Verify invalid UTF-8 files are ignored by `scan_paths()` and clean/tracked path order is deterministic.

- [ ] **Step 2: Run the unit test and confirm RED**

Run:

```bash
python3 scripts/test_english_only.py
```

Expected: non-zero because `scripts.check_english_only` does not yet exist.

- [ ] **Step 3: Implement the dependency-free scanner**

Use `git ls-files -z` for the tracked set. Detect these ranges:

```python
CYRILLIC_RANGES = (
    (0x0400, 0x052F),
    (0x1C80, 0x1C8F),
    (0x2DE0, 0x2DFF),
    (0xA640, 0xA69F),
)
```

Skip only files that raise `UnicodeDecodeError`. Print each finding as:

```text
path:line:column: Cyrillic character U+XXXX is not allowed
```

- [ ] **Step 4: Connect unit and repository checks to the fast suite**

Add, before Docker validation:

```sh
python3 scripts/test_english_only.py
python3 scripts/check_english_only.py
```

- [ ] **Step 5: Run focused checks and confirm GREEN**

Run:

```bash
python3 scripts/test_english_only.py
python3 scripts/check_english_only.py
```

Expected: unit tests pass and the current tracked tree reports no Cyrillic text.

- [ ] **Step 6: Commit the language gate**

```bash
git add scripts/check_english_only.py scripts/test_english_only.py scripts/check.sh
git commit -m "test: enforce English-only repository content"
```

---

### Task 3: Parameterize the Netdata listener without changing its default

**Files:**
- Modify: `compose.yaml`
- Modify: `.env.example`
- Modify: `README.md`
- Test through: `scripts/check_optional_runtime_policy.py` from Task 4

**Interfaces:**
- Consumes: `NETDATA_PORT` from the Compose environment.
- Produces: `NETDATA_LISTENER_PORT: ${NETDATA_PORT:-19999}` in the Netdata service.

- [ ] **Step 1: Add the failing policy requirement in Task 4 before editing Compose**

The policy must require both:

```text
NETDATA_LISTENER_PORT: ${NETDATA_PORT:-19999}
NETDATA_PORT=19999
```

- [ ] **Step 2: Confirm the policy fails against the current tree**

Run:

```bash
python3 scripts/check_optional_runtime_policy.py
```

Expected: non-zero naming the missing Compose interpolation, environment default, runtime command, and workflow.

- [ ] **Step 3: Add the environment interpolation**

Under the Netdata service, add:

```yaml
environment:
  NETDATA_LISTENER_PORT: ${NETDATA_PORT:-19999}
```

In `.env.example`, add:

```dotenv
# Netdata uses host networking; change this when port 19999 is already occupied.
NETDATA_PORT=19999
```

- [ ] **Step 4: Update operator documentation**

Document the configurable endpoint as `http://localhost:${NETDATA_PORT}` with the default `19999`, without changing the `make netdata` command.

- [ ] **Step 5: Commit the compatible configuration change**

```bash
git add compose.yaml .env.example README.md
git commit -m "feat: make the Netdata listener port configurable"
```

---

### Task 4: Define and implement optional runtime verification

**Files:**
- Create: `scripts/check_optional_runtime_policy.py`
- Create: `scripts/test_optional_runtime.py`
- Create: `scripts/check_optional_runtime.sh`
- Modify: `scripts/check.sh`
- Modify: `Makefile`

**Interfaces:**
- Produces: `make check-optional-runtime`.
- Runtime inputs: committed `compose.yaml`, `config/k6/smoke.js`, and a generated disposable `.env`/`.secrets` tree.
- Runtime outputs: exit `0` only after a real Netdata CPU sample and a successful k6 threshold run.

- [ ] **Step 1: Write the focused static policy**

Require:

- executable `scripts/check_optional_runtime.sh`;
- a Make target that runs it through POSIX `sh` without `init`;
- Netdata port interpolation and `.env.example` default;
- random `127.0.0.1` port allocation in the harness;
- `/api/v1/info` and a `system.cpu` `/api/v1/data` query;
- `--profile netdata` and `--profile test` only;
- `run --rm k6`;
- scoped `down --volumes --remove-orphans` cleanup;
- no deployment `.env`, deployment `.secrets`, monitoring/tools/IoT profiles, or destructive commands;
- a dedicated workflow and README section.

- [ ] **Step 2: Write behavioral tests before the harness exists**

The fake-command test must prove:

1. success uses a unique project and only Netdata, whoami, and disposable k6;
2. the generated Mosquitto placeholder is PBKDF2-shaped;
3. a Netdata startup failure prints bounded diagnostics and cleans up;
4. a k6 failure propagates non-zero and cleans up;
5. deployment `.env` and `.secrets` sentinels remain unchanged;
6. temporary directories are removed.

- [ ] **Step 3: Connect policy and behavior tests to `scripts/check.sh` and confirm RED**

Add:

```sh
python3 scripts/check_optional_runtime_policy.py
python3 scripts/test_optional_runtime.py
```

Run:

```bash
./scripts/check.sh
```

Expected: non-zero because the runtime harness, Make target, Compose interpolation, workflow, and documentation are not yet complete.

- [ ] **Step 4: Implement the isolated POSIX-shell harness**

The harness must:

- create a mode-`0700` temporary directory;
- choose a free port with Python and write `NETDATA_PORT` to its private `.env`;
- create all Compose secret-source placeholders with no real credentials;
- run `docker compose ... --profile netdata --profile test config --quiet`;
- start `netdata` only;
- poll `/api/v1/info` and validate it as a JSON object;
- poll `api/v1/data?chart=system.cpu&points=1&after=-10&options=jsonwrap` until `data` is non-empty;
- start `whoami` and execute `docker compose --profile test run --rm k6`;
- assert that no default monitoring, tools, or IoT application services were started;
- clean up its unique project and volumes in an EXIT/HUP/INT/TERM path.

- [ ] **Step 5: Add the Make target**

Add `check-optional-runtime` to `.PHONY` and define:

```make
check-optional-runtime: ## Verify Netdata host metrics and the committed k6 smoke test in isolation
	@sh ./scripts/check_optional_runtime.sh
```

- [ ] **Step 6: Run focused checks and confirm GREEN**

Run:

```bash
python3 scripts/check_optional_runtime_policy.py
python3 scripts/test_optional_runtime.py
sh -n scripts/check_optional_runtime.sh
```

Expected: all commands exit `0` without starting real containers.

- [ ] **Step 7: Commit the runtime implementation**

```bash
git add Makefile scripts/check.sh scripts/check_optional_runtime.sh scripts/check_optional_runtime_policy.py scripts/test_optional_runtime.py
git commit -m "test: add isolated Netdata and k6 runtime coverage"
```

---

### Task 5: Add CI, complete documentation, and integrate

**Files:**
- Create: `.github/workflows/optional-runtime.yml`
- Modify: `README.md`
- Modify: the files above only if verification finds a concrete defect

**Interfaces:**
- Produces: the `Optional runtime smoke` GitHub Actions check.

- [ ] **Step 1: Add the read-only workflow**

The workflow must include:

```yaml
name: Optional runtime smoke
permissions:
  contents: read
```

It must run for relevant pull requests, pushes to `main`, weekly schedule, and manual dispatch; execute `make check-optional-runtime`; use a bounded timeout; and upload a three-day diagnostic log only on failure.

- [ ] **Step 2: Document six verification levels**

Rename the README heading to `## Six verification levels`, retain the existing five sections unchanged in meaning, and add:

```markdown
### 6. Isolated optional-profile runtime check

make check-optional-runtime
```

Explain the random Netdata listener, real `system.cpu` sample, real committed k6 smoke test, Linux Docker requirement, and scoped cleanup.

- [ ] **Step 3: Run the complete local suite**

Run:

```bash
./scripts/check.sh
```

Expected: every static, unit, behavior, shell, and Compose check passes.

- [ ] **Step 4: Open a pull request and verify every final-head workflow**

Required checks:

```text
CI
Image platforms
Runtime smoke
IoT runtime smoke
Optional runtime smoke
Backup runtime
```

Inspect any failure log, add a regression test for each concrete defect, and rerun on one exact head SHA.

- [ ] **Step 5: Review the final diff**

Confirm:

- no Cyrillic text;
- no real credentials;
- no Argon2id operational placeholder;
- no new image/version/volume changes;
- no new default-profile service;
- no host-wide cleanup;
- no temporary applicator or write-enabled workflow;
- documentation matches behavior.

- [ ] **Step 6: Squash merge into `main` and verify the remote result**

Merge only the exact verified head SHA. Then confirm the pull request is merged and the resulting squash commit is the newest commit on `main`.
