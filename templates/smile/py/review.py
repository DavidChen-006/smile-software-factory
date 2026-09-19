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
from contextlib import suppress

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
PR_FIELDS = "number,title,state,headRefOid,headRefName,baseRefName,body,labels"
ISSUE_FIELDS = "number,title,body,comments,url"
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
    """`git diff origin/<base>...<head>`, the stat first, then the patch unless it is past what a prompt holds."""
    stat = tool(repo, ["git", "diff", "--stat", f"{base}...{sha}"])
    patch = tool(repo, ["git", "diff", f"{base}...{sha}"])
    return stat + ("diff too large" if len(patch.encode("utf-8", "surrogateescape")) > MAX_DIFF else patch)


def prompt(root: str, repo: str, pr: dict, bead: str, issues: list) -> str:
    with open(f"{root}/prompts/reviewer.md", encoding="utf-8") as f:
        template = f.read()
    return worktree.render(template, {
        "pr_number": str(pr["number"]), "pr_title": pr.get("title", ""), "bead_id": bead,
        "base_branch": pr["baseRefName"], "spec_path": worktree.spec_path(repo),
        "diff": diff_text(repo, f"origin/{pr['baseRefName']}", pr["headRefOid"]),
        "issues": issue_text(issues)})


# ---------------------------------------------------------------- the reviewer
def reviewer(root: str) -> tuple:
    """(argv, detail): the override when SMILE_REVIEW_CMD is set, else claude on the first model.

    The reviewer reads and never edits, so it always runs in `plan`; worker.permission_mode is the
    worker's business alone.
    """
    override = os.environ.get("SMILE_REVIEW_CMD")
    if override:
        return override.split(), "custom"
    model = config.get(root, "reviewer.models").split(",")[0].strip()
    return ["claude", "-p", "--model", model, "--permission-mode", "plan"], model


def timeout(root: str) -> int:
    """`reviewer.timeout` seconds, validated like `--interval`: a misconfigured repo never runs a review."""
    value = config.get(root, "reviewer.timeout")
    if not run.COUNT.fullmatch(value):
        raise RuntimeError(f"bad reviewer.timeout {value}")
    return int(value)


def ask(argv: list, cwd: str, text: str, env: dict, seconds: int) -> tuple:
    """(returncode, stdout, stderr) from the reviewer, the prompt on its stdin.

    A reviewer that outruns `reviewer.timeout` is killed and counts as a non-zero exit, so a wedged
    claude is one failed attempt against the cap, not a driver that never ticks again.
    """
    try:
        proc = subprocess.run(argv, cwd=cwd, env=env, input=text.encode("utf-8", "surrogateescape"),
                              capture_output=True, check=False, timeout=seconds)
    except subprocess.TimeoutExpired as expired:
        out = (expired.stdout or b"").decode("utf-8", "surrogateescape")
        err = (expired.stderr or b"").decode("utf-8", "surrogateescape")
        return 1, out, f"{err}\nreviewer timed out after {seconds}s"
    return (proc.returncode, proc.stdout.decode("utf-8", "surrogateescape"),
            proc.stderr.decode("utf-8", "surrogateescape"))


def save(factory: str, number: int, sha: str, text: str, failed: bool = False) -> None:
    """The review, or what the reviewer printed when there was no review to act on."""
    os.makedirs(f"{factory}/reviews", exist_ok=True)
    suffix = ".failed.md" if failed else ".md"
    with open(f"{factory}/reviews/{number}-{sha}{suffix}", "w", encoding="utf-8") as f:
        f.write(text)


# ---------------------------------------------------------------- acting on the verdict
def already_open(issues: list, line: str, number: int, sha: str) -> dict | None:
    """The open finding this exact line already has at this head, if any.

    A review that failed after opening some of its issues is run again at the same head, and the
    second pass must reuse what the first one wrote instead of filing every finding twice.
    """
    want = {f"PR: #{number}", f"SHA: {sha}"}
    for issue in issues:
        body = [entry.strip() for entry in (issue.get("body") or "").splitlines()]
        if body and body[0] == line and want <= set(body):
            return issue
    return None


def request_changes(driver: run.Driver, pr: dict, bead: str, findings: list, issues: list) -> None:
    """One issue per blocking finding, one comment linking them, then another round for the worker."""
    number, sha, repo = pr["number"], pr["headRefOid"], driver.repo
    tool(repo, ["gh", "label", "create", "review", "--force"])
    urls = []
    for line, text in findings:
        known = already_open(issues, line, number, sha)
        if known is not None:  # a retry at the same head: the issue is already filed and already logged
            urls.append(known.get("url") or "")
            continue
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


