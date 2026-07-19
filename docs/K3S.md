# k3s: separate, optional track

k3s is intentionally not a service in `compose.yaml`. It is a Kubernetes distribution with its own container runtime, networking, ingress, storage, service lifecycle, upgrades, and recovery model. Nesting it inside the homelab Compose project would make both systems harder to operate.

## Recommended deployment

Use a separate host or VM for k3s. This avoids shared port, firewall, storage, and resource ownership between Docker Compose and Kubernetes.

For a single-node lab on a dedicated Linux machine, download and inspect the official installer before running it:

```bash
curl -sfL https://get.k3s.io -o install-k3s.sh
less install-k3s.sh
sudo env INSTALL_K3S_CHANNEL=stable sh install-k3s.sh
sudo k3s kubectl get nodes
```

The `stable` channel is the production-oriented default. Keep the downloaded installer and the service configuration under normal host change control.

## Running on the same host

The bundled k3s Traefik normally consumes host ports `80` and `443`, while this Compose project publishes port `80`. They cannot own the same address and port simultaneously.

The least complicated same-host option is to keep the Compose Traefik and disable the k3s-packaged Traefik in the persistent k3s configuration before installation:

```bash
curl -sfL https://get.k3s.io -o install-k3s.sh
less install-k3s.sh

sudo install -d -m 0755 /etc/rancher/k3s
cat <<'EOF' | sudo tee /etc/rancher/k3s/config.yaml >/dev/null
disable:
  - traefik
EOF

sudo env INSTALL_K3S_CHANNEL=stable sh install-k3s.sh
```

Keeping the setting in `/etc/rancher/k3s/config.yaml` makes it survive service restarts and later installer runs. This does not automatically expose Kubernetes workloads through the Compose Traefik. Add an ingress design only after deciding how Docker and Kubernetes networks should communicate. Do not expose the Kubernetes API or dashboard through an unauthenticated HTTP route.

Other same-host concerns:

- reserve CPU, memory, and disk space for both runtimes;
- ensure Docker and k3s pod/service CIDRs do not overlap local networks;
- back up `/var/lib/rancher/k3s` and the server token according to k3s documentation;
- retain the exact install configuration when upgrading;
- test host reboot ordering and firewall rules.

## Verification

```bash
sudo systemctl status k3s --no-pager
sudo k3s kubectl get nodes -o wide
sudo k3s kubectl get pods -A
sudo ss -lntup
```

Check that the Compose HTTP/MQTT ports and Kubernetes services do not conflict.

## Uninstall warning

The installer creates `/usr/local/bin/k3s-uninstall.sh`. Running it removes the local cluster data and configuration. Treat it as destructive and take a verified backup before use.
