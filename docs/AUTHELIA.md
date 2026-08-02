# Authelia single sign-on

Authelia is optional. Existing Traefik Basic Auth remains the default middleware and recovery path.

## Requirements

Authelia session cookies require a normal domain with at least one dot and HTTPS. `localhost` is intentionally rejected. Complete either `docs/TLS-LAN.md` or `docs/TLS-PUBLIC.md` before switching application routes to Authelia.

Configure `.env`:

```dotenv
BASE_DOMAIN=home.example.com
AUTHELIA_USERNAME=admin
AUTHELIA_DISPLAY_NAME=Homelab Administrator
AUTHELIA_EMAIL=admin@example.com
AUTH_MIDDLEWARE=local-auth@docker
```

Keep `AUTH_MIDDLEWARE=local-auth@docker` until the portal and ForwardAuth have been tested.

## Initialize

```bash
make init
make auth-init
```

`auth-init` is idempotent. It creates only missing credentials and refuses silent username drift. Generated files are stored under the private `.secrets` directory:

```text
authelia_password
authelia_username
authelia_session_secret
authelia_storage_encryption_key
authelia_jwt_secret
authelia_users.yml
authelia_configuration.yml
```

The plaintext initial password is operator-only and mode `0600`. The users database contains a cost-12 bcrypt record generated through stdin; the password is not passed in Docker process arguments. Configuration and users files are mode `0644` only because they are inside the mode-`0700` parent and must be bind-mounted into the container.

Read the initial password:

```bash
cat .secrets/authelia_password
```

## Validate and start

```bash
make auth-check
make auth
```

`auth-check` uses the pinned Authelia image to validate the generated configuration with the same file-backed secrets used at runtime.

The portal is expected at:

```text
https://auth.<BASE_DOMAIN>
```

Log in while the protected services still use Basic Auth. Review the filesystem notification at the Authelia data volume when testing identity-validation flows.

## Enable ForwardAuth

After the portal, certificate chain, session cookie, and login have been verified, change:

```dotenv
AUTH_MIDDLEWARE=authelia@docker
```

Then recreate the protected opt-in services:

```bash
make community
```

Uptime Kuma, Homepage, and Dozzle use the selected middleware. Existing core applications retain their established behavior unless their labels are deliberately changed in a local override.

## TOTP

The maintained configuration starts with one-factor authentication so initial recovery is practical. Enroll a TOTP device through the portal, back up recovery information, then change selected access-control rules to `two_factor` in a deployment-specific configuration.

## Rollback

1. Set `AUTH_MIDDLEWARE=local-auth@docker` in `.env`.
2. Recreate protected services with `make community`.
3. Confirm Basic Auth works before stopping Authelia.
4. Preserve `authelia_data` and all Authelia secret files.

Do not regenerate `authelia_storage_encryption_key`; changing it makes encrypted database values unreadable. Do not regenerate the session secret during an incident unless invalidating all sessions is intentional.

## Backup

The community backup inventory includes `authelia_data`. Current `.env` and `.secrets` remain separate from Docker-volume snapshots and must be stored in encrypted operator storage. A successful database restore without the original storage encryption key and users database is not a complete recovery.
