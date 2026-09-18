# Doctor

Doctor checks every prerequisite SMILE needs, prints one line per check, and exits 1 when anything is missing. (landed in S1)

## Sub-features

- `doctor-ok` prints seven lines in order, `ok git`, `ok gh`, `ok gh-auth`, `ok claude`, `ok bd`, `ok treehouse`, `ok mux <backend>`, and exits 0.
- `doctor-missing` prints `missing <tool> <reason>` on the tool's line and exits 1 when a tool is absent or gh is logged out; the other lines still print.
- `doctor-backend` names the backend it would pick when `backend` is unset, in the order tmux, cmux, herdr, and honors `backend` when set.

## How to get to it (user POV)

- Run `smile doctor` in the stamped repo.
- Run `/smile doctor` in Claude Code.

## Driving it with verify-smile

Preconditions:

- A fixture with `install: stamped`.

- **All present.** Run `verify-smile feature doctor`. The helper runs `<fixture>/smile/smile doctor` and asserts exit code `0` and exactly seven lines each starting with `ok `. It prints `PASS doctor` or `FAIL doctor: <reason>`.
- **One missing.** Not driven live; `tests/test_core.py` proves the missing-tool lines, the backend variants, and the read-only rule against a PATH built from stubs.
- **Proof.** `~/.smile-verify/<runid>/doctor.log` holds the transcript and the exit code.

## Gotchas

- `gh auth status` writes to stderr. Assert the exit code, not stdout.
- Doctor must not create `.factory/` or touch bd. It is read-only.
- The helper is read-only on the fixture: doctor takes no config edit.
