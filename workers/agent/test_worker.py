import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
os.environ.setdefault("WORKER_TOKEN", "t")
import devenv_worker as w  # noqa: E402


def test_prompt_contains_definition_of_done():
    task = {
        "id": 7,
        "title": "Add login",
        "description": "Use {braces} safely",
        "repo": "me/app",
        "base_branch": "main",
        "last_error": "",
        "pr_url": "",
    }
    p = w.build_prompt(task, "agent/task-7-add-login", ["spec.pdf"], Path("/workspace/x/attachments"))
    assert "agent/task-7-add-login" in p and "merged into `main`" in p and "spec.pdf" in p and "{braces}" in p


def test_prompt_mentions_previous_attempt():
    task = {
        "id": 7,
        "title": "t",
        "description": "",
        "repo": "me/app",
        "base_branch": "main",
        "last_error": "checks failed",
        "pr_url": "https://x/pr/3",
    }
    p = w.build_prompt(task, "b", [], Path("/a"))
    assert "checks failed" in p and "https://x/pr/3" in p


def test_describe_stream_json():
    line = json.dumps(
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": "hi"},
                    {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}},
                ]
            },
        }
    )
    assert w.describe(line).startswith("hi\n→ Bash")
    assert w.describe("plain text") == "plain text"


def test_agent_commands():
    w.PROVIDER, w.MODEL = "claude", "claude-opus-5-5"
    assert w.agent_command("do it")[:3] == ["claude", "-p", "do it"] and "claude-opus-5-5" in w.agent_command("x")
    w.PROVIDER, w.MODEL = "codex", "gpt-5-codex"
    cmd = w.agent_command("do it")
    assert cmd[:2] == ["codex", "exec"] and cmd[-1] == "do it"


def test_slug():
    assert w.slug("Fix the Login Page!") == "fix-the-login-page"
