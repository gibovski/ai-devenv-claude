"""Minimal GitHub REST client used by the done checker."""

import base64

import httpx
import yaml


class GitHub:
    def __init__(self, token: str, api: str = "https://api.github.com", client: httpx.Client | None = None):
        self.client = client or httpx.Client(
            base_url=api,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=20,
        )

    def get(self, path: str, **params) -> dict | list | None:
        r = self.client.get(path, params=params or None)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    def pull(self, repo: str, number: int) -> dict | None:
        return self.get(f"/repos/{repo}/pulls/{number}")

    def checks_state(self, repo: str, sha: str) -> tuple[str, list[str]]:
        """Return (pending|success|failure|none, failing check names) from check runs and commit statuses."""
        runs = (self.get(f"/repos/{repo}/commits/{sha}/check-runs", per_page=100) or {}).get("check_runs", [])
        statuses = (self.get(f"/repos/{repo}/commits/{sha}/status") or {}).get("statuses", [])
        if not runs and not statuses:
            return "none", []
        failing = [
            r["name"]
            for r in runs
            if r["status"] == "completed" and r["conclusion"] not in ("success", "neutral", "skipped")
        ]
        failing += [s["context"] for s in statuses if s["state"] in ("failure", "error")]
        if failing:
            return "failure", failing
        pending = any(r["status"] != "completed" for r in runs) or any(s["state"] == "pending" for s in statuses)
        return ("pending" if pending else "success"), []

    def merge(self, repo: str, number: int, sha: str, method: str = "squash") -> tuple[bool, str]:
        r = self.client.put(f"/repos/{repo}/pulls/{number}/merge", json={"merge_method": method, "sha": sha})
        if r.status_code == 200:
            return True, r.json().get("sha", "")
        return False, r.json().get("message", r.text)

    def repo_config(self, repo: str, ref: str) -> dict:
        """Read .devenv.yaml from the target repo, if any."""
        f = self.get(f"/repos/{repo}/contents/.devenv.yaml", ref=ref)
        if not f or "content" not in f:
            return {}
        return yaml.safe_load(base64.b64decode(f["content"])) or {}

    def has_file(self, repo: str, path: str, ref: str) -> bool:
        return self.get(f"/repos/{repo}/contents/{path}", ref=ref) is not None

    def workflow_files(self, repo: str, ref: str) -> list[str]:
        items = self.get(f"/repos/{repo}/contents/.github/workflows", ref=ref)
        return sorted(
            i["name"] for i in items or [] if isinstance(i, dict) and i.get("name", "").endswith((".yml", ".yaml"))
        )

    def workflow_runs(self, repo: str, workflow: str, sha: str) -> list[dict]:
        data = self.get(f"/repos/{repo}/actions/workflows/{workflow}/runs", head_sha=sha, per_page=20) or {}
        return data.get("workflow_runs", [])
