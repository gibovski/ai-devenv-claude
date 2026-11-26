# ai-devenv-claude

A fully code-defined AI development environment.

* **VM images** for `amd64` and `arm64` (Ubuntu 24.04 LTS), built by GitHub Actions with Packer whenever their inputs change on main (plus a monthly patch rebuild), published to GitHub Releases as VHDX (Hyper-V), qcow2 (KVM/Proxmox/UTM), OVA (VirtualBox/VMware) and raw.
* **Headless first boot**: the VM starts a Docker stack and prints the URL of its browser **Settings UI** on the console.
* **Settings UI** for GitHub, OpenAI, Anthropic and Cloudflare credentials, the number of Claude and OpenAI coding agents, and the model for each (with a token-usage tier from very high to low). Applying settings re-renders and re-deploys the stack.
* **Agent dashboard** showing the availability and status of every coding agent.
* **Work queue** with dependencies (a task stays queued until every dependency is done), file uploads, a list view and a dependency graph.
* **Definition of done**: committed, pushed, merged to `main`, deployed if relevant — checked by the control plane through the GitHub API.
* **Controller interface**: an OpenAPI + remote MCP server, so Claude or ChatGPT can break ideas into the smallest practical tasks and queue them.
* **Tunnels as code**: Cloudflare Tunnel + Access via Terraform so a remote controller can see the agents.
* **Plugins/MCP as code**: `mcp/mcp.yaml` is rendered into each agent's config; changes are picked up automatically.

## Repository layout

| Path | What lives there |
|------|------------------|
| `images/packer` | Packer templates and provisioning scripts for the VM images |
| `images/cloud-init` | cloud-init user-data and seed ISO generator |
| `stack` | Docker Compose stack that runs inside the VM (Caddy, control plane, web UI, workers, cloudflared) |
| `services/control-plane` | FastAPI control plane: settings, secrets, apply engine, agents, queue, MCP server |
| `services/web` | React web UI: settings, dashboard, queue, graph, plugins |
| `workers` | Agent worker images (base, Claude Code, Codex) |
| `mcp` | MCP server and plugin definitions (`mcp.yaml`) |
| `infra/terraform` | Terraform for Cloudflare tunnels/Access and GitHub repo settings |
| `deploy/windows` | Hyper-V and VirtualBox scripts for Windows hosts |
| `docs` | ADRs and user guides |
| `plan` | The milestone/task plan that seeded the issues |

See [docs/adr/001-architecture.md](docs/adr/001-architecture.md) for the architecture and
[docs/windows-guide.md](docs/windows-guide.md) for getting started on Windows.

## Licence

MIT, see [LICENSE](LICENSE).
