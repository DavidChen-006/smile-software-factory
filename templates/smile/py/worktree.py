"""Where the factory lives, and the work order the driver hands a worker (contract section 8).

The factory directory is resolved through git's common dir, so a linked worktree of the repo reads
and writes the main checkout's `.factory/`: one event log, one pause file, one set of run states.
Everything here is a lookup of the world (repo, spec_path) or a pure rendering of it (order); the
driver does the writing.
"""
from __future__ import annotations

import glob
import os
import re
import subprocess

TOOL_ENV = {**os.environ, "BD_NON_INTERACTIVE": "1"}  # bd must never open a prompt under a driver
PLACEHOLDERS = ("bead_id", "bead_title", "bead_description", "spec_path", "base_branch")
FIELD = re.compile(r"\{\{(" + "|".join(PLACEHOLDERS) + r")\}\}")


def repo(root: str) -> str:
    """The main checkout: the parent of the git common dir. `root` itself when git cannot answer."""
    proc = subprocess.run(["git", "-C", root, "rev-parse", "--path-format=absolute", "--git-common-dir"],
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False)
    common = proc.stdout.decode("utf-8", "surrogateescape").strip() if proc.returncode == 0 else ""
    return os.path.dirname(common) if common else root


def factory(root: str) -> str:
    return f"{repo(root)}/.factory"


def spec_path(root: str) -> str:
    """The newest docs/*SPEC*.md or docs/*DESIGN*.md as a repo-relative path; empty when there is none.

    Same mtime to the second on two files is common in a fresh clone, so the greater path breaks the tie
    and both runtimes name the same file.
    """
    found = glob.glob(f"{root}/docs/*SPEC*.md") + glob.glob(f"{root}/docs/*DESIGN*.md")
    newest = max(found, key=lambda p: (os.path.getmtime(p), p)) if found else ""
    return os.path.relpath(newest, root) if newest else ""


def order(template: str, values: dict) -> str:
    """The work order: one pass, so a value that itself looks like a placeholder is left alone."""
    return FIELD.sub(lambda m: values[m.group(1)], template)
