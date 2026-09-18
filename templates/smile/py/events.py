"""The event log at .factory/events.jsonl (contract section 3)."""
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

EVENTS = (
    "campaign.start", "bead.claimed", "worktree.acquired", "pane.spawned", "pr.opened",
    "review.started", "review.verdict", "issue.opened", "issue.resolved", "pr.merged",
    "bead.closed", "pane.reaped", "worker.crashed", "watch.escalation",
    "driver.paused", "driver.resumed", "campaign.complete",
)
MAX_LINE = 4096  # POSIX PIPE_BUF: a single write of at most this many bytes never interleaves


@dataclass
class Event:  # field order is the key order on the wire
    ts: str
    event: str
    bead: str | None
    pr: int | None
    sha: str | None
    actor: str | None
    detail: str | None


def encode(e: Event) -> bytes:
    return json.dumps(asdict(e), separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n"


def append(root: str, event: str, bead: str | None = None, pr: int | None = None,
           sha: str | None = None, actor: str | None = None, detail: str | None = None) -> None:
    """Append one event line in a single write; detail is truncated until the line fits."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    e = Event(ts, event, bead, pr, sha, actor, detail)
    line = encode(e)
    while len(line) > MAX_LINE and e.detail:
        e.detail = e.detail[:-max(1, (len(line) - MAX_LINE) // 6)]  # one char encodes to at most 6 bytes
        line = encode(e)
    os.makedirs(f"{root}/.factory", exist_ok=True)
    fd = os.open(f"{root}/.factory/events.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, line)
    finally:
        os.close(fd)


def tail(root: str, n: int) -> list[str]:
    """The last n lines of the log, oldest first, raw; [] when the log is missing or empty."""
    try:
        with open(f"{root}/.factory/events.jsonl", encoding="utf-8", errors="surrogateescape") as f:
            lines = f.read().split("\n")
    except FileNotFoundError:
        return []
    if lines and lines[-1] == "":
        lines.pop()  # the file's trailing newline is not an empty line
    return lines[-n:]
