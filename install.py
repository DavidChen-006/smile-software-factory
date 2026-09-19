#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Stamp the SMILE templates into a target repo.

    uv run install.py <target-repo> [--force]

Copies every file under templates/ to the same relative path in the target, preserving file
modes, and prints one line per file: stamped, unchanged, drifted (differs and not overwritten),
or replaced (differs and --force given). A destination that is a symlink is reported as
`drifted <path>, symlink` and never written through. Appends `.factory/` to the target's
.gitignore when absent and prints `appended .gitignore`. Exit 1 when any file drifted without
--force or on an I/O error, 2 on usage error, else 0.
"""
import shutil
import sys
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent / "templates"
SKIP = {"__pycache__", ".DS_Store"}
GITIGNORE_LINE = b".factory/"


def stamp(target: Path, force: bool) -> int:
    drifted = 0
    files = sorted(
        (p for p in TEMPLATES.rglob("*") if p.is_file() and not SKIP & set(p.parts)),
        key=lambda p: p.relative_to(TEMPLATES).parts,
    )
    for src in files:
        rel = src.relative_to(TEMPLATES)
        dst = target / rel
        if src.is_symlink():
            print(f"install.py: skipping symlink template {rel}", file=sys.stderr)
        elif dst.is_symlink():
            drifted += 1
            print(f"drifted {rel}, symlink")
        elif not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(src, dst)
            print(f"stamped {rel}")
        elif dst.read_bytes() == src.read_bytes():
            shutil.copymode(src, dst)
            print(f"unchanged {rel}")
        elif force:
            shutil.copy(src, dst)
            print(f"replaced {rel}")
        else:
            drifted += 1
            print(f"drifted {rel}, use --force")

    gitignore = target / ".gitignore"
    data = gitignore.read_bytes() if gitignore.exists() else b""
    if GITIGNORE_LINE in {line.rstrip(b" \t\r") for line in data.split(b"\n")}:
        print("unchanged .gitignore")
    else:
        with gitignore.open("ab") as f:
            if data and not data.endswith(b"\n"):
                f.write(b"\n")
            f.write(GITIGNORE_LINE + b"\n")
        print("appended .gitignore")
    return 1 if drifted else 0


def main(argv: list[str]) -> int:
    force = "--force" in argv
    args = [a for a in argv if a != "--force"]
    if len(args) != 1:
        print("usage: uv run install.py <target-repo> [--force]", file=sys.stderr)
        return 2
    target = Path(args[0]).resolve()
    if not target.is_dir():
        print(f"install.py: not a directory: {target}", file=sys.stderr)
        return 2
    try:
        return stamp(target, force)
    except OSError as e:
        print(f"install.py: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
