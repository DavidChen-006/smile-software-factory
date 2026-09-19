"""smile review <n>: one reviewer's pass over one pull request (contract section 9).

The reviewer is the signed-in `claude` in print mode, run as a subprocess with the rendered prompt on
stdin and a detached worktree pinned at the pull request head as its working directory. It decides
nothing: it answers a verdict and findings, and this file turns that answer into GitHub issues, a
merge, or a label, and into events. Nothing is cached between calls, so a re-review at a new head
starts from the world as it is.

Parsing the review is pure (`parse`); everything that touches GitHub, bd or the pane lives below it.
"""

import os
import re
import shutil
import subprocess

import config
import events
import gate
import github
import run
import worktree
from mux import Usage
from worktree import tool

NUMBER = re.compile(r"[1-9][0-9]*")
VERDICT = re.compile(r"^Verdict: (APPROVE|REQUEST CHANGES)$")
FINDING = re.compile(r"^- \[(?:Critical|Important)\] (.+)$")
PR_FIELDS = "number,title,headRefOid,headRefName,baseRefName,body,labels"
MAX_DIFF = 200000  # bytes of patch a reviewer can hold; past that it reads the stat and the spec
TITLE_CUT = 80
DASHES = "-" * 60


# ---------------------------------------------------------------- the review text
def parse(text: str) -> tuple:
    """(verdict, findings) from a review: the first verdict line, and the blocking lines after it.

    Findings are (line, text) pairs: the issue body quotes the line, its title carries the text.
    ("", []) means no verdict, which includes a REQUEST CHANGES that names nothing blocking: a
    verdict the lane cannot act on is a review that did not happen.
    """
    lines = text.splitlines()
    for i, line in enumerate(lines):
        verdict = VERDICT.match(line)
        if not verdict:
            continue
        found = [(m.group(0), m.group(1)) for m in map(FINDING.match, lines[i + 1:]) if m]
        if verdict.group(1) == "REQUEST CHANGES" and not found:
            return "", []
        return verdict.group(1), found
    return "", []


def issue_text(issues: list) -> str:
    """The open findings on this pull request as the reviewer reads them; `none` when there are none."""
    blocks = []
    for issue in issues:
        comments = "".join(f"\n\n{c.get('body', '')}" for c in issue.get("comments") or [])
        blocks.append(f"#{issue['number']} {issue.get('title', '')}\n\n{issue.get('body', '')}{comments}")
    return f"\n{DASHES}\n".join(blocks) if blocks else "none"


def diff_text(repo: str, base: str, sha: str) -> str:
    """`git diff <base>...<head>`, the stat first, then the patch unless it is past what a prompt can hold."""
    stat = tool(repo, ["git", "diff", "--stat", f"{base}...{sha}"])
    patch = tool(repo, ["git", "diff", f"{base}...{sha}"])
    return stat + ("diff too large" if len(patch.encode("utf-8", "surrogateescape")) > MAX_DIFF else patch)


def prompt(root: str, repo: str, pr: dict, bead: str, issues: list) -> str:
    with open(f"{root}/prompts/reviewer.md", encoding="utf-8") as f:
        template = f.read()
    return worktree.render(template, {
        "pr_number": str(pr["number"]), "pr_title": pr.get("title", ""), "bead_id": bead,
        "base_branch": pr["baseRefName"], "spec_path": worktree.spec_path(repo),
        "diff": diff_text(repo, pr["baseRefName"], pr["headRefOid"]), "issues": issue_text(issues)})


# ---------------------------------------------------------------- the reviewer
def reviewer(root: str) -> tuple:
    """(argv, detail): the override when SMILE_REVIEW_CMD is set, else claude on the first model."""
    override = os.environ.get("SMILE_REVIEW_CMD")
    if override:
        return override.split(), "custom"
    model = config.get(root, "reviewer.models").split(",")[0].strip()
    return ["claude", "-p", "--model", model, "--permission-mode",
            config.get(root, "worker.permission_mode")], model


def ask(argv: list, cwd: str, text: str, env: dict) -> str:
    """Run the reviewer with the prompt on stdin and return its stdout; a non-zero exit is a failure."""
    proc = subprocess.run(argv, cwd=cwd, env=env, input=text.encode("utf-8", "surrogateescape"),
                          capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"reviewer exited {proc.returncode}: {worktree.stderr(proc)}")
    return proc.stdout.decode("utf-8", "surrogateescape")


def save(factory: str, number: int, sha: str, text: str) -> None:
    os.makedirs(f"{factory}/reviews", exist_ok=True)
    with open(f"{factory}/reviews/{number}-{sha}.md", "w", encoding="utf-8") as f:
        f.write(text)


# ---------------------------------------------------------------- acting on the verdict
def request_changes(driver: run.Driver, pr: dict, bead: str, findings: list) -> None:
    """One issue per blocking finding, one comment linking them, then another round for the worker."""
    number, sha, repo = pr["number"], pr["headRefOid"], driver.repo
    tool(repo, ["gh", "label", "create", "review", "--force"])
    urls = []
    for line, text in findings:
        body = f"{line}\n\nPR: #{number}\nSHA: {sha}\nBead: {bead}"
        url = tool(repo, ["gh", "issue", "create", "--title", f"PR #{number}: {text[:TITLE_CUT]}",
                          "--label", "review", "--body", body]).strip().splitlines()[-1]
        urls.append(url)
        events.append(driver.root, "issue.opened", bead=bead, pr=number, sha=sha, actor="reviewer",
                      detail=url.rsplit("/", 1)[-1])
    tool(repo, ["gh", "pr", "comment", str(number), "--body", "\n".join(urls)])
    events.append(driver.root, "review.verdict", bead=bead, pr=number, sha=sha, actor="reviewer",
                  detail=f"REQUEST CHANGES {len(findings)}")
    fix_round(driver, bead)


