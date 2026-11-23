# /// script
# requires-python = ">=3.12"
# dependencies = ["anthropic>=0.70", "openai>=2.0", "httpx>=0.27"]
# ///
"""End-to-end controller test: ask Claude or ChatGPT to plan a small idea through the devenv MCP server,
then check through the REST API that a dependency-linked plan was queued.

  uv run scripts/controller_e2e.py claude  --url https://devenv.example.com --token dv_...
  uv run scripts/controller_e2e.py chatgpt --url https://devenv.example.com --token dv_...

Needs ANTHROPIC_API_KEY or OPENAI_API_KEY. The URL must be reachable from the provider's cloud
(the Cloudflare tunnel hostname), because the provider calls the MCP server, not this script."""

import argparse
import sys
import time

import httpx

IDEA = (
    "Idea for repo {repo}: add a tiny CLI `hello` that prints a greeting, with a unit test and a README section. "
    "Plan it as 3 small tasks with correct dependencies (code first, then test and docs). "
    "Use get_planning_guide, then create_tasks. Prefix every task title with '[e2e {stamp}]'. Reply with the task ids."
)


def run_claude(url: str, token: str, prompt: str) -> str:
    import anthropic

    client = anthropic.Anthropic()
    resp = client.beta.messages.create(
        model="claude-opus-5-5",
        max_tokens=16000,
        betas=["mcp-client-2025-11-20"],
        mcp_servers=[{"type": "url", "url": f"{url}/mcp", "name": "devenv", "authorization_token": token}],
        tools=[{"type": "mcp_toolset", "mcp_server_name": "devenv"}],
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in resp.content if b.type == "text")


def run_chatgpt(url: str, token: str, prompt: str) -> str:
    import openai

    client = openai.OpenAI()
    resp = client.responses.create(
        model="gpt-5",
        tools=[
            {
                "type": "mcp",
                "server_label": "devenv",
                "server_url": f"{url}/mcp",
                "headers": {"Authorization": f"Bearer {token}"},
                "require_approval": "never",
            }
        ],
        input=prompt,
    )
    return resp.output_text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("controller", choices=["claude", "chatgpt"])
    ap.add_argument("--url", required=True, help="Public base URL of the environment")
    ap.add_argument("--token", required=True, help="Controller token for this controller")
    ap.add_argument("--repo", default="gibovski/devenv-e2e-claude")
    ap.add_argument("--cancel", action="store_true", help="Cancel the created tasks afterwards")
    args = ap.parse_args()
    url = args.url.rstrip("/")
    stamp = time.strftime("%Y%m%d%H%M%S")
    prompt = IDEA.format(repo=args.repo, stamp=stamp)
    text = (run_claude if args.controller == "claude" else run_chatgpt)(url, args.token, prompt)
    print(f"--- {args.controller} said:\n{text}\n---")

    h = {"Authorization": f"Bearer {args.token}"}
    tasks = [t for t in httpx.get(f"{url}/api/tasks", headers=h, timeout=30).json() if f"[e2e {stamp}]" in t["title"]]
    ok = len(tasks) >= 2 and any(t["deps"] for t in tasks)
    for t in tasks:
        print(f"#{t['id']} {t['state']:<8} deps={[d['id'] for d in t['deps']]} {t['title']}")
        if args.cancel:
            httpx.patch(f"{url}/api/tasks/{t['id']}", headers=h, json={"action": "cancel"}, timeout=30)
    print("PASS" if ok else "FAIL: expected at least 2 tasks with dependencies")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
