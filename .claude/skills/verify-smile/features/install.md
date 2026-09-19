# Install

Install stamps the SMILE runtime, skills, config, and prompts into a target repo through `install.py`, refuses to overwrite a stamped file the user edited, and replaces it only with `--force`.

## Sub-features

- `install-stamp` copies every file the spec lists into a clean repo and prints one line per file.
- `install-idempotent` prints `unchanged` per file on a second run.
- `install-drift` refuses a drifted file and names the flag.
- `install-force` replaces drifted files with `--force`.
- `install-init` leaves the repo ready to drive: `smile init` creates `.beads`, `treehouse.toml`, `.worktreeinclude`, `.factory`, and `.factory/events.jsonl`.

## How to get to it (user POV)

- Run `/smile install` in Claude Code inside the target repo.
- Run `uv run <smile-repo>/install.py <target> [--force]` in a terminal.
- Run `smile init` once in the stamped repo.

## Driving it with verify-smile

Preconditions:

- A fixture in state `up` that has not been stamped.
- The checkout under test ships `install.py`. `--from` defaults to the checkout this skill lives in, so a spike branch stamps itself.

- **Stamp.** `verify-smile stamp` runs `uv run <checkout>/install.py <fixture>`, commits and pushes the stamp as a user would, then runs `smile init`. It prints `source`, `source_commit`, `stamp_commit`, `init` (the init lines) and `log` (the installer transcript).
- **Idempotent.** Run the installer a second time by hand against the same fixture path, `uv run <checkout>/install.py <fixture>`. Every line reads `unchanged <path>`.
- **Drift.** Append a line to `<fixture>/smile.config.yaml` and run the installer again. Exit `1` and a line `drifted <path>, use --force`.
- **Force.** Run it with `--force`. Exit `0`, and the file matches the template again.
- **Stamp is real.** `verify-smile doctor` reports `stamp.shim` ok for `<fixture>/smile/smile` and runs `smile doctor` through it.

## Evidence that proves it

- `stamp`'s object: `init` is exactly `["exists .beads", "created treehouse.toml", "created .worktreeinclude", "created .factory", "created .factory/events.jsonl"]` on a fixture `up` already `bd init`-ed, and `stamp_commit` is a full SHA.
- The manifest at `~/.smile-verify/<runid>/manifest.json` reads `"install": "stamped"`, and `verify-smile list` shows `install: stamped` for the run.
- `~/.smile-verify/<runid>/install-stamp.log` holds one line per stamped file; the second run's transcript is all `unchanged`.
- `verify-smile doctor` prints `{"name": "stamp.shim", "ok": true, ...}` naming an executable `<fixture>/smile/smile`.
- The stamp is on `main` on GitHub, not just on disk: the fixture's `git log` carries `chore: stamp smile` and the push succeeded, so a later worker's `pull --rebase` has it.

## Gotchas

- `--from` defaults to the checkout this skill lives in, so a worktree stamps its own branch. Read `source_commit` in the `stamp` object to see which.
- A failed installer leaves the manifest at `install: stamp-failed` and `stamp` refuses to continue. Read the log it names; do not repair the fixture in place.
- `stamp` commits and pushes, because an unstaged edit to `.gitignore` (which `bd init` wrote) makes the stub worker's `pull --rebase` refuse later.
- `smile init` is idempotent, so `stamp` is safe to think of as "leave the fixture drivable", but the first line is `exists .beads`, not `created`: `up` already ran `bd init`.
- `treehouse init` prints to stderr, including an update notice. That is not part of the `init` lines in the JSON.
