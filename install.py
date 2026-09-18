#!/usr/bin/env python3
"""Stamp the SMILE templates into a target repo.

    python3 install.py <target-repo> [--force]

Copies every file under templates/ to the same relative path in the target, preserving file
modes, and prints one line per file: stamped, unchanged, drifted (differs and not overwritten),
or replaced (differs and --force given). Appends `.factory/` to the target's .gitignore when
absent and prints `appended .gitignore`. Exit 1 when any file drifted without --force, else 0.
"""
import shutil
import sys
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent / "templates"
SKIP = {"__pycache__", ".DS_Store"}
GITIGNORE_LINE = ".factory/"


def stamp(target: Path, force: bool) -> int:
    drifted = 0
    files = sorted(p for p in TEMPLATES.rglob("*") if p.is_file() and not SKIP & set(p.parts))
    for src in files:
        rel = src.relative_to(TEMPLATES)
        dst = target / rel
        if not dst.exists():
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
    lines = gitignore.read_text().splitlines() if gitignore.exists() else []
    if GITIGNORE_LINE in lines:
        print("unchanged .gitignore")
    else:
        with gitignore.open("a") as f:
            if lines and not gitignore.read_text().endswith("\n"):
                f.write("\n")
            f.write(GITIGNORE_LINE + "\n")
        print("appended .gitignore")
    return 1 if drifted else 0


def main(argv: list[str]) -> int:
    force = "--force" in argv
    args = [a for a in argv if a != "--force"]
    if len(args) != 1:
        print("usage: python3 install.py <target-repo> [--force]", file=sys.stderr)
        return 2
    target = Path(args[0]).resolve()
    if not target.is_dir():
        print(f"install.py: not a directory: {target}", file=sys.stderr)
        return 2
    return stamp(target, force)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
