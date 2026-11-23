"""Agent worker: registers with the control plane, claims tasks, runs Claude Code or Codex headless,
and reports the pull request it opened. Standard library only."""

import fcntl
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

VERSION = "0.1.0"
API = os.environ.get("CONTROL_PLANE_URL", "http://control-plane:8000").rstrip("/")
TOKEN = os.environ.get("WORKER_TOKEN", "")
PROVIDER = os.environ.get("WORKER_PROVIDER", "claude")
MODEL = os.environ.get("MODEL", "")
WORKSPACE = Path(os.environ.get("WORKSPACE", "/workspace"))
AGENT_CONFIG = Path(os.environ.get("AGENT_CONFIG_DIR", "/etc/devenv-agent"))
# An empty credential variable would shadow the other auth method in Claude Code, so drop empty ones.
for _name in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "OPENAI_API_KEY", "CODEX_AUTH_JSON"):
    if not os.environ.get(_name):
        os.environ.pop(_name, None)
TASK_TIMEOUT = int(os.environ.get("TASK_TIMEOUT_SECONDS", str(3 * 3600)))
WORKER_ID = f"{PROVIDER}-{socket.gethostname()}"
HERE = Path(__file__).parent


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def call(method: str, path: str, body: dict | None = None, raw: bool = False):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method)
    req.add_header("Authorization", f"Bearer {TOKEN}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=60) as r:
        if r.status == 204:
            return None
        payload = r.read()
        return payload if raw else json.loads(payload or b"null")


def run(cmd: list[str], cwd: Path | None = None, check: bool = True, env: dict | None = None) -> str:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env)
    if check and p.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:3])} failed: {p.stderr.strip()[-2000:]}")
    return p.stdout.strip()


class Reporter:
    """Batches agent output into task events and heartbeats while a task runs."""

    def __init__(self, task_id: int, interval: int):
        self.task_id, self.interval = task_id, interval
        self.buf: list[str] = []
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.cancelled = threading.Event()
        self.status = "starting"
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def line(self, text: str) -> None:
        with self.lock:
            self.buf.append(text.rstrip()[:2000])

    def flush(self) -> None:
        with self.lock:
            chunk, self.buf = "\n".join(self.buf), []
        if chunk:
            try:
                call(
                    "POST",
                    f"/api/workers/{WORKER_ID}/tasks/{self.task_id}/events",
                    {"kind": "log", "message": chunk[-20000:]},
                )
            except Exception as e:  # noqa: BLE001
                log(f"event post failed: {e}")

    def _loop(self) -> None:
        while not self.stop.wait(self.interval):
            self.flush()
            try:
                r = call(
                    "POST",
                    f"/api/workers/{WORKER_ID}/heartbeat",
                    {"state": "busy", "task_id": self.task_id, "message": self.status},
                )
                if r and r.get("continue") is False:
                    self.cancelled.set()
            except Exception as e:  # noqa: BLE001
                log(f"heartbeat failed: {e}")

    def close(self) -> None:
        self.stop.set()
        self.flush()


def apply_agent_config() -> None:
    """Copy rendered MCP/plugin config (from the control plane) into the agent's home directory."""
    src = AGENT_CONFIG / PROVIDER / "home"
    if not src.is_dir():
        return
    home = Path.home()
    for f in src.rglob("*"):
        if f.is_file():
            dest = home / f.relative_to(src)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dest)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "task"


def fetch_attachments(task: dict, dest: Path) -> list[str]:
    names = []
    for a in task.get("attachment_urls", []):
        dest.mkdir(parents=True, exist_ok=True)
        (dest / a["filename"]).write_bytes(call("GET", a["url"], raw=True))
        names.append(a["filename"])
    return names


def prepare_repo(task: dict, workdir: Path) -> tuple[Path, str]:
    repo, base = task["repo"], task["base_branch"]
    token = os.environ.get("GITHUB_TOKEN", "")
    url = f"https://x-access-token:{token}@github.com/{repo}.git" if token else f"https://github.com/{repo}.git"
    dest = workdir / "repo"
    run(["git", "clone", "--quiet", url, str(dest)])
    git = task.get("git", {})
    run(["git", "config", "user.name", git.get("user_name") or "AI Dev Agent"], dest)
    run(["git", "config", "user.email", git.get("user_email") or "agent@devenv.local"], dest)
    branch = task.get("branch") or f"agent/task-{task['id']}-{slug(task['title'])}"
    remote = run(["git", "ls-remote", "--heads", "origin", branch], dest)
    if remote:
        run(["git", "checkout", "-q", "-b", branch, f"origin/{branch}"], dest)
    else:
        run(["git", "checkout", "-q", "-b", branch, f"origin/{base}"], dest)
    return dest, branch


