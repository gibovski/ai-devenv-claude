# Getting started on Windows

This guide takes you from a Windows PC to a running AI dev environment with agents working on your
repositories. It assumes an Intel or AMD PC with Windows 10/11 Pro, Enterprise or Education (Hyper-V).

## 1. Enable Hyper-V (once)

In an elevated PowerShell (right-click, *Run as administrator*):

```powershell
Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V -All
```

Reboot when asked. Windows Home has no Hyper-V: use the VirtualBox fallback in step 2b.

## 2. Create the VM

Download the scripts (or clone the repo) and run them from an elevated PowerShell:

```powershell
iwr https://github.com/gibovski/ai-devenv-claude/archive/refs/heads/main.zip -OutFile devenv.zip
Expand-Archive devenv.zip -DestinationPath . ; cd ai-devenv-claude-main\deploy\windows
Set-ExecutionPolicy -Scope Process Bypass
.\New-DevEnvVM.ps1
```

The script downloads the newest daily image from
[Releases](https://github.com/gibovski/ai-devenv-claude/releases), checks its SHA-256, creates a
Generation 2 VM (Secure Boot on, 4 vCPUs, 8 GB RAM, 100 GB disk by default) on the *Default Switch*,
starts it, and prints:

```
VM 'devenv' is running.
  Settings UI:  http://172.x.x.x/   (or http://devenv.local/)
  Admin password (one-time): ...
```

Options: `-VMName`, `-MemoryGB`, `-CPUs`, `-DiskSizeGB`, `-SwitchName "External"` (to reach the VM from
other machines on your LAN), `-Version v2026.11.23` (a specific release), `-Replace` (rebuild an existing VM;
its disk, and everything on it, is deleted).

### 2b. VirtualBox fallback

```powershell
.\Import-DevEnvVirtualBox.ps1
```

The UI is then at http://localhost:8080/ and SSH at `ssh -p 2222 dev@localhost`. The one-time password is
shown on the VM console (VirtualBox Manager, *Show*).

## 3. First login

Open the printed URL in your browser and log in as `admin` with the one-time password. You are asked to set
your own password. If you lose the printed password, it is also on the VM console
(`vmconnect localhost devenv`) until you change it.

## 4. Settings

On the **Settings** page:

| Section | What to enter |
|---|---|
| GitHub | A personal access token with `repo` and `workflow` scopes, the owner and a default repository. Keep *auto merge* on so the definition of done (merged to main) can be reached without you. |
| Claude | Your Claude Pro/Max subscription token (run `claude setup-token` on a computer with Claude Code and paste the result), or an Anthropic API key. Then the number of Claude agents and the model (Opus 5.5 is the default). All agents share your subscription's usage limits. |
| OpenAI | An API key, the number of Codex agents and the model. |
| Cloudflare | API token, account id, zone, hostname and the emails allowed through Cloudflare Access. See [tunnels.md](tunnels.md). |

Use **Check** next to each credential, then **Apply**. Apply shows the change it will make, then starts or
stops agent containers to match.

### Sharing the VM with friends

The published images contain no credentials and no per-machine keys. Every VM creates its own encryption
key, admin password and SSH host keys on first boot, and every account (GitHub, Claude, OpenAI, Cloudflare)
is entered by whoever runs it, here in Settings. Each image build checks this and fails if it finds any
credential, key or saved state in the image. Credentials are stored encrypted on the VM's disk, so share the
download link or a fresh image, not a VM you have already set up.

## 5. Give the agents work

- **Queue** page: add tasks by hand, import a YAML/JSON/TSV plan, set dependencies, attach files.
- **Graph** page: see the dependency graph; ready tasks are picked up first.
- **Controllers** page: create a token for Claude (Baz) or ChatGPT, which then plan and queue work through
  the MCP server or the OpenAPI actions. See [controllers/README.md](controllers/README.md).

A task is **done** only when its pull request is merged into the base branch and, if the repository has a
deploy workflow, that workflow succeeded on the merge commit.

## 6. Reach it from anywhere

Turn on the tunnel in Settings (Remote access) and press Apply. With **Quick tunnel** you need no
Cloudflare account or domain: the Controllers page shows a random `https://…trycloudflare.com` address that
changes when the tunnel restarts. For an address that never changes, tick **Give it a fixed address on
workers.dev**: with a free Cloudflare account it becomes `https://<worker-name>.<your-subdomain>.workers.dev`
(steps in [tunnels.md](tunnels.md#fixed-address-for-the-quick-tunnel-free-workersdev-no-domain)). With your own domain the UI is at `https://<hostname>/` behind Cloudflare
Access. Controllers use `<address>/mcp/t/<token>`.

## Updating

Images are rebuilt every day with the latest Ubuntu patches and agent versions. Your settings, secrets and
queue live on the VM disk in `/var/lib/devenv`, so to move to a new image keep a copy of that folder
(`ssh dev@<ip> sudo tar -C /var/lib -czf - devenv > devenv-state.tgz`), run `.\New-DevEnvVM.ps1 -Replace`,
and restore it the same way before logging in. In-place updates also work: `ssh dev@<ip>` then
`sudo apt upgrade` and `sudo /opt/devenv/bin/stack-up`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Unable to allocate ... RAM` (0x800705AA) when the VM starts | Not enough free memory. The script uses dynamic memory when less than MemoryGB + 1 GB is free, but other apps may have taken more since. Close some apps and run `Start-VM devenv`, or recreate it smaller: `.\New-DevEnvVM.ps1 -Replace -MemoryGB 6`. |
| No IP printed | The Default Switch can take a minute; run `Get-VMNetworkAdapter devenv` later, or open the console. |
| `devenv.local` does not resolve | Use the IP. mDNS needs Bonjour/mDNS support on Windows (built into Windows 10 1803+ for most browsers). |
| Secure Boot error at boot | `Set-VMFirmware devenv -SecureBootTemplate MicrosoftUEFICertificateAuthority` |
| Agents stay *offline* | Settings, Check each credential, then Apply again; `ssh dev@<ip>` and `docker compose -p devenv logs` in `/opt/devenv`. |
