"""S4 review lane tests, driven through the stamped shim in scratch git repos.

git and bd are real: the review worktree is a real detached worktree of a real repo with a real
`origin`, and `bd close` really closes a bead. GitHub is a fake `gh` first on PATH that records every
argv and answers from one JSON world file the test writes, so the bytes the lane sends (issue titles,
issue bodies, the pull request comment, the merge flags) are asserted as argv, not as intent. The
reviewer is a script named by SMILE_REVIEW_CMD that prints whatever review the test chose.

HOME points at a scratch directory in every run, so the real ~/.claude.json, the real gh config, and
the real treehouse pool are never touched.

Run from the repo root: uv run python -m unittest tests.test_review -v
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.test_core import make_repo, set_config, smile, smile_inproc
from tests.test_driver import FAKE_TMUX, WORKER, bd, bd_json, seed, write_exec

SESSION = f"s4py-{os.getpid()}"
PR_FIELDS = "number,title,state,headRefOid,headRefName,baseRefName,body,labels"
TEMPLATE = ("review {{pr_number}} / {{pr_title}} / {{bead_id}} / {{base_branch}} / {{spec_path}}\n"
            "--- issues\n{{issues}}\n--- diff\n{{diff}}\n--- env\n")
# The reviewer: the prompt is kept for the prompt tests, the environment with it, and the review the
# test chose is printed. REVIEW_EXIT lets a test make the reviewer fail.
REVIEWER = ('#!/bin/sh\ncat > "$REVIEW_PROMPT"\n'
            'printf \'SMILE_PR=%s SMILE_REPO=%s SMILE_BEAD=%s SMILE_SHA=%s SMILE_BASE_BRANCH=%s\\n\' '
            '"$SMILE_PR" "$SMILE_REPO" "$SMILE_BEAD" "$SMILE_SHA" "$SMILE_BASE_BRANCH" >> "$REVIEW_PROMPT"\n'
            'printf \'%s\' "$(pwd)" > "$REVIEW_CWD"\n'
            'cat "$REVIEW_FILE"\nexit "${REVIEW_EXIT:-0}"\n')
FAKE_GH = '''#!/usr/bin/env python3
"""A gh that records argv and answers from the JSON world file the test writes."""
import json, os, sys

argv = sys.argv[1:]
with open(os.environ["FAKE_GH_LOG"], "a") as f:
    f.write(json.dumps(argv) + "\\n")
path = os.environ["FAKE_GH_DATA"]
with open(path) as f:
    data = json.load(f)


def save():
    with open(path, "w") as f:
        json.dump(data, f)


def flag(name):
    return argv[argv.index(name) + 1] if name in argv else ""


def project(obj, fields):
    return {k: obj.get(k) for k in fields.split(",")}


def ordered(table):
    return sorted(table.values(), key=lambda row: row["number"])


STATES = {"open": ["OPEN"], "closed": ["CLOSED", "MERGED"], "merged": ["MERGED"],
          "all": ["OPEN", "CLOSED", "MERGED"]}
verb = argv[:2]
if verb == ["pr", "view"]:
    print(json.dumps(project(data["prs"][argv[2]], flag("--json"))))
elif verb == ["pr", "list"]:
    want = STATES[flag("--state")]
    print(json.dumps([project(p, flag("--json")) for p in ordered(data["prs"]) if p["state"] in want]))
elif verb == ["issue", "list"]:
    print(json.dumps([project(i, flag("--json")) for i in ordered(data["issues"]) if i["state"] == "OPEN"]))
elif verb == ["issue", "create"]:
    n = data["next_issue"]
    data["next_issue"] = n + 1
    url = "https://github.com/o/r/issues/%d" % n
    data["issues"][str(n)] = {"number": n, "title": flag("--title"), "body": flag("--body"),
                              "state": "OPEN", "comments": [], "url": url}
    save()
    print(url)
elif verb == ["issue", "close"]:
    issue = data["issues"][argv[2]]
    issue["state"], issue["closedWith"] = "CLOSED", flag("--comment")
    save()
elif verb == ["pr", "merge"]:
    pr = data["prs"][argv[2]]
    pr["state"], pr["mergedAt"] = "MERGED", "2026-09-18T00:00:00Z"
    pr["mergeCommit"] = {"oid": data["merge_oid"]}
    save()
elif verb == ["pr", "edit"]:
    data["prs"][argv[2]].setdefault("labels", []).append({"name": flag("--add-label")})
    save()
elif verb in (["pr", "comment"], ["label", "create"]):
    pass
else:
    sys.stderr.write("fake gh: unsupported %s\\n" % " ".join(argv))
    sys.exit(2)
'''
# A `claude` first on PATH: it records the argv the lane launched it with and approves.
FAKE_CLAUDE = '#!/bin/sh\ncat >/dev/null\nprintf \'%s\\n\' "$*" > "$CLAUDE_ARGV"\nprintf \'Verdict: APPROVE\\n\'\n'
SLOW_REVIEWER = "#!/bin/sh\ncat >/dev/null\nsleep 30\nprintf 'Verdict: APPROVE\\n'\n"
# A reviewer that files an issue while it thinks, so approve must re-read the open findings.
ISSUE_MAKER = '''#!/usr/bin/env python3
import json, os, sys

sys.stdin.read()
path = os.environ["FAKE_GH_DATA"]
with open(path) as f:
    data = json.load(f)
data["issues"]["7"] = {"number": 7, "title": "PR #1: late finding", "state": "OPEN", "comments": [],
                       "url": "https://github.com/o/r/issues/7",
                       "body": "- [Critical] late finding\\n\\nPR: #1\\nSHA: %s" % os.environ["SMILE_SHA"]}
with open(path, "w") as f:
    json.dump(data, f)
print("Verdict: APPROVE")
'''
APPROVE = "Looks right.\n\nVerdict: APPROVE\n\nPrinciples applied: prove-it-works\n"
CHANGES = ("Not yet.\n\nVerdict: REQUEST CHANGES\n\n"
           "- [Critical] the reap path never returns the worktree\n"
           "- [Important] the test passes on empty output\n\nPrinciples applied: prove-it-works\n")


def git(repo: str, *args: str) -> str:
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True,
                          check=True).stdout.strip()


class ReviewCase(unittest.TestCase):
    """A stamped scratch repo with a real `origin`, one bead, one pushed branch, and a fake GitHub."""

    def setUp(self) -> None:
        self.repo = make_repo("smile-rev", init=True)
        self.addCleanup(shutil.rmtree, os.path.dirname(self.repo), ignore_errors=True)
        set_config(self.repo, "watchtower", "off")  # S5's pane is test_watchtower's subject, not this suite's
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "stamp")
        git(self.repo, "branch", "-M", "main")

        origin = os.path.join(os.path.dirname(self.repo), "origin.git")
        subprocess.run(["git", "init", "-q", "--bare", origin], check=True)
        git(self.repo, "remote", "add", "origin", origin)
        git(self.repo, "push", "-q", "-u", "origin", "main")

        seed(self.repo, "alpha")
        self.bead = bd_json(self.repo, "list", "--all")[0]["id"]
        self.branch = f"smile/{self.bead}"
        git(self.repo, "checkout", "-q", "-b", self.branch)
        Path(self.repo, f"{self.bead}.txt").write_text("worker output\n")
        git(self.repo, "add", f"{self.bead}.txt")  # only the worker's file: the diff is what it wrote
        git(self.repo, "commit", "-qm", "feat: alpha")
        git(self.repo, "push", "-q", "-u", "origin", self.branch)
        self.sha = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "checkout", "-q", "main")
        # the prompts the lane renders, written after the checkout so no branch carries them
        Path(self.repo, "prompts/reviewer.md").write_text(TEMPLATE)
        Path(self.repo, "prompts/worker.md").write_text("order {{bead_id}}\n")

        self.scratch = Path(tempfile.mkdtemp(prefix="smile-rev-env-"))
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.home = self.scratch / "home"
        self.home.mkdir()
        self.bin = self.scratch / "bin"
        self.bin.mkdir()
        self.gh_log, self.data_path = self.scratch / "gh.log", self.scratch / "gh.json"
        self.review_file = self.scratch / "review.md"
        self.prompt_file, self.cwd_file = self.scratch / "prompt.txt", self.scratch / "cwd.txt"
        self.tmux_log, self.tmux_state = self.scratch / "tmux.log", self.scratch / "tmux.json"
        write_exec(self.bin / "gh", FAKE_GH)
        write_exec(self.bin / "tmux", FAKE_TMUX)
        self.reviewer = write_exec(self.bin / "reviewer", REVIEWER)
        self.worker = write_exec(self.bin / "stub-worker", WORKER)
        self.write_data({"prs": {"1": self.pr(1)}, "issues": {}, "next_issue": 7,
                         "merge_oid": "0" * 40})
        self.set_review(APPROVE)
        self.env = {"HOME": str(self.home), "PATH": f"{self.bin}:{os.environ['PATH']}",
                    "FAKE_GH_LOG": str(self.gh_log), "FAKE_GH_DATA": str(self.data_path),
                    "FAKE_TMUX_LOG": str(self.tmux_log), "FAKE_TMUX_STATE": str(self.tmux_state),
                    "SMILE_MUX_SESSION": SESSION, "SMILE_STUB_LOG": str(self.scratch / "stub.log"),
                    "SMILE_REVIEW_CMD": self.reviewer, "SMILE_WORKER_CMD": self.worker,
                    "REVIEW_FILE": str(self.review_file), "REVIEW_PROMPT": str(self.prompt_file),
                    "REVIEW_CWD": str(self.cwd_file)}

    # ------------------------------------------------------------ the world the fake gh answers from
    def pr(self, number: int, **over: object) -> dict:
        pr = {"number": number, "title": "alpha work", "headRefOid": self.sha, "headRefName": self.branch,
              "baseRefName": "main", "body": f"Stub worker output.\n\nBead: {self.bead}",
              "state": "OPEN", "labels": [], "mergedAt": None, "mergeCommit": None}
        pr.update(over)
        return pr

    def write_data(self, data: dict) -> None:
        self.data_path.write_text(json.dumps(data))

    def data(self) -> dict:
        return json.loads(self.data_path.read_text())

    def patch_pr(self, number: int, **over: object) -> None:
        data = self.data()
        data["prs"][str(number)].update(over)
        self.write_data(data)

    def set_review(self, text: str) -> None:
        self.review_file.write_text(text)

    def put_config(self, key: str, value: str) -> None:
        """Append a key the stamped config does not carry, so its default is what it overrides."""
        cfg = Path(self.repo, "smile.config.yaml")
        cfg.write_text(f"{cfg.read_text().rstrip(chr(10))}\n{key}: {value}\n")

    # ------------------------------------------------------------ driving
    def review(self, *args: str, **env: str) -> subprocess.CompletedProcess:
        return smile_inproc(self.repo, "review", *(args or ("1",)), env={**self.env, **env})

    def tick(self, **env: str) -> subprocess.CompletedProcess:
        return smile_inproc(self.repo, "run", "--once", env={**self.env, **env})

    def records(self) -> list:
        path = Path(self.repo, ".factory/events.jsonl")
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def events(self) -> list:
        """(event, bead, pr, sha, actor, detail) per line: every field the contract names."""
        return [(r["event"], r["bead"], r["pr"], r["sha"], r["actor"], r["detail"]) for r in self.records()]

    def names(self) -> list:
        return [r["event"] for r in self.records()]

    def clear_events(self) -> None:
        Path(self.repo, ".factory/events.jsonl").write_text("")

    def gh_calls(self) -> list:
        return [json.loads(line) for line in self.gh_log.read_text().splitlines()] if self.gh_log.exists() else []

    def gh_call(self, *prefix: str) -> list:
        """The one gh call starting with these words; fails when there is not exactly one."""
        found = [c for c in self.gh_calls() if c[:len(prefix)] == list(prefix)]
        self.assertEqual(len(found), 1, f"{' '.join(prefix)}: {found}")
        return found[0]

    def reviews(self) -> list:
        d = Path(self.repo, ".factory/reviews")
        return sorted(p.name for p in d.glob("*.md")) if d.is_dir() else []

    def failed_review(self) -> str:
        return Path(self.repo, f".factory/reviews/1-{self.sha}.failed.md").read_text()

    def lock_file(self) -> Path:
        return Path(self.repo, ".factory/review/1.lock")

    def issue(self, number: int, line: str, sha: str) -> dict:
        """One open `review` issue as the lane itself would have written it."""
        return {"number": number, "title": f"PR #1: {line}", "state": "OPEN", "comments": [],
                "url": f"https://github.com/o/r/issues/{number}",
                "body": f"{line}\n\nPR: #1\nSHA: {sha}\nBead: {self.bead}"}

    def put_issues(self, *issues: dict) -> None:
        data = self.data()
        data["issues"] = {str(i["number"]): i for i in issues}
        self.write_data(data)

    def status(self, bead: str) -> str:
        return next(b["status"] for b in bd_json(self.repo, "list", "--all") if b["id"] == bead)

    def assert_one_line_failure(self, r: subprocess.CompletedProcess) -> None:
        self.assertEqual((r.returncode, r.stdout), (1, b""), r.stderr)
        self.assertEqual(len(r.stderr.splitlines()), 1, r.stderr)
        self.assertNotIn(b"Traceback", r.stderr)


class ShimTest(ReviewCase):
    """The two things the in-process tests do not cover: the shim's dispatch and `init` on a live repo."""

    def test_init_on_an_initialised_repo(self) -> None:
        r = smile(self.repo, "init")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.decode(), "".join(f"exists {t}\n" for t in (
            ".beads", "treehouse.toml", ".worktreeinclude", ".factory", ".factory/events.jsonl")))

    def test_review_through_the_shim(self) -> None:
        r = smile(self.repo, "review", "1", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("review.verdict", self.names())


class VerdictTest(ReviewCase):
    def test_approve_with_no_gate_merges_closes_the_bead_and_logs_the_sequence(self) -> None:
        r = self.review()
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, b"", b""), r.stderr)
        self.assertEqual(self.events(), [
            ("review.started", self.bead, 1, self.sha, "reviewer", "custom"),
            ("review.verdict", self.bead, 1, self.sha, "reviewer", "APPROVE"),
            ("pr.merged", self.bead, 1, "0" * 40, "driver", None),
            ("bead.closed", self.bead, 1, None, "driver", None)])
        self.assertEqual(self.gh_call("pr", "merge"),
                         ["pr", "merge", "1", "--squash", "--delete-branch"])
        self.assertEqual(self.status(self.bead), "closed")
        self.assertEqual(self.data()["prs"]["1"]["state"], "MERGED")

    def test_the_review_text_is_saved_under_the_factory(self) -> None:
        self.assertEqual(self.review().returncode, 0)
        self.assertEqual(self.reviews(), [f"1-{self.sha}.md"])
        self.assertEqual(Path(self.repo, f".factory/reviews/1-{self.sha}.md").read_text(), APPROVE)

    def test_request_changes_opens_one_issue_per_finding_and_comments_the_links(self) -> None:
        self.set_review(CHANGES)
        r = self.review()
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, b"", b""), r.stderr)
        issues = self.data()["issues"]
        self.assertEqual(sorted(issues), ["7", "8"])
        self.assertEqual(issues["7"]["title"], "PR #1: the reap path never returns the worktree")
        self.assertEqual(issues["7"]["body"], "- [Critical] the reap path never returns the worktree\n\n"
                                              f"PR: #1\nSHA: {self.sha}\nBead: {self.bead}")
        self.assertEqual(issues["8"]["title"], "PR #1: the test passes on empty output")
        self.assertEqual(issues["8"]["body"], "- [Important] the test passes on empty output\n\n"
                                              f"PR: #1\nSHA: {self.sha}\nBead: {self.bead}")
        self.assertEqual(self.gh_call("label", "create"), ["label", "create", "review", "--force"])
        self.assertEqual(self.gh_call("pr", "comment"), [
            "pr", "comment", "1", "--body",
            "https://github.com/o/r/issues/7\nhttps://github.com/o/r/issues/8"])
        self.assertEqual(self.events(), [
            ("review.started", self.bead, 1, self.sha, "reviewer", "custom"),
            ("issue.opened", self.bead, 1, self.sha, "reviewer", "7"),
            ("issue.opened", self.bead, 1, self.sha, "reviewer", "8"),
            ("review.verdict", self.bead, 1, self.sha, "reviewer", "REQUEST CHANGES 2")])
        self.assertEqual(self.status(self.bead), "open", "a rejected pull request never closes its bead")

    def test_a_long_finding_is_cut_to_eighty_characters_in_the_title_only(self) -> None:
        text = "x" * 200
        self.set_review(f"Verdict: REQUEST CHANGES\n\n- [Critical] {text}\n")
        self.assertEqual(self.review().returncode, 0)
        issue = self.data()["issues"]["7"]
        self.assertEqual(issue["title"], "PR #1: " + "x" * 80)
        self.assertTrue(issue["body"].startswith(f"- [Critical] {text}\n\nPR: #1\n"), issue["body"])

    def test_request_changes_with_no_blocking_finding_is_no_verdict(self) -> None:
        self.set_review("Verdict: REQUEST CHANGES\n\n- [Suggestion] rename the variable\n")
        self.assert_one_line_failure(self.review())
        self.assertEqual(self.names(), ["review.started"])
        self.assertEqual(self.data()["issues"], {})

    def test_a_review_with_no_verdict_line_fails_and_logs_nothing_further(self) -> None:
        for text in ("", "nothing to say\n", "Verdict: LGTM\n", "  Verdict: APPROVE\n",
                     "Verdict: APPROVE now\n"):
            self.clear_events()
            self.set_review(text)
            self.assert_one_line_failure(self.review())
            self.assertEqual(self.names(), ["review.started"], text)
        self.assertEqual(self.data()["prs"]["1"]["state"], "OPEN")

    def test_a_reviewer_that_exits_non_zero_keeps_its_output_under_failed_md(self) -> None:
        self.set_review("half a thought\n")
        self.assert_one_line_failure(self.review(REVIEW_EXIT="3"))
        self.assertEqual(self.names(), ["review.started"])
        self.assertEqual(self.reviews(), [f"1-{self.sha}.failed.md"], "the reviewer's output was thrown away")
        self.assertIn("half a thought", self.failed_review())

    def test_a_review_with_no_verdict_keeps_its_output_under_failed_md(self) -> None:
        self.set_review("I could not read the diff\n")
        self.assert_one_line_failure(self.review())
        self.assertEqual(self.reviews(), [f"1-{self.sha}.failed.md"])
        self.assertIn("I could not read the diff", self.failed_review())

    def test_a_verdict_line_after_the_first_one_is_ignored(self) -> None:
        self.set_review("Verdict: APPROVE\n\n- [Critical] stale finding\n\nVerdict: REQUEST CHANGES\n")
        self.assertEqual(self.review().returncode, 0)
        self.assertEqual([e for e, *_ in self.events()][1], "review.verdict")
        self.assertEqual(self.events()[1][5], "APPROVE")
        self.assertEqual(self.data()["issues"], {}, "an approve never opens an issue")

    def test_a_pull_request_with_no_bead_line_fails_before_any_worktree(self) -> None:
        self.patch_pr(1, body="no trailer here")
        self.assert_one_line_failure(self.review())
        self.assertEqual(self.names(), [])
        self.assertEqual(self.gh_calls(), [["pr", "view", "1", "--json", PR_FIELDS]])

    def test_bad_arguments_exit_2(self) -> None:
        for args in ((), ("0",), ("x",), ("1", "2"), ("-1",), ("01",)):
            r = self.review(*args) if args else smile(self.repo, "review", env=self.env)
            self.assertEqual((r.returncode, r.stdout), (2, b""), args)
            self.assertEqual(len(r.stderr.splitlines()), 1, r.stderr)
        self.assertEqual(self.names(), [])

    def test_the_review_worktree_is_removed_on_success_and_on_failure(self) -> None:
        path = Path(self.repo, ".factory/review/1")
        self.assertEqual(self.review().returncode, 0)
        self.assertFalse(path.exists(), "the worktree outlived a successful review")
        self.clear_events()
        self.set_review("no verdict at all\n")
        self.assert_one_line_failure(self.review())
        self.assertFalse(path.exists(), "the worktree outlived a failed review")
        self.assertEqual(git(self.repo, "worktree", "list", "--porcelain").count("worktree "), 1)

    def test_the_reviewer_runs_inside_the_worktree_pinned_at_the_head(self) -> None:
        self.assertEqual(self.review().returncode, 0)
        self.assertEqual(self.cwd_file.read_text(),
                         os.path.realpath(Path(self.repo, ".factory/review/1")))


