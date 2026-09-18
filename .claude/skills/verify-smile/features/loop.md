# Loop

Loop is the driver taking every ready bead from claim to a worker pane, reaping the pane when the
bead closes, and exiting when no bead is open. (landed in S3; the review lane and the merges that
close the beads land in S4)

## Sub-features

- `loop-claim` claims each ready bead, acquires a worktree, spawns a pane, and logs `bead.claimed`, `worktree.acquired`, `pane.spawned`.
- `loop-order` claims B only after A is closed, because bd hides blocked beads.
- `loop-reap` kills the pane of a closed bead, returns its worktree, logs `pane.reaped`, and moves the run state file to `.factory/runs/done/`.
- `loop-complete` logs `campaign.complete`, removes the pid file, and exits when no bead is open and no run is live.
- `loop-crash` logs `worker.crashed` when a pane dies with its bead open, respawns once, then escalates and leaves the bead claimed.
- `loop-singleton` refuses a second driver for the same repo.
- `loop-pause` claims nothing while `.factory/pause` exists, and logs nothing about it.

## How to get to it (user POV)

- Run `smile run` in the stamped repo and watch panes appear in the multiplexer.
- Run `smile run --once` for a single tick, `--interval <seconds>` for a slower or faster loop.
- Run `smile status` to see bead counts, open PRs, and the last events.

## Driving it with verify-smile

Preconditions:

- A fixture with `install: stamped`, beads A and B seeded, B blocked by A.
- `SMILE_WORKER_CMD` points at `scripts/stub-worker`. The helper sets it; nothing else spawns workers in S3.

- **Claim tick.** Run `verify-smile feature loop --runtime bash`. The helper sets `runtime: <r>` in the fixture config, runs `smile init` so the treehouse pool and `.factory/` exist, seeds a third bead C with no blockers so exactly A and C are ready, then runs `<fixture>/smile/smile run --once`. Each of A and C has exactly one `bead.claimed`, one `worktree.acquired`, and one `pane.spawned` in `.factory/events.jsonl`, and `.factory/runs/` holds two run state files.
- **Pull requests.** The helper polls `gh pr list --state open --json number,body` for up to 200 seconds until two open PRs carry a `Bead: <id>` trailer for A and C. The GitHub API lags behind the worker's `gh pr create`, so this is a poll, not a single read.
- **Reap tick.** The helper closes A, C, and B with `bd close` (in S4 the review lane closes them), then runs `smile run --once` again. Each of A and C has one `pane.reaped`, `.factory/runs/done/` holds two files, the log ends with `campaign.complete`, and `.factory/driver.pid` is gone.
- **Not driven live.** The singleton refusal, the stale pid file, the `max_parallel` cap, the pause skip, crash respawn and escalation, the work order substitution, the worker argv and environment, and the trust edit. `tests/driver.test.sh` proves those against scratch repos with real bd and treehouse and a fake tmux.
- **Proof.** `~/.smile-verify/<runid>/loop.log` holds both ticks, the PR list, and the last fifteen events. It prints `PASS loop (runtime=<r>)` or `FAIL loop: <reason>`, and `NOT IMPLEMENTED loop (no smile/<r>/run stamped)` with exit 2 when the runtime under test has no driver.

## Gotchas

- S3 stops at `pane.reaped`. The spec's live box for S3 names `pr.opened`, `review.started`, `review.verdict`, `pr.merged`, and `bead.closed` as well; those are the review lane, which lands in S4, and this feature file is re-driven then.
- The helper points `HOME` at `~/.smile-verify/<runid>/home`, because the driver writes the trust flag into `~/.claude.json` and treehouse pools its worktrees under `$HOME`. Nothing under the real home is linked into it. The run gets its own `GIT_CONFIG_GLOBAL` holding the `!gh auth git-credential` helper and the real `user.name`/`user.email`, plus `GIT_CONFIG_NOSYSTEM=1`, because the Xcode command-line tools put `credential.helper = osxkeychain` in the *system* config, which still applies under `GIT_CONFIG_GLOBAL`, and a scratch home has no login keychain, so git would make macOS pop a "reset keychain" dialog on every fetch and push. gh keeps this account's token in that keyring, so the helper is answered from `GH_TOKEN`, read once while `HOME` is still the real one; no token is written to disk. The worker pane gets the same scratch world through a wrapper script, since a pane inherits the multiplexer session's environment, not the driver's. `down` removes a `home/Library` link an older run left behind.
- The stub worker pushes to the fixture's `main`, so a leftover branch protection on the account would break it. The fixture has none.
- A pane inherits the multiplexer session's environment, not the driver's, so the four worker variables ride on the command line through `env`. Asserting them belongs to `tests/driver.test.sh`, where the fake tmux runs the command itself.
- The helper never kills a window it did not spawn; the reap tick kills the two it opened, and `verify-smile down` owns the session.
- A tick shorter than the stub's push plus PR create could double-claim if the driver read bd before its own claim committed. Assert exactly one `bead.claimed` per bead, as this feature does.
