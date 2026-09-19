# SMILE verification map

This directory is the maintained source for verifying the user-facing behavior of SMILE. Read the index, then the page for the behavior under test, then drive it with the `verify-smile` primitives. The map says how to reach a behavior and what observable end state proves it. It never says PASS: you compose the primitives, read the end state, and paste it.

## Baseline preconditions

- `uv`, `git`, `gh` logged in, `bd`, `treehouse`, and `tmux` are on PATH. Everything SMILE runs, the shim, the runtime, the installer, and the `tests/*-py.test.sh` wrappers, goes through `uv run`, which picks the interpreter from each entry point's PEP 723 header.
- A fixture from `verify-smile up` is in state `up`. Its manifest is at `~/.smile-verify/<runid>/manifest.json`.
- `verify-smile stamp` has stamped the branch under test into the fixture and run `smile init`, so the manifest says `install: stamped`.
- `verify-smile seed --beads <n>` has created the beads the page needs.
- `verify-smile doctor` exits 0.
- Never drive a fixture this run did not create.

## Gotchas that apply to every page

- The harness itself needs `python3` on PATH even though SMILE does not. SMILE's shim execs `uv run` and never asks for a system interpreter, but `verify-smile`'s own JSON shaping falls back to `uv run python` while the stub worker's issue lookup and the fake `gh` in `tests/` hard-code `#!/usr/bin/env python3`. On a machine with only `uv`, the fixture drives and SMILE passes, but the stub worker's fix round and the unit tests' fake GitHub do not run.

## Driving conventions

- Every primitive prints JSON on stdout: one object, or one object per line for a listing. Read the JSON, never a prose summary.
- Every primitive takes `--run <runid>` and uses the newest run when it is left out. `<verb> --help` prints its own usage.
- Only `doctor` decides pass or fail. Every other verb reports what happened, including a non-zero tick exit, and leaves the judgment to you.
- `tick` is one `smile run --once` with the stub worker and stub reviewer wired in. Drive a multi-step behavior by ticking until the end state appears, not by sleeping a fixed time.
- Read state from `prs`, `issues`, `events`, `runs`, `panes`, and `trust`. Never from the driver's stdout.
- Do not remove proof artifacts during cleanup. `down` keeps the evidence directory.

## Proof and skip reporting

- A proof names the action (the exact primitive invocations) and the resulting state (the JSON those invocations printed), in that order.
- Prove a mutation from a second, read-only view: a merge from `prs` (GitHub's own `state` and `mergedAt`), a closed bead from `close-bead`'s read-back or `beads.json`, an event from `events`.
- Prove side effects too: the run state files under `runs`, the windows under `panes`, the trust entries under `trust`, the files under `evidence`.
- Report an unreachable path with the attempted command and the unmet precondition. Do not report a skipped entry point as verified through a different path.

## Feature entry contract

Each page starts with an H1 title and one paragraph describing the user-visible behavior, then uses these H2 sections in this order.

1. `Sub-features` lists short ids with one line for each behavior.
2. `How to get to it (user POV)` lists every user entry point.
3. `Driving it with verify-smile` starts with `Preconditions:` and pairs each user action with the exact primitive invocation and what it prints.
4. `Evidence that proves it` lists the observable end states: event lines in order, PR and issue states, pane counts, run-file locations, file contents.
5. `Gotchas` lists traps that can waste or invalidate a verification run.

Keep implementation details out of the map. Name only user paths, stable handles, required state, commands, and observable proof.

## Features

- [Install](./install.md) stamping SMILE into a repo, idempotence, drift refusal, and force.
- [Doctor](./doctor.md) the prerequisite checks and their exit codes.
- [Mux](./mux.md) spawning, probing, and killing panes through the backend seam.
- [Loop](./loop.md) claim, spawn, waiting, reap, crash and escalation, pause, singleton.
- [Review](./review.md) verdicts, finding issues, the fix round, and the merge.
- [Gate](./gate.md) the modes, the `smile:approved` label, and the manual merge close.
- [Audit](./audit.md) merges with no `APPROVE` verdict at their head SHA.
- [uv runtime](./uv-runtime.md) the shim on a PATH with no `python3`, and what the indirection costs.