def build_prompt(task: dict, branch: str, attachments: list[str], att_dir: Path) -> str:
    att = ""
    if attachments:
        att = f"- Files attached to this task are in `{att_dir}`: " + ", ".join(f"`{n}`" for n in attachments)
    prev = ""
    if task.get("last_error"):
        prev = f"- A previous attempt did not finish: {task['last_error']}. Continue from the existing branch and fix that."
    if task.get("new_repo"):
        prev += (
            "\n- This repository was just created for this task and holds only a README. Set up the project: a clear"
            " README, a .gitignore, tests, and a GitHub Actions workflow that runs them on pull requests."
        )
    if task.get("pr_url"):
        prev += f"\n- The existing pull request is {task['pr_url']}; push fixes to it rather than opening a new one."
    template = (HERE / ("prompt.md" if task["repo"] else "prompt-norepo.md")).read_text()
    return template.format(
        id=task["id"], title=task["title"], description=task["description"] or "(no further description)",
        repo=task["repo"], branch=branch, base_branch=task["base_branch"], previous_attempt=prev, attachments=att,
    )  # fmt: skip


CODEX_EFFORT = {"low": "low", "medium": "medium", "high": "high", "xhigh": "high", "max": "high"}


def agent_command(prompt: str, model: str | None = None, effort: str = "") -> list[str]:
    """The agent CLI call. `model` None or empty means the model from Settings (MODEL)."""
    model = model or MODEL
    if PROVIDER == "claude":
        cmd = ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose", "--dangerously-skip-permissions"]
        mcp = AGENT_CONFIG / "claude" / "mcp.json"
        if mcp.is_file():
            cmd += ["--mcp-config", str(mcp)]
        return cmd + (["--model", model] if model else []) + (["--effort", effort] if effort else [])
    if PROVIDER == "codex":
        cmd = ["codex", "exec", "--dangerously-bypass-approvals-and-sandbox", "--skip-git-repo-check"]
        if effort in CODEX_EFFORT:
            cmd += ["-c", f"model_reasoning_effort={CODEX_EFFORT[effort]}"]
        return cmd + (["--model", model] if model else []) + [prompt]
    raise SystemExit(f"unknown provider {PROVIDER}")


def describe(line: str) -> str:
    """Turn a Claude stream-json line into a readable log line; pass other output through."""
    try:
        ev = json.loads(line)
    except ValueError:
        return line
    if ev.get("type") == "assistant":
        parts = []
        for block in ev.get("message", {}).get("content", []):
            if block.get("type") == "text":
                parts.append(block["text"])
            elif block.get("type") == "tool_use":
                parts.append(f"→ {block.get('name')} {json.dumps(block.get('input'))[:300]}")
        return "\n".join(parts)
    if ev.get("type") == "result":
        return f"RESULT ({ev.get('subtype')}): {ev.get('result', '')}"
    return ""


MODEL_UNAVAILABLE = re.compile(
    r"model.{0,80}(not found|not available|not supported|unsupported|does not exist|invalid|no access|not allowed)"
    r"|(unknown|invalid|unsupported) model",
    re.IGNORECASE,
)


def run_agent(prompt: str, cwd: Path, rep: Reporter, run_cfg: dict | None = None) -> tuple[int, str]:
    """Run the agent with the task's model; if that model is not available here, run again with Settings' model."""
    run_cfg = run_cfg or {}
    model, effort = run_cfg.get("model") or "", run_cfg.get("effort") or ""
    code, tail = _run_agent(agent_command(prompt, model, effort), cwd, rep, model or MODEL)
    if code > 0 and model and model != MODEL and MODEL_UNAVAILABLE.search(tail):
        rep.line(
            f"{model} is not available to this agent; running again with the Settings model {MODEL or '(default)'}"
        )
        code, tail = _run_agent(agent_command(prompt, MODEL, effort), cwd, rep, MODEL)
    return code, tail


