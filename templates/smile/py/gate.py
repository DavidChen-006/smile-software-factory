"""smile gate: the human hold on merges (contract section 9).

The whole state is `<factory>/gate.json`, `{"mode": <all|none|auto>, "beads": [...]}`. The review
lane asks one question of it, `gated`, at verdict time; nothing else reads the file.
"""
from __future__ import annotations

import json
import os

import worktree
from mux import Usage

MODES = ("all", "none", "auto")
DEFAULT = {"mode": "auto", "beads": []}


def path(root: str) -> str:
    return f"{worktree.factory(root)}/gate.json"


def read(root: str) -> dict:
    """The gate state; the default when the file is absent. An unreadable file is a failure, not a default."""
    try:
        with open(path(root), encoding="utf-8") as f:
            state = json.load(f)
    except FileNotFoundError:
        return dict(DEFAULT)
    except (OSError, ValueError):
        raise RuntimeError("bad gate.json") from None
    if not isinstance(state, dict) or state.get("mode") not in MODES or not isinstance(state.get("beads"), list):
        raise RuntimeError("bad gate.json")
    return state


def write(root: str, state: dict) -> None:
    """Compact JSON with sorted keys and a trailing newline, beads sorted: the same bytes every time."""
    os.makedirs(worktree.factory(root), exist_ok=True)
    with open(path(root), "w", encoding="utf-8") as f:
        f.write(json.dumps({"mode": state["mode"], "beads": sorted(set(state["beads"]))},
                           sort_keys=True, separators=(",", ":")) + "\n")


def gated(root: str, bead: str, labels: list) -> bool:
    """Does this approval wait for a human? Mode `all`, mode `auto` with the bead held, or the PR label."""
    state = read(root)
    return state["mode"] == "all" or (state["mode"] == "auto" and bead in state["beads"]) or "human-gate" in labels


def cmd_gate(root: str, args: list) -> int:
    if args == ["status"]:
        state = read(root)
        print("\n".join([f"mode {state['mode']}", *(f"bead {b}" for b in sorted(state["beads"]))]))
        return 0
    if len(args) == 1 and args[0] in MODES:
        write(root, {**read(root), "mode": args[0]})
        return 0
    if len(args) == 3 and args[0] == "bead" and args[2] in ("on", "off"):
        state = read(root)
        held = set(state["beads"]) | {args[1]} if args[2] == "on" else set(state["beads"]) - {args[1]}
        write(root, {**state, "beads": list(held)})
        return 0
    raise Usage("usage: smile gate status|all|none|auto, or smile gate bead <id> on|off")
