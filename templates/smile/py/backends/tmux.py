"""tmux backend: one detached window per pane. Handle rest is `<session>:<window_id>` (contract section 7).

tmux rewrites `.` and `:` in a session name to `_`, so the name it reports back is the only one that
targets anything. spawn prints `#{session_name}:#{window_id}` and returns that line unread, and alive
and kill target what the handle carries; only the -t of a brand new window is built from the asked name.
"""

import re
import subprocess

import mux

REST = re.compile(r"(?P<session>[^\s:]+):(?P<window>@[0-9]+)")  # what a tmux handle's rest may look like
CREATE = ("-d", "-P", "-F", "#{session_name}:#{window_id}")
ILLEGAL = re.compile(r"[.:\s]")  # tmux turns . and : into _ in a session name; whitespace would break the handle


def tmux(argv: list[str]) -> subprocess.CompletedProcess:
    """Run tmux with argv passed through as one argv list, never re-joined through a shell."""
    try:
        return subprocess.run(["tmux", *argv], capture_output=True, check=False)
    except FileNotFoundError:
        raise RuntimeError("missing tmux not on PATH") from None


def stderr(proc: subprocess.CompletedProcess) -> str:
    return next(iter(proc.stderr.decode(errors="replace").splitlines()), "no output")


def parts(rest: str) -> tuple[str, str]:
    """(session, window id) for a well-formed rest; a rest we did not print names nothing, so it is malformed."""
    match = REST.fullmatch(rest)
    if match is None:
        raise mux.Usage(f"malformed handle tmux:{rest}")
    return match["session"], match["window"]


def spawn(session: str, name: str, cwd: str, argv: list[str]) -> str:
    session = ILLEGAL.sub("_", session)
    if len(argv) == 1:
        argv = ["env", *argv]  # tmux hands a lone word to sh -c; two words it execs itself, shell-free
    window = ["new-window", "-t", f"={session}", *CREATE, "-n", name, "-c", cwd, "--", *argv]
    proc = tmux(window)
    if proc.returncode != 0:  # no session yet: this window opens one. Two spawns can race here
        proc = tmux(["new-session", "-s", session, *CREATE, "-n", name, "-c", cwd, "--", *argv])
        if "duplicate session" in proc.stderr.decode(errors="replace"):
            proc = tmux(window)  # the other spawn won the race; the session it made is there now
    if proc.returncode != 0:
        raise RuntimeError(f"tmux refused: {stderr(proc)}")
    rest = proc.stdout.decode().strip()
    tmux(["set-option", "-w", "-t", f"={rest}", "remain-on-exit", "off"])
    return rest


def alive(rest: str) -> bool:
    """True while the session lists the window and the pane of that window has not died."""
    session, window = parts(rest)
    proc = tmux(["list-windows", "-t", f"={session}", "-F", "#{window_id} #{pane_dead}"])
    listed = dict(line.split(" ", 1) for line in proc.stdout.decode().splitlines() if " " in line)
    return proc.returncode == 0 and listed.get(window) == "0"


def kill(rest: str) -> None:
    """A missing window is already the end state; a missing tmux is not, so that one propagates (exit 1)."""
    session, window = parts(rest)
    tmux(["kill-window", "-t", f"={session}:{window}"])
