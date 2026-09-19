# uv runtime

Every SMILE entry point runs through `uv run`. The shim `smile/smile` execs `uv run smile/py/smile.py`, and the installer and the test wrappers go through `uv run` too. uv picks the interpreter from each entry point's PEP 723 header, so the machine's own `python3` is not a prerequisite and no run pins a Python version.

## Sub-features

- `uv-shim` the shim execs `uv run` on the runtime and passes the command through unchanged.
- `uv-no-python3` every command works on a PATH with no `python3` at all.
- `uv-missing` a PATH with no `uv` fails at the shim: exactly one stderr line `smile: uv is not on PATH`, exit 2, before any command runs.
- `uv-doctor-first` `smile doctor`'s first line is `uv`, and it checks no `python3`.
- `uv-cost` the `uv run` indirection adds a fixed per-command overhead worth knowing before blaming the runtime for a slow tick.

## How to get to it (user POV)

- Run any `smile` command in the stamped repo; every one goes through the shim.
- Run `uv run <smile-repo>/install.py <target>` to stamp.
- Run `tests/*-py.test.sh`, which go through `uv run` as well.

## Driving it with verify-smile

Preconditions:

- A fixture with `install: stamped`. `uv` on PATH.

- **Normal path.** `verify-smile time doctor --n 1` runs the stamped shim and prints the eight doctor lines. `uv` is the first.
- **No python3.** Run the shim with a PATH that has `uv`, `git`, `gh`, `bd`, `treehouse`, `tmux` and no `python3`, in the fixture: build such a directory of symlinks and run `env PATH=<that dir> <fixture>/smile/smile doctor`. Exit 0 and the same eight lines, because nothing in SMILE asks for `python3`.
- **No uv.** Run the shim with `uv` removed from PATH: `env PATH=<dir without uv> <fixture>/smile/smile doctor`. Exactly one stderr line `smile: uv is not on PATH` and exit 2.
- **Cost.** `verify-smile time status --n 5` and `verify-smile time doctor --n 5` report the median wall milliseconds over five runs and the individual samples.

## Evidence that proves it

- `verify-smile time doctor --n 1`'s `stdout` beginning with `ok uv` and holding eight lines; no line mentions `python3`.
- The PATH-without-`python3` run's exit `0` and identical eight lines, next to the `command -v python3` that shows it really was absent from that PATH.
- The PATH-without-`uv` run's stderr, exactly `smile: uv is not on PATH`, exit `2`, and an event log unchanged across it: the shim fails before the runtime starts.
- `verify-smile time <cmd> --n 5`'s `median_ms` and `samples_ms`, e.g. `{"argv": ["doctor"], "n": 3, "median_ms": 606, "samples_ms": [741, 606, 606]}`. The first sample is usually the slowest; that is uv's environment resolution warming, not the runtime.

## Gotchas

- `verify-smile time` runs the shim inside the run's scratch world, where `HOME` is the run's own directory. That makes `smile doctor` report `missing gh-auth gh auth status failed` and exit 1, because gh reads this account's token from the login keyring under the real `$HOME`. Read the other seven lines; for a user-path doctor use `verify-smile doctor`.
- Never use a wall time from the first run of a fresh fixture as the number. uv resolves the environment once; take the median of at least five.
- A missing `uv` is not a `missing uv` doctor line. Doctor never runs: the shim exits 2 first. Do not report the two as the same failure.
- `uv run` writes to uv's own cache under the invoking `HOME`. A scratch `HOME` per run means each run's first command pays that cost again.
