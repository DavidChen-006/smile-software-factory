"""smile mux: the seam the driver spawns and reaps panes through (contract section 7).

One backend module per pane tool in backends/, each exposing spawn(session, name, cwd, argv) -> rest,
alive(rest) -> bool, and kill(rest) -> None. This file owns the handle grammar `<backend>:<rest>`,
so a backend never sees or builds a handle: spawn returns the rest and alive and kill are given it.
"""
import importlib
import importlib.util
import os
import shutil

import config

BACKENDS = ("tmux", "cmux", "herdr")  # also the auto-detect order


class Usage(Exception):
    """Bad arguments, malformed handle, or unknown backend: one stderr line, exit 2.

    smile.py runs as __main__ and cannot be imported back, so the one Usage the dispatcher catches
    is defined here and imported there.
    """


def backend(name: str):
    """The backends/<name>.py module; None when there is no such file yet (S8 writes cmux and herdr).

    A backend that exists but fails to import is a real failure, not an unknown backend: it propagates.
    """
    if name not in BACKENDS or importlib.util.find_spec(f"backends.{name}") is None:
        return None
    return importlib.import_module(f"backends.{name}")


def session(root: str) -> str:
    return os.environ.get("SMILE_MUX_SESSION") or f"smile-{os.path.basename(root)}"


def resolve(handle: str) -> tuple:
    """(module, rest) for `<backend>:<rest>`; the backend comes from the handle, never from config."""
    name, colon, rest = handle.partition(":")
    if not colon or not name or not rest or handle.split() != [handle]:
        raise Usage(f"malformed handle {handle}")
    module = backend(name)
    if module is None:
        raise Usage(f"unknown backend {name}")
    return module, rest


def spawn(root: str, args: list[str]) -> int:
    if len(args) < 3:
        raise Usage("usage: smile mux spawn <name> <cwd> <command> [args...]")
    name = config.get(root, "backend")
    if not name:
        name = next((b for b in BACKENDS if shutil.which(b)), "")
        if not name:
            raise RuntimeError("missing mux none of tmux, cmux, herdr on PATH")
    module = backend(name)
    if module is None:
        raise Usage(f"unknown backend {name}")
    if not os.path.isdir(args[1]):  # tmux itself accepts a missing -c and leaves a dead window behind
        raise RuntimeError(f"no such directory {args[1]}")
    print(f"{name}:{module.spawn(session(root), args[0], args[1], list(args[2:]))}")
    return 0


def alive(root: str, args: list[str]) -> int:
    if len(args) != 1:
        raise Usage("usage: smile mux alive <handle>")
    module, rest = resolve(args[0])
    return 0 if module.alive(rest) else 1


def kill(root: str, args: list[str]) -> int:
    if len(args) != 1:
        raise Usage("usage: smile mux kill <handle>")
    module, rest = resolve(args[0])
    module.kill(rest)  # already gone is success: the end state is the same either way
    return 0


VERBS = {"spawn": spawn, "alive": alive, "kill": kill}


def cmd_mux(root: str, args: list[str]) -> int:
    verb = VERBS.get(args[0]) if args else None
    if verb is None:
        raise Usage(f"usage: smile mux <spawn|alive|kill> [args...], got {args[0] if args else ''}")
    return verb(root, args[1:])
