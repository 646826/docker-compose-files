# AdGuard Home: guarded DNS deployment

AdGuard Home is an opt-in network-infrastructure module. It is never started by `make up`, `make full`, or `make community` because an incorrect DNS deployment can affect every device on the network.

## Before starting

Use a stable host IP and keep the current router/DHCP DNS settings unchanged until AdGuard Home is configured and tested.

Review `.env`:

```dotenv
DNS_HOST_IP=0.0.0.0
DNS_PORT=53
ADGUARD_SETUP_HOST_IP=127.0.0.1
ADGUARD_SETUP_PORT=3000
```

Binding DNS to `0.0.0.0` exposes TCP and UDP port 53 on all host interfaces. Restrict `DNS_HOST_IP` to the LAN address when the host has multiple or untrusted interfaces.

## Read-only preflight

```bash
make dns-preflight
```

The preflight checks the configured address and TCP/UDP listener, inspects existing listeners, and gives specific guidance when `systemd-resolved` owns port 53. It does not disable services, edit `/etc/resolv.conf`, change Docker, modify firewall rules, or touch the router.

If port 53 is occupied, identify the existing resolver and choose a deliberate architecture. Do not blindly disable `systemd-resolved`; Docker and the host may depend on it.

## Start the module

```bash
make dns
```

The setup interface is loopback-only by default:

```text
http://127.0.0.1:3000
```

Use SSH port forwarding when the Docker host is remote:

```bash
ssh -L 3000:127.0.0.1:3000 user@docker-host
```

Complete the AdGuard Home setup wizard, select trustworthy upstream resolvers, and test direct queries against the host before changing router or DHCP settings.

## Network rollout

1. Configure one test device to use the AdGuard host as DNS.
2. Verify normal browsing, local hostnames, software updates, and IoT devices.
3. Review the query log and allowlist false positives.
4. Change DHCP/router DNS only after the test device is stable.
5. Keep the previous DNS server documented for rollback.

## Rollback

1. Restore the former DNS servers in DHCP/router configuration.
2. Renew client DHCP leases or restart affected clients.
3. Stop the module with the normal project command:

```bash
docker compose --profile dns stop adguard-home
```

4. Preserve `adguard_work` and `adguard_config` for investigation or restore them from a verified backup.

## Limitations

DNS filtering blocks domains, not individual paths or page elements. It cannot reliably remove advertising served from the same domain as the desired content, including many video-platform ads. Browser content blockers may still be useful.

The default module exposes ordinary DNS on port 53. DNS-over-HTTPS, DNS-over-TLS, and DNS-over-QUIC require certificates and deployment-specific network decisions. Configure them only after following the relevant TLS guidance and testing rollback.

## Backups

The community backup inventory includes:

```text
adguard_work
adguard_config
```

Stop the module before a cold snapshot. After restore, verify the server address, upstream resolvers, rewrites, client rules, and DHCP settings before routing network clients to it.
