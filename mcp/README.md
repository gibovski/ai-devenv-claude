# MCP servers and plugins as code

[`mcp.yaml`](mcp.yaml) declares which MCP servers and plugins each agent type gets. The image copies
it to `/opt/devenv/mcp/mcp.yaml`; the control plane watches that file and on every change:

1. validates it (schema errors show on the **Plugins** page and nothing is rendered),
2. renders `/var/lib/devenv/agent-config/claude/mcp.json` and `.../claude/home/.claude/settings.json`,
   and `/var/lib/devenv/agent-config/codex/home/.codex/config.toml`,
3. restarts idle agents so they load the new config; busy agents pick it up before their next task.

## Schema
```yaml
version: 1
servers:
  <name>:
    type: stdio | http
    command: npx            # stdio
    args: ["-y", "pkg@1.2.3"]
    env: {KEY: "${VAR}"}    # optional
    url: https://...        # http
    bearer_token_env: VAR   # http: send "Authorization: Bearer $VAR"
    agents: [claude, codex] # which agent types get it (default: both)
    enabled: true           # default true
plugins:
  claude:
    marketplaces: {<name>: {github: owner/repo}}   # or {git: url}
    enabled: [plugin@marketplace]
```
