---
name: smile
description: >-
  Install and operate the SMILE software factory in a target repo. Use on "/smile",
  "install smile", "smile doctor", or "smile init". Stamps the smile CLI, config, prompts,
  and skills through install.py, then checks prerequisites and initializes the repo.
---

# smile

SMILE stamps a small CLI into a repo and drives its build loop from there. Three steps put a repo on the factory.

## Install

From the target repo, stamp the templates. `<smile-repo>` is this checkout.

	uv run <smile-repo>/install.py <target-repo>

One line per file: `stamped`, `unchanged`, `drifted <path>, use --force`, or `replaced`. A drifted file is one the user edited after stamping; `--force` overwrites it. The installer also adds `.factory/` to the target's `.gitignore`.

## Doctor

	smile/smile doctor

Eight lines, one per prerequisite, `ok <tool>` or `missing <tool> <reason>`, for uv, git, gh, gh-auth, claude, bd, treehouse, and mux (one of tmux, cmux, herdr). Exit 1 when anything is missing. Fix every `missing` line before init.

`uv` comes first because everything else runs through it: the shim execs `uv run` on the runtime, and the installer and the tests run the same way. uv fetches the interpreter named by each script's PEP 723 header, so the machine's own `python3` is not a prerequisite.

## Init

	smile/smile init

Runs `bd init`, writes `treehouse.toml` and `.worktreeinclude`, and creates `.factory/` with an empty `events.jsonl`. Prints `created <thing>` or `exists <thing>` per step and is safe to rerun.

## Reference

Design and spike plan: `docs/SPEC.md`. Command formats, config keys, and the event log schema: `docs/RUNTIME-CONTRACT.md`.
