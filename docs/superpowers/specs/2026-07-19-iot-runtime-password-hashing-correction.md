# IoT Runtime Password Hashing Correction

## Status

This note supersedes every Argon2id password-file reference in the original IoT runtime design and implementation plan.

## Verified upstream limitation

The published official Eclipse Mosquitto `2.1.2` images do not provide a working Argon2 password-hashing path. The first real IoT runtime workflow proved this twice:

1. the implicit `mosquitto_passwd -U` path produced the compiled default rather than an Argon2 record;
2. explicit `mosquitto_passwd -H argon2id` failed with `Unable to hash password`.

Upstream build configuration explains the behavior: the 2.1 CMake configuration does not enable the `WITH_ARGON2` definition for these official images.

## Implemented replacement

Both normal bootstrap and the isolated IoT runtime harness use the official image and create a new password file with:

```text
mosquitto_passwd -H sha512-pbkdf2 -I 220000 -c
```

The disposable password and its confirmation are supplied through standard input. The password is never placed in a process argument, environment variable, repository file, CI log, or workflow artifact.

The generated password-file record must begin with:

```text
<username>:$7$220000$
```

This keeps the implementation on an upstream-supported code path while using an explicit high work factor. Focused policy and behavioral tests reject Argon2 requests, legacy conversion mode, batch-mode password arguments, a lower or implicit iteration count, and an unexpected record prefix.

## Scope impact

No runtime behavior outside password-file generation changes. Mosquitto authentication, anonymous denial, retained publish/subscribe, SQLite persistence after restart, openHAB readiness, loopback exposure, and scoped cleanup remain exactly as designed.
