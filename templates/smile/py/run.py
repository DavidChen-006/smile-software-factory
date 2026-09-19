"""smile run: the driver loop (contract section 8).

One tick is reap, review, claim and spawn, complete, in that order. Everything the driver knows about
a pane lives in `.factory/runs/<bead>.json`; the pane itself is only ever touched through
`smile mux`, run as a subprocess, so both runtimes drive the same seam. Every tool runs with the main
checkout as its working directory, so a driver started in a linked worktree drives one factory and one
treehouse pool. Failures raise: main turns them into one stderr line and exit 1.
"""

import glob
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from contextlib import suppress
from datetime import datetime, timezone

import config
import events
import github
import worktree
from mux import Usage
from worktree import stderr, tool

OPEN = ("open", "in_progress", "blocked")  # a campaign is complete when no bead is in one of these
STATE_KEYS = ("bead", "worktree", "handle", "order", "attempts", "spawned_at")
COUNT = re.compile(r"[1-9][0-9]*")  # ASCII only: str.isdigit() would take ٣ and ⁷
CAP = 3  # reviews of one head that named no verdict before the driver stops trying (contract section 9)


def unanswered(log: list, pr: int, sha: str) -> int:
    """How many reviews of this head no verdict ever answered: the cap counts attempts, not reviews.

    A verdict at the pair clears the count, so a head that was judged and then re-reviewed at the
    same sha starts its tally again rather than inheriting the old one.
    """
    count = 0
    for record in log:
        if record.get("pr") != pr or record.get("sha") != sha:
            continue
        if record.get("event") == "review.started":
            count += 1
        elif record.get("event") == "review.verdict":
            count = 0
    return count


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def beads(cwd: str, argv: list) -> list:
    """The bead records a bd command prints, as a list of dicts."""
    listed = json.loads(tool(cwd, argv) or "[]")
    if not isinstance(listed, list) or any(not isinstance(b, dict) for b in listed):
        raise RuntimeError(f"{' '.join(argv)} did not print a list of beads")
    return listed