def approve(driver: run.Driver, pr: dict, bead: str) -> None:
    """Close what the findings opened, then merge or hand the pull request to a human.

    The findings are listed afresh here, not taken from the read the prompt was built from: the
    reviewer's own round may have taken minutes, and what is open now is what must be closed.
    """
    number, sha, repo, root = pr["number"], pr["headRefOid"], driver.repo, driver.root
    for issue in github.review_issues(repo, number):
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


# ---------------------------------------------------------------- the lock
def take(path: str) -> bool:
    """Create the lock exclusively with this pid inside. False when it already exists."""
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(f"{os.getpid()}\n")
    return True


def lock(factory: str, number: int) -> str:
    """Take <factory>/review/<n>.lock, or refuse: a live pid in it means this pull request is being reviewed.

    A review killed mid-run leaves the lock behind, so anything but a live pid is stale and replaced;
    the worktree that review left registered is removed by the caller, not here.
    """
    os.makedirs(f"{factory}/review", exist_ok=True)
    path = f"{factory}/review/{number}.lock"
    if take(path):
        return path
    pid = run.owner(path)
    if pid > 0 and run.alive(pid):
        raise RuntimeError(f"review already running (pid {pid})")
    with suppress(FileNotFoundError):
        os.remove(path)
    if not take(path):  # another review took it in between; whoever holds it now is the live one
        raise RuntimeError(f"review already running (pid {run.owner(path)})")
    return path


# ---------------------------------------------------------------- the command
def cmd_review(root: str, args: list) -> int:
    if len(args) != 1 or not NUMBER.fullmatch(args[0]):
        raise Usage(f"usage: smile review <pr>, got {' '.join(args) if args else ''}")
    number = int(args[0])
    driver = run.Driver(root)
    seconds = timeout(root)
    pr = github.json_out(driver.repo, ["pr", "view", str(number), "--json", PR_FIELDS])
    if not isinstance(pr, dict) or "headRefOid" not in pr:
        raise RuntimeError(f"gh pr view {number} did not print a pull request")
    pr["labels"] = github.labels(pr)
    bead = github.bead_of(pr.get("body") or "")
    if not bead:
        raise RuntimeError(f"pr #{number} carries no Bead: line")
    if pr.get("state") != "OPEN":
        raise RuntimeError(f"pr #{number} is {pr.get('state')}, not OPEN")
    held = lock(driver.factory, number)
    try:
        tool(driver.repo, ["git", "fetch", "origin", pr["baseRefName"], pr["headRefName"]])
        path = f"{driver.factory}/review/{number}"
        remove_worktree(driver.repo, path)  # a review killed mid-run left this path registered
        tool(driver.repo, ["git", "worktree", "add", "--detach", path, pr["headRefOid"]])
        try:
            judge(driver, pr, bead, path, seconds)
        finally:  # the worktree goes on every exit path; its removal has nowhere to report
            remove_worktree(driver.repo, path)
    finally:
        with suppress(FileNotFoundError):
            os.remove(held)
    return 0


def remove_worktree(repo: str, path: str) -> None:
    """Drop the review worktree if git knows it; a path git never registered is not an error."""
    subprocess.run(["git", "worktree", "remove", "--force", path], cwd=repo,
                   env=worktree.TOOL_ENV, capture_output=True, check=False)


def judge(driver: run.Driver, pr: dict, bead: str, path: str, seconds: int) -> None:
    """Ask the reviewer inside the pinned worktree and act on what it answers."""
    root, number, sha = driver.root, pr["number"], pr["headRefOid"]
    argv, detail = reviewer(root)
    events.append(root, "review.started", bead=bead, pr=number, sha=sha, actor="reviewer", detail=detail)
    issues = github.review_issues(driver.repo, number, ISSUE_FIELDS)
    code, text, err = ask(argv, path, prompt(root, driver.repo, pr, bead, issues), {
        **os.environ, "SMILE_PR": str(number), "SMILE_REPO": driver.repo, "SMILE_BEAD": bead,
        "SMILE_SHA": sha, "SMILE_BASE_BRANCH": pr["baseRefName"]}, seconds)
    verdict, findings = ("", []) if code else parse(text)
    if not verdict:  # what the reviewer printed is kept where a human can read why it was thrown away
        save(driver.factory, number, sha, text + err, failed=True)
        raise RuntimeError(f"pr #{number}: the reviewer exited {code} and named no actionable verdict")
    save(driver.factory, number, sha, text)  # the review is kept before it is acted on
    if verdict == "REQUEST CHANGES":
        request_changes(driver, pr, bead, findings, issues)
    else:
        approve(driver, pr, bead)
