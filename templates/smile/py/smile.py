"""SMILE py runtime. The shim runs `python3 smile.py <command> [args...]` with SMILE_ROOT exported.

One function per command, all listed in COMMANDS. Contract: docs/RUNTIME-CONTRACT.md in the SMILE repo.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter

sys.dont_write_bytecode = True  # no __pycache__ in the stamped repo; set before the modules beside this file load
import config
import events

BACKENDS = ("tmux", "cmux", "herdr")
EVENT_FIELDS = ("bead", "pr", "sha", "actor", "detail")
TOOL_ENV = {**os.environ, "BD_NON_INTERACTIVE": "1"}


class Usage(Exception):
    """Bad arguments: one stderr line, exit 2."""


def no_args(args: list[str]) -> None:
    if args:
        raise Usage(f"unexpected argument {args[0]}")


def actor() -> str:
    return os.environ.get("SMILE_ACTOR") or "human"


def tool_json(root: str, argv: list[str]) -> list | None:
    """The JSON list a tool prints when run in root; None when it is missing, fails, or prints no list."""
    try:
        proc = subprocess.run(argv, cwd=root, env=TOOL_ENV, stdout=subprocess.PIPE, check=False)
        out = json.loads(proc.stdout) if proc.returncode == 0 else None
    except (OSError, ValueError):
        return None
    return out if isinstance(out, list) else None


# ---------------------------------------------------------------- doctor
def on_path(tool: str) -> str:
    return f"ok {tool}" if shutil.which(tool) else f"missing {tool} not on PATH"


def gh_auth() -> str:
    if not shutil.which("gh"):
        return "missing gh-auth gh not on PATH"
    rc = subprocess.run(["gh", "auth", "status"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False).returncode
    return "ok gh-auth" if rc == 0 else "missing gh-auth gh auth status failed"


def mux(backend: str) -> str:
    if backend == "":
        found = next((b for b in BACKENDS if shutil.which(b)), None)
        return f"ok mux {found}" if found else "missing mux none of tmux, cmux, herdr on PATH"
    if backend not in BACKENDS:
        return f"missing mux unknown backend {backend}"
    return f"ok mux {backend}" if shutil.which(backend) else f"missing mux {backend} not on PATH"


def cmd_doctor(root: str, args: list[str]) -> int:
    no_args(args)
    lines = [on_path("git"), on_path("gh"), gh_auth(), on_path("claude"), on_path("bd"), on_path("treehouse"),
             mux(config.get(root, "backend"))]
    print("\n".join(lines))
    return 1 if any(line.startswith("missing ") for line in lines) else 0


# ---------------------------------------------------------------- init
def bead_prefix(root: str) -> str:
    """Basename ASCII-lowercased, everything outside [a-z0-9] dropped, first two characters; else sm."""
    name = os.path.basename(root).encode("utf-8", "surrogateescape").lower()
    kept = re.sub(rb"[^a-z0-9]", b"", name)[:2]
    return kept.decode() if len(kept) == 2 else "sm"


def run_tool(root: str, argv: list[str]) -> None:
    subprocess.run(argv, cwd=root, env=TOOL_ENV, stdout=subprocess.DEVNULL, check=True)


def write_file(path: str, data: bytes) -> None:
    with open(path, "wb") as f:
        f.write(data)


def cmd_init(root: str, args: list[str]) -> int:
    no_args(args)
    steps = (  # (thing, is present, create it)
        (".beads", os.path.isdir, lambda p: run_tool(root, ["bd", "init", "--prefix", bead_prefix(root), "-q"])),
        ("treehouse.toml", os.path.exists, lambda p: run_tool(root, ["treehouse", "init"])),
        (".worktreeinclude", os.path.exists, lambda p: write_file(p, b".env\nsmile.config.yaml\n")),
        (".factory", os.path.isdir, os.mkdir),
        (".factory/events.jsonl", os.path.exists, lambda p: write_file(p, b"")),
    )
    for thing, present, create in steps:
        path = f"{root}/{thing}"
        if present(path):
            print(f"exists {thing}")
        else:
            create(path)
            print(f"created {thing}")
        sys.stdout.flush()
    return 0


# ---------------------------------------------------------------- event, config, pause, resume
def cmd_event(root: str, args: list[str]) -> int:
    if not args or args[0] not in events.EVENTS:
        raise Usage(f"unknown event name {args[0] if args else ''}")
    fields: dict[str, str] = {}
    for arg in args[1:]:
        key, eq, value = arg.partition("=")
        if not eq or key not in EVENT_FIELDS or key in fields:
            raise Usage(f"bad argument {arg}")
        fields[key] = value
    pr = fields.pop("pr", None)
    if pr is not None and not re.fullmatch(r"[1-9][0-9]*", pr):
        raise Usage(f"pr must be a positive integer, got {pr!r}")
    events.append(root, args[0], pr=None if pr is None else int(pr), **fields)
    return 0


def cmd_config(root: str, args: list[str]) -> int:
    if len(args) != 2 or args[0] != "get":
        raise Usage("usage: smile config get <key>")
    if args[1] not in config.SCHEMA:
        print(f"smile: unknown config key {args[1]}", file=sys.stderr)
        return 3
    print(config.get(root, args[1]))
    return 0


def cmd_pause(root: str, args: list[str]) -> int:
    no_args(args)
    os.makedirs(f"{root}/.factory", exist_ok=True)
    try:
        os.close(os.open(f"{root}/.factory/pause", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644))
    except FileExistsError:
        print("already paused")
        return 0
    events.append(root, "driver.paused", actor=actor())
    print("paused")
    return 0


def cmd_resume(root: str, args: list[str]) -> int:
    no_args(args)
    try:
        os.remove(f"{root}/.factory/pause")
    except FileNotFoundError:
        print("not paused")
        return 0
    events.append(root, "driver.resumed", actor=actor())
    print("resumed")
    return 0


# ---------------------------------------------------------------- status
def render(line: str) -> str:
    """`<ts> <event> <bead> <pr> <detail>` with null as `-`; a line that is not a JSON object stays raw."""
    try:
        obj = json.loads(line)
    except ValueError:
        return line
    if not isinstance(obj, dict) or any(type(obj.get(k)) not in (str, int, type(None)) for k in events.KEYS):
        return line
    detail = obj.get("detail")
    if isinstance(detail, str):
        detail = re.sub(r"[\n\r\t]", " ", detail)
    values = [obj.get("ts"), obj.get("event"), obj.get("bead"), obj.get("pr"), detail]
    return " ".join("-" if v is None else str(v) for v in values)


def cmd_status(root: str, args: list[str]) -> int:
    no_args(args)
    print("beads:")
    beads = tool_json(root, ["bd", "list", "--all", "--json"])
    statuses = [b.get("status") if isinstance(b, dict) else None for b in beads or []]
    if beads is None or any(not isinstance(s, str) for s in statuses):
        print("  unavailable")
    else:
        counts = Counter(statuses)
        for status in sorted(counts):
            print(f"  {status} {counts[status]}")
    print("prs:")
    prs = tool_json(root, ["gh", "pr", "list", "--state", "open", "--limit", "1000", "--json", "number"])
    print("  unavailable" if prs is None else f"  open {len(prs)}")
    print("events:")
    for line in events.tail(root, 10):
        print("  " + render(line))
    return 0


COMMANDS = {
    "doctor": cmd_doctor,
    "init": cmd_init,
    "event": cmd_event,
    "config": cmd_config,
    "pause": cmd_pause,
    "resume": cmd_resume,
    "status": cmd_status,
}


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="surrogateescape")
    root = os.environ.get("SMILE_ROOT")
    if not root:
        print("smile: SMILE_ROOT is not set; run through smile/smile", file=sys.stderr)
        return 2
    command = COMMANDS.get(argv[0]) if argv else None
    if command is None:
        print(f"smile: unknown command {argv[0] if argv else ''}", file=sys.stderr)
        return 2
    try:
        return command(root, argv[1:])
    except Usage as e:
        print(f"smile: {e}", file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001  any other failure: one stderr line, exit 1 (contract section 4)
        print(f"smile: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
