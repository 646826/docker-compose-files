# Public HTTPS with ACME DNS-01

Public HTTPS is deployment-specific and is never enabled by the maintained default stack. This recipe assumes you own a public DNS zone and understand that exposing a homelab service changes its threat model.

Prefer private access through a VPN when public reachability is unnecessary. Do not expose Portainer, Netdata, AdGuard setup, MQTT plaintext port 1883, or Docker management interfaces directly to the Internet.

## Prerequisites

- a public domain you control;
- a DNS provider supported by the selected ACME client or Traefik DNS challenge;
- least-privilege DNS API credentials restricted to the required zone;
- inbound TCP 443 routing to the Docker host, or another deliberate reverse-proxy topology;
- host firewall rules;
- a tested backup and rollback plan;
- time synchronization.

Set `.env` to the real domain and preserve Basic Auth during staging:

```dotenv
BASE_DOMAIN=home.example.com
HTTPS_HOST_IP=0.0.0.0
HTTPS_PORT=443
AUTH_MIDDLEWARE=local-auth@docker
```

## Keep provider credentials outside Git

Create provider-specific files under the mode-`0700` `.secrets` directory. Use the provider's least-privilege token mechanism. Do not place token values directly in Compose command arguments, labels, issue comments, screenshots, or CI logs.

The exact environment variable names depend on the provider and must come from current Traefik/lego documentation. A generic local file might look like:

```dotenv
DNS_PROVIDER_API_TOKEN=replace-locally
```

Do not commit this file. Prefer provider variables that support `_FILE` when available. Otherwise pass the entire private env file to the Traefik container through a deployment-specific override and protect it with mode `0600`.

## Use ACME staging first

Before requesting production certificates, configure the ACME staging directory and verify:

- DNS record creation and cleanup;
- wildcard and apex names;
- certificate storage permissions;
- renewal scheduling;
- Traefik routing on port 443;
- no credential values in logs;
- rollback to ordinary HTTP/Basic Auth.

Staging avoids production rate-limit damage while configuration is being debugged.

## Certificate storage

Traefik's ACME storage file contains account data and private keys. Store it outside Git with mode `0600`, for example:

```text
/opt/homelab/acme/acme.json
```

Back it up in encrypted operator storage. Do not place it in the ordinary named-volume snapshot unless the confidentiality model explicitly covers certificate private keys.

## DNS-01 override outline

Create a local, untracked Compose override that extends Traefik with:

```yaml
services:
  traefik:
    command:
      # Repeat the maintained Traefik command and add:
      - --entrypoints.websecure.address=:443
      - --certificatesresolvers.public.acme.email=replace@example.com
      - --certificatesresolvers.public.acme.storage=/var/lib/traefik-acme/acme.json
      - --certificatesresolvers.public.acme.dnschallenge=true
      - --certificatesresolvers.public.acme.dnschallenge.provider=replace-with-provider
      - --certificatesresolvers.public.acme.caserver=https://acme-staging-v02.api.letsencrypt.org/directory
    ports:
      - "${HTTPS_HOST_IP:-0.0.0.0}:${HTTPS_PORT:-443}:443"
    volumes:
      - /opt/homelab/acme:/var/lib/traefik-acme
    env_file:
      - ./.secrets/dns-provider.env
```

Do not copy this outline verbatim without replacing the provider and checking current upstream documentation. The complete Traefik command must retain the restricted Docker socket proxy and `exposedByDefault=false` behavior.

Add TLS router labels only through a local override, for example:

```yaml
services:
  homepage:
    labels:
      traefik.http.routers.homepage.entrypoints: websecure
      traefik.http.routers.homepage.tls: "true"
      traefik.http.routers.homepage.tls.certresolver: public
```

## Production promotion

After staging succeeds repeatedly:

1. back up the staging configuration and ACME file;
2. replace only the staging CA URL with the production endpoint;
3. request one certificate set;
4. verify chain, names, expiry, renewal metadata, and all protected routes;
5. configure Uptime Kuma certificate-expiration monitors;
6. keep Basic Auth until Authelia login and ForwardAuth are separately validated.

## Public exposure checklist

- only TCP 443 is forwarded from the router;
- HTTP either remains LAN-only or performs an intentional HTTPS redirect;
- Portainer and Netdata are not publicly routed;
- AdGuard setup port and DNS recursion are not open to the Internet;
- MQTT port 1883 is not publicly exposed;
- Dozzle actions and shell remain disabled;
- Homepage has no Docker socket;
- Authelia uses HTTPS, a normal dotted domain, and protected recovery secrets;
- firewall and DNS changes are documented;
- verified local and encrypted remote backups are current;
- restore and authentication rollback have been tested.

## Rollback

1. Set `AUTH_MIDDLEWARE=local-auth@docker`.
2. Remove public DNS records or router forwarding.
3. recreate protected services on the trusted network;
4. stop the public TLS override;
5. verify local HTTP/HTTPS access and Basic Auth;
6. preserve ACME storage and logs for investigation.

Revoking a certificate does not revoke leaked DNS API credentials. Rotate provider credentials independently whenever exposure is suspected.
