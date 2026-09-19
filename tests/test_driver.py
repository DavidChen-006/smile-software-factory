"""S3 driver tests for the py runtime, driven through the stamped shim in scratch git repos.

bd and treehouse are real. The pane tool is a fake `tmux` first on PATH that records every argv line
and answers list-windows from a state file, so `smile mux` and backends/tmux.py run unchanged and a
pane can be declared dead per handle. One class at the end drives the real tmux, to prove the four
worker variables reach a pane that inherits the tmux server's environment, not the driver's.

HOME points at a scratch directory in every run, so the real ~/.claude.json and the real treehouse
pool are never touched.

Run from the repo root: uv run python -m unittest tests.test_driver -v
"""
import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from tests.test_core import TS, make_repo, set_config, smile, smile_inproc

SESSION = f"s3py-{os.getpid()}"
TEMPLATE = "order {{bead_id}} / {{bead_title}} / {{bead_description}} / {{spec_path}} / {{base_branch}}\n"
WORKER = "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$SMILE_STUB_LOG\"\nexit 0\n"
NO_PRS = "#!/bin/sh\nprintf '[]\\n'\n"  # a gh with no pull requests: the review step finds nothing to do
# the log path is baked into this one: a tmux pane inherits the server's environment, so under real
# tmux nothing but the argv reaches the worker, which is exactly what the test is checking.
ENV_WORKER = ("#!/bin/sh\nprintf 'BEAD=%s|TITLE=%s|REPO=%s|BRANCH=%s\\n' \"$SMILE_BEAD\" \"$SMILE_BEAD_TITLE\" "
              "\"$SMILE_REPO\" \"$SMILE_BASE_BRANCH\" >> '{log}'\nsleep 30\n")
FAKE_TMUX = '''#!/usr/bin/env python3
"""A tmux that opens no window: it records argv and fakes window state in a file the test can edit."""
import json, os, sys

argv = sys.argv[1:]
log, state = os.environ["FAKE_TMUX_LOG"], os.environ["FAKE_TMUX_STATE"]
with open(log, "a") as f:
    f.write(json.dumps({"argv": argv}) + "\\n")


def load():
    try:
        with open(state) as f:
            return json.load(f)
    except OSError:
        return {"counter": 0, "windows": {}}


def save(data):
    with open(state, "w") as f:
        json.dump(data, f)


def target(flag):
    return argv[argv.index(flag) + 1].lstrip("=")


verb = argv[0] if argv else ""
if verb in ("new-window", "new-session"):
    data = load()
    data["counter"] += 1
    key = "%s:@%d" % (target("-t" if verb == "new-window" else "-s"), data["counter"])
    data["windows"][key] = "0"
    save(data)
    print(key)
elif verb == "list-windows":
    session = target("-t")
    for key, dead in load()["windows"].items():
        name, _, window = key.rpartition(":")
        if name == session:
            print("%s %s" % (window, dead))
elif verb == "kill-window":
    data = load()
    data["windows"].pop(target("-t"), None)
    save(data)
elif verb != "set-option":
    sys.exit(1)
'''


def is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def parent_of(pid: int) -> int:
    """The pid's parent per `ps`; 0 when ps does not know it."""
    out = subprocess.run(["ps", "-o", "ppid=", "-p", str(pid)], capture_output=True, text=True,
                         check=False).stdout.strip()
    return int(out) if out.isdigit() else 0


def descends_from(pid: int, ancestor: int) -> bool:
    """Walk the parent chain: `uv run` puts one or more processes between the shim and the runtime."""
    for _ in range(16):
        pid = parent_of(pid)
        if pid == ancestor:
            return True
        if pid <= 1:
            return False
    return False


def write_exec(path: Path, text: str) -> str:
    path.write_text(text)
    path.chmod(0o755)
    return str(path)


def bd(repo: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bd", *args], cwd=repo, env={**os.environ, "BD_NON_INTERACTIVE": "1"},
                          capture_output=True, text=True, check=True)


def seed(repo: str, *titles: str) -> None:
    for title in titles:
        bd(repo, "create", title, "-d", f"do {title}", "--silent")


def bd_json(repo: str, *args: str) -> list:
    return json.loads(bd(repo, *args, "--json").stdout or "[]")


def pane_argv(call: dict) -> list:
    """What the window was told to run: everything after tmux's `--`."""
    argv = call["argv"]
    return argv[argv.index("--") + 1:]


def pane_env(call: dict) -> dict:
    """The four variables the argv's `env` prefix carries into the pane."""
    argv = pane_argv(call)
    return dict(word.split("=", 1) for word in argv[1:5])


