"""cmux backend: one terminal surface per spawn, inside a workspace named for the checkout (section 14).

Handle rest is `<workspace index>:<surface index>`, the two numbers of cmux's short refs, so the handle
stays one colon-separated word and `kill` can name the workspace explicitly (a close without
--workspace acts on the focused workspace, the 2026-07-20 finding). Liveness comes from cmux's own
surface listing, never a screen scrape.
"""

import json
import re
import shlex
import subprocess

import mux

REST = re.compile(r"(?P<workspace>[0-9]+):(?P<surface>[0-9]+)")
INDEX = re.compile(r"(?:workspace|surface):([0-9]+)")


def cmux(argv: list[str]) -> tuple[int, str]:
    """(exit status, stdout) for one cmux call; a socket that refuses is a missing tool, like tmux absent."""
    try:
        proc = subprocess.run(["cmux", *argv], capture_output=True, check=False)
    except FileNotFoundError:
        raise RuntimeError("missing cmux not on PATH") from None
    out = proc.stdout.decode(errors="replace")
    if proc.returncode != 0 and "Failed to connect to socket" in proc.stderr.decode(errors="replace"):
        raise RuntimeError("missing cmux server not answering")
    return proc.returncode, out


def rows(out: str) -> list[dict]:
    """cmux prints JSON when it has structure to print; anything else means nothing was listed."""
    try:
        body = json.loads(out)
    except ValueError:
        return []
    for value in (body if isinstance(body, dict) else {}).values():
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    return body if isinstance(body, list) else []


def index(row: dict, key: str) -> str:
    """The number out of a cmux ref or uuid field, whichever of the two the listing carried."""
    match = INDEX.search(str(row.get(key, "")) or str(row.get("ref", "")))
    return match[1] if match else ""


def parts(rest: str) -> tuple[str, str]:
    match = REST.fullmatch(rest)
    if match is None:
        raise mux.Usage(f"malformed handle cmux:{rest}")
    return match["workspace"], match["surface"]


def workspace(session: str, cwd: str) -> str:
    """The index of the workspace named `session`, created against `cwd` when it is not there yet."""
    for _ in range(2):
        for row in rows(cmux(["list-workspaces", "--id-format", "both"])[1]):
            if row.get("name") == session or row.get("title") == session:
                return index(row, "workspace")
        cmux(["new-workspace", "--name", session, "--cwd", cwd, "--focus", "false"])
    raise RuntimeError(f"cmux refused: no workspace {session}")


def spawn(session: str, name: str, cwd: str, argv: list[str]) -> str:
    space = workspace(session, cwd)
    code, out = cmux(["new-surface", "--type", "terminal", "--workspace", f"workspace:{space}",
                      "--focus", "false", "--id-format", "both"])
    surface = index(next(iter(rows(out)), {}), "surface") or index({"ref": out}, "ref")
    if code != 0 or not surface:
        raise RuntimeError(f"cmux refused: {next(iter(out.splitlines()), 'no output')}")
    cmux(["rename-tab", "--workspace", f"workspace:{space}", "--surface", f"surface:{surface}", name])
    command = "cd " + shlex.quote(cwd) + " && exec " + " ".join(shlex.quote(word) for word in argv)
    cmux(["send", "--workspace", f"workspace:{space}", "--surface", f"surface:{surface}", command])
    return f"{space}:{surface}"


def alive(rest: str) -> bool:
    space, surface = parts(rest)
    code, out = cmux(["list-pane-surfaces", "--workspace", f"workspace:{space}", "--id-format", "both"])
    return code == 0 and any(index(row, "surface") == surface for row in rows(out))


def kill(rest: str) -> None:
    """--workspace is not optional here: a close without it closes whatever the user is looking at."""
    space, surface = parts(rest)
    cmux(["close-surface", "--surface", f"surface:{surface}", "--workspace", f"workspace:{space}"])