class LockTest(ReviewCase):
    """The pull request state check and the per-PR lock: contract section 9, `smile review <n>`."""

    def test_a_pull_request_that_is_not_open_is_refused_before_anything_is_touched(self) -> None:
        for state in ("MERGED", "CLOSED"):
            self.clear_events()
            self.patch_pr(1, state=state)
            self.assert_one_line_failure(self.review())
            self.assertEqual(self.names(), [], state)
            self.assertFalse(self.lock_file().exists(), "a closed pull request took the lock")
            self.assertEqual(self.reviews(), [])

    def test_a_lock_naming_a_live_pid_refuses_the_second_review(self) -> None:
        self.lock_file().parent.mkdir(parents=True, exist_ok=True)
        self.lock_file().write_text(f"{os.getpid()}\n")
        r = self.review()
        self.assert_one_line_failure(r)
        self.assertRegex(r.stderr.decode(), rf"review already running \(pid {os.getpid()}\)\n$")
        self.assertEqual(self.names(), [])
        self.assertEqual(self.lock_file().read_text(), f"{os.getpid()}\n", "the live lock was overwritten")

    def test_a_lock_naming_a_dead_pid_is_replaced_and_the_lock_is_gone_after(self) -> None:
        dead = subprocess.Popen(["true"])
        dead.wait()
        self.lock_file().parent.mkdir(parents=True, exist_ok=True)
        self.lock_file().write_text(f"{dead.pid}\n")
        self.assertEqual(self.review().returncode, 0)
        self.assertFalse(self.lock_file().exists(), "the lock outlived the review")
        self.assertIn("review.verdict", self.names())

    def test_a_worktree_a_killed_review_left_registered_is_reclaimed(self) -> None:
        """kill -9 leaves <factory>/review/<n> registered; without the removal the PR wedges forever."""
        path = Path(self.repo, ".factory/review/1")
        git(self.repo, "worktree", "add", "--detach", str(path), "main")
        self.assertEqual(self.review().returncode, 0, "a stale review worktree wedged the pull request")
        self.assertFalse(path.exists())
        self.assertEqual(git(self.repo, "worktree", "list", "--porcelain").count("worktree "), 1)


