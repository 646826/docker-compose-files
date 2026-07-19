# Compose Homelab Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the legacy collection of independent Compose files with one secure, profile-based, reproducible homelab stack while retaining all existing functionality and completing the explicit roadmap.

**Architecture:** A root Compose Specification file defines a profile-free Traefik core and optional monitoring, tools, IoT, and test profiles. Local file-backed secrets, named volumes, purpose-specific networks, concise service configuration, validation scripts, CI, and Renovate keep the implementation secure without adding an orchestration framework.

**Tech Stack:** Docker Engine, Docker Compose v2, Traefik 3, InfluxDB 2, Telegraf, Grafana, Portainer CE LTS, Netdata, Eclipse Mosquitto, openHAB, Grafana k6, POSIX shell, Python standard library, GitHub Actions, Renovate.

## Global Constraints

- Support Linux `amd64` and `arm64` with current Docker Engine and Docker Compose v2.
- `make up` must preserve the previous Traefik + InfluxDB + Telegraf + Grafana + Portainer scope.
- Never commit plaintext credentials or generated secret files.
- Never use `latest` or an implicit container tag.
- Never delete volumes, prune the Docker host, reset Git, or recursively loosen host permissions from a normal lifecycle target.
- Keep k3s separate from Docker Compose.
- Add only the services explicitly listed in the README roadmap.

---

### Task 1: Add executable acceptance checks

**Files:**
- Create: `scripts/check_static.py`
- Create: `scripts/check.sh`

**Interfaces:**
- Consumes: repository files from subsequent tasks.
- Produces: `python3 scripts/check_static.py` and `./scripts/check.sh`, both returning zero only for a complete and safe stack.

- [ ] **Step 1: Write the failing static acceptance check**

Create a standard-library Python checker that requires `compose.yaml`, all roadmap services, explicit image tags, local file-backed secrets, valid JSON/TOML, and absence of leaked values or destructive commands.

- [ ] **Step 2: Verify the check fails against the legacy tree**

Run: `python3 scripts/check_static.py`

Expected: non-zero exit with `compose.yaml is missing`.

- [ ] **Step 3: Add the Compose-aware shell wrapper**

The wrapper runs the static checker, `sh -n scripts/*.sh`, creates non-destructive temporary placeholder secret files when needed, and runs:

```sh
docker compose --env-file .env.example --profile monitoring --profile tools --profile iot --profile test config --quiet
```

- [ ] **Step 4: Commit**

```sh
git add scripts/check_static.py scripts/check.sh
git commit -m "test: add homelab configuration checks"
```

### Task 2: Implement the unified Compose project

**Files:**
- Create: `compose.yaml`
- Create: `.env.example`
- Replace: `.gitignore`
- Replace: `Makefile`

**Interfaces:**
- Consumes: `.env` non-secret settings and `.secrets/*` files created by Task 3.
- Produces: profiles `monitoring`, `tools`, `iot`, and `test`; Make targets `init`, `core`, `up`, `full`, `monitoring`, `tools`, `iot`, `k6`, `pull`, `ps`, `logs`, `down`, and `check`.

- [ ] **Step 1: Confirm the acceptance check remains red**

Run: `python3 scripts/check_static.py`

Expected: failure because `compose.yaml` and required services are absent.

- [ ] **Step 2: Add the root Compose model**

Define explicit stable images, named volumes, internal networks, health checks, profile gates, Traefik routing, and local Compose secrets. The profile-free core is `docker-socket-proxy`, `traefik`, and `whoami`.

- [ ] **Step 3: Add safe lifecycle commands**

Make `make up` start `monitoring` + `tools`, `make full` add `iot`, and `make down` omit `--volumes`.

- [ ] **Step 4: Run static validation**

Run: `python3 scripts/check_static.py`

Expected: failure only for configuration files not yet supplied by Task 3.

- [ ] **Step 5: Commit**

```sh
git add compose.yaml .env.example .gitignore Makefile
git commit -m "feat: unify services in profile-based compose stack"
```

### Task 3: Add generated secrets and maintained service configuration

**Files:**
- Create: `scripts/init.sh`
- Create: `config/telegraf/telegraf.conf`
- Create: `config/mosquitto/mosquitto.conf`
- Create: `config/grafana/provisioning/datasources/influxdb.yaml`
- Create: `config/grafana/provisioning/dashboards/default.yaml`
- Create: `config/grafana/dashboards/host-overview.json`
- Create: `config/k6/smoke.js`

