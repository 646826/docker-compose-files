# Migration from the legacy layout

The refreshed stack intentionally does not import or delete old data automatically. Read this document before starting the new containers on a host that already ran the legacy repository.

## 1. Back up first

For an already migrated installation that uses the current named volumes, use the verified cold backup and side-by-side restore procedure in [`docs/BACKUP.md`](BACKUP.md). The commands below remain specific to the legacy `docker-data/v1` bind-mounted layout.

Stop the old containers without deleting the bind-mounted directories:

```bash
docker stop traefik influxdb telegraf grafana portainer 2>/dev/null || true
docker rm traefik influxdb telegraf grafana portainer 2>/dev/null || true
```

Create a filesystem-level backup of the old local data:

```bash
tar -czf "../docker-data-backup-$(date +%Y%m%d-%H%M%S).tgz" docker-data/v1
```

Verify that the archive exists and is readable before continuing.

## 2. Choose fresh start or data migration

A fresh start is safest because the credentials previously committed to the public repository are compromised. Run:

```bash
make init
make up
```

Continue below only when retaining dashboards, metrics, or Portainer state is necessary.

## 3. Initialize local files

```bash
make init
```

This creates `.env` and new values under `.secrets/`. It does not alter the legacy directories.

## 4. Copy bind-mounted data into named volumes

Run only the commands for directories that exist on your host.

### Grafana

```bash
docker volume create homelab_grafana_data
docker run --rm \
  -v "$PWD/docker-data/v1/grafana/data:/from:ro" \
  -v homelab_grafana_data:/to \
  alpine:3.22 sh -euc 'cp -a /from/. /to/; chown -R 472:0 /to'
```

### InfluxDB data and configuration

```bash
docker volume create homelab_influxdb_data
docker volume create homelab_influxdb_config

docker run --rm \
  -v "$PWD/docker-data/v1/influxdb/data:/from:ro" \
  -v homelab_influxdb_data:/to \
  alpine:3.22 sh -euc 'cp -a /from/. /to/'

docker run --rm \
  -v "$PWD/docker-data/v1/influxdb/config:/from:ro" \
  -v homelab_influxdb_config:/to \
  alpine:3.22 sh -euc 'cp -a /from/. /to/'
```

### Portainer

```bash
docker volume create homelab_portainer_data
docker run --rm \
  -v "$PWD/docker-data/v1/portainer/data:/from:ro" \
  -v homelab_portainer_data:/to \
  alpine:3.22 sh -euc 'cp -a /from/. /to/'
```

The old Telegraf configuration is not copied. The new maintained configuration replaces the generated multi-thousand-line sample.

## 5. Reconcile credentials retained inside application data

Initialization environment variables are applied only to a new InfluxDB database. If an initialized InfluxDB volume was copied, place a currently valid existing admin token in `.secrets/influxdb_token` before starting Grafana and Telegraf. Then create a new token in InfluxDB, replace the local file, and restart the clients:

```bash
docker compose --profile monitoring restart telegraf grafana
```

Do not keep using any value that appeared in public Git history.

A copied Grafana database retains its existing users. After Grafana starts, reset the admin password to the newly generated local value through the Grafana UI or CLI. A copied Portainer database also retains its existing authentication settings; rotate them in Portainer after login.

## 6. Start in stages

Start and inspect the metrics backend first:

```bash
docker compose --profile monitoring up -d influxdb telegraf grafana
docker compose --profile monitoring ps
docker compose --profile monitoring logs --tail=100 influxdb telegraf grafana
```

Then start the default stack:

```bash
make up
```

Confirm the following before deleting the old backup:

- InfluxDB accepts writes from Telegraf;
- Grafana datasource health is successful and the Host Overview dashboard has data;
- Portainer shows the expected endpoint and stacks;
- `make down && make up` preserves all state.

## 7. Rollback

Stop the new project without deleting volumes:

```bash
make down
```

Restore the original repository revision and bind-mounted directories from the backup. The migration commands above copy data; they do not modify the source directories.