class DriverCase(unittest.TestCase):
    """A stamped scratch repo with bd and treehouse initialised, a fake tmux, and a scratch HOME."""

    beads: tuple = ("alpha", "beta")

    def setUp(self) -> None:
        self.repo = make_repo("smile-drv", init=True)
        self.addCleanup(shutil.rmtree, os.path.dirname(self.repo), ignore_errors=True)
        set_config(self.repo, "watchtower", "off")  # S5's pane is test_watchtower's subject, not this suite's
        subprocess.run(["git", "-C", self.repo, "add", "-A"], check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["git", "-C", self.repo, "commit", "-qm", "stamp"], check=True, stdout=subprocess.DEVNULL)
        seed(self.repo, *self.beads)
        Path(self.repo, "prompts/worker.md").write_text(TEMPLATE)
        self.scratch = Path(tempfile.mkdtemp(prefix="smile-drv-env-"))
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.home = self.scratch / "home"
        self.home.mkdir()
        self.log, self.state = self.scratch / "tmux.log", self.scratch / "tmux.json"
        self.stub = self.scratch / "stub.log"
        self.bin = self.scratch / "bin"
        self.bin.mkdir()
        self.worker = write_exec(self.bin / "stub-worker", WORKER)
        write_exec(self.bin / "tmux", FAKE_TMUX)
        write_exec(self.bin / "gh", NO_PRS)
        self.env = {"HOME": str(self.home), "PATH": f"{self.bin}:{os.environ['PATH']}",
                    "FAKE_TMUX_LOG": str(self.log), "FAKE_TMUX_STATE": str(self.state),
                    "SMILE_MUX_SESSION": SESSION, "SMILE_STUB_LOG": str(self.stub),
                    "SMILE_WORKER_CMD": self.worker}

    # ------------------------------------------------------------ driving
    def run_driver(self, *args: str, **env: str) -> subprocess.CompletedProcess:
        # behaviour, not shim dispatch: in-process, so the test does not pay a `uv run` start per tick
        return smile_inproc(self.repo, "run", *args, env={**self.env, **env})

    def run_driver_shim(self, *args: str, **env: str) -> subprocess.CompletedProcess:
        return smile(self.repo, "run", *args, env={**self.env, **env})

    def popen(self, *args: str, repo: str = "", **env: str) -> subprocess.Popen:
        full = {**os.environ, **self.env, **env}
        return subprocess.Popen([f"{repo or self.repo}/smile/smile", "run", *args], cwd="/", env=full,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def tick(self, *args: str, **env: str) -> subprocess.CompletedProcess:
        r = self.run_driver("--once", *args, **env)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, b"", b""), r.stderr)
        return r

    def wait_for(self, predicate, what: str) -> None:
        for _ in range(200):
            if predicate():
                return
            time.sleep(0.1)
        self.fail(f"timed out waiting for {what}")

    # ------------------------------------------------------------ reading the world
    def events(self) -> list:
        path = Path(self.repo, ".factory/events.jsonl")
        records = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
        return [(r["event"], r["bead"], r["detail"]) for r in records]

    def calls(self) -> list:
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def spawns(self) -> list:
        return [c for c in self.calls() if c["argv"][0] in ("new-window", "new-session")]

    def filed(self, where: str) -> list:
        """The names under runs/<where>/; a filed run state need not parse."""
        d = Path(self.repo, ".factory/runs", where)
        return sorted(p.name for p in d.glob("*.json")) if d.is_dir() else []

    def runs(self, where: str = "") -> dict:
        d = Path(self.repo, ".factory/runs", where)
        return {p.name: json.loads(p.read_text()) for p in sorted(d.glob("*.json"))} if d.is_dir() else {}

    def pid_file(self) -> Path:
        return Path(self.repo, ".factory/driver.pid")

    def kill_window(self, handle: str) -> None:
        """Declare a pane dead: the fake tmux stops listing it, so `smile mux alive` exits 1."""
        data = json.loads(self.state.read_text())
        data["windows"].pop(handle.partition(":")[2], None)
        self.state.write_text(json.dumps(data))

    def one_run(self) -> dict:
        states = self.runs()
        self.assertEqual(len(states), 1, states)
        return next(iter(states.values()))


class ShimTest(DriverCase):
    """The two things the in-process tests do not cover: the shim's dispatch and `init` on a live repo."""

    beads = ()

    def test_init_on_an_initialised_repo(self) -> None:
        r = smile(self.repo, "init")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.decode(), "".join(f"exists {t}\n" for t in (
            ".beads", "treehouse.toml", ".worktreeinclude", ".factory", ".factory/events.jsonl")))

    def test_tick_through_the_shim(self) -> None:
        r = self.run_driver_shim("--once")
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, b"", b""), r.stderr)
        names = [e for e, _, _ in self.events()]  # dispatch only: the tick's own events are asserted in-process
        self.assertEqual((names[0], names[-1]), ("campaign.start", "campaign.complete"), names)


