"""Label each open task issue `ready` when every "Blocked by #N" issue is closed, else `blocked`."""

import json
import re
import subprocess


def gh(*args: str) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


def main() -> None:
    issues = json.loads(gh("issue", "list", "--state", "all", "--limit", "500", "--json", "number,state,body,labels"))
    state = {i["number"]: i["state"] for i in issues}
    for issue in issues:
        if issue["state"] != "OPEN":
            continue
        labels = {lbl["name"] for lbl in issue["labels"]}
        if "task" not in labels:
            continue
        deps = [int(n) for n in re.findall(r"Blocked by #(\d+)", issue["body"] or "")]
        ready = all(state.get(d) == "CLOSED" for d in deps)
        want, drop = ("ready", "blocked") if ready else ("blocked", "ready")
        if want not in labels or drop in labels:
            gh("issue", "edit", str(issue["number"]), "--add-label", want, "--remove-label", drop)
            print(f"#{issue['number']}: {want}")


if __name__ == "__main__":
    main()
