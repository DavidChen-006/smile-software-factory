# Loop

Loop is the driver taking every ready bead from claim to a worker pane, holding it while review runs, reaping the pane when the bead closes, and exiting when no bead is open.

## Sub-features

- `loop-claim` claims each ready bead, acquires a worktree, spawns a pane, and logs `bead.claimed`, `worktree.acquired`, `pane.spawned`.
- `loop-order` claims a blocked bead only after its blocker closes, because bd hides blocked beads.
- `loop-waiting` moves the run state file to `.factory/runs/waiting/` with no event when the pane died, the bead is open, and the log holds a `pr.opened` for it.
- `loop-reap` kills the pane of a closed bead, returns its worktree, logs `pane.reaped`, and moves the run state file to `.factory/runs/done/`.
- `loop-crash` logs `worker.crashed` when a pane dies with its bead open and no PR, respawns once, then escalates with a second `worker.crashed` (`detail` `escalated`), moves the file to `.factory/runs/crashed/`, and leaves the bead claimed.
- `loop-complete` logs `campaign.complete`, removes the pid file, and exits when no bead is open and no run is live.
- `loop-pause` claims nothing while `.factory/pause` exists, and logs nothing about pausing.
- `loop-singleton` refuses a second driver for the same repo.
- `loop-trust` marks each worktree trusted in `~/.claude.json` before spawning into it.

## How to get to it (user POV)

- Run `smile run` in the stamped repo and watch panes appear in the multiplexer.
- Run `smile run --once` for a single tick, `--interval <seconds>` for a slower or faster loop.
- Run `smile pause` and `smile resume`.
- Run `smile status` to see bead counts, open PRs, and the last events.

## Driving it with verify-smile

Preconditions:

- A fixture with `install: stamped` and beads from `verify-smile seed`. Two independent beads is the smallest interesting case; `seed --beads 1 --deps <id>` adds a blocked one for `loop-order`.

- **Claim tick.** `verify-smile tick` runs one `smile run --once` in the run world. The object it prints carries `exit` and every event appended during the tick.
- **Live state.** `verify-smile runs` lists the run state files under `live`, one per claimed bead, each with `bead`, `worktree`, `handle`, `order`, `attempts`, `spawned_at`. `verify-smile panes` shows one window per spawned bead. `verify-smile trust` shows each worktree path mapped to `true`.
- **Pull requests.** `verify-smile prs` lists one open PR per bead with its `Bead:` trailer resolved into the `bead` field. GitHub's API lags the worker's `gh pr create` by seconds, so re-read `prs` rather than assuming the first read is final.
- **Order.** With a bead seeded `--deps <blocker>`, the claim tick logs no `bead.claimed` for it. After `verify-smile close-bead <blocker>`, the next `verify-smile tick` claims it.
- **Waiting.** After the workers open their PRs and their panes exit, `verify-smile tick` moves each run file to `waiting` with no event of its own. `verify-smile runs` shows them under `waiting`, not `live`.
- **Reap.** Once the beads are closed (by the review lane, or by `verify-smile close-bead <id>` standing in for it), `verify-smile tick` logs one `pane.reaped` per bead whose pane is still alive, moves each run file to `done`, and logs `campaign.complete`. The reap always lags a tick behind `bead.closed`: the tick that closes the bead leaves its run file under `waiting`, and only the next tick moves it to `done`. A bead whose stub-worker pane already exited gets no `pane.reaped` of its own; the only `pane.reaped` of that tick is the watchtower's.
- **Crash and escalation.** `verify-smile tick --worker-crash <bead>` makes the stub worker exit 3 for that bead. The flag reaches the pane through the fixture tmux session's environment for that tick only, because a pane inherits the session's environment and not the driver's. Tick again: `worker.crashed` (`detail` `attempt 1`) and a respawn with a second `pane.spawned` and no new `bead.claimed`. Tick again: a second `worker.crashed` with `detail` `escalated`, and the run file under `crashed`.
- **Real worker.** `verify-smile tick --worker real` runs the tick with no `SMILE_WORKER_CMD`, so the driver spawns its own `claude -p --model <worker.model> --permission-mode <worker.permission_mode> <order text>` in the pane, and runs the whole tick under the caller's real `HOME` because the scratch one is not signed in; the fixture account still rides `GH_TOKEN` and `GH_CONFIG_DIR` on the tmux session, so the push and the pull request land on the fixture repo. `verify-smile seed --title <text> --description <text>` is how that bead gets a real order. Expect minutes per bead.
- **Pause.** `verify-smile time pause --n 1` creates `.factory/pause` and logs `driver.paused`. The next `verify-smile tick` claims nothing. `verify-smile time resume --n 1` removes it and logs `driver.resumed`.
- **Not driven live.** The singleton refusal, the stale pid file, the `max_parallel` cap, the work order substitution, and the worker argv. `tests/driver.test.sh` proves those against scratch repos with real bd and treehouse and a fake tmux.

