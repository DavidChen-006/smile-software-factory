# Doctor

Doctor checks every prerequisite SMILE needs, prints one line per check, and exits 1 when anything is missing. (lands in S1)

## Sub-features

- `doctor-ok` prints `ok <tool>` for git, gh, claude, bd, treehouse, and each installed backend, and exits 0.
- `doctor-missing` prints `missing <tool> <reason>` and exits 1 when a tool is absent or gh is logged out.
- `doctor-backend` names the backend it would pick when `backend` is unset, in the order tmux, cmux, herdr.

## How to get to it (user POV)

- Run `smile doctor` in the stamped repo.
- Run `/smile doctor` in Claude Code.

## Driving it with verify-smile

Preconditions:

- A fixture with `install: stamped`.

- **All present.** Run `verify-smile feature doctor --runtime bash`. The helper runs `<fixture>/smile/smile doctor`. Every line starts with `ok` and the exit code is `0`.
- **One missing.** The helper runs doctor again with `PATH` stripped of the directory holding `treehouse`. One line reads `missing treehouse` and the exit code is `1`.
- **Proof.** `~/.smile-verify/<runid>/doctor.log` holds both transcripts.

## Gotchas

- `gh auth status` writes to stderr. Assert the exit code, not stdout.
- Doctor must not create `.factory/` or touch bd. It is read-only.
