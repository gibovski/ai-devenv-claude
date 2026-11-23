# ADR-001: Architecture

* Status: accepted
* Date: 2026-11-23

## Context

We need a reproducible, code-defined AI development environment that runs as a VM on a
developer's machine (first target: Windows + Hyper-V on amd64), is rebuilt daily for both
`amd64` and `arm64`, and lets Claude or ChatGPT queue work for a pool of coding agents.
OpenAI is building a parallel version, so this project lives only in new `-claude` repos.

## Decisions

### Images
* **Base**: Ubuntu 24.04 LTS cloud image, customised with **Packer** (QEMU builder) and
  shell provisioners. Packer runs inside GitHub Actions on the native architecture when a
  native runner is available, else under emulation.
* **Formats**: qcow2 is the build output; `qemu-img` converts it to VHDX (Hyper-V Gen2),
  OVA (VirtualBox/VMware) and compressed raw. Files over 2 GB are split for GitHub Releases.
* **Schedule**: daily at 03:17 UTC plus manual dispatch. Tags are `vYYYY.MM.DD`. The last 7
  releases are kept.
* **First boot**: cloud-init (NoCloud seed, or the baked default) creates the `dev` user,
  hostname `devenv`, and a systemd unit starts the Docker Compose stack. The console and SSH
  banner print the settings URL and a one-time admin password.

### Runtime stack (Docker Compose inside the VM)
| Service | Tech | Purpose |
|---------|------|---------|
| `caddy` | Caddy 2 | Single entry point on :80/:443, serves the web UI and proxies `/api` and `/mcp` |
| `control-plane` | Python 3.12, FastAPI, SQLite | Settings, encrypted secrets, apply engine, agent registry, queue, scheduler, done checks, OpenAPI, MCP |
| `web` | React + Vite (static) | Settings, agent dashboard, queue list, dependency graph, task detail, plugins |
| `worker-claude-N` | Claude Code CLI, headless | Coding agents using the Anthropic API |
| `worker-codex-N` | OpenAI Codex CLI, headless | Coding agents using the OpenAI API |
| `cloudflared` | Cloudflare Tunnel | Optional; exposes the UI/API/MCP to remote controllers behind Cloudflare Access |
| `openhands` | OpenHands | Optional compose profile |

* The **apply engine** turns saved settings into `compose.override.yaml` and runs
  `docker compose up -d --remove-orphans` via the Docker socket. Secrets are written to a
  root-only env file, never returned to the browser.
* **Workers** speak a small HTTP protocol to the control plane: register, heartbeat, claim,
  report. The scheduler leases a task to a worker; an expired lease re-queues the task.
* **Queue**: a task is `ready` only when every dependency is `done`. Cycles are rejected.
  Uploaded files are copied into the worker's workspace when the task is claimed.
* **Definition of done**: the agent must create a branch, commit, push and open a PR; the
  control plane marks the task `done` only when the GitHub API shows the PR merged into
  `main` and, if the repo defines a deploy hook, the deploy succeeded.

### Controllers
* Claude ("Baz") and ChatGPT talk to the same **OpenAPI** and a **remote MCP server**
  (`/mcp`, streamable HTTP) with per-controller bearer tokens. A shared planning prompt
  tells the controller to break ideas into the smallest practical tasks with dependencies.

### Tunnels and infrastructure
* **Terraform** (Cloudflare provider) creates the tunnel, DNS records and Access
  application/service tokens. The tunnel token is pasted into the settings UI (or provided
  by Terraform output) and run by the `cloudflared` service.
* GitHub repository settings (branch protection) are also Terraform.

### Plugins and MCP
* `mcp/mcp.yaml` declares MCP servers and plugins per agent type. The control plane renders
  it into Claude Code (`.mcp.json`, settings) and Codex (`config.toml`) config, watches the
  file, and restarts idle workers on change.

## Consequences
* Everything is reproducible from the repo; no hand-built state outside the settings DB.
* The control plane needs the Docker socket, so it is the trust boundary of the VM.
* SQLite keeps the stack simple; it is adequate for tens of agents and thousands of tasks.