def fix_round(driver: run.Driver, bead: str) -> None:
    """Put the waiting run back under runs/ and spawn the worker again, exactly as a respawn does.

    A bead with no waiting run was reviewed by hand, not by a tick: there is no worker to wake.
    """
    waiting = f"{driver.runs}/waiting/{bead}.json"
    state = driver.read_state(waiting)
    if state is None:
        return
    os.makedirs(driver.runs, exist_ok=True)
    shutil.move(waiting, f"{driver.runs}/{bead}.json")  # before the spawn: a failed one is reaped, not lost
    driver.spawn(bead, state["worktree"], state["order"], attempts=1)


def approve(driver: run.Driver, pr: dict, bead: str, issues: list) -> None:
    """Close what the findings opened, then merge or hand the pull request to a human."""
    number, sha, repo, root = pr["number"], pr["headRefOid"], driver.repo, driver.root
    for issue in issues:
        tool(repo, ["gh", "issue", "close", str(issue["number"]), "--comment", f"Resolved at {sha}"])
        events.append(root, "issue.resolved", bead=bead, pr=number, sha=sha, actor="reviewer",
                      detail=str(issue["number"]))
    events.append(root, "review.verdict", bead=bead, pr=number, sha=sha, actor="reviewer", detail="APPROVE")
    if gate.gated(root, bead, pr["labels"]) or config.get(root, "merge") != "auto":
        tool(repo, ["gh", "label", "create", "smile:approved", "--force"])
        tool(repo, ["gh", "pr", "edit", str(number), "--add-label", "smile:approved"])
        return  # the merge is the human's; the driver closes the bead on the tick that finds it merged
    merged = merge(repo, number)
    events.append(root, "pr.merged", bead=bead, pr=number,
                  sha=(merged.get("mergeCommit") or {}).get("oid"), actor="driver")
    tool(repo, ["bd", "close", bead])
    events.append(root, "bead.closed", bead=bead, pr=number, actor="driver")


def merge(repo: str, number: int) -> dict:
    """Squash-merge, and let GitHub say whether it landed. Returns the merged view.

    `--delete-branch` also deletes the local branch, which git refuses while the worker's treehouse
    worktree still has it checked out, and that worktree is only returned after the bead closes. The
    merge is what matters, so the view decides, not gh's exit code.
    """
    proc = subprocess.run(["gh", "pr", "merge", str(number), "--squash", "--delete-branch"], cwd=repo,
                          env=worktree.TOOL_ENV, capture_output=True, check=False)
    view = github.json_out(repo, ["pr", "view", str(number), "--json", "mergedAt,mergeCommit"])
    if not isinstance(view, dict) or not view.get("mergedAt"):
        raise RuntimeError(f"gh pr merge {number} failed: {worktree.stderr(proc)}")
    return view


# ---------------------------------------------------------------- the command
def cmd_review(root: str, args: list) -> int:
    if len(args) != 1 or not NUMBER.fullmatch(args[0]):
        raise Usage(f"usage: smile review <pr>, got {' '.join(args) if args else ''}")
    number = int(args[0])
    driver = run.Driver(root)
    pr = github.json_out(driver.repo, ["pr", "view", str(number), "--json", PR_FIELDS])
    if not isinstance(pr, dict) or "headRefOid" not in pr:
        raise RuntimeError(f"gh pr view {number} did not print a pull request")
    pr["labels"] = github.labels(pr)
    bead = github.bead_of(pr.get("body") or "")
    if not bead:
        raise RuntimeError(f"pr #{number} carries no Bead: line")
    tool(driver.repo, ["git", "fetch", "origin", pr["headRefName"]])
    path = f"{driver.factory}/review/{number}"
    tool(driver.repo, ["git", "worktree", "add", "--detach", path, pr["headRefOid"]])
    try:
        judge(driver, pr, bead, path)
    finally:  # the worktree goes on every exit path; its removal has nowhere to report, so it is quiet
        subprocess.run(["git", "worktree", "remove", "--force", path], cwd=driver.repo,
                       env=worktree.TOOL_ENV, capture_output=True, check=False)
    return 0


def judge(driver: run.Driver, pr: dict, bead: str, path: str) -> None:
    """Ask the reviewer inside the pinned worktree and act on what it answers."""
    root, number, sha = driver.root, pr["number"], pr["headRefOid"]
    argv, detail = reviewer(root)
    events.append(root, "review.started", bead=bead, pr=number, sha=sha, actor="reviewer", detail=detail)
    issues = github.review_issues(driver.repo, number, "number,title,body,comments")
    text = ask(argv, path, prompt(root, driver.repo, pr, bead, issues), {
        **os.environ, "SMILE_PR": str(number), "SMILE_REPO": driver.repo, "SMILE_BEAD": bead,
        "SMILE_SHA": sha, "SMILE_BASE_BRANCH": pr["baseRefName"]})
    save(driver.factory, number, sha, text)  # the review is kept before it is acted on, verdict or not
    verdict, findings = parse(text)
    if not verdict:
        raise RuntimeError(f"pr #{number}: the review names no actionable verdict")
    if verdict == "REQUEST CHANGES":
        request_changes(driver, pr, bead, findings)
    else:
        approve(driver, pr, bead, issues)