class ReviewerCommandTest(ReviewCase):
    """What the lane launches, and what a reviewer that never answers costs it."""

    def test_the_default_argv_is_claude_in_plan_mode_on_the_first_model(self) -> None:
        argv_file = self.scratch / "claude-argv.txt"
        write_exec(self.bin / "claude", FAKE_CLAUDE)
        set_config(self.repo, "reviewer.models", "opus, haiku")
        r = self.review(SMILE_REVIEW_CMD="", CLAUDE_ARGV=str(argv_file))
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, b"", b""), r.stderr)
        self.assertEqual(argv_file.read_text().strip(), "-p --model opus --permission-mode plan")
        self.assertEqual(self.events()[0], ("review.started", self.bead, 1, self.sha, "reviewer", "opus"))

    def test_a_reviewer_that_never_answers_is_killed_at_the_timeout(self) -> None:
        slow = write_exec(self.bin / "slow-reviewer", SLOW_REVIEWER)
        self.put_config("reviewer.timeout", "1")
        r = self.review(SMILE_REVIEW_CMD=slow)
        self.assert_one_line_failure(r)
        self.assertEqual(self.names(), ["review.started"])
        self.assertEqual(self.reviews(), [f"1-{self.sha}.failed.md"])
        self.assertIn("timed out", self.failed_review())
        self.assertFalse(self.lock_file().exists())

    def test_a_bad_reviewer_timeout_is_refused_before_anything_is_touched(self) -> None:
        for value in ("0", "600s", "", "-1"):
            self.clear_events()
            self.put_config("reviewer.timeout", value)
            self.assert_one_line_failure(self.review())
            self.assertEqual(self.names(), [], value)
            self.assertFalse(self.lock_file().exists(), value)


