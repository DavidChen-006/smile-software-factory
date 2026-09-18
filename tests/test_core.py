"""S1 core tests for the py runtime, driven through the stamped shim in scratch git repos.

Run from the repo root: python3 -m unittest tests.test_core -v
"""
from __future__ import annotations  # PEP 604 unions in annotations on the 3.9 floor

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TS = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z"
TOOLS = ("git", "gh", "claude", "bd", "treehouse", "tmux", "cmux", "herdr")
SHIM_NEEDS = ("bash", "sed", "dirname")  # the shim's own commands beyond the tools doctor checks


def make_repo(name: str = "smile-core") -> str:
    """A scratch git repo stamped by install.py. Returned path is real (no /var -> /private/var drift)."""
    parent = os.path.realpath(tempfile.mkdtemp(prefix="smile-core-"))
    path = os.path.join(parent, name)
    os.mkdir(path)
    subprocess.run(["git", "init", "-q", path], check=True)
    subprocess.run(["git", "-C", path, "config", "user.email", "test@localhost"], check=True)
    subprocess.run(["git", "-C", path, "config", "user.name", "test"], check=True)
    subprocess.run([sys.executable, str(ROOT / "install.py"), path], check=True, stdout=subprocess.DEVNULL)
    return path


def set_config(repo: str, key: str, value: str) -> None:
    """Rewrite the `key:` line of the stamped config."""
    cfg = Path(repo, "smile.config.yaml")
    lines = [f"{key}: {value}" if line.startswith(f"{key}:") else line for line in cfg.read_text().split("\n")]
    cfg.write_text("\n".join(lines))