class SingletonTest(DriverCase):
    beads = ()

    def test_a_live_pid_refuses_the_second_driver(self) -> None:
        os.makedirs(Path(self.repo, ".factory"), exist_ok=True)
        self.pid_file().write_text(f"{os.getpid()}\n")
        r = self.run_driver("--once")
        self.assertEqual((r.returncode, r.stdout), (1, b""))
        self.assertEqual(r.stderr.decode(), f"smile: driver already running (pid {os.getpid()})\n")
        self.assertEqual(self.pid_file().read_text(), f"{os.getpid()}\n", "the pid file was overwritten")
        self.assertEqual(self.events(), [])

    def test_a_stale_pid_is_overwritten_and_the_file_is_removed_on_exit(self) -> None:
        dead = subprocess.Popen(["true"])
        dead.wait()
        self.pid_file().write_text(f"{dead.pid}\n")
        self.tick()
        self.assertFalse(self.pid_file().exists())
        self.assertEqual(self.events()[0], ("campaign.start", None, "60"))

    def test_a_garbage_or_negative_pid_file_is_stale(self) -> None:
        for content in ("not a pid\n", "-1\n", "0\n", ""):
            self.pid_file().write_text(content)
            self.tick()
            self.assertFalse(self.pid_file().exists(), content)


class ConcurrentTest(DriverCase):
    def test_a_second_driver_names_the_runtime_pid_the_file_holds(self) -> None:
        """driver.pid holds the runtime's own pid, which under `uv run` is a child of what we launched.

        Signalling the shim's pid kills uv; SIGKILL there orphans the runtime, so the file must name
        the process a caller has to signal, and the refusal must name what the file holds.
        """
        held = self.popen("--interval", "60")
        self.addCleanup(held.communicate)  # drains and closes the pipes, then waits
        self.addCleanup(held.terminate)
        self.wait_for(lambda: self.pid_file().read_text().strip().isdigit()
                      if self.pid_file().exists() else False, "the pid file")
        pid = int(self.pid_file().read_text().strip())
        r = self.run_driver("--once")
        self.assertEqual((r.returncode, r.stdout), (1, b""))
        self.assertEqual(r.stderr.decode(), f"smile: driver already running (pid {pid})\n")
        self.assertTrue(is_alive(pid), f"the file names pid {pid}, which is not running")
        self.assertTrue(descends_from(pid, held.pid),
                        f"pid {pid} is not a descendant of the launched process {held.pid}")

    def test_two_drivers_started_together_claim_each_bead_once(self) -> None:
        first, second = self.popen("--once"), self.popen("--once")
        results = [p.communicate(timeout=180) for p in (first, second)]
        codes = sorted(p.returncode for p in (first, second))
        self.assertIn(codes, ([0, 0], [0, 1]), results)  # [0, 0] only when the second started after the first ended
        for process, (out, err) in zip((first, second), results):
            self.assertEqual(out, b"")
            if process.returncode == 1:
                self.assertRegex(err.decode(), r"^smile: driver already running \(pid [0-9]+\)\n$")
        claimed = [bead for event, bead, _ in self.events() if event == "bead.claimed"]
        self.assertEqual(sorted(claimed), sorted({b["id"] for b in bd_json(self.repo, "list", "--all")}))
        self.assertEqual(len(self.runs()), 2)
        self.assertFalse(self.pid_file().exists())


class SignalTest(DriverCase):
    beads = ("alpha",)

    def test_sigterm_leaves_no_pid_file(self) -> None:
        driver = self.popen("--interval", "60")
        self.wait_for(lambda: len(self.runs()) == 1, "the first pane")
        self.wait_for(self.pid_file().exists, "the pid file")
        time.sleep(0.5)  # let the tick finish and the loop reach its sleep
        driver.send_signal(signal.SIGTERM)
        out, err = driver.communicate(timeout=60)
        self.assertEqual((driver.returncode, out), (1, b""))
        self.assertEqual(err, b"smile: driver stopped\n")
        self.assertFalse(self.pid_file().exists())


class UsageTest(DriverCase):
    beads = ()

    def test_bad_arguments_exit_2(self) -> None:
        for args in (("--twice",), ("--interval",), ("--interval", "x"), ("--interval", "0"),
                     ("--interval", "007"), ("--interval=5",), ("--interval", "-3"), ("extra",)):
            r = self.run_driver(*args)
            self.assertEqual((r.returncode, r.stdout), (2, b""), args)
            self.assertEqual(len(r.stderr.splitlines()), 1, r.stderr)
            self.assertNotIn(b"Traceback", r.stderr)
        self.assertEqual(self.events(), [])

    def test_the_interval_is_the_campaign_start_detail(self) -> None:
        self.tick("--interval", "7")
        self.assertEqual(self.events()[0], ("campaign.start", None, "7"))

    def test_a_repeated_flag_takes_the_last_value(self) -> None:
        self.tick("--interval", "7", "--once", "--interval", "9")
        self.assertEqual(self.events()[0], ("campaign.start", None, "9"))

    def test_a_bad_max_parallel_touches_nothing(self) -> None:
        set_config(self.repo, "max_parallel", "abc")
        r = self.run_driver("--once")
        self.assertEqual((r.returncode, r.stdout, r.stderr), (1, b"", b"smile: bad max_parallel abc\n"))
        self.assertEqual(self.events(), [])
        self.assertFalse(self.pid_file().exists())


