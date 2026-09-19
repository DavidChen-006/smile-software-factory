# SMILE verification map

This directory is the maintained source for verifying the user-facing behavior of SMILE. Read the index before driving, then use the matching feature file as the recipe.

## Baseline preconditions

- `uv`, `git`, `gh` logged in, `bd`, `treehouse`, and `tmux` are on PATH. Everything SMILE runs, the shim, the runtime, the installer, and the `tests/*-py.test.sh` wrappers, goes through `uv run`, which picks the interpreter from each entry point's PEP 723 header.
- A fixture from `verify-smile up` is in state `up`. Its manifest is at `~/.smile-verify/<runid>/manifest.json`.
- The fixture has beads A and B seeded, B blocked by A, and `bd ready --json` lists only A.
- The tmux session `smile-verify-<runid>` exists.
- SMILE is stamped when the branch under test ships `install.py`. Before S1 the manifest says `install: skipped`.
- Never drive a fixture this run did not create.

## Driving conventions

- Start every recipe from the baseline unless its preconditions say otherwise.
- Run the loop with `SMILE_WORKER_CMD` set to `scripts/stub-worker` and `SMILE_REVIEW_CMD` set to `scripts/stub-reviewer` unless the recipe says `--real-review`.
- Treat every command as literal. Keep names and flags unchanged.
- Read state from bd, gh, and `.factory/events.jsonl`. Never from the driver's stdout.
- Do not remove proof artifacts during cleanup.

## Proof and skip reporting

- CLI proof includes the command, stdout, stderr, and exit code, appended to `~/.smile-verify/<runid>/<feature>.log`.
- Mutation proof includes a read-only second view of the stored value. A merged PR is proven by `gh pr view --json state`, a closed bead by `bd list --json`.
- Record the feature id and entry point used with every artifact.
- Report an unreachable path with the attempted command and the unmet precondition.
- Do not report a skipped entry point as verified through a different path.

## Feature entry contract

Each feature file starts with an H1 title and one paragraph describing the user-visible behavior. It then uses exactly four H2 sections in this order.

1. `Sub-features` lists short ids with one line for each behavior.
2. `How to get to it (user POV)` lists every user entry point.
3. `Driving it with verify-smile` starts with `Preconditions:` and uses labeled bullets that pair each user action with an exact command and observable result.
4. `Gotchas` lists traps that can waste or invalidate a verification run.

Keep implementation details out of the map. Name only user paths, stable handles, required state, commands, and observable proof.

## Features

- [Install](./install.md) covers stamping SMILE into a repo, drift refusal, and force. Landed in S0 for the stamp check, completed in S1.
- [Doctor](./doctor.md) covers prerequisite checks and their exit codes. Lands in S1.
- [Mux](./mux.md) covers spawning, probing, and killing panes through the backend seam. Lands in S2.
- [Loop](./loop.md) covers the driver taking two beads from claim to merged PR and closed bead. Lands in S3.
- [Review](./review.md) covers the request-changes issue loop, the fix round, and the real reviewer lane. Lands in S4.
- [Gate](./gate.md) covers the human gate holding an approved PR until a person merges it. Lands in S4.
- [Watchtower](./watchtower.md) covers escalation on a crashing worker and the pause file. Lands in S5.
- [Narrate](./narrate.md) covers the planner session replaying new events once each. Lands in S6.
