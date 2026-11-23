# Reaching the VM from your computer

The VM is headless. Everything happens in a browser on your computer.

| What | Address |
|------|---------|
| Settings UI, dashboard, queue | `http://devenv.local/` (mDNS) or `http://<vm-ip>/` |
| API docs (OpenAPI) | `http://devenv.local/docs` |
| MCP endpoint for controllers | `http://devenv.local/mcp` (or your Cloudflare hostname) |
| SSH | `ssh dev@devenv.local` |

The VM console and the SSH banner print the current IP addresses and, until you change it,
the one-time admin password.

## Hostname and mDNS

The image runs `avahi-daemon`, so the VM announces itself as **devenv.local**.

* **Windows 10/11** resolves `.local` names natively (mDNS is on by default). If it does not
  resolve, use the IP shown on the VM console, or add it to `C:\Windows\System32\drivers\etc\hosts`.
* **macOS** resolves `.local` names natively.
* **Linux** needs `nss-mdns` (installed by default on most desktops).

To change the hostname, boot with a seed ISO: `images/cloud-init/make-seed.sh -n myname`.

## Hyper-V networking

`deploy/windows/New-DevEnvVM.ps1` attaches the VM to the **Default Switch**, which gives it a
NAT address reachable from the host (and mDNS works across it). For access from other machines
on your LAN, create an external switch and pass `-SwitchName "<your external switch>"`.

## Ports

| Port | Service |
|------|---------|
| 22 | SSH |
| 80 | Caddy: web UI, `/api`, `/mcp`, `/docs` |

Nothing else listens on the VM's network interface. Remote access goes through the Cloudflare
Tunnel (outbound only), protected by Cloudflare Access; see [tunnels.md](tunnels.md).