**Interfaces:**
- Consumes: `.env` names and Docker for Mosquitto password hashing.
- Produces: `.secrets/influxdb_username`, `.secrets/influxdb_password`, `.secrets/influxdb_token`, `.secrets/grafana_admin_password`, `.secrets/traefik_users`, `.secrets/mosquitto_password`, and `.secrets/mosquitto_passwords` without overwriting existing files.

- [ ] **Step 1: Add idempotent initialization**

Generate missing random values with OpenSSL, build Apache MD5 Basic Auth and Mosquitto password hashes, set directory mode `0700` and file mode `0600`, and copy `.env.example` to `.env` only when absent.

- [ ] **Step 2: Replace generated sample configuration**

Use a concise Telegraf configuration with host/Docker inputs and InfluxDB v2 output through the Docker secret store. Require Mosquitto authentication and persistence.

- [ ] **Step 3: Provision Grafana and k6**

Provision the InfluxDB datasource from environment-injected secret data, a four-panel host dashboard, and a bounded ten-second smoke test.

- [ ] **Step 4: Run all local non-Docker checks**

Run: `python3 scripts/check_static.py && sh -n scripts/init.sh scripts/check.sh`

Expected: `Static checks passed` and zero shell syntax errors.

- [ ] **Step 5: Commit**

```sh
git add scripts config
git commit -m "feat: add secure bootstrap and maintained configs"
```

### Task 4: Document operation and migration

**Files:**
- Replace: `README.md`
- Create: `SECURITY.md`
- Create: `docs/MIGRATION.md`
- Create: `docs/K3S.md`

**Interfaces:**
- Consumes: commands and profile names from Tasks 2 and 3.
- Produces: a copy/paste quick start, service/profile matrix, credential locations, backup guidance, safe legacy data migration, and separate k3s guidance.

- [ ] **Step 1: Write the quick start and operating reference**

Document `make init`, `make up`, profile targets, local URLs, image versions, data volumes, backup commands, and the Netdata/openHAB permission trade-offs.

- [ ] **Step 2: Document the security reset**

State that all historical credentials must be rotated, generated secret files are local only, and Portainer/Netdata have intentionally elevated host visibility.

- [ ] **Step 3: Document migration and k3s separation**

Provide explicit, opt-in copy commands for old bind-mounted data and a reviewed-script k3s installation flow that warns about port conflicts.

- [ ] **Step 4: Re-run static checks**

Run: `python3 scripts/check_static.py`

Expected: `Static checks passed`.

- [ ] **Step 5: Commit**

```sh
git add README.md SECURITY.md docs
git commit -m "docs: add operations migration and k3s guidance"
```

### Task 5: Add continuous validation and dependency maintenance

**Files:**
- Create: `.github/workflows/ci.yml`
- Create: `renovate.json`

**Interfaces:**
- Consumes: `scripts/check.sh`.
- Produces: CI validation for pushes and pull requests and grouped dependency update pull requests.

- [ ] **Step 1: Add CI**

Use `actions/checkout@v6`, minimal `contents: read` permissions, and run `./scripts/check.sh` on Ubuntu.

- [ ] **Step 2: Add Renovate configuration**

Use `config:recommended`, group Compose image updates and GitHub Actions updates separately, and require the dependency dashboard.

- [ ] **Step 3: Run local checks and inspect the rendered model**

Run:

```sh
./scripts/check.sh
docker compose --env-file .env.example --profile monitoring --profile tools --profile iot --profile test config --images
```

Expected: all checks pass and every image is explicitly tagged.

- [ ] **Step 4: Commit**

```sh
git add .github renovate.json
git commit -m "ci: validate compose stack and automate updates"
```

### Task 6: Verify and publish the change

**Files:**
- Review: all changed files.

**Interfaces:**
- Consumes: completed branch.
- Produces: a passing pull request against `main`.

- [ ] **Step 1: Run final validation from a clean checkout**

Run: `./scripts/check.sh`

Expected: static checks, shell checks, and full-profile Compose validation pass.

- [ ] **Step 2: Inspect the branch diff for secrets and unrelated scope**

Run:

```sh
git diff --check main...HEAD
git grep -nE 'bc183SEgTbuNqxLyuGTd2s|home-token|docker system prune|chmod 0777|git reset --hard' || true
```

Expected: no whitespace errors and no matches outside migration/security explanations where values are not reproduced.

- [ ] **Step 3: Open the pull request**

The pull request body must list compatibility, added roadmap services, security changes, migration requirements, and exact validation results.
