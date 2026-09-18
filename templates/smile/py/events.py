"""The event log at .factory/events.jsonl (contract section 3)."""
import json
import os
from datetime import datetime, timezone

EVENTS = (
    "campaign.start", "bead.claimed", "worktree.acquired", "pane.spawned", "pr.opened",
    "review.started", "review.verdict", "issue.opened", "issue.resolved", "pr.merged",
    "bead.closed", "pane.reaped", "worker.crashed", "watch.escalation",
    "driver.paused", "driver.resumed", "campaign.complete",
)
KEYS = ("ts", "event", "bead", "pr", "sha", "actor", "detail")  # wire order
MAX_LINE = 4096  # POSIX PIPE_BUF: a single write of at most this many bytes never interleaves


def encode(record: dict) -> bytes:
    text = json.dumps(record, separators=(",", ":"), ensure_ascii=False)
    return text.encode("utf-8", "surrogateescape") + b"\n"  # argv bytes that were not UTF-8 pass through raw


def append(root: str, event: str, bead: str | None = None, pr: int | None = None,
           sha: str | None = None, actor: str | None = None, detail: str | None = None) -> None:
    """Append one event line in a single write; detail is cut to the longest prefix that fits MAX_LINE."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    record = dict(zip(KEYS, (ts, event, bead, pr, sha, actor, detail)))
    line = encode(record)
    while len(line) > MAX_LINE and record["detail"]:
        record["detail"] = record["detail"][:-max(1, (len(line) - MAX_LINE) // 6)]  # a code point is at most 6 bytes
        line = encode(record)
    os.makedirs(f"{root}/.factory", exist_ok=True)
    fd = os.open(f"{root}/.factory/events.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, line)
    finally:
        os.close(fd)


def tail(root: str, n: int) -> list[str]:
    """The last n lines of the log, oldest first, raw; [] when the log is missing or empty.

    newline="" keeps a corrupt line's own CR: only the trailing newline is stripped, nothing is translated.
    """
    try:
        with open(f"{root}/.factory/events.jsonl", encoding="utf-8", errors="surrogateescape", newline="") as f:
            lines = f.read().split("\n")
    except FileNotFoundError:
        return []
    if lines and lines[-1] == "":
        lines.pop()  # the file's trailing newline is not an empty line
    return lines[-n:]
