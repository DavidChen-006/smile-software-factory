# SMILE runtime contract

The contract both runtimes implement. `templates/smile/bash/` and `templates/smile/py/` expose the same commands with the same stdout, exit codes, files, and events, so the verification harness drives either through the `runtime` config key and the bakeoff compares like with like. This document is normative for S1. Later spikes extend it; they do not change what is here without a spec revision.

Where `docs/SPEC.md` and the S1 brief differ, the brief is more specific and this contract follows it. Each such point is marked "Reconciled".

## 1. Shim dispatch

`smile/smile` is a bash shim stamped into the target repo. It is the only entry point.

	smile <command> [args...]

1. With no arguments it prints `usage: smile <command> [args...]` to stderr and exits 1.
2. It resolves the repo root by walking up from the shim's directory; it stops at the first directory that contains `smile.config.yaml` or a `.git` entry (file or directory). If that directory has no `smile.config.yaml`, exit 2 with a one-line stderr message. The shim is run by its stamped path `smile/smile`; invoking it through a symlink is unsupported.
3. It exports `SMILE_ROOT=<repo root>` (absolute, no trailing slash) for the runtime.
4. It reads `runtime` from `$SMILE_ROOT/smile.config.yaml` (empty or absent means `bash`) and execs:
   - `bash`: `"$SMILE_ROOT/smile/bash/<command>" "$@"`. The command file must exist and be executable, else stderr error and exit 2.
   - `py`: `python3 "$SMILE_ROOT/smile/py/smile.py" <command> "$@"`. `smile.py` must exist, else stderr error and exit 2. Unknown commands are the py runtime's job: print a one-line error to stderr and exit 2.
   - any other value: stderr error, exit 2.
5. A command name containing `/` or starting with `.` is rejected with exit 2, so `smile lib/events` cannot run a library file.

Rules for the runtimes that follow from this:

- The bash runtime is one executable file per command at `smile/bash/<command>`. Shared code lives under `smile/bash/lib/` and is sourced, never executed. Subcommands (`smile config get`, `smile mux spawn`) are arguments to the command file.
- The py runtime is `smile/py/smile.py` as the dispatcher plus modules beside it. It runs with the stdlib only.
- Every command reads `SMILE_ROOT` from the environment and never recomputes it. Every path below is relative to `$SMILE_ROOT`.
- Runtimes shell out to `git`, `gh`, `bd`, and `treehouse`; they never import their internals.

## 2. Config

File: `$SMILE_ROOT/smile.config.yaml`. Neither runtime uses a YAML library. The format is:

- One `key: value` per line. A key line matches `^[A-Za-z0-9_.]+:`; the key is not trimmed. The value is everything after the first `:` with surrounding whitespace trimmed; whitespace trimmed from values is ASCII space, tab, and CR only. A line with leading whitespace or whitespace before the colon is neither a key nor a comment and is ignored. The file is UTF-8 regardless of locale. Keys may contain dots.
- A line whose first non-blank character is `#` is a comment. Blank lines are allowed. No inline comments, no nesting, no quoting.
- A key present with an empty value is the empty string. A key absent from the file takes its default. Duplicate keys: the first wins.

Keys, defaults, and meaning. This table is the schema; a key not in it is unknown.

| key | default | meaning |
| --- | --- | --- |
| `runtime` | `bash` | Runtime the shim dispatches to: `bash` or `py`. |
| `backend` | empty | Pane backend: `tmux`, `cmux`, or `herdr`. Empty means auto-detect in that order. |
| `worker.model` | `opus` | Claude model the driver launches each worker with. |
| `worker.permission_mode` | `acceptEdits` | Permission mode the worker runs under. |
| `reviewer.models` | `opus` | Comma-separated list; one review runs per model. |
| `max_parallel` | `3` | Most beads in flight at once. |
| `watchtower` | `on` | Spawn the watchtower pane at campaign start: `on` or `off`. |
| `merge` | `auto` | `auto` squash-merges approved PRs; `human` labels them `smile:approved`. |
| `base_branch` | `main` | Branch worker PRs target and worktrees branch from. |

Values are strings. `max_parallel` is parsed as an integer by the driver (S3), `reviewer.models` is split on commas with each entry trimmed by the review lane (S4).

## 3. Event log

Path: `$SMILE_ROOT/.factory/events.jsonl`. One JSON object per line, appended.

Keys, always present, in this order: `ts`, `event`, `bead`, `pr`, `sha`, `actor`, `detail`.

| key | type | value |
| --- | --- | --- |
| `ts` | string | UTC, ISO 8601, seconds precision, `Z` suffix: `2026-09-18T06:39:00Z`. |
| `event` | string | One of the seventeen names below. |
| `bead` | string or null | Bead id, e.g. `sv-1`. |
| `pr` | integer or null | Pull request number as a bare JSON integer, never a string. On `smile event`, `pr` must match `^[1-9][0-9]*$`; anything else, including `pr=`, is exit 2. |
| `sha` | string or null | Commit SHA the event refers to. |
| `actor` | string or null | Who caused it. Conventions: `driver`, `worker`, `reviewer`, `watchtower`, `human`. |
| `detail` | string or null | Free text. Keep it short; see the line-size rule. |

