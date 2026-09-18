# Mux

Mux is the three-verb seam the driver uses to open, probe, and close worker panes in whichever multiplexer the config names. (lands in S2)

## Sub-features

- `mux-spawn` opens a pane running a command in a directory and prints an opaque handle.
- `mux-alive` exits 0 while the pane's command runs and 1 after it exits or the pane is gone.
- `mux-kill` closes the pane and exits 0 even when it is already gone.
- `mux-select` picks the backend from `backend` in `smile.config.yaml`, else the first installed of tmux, cmux, herdr.

## How to get to it (user POV)

- Run `smile mux spawn <name> <cwd> <command>`, `smile mux alive <handle>`, `smile mux kill <handle>` in the stamped repo.
- Watch the pane appear in the tmux session, the cmux workspace, or the Herdr tab list.

## Driving it with verify-smile

Preconditions:

- A fixture with `install: stamped`.
- `--backend` names an installed backend, default tmux. The tmux backend uses the fixture's own session `smile-verify-<runid>`.

- **Spawn three.** Run `verify-smile feature mux --runtime bash --backend tmux`. The helper spawns `w1`, `w2`, `w3` each running `sleep 60` in the fixture and records three handles. `tmux list-windows -t smile-verify-<runid>` lists three windows named `w1`, `w2`, `w3`.
- **Alive.** `smile mux alive <handle>` exits `0` for each.
- **Kill.** `smile mux kill <handle>` for each exits `0`. `tmux list-windows` no longer lists them. `alive` now exits `1`.
- **Double kill.** A second `kill` on a gone handle exits `0`.
- **Proof.** `~/.smile-verify/<runid>/mux.log` holds the window listings before and after.

## Gotchas

- A handle is opaque. Never parse it in a recipe. Pass it back unchanged.
- The tmux backend must target the fixture session, not the user's own. Assert against `smile-verify-<runid>`.
- cmux and Herdr open visible panes on the user's screen. Only drive those backends when the user expects it.