class ClaimTest(DriverCase):
    def test_two_ready_beads_are_claimed_acquired_and_spawned(self) -> None:
        self.tick()
        ids = [b["id"] for b in bd_json(self.repo, "list", "--all")]
        self.assertEqual(len(ids), 2)
        per_bead = {}
        for event, bead, detail in self.events()[1:]:
            per_bead.setdefault(bead, []).append((event, detail))
        self.assertEqual(sorted(per_bead), sorted(ids))
        states = self.runs()
        self.assertEqual(sorted(states), sorted(f"{i}.json" for i in ids))
        for bead, seen in per_bead.items():
            state = states[f"{bead}.json"]
            self.assertEqual([e for e, _ in seen], ["bead.claimed", "worktree.acquired", "pane.spawned"])
            self.assertEqual([d for _, d in seen], [None, state["worktree"], state["handle"]])
            self.assertEqual(sorted(state), ["attempts", "bead", "handle", "order", "spawned_at", "worktree"])
            self.assertEqual((state["bead"], state["attempts"]), (bead, 1))
            self.assertRegex(state["spawned_at"], f"^{TS}$")
            self.assertTrue(state["handle"].startswith(f"tmux:{SESSION}:@"), state["handle"])
            self.assertTrue(os.path.isdir(state["worktree"]), state["worktree"])
        self.assertEqual(len(self.spawns()), 2)
        self.assertEqual({b["status"] for b in bd_json(self.repo, "list", "--all")}, {"in_progress"})

    def test_the_run_state_is_compact_sorted_json_with_a_trailing_newline(self) -> None:
        self.tick()
        files = sorted(Path(self.repo, ".factory/runs").glob("*.json"))
        self.assertEqual(len(files), 2)
        raw = files[0].read_bytes()
        self.assertTrue(raw.endswith(b"}\n"), raw)
        self.assertEqual(raw, json.dumps(json.loads(raw), sort_keys=True,
                                         separators=(",", ":")).encode() + b"\n")

    def test_the_work_order_has_every_placeholder_substituted(self) -> None:
        self.tick()
        states = self.runs()
        self.assertEqual(len(states), 2)
        for name, state in states.items():
            bead = name[: -len(".json")]
            title = next(b["title"] for b in bd_json(self.repo, "list", "--all") if b["id"] == bead)
            self.assertEqual(state["order"], f"{self.repo}/.factory/orders/{bead}.md")
            self.assertEqual(Path(state["order"]).read_text(),
                             f"order {bead} / {title} / do {title} /  / main\n")

    def test_the_spec_path_is_the_newest_doc_repo_relative(self) -> None:
        docs = Path(self.repo, "docs")
        docs.mkdir()
        Path(docs, "DESIGN.md").write_text("old\n")
        Path(docs, "PROJECT-SPEC.md").write_text("new\n")
        os.utime(docs / "DESIGN.md", (1, 1))
        self.tick()
        for state in self.runs().values():
            self.assertIn("/ docs/PROJECT-SPEC.md / main\n", Path(state["order"]).read_text())

    def test_the_four_variables_ride_on_the_pane_argv(self) -> None:
        self.tick()
        spawns = self.spawns()
        self.assertEqual(len(spawns), 2)
        for call in spawns:
            argv = pane_argv(call)
            env = pane_env(call)
            bead = env["SMILE_BEAD"]
            state = self.runs()[f"{bead}.json"]
            title = next(b["title"] for b in bd_json(self.repo, "list", "--all") if b["id"] == bead)
            self.assertEqual(argv[:5], ["env", f"SMILE_BEAD={bead}", f"SMILE_BEAD_TITLE={title}",
                                        f"SMILE_REPO={self.repo}", "SMILE_BASE_BRANCH=main"])
            self.assertEqual(argv[5:], [self.worker, state["order"]])
            self.assertEqual(call["argv"][call["argv"].index("-c") + 1], state["worktree"])

    def test_the_default_worker_command_is_claude_with_the_order_text(self) -> None:
        r = self.run_driver("--once", SMILE_WORKER_CMD="")
        self.assertEqual(r.returncode, 0, r.stderr)
        spawns = self.spawns()
        self.assertEqual(len(spawns), 2)
        for call in spawns:
            argv = pane_argv(call)
            order = self.runs()[f"{pane_env(call)['SMILE_BEAD']}.json"]["order"]
            self.assertEqual(argv[5:-1], ["claude", "--model", "opus", "--permission-mode", "acceptEdits"])
            self.assertEqual(argv[-1], Path(order).read_text())

    def test_the_worktree_is_trusted_and_other_keys_survive(self) -> None:
        claude_json = self.home / ".claude.json"
        original = {"numStartups": 7, "projects": {"/élsewhère": {"keep": True}}}
        claude_json.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")
        self.tick()
        data = json.loads(claude_json.read_text(encoding="utf-8"))
        self.assertEqual(data["numStartups"], 7)
        self.assertEqual(data["projects"]["/élsewhère"], {"keep": True})
        self.assertIn("/élsewhère".encode(), claude_json.read_bytes(), "a non-ASCII key was escaped")
        states = self.runs()
        self.assertEqual(len(states), 2)
        for state in states.values():
            self.assertEqual(data["projects"][state["worktree"]], {"hasTrustDialogAccepted": True})

    def test_a_missing_claude_json_is_created_with_only_the_trust_entry(self) -> None:
        self.tick()
        data = json.loads((self.home / ".claude.json").read_text())
        self.assertEqual(sorted(data), ["projects"])
        self.assertEqual(sorted(data["projects"]), sorted(s["worktree"] for s in self.runs().values()))

    def test_a_malformed_claude_json_stops_the_driver_before_anything_is_touched(self) -> None:
        for content in ("{not json", '"a string"', "[]"):
            (self.home / ".claude.json").write_text(content)
            r = self.run_driver("--once")
            self.assertEqual((r.returncode, r.stdout, r.stderr), (1, b"", b"smile: bad ~/.claude.json\n"), content)
            self.assertEqual((self.events(), self.runs()), ([], {}))
            self.assertFalse(self.pid_file().exists())
            self.assertEqual((self.home / ".claude.json").read_text(), content, "an unparsable file was written")
            self.assertEqual({b["status"] for b in bd_json(self.repo, "list", "--all")}, {"open"})

    def test_the_spawned_at_is_the_pane_spawned_timestamp(self) -> None:
        self.tick()
        log = [json.loads(line) for line in Path(self.repo, ".factory/events.jsonl").read_text().splitlines()]
        spawned = {r["bead"]: r["ts"] for r in log if r["event"] == "pane.spawned"}
        states = self.runs()
        self.assertEqual(len(states), 2)
        self.assertEqual({s["bead"]: s["spawned_at"] for s in states.values()}, spawned)

    def test_a_second_driver_over_live_runs_starts_no_campaign(self) -> None:
        self.tick()
        self.assertEqual([e for e, _, _ in self.events()].count("campaign.start"), 1)
        self.tick()
        self.assertEqual([e for e, _, _ in self.events()].count("campaign.start"), 1)


