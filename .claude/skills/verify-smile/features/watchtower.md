# Watchtower

The watchtower is one long-lived observer pane per campaign. The driver spawns it right after `campaign.start`, respawns it whenever its handle is dead, and kills it just before `campaign.complete`. It reports and escalates; it never edits code, beads, or GitHub.

## Sub-features

- `watch-spawn` spawns the pane on the first tick when config `watchtower` is `on`, logs `pane.spawned` with a null bead, and writes `.factory/watchtower.json` (`handle`, `spawned_at`).
- `watch-off` spawns nothing and logs nothing when config `watchtower` is `off`.
- `watch-respawn` spawns a new pane with a new `pane.spawned` on any later tick where the recorded handle is dead. No attempt cap.
- `watch-reap` kills the pane, logs `pane.reaped` (null bead), and removes `.factory/watchtower.json` before `campaign.complete`.
- `watch-log` appends one `<ts> <event> <bead> <detail>` line per new event to `.factory/watch.md`, null fields as `-`, tailing the log from where it stood when the pane started.
- `watch-escalate` runs `smile event watch.escalation bead=<id> actor=watchtower detail="crashed twice"` and then `smile pause` once per bead on `worker.crashed` with `detail` `escalated`, and never removes the pause file.

## How to get to it (user POV)

- Set `watchtower: on` in `smile.config.yaml` (the default) and run `smile run`. A window named `watchtower` appears in the multiplexer session alongside the worker windows.
- Read `.factory/watch.md` while the campaign runs; read `.factory/watchtower.json` for the live handle.
- After an escalation, the campaign is paused: `smile status` shows it, and `smile resume` is the human's move.

## Driving it with verify-smile

Preconditions: a fixture with `install: stamped` and at least one seeded bead. The run world points `SMILE_WATCHTOWER_CMD` at `scripts/stub-watchtower` wherever it points `SMILE_WORKER_CMD` at `scripts/stub-worker`, so the pane is the deterministic stub, not a model.

- **Spawn.** `verify-smile tick` runs one `smile run --once`. Its appended events carry `campaign.start` and then a `pane.spawned` with a null bead. `verify-smile panes` lists a window named `watchtower` in the fixture session.
- **Escalation.** `verify-smile tick --worker-crash <bead>` twice, then tick again: the driver writes `worker.crashed` `attempt 1`, respawns, then `worker.crashed` `escalated`. The stub in the watchtower pane sees that line and appends `watch.escalation` and `driver.paused`.
- **Pause holds.** The next `verify-smile tick` claims no bead and `verify-smile runs` is unchanged until `verify-smile time resume --n 1`.
- **Reap.** When the last bead closes, the completing tick logs `pane.reaped` with a null bead immediately before `campaign.complete`, and the `watchtower` window is gone from `verify-smile panes`.
- **Reading the watch.** There is no `watch` primitive. `verify-smile evidence` copies the whole factory directory, so read `.factory/watch.md` and `.factory/watchtower.json` from the fixture path that `verify-smile list` prints, or from the evidence directory after the run.
- **Not driven live.** The config flag, the respawn of a dead handle, the `SMILE_WATCHTOWER_CMD` argv, and the stub's own escalation are proved offline by `tests/watchtower.test.sh`.

## Evidence that proves it

- From `verify-smile events`: `campaign.start`, then `pane.spawned` with `"bead": null` and `"actor": "driver"` whose `detail` is a handle in the section 7 grammar; at the end `pane.reaped` with `"bead": null` immediately before `campaign.complete`.
- `.factory/watchtower.json`: `{"handle": "...", "spawned_at": "..."}` with the same handle and timestamp as that `pane.spawned`, and the file absent after the reap.
- `verify-smile panes`: one more window than the bead panes, named `watchtower`, present from the first tick and gone after the reap.
- `.factory/watch.md`: non-empty and growing across ticks, one `<ts> <event> <bead> <detail>` line per event the pane saw.
- For the escalation: `worker.crashed` `attempt 1`, then `worker.crashed` `escalated`, then `watch.escalation` with the bead, `"actor": "watchtower"` and `detail` `crashed twice`, then `driver.paused` with `"actor": "watchtower"`; `<fixture>/.factory/pause` present; the next tick appends no `bead.claimed`.

## Gotchas

- The pane inherits the tmux session's environment, not the driver's, so `SMILE_WATCHTOWER_CMD` must be set on the drive and the stub re-enters the scratch world through the `watchtower-env` wrapper, exactly like the worker.
- The stub tails the log from where it stood when it started, so events written before the spawn never appear in `watch.md`. That is the contract, not a miss.
- `smile event` leaves unset fields null (contract section 4), so the escalation passes `actor=watchtower` explicitly; `smile pause` takes the actor from `SMILE_ACTOR`.
- The watchtower is spawned before the pause check, so a paused campaign still gets its observer back if the pane dies. Do not read a `pane.spawned` during a pause as a claim.
- A spawn failure is one stderr line and the tick continues; a tick that exits 0 with no watchtower is a finding only when `watchtower` is `on` and the stderr line is absent.
- Never kill the `watchtower` window by hand: the reap is part of the evidence.