def smile(repo: str, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    """Run one command through the stamped shim from an unrelated cwd; bytes in and out. SMILE_ACTOR only via env."""
    full = {k: v for k, v in os.environ.items() if k != "SMILE_ACTOR"} | (env or {})
    return subprocess.run([f"{repo}/smile/smile", *args], cwd="/", env=full, capture_output=True, check=False)


def log_lines(repo: str) -> list[bytes]:
    path = Path(repo, ".factory/events.jsonl")
    return path.read_bytes().split(b"\n")[:-1] if path.exists() else []


def strip_ts(line: bytes) -> str:
    return re.sub(TS, "TS", line.decode("utf-8", "surrogateescape"), count=1)


def bin_dir(tools: tuple[str, ...], stubs: dict[str, str] | None = None) -> str:
    """A PATH directory holding symlinks to the named tools (stubbed when absent) plus what the shim needs."""
    d = tempfile.mkdtemp(prefix="smile-bin-")
    for tool in (*tools, *SHIM_NEEDS):
        if tool in (stubs or {}):
            continue
        real = shutil.which(tool)
        if real:
            os.symlink(real, os.path.join(d, tool))
        else:
            Path(d, tool).write_text("#!/bin/sh\nexit 0\n")
            os.chmod(os.path.join(d, tool), 0o755)
    os.symlink(sys.executable, os.path.join(d, "python3"))
    for tool, body in (stubs or {}).items():
        Path(d, tool).write_text(f"#!/bin/sh\n{body}\n")
        os.chmod(os.path.join(d, tool), 0o755)
    return d


class RepoCase(unittest.TestCase):
    repo: str

    @classmethod
    def setUpClass(cls) -> None:
        cls.repo = make_repo()
        cls.addClassCleanup(shutil.rmtree, os.path.dirname(cls.repo), ignore_errors=True)


class DispatchTest(RepoCase):
    def test_unknown_command_exits_2(self) -> None:
        r = smile(self.repo, "nosuch")
        self.assertEqual((r.returncode, r.stdout), (2, b""))
        self.assertEqual(len(r.stderr.splitlines()), 1)

    def test_extra_argument_exits_2(self) -> None:
        for cmd in ("doctor", "init", "pause", "resume", "status"):
            r = smile(self.repo, cmd, "extra")
            self.assertEqual((r.returncode, r.stdout, len(r.stderr.splitlines())), (2, b"", 1), cmd)


class DoctorTest(RepoCase):
    def doctor(self, tools: tuple[str, ...], stubs: dict[str, str] | None = None) -> tuple[int, list[str]]:
        d = bin_dir(tools, stubs)
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        r = smile(self.repo, "doctor", env={"PATH": d})
        self.assertEqual(r.stderr, b"")
        return r.returncode, r.stdout.decode().split("\n")[:-1]

    def test_all_ok_in_order(self) -> None:
        rc, lines = self.doctor(TOOLS)
        self.assertEqual(lines, ["ok git", "ok gh", "ok gh-auth", "ok claude", "ok bd", "ok treehouse", "ok mux tmux"])
        self.assertEqual(rc, 0)
        self.assertFalse(Path(self.repo, ".factory").exists(), "doctor is read-only")

    def test_missing_tools(self) -> None:
        rc, lines = self.doctor(("git", "claude", "bd", "cmux"))
        self.assertEqual(lines, ["ok git", "missing gh not on PATH", "missing gh-auth gh not on PATH", "ok claude",
                                 "ok bd", "missing treehouse not on PATH", "ok mux cmux"])
        self.assertEqual(rc, 1)

    def test_gh_auth_failed(self) -> None:
        rc, lines = self.doctor(TOOLS, stubs={"gh": "exit 1"})
        self.assertEqual(lines[1:3], ["ok gh", "missing gh-auth gh auth status failed"])
        self.assertEqual(rc, 1)

    def test_no_backend_on_path(self) -> None:
        rc, lines = self.doctor(("git", "gh", "claude", "bd", "treehouse"))
        self.assertEqual(lines[-1], "missing mux none of tmux, cmux, herdr on PATH")
        self.assertEqual(rc, 1)

    def test_backend_from_config(self) -> None:
        self.addCleanup(set_config, self.repo, "backend", "")
        set_config(self.repo, "backend", "herdr")
        self.assertEqual(self.doctor(TOOLS)[1][-1], "ok mux herdr")
        rc, lines = self.doctor(("git", "gh", "claude", "bd", "treehouse", "tmux"))
        self.assertEqual((rc, lines[-1]), (1, "missing mux herdr not on PATH"))
        set_config(self.repo, "backend", "screen")
        rc, lines = self.doctor(TOOLS)
        self.assertEqual((rc, lines[-1]), (1, "missing mux unknown backend screen"))


class InitTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo = make_repo("Zq-Repo")  # prefix rule: lowercase, strip non [a-z0-9], first two -> zq
        cls.addClassCleanup(shutil.rmtree, os.path.dirname(cls.repo), ignore_errors=True)

    def test_init_twice(self) -> None:
        things = [".beads", "treehouse.toml", ".worktreeinclude", ".factory", ".factory/events.jsonl"]
        r = smile(self.repo, "init")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.decode(), "".join(f"created {t}\n" for t in things))
        self.assertEqual(Path(self.repo, ".worktreeinclude").read_bytes(), b".env\nsmile.config.yaml\n")
        self.assertEqual(Path(self.repo, ".factory/events.jsonl").read_bytes(), b"")
        self.assertTrue(Path(self.repo, "treehouse.toml").is_file())
        ready = subprocess.run(["bd", "ready"], cwd=self.repo, capture_output=True, check=False)
        self.assertEqual(ready.returncode, 0, ready.stderr)
        bead = subprocess.run(["bd", "create", "x", "--silent"], cwd=self.repo, capture_output=True, text=True, check=True)
        self.assertTrue(bead.stdout.startswith("zq-"), bead.stdout)
        r = smile(self.repo, "init")
        self.assertEqual((r.returncode, r.stdout.decode()), (0, "".join(f"exists {t}\n" for t in things)))


