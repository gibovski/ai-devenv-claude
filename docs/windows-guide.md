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
| GitHub | A personal access token with `repo` and `workflow` scopes, and the owner (your GitHub user name). A default repository is optional. Keep *auto merge* on so the definition of done (merged to main) can be reached without you. Then choose which repositories agents may use (below). |
| Claude | Your Claude Pro/Max subscription token (run `claude setup-token` on a computer with Claude Code and paste the result), or an Anthropic API key. Then the number of Claude agents and the model (Opus 5.5 is the default). All agents share your subscription's usage limits. |
| Codex (OpenAI) | Your ChatGPT subscription sign-in (see below), or an OpenAI API key. Then the number of Codex agents and the model. |
| Cloudflare | API token, account id, zone, hostname and the emails allowed through Cloudflare Access. See [tunnels.md](tunnels.md). |

Use **Test connection** next to each credential, then **Apply**. Apply shows the change it will make, then starts or
stops agent containers to match.

### Which repositories the agents work on

Agents are not tied to one repository. Every task names where its change goes:

- an existing repository, as `my-app` (under the owner you set) or `someone/their-app`;
- `new:my-new-app` for a new project. The repository is created when an agent starts the task: private
  (untick *Make new repositories private* for public ones), with a README, under the owner. If you set a
  *suffix*, for example `-ai`, it becomes `my-new-app-ai`;
- nothing, which uses the default repository if you set one (otherwise the task is research with no code).

When you give Claude (Baz) or ChatGPT an idea, they look at the list of your repositories with their
descriptions and pick the right one for each task, or plan a new repository. Good descriptions on your
repositories help them choose. In **Settings → GitHub → Repositories agents may use**:

1. **Blocked repositories**: names agents must never touch, comma-separated, for example
   `ai-devenv, private-*`. Blocked always wins.
2. **Allowed repositories**: leave empty to allow all of yours, or list the only ones agents may use, for
   example `infra-*, tofu-*, my-app`.
3. **Agents may create new repositories**: on by default. Turn it off to keep agents to existing ones.
4. **Save settings**. No Apply is needed; the queue checks these rules when tasks are added and again when
   an agent starts one.

Your token can create repositories when it is a *classic* token with the `repo` scope. A *fine-grained*
token needs **All repositories** plus *Administration: Read and write* (and *Contents*, *Pull requests*,
*Workflows: Read and write*).

### Which model runs each task

The model you choose for Claude and Codex agents in Settings is the default. When Claude (Baz) or ChatGPT
plans work, it also rates each task's **complexity** and gives a one-line reason, and the agent that picks
the task up uses the matching model:

| Complexity | Typical task | Claude agents | Codex agents | Effort |
|---|---|---|---|---|
| Trivial | typo, wording, a config value | Haiku 5.5 | GPT-5 nano | low |
| Small | one file or function with a clear spec | Sonnet 5.5 | GPT-5 mini | medium |
| Medium | several files, a new endpoint or component | Sonnet 5.5 | GPT-5 Codex | high |
| Large | cross-cutting change, infrastructure, new project | Opus 5.5 | GPT-5 Codex | high |
| Hard | architecture, security, hard bugs | Opus 5.5 | GPT-5 Codex | xhigh |

Small models use much less of your subscription's limits, so routine work leaves room for the big tasks.
The **Queue** shows each task's rating and model (hover for the reason), and the **Graph** shows it when you
hover a task. To change it, open the task, click **Change** next to *Model*, pick a complexity, a specific
model (for example Fable 5.2 for one difficult task) or an effort, and **Save**. It applies the next time
an agent starts the task. If a chosen model isn't available to an agent (for example on your plan), the
agent runs the task again with the model from Settings. The table lives in one place,
`services/control-plane/devenv/catalogue/models.yaml`, together with the model list and usage tiers.

### Using your ChatGPT subscription for Codex (no API key)

Codex agents can sign in with your ChatGPT Plus, Pro or Business plan instead of a paid API key. You sign
in once on your PC and paste the result into Settings:

1. Install Node.js (one time). Open **PowerShell** and run:
   `winget install OpenJS.NodeJS.LTS`
   then close PowerShell and open a new one.
2. Install the Codex CLI: `npm install -g @openai/codex`
3. Sign in: `codex login`. A browser opens. Choose **Sign in with ChatGPT** and log in.
   When it says you are signed in, go back to PowerShell.
4. Open the file it saved: `notepad $env:USERPROFILE\.codex\auth.json`.
   Press **Ctrl+A**, then **Ctrl+C**.
5. In the dev environment: **Settings → Codex (OpenAI) → ChatGPT sign-in for Codex**, click the box,
   press **Ctrl+V**, then **Test connection**. It should say *ChatGPT sign-in for you@example.com (plus plan)*.
6. Set the number of Codex agents (start with 1), **Save settings**, then **Apply**.

The agents keep the sign-in fresh by themselves and share it, so you only do this again if you sign out of
ChatGPT everywhere or the test says it stopped working. All Codex agents count against your plan's usage
limits. Treat `auth.json` like a password: it is stored encrypted on the VM, never in the image, and you
can delete the copy on your PC afterwards (`codex logout` signs that copy out).

No Node.js on your PC? Do it on the VM instead: `ssh dev@<vm-ip>`, then
`mkdir -p ~/codex-login && sudo docker run --rm -it --entrypoint codex -v ~/codex-login:/home/agent/.codex ghcr.io/gibovski/ai-devenv-claude/worker-codex:latest login --device-auth`,
open the link it shows on your PC, enter the code, and finally `cat ~/codex-login/auth.json` and copy
the output into Settings (then `rm -r ~/codex-login`).

### Sharing the VM with friends

The published images contain no credentials and no per-machine keys. Every VM creates its own encryption
key, admin password and SSH host keys on first boot, and every account (GitHub, Claude, OpenAI, Cloudflare)
is entered by whoever runs it, here in Settings. Each image build checks this and fails if it finds any
credential, key or saved state in the image. Credentials are stored encrypted on the VM's disk, so share the
download link or a fresh image, not a VM you have already set up.

## 5. Give the agents work

- **Queue** page: add tasks by hand, import a YAML/JSON/TSV plan, set dependencies, attach files, and rate a
  task's complexity (or pick its model).
- **Graph** page: see the dependency graph; ready tasks are picked up first.
- **Controllers** page: create a token for Claude (Baz) or ChatGPT, which then plan and queue work through
  the MCP server or the OpenAPI actions. See [controllers/README.md](controllers/README.md).

A task is **done** only when its pull request is merged into the base branch and, if the repository has a
deploy workflow, that workflow succeeded on the merge commit.

## 6. Reach it from anywhere

In Settings (Remote access) choose **Quick tunnel** or **My own domain** instead of *Off*, **Save settings**, then Apply. Apply always uses the saved settings; the Settings page warns you about unsaved changes. With **Quick tunnel** you need no
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
| OpenHands | Optional. Tick *Also run OpenHands* in Settings and Apply, then open `http://<vm-ip>:3000/` (your network only, not through the tunnel). It needs an Anthropic API key; it is a separate chat-style agent and doesn't take work from the queue. |
| Agents stay *offline* | Settings, Check each credential, then Apply again; `ssh dev@<ip>` and `docker compose -p devenv logs` in `/opt/devenv`. |