Encoding: Python `json.dumps(obj, separators=(",", ":"), ensure_ascii=False)`. Escape exactly `"` as `\"`, `\` as `\\`, U+0008/0009/000A/000C/000D as `\b \t \n \f \r`, every other code point below U+0020 as `\u00XX` with lowercase hex; escape nothing else, including `/` and U+007F; write UTF-8. Both runtimes must produce byte-identical lines for the same inputs and timestamp. Invalid UTF-8 bytes in an argument or in the config file pass through unchanged (Python: `surrogateescape` on decode and encode). Example:

	{"ts":"2026-09-18T06:39:00Z","event":"bead.claimed","bead":"sv-1","pr":null,"sha":null,"actor":"driver","detail":"tick 3"}

Append rule: open the file in append mode and write the whole line, including the trailing newline, in one call. Python: `os.write` on a fd opened `O_WRONLY|O_APPEND|O_CREAT`. Bash: a single `printf '%s\n' "$line" >> file`. A line including its trailing newline is at most 4096 bytes (POSIX `PIPE_BUF`). When the line would be longer, `detail` is cut to the longest prefix of code points for which the encoded line fits; the cut never splits a UTF-8 sequence. When the other six fields alone exceed the limit the line is written as is. Never rewrite or truncate the file. Create `.factory/` and the file if absent.

The seventeen event names, from the spec's "The bus":

	campaign.start  bead.claimed  worktree.acquired  pane.spawned  pr.opened
	review.started  review.verdict  issue.opened  issue.resolved  pr.merged
	bead.closed  pane.reaped  worker.crashed  watch.escalation
	driver.paused  driver.resumed  campaign.complete

Deferred to S3 (finding, not implemented in S1): the spec's Design says worktrees resolve the log path through the main checkout so every process writes one file. In S1 the path is literally `$SMILE_ROOT/.factory/events.jsonl` as the brief states; the driver spike must either pass the main checkout as `SMILE_ROOT` to workers or add a git-common-dir resolution to the events library in both runtimes.

## 4. Commands (S1)

Every command reads `SMILE_ROOT` from the environment. Stdout carries only the lines named here; diagnostics go to stderr. Commands take no flags other than those listed. Any argument not listed is exit 2 with a one-line stderr message. Any other failure (I/O error, a tool crashing): exit 1.

| command | stdout | side effects | exit |
| --- | --- | --- | --- |
| `smile doctor` | One line per check, in this order: `git`, `gh`, `gh-auth`, `claude`, `bd`, `treehouse`, `mux`. Each line is `ok <tool>` or `missing <tool> <reason>`. The mux line names the backend picked: `ok mux tmux`. | None. Doctor is read-only; it never creates `.factory/` or touches bd. | 0 all ok; 1 any missing. |
| `smile init` | One line per action, in this order: `.beads`, `treehouse.toml`, `.worktreeinclude`, `.factory`, `.factory/events.jsonl`. Each line is `created <thing>` or `exists <thing>`. | See Init below. Idempotent. | 0. |
| `smile event <name> [bead=<id>] [pr=<n>] [sha=<s>] [actor=<a>] [detail=<text>]` | Nothing. | Appends one event line per section 3. Unset fields are `null`. | 0; 2 when `<name>` is not one of the seventeen, an argument is not `key=value` with one of the five keys, or `pr` is not an integer. |
| `smile config get <key>` | The value followed by a newline; the default when the key is absent from the file; an empty line when the value is empty. | None. Prints nothing on exit 3. | 0; 2 when `<key>` is missing from the argument list; 3 when `<key>` is not in the schema table. |
| `smile pause` | `paused` when `.factory/pause` was created; `already paused` when it existed. | Creates `.factory/` if absent, then `.factory/pause` (empty file). Appends `driver.paused` only when the file did not exist. | 0. |
| `smile resume` | `resumed` when `.factory/pause` was removed; `not paused` when it did not exist. | Removes `.factory/pause`. Appends `driver.resumed` only when the file existed. | 0. |
| `smile status` | Three sections, see Status below. | None. | 0. |

Detail per command.

**doctor.** A tool is `ok` when `command -v <tool>` finds it on PATH. Reasons for missing lines are one short phrase:

	missing git not on PATH
	missing gh not on PATH
	missing gh-auth gh not on PATH            (when gh itself is missing)
	missing gh-auth gh auth status failed     (gh present, `gh auth status` exits non-zero)
	missing claude not on PATH
	missing bd not on PATH
	missing treehouse not on PATH
	missing mux none of tmux, cmux, herdr on PATH
	missing mux <backend> not on PATH         (config `backend` names one that is absent)

The mux check honors `backend` from config: when set, only that backend is checked and the ok line is `ok mux <backend>`; when empty, the first of `tmux`, `cmux`, `herdr` on PATH is picked. A `backend` value outside `tmux`, `cmux`, `herdr` prints `missing mux unknown backend <value>`. Doctor prints all seven lines even after a failure; it does not stop early.

**init.** Each step creates its thing only when absent and prints `created <thing>` or `exists <thing>`.

1. `.beads`: when `$SMILE_ROOT/.beads/` is absent, run (note: bd 1.0.5 also writes `CLAUDE.md`, `AGENTS.md`, `.claude/settings.json`, `.agents/`, and `.codex/` into the repo and prints about twenty lines even with `-q`; the runtime discards that stdout and leaves those files alone) `BD_NON_INTERACTIVE=1 bd init --prefix <p> -q` in `$SMILE_ROOT`, where `<p>` is the basename ASCII-lowercased with every character outside `[a-z0-9]` removed, then the first two characters; fewer than two characters left: `sm`.
2. `treehouse.toml`: when absent, run `treehouse init` in `$SMILE_ROOT` (it requires a git repo and writes `treehouse.toml` there). Discard its stdout.
3. `.worktreeinclude`: when absent, write exactly `.env\nsmile.config.yaml\n`.
4. `.factory`: `mkdir` when absent.
5. `.factory/events.jsonl`: create empty when absent.

When `bd init` or `treehouse init` fails, init prints one stderr line, exits 1, and runs no later step. `smile init` appends no event. Reconciled: the spec's "appends a `campaign.start` placeholder only when asked" is covered by `smile event campaign.start`; init has no flag for it.

**event.** Arguments after `<name>` are `key=value` tokens in any order; the value is everything after the first `=`, untrimmed, and may contain spaces when quoted by the shell. An empty value is the empty string, not null. A key given more than once is exit 2. `ts` is taken at append time. `actor` defaults to null when not given.

**config get.** Parse per section 2. The lookup order is file value, then default. Both runtimes carry the same defaults table as section 2; the template file is not the source of defaults at runtime.

**pause and resume.** The events carry `actor` from `$SMILE_ACTOR` when it is set and non-empty, else `human`, and `detail` null. Everything else null.

**status.** Three sections, each a heading line ending in `:` followed by indented lines (two spaces).

	beads:
	  closed 1
	  in_progress 1
	  open 2
	prs:
	  open 1
	events:
	  2026-09-18T06:39:00Z bead.claimed sv-1 - tick 3
	  2026-09-18T06:39:04Z pr.opened sv-1 7 -

- `beads:` runs `BD_NON_INTERACTIVE=1 bd list --all --json` in `$SMILE_ROOT` and prints `  <status> <count>` for each distinct `status` value, sorted by byte value (`LC_ALL=C`). No beads: the heading alone.
- `prs:` runs `gh pr list --state open --limit 1000 --json number` in `$SMILE_ROOT` and prints `  open <count>`.
- `events:` prints the last ten lines of `.factory/events.jsonl`, oldest first, each rendered `  <ts> <event> <bead> <pr> <detail>` with null rendered as `-`. Fields are the decoded JSON strings; empty string renders as empty; `detail` has `\n`, `\r`, and `\t` replaced by a space. A line that does not parse as a JSON object is rendered as `  <raw line>`. The last line of the file counts whether or not it ends in a newline. Missing or empty log: the heading alone.
- When `bd` or `gh` fails (no `.beads/`, not a GitHub repo, logged out), that section prints `  unavailable` and status still exits 0.

## 5. Exit codes

| code | meaning |
| --- | --- |
| 0 | ok |
| 1 | a check failed (`doctor` with a missing tool) |
| 2 | usage: unknown command, bad arguments, unknown event name, bad runtime |
| 3 | unknown config key |

## 6. Installer

`python3 install.py <target-repo> [--force]` at the SMILE repo root, stdlib only. It copies the `templates/` tree into the target, preserving relative paths and file modes, skipping `__pycache__/` and `.DS_Store`. One stdout line per file, sorted by path components: `stamped <path>` (new), `unchanged <path>` (byte-identical; mode re-applied), `drifted <path>, use --force` (differs, left alone), `replaced <path>` (differs, `--force`), or `drifted <path>, symlink` (the destination is a symlink; counted as drift even with `--force`, never written through). A template that is itself a symlink is skipped with one stderr line. Then one line for `.gitignore`: `appended .gitignore` when it added `.factory/`, `unchanged .gitignore` when the line was present. Exit 1 when any file drifted without `--force` or on an I/O error (one stderr line), 2 on usage error, else 0. It touches nothing outside the templates image plus `.gitignore`.

The runtime writers add their files under `templates/smile/bash/` and `templates/smile/py/`; the installer picks them up with no change. Executable bits are taken from the file mode in the checkout, so `chmod +x` the bash command files and commit the mode.
