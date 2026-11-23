# Tunnels: letting Claude (Baz) and ChatGPT see the agents

## Option 1: quick tunnel (no account, no domain)

Settings, Remote access: turn on the tunnel, choose **Quick tunnel**, press Apply. The VM runs
`cloudflared tunnel --url http://caddy:80` and gets a random `https://<words>.trycloudflare.com` address,
shown on the Controllers page (and as the base of the MCP URL). The address changes whenever the tunnel
restarts, and there is no Cloudflare Access in front of it: the admin password protects the UI and the
per-controller tokens protect `/mcp` and the API. Good for trying things out and for friends without a domain.

### Fixed address for the quick tunnel (free workers.dev, no domain)

Tick **Give it a fixed address on workers.dev** under the quick tunnel. The VM then deploys a small
Cloudflare Worker named after the *Worker name* setting (default `devenv-` plus 6 random characters, made on
first use, so every install gets its own) to your free workers.dev subdomain:

    https://<worker-name>.<your-subdomain>.workers.dev

The Worker forwards every request (including the MCP endpoint) to the current `trycloudflare.com` address.
The VM checks that address every 30 seconds and redeploys the Worker when it changes, so the workers.dev
address never changes. The Controllers page shows it, and controllers should use it.

What you need (free Cloudflare account, no domain, no card):

1. Sign up at dash.cloudflare.com. Open **Workers & Pages** once and accept the workers.dev subdomain it
   offers (for example `gibbo`). That is the `<your-subdomain>` part.
2. My Profile → API Tokens → *Create Token* → *Create Custom Token*. Permissions: **Account → Workers
   Scripts → Edit**. Account resources: your account. Create it and copy it.
3. Copy your **Account ID** (Workers & Pages overview, right-hand side, or the URL after `dash.cloudflare.com/`).
4. In Settings → Remote access: Quick tunnel, tick the workers.dev option, paste the token and Account ID,
   optionally choose a Worker name, **Save settings**, then **Apply**. The address appears under the option
   within a minute.

The token lives only in the VM's encrypted secret store (never in the image). The app's own admin login and
controller tokens still protect everything behind the address.

**Optional: Cloudflare Access in front of it.** Cloudflare's free Zero Trust plan (up to 50 users) can put a
login in front of a workers.dev address: Workers & Pages → your Worker → Settings → Domains & Routes →
workers.dev → *Enable Cloudflare Access*, then edit the policy to allow your email. Cloud assistants such as
Claude and ChatGPT can't get through Access, so leave it off if they need to reach `/mcp`. The raw
`trycloudflare.com` address is not behind Access either way.

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
