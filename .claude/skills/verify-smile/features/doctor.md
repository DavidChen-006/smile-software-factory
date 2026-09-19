# Doctor

Doctor checks every prerequisite SMILE needs, prints one line per check in a fixed order, and exits 1 when anything is missing. It is read-only: it never creates `.factory/` and never touches bd.

## Sub-features

- `doctor-ok` prints eight lines in order, `ok uv`, `ok git`, `ok gh`, `ok gh-auth`, `ok claude`, `ok bd`, `ok treehouse`, `ok mux <backend>`, and exits 0.
- `doctor-missing` prints `missing <tool> <reason>` on that tool's line and exits 1; the other lines still print and the order does not change.
- `doctor-backend` names the backend it would pick when `backend` is unset, in the order tmux, cmux, herdr, and honors `backend` when it is set.
- `doctor-readonly` leaves the repo untouched.

## How to get to it (user POV)

- Run `smile doctor` in the stamped repo.
- Run `/smile doctor` in Claude Code.

## Driving it with verify-smile

Preconditions:

- A fixture with `install: stamped`.

- **All present.** `verify-smile doctor` runs the runtime the way a user does, through the stamped shim, and reports its eight lines as the `smile.doctor` check's `detail`, semicolon separated, alongside the driving machine's own tool checks. Exit 0 when every check passed, 1 when any failed.
- **Backend named.** Edit `backend:` in `<fixture>/smile.config.yaml`, then `verify-smile time doctor --n 1`. The eighth stdout line is `ok mux <that backend>` for an installed one, `missing mux unknown backend <value>` for a name outside tmux, cmux, herdr.
- **One missing.** Not driven live; `tests/test_core.py` proves the missing-tool lines, the backend variants, and the read-only rule against a PATH built from stubs.
- **Read-only.** Run `verify-smile doctor` on a freshly stamped fixture and then `verify-smile events`. The event log is unchanged; doctor appends nothing.

## Evidence that proves it

- `verify-smile doctor` prints `{"name": "smile.doctor", "ok": true, "detail": "ok uv;ok git;ok gh;ok gh-auth;ok claude;ok bd;ok treehouse;ok mux tmux"}` and the object's `"ok": true`, exit 0.
- Every other check object in the same array: `tool.uv`, `tool.git`, `tool.gh`, `tool.bd`, `tool.treehouse`, `tool.tmux`, `gh.auth`, `run.state` (`state up`), `repo` (`<owner>/smile-verify-<runid> private=true`), `tmux.session`, `fixture.clone`, `bd.ready` (the ready ids), `stamp.shim`.
- A failing run prints the same object with `"ok": false` on the failing check, the stderr line naming `verify-smile down`, and exit 1.
- `verify-smile events` before and after are byte-identical, which is what proves the read-only rule.

## Gotchas

- `gh auth status` writes to stderr. Judge the exit code and the `ok`/`missing` line, not stdout text.
- `verify-smile time doctor` runs the shim inside the run's scratch world, where `HOME` is the run's own directory. gh keeps this account's token in the login keyring, which it finds under the real `$HOME`, so the `gh-auth` line there reads `missing gh-auth gh auth status failed` and the command exits 1. That is the scratch world, not a broken fixture: `verify-smile doctor` runs the same shim in the real environment, which is the user path, and gets `ok gh-auth`.
- A PATH without `uv` fails before doctor's first line: the shim prints `smile: uv is not on PATH` and exits 2. That is a broken fixture, not a `missing uv` line.
- Doctor must not create `.factory/`. If `verify-smile events` starts working only after a doctor run, that is a finding against the runtime.
- `verify-smile doctor` is read-only on the fixture too. It takes no config edit; the backend variants need one, so make it yourself and commit it.