## Evidence that proves it

- Per bead, in order, from `verify-smile events --bead <id>`: `bead.claimed`, `worktree.acquired` (`detail` the worktree path), `pane.spawned` (`detail` the handle). Exactly one of each; a repeated `bead.claimed` is a double claim, which is a finding.
- `verify-smile runs`: two live entries after the claim tick, the same two under `waiting` after the workers finish, the same two under `done` after the reap tick, and `live` empty at the end.
- `verify-smile prs`: one object per bead with `"state": "OPEN"` and a non-null `bead`, later `"state": "MERGED"` with a `mergedAt` timestamp. GitHub's own answer, not the driver's summary.
- `verify-smile panes`: the window count rises by one per claimed bead, plus one `watchtower` window from the first tick, and falls back after the reap. A stub worker without `--worker-sleep` is usually gone before you read `panes`, so the worker windows may never be observable at all.
- `verify-smile trust`: one entry per acquired worktree, each `true`, and the path under `~/.smile-verify/<runid>/home/.claude.json`, never the real home.
- The last events of the run: `pane.reaped` per bead, then one `campaign.complete` with a null bead. `<fixture>/.factory/driver.pid` does not exist afterwards.
- For the crash path: `worker.crashed` `attempt 1`, a second `pane.spawned` for the same bead with no second `bead.claimed`, then `worker.crashed` `escalated`, and the bead still claimed in `beads.json`.

## Gotchas

- A closed bead is invisible to plain `bd list --json`, which prints `[]`; read it back with `bd list --all --json` (or from `beads.json` in the evidence directory). The driver itself reads status that way (`Driver.reap` calls `bd list --all --json`). Do not read an empty `bd list` as a lost bead.
- The run world points `HOME` at `~/.smile-verify/<runid>/home`, because the driver writes the trust flag into `~/.claude.json` and treehouse pools its worktrees under `$HOME`. Nothing under the real home is linked into it. The run gets its own `GIT_CONFIG_GLOBAL` holding the `!gh auth git-credential` helper and the real `user.name`/`user.email`, plus `GIT_CONFIG_NOSYSTEM=1`, because the Xcode command-line tools put `credential.helper = osxkeychain` in the *system* config, which still applies under `GIT_CONFIG_GLOBAL`, and a scratch home has no login keychain, so git would make macOS pop a "reset keychain" dialog on every fetch and push. gh keeps this account's token in that keyring, so the helper is answered from `GH_TOKEN`, read once while `HOME` is still the real one. That token is never written under the evidence directory, which survives `down`: it reaches a pane through the fixture tmux session's own environment (`tmux set-environment`), which dies with the session, and reaches the driver and its `smile review` subprocess through their own process environments. The wrapper files under `home/` carry `HOME` and the git settings and nothing else. The worker pane and the reviewer subprocess both re-enter that world through a wrapper, since a pane inherits the multiplexer session's environment, not the driver's.
- A tick that exits non-zero (a gh hiccup, bd contention on a concurrent read) is reported in the JSON and is not by itself a failure: the next tick re-reads the world. Only the end state decides.
- The stub worker pushes to the fixture's `main`, so a leftover branch protection on the account would break it. A fresh fixture has none.
- A tick shorter than the stub's push plus PR create could double-claim if the driver read bd before its own claim committed. Assert exactly one `bead.claimed` per bead.
- Without `--worker-sleep` the worker's pane is usually gone before you can look at it. That is why `waiting` appears on the very next tick.
- `--worker-crash <bead>` keeps crashing for as long as you pass it, so the respawn and the escalation are separate ticks you choose, not a race.
- Never kill a window this run did not spawn. `kill-pane` only ever kills the handle in a run state file, and `down` owns the session.