class IssueTest(ReviewCase):
    """Issue bookkeeping: a retry at the same head files nothing twice, and approve closes what is open now."""

    def test_a_finding_that_is_already_filed_at_this_head_is_reused(self) -> None:
        line = "- [Critical] the reap path never returns the worktree"
        data = self.data()
        data["issues"] = {"7": self.issue(7, line, self.sha)}
        data["next_issue"] = 9
        self.write_data(data)
        self.set_review(CHANGES)
        r = self.review()
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, b"", b""), r.stderr)
        self.assertEqual(sorted(self.data()["issues"]), ["7", "9"], "the known finding was filed twice")
        self.assertEqual([e[5] for e in self.events() if e[0] == "issue.opened"], ["9"])
        self.assertEqual(self.gh_call("pr", "comment")[4],
                         "https://github.com/o/r/issues/7\nhttps://github.com/o/r/issues/9")

    def test_a_finding_filed_at_an_older_head_is_filed_again(self) -> None:
        line = "- [Critical] the reap path never returns the worktree"
        data = self.data()
        data["issues"] = {"7": self.issue(7, line, "a" * 40)}
        data["next_issue"] = 9
        self.write_data(data)
        self.set_review(CHANGES)
        self.assertEqual(self.review().returncode, 0)
        self.assertEqual([e[5] for e in self.events() if e[0] == "issue.opened"], ["9", "10"])

    def test_approve_closes_an_issue_opened_while_the_reviewer_was_thinking(self) -> None:
        maker = write_exec(self.bin / "issue-maker", ISSUE_MAKER)
        r = self.review(SMILE_REVIEW_CMD=maker)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, b"", b""), r.stderr)
        self.assertEqual([e[5] for e in self.events() if e[0] == "issue.resolved"], ["7"],
                         "approve closed the issues read before the reviewer ran, not the open ones")
        self.assertEqual(self.data()["issues"]["7"]["state"], "CLOSED")


