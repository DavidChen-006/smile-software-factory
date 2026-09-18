# Loop

Loop is the driver taking every ready bead from claim to a merged pull request and a closed bead, with one worker pane per bead, and exiting when no bead is open. (lands in S3)

## Sub-features

- `loop-claim` claims each ready bead, acquires a worktree, spawns a pane, and logs `bead.claimed`, `worktree.acquired`, `pane.spawned`.
- `loop-order` claims B only after A is closed, because bd hides blocked beads.
- `loop-close` merges an approved PR, closes the bead, reaps the pane, and logs `pr.merged`, `bead.closed`, `pane.reaped`.
- `loop-complete` logs `campaign.complete` and exits when no bead is open.
- `loop-singleton` refuses a second driver for the same repo.
- `loop-pause` claims nothing while `.factory/pause` exists.

## How to get to it (user POV)

- Run `smile run` in the stamped repo and watch panes appear in the multiplexer.
- Run `smile run --once` for a single tick.
- Run `smile status` to see bead counts, open PRs, and the last events.

## Driving it with verify-smile

Preconditions:

- A fixture with `install: stamped`, beads A and B seeded, B blocked by A.
- `SMILE_WORKER_CMD` points at `scripts/stub-worker` and `SMILE_REVIEW_CMD` at `scripts/stub-reviewer`.

- **Run to completion.** Run `verify-smile feature loop --runtime bash`. The helper starts `<fixture>/smile/smile run --interval 5` with a 10 minute timeout and waits for a `campaign.complete` line in `<fixture>/.factory/events.jsonl`.
- **Both beads closed.** `bd list --json` shows A and B with status `closed`.
- **Both PRs merged.** `gh pr list --state merged --json number,headRefName` lists `smile/<A>` and `smile/<B>`.
- **Event order per bead.** For each bead id the events in order are `bead.claimed`, `worktree.acquired`, `pane.spawned`, `pr.opened`, `review.started`, `review.verdict`, `pr.merged`, `bead.closed`, `pane.reaped`.
- **Singleton.** While the driver runs, a second `smile run --once` prints a line containing `already running` and exits 0 without claiming.
- **Proof.** `~/.smile-verify/<runid>/loop.log` holds the wait transcript. `down` copies `events.jsonl` into `factory/`.

## Gotchas

- The stub worker pushes to `main` of the fixture, so a leftover branch protection on the account would break it. The fixture has none.
- A tick shorter than the stub's push plus PR create can double-claim if the driver reads bd before its own claim commits. Assert exactly one `bead.claimed` per bead.
- Timeout is a `FAIL`, not `INCONCLUSIVE`. Report the last ten events.