def _run_agent(cmd: list[str], cwd: Path, rep: Reporter, model: str) -> tuple[int, str]:
    rep.status = f"running {PROVIDER}{' ' + model if model else ''}"
    proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    last = []
    deadline = time.time() + TASK_TIMEOUT
    assert proc.stdout
    for raw in proc.stdout:
        text = describe(raw.rstrip("\n"))
        if text:
            rep.line(text)
            last = (last + [text])[-20:]
        if rep.cancelled.is_set() or time.time() > deadline:
            proc.kill()
            break
    code = proc.wait()
    if rep.cancelled.is_set():
        return -1, "task was cancelled or reassigned"
    if time.time() > deadline:
        return -2, f"agent timed out after {TASK_TIMEOUT}s"
    return code, "\n".join(last)[-4000:]


def finish_repo_task(task: dict, repo_dir: Path, branch: str, rep: Reporter) -> dict:
    base = task["base_branch"]
    if run(["git", "status", "--porcelain"], repo_dir):
        rep.line("Agent left uncommitted changes; committing them.")
        run(["git", "add", "-A"], repo_dir)
        run(["git", "commit", "-q", "-m", f"Task #{task['id']}: {task['title']}"], repo_dir)
    ahead = run(["git", "rev-list", "--count", f"origin/{base}..HEAD"], repo_dir)
    if ahead == "0":
        return {"outcome": "failed", "error": "no commits on the task branch"}
    run(["git", "push", "-q", "-u", "origin", branch], repo_dir)
    env = {**os.environ, "GH_TOKEN": os.environ.get("GITHUB_TOKEN", "")}
    out = run(["gh", "pr", "list", "--head", branch, "--state", "open", "--json", "url,number"], repo_dir, env=env)
    prs = json.loads(out or "[]")
    if not prs:
        body = f"Automated change for queue task #{task['id']}.\n\n{task['description']}"
        run(
            ["gh", "pr", "create", "--base", base, "--head", branch, "--title", task["title"], "--body", body],
            repo_dir,
            env=env,
        )
        prs = json.loads(
            run(["gh", "pr", "list", "--head", branch, "--state", "open", "--json", "url,number"], repo_dir, env=env)
        )
    pr = prs[0]
    return {"outcome": "pr", "branch": branch, "pr_url": pr["url"], "pr_number": pr["number"]}


def do_task(task: dict, interval: int) -> None:
    rep = Reporter(task["id"], interval)
    workdir = WORKSPACE / f"task-{task['id']}-{task['attempts']}"
    shutil.rmtree(workdir, ignore_errors=True)
    workdir.mkdir(parents=True)
    result: dict
    auth_before = ""
    try:
        apply_agent_config()
        auth_before = pull_codex_auth()
        att_dir = workdir / "attachments"
        names = fetch_attachments(task, att_dir)
        if task["repo"]:
            rep.status = f"cloning {task['repo']}"
            repo_dir, branch = prepare_repo(task, workdir)
            code, tail = run_agent(build_prompt(task, branch, names, att_dir), repo_dir, rep, task.get("run"))
            if code < 0:
                result = {"outcome": "failed", "error": tail}
            else:
                result = finish_repo_task(task, repo_dir, branch, rep)
                result["summary"] = tail
                if code != 0 and result["outcome"] == "pr":
                    rep.line(f"agent exited with {code} but a PR exists; reporting it")
        else:
            code, tail = run_agent(build_prompt(task, "", names, att_dir), workdir, rep, task.get("run"))
            result = (
                {"outcome": "completed", "summary": tail}
                if code == 0
                else {"outcome": "failed", "error": tail or f"exit {code}"}
            )
    except Exception as e:  # noqa: BLE001
        result = {"outcome": "failed", "error": str(e)[-2000:]}
    finally:
        rep.close()
        push_codex_auth(auth_before)
    log(f"task {task['id']}: {result['outcome']}")
    try:
        call("POST", f"/api/workers/{WORKER_ID}/tasks/{task['id']}/result", result)
    except urllib.error.HTTPError as e:
        log(f"result rejected: {e.code} {e.read()[:300]!r}")
    shutil.rmtree(workdir, ignore_errors=True)


# ChatGPT sign-in for Codex. The pasted auth.json seeds a directory shared by all Codex agents; each task
# copies it in, and copies it back if Codex refreshed the tokens, so every agent keeps a working sign-in.
SHARED_AUTH = Path(os.environ.get("CODEX_SHARED_AUTH_DIR", "/codex-auth"))


