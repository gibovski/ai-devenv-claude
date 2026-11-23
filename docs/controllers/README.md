# Controllers: Claude (Baz) and ChatGPT

Either assistant can be the "controlling system": you give it project ideas, it breaks them into the
smallest practical tasks and queues them for the agents. Both use the same interfaces:

* **MCP server** at `https://<your tunnel hostname>/mcp` (streamable HTTP). Tools: `get_planning_guide`,
  `list_repos`, `get_repo_readme`, `create_tasks`, `list_tasks`, `get_task`, `get_status`, `update_task`,
  `upload_file`. `list_repos` shows the repositories agents may work on, so the controller can put each task
  in the right one, or plan a new repository (`repo: "new:<name>"`) for a new project.
* **REST API** described by [openapi.json](openapi.json) (also served at `/openapi.json`, docs at `/docs`).
* **Planning guide**: [planning-prompt.md](planning-prompt.md), also returned by `get_planning_guide`.

## 1. Create a token per controller
Open the UI → **Controllers** → create `claude` and `chatgpt`. Copy the token and URLs (shown once).
Revoking a token cuts that controller off without affecting the other.

## 2. Make the environment reachable
Cloud-hosted assistants connect from the internet, so enable the Cloudflare Tunnel
(see [../tunnels.md](../tunnels.md)). The `/mcp` path is allowed through Cloudflare Access because
the controller token protects it; everything else needs an Access login or service token.

## 3. Connect Claude (Baz)
* **claude.ai** (Projects, chat): Settings → Connectors → *Add custom connector* → URL
  `https://<host>/mcp/t/<token>`. Enable it in the conversation's tools menu.
* **Claude Code**: `claude mcp add --transport http devenv https://<host>/mcp --header "Authorization: Bearer <token>"`
* **Claude API**: MCP connector (`mcp_servers` with `authorization_token`), as in `scripts/controller_e2e.py`.

## 4. Connect ChatGPT
* **ChatGPT** (developer mode): Settings → Connectors → *Create* → MCP server URL
  `https://<host>/mcp/t/<token>`, authentication *No authentication* (the token is in the URL).
* **Custom GPT actions**: import `https://<host>/openapi.json`, authentication *API key → Bearer*.
* **OpenAI API**: Responses API `mcp` tool with an `Authorization` header, as in `scripts/controller_e2e.py`.

## 5. End-to-end test
```bash
uv run scripts/controller_e2e.py claude  --url https://<host> --token <claude token>  --cancel
uv run scripts/controller_e2e.py chatgpt --url https://<host> --token <chatgpt token> --cancel
```
Each run asks the assistant to plan a three-task idea and checks that the tasks were queued with
dependencies.
