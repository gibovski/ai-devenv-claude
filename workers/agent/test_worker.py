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


def test_codex_auth_is_seeded_shared_and_refreshed(tmp_path, monkeypatch):
    shared, home = tmp_path / "shared", tmp_path / "home"
    shared.mkdir()
    monkeypatch.setattr(w, "SHARED_AUTH", shared)
    monkeypatch.setattr(w, "PROVIDER", "codex")
    monkeypatch.setenv("CODEX_HOME", str(home))
    pasted = '{"tokens":{"refresh_token":"r1"}}'
    monkeypatch.setenv("CODEX_AUTH_JSON", pasted)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")

    w.login()
    assert "OPENAI_API_KEY" not in os.environ  # the subscription wins
    assert (shared / "auth.json").read_text() == pasted
    assert oct((shared / "auth.json").stat().st_mode & 0o777) == "0o600"

    before = w.pull_codex_auth()
    assert (home / "auth.json").read_text() == pasted
    (home / "auth.json").write_text('{"tokens":{"refresh_token":"r2"}}')  # Codex refreshed it
    w.push_codex_auth(before)
    assert "r2" in (shared / "auth.json").read_text()

    w.seed_codex_auth()  # same pasted value on restart: keep the refreshed tokens
    assert "r2" in (shared / "auth.json").read_text()
    monkeypatch.setenv("CODEX_AUTH_JSON", '{"tokens":{"refresh_token":"r3"}}')
    w.seed_codex_auth()  # a newly pasted sign-in replaces it
    assert "r3" in (shared / "auth.json").read_text()


def test_task_model_and_effort():
    w.PROVIDER, w.MODEL = "claude", "claude-opus-5-5"
    cmd = w.agent_command("x", "claude-haiku-5-5", "low")
    assert cmd[cmd.index("--model") + 1] == "claude-haiku-5-5" and cmd[cmd.index("--effort") + 1] == "low"
    assert "--effort" not in w.agent_command("x") and "claude-opus-5-5" in w.agent_command("x", "")
    w.PROVIDER, w.MODEL = "codex", "gpt-5-codex"
    cmd = w.agent_command("x", "gpt-5-mini", "xhigh")
    assert "model_reasoning_effort=high" in cmd and cmd[cmd.index("--model") + 1] == "gpt-5-mini" and cmd[-1] == "x"


def test_unavailable_model_falls_back_to_settings(monkeypatch, tmp_path):
    w.PROVIDER, w.MODEL = "claude", "claude-opus-5-5"
    calls = []

    def fake(cmd, cwd, rep, model):
        calls.append(model)
        return (1, "Error: model claude-fable-5-2 is not available on your plan") if len(calls) == 1 else (0, "ok")

    monkeypatch.setattr(w, "_run_agent", fake)

    class Rep:
        def line(self, text):
            pass

    assert w.run_agent("p", tmp_path, Rep(), {"model": "claude-fable-5-2"}) == (0, "ok")
    assert calls == ["claude-fable-5-2", "claude-opus-5-5"]
    calls.clear()
    monkeypatch.setattr(w, "_run_agent", lambda *a: calls.append(a[3]) or (1, "tests failed"))
    assert w.run_agent("p", tmp_path, Rep(), {"model": "claude-haiku-5-5"})[0] == 1 and len(calls) == 1