class PartialClaimTest(DriverCase):
    """A bead that cannot start goes back to ready and the tick carries on with the next one."""

    def test_a_full_pool_releases_that_bead_and_the_next_one_still_starts(self) -> None:
        real = shutil.which("treehouse")
        once = self.scratch / "get-failed"
        write_exec(self.bin / "treehouse", f'#!/bin/sh\nif [ "$1" = get ] && [ ! -f {once} ]; then\n'
                                           f'  : > {once}; echo "pool is full" >&2; exit 1\nfi\nexec {real} "$@"\n')
        r = self.run_driver("--once")
        self.assertEqual((r.returncode, r.stdout), (0, b""))
        self.assertEqual(len(r.stderr.splitlines()), 1, r.stderr)
        self.assertRegex(r.stderr.decode(), r"^smile: [a-z0-9-]+ not started: .*\n$")
        started = self.one_run()["bead"]
        released = next(b for b in bd_json(self.repo, "list", "--all") if b["id"] != started)
        self.assertEqual(released["status"], "open")
        self.assertIn(released["id"], [b["id"] for b in bd_json(self.repo, "ready")], "the bead is not ready again")
        self.assertEqual([e for e, _, _ in self.events()],
                         ["campaign.start", "bead.claimed", "bead.claimed", "worktree.acquired", "pane.spawned"])

    def test_a_failure_after_the_worktree_returns_it_and_releases_the_claim(self) -> None:
        os.remove(Path(self.repo, "prompts/worker.md"))  # the order cannot be written: fail after acquiring
        r = self.run_driver("--once")
        self.assertEqual((r.returncode, r.stdout), (0, b""))
        self.assertEqual(len(r.stderr.splitlines()), 2, r.stderr)  # one line per bead
        self.assertEqual((self.runs(), self.spawns()), ({}, []))
        self.assertEqual({b["status"] for b in bd_json(self.repo, "list", "--all")}, {"open"})
        acquired = [d for e, _, d in self.events() if e == "worktree.acquired"]
        self.assertEqual(len(acquired), 2)
        handed_back = subprocess.run(["treehouse", "get", "--lease", "--lease-holder", "check"], cwd=self.repo,
                                     env={**os.environ, **self.env}, capture_output=True, text=True, check=True)
        self.assertIn(handed_back.stdout.strip(), acquired, "the worktree was not returned")


class BdOutageTest(DriverCase):
    beads = ("alpha",)

    def test_a_failing_bd_list_aborts_the_tick_before_reap(self) -> None:
        self.tick()
        state = self.one_run()
        self.kill_window(state["handle"])
        real = shutil.which("bd")
        write_exec(self.bin / "bd", f'#!/bin/sh\n[ "$1" = list ] && {{ echo "bd is down" >&2; exit 1; }}\n'
                                    f'exec {real} "$@"\n')
        r = self.run_driver("--once")
        self.assertEqual((r.returncode, r.stdout), (1, b""))
        self.assertEqual(len(r.stderr.splitlines()), 1, r.stderr)
        self.assertNotIn("worker.crashed", [e for e, _, _ in self.events()])
        self.assertEqual(sorted(self.runs()), [f"{state['bead']}.json"])
        self.assertFalse(self.pid_file().exists())