def trust_file() -> dict:
    """~/.claude.json as an object; {} when absent. Anything else is a failure, never a file to overwrite."""
    try:
        with open(os.path.expanduser("~/.claude.json"), encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        raise RuntimeError("bad ~/.claude.json") from None
    if not isinstance(data, dict):
        # suppressed TRY004: every driver failure leaves as one RuntimeError line, never a TypeError
        raise RuntimeError("bad ~/.claude.json")  # noqa: TRY004
    return data


def trust(path: str) -> None:
    """Mark one worktree trusted in ~/.claude.json: rewrite beside it and replace, so a crash keeps the file."""
    home = os.path.expanduser("~/.claude.json")
    data = trust_file()
    data.setdefault("projects", {}).setdefault(path, {})["hasTrustDialogAccepted"] = True
    with open(f"{home}.tmp", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(f"{home}.tmp", home)


class Driver:
    """The loop's state: where the factory is, what the config says, and the run files under it."""

    def __init__(self, root: str, interval: int = 60) -> None:
        self.root = root
        self.interval = interval
        self.repo = worktree.repo(root)  # every tool call runs here, never in a linked worktree
        self.factory = worktree.factory(root)
        self.runs = f"{self.factory}/runs"
        self.parallel = int(config.get(root, "max_parallel"))
        self.prs: list | None = None
        self.every_pr: list | None = None
        self.base_branch = config.get(root, "base_branch")

    # ------------------------------------------------------------ seams
    def smile(self, *args: str) -> subprocess.CompletedProcess:
        """A command of the stamped shim as a subprocess, never as an import: one entry point, always."""
        return subprocess.run([f"{self.root}/smile/smile", *args], cwd=self.repo,
                              env=worktree.TOOL_ENV, capture_output=True, check=False)

    def mux(self, *args: str) -> subprocess.CompletedProcess:
        """The mux seam, always through the shim, so both the driver and a reviewer drive one seam."""
        return self.smile("mux", *args)

    def event(self, name: str, bead: str, detail: str | None = None, ts: str | None = None) -> None:
        events.append(self.root, name, bead=bead, actor="driver", detail=detail, ts=ts)

    def open_prs(self) -> list:
        """The open factory pull requests, read once per tick: reap and review ask the same question."""
        if self.prs is None:
            self.prs = github.factory_prs(self.repo, "open")
        return self.prs

    def all_prs(self) -> list:
        """Every factory pull request in any state, read once per tick: reap asks whether one exists at all."""
        if self.every_pr is None:
            self.every_pr = github.factory_prs(self.repo, "all", "number,body")
        return self.every_pr

    def state_files(self, where: str = "") -> list:
        return sorted(glob.glob(f"{self.runs}/{where}/*.json" if where else f"{self.runs}/*.json"))

    def live_files(self) -> list:
        """Every run that still holds a worktree: spawned under runs/, or waiting on review."""
        return self.state_files() + self.state_files("waiting")

    def read_state(self, path: str) -> dict | None:
        """The run state in a file, or None when it is not a JSON object carrying all six keys."""
        try:
            with open(path, encoding="utf-8") as f:
                state = json.load(f)
        except (OSError, ValueError):
            return None
        return state if isinstance(state, dict) and all(k in state for k in STATE_KEYS) else None

    def write_state(self, state: dict) -> None:
        """Compact JSON with sorted keys and a trailing newline: both runtimes write the same bytes."""
        os.makedirs(self.runs, exist_ok=True)
        with open(f"{self.runs}/{state['bead']}.json", "w", encoding="utf-8") as f:
            f.write(json.dumps(state, sort_keys=True, separators=(",", ":")) + "\n")

    def file_under(self, path: str, name: str) -> None:
        os.makedirs(f"{self.runs}/{name}", exist_ok=True)
        shutil.move(path, f"{self.runs}/{name}/{os.path.basename(path)}")

    # ------------------------------------------------------------ tick
    def tick(self) -> bool:
        """One tick in contract order. True when the campaign is complete."""
        self.prs = self.every_pr = None  # the tick's view of GitHub, read at most once each
        self.reap()
        self.review_pending()
        self.watchtower()  # before the pause check: a paused campaign is exactly when it must be watching
        if not os.path.exists(f"{self.factory}/pause"):  # pause already logged driver.paused; log nothing here
            self.claim()
        return self.complete()

    # ------------------------------------------------------------ watchtower (contract section 11)
    def watchtower(self) -> None:
        """One long-lived observer pane per campaign, respawned whenever its handle is dead.

        Its failure is never a bead's failure: a spawn that does not take is one stderr line and
        the tick goes on.
        """
        if config.get(self.root, "watchtower") != "on":
            return
        path = f"{self.factory}/watchtower.json"
        state = self.read_watchtower(path)
        if state and self.mux("alive", state["handle"]).returncode == 0:
            return
        try:
            order = self.write_watch_order()
            proc = self.mux("spawn", "watchtower", self.repo, *self.watch_pane(order))
            if proc.returncode != 0:
                raise RuntimeError(f"spawn failed: {stderr(proc)}")
            handle, stamp = proc.stdout.decode().strip(), now()
            events.append(self.root, "pane.spawned", bead=None, actor="driver", detail=handle, ts=stamp)
            with open(path, "w", encoding="utf-8") as f:
                f.write(json.dumps({"handle": handle, "spawned_at": stamp},
                                   sort_keys=True, separators=(",", ":")) + "\n")
        except Exception as e:  # noqa: BLE001  the observer never takes the campaign down with it
            print(f"smile: watchtower not started: {e}", file=sys.stderr)

    def read_watchtower(self, path: str) -> dict | None:
        """The watchtower state, or None when the file is missing or names no handle."""
        try:
            with open(path, encoding="utf-8") as f:
                state = json.load(f)
        except (OSError, ValueError):
            return None
        return state if isinstance(state, dict) and state.get("handle") else None

    def write_watch_order(self) -> str:
        """Render prompts/watchtower.md into .factory/orders/watchtower.md and return that path."""
        with open(f"{self.root}/prompts/watchtower.md", encoding="utf-8") as f:
            template = f.read()
        values = {"spec_path": worktree.spec_path(self.repo), "base_branch": self.base_branch,
                  "repo": self.repo}
        order = f"{self.factory}/orders/watchtower.md"
        os.makedirs(os.path.dirname(order), exist_ok=True)
        with open(order, "w", encoding="utf-8") as f:
            f.write(worktree.render(template, values))
        return order

    def watch_pane(self, order: str) -> list:
        """The watchtower pane's argv; SMILE_ACTOR is what signs its `smile event` lines."""
        return ["env", f"SMILE_REPO={self.repo}", f"SMILE_BASE_BRANCH={self.base_branch}",
                "SMILE_ACTOR=watchtower", *self.watch_cmd(order)]

    def watch_cmd(self, order: str) -> list:
        """SMILE_WATCHTOWER_CMD plus the order path, else claude in plan mode with the order text."""
        override = os.environ.get("SMILE_WATCHTOWER_CMD")
        if override:
            return [*override.split(), order]
        with open(order, encoding="utf-8") as f:
            text = f.read()
        return ["claude", "--model", config.get(self.root, "watchtower.model"),
                "--permission-mode", "plan", text]

    def reap_watchtower(self) -> None:
        """Kill the observer and forget it, before the campaign is called complete."""
        path = f"{self.factory}/watchtower.json"
        state = self.read_watchtower(path)
        if state is None:
            return
        self.mux("kill", state["handle"])  # a dead handle is not an error
        events.append(self.root, "pane.reaped", bead=None, actor="driver", detail=state["handle"])
        with suppress(FileNotFoundError):
            os.remove(path)

    def reap(self) -> None:
        status = {b.get("id"): b.get("status") for b in beads(self.repo, ["bd", "list", "--all", "--json"])}
        waiting = self.state_files("waiting")
        opened = {r.get("bead") for r in events.read(self.root) if r.get("event") == "pr.opened"}
        for path in self.state_files() + waiting:
            state = self.read_state(path)
            if state is None or state["bead"] not in status:  # a file no tick can act on never wedges the loop
                self.event("worker.crashed", os.path.basename(path)[:-len(".json")], "unreadable")
                self.file_under(path, "crashed")
            elif self.mux("alive", state["handle"]).returncode != 0:  # 1 gone, 2 malformed: both are dead
                if status[state["bead"]] == "closed":
                    self.reaped(path, state)
                elif path in waiting:
                    pass  # already parked: the review lane moves it back when it asks for a fix round
                elif state["bead"] in opened or self.has_pr(state["bead"]):
                    self.file_under(path, "waiting")  # a round is done and its pull request is up: no event
                else:
                    self.crashed(path, state)

    def has_pr(self, bead: str) -> bool:
        """Did this worker open its pull request? The log knows only after step 2, GitHub knows now.

        A worker opens its pull request and exits seconds later, so on the tick that finds the pane
        dead the log has not named it yet; asking GitHub here is what keeps a finished round from
        being read as a crash. Every state is asked for, not only open: a pull request a human
        merged before the first tick is a finished round too, never a crash.
        """
        return any(pr["bead"] == bead for pr in self.all_prs())

    def reaped(self, path: str, state: dict) -> None:
        """A dead pane whose bead is closed: kill the window, return the worktree, file the run under done/."""
        self.mux("kill", state["handle"])
        tool(self.repo, ["treehouse", "return", "--force", state["worktree"]])
        self.event("pane.reaped", state["bead"], state["handle"])
        self.file_under(path, "done")

    def crashed(self, path: str, state: dict) -> None:
        """A dead pane whose bead is still open: one respawn, then escalate and leave the bead claimed."""
        self.event("worker.crashed", state["bead"], f"attempt {state['attempts']}")
        if state["attempts"] != 1:
            self.event("worker.crashed", state["bead"], "escalated")
            self.file_under(path, "crashed")
            return
        self.write_state({**state, "attempts": 2})  # before the respawn: a failed one escalates next tick
        self.spawn(state["bead"], state["worktree"], state["order"], attempts=2)

    def review_pending(self) -> None:
        """Contract section 9 step 2: name every new pull request, review every head with no verdict.

        The review itself runs as `smile review <n>`, a subprocess of the shim, so one PR that cannot
        be reviewed is one stderr line and the tick goes on to the next.
        """
        log = events.read(self.root)
        opened = {r.get("pr") for r in log if r.get("event") == "pr.opened"}
        judged = {(r.get("pr"), r.get("sha")) for r in log if r.get("event") == "review.verdict"}
        escalated = {(r.get("pr"), r.get("sha")) for r in log if r.get("event") == "watch.escalation"}
        for pr in self.open_prs():
            pair = (pr["number"], pr["headRefOid"])
            if pr["number"] not in opened:
                events.append(self.root, "pr.opened", bead=pr["bead"], pr=pr["number"],
                              sha=pr["headRefOid"], actor="driver")
            if pair in judged:
                continue
            if unanswered(log, *pair) >= CAP:  # a head three reviews could not judge is a human's problem
                if pair not in escalated:
                    events.append(self.root, "watch.escalation", bead=pr["bead"], pr=pr["number"],
                                  sha=pr["headRefOid"], actor="driver", detail="review failed 3 times")
                continue
            proc = self.smile("review", str(pr["number"]))
            if proc.returncode != 0:
                print(f"smile: review {pr['number']} failed: {stderr(proc)}", file=sys.stderr)
        self.close_merged(events.read(self.root))  # re-read: the reviews above merged and closed beads

    def close_merged(self, log: list) -> None:
        """A merged pull request whose bead is still open: close it now that GitHub says it landed.

        Whether the lane merged it or a human did, and whether or not it carries `smile:approved`,
        GitHub is the record of what landed; `smile audit` is what reports a merge no verdict approved.
        """
        closed = {r.get("bead") for r in log if r.get("event") == "bead.closed"}
        announced = {r.get("pr") for r in log if r.get("event") == "pr.merged"}
        for pr in github.factory_prs(self.repo, "merged", "number,body,mergeCommit"):
            if pr["bead"] in closed:
                continue
            tool(self.repo, ["bd", "close", pr["bead"]])
            if pr["number"] not in announced:  # the lane logs its own merges; this is the human's path
                events.append(self.root, "pr.merged", bead=pr["bead"], pr=pr["number"],
                              sha=(pr.get("mergeCommit") or {}).get("oid"), actor="human")
            events.append(self.root, "bead.closed", bead=pr["bead"], pr=pr["number"], actor="driver")

    def claim(self) -> None:
        live = len(self.live_files())
        for bead in beads(self.repo, ["bd", "ready", "--json"]):
            if live >= self.parallel:
                return
            bead_id = bead["id"]
            tool(self.repo, ["bd", "update", bead_id, "--claim"])
            self.event("bead.claimed", bead_id)
            live += self.start(bead_id)

    def start(self, bead_id: str) -> bool:
        """Everything after the claim. A bead that cannot start goes back to ready; the tick goes on.

        A full treehouse pool is the ordinary case here, not an error: the bead is claimed again next tick.
        """
        path = ""
        try:
            path = tool(self.repo, ["treehouse", "get", "--lease", "--lease-holder", bead_id]).strip()
            self.event("worktree.acquired", bead_id, path)
            record = beads(self.repo, ["bd", "show", bead_id, "--json"])[0]
            self.spawn(bead_id, path, self.write_order(record, bead_id), attempts=1, record=record)
        except Exception as e:  # noqa: BLE001  one bead's failure must not end the tick (contract section 8)
            print(f"smile: {bead_id} not started: {e}", file=sys.stderr)
            if path:
                self.let_go(["treehouse", "return", "--force", path])
            self.let_go(["bd", "update", bead_id, "--status", "open"])
            return False
        return True

    def let_go(self, argv: list) -> None:
        """Undo a claim step. A failure here has nowhere to go: the stderr line above already told the story."""
        subprocess.run(argv, cwd=self.repo, env=worktree.TOOL_ENV, capture_output=True, check=False)

    def write_order(self, record: dict, bead_id: str) -> str:
        """Render prompts/worker.md for this bead into .factory/orders/<bead>.md and return that path."""
        with open(f"{self.root}/prompts/worker.md", encoding="utf-8") as f:
            template = f.read()
        values = {"bead_id": bead_id, "bead_title": record.get("title", ""),
                  "bead_description": record.get("description", ""), "spec_path": worktree.spec_path(self.repo),
                  "base_branch": self.base_branch}
        order = f"{self.factory}/orders/{bead_id}.md"
        os.makedirs(os.path.dirname(order), exist_ok=True)
        with open(order, "w", encoding="utf-8") as f:
            f.write(worktree.render(template, values))
        return order

    def spawn(self, bead_id: str, path: str, order: str, attempts: int, record: dict | None = None) -> None:
        """Trust the worktree, open the pane through the seam, and record the run state."""
        if record is None:  # a respawn has no record in hand; a claim passes the one it already read
            record = beads(self.repo, ["bd", "show", bead_id, "--json"])[0]
        trust(path)
        proc = self.mux("spawn", bead_id, path, *self.pane(bead_id, record.get("title", ""), order))
        if proc.returncode != 0:
            raise RuntimeError(f"spawn failed for {bead_id}: {stderr(proc)}")
        handle = proc.stdout.decode().strip()
        stamp = now()  # one timestamp for both, so the run file and its pane.spawned can never disagree
        self.event("pane.spawned", bead_id, handle, ts=stamp)
        self.write_state({"bead": bead_id, "worktree": path, "handle": handle, "order": order,
                          "attempts": attempts, "spawned_at": stamp})

    def pane(self, bead_id: str, title: str, order: str) -> list:
        """The pane's argv. The four variables ride on it: a tmux window inherits the server's environment."""
        return ["env", f"SMILE_BEAD={bead_id}", f"SMILE_BEAD_TITLE={title}", f"SMILE_REPO={self.repo}",
                f"SMILE_BASE_BRANCH={self.base_branch}", *self.worker(order)]

    def worker(self, order: str) -> list:
        """The worker argv: SMILE_WORKER_CMD plus the order path, else claude with the order text."""
        override = os.environ.get("SMILE_WORKER_CMD")
        if override:
            return [*override.split(), order]
        with open(order, encoding="utf-8") as f:
            text = f.read()
        return ["claude", "--model", config.get(self.root, "worker.model"),
                "--permission-mode", config.get(self.root, "worker.permission_mode"), text]

    def complete(self) -> bool:
        if self.live_files() or any(b.get("status") in OPEN for b in beads(self.repo, ["bd", "list", "--json"])):
            return False
        self.reap_watchtower()  # the observer outlives every worker and dies just before the campaign
        events.append(self.root, "campaign.complete", actor="driver")
        return True


def singleton(factory: str) -> None:
    """Take .factory/driver.pid exclusively. A live pid in it means another driver owns this factory."""
    os.makedirs(factory, exist_ok=True)
    path = f"{factory}/driver.pid"
    if take(path):
        return
    pid = owner(path)
    if pid > 0 and alive(pid):
        raise RuntimeError(f"driver already running (pid {pid})")
    with suppress(FileNotFoundError):  # stale: the owner is gone, so the file is ours to replace
        os.remove(path)
    if not take(path):  # another driver took it in between; whoever holds it now is the live one
        raise RuntimeError(f"driver already running (pid {owner(path)})")


def owner(path: str) -> int:
    """The pid the file names; 0 when it is missing, empty, or not an integer."""
    try:
        with open(path, encoding="utf-8") as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return 0


def take(path: str) -> bool:
    """Create the pid file exclusively. False when it exists.

    The pid is written before the name appears: a link is atomic, where O_EXCL would leave a moment in
    which the file exists and is still empty, and a racing driver would read that as a stale pid.
    """
    tmp = f"{path}.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(f"{os.getpid()}\n")
    try:
        os.link(tmp, path)
    except FileExistsError:
        return False
    finally:
        os.remove(tmp)
    return True


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # somebody else's process, so not ours to overwrite
    return True


def parse(args: list) -> tuple:
    """(once, interval). Flags may repeat, the last wins; anything else is usage, exit 2."""
    once, interval, rest = False, 60, list(args)
    while rest:
        arg = rest.pop(0)
        if arg == "--once":
            once = True
        elif arg == "--interval" and rest and COUNT.fullmatch(rest[0]):
            interval = int(rest.pop(0))
        else:
            raise Usage(f"usage: smile run [--once] [--interval <seconds>], got {arg}")
    return once, interval


def stop(signum: int, frame: object) -> None:
    """SIGTERM reaches the driver as the interrupt SIGINT already is, so both leave through one path."""
    raise KeyboardInterrupt


def cmd_run(root: str, args: list) -> int:
    once, interval = parse(args)
    parallel = config.get(root, "max_parallel")
    if not COUNT.fullmatch(parallel):  # before the pid file: a misconfigured repo is touched not at all
        raise RuntimeError(f"bad max_parallel {parallel}")
    trust_file()  # a ~/.claude.json the driver could not write back is a failure before anything is touched
    driver = Driver(root, interval)
    singleton(driver.factory)
    signal.signal(signal.SIGTERM, stop)
    try:
        if not driver.live_files():  # a driver resuming over live runs joins the campaign, it does not start one
            events.append(root, "campaign.start", actor="driver", detail=str(interval))
        while not driver.tick():
            if once:
                return 0
            time.sleep(interval)
    except KeyboardInterrupt:
        print("smile: driver stopped", file=sys.stderr)
        return 1
    finally:
        with suppress(FileNotFoundError):
            os.remove(f"{driver.factory}/driver.pid")
    return 0