class DiffTest(ReviewCase):
    def test_the_diff_is_taken_against_the_fetched_base_not_a_stale_local_one(self) -> None:
        """A local base behind origin pads a three-dot diff with work the pull request never did."""
        git(self.repo, "checkout", "-q", "--detach", "main")
        Path(self.repo, "unrelated.txt").write_text("someone else's merge\n")
        git(self.repo, "add", "unrelated.txt")
        git(self.repo, "commit", "-qm", "chore: unrelated")
        git(self.repo, "push", "-q", "origin", "HEAD:main")
        git(self.repo, "checkout", "-q", "-B", self.branch, "HEAD")
        Path(self.repo, f"{self.bead}.txt").write_text("worker output\n")
        git(self.repo, "add", f"{self.bead}.txt")
        git(self.repo, "commit", "-qm", "feat: alpha")
        git(self.repo, "push", "-qf", "origin", self.branch)
        self.sha = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "checkout", "-q", "main")  # left one commit behind origin/main on purpose
        self.patch_pr(1, headRefOid=self.sha)
        self.assertEqual(self.review().returncode, 0, self.prompt_file)
        body = self.prompt_file.read_text().split("--- diff\n", 1)[1]
        self.assertIn(f"+++ b/{self.bead}.txt", body)
        self.assertNotIn("unrelated.txt", body, "the diff carried work the pull request never did")


class PromptTest(ReviewCase):
    def prompt(self) -> str:
        self.assertEqual(self.review().returncode, 0, self.prompt_file)
        return self.prompt_file.read_text()

    def test_every_placeholder_is_rendered(self) -> None:
        text = self.prompt()
        self.assertTrue(text.startswith(f"review 1 / alpha work / {self.bead} / main / \n"), text[:200])
        self.assertIn(f"SMILE_PR=1 SMILE_REPO={self.repo} SMILE_BEAD={self.bead} "
                      f"SMILE_SHA={self.sha} SMILE_BASE_BRANCH=main\n", text)

    def test_the_diff_carries_the_stat_and_the_patch(self) -> None:
        body = self.prompt().split("--- diff\n", 1)[1]
        self.assertIn(f" {self.bead}.txt | 1 +", body)
        self.assertIn(f"+++ b/{self.bead}.txt", body)
        self.assertIn("+worker output", body)

    def test_issues_reads_none_when_there_are_no_open_findings(self) -> None:
        self.assertEqual(self.prompt().split("--- issues\n", 1)[1].split("\n--- diff")[0], "none")

    def test_issues_carries_every_open_finding_with_its_comments(self) -> None:
        data = self.data()
        data["issues"] = {
            "7": {"number": 7, "title": "PR #1: fix the reap path", "state": "OPEN",
                  "body": f"- [Critical] fix the reap path\n\nPR: #1\nSHA: {self.sha}\nBead: {self.bead}",
                  "comments": [{"body": "worker: pushed a fix"}]},
            "9": {"number": 9, "title": "other pr", "state": "OPEN", "body": "PR: #2", "comments": []}}
        self.write_data(data)
        block = self.prompt().split("--- issues\n", 1)[1].split("\n--- diff")[0]
        self.assertTrue(block.startswith("#7 PR #1: fix the reap path\n\n- [Critical] fix the reap path\n"),
                        block)
        self.assertIn("\n\nworker: pushed a fix", block)
        self.assertNotIn("other pr", block, "an issue naming another pull request was rendered")

    def test_the_spec_path_is_the_newest_doc_repo_relative(self) -> None:
        docs = Path(self.repo, "docs")
        docs.mkdir(exist_ok=True)
        Path(docs, "SPEC.md").write_text("frozen\n")
        self.assertTrue(self.prompt().startswith(
            f"review 1 / alpha work / {self.bead} / main / docs/SPEC.md\n"))


