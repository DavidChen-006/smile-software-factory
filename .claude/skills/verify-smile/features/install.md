# Install

Install stamps the SMILE runtime, skills, config, and prompts into a target repo through `install.py`, refuses to overwrite a stamped file the user edited, and replaces it only with `--force`.

## Sub-features

- `install-stamp` copies every file the spec lists into a clean repo and prints one line per file.
- `install-idempotent` prints `unchanged` per file on a second run.
- `install-drift` refuses a drifted file and names the flag. (lands in S1)
- `install-force` replaces drifted files with `--force`. (lands in S1)

## How to get to it (user POV)

- Run `/smile install` in Claude Code inside the target repo.
- Run `uv run <smile-repo>/install.py <target> [--force]` in a terminal.

## Driving it with verify-smile

Preconditions:

- `uv` on PATH; the installer runs through `uv run`.
- A fixture in state `up`.
- The branch under test either ships `install.py` (manifest `install: stamped`) or not yet (`install: skipped`).

- **Stamp.** `verify-smile up` already ran the stamp. Run `verify-smile feature install`. Before S1 the result is `PASS install (stamp skipped, nothing stamped yet)` and the proof is `.beads/` plus the tmux session. From S1 on the result is `PASS install (stamped)` and the proof is an executable `<fixture>/smile/smile` and a `<fixture>/smile.config.yaml`.
- **Idempotent.** Run `uv run <smile-repo>/install.py <fixture>` a second time. Every line reads `unchanged <path>`. (lands in S1)
- **Drift.** Append a line to `<fixture>/smile.config.yaml`, run install again. Exit code `1` and a line `drifted <path>, use --force`. (lands in S1)
- **Force.** Run with `--force`. Exit code `0` and the file matches the template again. (lands in S1)
- **Proof.** `~/.smile-verify/<runid>/install.log` holds the feature output and `install-stamp.log` holds the stamp output.

## Gotchas

- The stamp uses the smile repo the skill lives in, so a fork's worktree stamps its own branch. Check `smile_commit` in the manifest.
- `install.py` failing at `up` time leaves the manifest at `install: stamp-failed`, and the feature fails until a new fixture is created.
