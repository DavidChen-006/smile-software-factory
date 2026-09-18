# Mux

Mux is the three-verb seam the driver uses to open, probe, and close worker panes in whichever multiplexer the config names. (landed in S2)

## Sub-features

- `mux-spawn` opens a pane running a command in a directory and prints an opaque handle.
- `mux-alive` exits 0 while the pane's command runs and 1 after it exits or the pane is gone.
- `mux-kill` closes the pane and exits 0 even when it is already gone.
- `mux-select` picks the backend from `backend` in `smile.config.yaml`, else the first installed of tmux, cmux, herdr, and for `alive` and `kill` from the handle instead.

## How to get to it (user POV)

- Run `smile mux spawn <name> <cwd> <command>`, `smile mux alive <handle>`, `smile mux kill <handle>` in the stamped repo.
- Watch the pane appear in the tmux session, the cmux workspace, or the Herdr tab list.

## Driving it with verify-smile

Preconditions:

- A fixture with `install: stamped`.
- `--backend` names an installed backend and is written to the fixture's `backend` key. Left out, the runtime auto-detects, which is tmux on a normal box.

- **Spawn three.** Run `verify-smile feature mux`. The helper writes the `backend` key in the fixture config and commits it, exports `SMILE_MUX_SESSION` to the fixture's own session `smile-verify-<runid>`, counts the windows there, then spawns `w1`, `w2`, `w3` each running `sleep 300` in the fixture through `<fixture>/smile/smile mux spawn`. Each prints a handle beginning with a backend name, and `tmux list-windows -t "=smile-verify-<runid>"` shows three more windows than before.
- **Alive.** `smile mux alive <handle>` exits `0` for each of the three.
- **Kill.** `smile mux kill <handle>` for each exits `0`, `alive` then exits `1` for each, and the window count is back to what it was.
- **Double kill.** A second `kill` on one of the gone handles exits `0`.
- **Not driven live.** Handle and usage rejections (exit 2), a missing `cwd`, an argument containing a space, a lone-word command, a session name tmux would rewrite, ten concurrent spawns, a config backend with no file, and a PATH with no multiplexer. `tests/test_mux.py` proves those against a scratch repo and sessions it owns.
- **Proof.** `~/.smile-verify/<runid>/mux.log` holds the window listings before spawn, after spawn, and after kill, plus every handle and verdict. It prints `PASS mux` or `FAIL mux: <reason>`.

## Gotchas

- A handle is opaque. Never parse it in a recipe. Pass it back unchanged.
- The tmux backend must target the fixture session, not the user's own. The helper exports `SMILE_MUX_SESSION` and asserts against `smile-verify-<runid>`, and kills only the handles it spawned. It never kills the session or a window it did not open; `verify-smile down` owns the session.
- The window count is asserted as a delta, not as three. The fixture session already has the window `up` created.
- cmux and Herdr open visible panes on the user's screen, and their backend files land in S8. Until then a handle or a config naming them exits 2 with `unknown backend <name>`.
- With the multiplexer off PATH every verb exits 1 with `smile mux: missing tmux not on PATH`. Exit 0 from `kill` means the pane is known to be gone, never that the tool could not be asked.
- A stamp without `smile/py/backends/tmux.py` prints `NOT IMPLEMENTED mux` and exits 2 before it touches the config.
- The helper edits the fixture's `smile.config.yaml` and commits it, as the `doctor` feature does.
