"""`smile narrate`: the events appended since the last call, one line each (contract section 12).

A planner session wakes, calls this, and relays what it prints. The cursor in
`.factory/narrate.cursor` is a byte offset into the log, so any later session resumes where the
last one stopped: the log itself is never rewritten, only read from an offset.
"""

import json
import os
import re
import sys

import events
import worktree
from mux import Usage

CURSOR = re.compile(rb"[0-9]+\n")
ESCALATIONS = ("watch.escalation", "driver.paused")


def read_cursor(factory: str) -> int:
    """The byte offset already narrated. Absent is 0; anything but `<digits>\\n` is a bad cursor."""
    try:
        with open(f"{factory}/narrate.cursor", "rb") as f:
            raw = f.read()
    except FileNotFoundError:
        return 0
    if not CURSOR.fullmatch(raw):
        raise ValueError("bad narrate.cursor")
    return int(raw)


def write_cursor(factory: str, offset: int) -> None:
    """Write the cursor through a temporary file: a reader sees the old offset or the new one."""
    tmp = f"{factory}/narrate.cursor.tmp"
    with open(tmp, "wb") as f:
        f.write(f"{offset}\n".encode())
    os.replace(tmp, f"{factory}/narrate.cursor")


def parse(line: bytes) -> dict | None:
    """The event a raw log line carries, or None when it is not a section 3 event object."""
    try:
        record = json.loads(line.decode("utf-8", "surrogateescape"))
    except ValueError:
        return None
    if not isinstance(record, dict) or any(type(record.get(k)) not in (str, int, type(None)) for k in events.KEYS):
        return None
    return record


def render(record: dict) -> str:
    values = [record.get(k) for k in ("ts", "event", "bead", "pr", "actor", "detail")]
    return " ".join("-" if v is None else str(v) for v in values)


def is_escalation(record: dict) -> bool:
    event = record.get("event")
    return event in ESCALATIONS or (event == "worker.crashed" and record.get("detail") == "escalated")


def new_lines(factory: str, offset: int) -> tuple[list[tuple[int, bytes]], int]:
    """The complete lines from offset on, each with its byte offset, and the offset after them.

    A trailing partial line is left behind: the driver writes a line in one call, but a reader can
    still land mid-write, and a half-read event must be narrated once, when it is whole.
    """
    try:
        with open(f"{factory}/events.jsonl", "rb") as f:
            f.seek(0, os.SEEK_END)
            if offset > f.tell():
                offset = 0  # the log was recreated under us; start over rather than skip it
            f.seek(offset)
            data = f.read()
    except FileNotFoundError:
        return [], 0
    found, at = [], offset
    for chunk in data.split(b"\n")[:-1]:
        found.append((at, chunk))
        at += len(chunk) + 1
    return found, at


def cmd_narrate(root: str, args: list[str]) -> int:
    if args:
        raise Usage(f"unexpected argument {args[0]}")
    factory = worktree.factory(root)
    try:
        cursor = read_cursor(factory)
    except ValueError as e:  # the contract names this line exactly, without the `smile: ` prefix
        print(e, file=sys.stderr)
        return 1
    found, consumed = new_lines(factory, cursor)
    if not found:
        return 0  # nothing new: print nothing, leave the cursor alone
    rendered = [(at, parse(line)) for at, line in found]
    out = [render(r) for at, r in rendered if r and is_escalation(r)]
    out += [f"{at} unreadable" if r is None else render(r)
            for at, r in rendered if r is None or not is_escalation(r)]
    print("\n".join(out))
    write_cursor(factory, consumed)
    return 0
