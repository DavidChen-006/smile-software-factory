"""S5 watchtower tests for the py runtime, driven through the stamped shim in scratch git repos.

The pane tool is the fake `tmux` of the driver tests, so a watchtower window can be declared dead
per handle without opening anything. `gh` answers with no pull requests, bd is real, and no bead is
ever claimed here: the watchtower is spawned by the tick whether or not any bead moves, which is
what these tests hold it to. The stub watchtower of the verification harness is driven directly
against a scratch factory directory, with no pane at all.

Run from the repo root: uv run python -m unittest tests.test_watchtower -v
"""

import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from tests.test_core import make_repo, set_config, smile
from tests.test_driver import FAKE_TMUX, NO_PRS, bd, write_exec

SESSION = f"s5py-{os.getpid()}"
TEMPLATE = "watch {{spec_path}} / {{base_branch}} / {{repo}}\n"
STUB = Path(__file__).resolve().parent.parent / ".claude/skills/verify-smile/scripts/stub-watchtower"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def log_events(repo: str) -> list:
    path = Path(repo, ".factory/events.jsonl")
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


class WatchtowerTest(unittest.TestCase):
    """One stamped repo for the class; every test starts from a fresh .factory and a fresh fake world."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.repo = make_repo("smile-watch")
        Path(cls.repo, "prompts/watchtower.md").write_text(TEMPLATE)
        smile(cls.repo, "init")  # one bd database for the class; each test starts from a fresh .factory
        cls.bead = bd(cls.repo, "create", "keep the campaign open", "-d", "open",
                      "--silent").stdout.strip()
        cls.home = tempfile.mkdtemp(prefix="smile-watch-home-")
        cls.bin = tempfile.mkdtemp(prefix="smile-watch-bin-")
        write_exec(Path(cls.bin, "tmux"), FAKE_TMUX)
        write_exec(Path(cls.bin, "gh"), NO_PRS)
        cls.tmux_log = Path(cls.bin, "tmux.log")
        cls.tmux_state = Path(cls.bin, "tmux.state")

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(os.path.dirname(cls.repo), ignore_errors=True)
        shutil.rmtree(cls.home, ignore_errors=True)
        shutil.rmtree(cls.bin, ignore_errors=True)

    def setUp(self) -> None:
        shutil.rmtree(Path(self.repo, ".factory"), ignore_errors=True)
        set_config(self.repo, "watchtower", "on")
        self.tmux_log.write_text("")
        self.tmux_state.write_text(json.dumps({"counter": 0, "windows": {}}))

    def env(self, **extra: str) -> dict:
        return {"HOME": self.home, "PATH": f"{self.bin}:{os.environ['PATH']}",
                "FAKE_TMUX_LOG": str(self.tmux_log), "FAKE_TMUX_STATE": str(self.tmux_state),
                "SMILE_MUX_SESSION": SESSION, **extra}

    def tick(self, **extra: str) -> subprocess.CompletedProcess:
        return smile(self.repo, "run", "--once", env=self.env(**extra))

    def spawn_calls(self) -> list:
        """Every fake-tmux call that opened a window, as argv lists."""
        calls = [json.loads(line)["argv"] for line in self.tmux_log.read_text().splitlines()]
        return [c for c in calls if c and c[0] in ("new-window", "new-session")]

    def pane_argv(self, call: list) -> list:
        return call[call.index("--") + 1:]

    def keep_open(self) -> None:
        """The class bead stays open, so the tick never completes and never reaps the watchtower."""
        bd(self.repo, "update", self.bead, "--status", "open")
        Path(self.repo, ".factory").mkdir(exist_ok=True)
        Path(self.repo, ".factory/pause").write_text("")  # no claim, so no treehouse and no worker

    # ---------------------------------------------------------------- spawn
    def test_spawn_after_campaign_start(self) -> None:
        self.keep_open()
        self.tick()
        names = [(e["event"], e["bead"], e["actor"]) for e in log_events(self.repo)]
        self.assertIn(("campaign.start", None, "driver"), names)
        spawned = [e for e in log_events(self.repo) if e["event"] == "pane.spawned"]
        self.assertEqual(len(spawned), 1)
        self.assertIsNone(spawned[0]["bead"])
        self.assertEqual(spawned[0]["actor"], "driver")
        state = read_json(Path(self.repo, ".factory/watchtower.json"))
        self.assertEqual(sorted(state), ["handle", "spawned_at"])
        self.assertEqual(state["handle"], spawned[0]["detail"])
        self.assertEqual(state["spawned_at"], spawned[0]["ts"])
        order = Path(self.repo, ".factory/orders/watchtower.md").read_text()
        self.assertEqual(order, f"watch  / main / {self.repo}\n")

    def test_off_spawns_nothing(self) -> None:
        set_config(self.repo, "watchtower", "off")
        self.keep_open()
        self.tick()
        self.assertEqual([e for e in log_events(self.repo) if e["event"] == "pane.spawned"], [])
        self.assertFalse(Path(self.repo, ".factory/watchtower.json").exists())
        self.assertEqual(self.spawn_calls(), [])

    def test_respawn_when_handle_is_dead(self) -> None:
        self.keep_open()
        self.tick()
        first = read_json(Path(self.repo, ".factory/watchtower.json"))["handle"]
        self.tick()  # still alive: no second spawn
        self.assertEqual(len([e for e in log_events(self.repo) if e["event"] == "pane.spawned"]), 1)
        self.tmux_state.write_text(json.dumps({"counter": 1, "windows": {}}))  # the window is gone
        self.tick()
        spawned = [e for e in log_events(self.repo) if e["event"] == "pane.spawned"]
        self.assertEqual(len(spawned), 2)
        self.assertNotEqual(spawned[1]["detail"], first)
        self.assertEqual(read_json(Path(self.repo, ".factory/watchtower.json"))["handle"],
                         spawned[1]["detail"])

    def test_reaped_before_campaign_complete(self) -> None:
        bd(self.repo, "close", self.bead)  # no open bead: one tick spawns the watchtower and completes
        self.addCleanup(bd, self.repo, "update", self.bead, "--status", "open")
        self.tick()
        events = [(e["event"], e["bead"]) for e in log_events(self.repo)]
        self.assertEqual(events[-2:], [("pane.reaped", None), ("campaign.complete", None)])
        self.assertFalse(Path(self.repo, ".factory/watchtower.json").exists())
        killed = [json.loads(line)["argv"] for line in self.tmux_log.read_text().splitlines()]
        self.assertTrue(any(c and c[0] == "kill-window" for c in killed))

    def test_command_override_takes_the_order_path_last(self) -> None:
        self.keep_open()
        self.tick(SMILE_WATCHTOWER_CMD="/bin/sh -c true")
        argv = self.pane_argv(self.spawn_calls()[0])
        self.assertEqual(argv, ["env", f"SMILE_REPO={self.repo}", "SMILE_BASE_BRANCH=main",
                                "SMILE_ACTOR=watchtower", "/bin/sh", "-c", "true",
                                f"{self.repo}/.factory/orders/watchtower.md"])

    def test_default_command_is_claude_with_the_order_text(self) -> None:
        self.keep_open()
        self.tick()
        argv = self.pane_argv(self.spawn_calls()[0])
        self.assertEqual(argv[4:8], ["claude", "--model", "opus", "--permission-mode"])
        self.assertEqual(argv[8], "plan")
        self.assertEqual(argv[9], f"watch  / main / {self.repo}\n")


class StubWatchtowerTest(unittest.TestCase):
    """The verification harness's stub, driven straight against a scratch factory: no pane, no driver."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.repo = make_repo("smile-stub-watch")

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(os.path.dirname(cls.repo), ignore_errors=True)

    def test_escalates_and_pauses_once_per_bead(self) -> None:
        factory = Path(self.repo, ".factory")
        factory.mkdir(exist_ok=True)
        log = factory / "events.jsonl"
        log.write_text(json.dumps({"ts": "T0", "event": "campaign.start", "bead": None,
                                   "detail": "60"}) + "\n")
        proc = subprocess.Popen([str(STUB), str(factory / "orders/watchtower.md")], cwd=self.repo,
                                env={**os.environ, "SMILE_REPO": self.repo, "SMILE_ACTOR": "watchtower"},
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        watch = factory / "watch.md"
        try:
            for _ in range(200):  # watch.md appearing means the stub has marked the end of the log
                if watch.exists():
                    break
                time.sleep(0.1)
            with log.open("a") as f:  # the tail starts at the end of the file, so this is the first line seen
                for record in ({"ts": "T1", "event": "worker.crashed", "bead": "b1", "detail": "attempt 2"},
                               {"ts": "T2", "event": "worker.crashed", "bead": "b1", "detail": "escalated"},
                               {"ts": "T3", "event": "worker.crashed", "bead": "b1", "detail": "escalated"}):
                    f.write(json.dumps(record) + "\n")
            for _ in range(200):
                if (factory / "pause").exists() and "T3" in (watch.read_text() if watch.exists() else ""):
                    break
                time.sleep(0.1)
        finally:
            proc.terminate()
            proc.wait(timeout=10)
        lines = (factory / "watch.md").read_text().splitlines()
        self.assertEqual(lines[:3], ["T1 worker.crashed b1 attempt 2", "T2 worker.crashed b1 escalated",
                                     "T3 worker.crashed b1 escalated"])
        self.assertNotIn("T0 campaign.start - 60", lines)  # the line already in the log is not this watch's
        self.assertTrue((factory / "pause").exists())
        events = [e for e in log_events(self.repo) if e["event"] in ("watch.escalation", "driver.paused")]
        self.assertEqual([(e["event"], e["bead"], e["actor"], e["detail"]) for e in events],
                         [("watch.escalation", "b1", "watchtower", "crashed twice"),
                          ("driver.paused", None, "watchtower", None)])


if __name__ == "__main__":
    unittest.main()
