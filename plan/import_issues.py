#!/usr/bin/env python3
"""Create milestones, labels and one issue per task from tasks.tsv, then link dependencies.
Usage: python3 import_issues.py owner/repo tasks.tsv   (needs an authenticated `gh`)."""

import json
import subprocess
import sys

repo, path = sys.argv[1], sys.argv[2]


def gh(*args, data=None):
    cmd = ["gh", "api", *args]
    out = subprocess.run(cmd, input=json.dumps(data) if data else None, capture_output=True, text=True)
    if out.returncode:
        raise SystemExit(f"{cmd}: {out.stderr}")
    return json.loads(out.stdout) if out.stdout.strip() else None


milestones, tasks, cur = {}, [], None
for line in open(path):
    parts = line.rstrip("\n").split("\t")
    if parts[0].startswith("M"):
        cur = parts[0]
        milestones[cur] = f"{parts[0]} {parts[1]}"
    else:
        deps = [d for d in (parts[2].split(",") if len(parts) > 2 and parts[2] else [])]
        tasks.append({"id": parts[0], "title": parts[1], "deps": deps, "m": cur})

existing = {m["title"]: m["number"] for m in gh(f"repos/{repo}/milestones?state=all&per_page=100")}
for _key, title in milestones.items():
    if title not in existing:
        existing[title] = gh(f"repos/{repo}/milestones", "--method", "POST", "--input", "-", data={"title": title})[
            "number"
        ]

for name, color in [("ready", "0e8a16"), ("blocked", "b60205"), ("task", "1d76db")]:
    subprocess.run(["gh", "label", "create", name, "--color", color, "--force", "-R", repo], capture_output=True)

DOD = (
    "\n\n## Definition of done\n- [ ] Committed on a branch\n- [ ] Pushed\n- [ ] PR merged to main\n"
    "- [ ] Deployed, if relevant\n"
)
issues = {}
open_issues = gh(f"repos/{repo}/issues?state=all&per_page=100")
for i in open_issues:
    tid = i["title"].split(" ", 1)[0]
    issues[tid] = i
for t in tasks:
    if t["id"] in issues:
        continue
    body = f"Task {t['id']} from plan/tasks.tsv." + DOD
    labels = ["task", "blocked" if t["deps"] else "ready"]
    issues[t["id"]] = gh(
        f"repos/{repo}/issues",
        "--method",
        "POST",
        "--input",
        "-",
        data={
            "title": f"{t['id']} {t['title']}",
            "body": body,
            "labels": labels,
            "milestone": existing[milestones[t["m"]]],
        },
    )
    print("created", t["id"], issues[t["id"]]["number"])

for t in tasks:
    if not t["deps"]:
        continue
    iss = issues[t["id"]]
    lines = "\n".join(f"Blocked by #{issues[d]['number']} ({d})" for d in t["deps"])
    body = f"Task {t['id']} from plan/tasks.tsv.\n\n## Dependencies\n{lines}" + DOD
    gh(f"repos/{repo}/issues/{iss['number']}", "--method", "PATCH", "--input", "-", data={"body": body})
    for d in t["deps"]:
        subprocess.run(
            [
                "gh",
                "api",
                f"repos/{repo}/issues/{iss['number']}/dependencies/blocked_by",
                "--method",
                "POST",
                "-F",
                f"issue_id={issues[d]['id']}",
            ],
            capture_output=True,
        )
print("done", len(issues))