class GateTest(ReviewCase):
    def reset(self) -> None:
        """Back to one open unlabeled pull request, an open bead, and an empty log."""
        self.clear_events()
        self.write_data({"prs": {"1": self.pr(1)}, "issues": {}, "next_issue": 7, "merge_oid": "0" * 40})
        self.gh_log.write_text("")
        bd(self.repo, "update", self.bead, "--status", "open")

    def gate(self, *args: str) -> subprocess.CompletedProcess:
        return smile_inproc(self.repo, "gate", *args, env=self.env)

    def test_the_gate_matrix_decides_label_versus_merge(self) -> None:
        cases = [  # (mode, bead held, PR labels, merge config, gated)
            ("auto", False, [], "auto", False),
            ("all", False, [], "auto", True),
            ("none", True, [], "auto", False),
            ("auto", True, [], "auto", True),
            ("auto", False, ["human-gate"], "auto", True),
            ("all", True, ["human-gate"], "auto", True),
            ("auto", False, [], "manual", True),
        ]
        for mode, held, labels, merge, want_gated in cases:
            with self.subTest(mode=mode, held=held, labels=labels, merge=merge):
                self.reset()
                set_config(self.repo, "merge", merge)
                self.assertEqual(self.gate(mode).returncode, 0)
                self.assertEqual(self.gate("bead", self.bead, "on" if held else "off").returncode, 0)
                self.patch_pr(1, labels=[{"name": name} for name in labels])
                r = self.review()
                self.assertEqual((r.returncode, r.stdout, r.stderr), (0, b"", b""), r.stderr)
                pr = self.data()["prs"]["1"]
                if want_gated:
                    self.assertEqual(self.names(), ["review.started", "review.verdict"])
                    self.assertEqual(pr["state"], "OPEN")
                    self.assertIn("smile:approved", [entry["name"] for entry in pr["labels"]])
                    self.assertEqual(self.gh_call("pr", "edit"),
                                     ["pr", "edit", "1", "--add-label", "smile:approved"])
                    self.assertEqual(self.status(self.bead), "open")
                else:
                    self.assertEqual(self.names(), ["review.started", "review.verdict",
                                                    "pr.merged", "bead.closed"])
                    self.assertEqual(pr["state"], "MERGED")
                    self.assertEqual(self.status(self.bead), "closed")

    def test_gate_status_and_the_file_bytes(self) -> None:
        path = Path(self.repo, ".factory/gate.json")
        status = self.gate("status")
        self.assertEqual((status.returncode, status.stdout, status.stderr), (0, b"mode auto\n", b""))
        self.assertFalse(path.exists(), "reading the gate wrote a file")
        for args, bytes_written in (
                (("all",), b'{"beads":[],"mode":"all"}\n'),
                (("bead", "sv-2", "on"), b'{"beads":["sv-2"],"mode":"all"}\n'),
                (("bead", "sv-1", "on"), b'{"beads":["sv-1","sv-2"],"mode":"all"}\n'),
                (("bead", "sv-2", "on"), b'{"beads":["sv-1","sv-2"],"mode":"all"}\n'),
                (("auto",), b'{"beads":["sv-1","sv-2"],"mode":"auto"}\n'),
                (("bead", "sv-1", "off"), b'{"beads":["sv-2"],"mode":"auto"}\n'),
                (("bead", "sv-9", "off"), b'{"beads":["sv-2"],"mode":"auto"}\n')):
            r = self.gate(*args)
            self.assertEqual((r.returncode, r.stdout, r.stderr), (0, b"", b""), args)
            self.assertEqual(path.read_bytes(), bytes_written, args)
        status = self.gate("status")
        self.assertEqual((status.returncode, status.stdout), (0, b"mode auto\nbead sv-2\n"), status.stderr)

    def test_bad_gate_arguments_exit_2_and_write_nothing(self) -> None:
        for args in ((), ("some",), ("bead",), ("bead", "sv-1"), ("bead", "sv-1", "maybe"),
                     ("status", "extra"), ("all", "none"), ("bead", "sv-1", "on", "extra")):
            r = self.gate(*args)
            self.assertEqual((r.returncode, r.stdout), (2, b""), args)
            self.assertEqual(len(r.stderr.splitlines()), 1, r.stderr)
        self.assertFalse(Path(self.repo, ".factory/gate.json").exists())


class AuditTest(ReviewCase):
    def audit(self, *args: str) -> subprocess.CompletedProcess:
        return smile_inproc(self.repo, "audit", *args, env=self.env)

    def test_audit_lists_merged_pull_requests_with_no_approve_at_their_head(self) -> None:
        self.write_data({"prs": {
            "1": self.pr(1, state="MERGED", headRefOid="a" * 40),
            "2": self.pr(2, state="MERGED", headRefOid="b" * 40),
            "3": self.pr(3, state="MERGED", headRefOid="c" * 40, body="no bead trailer"),
            "4": self.pr(4, state="OPEN", headRefOid="d" * 40)},
            "issues": {}, "next_issue": 7, "merge_oid": "0" * 40})
        before = self.audit()
        self.assertEqual((before.returncode, before.stderr), (0, b""), before.stderr)
        self.assertEqual(before.stdout, f"#1 {'a' * 40} {self.bead}\n#2 {'b' * 40} {self.bead}\n".encode())
        smile(self.repo, "event", "review.verdict", "pr=1", f"sha={'a' * 40}", "detail=APPROVE", env=self.env)
        smile(self.repo, "event", "review.verdict", "pr=2", f"sha={'z' * 40}", "detail=APPROVE", env=self.env)
        r = self.audit()
        self.assertEqual((r.returncode, r.stdout, r.stderr),
                         (0, f"#2 {'b' * 40} {self.bead}\n".encode(), b""))
        smile(self.repo, "event", "review.verdict", "pr=2", f"sha={'b' * 40}", "detail=APPROVE", env=self.env)
        clean = self.audit()
        self.assertEqual((clean.returncode, clean.stdout, clean.stderr), (0, b"", b""))

    def test_audit_takes_no_arguments(self) -> None:
        r = self.audit("1")
        self.assertEqual((r.returncode, r.stdout), (2, b""))
        self.assertEqual(len(r.stderr.splitlines()), 1, r.stderr)