class MaxParallelTest(DriverCase):
    def test_max_parallel_one_claims_one_bead_per_tick(self) -> None:
        set_config(self.repo, "max_parallel", "1")
        self.tick()
        self.assertEqual(len(self.runs()), 1)
        self.assertEqual([e for e, _, _ in self.events()[1:]], ["bead.claimed", "worktree.acquired", "pane.spawned"])
        self.tick()  # the first pane is still alive, so the cap holds
        self.assertEqual(len(self.runs()), 1)
        self.assertEqual(len(self.spawns()), 1)
        self.assertEqual(sorted(b["status"] for b in bd_json(self.repo, "list", "--all")), ["in_progress", "open"])


class PauseTest(DriverCase):
    def test_a_pause_file_skips_claims_and_appends_nothing(self) -> None:
        pause = smile(self.repo, "pause", env=self.env)
        self.assertEqual((pause.returncode, pause.stdout), (0, b"paused\n"), pause.stderr)
        before = self.events()
        self.tick()
        self.assertEqual(self.events(), [*before, ("campaign.start", None, "60")])
        self.assertEqual((self.runs(), self.spawns()), ({}, []))
        self.assertEqual({b["status"] for b in bd_json(self.repo, "list", "--all")}, {"open"})


class ReapTest(DriverCase):
    beads = ("alpha",)

    def test_a_closed_bead_with_a_dead_pane_is_reaped(self) -> None:
        self.tick()
        state = self.one_run()
        bd(self.repo, "close", state["bead"])
        self.kill_window(state["handle"])
        self.tick()
        self.assertEqual(self.events()[-2:], [("pane.reaped", state["bead"], state["handle"]),
                                              ("campaign.complete", None, None)])
        killed = [c["argv"] for c in self.calls() if c["argv"][0] == "kill-window"]
        self.assertEqual(killed, [["kill-window", "-t", f"={state['handle'].partition(':')[2]}"]])
        self.assertEqual(self.runs(), {})
        self.assertEqual(self.filed("done"), [f"{state['bead']}.json"])
        self.assertFalse(self.pid_file().exists())
        held = subprocess.run(["treehouse", "get", "--lease", "--lease-holder", "check"], cwd=self.repo,
                              env={**os.environ, **self.env}, capture_output=True, text=True, check=True)
        self.assertEqual(held.stdout.strip(), state["worktree"], "the worktree was not returned to the pool")

    def test_a_live_pane_is_not_reaped(self) -> None:
        self.tick()
        state = self.one_run()
        bd(self.repo, "close", state["bead"])
        self.tick()
        self.assertNotIn("pane.reaped", [e for e, _, _ in self.events()])
        self.assertEqual(sorted(self.runs()), [f"{state['bead']}.json"])


class BadRunFileTest(DriverCase):
    beads = ("alpha",)

    def unreadable(self, name: str, text: str) -> None:
        runs = Path(self.repo, ".factory/runs")
        runs.mkdir(parents=True, exist_ok=True)
        Path(runs, name).write_text(text)

    def test_a_corrupt_run_file_is_filed_and_the_tick_continues(self) -> None:
        self.unreadable("zz-junk.json", "{not json")
        self.tick()
        self.assertEqual(self.events()[0], ("worker.crashed", "zz-junk", "unreadable"))
        self.assertEqual(self.filed("crashed"), ["zz-junk.json"])
        self.assertEqual(len(self.runs()), 1, "the tick did not go on to claim")

    def test_a_run_file_naming_an_unknown_bead_is_filed(self) -> None:
        self.unreadable("zz-gone.json", json.dumps({"bead": "zz-gone", "worktree": "/tmp", "handle": "tmux:s:@9",
                                                    "order": "/tmp/o.md", "attempts": 1, "spawned_at": "x"}))
        self.tick()
        self.assertEqual(self.events()[0], ("worker.crashed", "zz-gone", "unreadable"))
        self.assertEqual(self.filed("crashed"), ["zz-gone.json"])
        self.assertEqual(len(self.runs()), 1)

    def test_a_run_file_missing_a_key_is_filed(self) -> None:
        self.unreadable("zz-short.json", json.dumps({"bead": "zz-short", "handle": "tmux:s:@9"}))
        self.tick()
        self.assertEqual(self.events()[0], ("worker.crashed", "zz-short", "unreadable"))
        self.assertEqual(self.filed("crashed"), ["zz-short.json"])


