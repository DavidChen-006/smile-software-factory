"""S6 narration tests for the py runtime, driven through the stamped shim in a scratch git repo.

`smile narrate` touches nothing but the event log and its cursor, so no fake tools are needed: the
tests write events with `smile event` or by appending raw bytes, and read stdout and the cursor.

Run from the repo root: uv run python -m unittest tests.test_narrate -v
"""

import os
import shutil
import unittest
from pathlib import Path

from tests.test_core import make_repo, smile

EVENT = ('{"ts":"2026-09-19T00:00:0%dZ","event":"%s","bead":%s,"pr":null,"sha":null,'
         '"actor":"driver","detail":%s}\n')


def line(n: int, event: str, bead: str | None = "sv-1", detail: str | None = None) -> bytes:
    bead_json = "null" if bead is None else f'"{bead}"'
    detail_json = "null" if detail is None else f'"{detail}"'
    return (EVENT % (n, event, bead_json, detail_json)).encode()


class NarrateTest(unittest.TestCase):
    """One stamped, initialised repo for the class; every test starts from a fresh .factory."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.repo = make_repo("smile-narrate", init=True)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(os.path.dirname(cls.repo), ignore_errors=True)

    def setUp(self) -> None:
        self.factory = Path(self.repo, ".factory")
        shutil.rmtree(self.factory, ignore_errors=True)
        self.factory.mkdir()
        self.log = self.factory / "events.jsonl"
        self.cursor = self.factory / "narrate.cursor"
        self.log.write_bytes(b"")

    def append(self, *chunks: bytes) -> None:
        with open(self.log, "ab") as f:
            f.writelines(chunks)

    def narrate(self) -> tuple[int, list[str], str]:
        proc = smile(self.repo, "narrate")
        out = proc.stdout.decode().splitlines()
        return proc.returncode, out, proc.stderr.decode()

    def test_first_call_prints_everything_and_writes_the_byte_length(self) -> None:
        smile(self.repo, "event", "campaign.start", "actor=driver")
        smile(self.repo, "event", "bead.claimed", "bead=sv-1", "actor=driver", "detail=tick 1")
        rc, out, err = self.narrate()
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(len(out), 2)
        self.assertRegex(out[0], r"^\S+ campaign\.start - - driver -$")
        self.assertRegex(out[1], r"^\S+ bead\.claimed sv-1 - driver tick 1$")
        self.assertEqual(self.cursor.read_bytes(), f"{self.log.stat().st_size}\n".encode())

    def test_second_call_with_nothing_new_prints_nothing_and_leaves_the_cursor(self) -> None:
        self.append(line(1, "pr.opened"))
        rc, out, _ = self.narrate()
        self.assertEqual((rc, len(out)), (0, 1))
        before = self.cursor.read_bytes()
        rc, out, err = self.narrate()
        self.assertEqual((rc, out, err), (0, [], ""))
        self.assertEqual(self.cursor.read_bytes(), before)

    def test_partial_trailing_line_waits_for_its_newline(self) -> None:
        whole = line(1, "pr.opened")
        self.append(whole)
        half = line(2, "pr.merged")
        self.append(half[:20])
        rc, out, _ = self.narrate()
        self.assertEqual((rc, len(out)), (0, 1))
        self.assertIn("pr.opened", out[0])
        self.assertEqual(self.cursor.read_bytes(), f"{len(whole)}\n".encode())
        self.append(half[20:])
        rc, out, _ = self.narrate()
        self.assertEqual(rc, 0)
        self.assertEqual(len(out), 1)
        self.assertIn("pr.merged", out[0])
        self.assertEqual(self.cursor.read_bytes(), f"{len(whole) + len(half)}\n".encode())

    def test_escalations_print_first_and_log_order_holds_otherwise(self) -> None:
        self.append(line(1, "bead.claimed"),
                    line(2, "worker.crashed", detail="attempt 1"),
                    line(3, "worker.crashed", detail="escalated"),
                    line(4, "watch.escalation", detail="crashed twice"),
                    line(5, "driver.paused", bead=None),
                    line(6, "pane.reaped"))
        rc, out, _ = self.narrate()
        self.assertEqual(rc, 0)
        events = [printed.split()[1] for printed in out]
        self.assertEqual(events, ["worker.crashed", "watch.escalation", "driver.paused",
                                  "bead.claimed", "worker.crashed", "pane.reaped"])
        self.assertTrue(out[0].endswith("escalated"))
        self.assertTrue(out[4].endswith("attempt 1"))

    def test_unreadable_line_prints_its_byte_offset(self) -> None:
        good = line(1, "pr.opened")
        self.append(good, b"not json at all\n", line(3, "pr.merged"))
        rc, out, _ = self.narrate()
        self.assertEqual(rc, 0)
        self.assertEqual(out[1], f"{len(good)} unreadable")
        self.assertEqual(self.cursor.read_bytes(), f"{self.log.stat().st_size}\n".encode())

    def test_bad_cursor_is_exit_1_with_one_stderr_line(self) -> None:
        self.append(line(1, "pr.opened"))
        self.cursor.write_bytes(b"seven\n")
        proc = smile(self.repo, "narrate")
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stdout, b"")
        self.assertEqual(proc.stderr.decode().splitlines(), ["bad narrate.cursor"])

    def test_offset_past_end_of_file_restarts_at_zero(self) -> None:
        self.append(line(1, "pr.opened"))
        self.cursor.write_bytes(b"9999\n")
        rc, out, _ = self.narrate()
        self.assertEqual((rc, len(out)), (0, 1))
        self.assertIn("pr.opened", out[0])
        self.assertEqual(self.cursor.read_bytes(), f"{self.log.stat().st_size}\n".encode())

    def test_extra_argument_is_exit_2_and_appends_no_event(self) -> None:
        self.append(line(1, "pr.opened"))
        size = self.log.stat().st_size
        proc = smile(self.repo, "narrate", "sv-1")
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.stdout, b"")
        self.assertTrue(proc.stderr.decode().strip())
        self.assertEqual(self.log.stat().st_size, size)
        self.assertFalse(self.cursor.exists())


if __name__ == "__main__":
    unittest.main()