class EventTest(RepoCase):
    CONTRACT_LINE = ('{"ts":"TS","event":"bead.claimed","bead":"sv-1","pr":null,"sha":null,'
                     '"actor":"driver","detail":"tick 3"}')

    def append(self, *args: str) -> str:
        before = len(log_lines(self.repo))
        r = smile(self.repo, "event", *args)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, b"", b""))
        lines = log_lines(self.repo)
        self.assertEqual(len(lines), before + 1)
        return strip_ts(lines[-1])

    def test_contract_example_byte_exact(self) -> None:
        self.assertEqual(self.append("bead.claimed", "bead=sv-1", "actor=driver", "detail=tick 3"), self.CONTRACT_LINE)
        self.assertRegex(log_lines(self.repo)[-1].decode(), f'^{{"ts":"{TS}",')

    def test_pr_is_a_bare_integer(self) -> None:
        line = self.append("pr.opened", "pr=7", "sha=abc123", "bead=sv-1")
        self.assertEqual(line, '{"ts":"TS","event":"pr.opened","bead":"sv-1","pr":7,"sha":"abc123","actor":null,"detail":null}')

    def test_empty_detail_is_empty_string(self) -> None:
        self.assertEqual(self.append("campaign.start", "detail="),
                         '{"ts":"TS","event":"campaign.start","bead":null,"pr":null,"sha":null,"actor":null,"detail":""}')

    def test_escapes_per_contract(self) -> None:
        detail = 'q"b\\t\tn\nc\x01café/\x7f\b\f\r'
        self.append("worker.crashed", f"detail={detail}")
        raw = log_lines(self.repo)[-1]
        self.assertTrue(raw.endswith(b'"detail":"q\\"b\\\\t\\tn\\nc\\u0001caf\xc3\xa9/\x7f\\b\\f\\r"}'), raw)
        self.assertEqual(json.loads(raw)["detail"], detail)

    def test_invalid_utf8_argv_passes_through_raw(self) -> None:
        self.append("pr.opened", os.fsdecode(b"detail=\xff"))
        self.assertTrue(log_lines(self.repo)[-1].endswith(b'"detail":"\xff"}'))
        self.assertIn(b" pr.opened - - \xff\n", smile(self.repo, "status").stdout)

    def test_long_detail_truncated_to_fit(self) -> None:
        self.append("watch.escalation", "detail=" + "x" * 5000)
        raw = log_lines(self.repo)[-1] + b"\n"
        self.assertEqual(len(raw), 4096)
        self.assertTrue(("x" * 5000).startswith(json.loads(raw)["detail"]))
        # multibyte detail: cut on a code point boundary, longest prefix that fits
        self.append("watch.escalation", "detail=" + "é" * 3000)
        raw = log_lines(self.repo)[-1] + b"\n"
        detail = json.loads(raw)["detail"]
        self.assertTrue(("é" * 3000).startswith(detail))
        self.assertLessEqual(len(raw), 4096)
        self.assertGreater(len(raw) + 2, 4096, "one more code point would not fit")

    def test_rejects_bad_arguments(self) -> None:
        bad = [(), ("nosuch.event",), ("pr.opened", "pr=x"), ("pr.opened", "pr=0"), ("pr.opened", "pr=07"),
               ("pr.opened", "pr="), ("pr.opened", "pr=-1"), ("pr.opened", "bead=a", "bead=b"),
               ("pr.opened", "foo=1"), ("pr.opened", "bead"), ("pr.opened", "ts=now")]
        for args in bad:
            before = log_lines(self.repo)
            r = smile(self.repo, "event", *args)
            self.assertEqual((r.returncode, r.stdout), (2, b""), args)
            self.assertEqual(len(r.stderr.splitlines()), 1, args)
            self.assertEqual(log_lines(self.repo), before, args)


class ConfigTest(RepoCase):
    def get(self, *args: str) -> subprocess.CompletedProcess:
        return smile(self.repo, "config", *args)

    def test_values_defaults_and_empty(self) -> None:
        self.assertEqual(self.get("get", "backend").stdout, b"\n")
        cfg = Path(self.repo, "smile.config.yaml")
        original = cfg.read_text()
        self.addCleanup(cfg.write_text, original)
        cfg.write_text("\n".join(line for line in original.split("\n") if not line.startswith("max_parallel:")))
        r = self.get("get", "max_parallel")
        self.assertEqual((r.returncode, r.stdout), (0, b"3\n"))
        # first wins, comments, indented and space-before-colon lines ignored, CR/tab trimmed, no yaml library
        cfg.write_text("# c\nbackend: tmux\nmerge:\thuman \t\nmerge: auto\n  base_branch: dev\nbase_branch : dev\n"
                       "worker.model:\tcafé\r\nwatchtower:off\n")
        self.assertEqual(self.get("get", "merge").stdout, b"human\n")
        self.assertEqual(self.get("get", "base_branch").stdout, b"main\n")
        self.assertEqual(self.get("get", "worker.model").stdout, "café\n".encode())
        self.assertEqual(self.get("get", "watchtower").stdout, b"off\n")
        cfg.write_bytes(b"backend: tmux\nworker.model: \xff\n")
        self.assertEqual(self.get("get", "worker.model").stdout, b"\xff\n")

    def test_exit_codes(self) -> None:
        r = self.get("get", "nosuch")
        self.assertEqual((r.returncode, r.stdout), (3, b""))
        for args in ((), ("get",), ("set", "backend"), ("get", "backend", "extra")):
            r = self.get(*args)
            self.assertEqual((r.returncode, r.stdout), (2, b""), args)