class CrashTest(DriverCase):
    beads = ("alpha",)

    def test_a_dead_pane_on_an_open_bead_respawns_once_then_escalates(self) -> None:
        self.tick()
        first = self.one_run()
        self.kill_window(first["handle"])
        self.tick()
        second = self.one_run()
        self.assertEqual(self.events()[-2:], [("worker.crashed", first["bead"], "attempt 1"),
                                              ("pane.spawned", first["bead"], second["handle"])])
        self.assertEqual(second["attempts"], 2)
        self.assertNotEqual(second["handle"], first["handle"])
        self.assertEqual((second["worktree"], second["order"]), (first["worktree"], first["order"]))
        self.assertEqual(len(self.spawns()), 2)

        self.kill_window(second["handle"])
        self.tick()
        self.assertEqual(self.events()[-2:], [("worker.crashed", first["bead"], "attempt 2"),
                                              ("worker.crashed", first["bead"], "escalated")])
        self.assertEqual((self.runs(), self.filed("crashed")), ({}, [f"{first['bead']}.json"]))
        self.assertEqual(len(self.spawns()), 2, "an escalated bead is not respawned")
        self.assertEqual([b["status"] for b in bd_json(self.repo, "list", "--all")], ["in_progress"])

    def test_a_failed_respawn_escalates_on_the_next_tick(self) -> None:
        self.tick()
        first = self.one_run()
        self.kill_window(first["handle"])
        shutil.rmtree(first["worktree"])  # mux spawn refuses a cwd that is not a directory
        r = self.run_driver("--once")
        self.assertEqual((r.returncode, r.stdout), (1, b""))
        self.assertEqual(len(r.stderr.splitlines()), 1, r.stderr)
        self.assertEqual(self.one_run()["attempts"], 2, "the attempt was not recorded before the respawn")
        self.assertEqual(self.events()[-1], ("worker.crashed", first["bead"], "attempt 1"))
        self.tick()
        self.assertEqual(self.events()[-2:], [("worker.crashed", first["bead"], "attempt 2"),
                                              ("worker.crashed", first["bead"], "escalated")])
        self.assertEqual(self.filed("crashed"), [f"{first['bead']}.json"])


