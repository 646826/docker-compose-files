# HTTPS on a trusted LAN

The maintained default stack uses HTTP and `*.localhost`. This recipe adds HTTPS without publishing the homelab to the Internet. It is an opt-in deployment override and does not store certificates or private keys in Git.

## Choose a private domain

Use a name you control locally, for example:

```text
home.example.internal
```

Configure local DNS or hosts entries so each service name resolves to the Docker host:

```text
traefik.home.example.internal
home.home.example.internal
uptime.home.example.internal
auth.home.example.internal
logs.home.example.internal
```

Set `.env`:

```dotenv
BASE_DOMAIN=home.example.internal
HTTPS_HOST_IP=0.0.0.0
HTTPS_PORT=443
```

Authelia requires a normal dotted domain and HTTPS. Do not use `localhost` for SSO cookies.

## Create a private certificate authority

Create the CA on a protected administration workstation, not in the repository. One OpenSSL example is:

```bash
mkdir -p "$HOME/homelab-ca"
chmod 700 "$HOME/homelab-ca"
cd "$HOME/homelab-ca"

openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:4096 -out root-ca.key
chmod 600 root-ca.key
openssl req -x509 -new -sha256 -days 3650 \
  -key root-ca.key \
  -subj '/CN=Homelab Local Root CA' \
  -out root-ca.crt
```

Keep `root-ca.key` offline and encrypted. Import only `root-ca.crt` into client trust stores.

## Issue a wildcard certificate

Create an OpenSSL configuration containing the exact private domain:

```ini
[req]
distinguished_name = dn
req_extensions = req_ext
prompt = no

[dn]
CN = *.home.example.internal

[req_ext]
subjectAltName = @alt_names

[alt_names]
DNS.1 = *.home.example.internal
DNS.2 = home.example.internal
```

Issue the certificate:

```bash
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out privkey.pem
chmod 600 privkey.pem
openssl req -new -key privkey.pem -config certificate.cnf -out request.csr
openssl x509 -req -sha256 -days 397 \
  -in request.csr \
  -CA root-ca.crt \
  -CAkey root-ca.key \
  -CAcreateserial \
  -extensions req_ext \
  -extfile certificate.cnf \
  -out fullchain.pem
```

Store runtime certificate material outside Git, for example:

```text
/opt/homelab/tls/certs/fullchain.pem
/opt/homelab/tls/certs/privkey.pem
/opt/homelab/tls/dynamic/tls.yaml
```

The directory should be readable only by the administrator and Docker daemon. Copy `examples/tls/traefik-dynamic.template.yaml` to the untracked `dynamic/tls.yaml` path and replace the placeholder hostname.

## Validate the override

Set absolute paths:

```bash
export TLS_CERT_DIR=/opt/homelab/tls/certs
export TLS_DYNAMIC_DIR=/opt/homelab/tls/dynamic
```

Render the merged configuration before starting anything:

```bash
docker compose \
  --env-file .env \
  -f compose.yaml \
  -f examples/tls/compose.tls.yaml \
  --profile uptime \
  --profile dashboard \
  --profile auth \
  --profile logs \
  config --quiet
```

Start the selected services only after validation:

```bash
docker compose \
  --env-file .env \
  -f compose.yaml \
  -f examples/tls/compose.tls.yaml \
  --profile uptime \
  --profile dashboard \
  --profile auth \
  --profile logs \
  up -d
```

## Client trust

Install `root-ca.crt` as a trusted root on each client that should access the homelab. Never distribute `root-ca.key`. Verify the certificate chain and hostname from a client before enabling Authelia:

```bash
curl --cacert root-ca.crt https://auth.home.example.internal/api/health
```

## Renewal

Private certificates do not renew automatically in this recipe. Document the expiration date, create an Uptime Kuma certificate-expiration monitor, and renew before the remaining validity falls below 30 days. Keep the old certificate until the replacement has been validated.

## Rollback

1. Set `AUTH_MIDDLEWARE=local-auth@docker`.
2. Recreate the protected services.
3. Stop the TLS override deployment.
4. Start the ordinary stack without `examples/tls/compose.tls.yaml`.
5. Confirm HTTP and Basic Auth work before removing certificate files.

A LAN certificate backup must include the current certificate and private key in encrypted operator storage. It must not include the offline CA private key unless the backup location has equivalent protection.