class PauseResumeTest(RepoCase):
    def test_pause_resume_cycle(self) -> None:
        r = smile(self.repo, "pause")
        self.assertEqual((r.returncode, r.stdout), (0, b"paused\n"))
        self.assertTrue(Path(self.repo, ".factory/pause").is_file())
        self.assertEqual([strip_ts(line) for line in log_lines(self.repo)], [
            '{"ts":"TS","event":"driver.paused","bead":null,"pr":null,"sha":null,"actor":"human","detail":null}'])
        r = smile(self.repo, "pause")
        self.assertEqual((r.returncode, r.stdout), (0, b"already paused\n"))
        self.assertEqual(len(log_lines(self.repo)), 1)
        r = smile(self.repo, "resume", env={"SMILE_ACTOR": "watchtower"})
        self.assertEqual((r.returncode, r.stdout), (0, b"resumed\n"))
        self.assertFalse(Path(self.repo, ".factory/pause").exists())
        self.assertEqual(strip_ts(log_lines(self.repo)[-1]),
                         '{"ts":"TS","event":"driver.resumed","bead":null,"pr":null,"sha":null,"actor":"watchtower","detail":null}')
        r = smile(self.repo, "resume")
        self.assertEqual((r.returncode, r.stdout), (0, b"not paused\n"))
        self.assertEqual(len(log_lines(self.repo)), 2)
        smile(self.repo, "pause", env={"SMILE_ACTOR": ""})  # empty counts as unset
        self.assertIn('"actor":"human"', strip_ts(log_lines(self.repo)[-1]))


class StatusTest(RepoCase):
    def status(self) -> str:
        r = smile(self.repo, "status")
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.decode()

    def test_status(self) -> None:
        # no .beads, no GitHub remote, no log
        self.assertEqual(self.status(), "beads:\n  unavailable\nprs:\n  unavailable\nevents:\n")
        self.assertEqual(smile(self.repo, "init").returncode, 0)
        self.assertEqual(self.status(), "beads:\nprs:\n  unavailable\nevents:\n")
        def bd(*a: str) -> str:
            return subprocess.run(["bd", *a], cwd=self.repo, capture_output=True, text=True, check=True).stdout.strip()

        ids = [bd("create", t, "--silent") for t in ("a", "b", "c", "d")]
        bd("close", ids[0])
        bd("update", ids[1], "--status", "in_progress")
        smile(self.repo, "event", "bead.claimed", "bead=sv-1", "actor=driver", "detail=tick 3")
        smile(self.repo, "event", "pr.opened", "bead=sv-1", "pr=7")
        with open(f"{self.repo}/.factory/events.jsonl", "ab") as f:
            f.write(b'not json\n[1,2]\n{"ts":"t","event":"pr.merged","bead":null,"pr":[7],"sha":null,"actor":null,"detail":null}\n')
        smile(self.repo, "event", "pane.spawned", "detail=a\tb\nc\rd", "sha=")
        out = self.status()
        self.assertEqual(re.sub(TS, "TS", out), (
            "beads:\n  closed 1\n  in_progress 1\n  open 2\nprs:\n  unavailable\nevents:\n"
            "  TS bead.claimed sv-1 - tick 3\n  TS pr.opened sv-1 7 -\n  not json\n  [1,2]\n"
            '  {"ts":"t","event":"pr.merged","bead":null,"pr":[7],"sha":null,"actor":null,"detail":null}\n'
            "  TS pane.spawned - - a b c d\n"))
        # a bd that prints a non-string status makes the section unavailable
        d = bin_dir((), stubs={"bd": "echo '[{\"status\":5}]'"})
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        self.assertTrue(smile(self.repo, "status", env={"PATH": d}).stdout.startswith(b"beads:\n  unavailable\n"))
        # last ten, oldest first, and a final line without a newline still counts
        for i in range(6):  # 6 lines so far + 6 + 1 unterminated = 13; the last ten start at "[1,2]"
            smile(self.repo, "event", "bead.closed", f"detail=n{i}")
        with open(f"{self.repo}/.factory/events.jsonl", "ab") as f:
            f.write(b'{"ts":"t","event":"campaign.complete","bead":null,"pr":null,"sha":null,"actor":null,"detail":"last"}')
        shown = self.status().split("events:\n")[1].split("\n")[:-1]
        self.assertEqual(len(shown), 10)
        self.assertEqual(shown[0], "  [1,2]")
        self.assertEqual(shown[-1], "  t campaign.complete - - last")

    def test_corrupt_line_keeps_its_own_cr(self) -> None:
        # only the trailing newline is stripped: a CRLF line renders with its CR (contract section 4, status)
        repo = make_repo()
        self.addCleanup(shutil.rmtree, os.path.dirname(repo), ignore_errors=True)
        Path(repo, ".factory").mkdir()
        Path(repo, ".factory/events.jsonl").write_bytes(b"not json\r\n")
        self.assertTrue(smile(repo, "status").stdout.endswith(b"events:\n  not json\r\n"))


if __name__ == "__main__":
    unittest.main()
