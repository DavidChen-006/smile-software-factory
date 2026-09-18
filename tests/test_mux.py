"""S2 mux seam tests for the py runtime, driven through the stamped shim against a real tmux server.

Every window lives in one dedicated session, smile-test-<pid>, killed in tearDownClass.
Run from the repo root: python3 -m unittest tests.test_mux -v
"""
from __future__ import annotations  # PEP 604 unions in annotations on the 3.9 floor

import os
import re
import shutil
import subprocess
import time
import unittest
from concurrent.futures import ThreadPoolExecutor

from tests.test_core import bin_dir, make_repo, set_config, smile

SESSION = f"smile-test-{os.getpid()}"


def tmux(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", *args], capture_output=True, text=True, check=False)


def wait_gone(case: unittest.TestCase, repo: str, handle: str) -> None:
    """Poll alive for up to five seconds; a command that has exited takes a moment to leave tmux."""
    for _ in range(50):
        r = mux(repo, "alive", handle)
        if r.returncode != 0:
            case.assertEqual((r.returncode, r.stdout, r.stderr), (1, b"", b""))
            return
        time.sleep(0.1)
    case.fail(f"{handle} still alive")


def mux(repo: str, *args: str, session: str = SESSION) -> subprocess.CompletedProcess:
    return smile(repo, "mux", *args, env={"SMILE_MUX_SESSION": session})


def kill_session(session: str) -> None:
    tmux("kill-session", "-t", "=" + re.sub(r"[.:\s]", "_", session))


@unittest.skipUnless(shutil.which("tmux"), "tmux not on PATH")
class MuxCase(unittest.TestCase):
    repo: str

    @classmethod
    def setUpClass(cls) -> None:
        cls.repo = make_repo("smile-mux")
        cls.addClassCleanup(shutil.rmtree, os.path.dirname(cls.repo), ignore_errors=True)
        cls.addClassCleanup(kill_session, SESSION)

    def spawn(self, *args: str) -> str:
        r = mux(self.repo, "spawn", *args)
        self.assertEqual((r.returncode, r.stderr), (0, b""), r.stderr)
        handle = r.stdout.decode()
        self.assertTrue(handle.endswith("\n"), handle)
        handle = handle[:-1]
        self.addCleanup(mux, self.repo, "kill", handle)
        return handle


class SpawnTest(MuxCase):
    def test_handle_names_a_window_with_the_given_name_and_cwd(self) -> None:
        handle = self.spawn("worker-a", "/usr", "sleep", "300")
        backend, _, rest = handle.partition(":")
        session, _, window = rest.rpartition(":")
        self.assertEqual((backend, session), ("tmux", SESSION))
        self.assertRegex(window, r"^@\d+$")
        target = f"={session}:{window}"
        self.assertEqual(tmux("display", "-p", "-t", target, "#{window_name}").stdout.strip(), "worker-a")
        self.assertEqual(tmux("display", "-p", "-t", target, "#{pane_current_path}").stdout.strip(), "/usr")
        self.assertEqual(tmux("display", "-p", "-t", target, "#{?remain_on_exit,on,off}").stdout.strip(), "off")

    def test_argument_with_a_space_reaches_the_command_intact(self) -> None:
        out = os.path.join(self.repo, "out.txt")
        self.spawn("writer", self.repo, "sh", "-c", 'printf "%s" "$1" > out.txt', "_", "a b")
        for _ in range(50):
            if os.path.exists(out):
                break
            time.sleep(0.1)
        with open(out, encoding="utf-8") as f:
            self.assertEqual(f.read(), "a b")

    def test_a_lone_command_word_is_not_handed_to_a_shell(self) -> None:
        handle = self.spawn("lone", "/tmp", "true")  # tmux would give a single word to sh -c
        wait_gone(self, self.repo, handle)

    def test_a_lone_word_with_a_space_is_a_program_that_does_not_exist(self) -> None:
        handle = self.spawn("lone-space", "/tmp", "true; touch /tmp/smile-mux-should-not-exist")
        wait_gone(self, self.repo, handle)
        self.assertFalse(os.path.exists("/tmp/smile-mux-should-not-exist"), "the command went through a shell")

    def test_missing_cwd_exits_1(self) -> None:
        r = mux(self.repo, "spawn", "nope", f"{self.repo}/no-such-dir", "true")
        self.assertEqual((r.returncode, r.stdout), (1, b""))
        self.assertEqual(len(r.stderr.splitlines()), 1, r.stderr)


class AliveKillTest(MuxCase):
    def test_alive_while_running_and_not_after_kill(self) -> None:
        handle = self.spawn("sleeper", "/tmp", "sleep", "300")
        self.assertEqual(mux(self.repo, "alive", handle).returncode, 0)
        for _ in range(2):  # kill is idempotent: already gone is the same end state
            r = mux(self.repo, "kill", handle)
            self.assertEqual((r.returncode, r.stdout, r.stderr), (0, b"", b""))
        self.assertEqual(mux(self.repo, "alive", handle).returncode, 1)

    def test_alive_is_1_after_the_command_exits(self) -> None:
        handle = self.spawn("quick", "/tmp", "true")
        wait_gone(self, self.repo, handle)

    def test_alive_and_kill_print_nothing(self) -> None:
        handle = self.spawn("quiet", "/tmp", "sleep", "300")
        for verb in ("alive", "kill"):
            r = mux(self.repo, verb, handle)
            self.assertEqual((r.stdout, r.stderr), (b"", b""), verb)


class DottedSessionTest(MuxCase):
    """tmux rewrites `.` to `_` in a session name, so a handle built from the asked name resolves nothing."""

    def test_a_dotted_session_resolves_through_the_reported_name(self) -> None:
        asked = f"s2py.dot.{os.getpid()}"
        self.addCleanup(kill_session, asked)
        handles = []
        for window in ("dot-a", "dot-b"):  # the second one goes through new-window, not new-session
            r = mux(self.repo, "spawn", window, "/tmp", "sleep", "300", session=asked)
            self.assertEqual((r.returncode, r.stderr), (0, b""), r.stderr)
            handles.append(r.stdout.decode().strip())
        for handle in handles:
            self.assertIn("s2py_dot", handle)
            self.assertEqual(mux(self.repo, "alive", handle, session=asked).returncode, 0, handle)
            self.assertEqual(mux(self.repo, "kill", handle, session=asked).returncode, 0, handle)
            self.assertEqual(mux(self.repo, "alive", handle, session=asked).returncode, 1, handle)


class SpacedSessionTest(MuxCase):
    def test_a_session_name_with_a_space_resolves_and_keeps_the_handle_one_word(self) -> None:
        asked = f"s2py space {os.getpid()}"
        self.addCleanup(kill_session, asked)
        r = mux(self.repo, "spawn", "spaced", "/tmp", "sleep", "300", session=asked)
        self.assertEqual((r.returncode, r.stderr), (0, b""), r.stderr)
        handle = r.stdout.decode().strip()
        self.assertIn(f"s2py_space_{os.getpid()}", handle)
        self.assertEqual(handle.split(), [handle])
        self.assertEqual(mux(self.repo, "alive", handle, session=asked).returncode, 0)
        self.assertEqual(mux(self.repo, "kill", handle, session=asked).returncode, 0)
        self.assertEqual(mux(self.repo, "alive", handle, session=asked).returncode, 1)


class RaceTest(MuxCase):
    def test_ten_concurrent_spawns_into_a_fresh_session(self) -> None:
        fresh = f"{SESSION}-race"
        self.addCleanup(kill_session, fresh)
        with ThreadPoolExecutor(max_workers=10) as pool:
            runs = list(pool.map(lambda i: mux(self.repo, "spawn", f"r{i}", "/tmp", "sleep", "300", session=fresh),
                                 range(10)))
        for r in runs:
            self.assertEqual((r.returncode, r.stderr), (0, b""), r.stderr)
        handles = {r.stdout.decode().strip() for r in runs}
        self.assertEqual(len(handles), 10, handles)
        listed = tmux("list-windows", "-t", f"={fresh}", "-F", "#{window_id}").stdout.split()
        self.assertEqual(len(listed), 10, listed)


class HandleTest(MuxCase):
    def control(self) -> str:
        """A live window in the test session that a malformed handle must not touch."""
        handle = self.spawn("control", "/tmp", "sleep", "300")
        self.assertEqual(mux(self.repo, "alive", handle).returncode, 0)
        return handle

    def test_malformed_and_unknown_backends_exit_2(self) -> None:
        control = self.control()
        window = control.rpartition(":")[2]
        for handle in ("nope", "tmux:", ":x", "cmux:x:y", "herdr:x", "tmux:a b", "tmux:x",
                       f"tmux:{SESSION}:", f"tmux:{SESSION}:byname", f"tmux:{SESSION}:control",
                       f"tmux:{SESSION}:{window[1:]}", f"tmux::{window}",
                       "../lib/config:x:@1", "TMUX:a:@1", "backends.tmux:a:@1"):
            for verb in ("alive", "kill"):
                r = mux(self.repo, verb, handle)
                self.assertEqual((r.returncode, r.stdout), (2, b""), f"{verb} {handle}")
                self.assertEqual(len(r.stderr.splitlines()), 1, r.stderr)
                self.assertNotIn(b"Traceback", r.stderr)
                if handle.count(":") == 2 and not handle.startswith("tmux:"):
                    self.assertIn(b"unknown backend", r.stderr, handle)
        self.assertEqual(mux(self.repo, "alive", control).returncode, 0, "a malformed handle touched a live window")

    def test_alive_of_a_gone_window_in_a_gone_session_exits_1(self) -> None:
        self.assertEqual(mux(self.repo, "alive", f"tmux:{SESSION}-absent:@99").returncode, 1)


class UsageTest(MuxCase):
    def test_usage_errors_exit_2(self) -> None:
        for args in ([], ["nosuch"], ["spawn"], ["spawn", "n"], ["spawn", "n", "/tmp"],
                     ["alive"], ["alive", "a", "b"], ["kill"], ["kill", "a", "b"]):
            r = mux(self.repo, *args)
            self.assertEqual((r.returncode, r.stdout), (2, b""), args)
            self.assertEqual(len(r.stderr.splitlines()), 1, r.stderr)


class BackendSelectionTest(MuxCase):
    def tearDown(self) -> None:
        set_config(self.repo, "backend", "")

    def test_auto_detect_picks_tmux_when_backend_is_empty(self) -> None:
        set_config(self.repo, "backend", "")
        self.assertTrue(self.spawn("auto", "/tmp", "sleep", "300").startswith("tmux:"))

    def test_config_naming_a_backend_without_a_file_exits_2(self) -> None:
        for backend in ("screen", "cmux", "herdr"):
            set_config(self.repo, "backend", backend)
            r = mux(self.repo, "spawn", "n", "/tmp", "true")
            self.assertEqual((r.returncode, r.stdout), (2, b""), backend)
            self.assertEqual(r.stderr.decode().strip(), f"smile: unknown backend {backend}")

    def test_alive_and_kill_without_tmux_exit_1(self) -> None:
        d = bin_dir(())  # what the shim needs, and no pane tool at all
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        handle = f"tmux:{SESSION}:@0"
        env = {"PATH": d, "SMILE_MUX_SESSION": SESSION}
        alive = smile(self.repo, "mux", "alive", handle, env=env)
        self.assertEqual((alive.returncode, alive.stdout), (1, b""))
        self.assertEqual(len(alive.stderr.splitlines()), 1, alive.stderr)
        self.assertNotIn(b"Traceback", alive.stderr)
        kill = smile(self.repo, "mux", "kill", handle, env=env)  # a pane may still be alive: exit 0 would lie
        self.assertEqual((kill.returncode, kill.stdout), (1, b""))
        for r in (alive, kill):
            self.assertEqual(r.stderr, b"smile: missing tmux not on PATH\n")

    def test_a_path_without_tmux_exits_1(self) -> None:
        d = bin_dir(("git",))  # no tmux, cmux, or herdr on it
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        r = smile(self.repo, "mux", "spawn", "n", "/tmp", "true", env={"PATH": d, "SMILE_MUX_SESSION": SESSION})
        self.assertEqual((r.returncode, r.stdout), (1, b""))
        self.assertIn(b"missing", r.stderr)
        self.assertEqual(len(r.stderr.splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
