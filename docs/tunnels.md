# Tunnels: letting Claude (Baz) and ChatGPT see the agents

## Option 1: quick tunnel (no account, no domain)

Settings, Remote access: turn on the tunnel, choose **Quick tunnel**, press Apply. The VM runs
`cloudflared tunnel --url http://caddy:80` and gets a random `https://<words>.trycloudflare.com` address,
shown on the Controllers page (and as the base of the MCP URL). The address changes whenever the tunnel
restarts, and there is no Cloudflare Access in front of it: the admin password protects the UI and the
per-controller tokens protect `/mcp` and the API. Good for trying things out and for friends without a domain.

## Option 2: your own domain (named tunnel with Cloudflare Access)

The VM makes an **outbound** Cloudflare Tunnel connection, so nothing on your network is opened.
Terraform in [`infra/terraform/cloudflare`](../infra/terraform/cloudflare) creates:

| Resource | Purpose |
|----------|---------|
| Tunnel + config | Routes `https://<hostname>` to the stack's Caddy (`http://caddy:80`) |
| DNS CNAME | `<hostname>` → `<tunnel-id>.cfargotunnel.com`, proxied |
| Access application | People listed in *allowed emails* log in with an email one-time PIN |
| Access service tokens | `baz-claude`, `chatgpt`: headers `CF-Access-Client-Id` / `CF-Access-Client-Secret` for automated clients |
| Access bypass on `/mcp` | Cloud assistants that cannot send Access headers reach the MCP server, which requires its own controller token |

State is kept in a Cloudflare R2 bucket (`devenv-claude-tfstate`), with S3 credentials derived from
the API token, so you need no other storage account.

## API token permissions
Create a token at dash.cloudflare.com → My Profile → API Tokens → *Create Custom Token*:
* Account: **Cloudflare Tunnel: Edit**, **Access: Apps and Policies: Edit**, **Access: Service Tokens: Edit**, **Workers R2 Storage: Edit**
* Zone (your domain): **DNS: Edit**, **Zone: Read**

## Option A: from the settings UI (recommended)
Settings → Cloudflare: paste the API token, account ID, zone (e.g. `example.com`), hostname
(e.g. `devenv.example.com`) and allowed emails, tick *Run the Cloudflare Tunnel*, Save, then Apply.
Apply runs Terraform, stores the tunnel token, and starts `cloudflared`. Changing the hostname or
emails and applying again updates the tunnel and Access policies.

## Option B: from GitHub Actions
Add the secret `CLOUDFLARE_API_TOKEN` and variables `CF_ACCOUNT_ID`, `CF_ZONE`, `CF_HOSTNAME`
(and optionally `CF_ACCESS_EMAILS`, a JSON list) to the repository, then run the **tunnel**
workflow with `apply`. The VM reads the same state when you Apply.

## Manual token
Untick *Create the tunnel … with Terraform* and paste a tunnel token from the Cloudflare dashboard.
