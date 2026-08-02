# Runtime and Policy Completion Design

## Goal

Close the remaining verified gaps in the homelab repository without expanding the service catalog or making the default deployment more complex.

The completed change must:

1. remove stale Argon2id-shaped Mosquitto placeholders from operational validation paths;
2. permanently reject Cyrillic text in tracked UTF-8 repository files so the English-only repository requirement cannot regress;
3. runtime-test the two implemented optional components that still have no application-level coverage: Netdata and k6;
4. preserve existing default commands, service scope, credentials, named volumes, and image versions.

## Evidence and scope

The original roadmap integrations are already present: Netdata, Eclipse Mosquitto, openHAB, k6, and separate k3s guidance. Existing workflows verify image manifests, the default stack, the IoT stack, and backup/restore. The remaining runtime gap is therefore not another service; it is application-level verification of Netdata and k6.

The current repository also contains two operational Mosquitto placeholders shaped as Argon2id records even though the supported official-image contract is SHA512-PBKDF2 with 220000 iterations. The actual bootstrap and IoT runtime code already use the supported contract. This design makes the specialized IoT policy own the placeholder contract as well.

The one-time translation workflow was intentionally removed after translating the repository. A permanent tracked-file check is required to prevent future Russian or other Cyrillic content from being committed accidentally.

## Architecture

### 1. Mosquitto placeholder contract

`scripts/check_iot_runtime_policy.py` remains the single static owner of Mosquitto password-record rules. It will require all operational placeholder producers to use a value beginning with:

```text
<username>:$7$220000$
```

It will reject `$argon2id$` in:

- `scripts/check.sh`;
- `scripts/check_runtime.sh`;
- `scripts/check_images.py`.

Historical design and plan documents remain unchanged because they accurately record the earlier experiment and correction.

### 2. English-only repository guard

`scripts/check_english_only.py` will:

- obtain the authoritative tracked-file set from `git ls-files -z`;
- read each tracked file as UTF-8;
- skip files that are not valid UTF-8;
- reject code points in the Cyrillic Unicode ranges used by modern and extended Cyrillic text;
- report every violation as `path:line:column` with the offending character's Unicode code point;
- return success only when no tracked UTF-8 file contains Cyrillic text.

`scripts/test_english_only.py` will test the pure scanner against clean text, multiple Cyrillic ranges, exact locations, and invalid UTF-8. `scripts/check.sh` will run both the unit tests and the repository scan.

### 3. Netdata port isolation

The Netdata service uses host networking, so the fixed default listener port would make parallel or local runtime tests fragile. `compose.yaml` will pass:

```yaml
NETDATA_LISTENER_PORT: ${NETDATA_PORT:-19999}
```

`.env.example` will define `NETDATA_PORT=19999`. This preserves current production behavior while allowing the isolated runtime harness to choose a random free port.

### 4. Optional runtime harness

`scripts/check_optional_runtime.sh` will create a private temporary Compose project and never read deployment `.env` or `.secrets/`.

The harness will:

1. copy only committed Compose/configuration inputs into a mode-`0700` temporary directory;
2. generate non-secret Compose placeholders, including a PBKDF2-shaped Mosquitto record;
3. choose a random host port and set `NETDATA_PORT` in the disposable `.env`;
4. render the `netdata` and `test` profiles;
5. start only Netdata and poll `/api/v1/info`;
6. query a real `system.cpu` data point through `/api/v1/data`;
7. start only whoami and run the committed k6 smoke script through the `test` profile;
8. prove no monitoring, tools, or IoT application services were started;
9. always remove only the uniquely named project, containers, networks, and volumes;
10. print bounded Compose state and logs on failure.

Netdata and k6 are checked sequentially in one workflow because both are small optional-profile runtime gaps and share the same disposable Compose inputs. This avoids two nearly identical workflows without coupling them to the default or IoT runtime checks.

### 5. CI and documentation

A separate `.github/workflows/optional-runtime.yml` workflow will run on relevant pull requests, pushes to `main`, a weekly schedule, and manual dispatch. It will have read-only repository permissions, a bounded timeout, and a three-day log artifact only on failure.

The README will document six verification levels and the configurable Netdata port. The fast `make check` path will continue to start no containers.

## Compatibility

- Existing `make up`, `make full`, `make netdata`, and `make k6` behavior is preserved.
- `NETDATA_PORT` defaults to `19999`, matching the previous hard-coded listener.
- No image references or persistent volume names change.
- No production credentials are created, rotated, or read by runtime CI.
- The maintained platforms remain Linux `amd64` and `arm64`.

## Error handling

The optional runtime check fails with a specific diagnostic when:

- Docker, Compose, curl, Python, or OpenSSL is unavailable;
- no random host port can be allocated;
- Compose rendering fails;
- Netdata does not become reachable in the bounded polling window;
- `/api/v1/info` is not valid JSON;
- no `system.cpu` sample is available in the bounded polling window;
- k6 exits non-zero because an HTTP check or threshold fails;
- an unexpected service is started;
- cleanup cannot be attempted.

Cleanup is trap-based and scoped by a unique Compose project name. It never runs host-wide prune or removal commands.

## Non-goals

This change does not add new homelab services, public TLS, Netdata Cloud enrollment, k6 performance baselines beyond the existing smoke thresholds, MQTT TLS, openHAB setup automation, live database backup, remote backup uploads, digest pinning, or a new validation framework.

## Verification strategy

The final branch must pass:

```bash
./scripts/check.sh
make check-images
make check-runtime
make check-iot-runtime
make check-optional-runtime
make check-backup-runtime
```

GitHub Actions must report success for every workflow triggered by the final pull-request head before squash merge into `main`.
