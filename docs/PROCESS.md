# Build process

How the SMILE factory itself gets built, spike by spike. This file governs the people and agents building the factory; `RUNTIME-CONTRACT.md` governs the product. Decided 2026-09-19 after S0 to S4 ran at 30 to 150 minutes per spike; the numbers below are the reason.

## Roles

Three roles, no others.

- **Lead** (the interactive session). Writes the brief, pins rulings into the contract, merges, and runs the watchtower cron. Never builds and never verifies by hand beyond a spot check.
- **Builder** (fresh Opus 5 subagent, one per spike or fix round). Reads the contract section for the spike, writes the code and the unit tests, runs the whole unit suite (`tests/all.sh`, never only its own file: S5 broke 18 driver tests that its builder never ran), pushes, reports. Budget 10 minutes. Runs nothing live: no fixtures, no GitHub, no real reviewer.
- **Verifier** (fresh subagent, Opus). Reads the feature map pages for the spike, drives the branch with the `verify-smile` primitives, pastes evidence, says MERGE or DO NOT MERGE. Budget 12 minutes. Verifies the spike's own evidence list, not every edge it can imagine; an edge worth testing later becomes a line in the next brief.

There is no code-reviewer role. Style and structure are the builder's job and the contract's job; the verifier checks behaviour only.

## Budgets

| Step | Budget | Enforced by |
|---|---|---|
| Build or fix round | 10 min | watchtower nudges at 10, stops at 15 |
| Verify | 12 min | watchtower nudges at 12, stops at 17 |
| Unit suite (`tests/all.sh`) | 5 min | a suite over 5 minutes is itself a defect to fix next |
| Whole spike, brief to merge | 20 min | lead reports overrun in `decisions.tsv` |

A spike that fails verification gets one fix round (a fresh builder with the verifier's evidence), then one re-verify. A second failure stops the line and goes to David.

## Unit suite rules

- Each test checks one behaviour with a fake `gh`, a fake worker, and in-process calls into the runtime modules. No test starts a real driver loop, waits on an interval, or opens a real tmux window; the mux seam has its own small suite for that and it runs in seconds.
- Shim-level tests (`uv run` per call) are a handful of smoke tests, not the body of the suite. `uv run` costs about 0.1 s per call and the S3 driver suite made hundreds.
- Long live drives belong to the verifier's harness, not to `tests/`.

## Watchtower

The lead keeps a 5-minute cron in its own session. Each tick lists the agents, compares elapsed time with the budgets, checks the herdr log for a stray Escape that killed a tool call, nudges or stops agents over budget, and acts on any report it has not acted on. It writes at most two lines to David per tick and nothing when nothing is running.

## Clock

`.claude/skills/factory-clock/scripts/factory-clock` reads the session's subagent transcripts and prints, per agent, wall time split into model time, live fixture time, unit tests, git, reading, editing, and killed calls, plus the longest calls. Run it after every spike; paste the spike's row into `decisions.tsv`. It is deterministic, needs no logging hooks, and works on any Claude Code session directory.

## Fixture workers

The verifier's fixture uses the stub worker script, no model at all, for every spike but the dogfood. When a real worker runs in a pane (S9), it runs on Opus: David's rule of 2026-09-19 is that no agent spawned for this build, by the lead or by the driver, runs on anything below Opus. Fable is never used for a subagent.

## Models

Opus is the floor. Builders, fix rounds, verifiers with a model override, and fixture workers are Opus. No Haiku, no Sonnet, whatever the size of the task.
