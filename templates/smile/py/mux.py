"""smile mux: the seam the driver spawns and reaps panes through (contract section 7).

One backend module per pane tool in backends/, each exposing spawn(session, name, cwd, argv) -> rest,
alive(rest) -> bool, and kill(rest) -> None. This file owns the handle grammar `<backend>:<rest>`,
so a backend never sees or builds a handle: spawn returns the rest and alive and kill are given it.
"""
import importlib
import os
import shutil
import sys

import config

BACKENDS = ("tmux", "cmux", "herdr")  # also the auto-detect order


class Bad(Exception):
    """Usage, malformed handle, or unknown backend: one stderr line, exit 2."""


def backend(name: str):
    """The backends/<name>.py module; None when the name is not a backend or has no file yet (S8)."""
    if name not in BACKENDS:
        return None
    try:
        return importlib.import_module(f"backends.{name}")
    except ImportError:
        return None


def session(root: str) -> str:
    return os.environ.get("SMILE_MUX_SESSION") or f"smile-{os.path.basename(root)}"


def resolve(handle: str) -> tuple:
    """(module, rest) for `<backend>:<rest>`; the backend comes from the handle, never from config."""
    name, colon, rest = handle.partition(":")
    if not colon or not name or not rest or handle.split() != [handle]:
        raise Bad(f"malformed handle {handle}")
    module = backend(name)
    if module is None:
        raise Bad(f"unknown backend {name}")
    return module, rest


def spawn(root: str, args: list[str]) -> int:
    if len(args) < 3:
        raise Bad("usage: smile mux spawn <name> <cwd> <command> [args...]")
    name = config.get(root, "backend")
    if not name:
        name = next((b for b in BACKENDS if shutil.which(b)), "")
        if not name:
            raise RuntimeError("missing: none of tmux, cmux, herdr on PATH")
    module = backend(name)
    if module is None:
        raise Bad(f"unknown backend {name}")
    if not os.path.isdir(args[1]):  # tmux itself accepts a missing -c and leaves a dead window behind
        raise RuntimeError(f"no such directory {args[1]}")
    print(f"{name}:{module.spawn(session(root), args[0], args[1], list(args[2:]))}")
    return 0


def alive(root: str, args: list[str]) -> int:
    if len(args) != 1:
        raise Bad("usage: smile mux alive <handle>")
    module, rest = resolve(args[0])
    return 0 if module.alive(rest) else 1


def kill(root: str, args: list[str]) -> int:
    if len(args) != 1:
        raise Bad("usage: smile mux kill <handle>")
    module, rest = resolve(args[0])
    module.kill(rest)  # already gone is success: the end state is the same either way
    return 0


VERBS = {"spawn": spawn, "alive": alive, "kill": kill}


def cmd_mux(root: str, args: list[str]) -> int:
    try:
        verb = VERBS.get(args[0]) if args else None
        if verb is None:
            raise Bad(f"usage: smile mux <spawn|alive|kill> [args...], got {args[0] if args else ''}")
        return verb(root, args[1:])
    except Bad as e:
        print(f"smile: {e}", file=sys.stderr)
        return 2