class WaitingTest(DriverCase):
    """A worker that finished a round and opened its pull request is waiting, not crashed."""

    beads = ("alpha",)

    def park(self) -> dict:
        """One claimed bead whose worker opened a pull request and whose pane then exited."""
        self.tick()
        state = self.one_run()
        r = smile(self.repo, "event", "pr.opened", f"bead={state['bead']}", "pr=4",
                  "actor=worker", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.kill_window(state["handle"])
        return state

    def test_a_dead_pane_with_a_pull_request_parks_silently_and_keeps_its_worktree(self) -> None:
        state = self.park()
        before = self.events()
        self.tick()
        self.assertEqual(self.events(), before, "parking a run logged something")
        self.assertEqual((self.runs(), self.filed("waiting")), ({}, [f"{state['bead']}.json"]))
        self.assertEqual(self.runs("waiting")[f"{state['bead']}.json"], state, "the run state changed")
        self.assertEqual([c["argv"] for c in self.calls() if c["argv"][0] == "kill-window"], [])
        held = subprocess.run(["treehouse", "get", "--lease", "--lease-holder", "check"], cwd=self.repo,
                              env={**os.environ, **self.env}, capture_output=True, text=True, check=True)
        self.assertNotEqual(held.stdout.strip(), state["worktree"], "the lease was given up")

    def test_a_parked_run_is_not_crashed_and_is_not_respawned(self) -> None:
        self.park()
        self.tick()
        self.tick()
        self.assertNotIn("worker.crashed", [e for e, _, _ in self.events()])
        self.assertEqual(len(self.spawns()), 1, "a waiting run was respawned")
        self.assertEqual(self.filed("crashed"), [])

    def test_a_dead_pane_with_no_pull_request_still_crashes(self) -> None:
        self.tick()
        state = self.one_run()
        self.kill_window(state["handle"])
        self.tick()
        self.assertEqual(self.events()[-2:], [("worker.crashed", state["bead"], "attempt 1"),
                                              ("pane.spawned", state["bead"], self.one_run()["handle"])])
        self.assertEqual(self.filed("waiting"), [])

    def test_a_parked_run_whose_bead_closes_is_reaped(self) -> None:
        state = self.park()
        self.tick()
        self.assertEqual(self.filed("waiting"), [f"{state['bead']}.json"])
        bd(self.repo, "close", state["bead"])
        self.tick()
        self.assertEqual(self.events()[-2:], [("pane.reaped", state["bead"], state["handle"]),
                                              ("campaign.complete", None, None)])
        self.assertEqual((self.filed("waiting"), self.filed("done")), ([], [f"{state['bead']}.json"]))
        held = subprocess.run(["treehouse", "get", "--lease", "--lease-holder", "check"], cwd=self.repo,
                              env={**os.environ, **self.env}, capture_output=True, text=True, check=True)
        self.assertEqual(held.stdout.strip(), state["worktree"], "the worktree was not returned")

    def test_a_waiting_run_keeps_the_campaign_running_and_counts_against_max_parallel(self) -> None:
        self.park()
        set_config(self.repo, "max_parallel", "1")
        seed(self.repo, "gamma")
        self.tick()
        self.assertNotIn("campaign.complete", [e for e, _, _ in self.events()])
        self.assertEqual(self.runs(), {}, "the cap ignored the waiting run")
        self.assertEqual(len(self.spawns()), 1)
        self.assertEqual([b["status"] for b in bd_json(self.repo, "list", "--all") if b["title"] == "gamma"],
                         ["open"])


class CompleteTest(DriverCase):
    beads = ()

    def test_no_open_bead_and_no_live_run_completes(self) -> None:
        self.tick()
        self.assertEqual(self.events(), [("campaign.start", None, "60"), ("campaign.complete", None, None)])
        self.assertFalse(self.pid_file().exists())

    def test_an_open_bead_keeps_the_campaign_running(self) -> None:
        seed(self.repo, "alpha")
        smile(self.repo, "pause", env=self.env)  # claim nothing, so only the open bead decides
        self.tick()
        self.assertEqual([e for e, _, _ in self.events()], ["driver.paused", "campaign.start"])


class LinkedWorktreeTest(DriverCase):
    beads = ("alpha",)

    def linked(self) -> str:
        path = os.path.join(os.path.dirname(self.repo), "linked")
        subprocess.run(["git", "-C", self.repo, "worktree", "add", "-q", path], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return path

    def test_event_and_status_from_a_linked_worktree_use_the_main_factory(self) -> None:
        linked = self.linked()
        r = smile(linked, "event", "bead.claimed", "bead=sv-9", "actor=driver", "detail=from a worktree")
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, b"", b""))
        self.assertFalse(Path(linked, ".factory").exists(), "the worktree wrote its own factory")
        self.assertIn(("bead.claimed", "sv-9", "from a worktree"), self.events())
        for repo in (self.repo, linked):
            status = smile(repo, "status")
            self.assertEqual(status.returncode, 0, status.stderr)
            self.assertIn(b" bead.claimed sv-9 - from a worktree\n", status.stdout)
        pause = smile(linked, "pause")
        self.assertEqual((pause.returncode, pause.stdout), (0, b"paused\n"), pause.stderr)
        self.assertTrue(Path(self.repo, ".factory/pause").exists())
        self.assertEqual(smile(linked, "resume").stdout, b"resumed\n")
        self.assertFalse(Path(self.repo, ".factory/pause").exists())

    def test_a_driver_in_a_linked_worktree_drives_the_main_factory_and_one_pool(self) -> None:
        linked = self.linked()
        r = smile(linked, "run", "--once", env=self.env)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, b"", b""), r.stderr)
        self.assertFalse(Path(linked, ".factory").exists(), "the worktree wrote its own factory")
        state = self.one_run()
        self.assertEqual([e for e, _, _ in self.events()],
                         ["campaign.start", "bead.claimed", "worktree.acquired", "pane.spawned"])
        self.assertEqual(pane_env(self.spawns()[0])["SMILE_REPO"], self.repo)
        self.assertTrue(state["worktree"].startswith(str(self.home / ".treehouse")), state["worktree"])
        pools = sorted(p.name for p in (self.home / ".treehouse").iterdir() if p.is_dir())
        self.assertEqual(len(pools), 1, pools)


@unittest.skipUnless(shutil.which("tmux"), "tmux not on PATH")
class RealTmuxTest(DriverCase):
    """The one test that opens real windows: a tmux pane inherits the server's environment, not ours."""

    def setUp(self) -> None:
        super().setUp()
        os.remove(self.bin / "tmux")  # the real one, so the four variables must travel on the argv
        self.session = f"s3py-real-{os.getpid()}"
        self.env["SMILE_MUX_SESSION"] = self.session
        self.env["SMILE_WORKER_CMD"] = write_exec(self.bin / "env-worker", ENV_WORKER.format(log=self.stub))
        self.addCleanup(subprocess.run, ["tmux", "kill-session", "-t", f"={self.session}"],
                        capture_output=True, check=False)

    def test_each_pane_reads_its_own_bead(self) -> None:
        self.tick()
        states = self.runs()
        self.assertEqual(len(states), 2)
        self.wait_for(lambda: self.stub.exists() and len(self.stub.read_text().splitlines()) == 2, "both workers")
        lines = sorted(self.stub.read_text().splitlines())
        expected = sorted(f"BEAD={b['id']}|TITLE={b['title']}|REPO={self.repo}|BRANCH=main"
                          for b in bd_json(self.repo, "list", "--all"))
        self.assertEqual(lines, expected)
        for state in states.values():
            self.assertEqual(subprocess.run([f"{self.repo}/smile/smile", "mux", "alive", state["handle"]],
                                            env={**os.environ, **self.env}, capture_output=True,
                                            check=False).returncode, 0)


if __name__ == "__main__":
    unittest.main()
