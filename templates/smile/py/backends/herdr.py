"""Herdr backend: one pane per spawn, split off the workspace root (contract sections 7 and 14).

Handle rest is the pane id Herdr reports, `w<N>:p<N>`. Herdr closes a pane when its process exits, so
`alive` is exactly "the server still lists this pane" and needs no separate liveness probe. The argv is
run through `herdr pane run`, which takes one command line, so it is shell-quoted word by word: the
shell never sees a word the caller did not write, and spaces inside a word survive.
"""

import json
import os
import re
import shlex
import subprocess
import time

import mux

REST = re.compile(r"w[0-9]+:p[0-9]+")  # the pane id shape Herdr hands back
READY = 5.0  # seconds to wait for a fresh pane's shell before the command is typed into it


def herdr(argv: list[str]) -> tuple[int, dict]:
    """(exit status, parsed JSON) for one herdr call; a server that does not answer is a missing tool."""
    try:
        proc = subprocess.run(["herdr", *argv], capture_output=True, check=False)
    except FileNotFoundError:
        raise RuntimeError("missing herdr not on PATH") from None
    try:
        body = json.loads(proc.stdout or proc.stderr)
    except ValueError:
        body = {}
    if proc.returncode != 0 and not body.get("error"):
        raise RuntimeError("missing herdr server not answering")
    return proc.returncode, body


def parts(rest: str) -> str:
    if REST.fullmatch(rest) is None:
        raise mux.Usage(f"malformed handle herdr:{rest}")
    return rest


def workspace() -> str:
    """The workspace Herdr calls current: the caller's when it has one, else the server's focused one."""
    current = os.environ.get("HERDR_WORKSPACE_ID")
    if current:
        return current
    code, body = herdr(["workspace", "list"])
    spaces = body.get("result", {}).get("workspaces", []) if code == 0 else []
    focused = next((w for w in spaces if w.get("focused")), None) or next(iter(spaces), None)
    if focused is None:
        raise RuntimeError("missing herdr server has no workspace")
    return focused["workspace_id"]


def root(space: str) -> str:
    code, body = herdr(["pane", "list", "--workspace", space])
    panes = body.get("result", {}).get("panes", []) if code == 0 else []
    if not panes:
        raise RuntimeError(f"herdr refused: no pane in workspace {space}")
    return panes[0]["pane_id"]


def ready(pane: str) -> None:
    """Wait for the new pane's shell to reach its prompt; a command typed before it is simply lost."""
    deadline = time.monotonic() + READY
    while time.monotonic() < deadline:
        code, body = herdr(["pane", "process-info", "--pane", pane])
        if code == 0 and body.get("result", {}).get("process_info", {}).get("foreground_processes"):
            return
        time.sleep(0.05)


def spawn(session: str, name: str, cwd: str, argv: list[str]) -> str:
    """Split a pane off the current workspace's root and exec the argv in it. `session` is unused:
    Herdr panes live in the workspace Herdr reports as current, not in a session of our naming."""
    space = workspace()
    code, body = herdr(["pane", "split", root(space), "--direction", "down", "--cwd", cwd, "--no-focus"])
    if code != 0:
        raise RuntimeError(f"herdr refused: {body.get('error', {}).get('message', 'no output')}")
    pane = body["result"]["pane"]["pane_id"]
    herdr(["pane", "rename", pane, name])
    ready(pane)
    command = "exec " + " ".join(shlex.quote(word) for word in argv)  # exec: the pane dies with the command
    code, body = herdr(["pane", "run", pane, command])
    if code != 0:
        herdr(["pane", "close", pane])
        raise RuntimeError(f"herdr refused: {body.get('error', {}).get('message', 'no output')}")
    return pane


def alive(rest: str) -> bool:
    """Herdr closes the pane when its process exits, so a listed pane is a running pane."""
    return herdr(["pane", "get", parts(rest)])[0] == 0


def kill(rest: str) -> None:
    """A pane Herdr no longer knows is already the end state; anything else, a dead server above all,
    is a failure: a kill that quietly did nothing would leave the driver believing a pane is gone."""
    code, body = herdr(["pane", "close", parts(rest)])
    error = body.get("error", {})
    if code != 0 and error.get("code") != "pane_not_found":
        raise RuntimeError(f"herdr refused: {error.get('message', 'no output')}")
