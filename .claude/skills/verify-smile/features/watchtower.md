# Watchtower

Watchtower is the observer pane the driver opens at campaign start. It reads the event log, writes a report, escalates when the run looks wrong, and can pause claiming. It never edits code, bd, or GitHub. (lands in S5)

## Sub-features

- `watch-spawn` opens a `watchtower` pane when `watchtower: on`.
- `watch-report` grows `.factory/watch.md` during the run.
- `watch-escalate` appends a `watch.escalation` event naming the bead and reason.
- `watch-pause` creates `.factory/pause`, and the driver logs `driver.paused` on its next tick.
- `watch-resume` is a human action. Removing the file makes the driver log `driver.resumed`.

## How to get to it (user POV)

- Run `smile run` with `watchtower: on` and watch the `watchtower` pane.
- Read `.factory/watch.md`.
- Run `smile pause` and `smile resume` by hand to do what the watchtower does.

## Driving it with verify-smile

Preconditions:

- A fixture with `install: stamped`, `watchtower: on`, stubs configured.
- `SMILE_STUB_CRASH_BEADS="<B>"` and `SMILE_STUB_CRASH_TIMES=2`, so bead B crashes twice.

- **Spawn.** Run `verify-smile feature watchtower --runtime bash`. `tmux list-windows -t smile-verify-<runid>` includes a window named `watchtower`.
- **Escalate.** After the second crash of B, the event log has `worker.crashed` twice for B and a `watch.escalation` whose `bead` is B.
- **Pause.** `.factory/pause` exists and the next `driver.paused` event follows the escalation in the log. No `bead.claimed` appears after it.
- **Resume.** The helper runs `smile resume`. The log gains `driver.resumed`.
- **Proof.** `~/.smile-verify/<runid>/watchtower.log` holds the window listing and the event excerpt. `down` copies `watch.md` into `factory/`.

## Gotchas

- The watchtower is a model in a pane. Its escalation wording varies. Assert the event fields, not the prose.
- With no crash the watchtower must stay silent. A `watch.escalation` on a clean run is a finding against the watchtower prompt.