def _codex_auth_file() -> Path:
    return Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "auth.json"


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_private(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


class _SharedLock:
    def __enter__(self):
        self.f = open(SHARED_AUTH / ".lock", "a")  # noqa: SIM115
        fcntl.flock(self.f, fcntl.LOCK_EX)

    def __exit__(self, *exc):
        fcntl.flock(self.f, fcntl.LOCK_UN)
        self.f.close()


def _shared_ok() -> bool:
    return SHARED_AUTH.is_dir() and os.access(SHARED_AUTH, os.W_OK)


def seed_codex_auth() -> None:
    """Put the sign-in pasted in Settings into the shared directory when it is a new one."""
    raw = os.environ.get("CODEX_AUTH_JSON", "").encode()
    if not raw:
        return
    if not _shared_ok():
        _write_private(_codex_auth_file(), raw)
        return
    with _SharedLock():
        seed = SHARED_AUTH / "seed.sha256"
        if not (SHARED_AUTH / "auth.json").exists() or not seed.exists() or seed.read_text().strip() != _digest(raw):
            _write_private(SHARED_AUTH / "auth.json", raw)
            seed.write_text(_digest(raw))
            log("ChatGPT sign-in for Codex updated from Settings")


def pull_codex_auth() -> str:
    """Copy the shared sign-in into this agent's Codex home. Returns its digest ("" if none)."""
    if PROVIDER != "codex" or not os.environ.get("CODEX_AUTH_JSON"):
        return ""
    if _shared_ok():
        with _SharedLock():
            shared = SHARED_AUTH / "auth.json"
            if shared.exists():
                _write_private(_codex_auth_file(), shared.read_bytes())
    local = _codex_auth_file()
    return _digest(local.read_bytes()) if local.exists() else ""


def push_codex_auth(before: str) -> None:
    """If Codex refreshed the tokens during the task, share the new ones with the other agents."""
    local = _codex_auth_file()
    if not before or not local.exists() or not _shared_ok():
        return
    data = local.read_bytes()
    if _digest(data) == before:
        return
    try:
        json.loads(data)
    except ValueError:
        return
    with _SharedLock():
        _write_private(SHARED_AUTH / "auth.json", data)
    log("shared refreshed ChatGPT sign-in")


def login() -> None:
    if PROVIDER != "codex":
        return
    if os.environ.get("CODEX_AUTH_JSON"):
        # ChatGPT subscription sign-in wins over an API key when both are set.
        os.environ.pop("OPENAI_API_KEY", None)
        seed_codex_auth()
    elif os.environ.get("OPENAI_API_KEY"):
        subprocess.run(
            ["codex", "login", "--with-api-key"], input=os.environ["OPENAI_API_KEY"], text=True, capture_output=True
        )


def main() -> None:
    if not TOKEN:
        sys.exit("WORKER_TOKEN is not set")
    login()
    while True:
        try:
            reg = call(
                "POST",
                "/api/workers/register",
                {
                    "id": WORKER_ID,
                    "provider": PROVIDER,
                    "model": MODEL,
                    "hostname": socket.gethostname(),
                    "version": VERSION,
                },
            )
            break
        except Exception as e:  # noqa: BLE001
            log(f"waiting for control plane: {e}")
            time.sleep(5)
    interval = reg["heartbeat_seconds"]
    config_version = reg.get("config_version", 0)
    log(f"registered as {WORKER_ID} ({MODEL or 'default model'})")
    idle_since = 0.0
    while True:
        try:
            task = call("POST", f"/api/workers/{WORKER_ID}/claim")
        except urllib.error.HTTPError as e:
            if e.code == 404:  # control plane forgot us (e.g. DB reset): register again
                return main()
            log(f"claim failed: {e}")
            task = None
        except Exception as e:  # noqa: BLE001
            log(f"claim failed: {e}")
            task = None
        if task:
            log(f"claimed task {task['id']}: {task['title']}")
            do_task(task, interval)
            continue
        if time.time() - idle_since > interval:
            try:
                hb = call(
                    "POST", f"/api/workers/{WORKER_ID}/heartbeat", {"state": "idle", "message": "waiting for work"}
                )
                if hb and hb.get("config_version", config_version) != config_version:
                    # MCP/plugin config changed: exit so Docker restarts us with a clean agent process.
                    log("agent config changed; restarting")
                    sys.exit(0)
            except Exception as e:  # noqa: BLE001
                log(f"heartbeat failed: {e}")
            idle_since = time.time()
        time.sleep(5)


if __name__ == "__main__":
    main()
