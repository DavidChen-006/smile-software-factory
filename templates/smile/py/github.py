"""What `gh` tells the review lane about pull requests and issues (contract section 9).

The lane reaches GitHub only through `gh`, and only through this file, so one place decides what a
factory pull request is: one whose body carries a `Bead: <id>` line. Everything here is a read of
the world; the writes (issues, comments, labels, merges) stay with the command that decides them.
"""

import json

from worktree import tool

BEAD_LINE = "Bead:"
PR_FIELDS = "number,headRefOid,body,labels"


def json_out(cwd: str, argv: list) -> object:
    """The JSON `gh <argv>` prints; a non-zero exit is one line and exit 1 through main."""
    return json.loads(tool(cwd, ["gh", *argv]) or "null")


def bead_of(body: str) -> str:
    """The id on the last `Bead: <id>` line of a pull request body; empty when there is none."""
    ids = [line.strip()[len(BEAD_LINE):].strip()
           for line in (body or "").splitlines() if line.strip().startswith(BEAD_LINE)]
    return ids[-1] if ids else ""


def labels(pr: dict) -> list:
    return [entry.get("name", "") for entry in pr.get("labels") or []]


def factory_prs(cwd: str, state: str, fields: str = PR_FIELDS) -> list:
    """The factory pull requests in that state, ascending by number, each with `bead` and `labels`.

    A pull request with no `Bead:` line belongs to a human, not to the factory, and is dropped here.
    """
    listed = json_out(cwd, ["pr", "list", "--state", state, "--json", fields, "--limit", "200"])
    if not isinstance(listed, list) or any(not isinstance(pr, dict) for pr in listed):
        raise RuntimeError(f"gh pr list --state {state} did not print a list of pull requests")
    prs = [{**pr, "bead": bead_of(pr.get("body") or ""), "labels": labels(pr)} for pr in listed]
    return sorted((pr for pr in prs if pr["bead"]), key=lambda pr: pr["number"])


def review_issues(cwd: str, number: int, fields: str = "number,body") -> list:
    """The open issues labeled `review` whose body carries the line `PR: #<number>`, ascending."""
    listed = json_out(cwd, ["issue", "list", "--label", "review", "--state", "open",
                            "--json", fields, "--limit", "200"])
    if not isinstance(listed, list) or any(not isinstance(i, dict) for i in listed):
        raise RuntimeError("gh issue list did not print a list of issues")
    marker = f"PR: #{number}"
    mine = [i for i in listed if marker in [line.strip() for line in (i.get("body") or "").splitlines()]]
    return sorted(mine, key=lambda issue: issue["number"])
