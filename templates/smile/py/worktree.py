"""Where the factory lives, and the work order the driver hands a worker (contract section 8).

The factory directory is resolved through git's common dir, so a linked worktree of the repo reads
and writes the main checkout's `.factory/`: one event log, one pause file, one set of run states.
Everything here is a lookup of the world (repo, spec_path) or a pure rendering of it (order); the
driver does the writing.
"""

import glob
import os
import re
import subprocess

TOOL_ENV = {**os.environ, "BD_NON_INTERACTIVE": "1"}  # bd must never open a prompt under a driver
FIELD = re.compile(r"\{\{([a-z_]+)\}\}")


def stderr(proc: subprocess.CompletedProcess) -> str:
    return next(iter(proc.stderr.decode(errors="replace").splitlines()), "no output")


def tool(cwd: str, argv: list) -> str:
    """Run a tool and return its stdout; a non-zero exit is one line and exit 1 through main.

    Every shell-out in the runtime lands here, so one place decides the environment and what a
    failure reads like.
    """
    proc = subprocess.run(argv, cwd=cwd, env=TOOL_ENV, capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"{' '.join(argv[:2])} failed: {stderr(proc)}")
    return proc.stdout.decode("utf-8", "surrogateescape")


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


def render(template: str, values: dict) -> str:
    """A prompt with its placeholders filled: one pass, so a value that looks like one is left alone.

    A `{{name}}` the caller has no value for stays as it is: the work order and the review prompt
    substitute different sets, and neither should eat the other's placeholders.
    """
    return FIELD.sub(lambda m: values.get(m.group(1), m.group(0)), template)