class TickTest(ReviewCase):
    """The driver's step 2: name new pull requests, review unjudged heads, close what a human merged."""

    def runs(self, where: str = "") -> dict:
        d = Path(self.repo, ".factory/runs", where)
        return {p.name: json.loads(p.read_text()) for p in sorted(d.glob("*.json"))} if d.is_dir() else {}

    def spawns(self) -> list:
        calls = [json.loads(line) for line in self.tmux_log.read_text().splitlines()]
        return [c for c in calls if c["argv"][0] in ("new-window", "new-session")]

    def test_pr_opened_is_logged_once_and_the_head_is_reviewed_once(self) -> None:
        first = self.tick()
        self.assertEqual((first.returncode, first.stdout, first.stderr), (0, b"", b""), first.stderr)
        self.assertEqual(self.names(), ["campaign.start", "pr.opened", "review.started", "review.verdict",
                                        "pr.merged", "bead.closed", "campaign.complete"])
        self.assertEqual(self.events()[1], ("pr.opened", self.bead, 1, self.sha, "driver", None))
        second = self.tick()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(self.names().count("pr.opened"), 1)
        self.assertEqual(self.names().count("review.started"), 1, "a judged head was reviewed again")

    def test_a_verdict_at_an_older_sha_does_not_count_as_a_verdict(self) -> None:
        smile(self.repo, "event", "review.verdict", f"bead={self.bead}", "pr=1", "sha=stale",
              "detail=APPROVE", env=self.env)
        self.assertEqual(self.tick().returncode, 0)
        started = [e for e in self.events() if e[0] == "review.started"]
        self.assertEqual(len(started), 1)
        self.assertEqual(started[0][3], self.sha)

    def test_a_failing_review_is_one_stderr_line_and_the_tick_goes_on(self) -> None:
        self.set_review("no verdict here\n")
        r = self.tick()
        self.assertEqual((r.returncode, r.stdout), (0, b""), r.stderr)
        self.assertEqual(len(r.stderr.splitlines()), 1, r.stderr)
        self.assertRegex(r.stderr.decode(), r"^smile: review 1 failed: .+\n$")
        self.assertEqual(self.names(), ["campaign.start", "pr.opened", "review.started", "bead.claimed",
                                        "worktree.acquired", "pane.spawned"])

    def test_a_merged_approved_pull_request_closes_its_bead(self) -> None:
        self.patch_pr(1, state="MERGED", mergedAt="2026-09-18T00:00:00Z",
                      mergeCommit={"oid": "f" * 40}, labels=[{"name": "smile:approved"}])
        r = self.tick()
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, b"", b""), r.stderr)
        self.assertEqual(self.events()[1:3], [
            ("pr.merged", self.bead, 1, "f" * 40, "human", None),
            ("bead.closed", self.bead, 1, None, "driver", None)])
        self.assertEqual(self.status(self.bead), "closed")
        self.assertEqual(self.tick().returncode, 0)
        self.assertEqual(self.names().count("bead.closed"), 1, "the bead was closed twice")

    def test_a_merged_pull_request_with_no_label_closes_its_bead(self) -> None:
        """`smile:approved` is not required: GitHub is the record of what landed, `smile audit` reports it."""
        self.patch_pr(1, state="MERGED", mergedAt="2026-09-18T00:00:00Z",
                      mergeCommit={"oid": "f" * 40}, labels=[])
        r = self.tick()
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, b"", b""), r.stderr)
        self.assertEqual(self.events()[1:3], [
            ("pr.merged", self.bead, 1, "f" * 40, "human", None),
            ("bead.closed", self.bead, 1, None, "driver", None)])
        self.assertEqual(self.status(self.bead), "closed")
        self.assertEqual(self.audit().stdout, f"#1 {self.sha} {self.bead}\n".encode())

    def test_a_pull_request_merged_by_hand_before_any_tick_is_never_a_crash(self) -> None:
        self.write_data({"prs": {}, "issues": {}, "next_issue": 7, "merge_oid": "0" * 40})
        self.assertEqual(self.tick().returncode, 0)
        state = self.runs()[f"{self.bead}.json"]
        self.kill_window(state["handle"])
        self.write_data({"prs": {"1": self.pr(1, state="MERGED", mergedAt="2026-09-18T00:00:00Z",
                                              mergeCommit={"oid": "f" * 40})},
                         "issues": {}, "next_issue": 7, "merge_oid": "0" * 40})
        r = self.tick()
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, b"", b""), r.stderr)
        self.assertNotIn("worker.crashed", self.names(), "a hand-merged pull request was read as a crash")
        self.assertEqual(sorted(self.runs("waiting")), [f"{self.bead}.json"])
        self.assertIn("bead.closed", self.names())

    def test_three_reviews_with_no_verdict_escalate_once_and_stop_reviewing(self) -> None:
        for _ in range(3):
            smile(self.repo, "event", "review.started", f"bead={self.bead}", "pr=1", f"sha={self.sha}",
                  "actor=reviewer", "detail=custom", env=self.env)
        self.set_review("no verdict here\n")
        r = self.tick()
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, b"", b""), r.stderr)
        self.assertEqual(self.names().count("review.started"), 3, "a capped head was reviewed again")
        escalations = [e for e in self.events() if e[0] == "watch.escalation"]
        self.assertEqual(escalations, [
            ("watch.escalation", self.bead, 1, self.sha, "driver", "review failed 3 times")])
        self.assertEqual(self.tick().returncode, 0)
        self.assertEqual(self.names().count("watch.escalation"), 1, "the escalation was logged twice")

    def test_two_failed_reviews_are_still_under_the_cap(self) -> None:
        for _ in range(2):
            smile(self.repo, "event", "review.started", f"bead={self.bead}", "pr=1", f"sha={self.sha}",
                  "actor=reviewer", "detail=custom", env=self.env)
        self.assertEqual(self.tick().returncode, 0)
        self.assertEqual(self.names().count("review.started"), 3)
        self.assertNotIn("watch.escalation", self.names())

    def audit(self) -> subprocess.CompletedProcess:
        return smile(self.repo, "audit", env=self.env)

    def test_a_merged_approved_pull_request_that_is_not_merged_yet_is_left_alone(self) -> None:
        self.patch_pr(1, state="CLOSED", labels=[{"name": "smile:approved"}])
        self.assertEqual(self.tick().returncode, 0)
        self.assertNotIn("bead.closed", self.names())
        self.assertEqual(self.status(self.bead), "in_progress")

    def test_a_pull_request_without_a_bead_trailer_is_not_the_factory_s(self) -> None:
        self.patch_pr(1, body="a human wrote this one")
        self.assertEqual(self.tick().returncode, 0)
        self.assertEqual(self.names(), ["campaign.start", "bead.claimed", "worktree.acquired",
                                        "pane.spawned"])

    def test_request_changes_moves_the_waiting_run_back_and_respawns_the_worker(self) -> None:
        # REVIEW_EXIT makes the reviewer fail, so the two ticks below only claim, park, and log.
        first = self.tick(REVIEW_EXIT="9")
        self.assertEqual((first.returncode, first.stdout), (0, b""), first.stderr)
        state = self.runs()[f"{self.bead}.json"]
        self.assertEqual(state["attempts"], 1)
        self.assertIn("pr.opened", self.names())
        self.kill_window(state["handle"])
        second = self.tick(REVIEW_EXIT="9")
        self.assertEqual((second.returncode, second.stdout), (0, b""), second.stderr)
        self.assertEqual(sorted(self.runs("waiting")), [f"{self.bead}.json"], "the run did not park")
        self.assertEqual(self.runs(), {})
        self.assertNotIn("worker.crashed", self.names(), "a finished round was read as a crash")

        self.clear_events()
        self.set_review(CHANGES)
        r = self.review()
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, b"", b""), r.stderr)
        back = self.runs()[f"{self.bead}.json"]
        self.assertEqual(self.runs("waiting"), {}, "the waiting file stayed parked")
        self.assertEqual(back["attempts"], 1, "a fix round starts a fresh pair of attempts")
        self.assertEqual((back["worktree"], back["order"]), (state["worktree"], state["order"]))
        self.assertNotEqual(back["handle"], state["handle"])
        self.assertEqual(self.names(), ["review.started", "issue.opened", "issue.opened",
                                        "review.verdict", "pane.spawned"])
        self.assertEqual(self.events()[-1], ("pane.spawned", self.bead, None, None, "driver", back["handle"]))
        self.assertEqual(len(self.spawns()), 2)

    def test_a_finished_worker_parks_before_the_log_names_its_pull_request(self) -> None:
        """Reap runs before review, so on the tick that finds the pane dead only GitHub knows."""
        self.write_data({"prs": {}, "issues": {}, "next_issue": 7, "merge_oid": "0" * 40})
        first = self.tick()
        self.assertEqual((first.returncode, first.stdout, first.stderr), (0, b"", b""), first.stderr)
        state = self.runs()[f"{self.bead}.json"]
        self.assertNotIn("pr.opened", self.names())
        self.kill_window(state["handle"])
        self.write_data({"prs": {"1": self.pr(1)}, "issues": {}, "next_issue": 7, "merge_oid": "0" * 40})
        second = self.tick(REVIEW_EXIT="9")  # the review fails, so only reap's own reading decides
        self.assertEqual((second.returncode, second.stdout), (0, b""), second.stderr)
        self.assertNotIn("worker.crashed", self.names(), "a finished round was read as a crash")
        self.assertEqual(sorted(self.runs("waiting")), [f"{self.bead}.json"])
        self.assertEqual(len(self.spawns()), 1, "a worker waiting on review was respawned")

    def test_a_hand_review_of_a_bead_with_no_waiting_run_spawns_nothing(self) -> None:
        self.set_review(CHANGES)
        self.assertEqual(self.review().returncode, 0)
        self.assertEqual(self.names(), ["review.started", "issue.opened", "issue.opened", "review.verdict"])
        self.assertFalse(self.tmux_log.exists(), "a pane was opened for a bead with no run")

    def test_approve_on_a_fix_round_closes_the_open_findings(self) -> None:
        self.set_review(CHANGES)
        self.assertEqual(self.review().returncode, 0)
        self.clear_events()
        self.gh_log.write_text("")
        self.set_review(APPROVE)
        self.assertEqual(self.review().returncode, 0)
        issues = self.data()["issues"]
        self.assertEqual([issues[n]["state"] for n in ("7", "8")], ["CLOSED", "CLOSED"])
        self.assertEqual([issues[n]["closedWith"] for n in ("7", "8")],
                         [f"Resolved at {self.sha}"] * 2)
        self.assertEqual(self.names(), ["review.started", "issue.resolved", "issue.resolved",
                                        "review.verdict", "pr.merged", "bead.closed"])
        self.assertEqual([e[5] for e in self.events() if e[0] == "issue.resolved"], ["7", "8"])

    def kill_window(self, handle: str) -> None:
        data = json.loads(self.tmux_state.read_text())
        data["windows"].pop(handle.partition(":")[2], None)
        self.tmux_state.write_text(json.dumps(data))


if __name__ == "__main__":
    unittest.main()
