"""tmux backend: one detached window per pane. Handle rest is `<session>:<window_id>` (contract section 7)."""
import shutil
import subprocess


def tmux(argv: list[str]) -> subprocess.CompletedProcess:
    """Run tmux with argv passed through as one argv list, never re-joined through a shell."""
    return subprocess.run(["tmux", *argv], capture_output=True, check=False)


def spawn(session: str, name: str, cwd: str, argv: list[str]) -> str:
    if not shutil.which("tmux"):
        raise RuntimeError("missing tmux not on PATH")
    exists = tmux(["has-session", "-t", f"={session}"]).returncode == 0
    create = (["new-window", "-t", f"={session}"] if exists else ["new-session", "-s", session])
    proc = tmux([*create, "-d", "-P", "-F", "#{window_id}", "-n", name, "-c", cwd, "--", *argv])
    if proc.returncode != 0:
        why = next(iter(proc.stderr.decode(errors="replace").splitlines()), "no output")
        raise RuntimeError(f"tmux refused: {why}")
    window = proc.stdout.decode().strip()
    tmux(["set-option", "-w", "-t", f"={session}:{window}", "remain-on-exit", "off"])
    return f"{session}:{window}"


def windows(session: str) -> dict[str, str]:
    """window id -> #{pane_dead} of its active pane, for every window of the session; empty when it is gone."""
    proc = tmux(["list-windows", "-t", f"={session}", "-F", "#{window_id} #{pane_dead}"])
    if proc.returncode != 0:
        return {}
    return dict(line.split(" ", 1) for line in proc.stdout.decode().splitlines() if " " in line)


def alive(rest: str) -> bool:
    session, _, window = rest.rpartition(":")
    return windows(session).get(window) == "0"


def kill(rest: str) -> None:
    session, _, window = rest.rpartition(":")
    tmux(["kill-window", "-t", f"={session}:{window}"])  # a missing window is already the end state
