# Mux

Mux is the three-verb seam the driver uses to open, probe, and close worker panes in whichever multiplexer the config names. A handle is opaque: whatever `spawn` printed is what `alive` and `kill` take back.

## Sub-features

- `mux-spawn` opens a pane running a command in a directory and prints an opaque handle.
- `mux-alive` exits 0 while the pane's command runs and 1 after it exits or the pane is gone.
- `mux-kill` closes the pane and exits 0 even when it is already gone.
- `mux-select` picks the backend from `backend` in `smile.config.yaml`, else the first installed of tmux, cmux, herdr, and for `alive` and `kill` from the handle instead.

## How to get to it (user POV)

- Run `smile mux spawn <name> <cwd> <command>`, `smile mux alive <handle>`, `smile mux kill <handle>` in the stamped repo.
- Watch the pane appear in the tmux session, the cmux workspace, or the Herdr tab list.
- Let `smile run` do it: every `pane.spawned` and `pane.reaped` event is the driver going through this seam.

## Driving it with verify-smile

Preconditions:

- A fixture with `install: stamped`. Its tmux session is `smile-verify-<runid>`; `verify-smile` exports `SMILE_MUX_SESSION` to it, so nothing of the user's own is ever touched.

- **Count before.** `verify-smile panes` prints one object per window. A fresh fixture has exactly one, the shell `up` opened. From the first tick on there is also a `watchtower` window (see [watchtower.md](watchtower.md)), which is not a worker pane and is reaped only at `campaign.complete`; count the delta against the reading taken just before the spawn, never against the fresh fixture's one window.
- **Spawn through the driver.** `verify-smile tick --worker-sleep 60` claims the ready beads and spawns one pane per bead, each running the stub worker for a minute. The tick's `events` array carries one `pane.spawned` per bead whose `detail` is the handle.
- **Alive.** `verify-smile panes` now lists one more window per spawned bead, each `"dead": false`, and `verify-smile runs` shows the same handles in the live run state files.
- **Kill.** `verify-smile kill-pane <bead>` reads that bead's handle from its run state file and runs `smile mux kill`. It prints `handle` and `exit` 0.
- **Double kill.** Run `verify-smile kill-pane <bead>` again on the same bead. Exit is still `0`: a pane known to be gone is not an error. Do both kills while that bead's run file is still `live` or `waiting`: `kill-pane` reads the handle out of the run state file, so once the reap tick has moved the file to `done` it exits 1 with `no live or waiting run state file for bead <id>` and never reaches `smile mux kill`.
- **Count after.** `verify-smile panes` is back to the window count from before the spawn.
- **Not driven live.** Handle and usage rejections (exit 2), a missing `cwd`, an argument containing a space, a lone-word command, a session name tmux would rewrite, ten concurrent spawns, a config backend with no file, and a PATH with no multiplexer. `tests/test_mux.py` proves those against a scratch repo and sessions it owns.

## Evidence that proves it

- The `pane.spawned` event's `detail`, e.g. `tmux:smile-verify-20260919T032152Z-600e:@1`, starting with a backend name and naming the fixture's own session.
- `verify-smile panes` before, after spawn, and after kill: the count rises by one per spawned bead and returns to the baseline. Assert the delta, never the absolute number; the session already has the window `up` created.
- `verify-smile runs` live entries carrying the same `handle` string the event carried.
- `verify-smile kill-pane <bead>` printing `"exit": 0` twice for the same bead.

## Gotchas

- A handle is opaque. Never parse it in a recipe; pass it back unchanged. `kill-pane` exists so a verifier never has to read one out of a run file by hand.
- The tmux backend must target the fixture session, not the user's own. `verify-smile` exports `SMILE_MUX_SESSION=smile-verify-<runid>` and kills only handles this run spawned. `down` owns the session itself.
- The stub worker without `--worker-sleep` finishes in seconds, so its pane is usually already gone by the time you look. Use `--worker-sleep <s>` whenever a live pane is the thing under test. The flag reaches the worker through the fixture tmux session's environment, set for that tick and unset after, because a pane inherits the session's environment and not the driver's.
- cmux and Herdr open visible panes on the user's screen. Their backends landed in S8: `smile/py/backends/cmux.py` and `smile/py/backends/herdr.py` are stamped, and `BACKENDS = ("tmux", "cmux", "herdr")` in `smile/py/mux.py` is also the auto-detect order. Herdr has been driven live; cmux has not, so treat a cmux drive as unverified rather than proven. A config naming a backend with no file still exits 2 with `unknown backend <name>`.
- With the multiplexer off PATH every verb exits 1 with `smile mux: missing tmux not on PATH`. Exit 0 from `kill` means the pane is known to be gone, never that the tool could not be asked.
