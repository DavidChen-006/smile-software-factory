"""S2 mux seam tests for the py runtime, driven through the stamped shim against a real tmux server.

Every window lives in one dedicated session, smile-test-<pid>, killed in tearDownClass.
Run from the repo root: python3 -m unittest tests.test_mux -v
"""
import os
import shutil
import subprocess
import time
import unittest

from tests.test_core import bin_dir, make_repo, set_config, smile

SESSION = f"smile-test-{os.getpid()}"


def tmux(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", *args], capture_output=True, text=True, check=False)


def wait_gone(case: unittest.TestCase, repo: str, handle: str) -> None:
    """Poll alive for up to five seconds; a command that has exited takes a moment to leave tmux."""
    for _ in range(50):
        if mux(repo, "alive", handle).returncode != 0:
            return
        time.sleep(0.1)
    case.fail(f"{handle} still alive")


def mux(repo: str, *args: str) -> subprocess.CompletedProcess:
    return smile(repo, "mux", *args, env={"SMILE_MUX_SESSION": SESSION})


@unittest.skipUnless(shutil.which("tmux"), "tmux not on PATH")
class MuxCase(unittest.TestCase):
    repo: str

    @classmethod
    def setUpClass(cls) -> None:
        cls.repo = make_repo("smile-mux")
        cls.addClassCleanup(shutil.rmtree, os.path.dirname(cls.repo), ignore_errors=True)
        cls.addClassCleanup(tmux, "kill-session", "-t", f"={SESSION}")

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


class HandleTest(MuxCase):
    def test_malformed_and_unknown_backends_exit_2(self) -> None:
        for handle in ("nope", "tmux:", ":x", "cmux:x:y", "herdr:x", "tmux:a b"):
            for verb in ("alive", "kill"):
                r = mux(self.repo, verb, handle)
                self.assertEqual((r.returncode, r.stdout), (2, b""), f"{verb} {handle}")
                self.assertEqual(len(r.stderr.splitlines()), 1, r.stderr)

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

    def test_a_path_without_tmux_exits_1(self) -> None:
        d = bin_dir(("git",))  # no tmux, cmux, or herdr on it
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        r = smile(self.repo, "mux", "spawn", "n", "/tmp", "true", env={"PATH": d, "SMILE_MUX_SESSION": SESSION})
        self.assertEqual((r.returncode, r.stdout), (1, b""))
        self.assertIn(b"missing", r.stderr)
        self.assertEqual(len(r.stderr.splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
