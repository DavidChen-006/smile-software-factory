# SMILE runtime contract

The contract the runtime implements. `templates/smile/py/` exposes the commands below with the stdout, exit codes, files, and events named here, and the verification harness drives them. This document is normative for S1. Later spikes extend it; they do not change what is here without a spec revision. It was written for two runtimes; Python won the bakeoff on 2026-09-18 and the bash runtime was removed, so every rule below is the py runtime's.

Where `docs/SPEC.md` and the S1 brief differ, the brief is more specific and this contract follows it. Each such point is marked "Reconciled".

## 1. Shim dispatch

`smile/smile` is a bash shim stamped into the target repo. It is the only entry point.

	smile <command> [args...]

1. With no arguments it prints `usage: smile <command> [args...]` to stderr and exits 1.
2. It resolves the repo root by walking up from the shim's directory; it stops at the first directory that contains `smile.config.yaml` or a `.git` entry (file or directory). If that directory has no `smile.config.yaml`, exit 2 with a one-line stderr message. The shim is run by its stamped path `smile/smile`; invoking it through a symlink is unsupported.
3. It exports `SMILE_ROOT=<repo root>` (absolute, no trailing slash) for the runtime.
4. It execs `uv run "$SMILE_ROOT/smile/py/smile.py" <command> "$@"`. When `uv` is not on PATH the shim prints exactly one stderr line, `smile: uv is not on PATH`, and exits 2. `smile.py` must exist, else stderr error and exit 2. Unknown commands are the runtime's job: print a one-line error to stderr and exit 2.
5. A command name containing `/` or starting with `.` is rejected with exit 2, so `smile lib/events` cannot run a library file.

Rules for the runtime that follow from this:

- The runtime is `smile/py/smile.py` as the dispatcher plus modules beside it. It runs with the stdlib only. Subcommands (`smile config get`, `smile mux spawn`) are arguments to the command.
- Every command reads `SMILE_ROOT` from the environment and never recomputes it. Every path below is relative to `$SMILE_ROOT`.
- The runtime shells out to `git`, `gh`, `bd`, and `treehouse`; it never imports their internals.

### Interpreter

uv owns the interpreter. The machine's `python3` is not a prerequisite and is never consulted.

Every entry-point script carries PEP 723 inline script metadata as its first lines: the shebang `#!/usr/bin/env -S uv run`, then

	# /// script
	# requires-python = ">=3.12"
	# dependencies = []
	# ///

SMILE has no third-party dependencies, so `dependencies` is the empty list everywhere. The entry points are `smile/py/smile.py` and `install.py`; the other modules under `smile/py/` are imported by `smile.py` and carry no header. `requires-python` is `>=3.12`, so modules may use 3.12 syntax freely. There is no Python 3.9 floor and no `from __future__ import annotations` requirement.

The runtime is tested once, on the interpreter uv resolves from `requires-python`. There is no second pass. The tests run through `uv run` too: each `tests/<name>-py.test.sh` runs `uv run python -m unittest tests.test_<name>`, so the test interpreter is chosen by the same rule as the runtime's.

## 2. Config

File: `$SMILE_ROOT/smile.config.yaml`. The runtime uses no YAML library. The format is:

- One `key: value` per line. A key line matches `^[A-Za-z0-9_.]+:`; the key is not trimmed. The value is everything after the first `:` with surrounding whitespace trimmed; whitespace trimmed from values is ASCII space, tab, and CR only. A line with leading whitespace or whitespace before the colon is neither a key nor a comment and is ignored. The file is UTF-8 regardless of locale. Keys may contain dots.
- A line whose first non-blank character is `#` is a comment. Blank lines are allowed. No inline comments, no nesting, no quoting.
- A key present with an empty value is the empty string. A key absent from the file takes its default. Duplicate keys: the first wins.

Keys, defaults, and meaning. This table is the schema; a key not in it is unknown.

| key | default | meaning |
| --- | --- | --- |
| `backend` | empty | Pane backend: `tmux`, `cmux`, or `herdr`. Empty means auto-detect in that order. |
| `worker.model` | `opus` | Claude model the driver launches each worker with. |
| `worker.permission_mode` | `acceptEdits` | Permission mode the worker runs under. |
| `reviewer.models` | `opus` | Comma-separated list; one review runs per model. |
| `reviewer.timeout` | `600` | Seconds the reviewer gets before the runtime kills it (S4). |
| `max_parallel` | `3` | Most beads in flight at once. |
| `watchtower` | `on` | Spawn the watchtower pane at campaign start: `on` or `off`. |
| `watchtower.model` | `opus` | Claude model the watchtower pane runs with (S5). |
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

Encoding: Python `json.dumps(obj, separators=(",", ":"), ensure_ascii=False)`. Escape exactly `"` as `\"`, `\` as `\\`, U+0008/0009/000A/000C/000D as `\b \t \n \f \r`, every other code point below U+0020 as `\u00XX` with lowercase hex; escape nothing else, including `/` and U+007F; write UTF-8. Invalid UTF-8 bytes in an argument or in the config file pass through unchanged (Python: `surrogateescape` on decode and encode). Example:

	{"ts":"2026-09-18T06:39:00Z","event":"bead.claimed","bead":"sv-1","pr":null,"sha":null,"actor":"driver","detail":"tick 3"}

Append rule: open the file in append mode and write the whole line, including the trailing newline, in one call. Python: `os.write` on a fd opened `O_WRONLY|O_APPEND|O_CREAT`. A line including its trailing newline is at most 4096 bytes (POSIX `PIPE_BUF`). When the line would be longer, `detail` is cut to the longest prefix of code points for which the encoded line fits; the cut never splits a UTF-8 sequence. When the other six fields alone exceed the limit the line is written as is. Never rewrite or truncate the file. Create `.factory/` and the file if absent.

The seventeen event names, from the spec's "The bus":

	campaign.start  bead.claimed  worktree.acquired  pane.spawned  pr.opened
	review.started  review.verdict  issue.opened  issue.resolved  pr.merged
	bead.closed  pane.reaped  worker.crashed  watch.escalation
	driver.paused  driver.resumed  campaign.complete

Deferred to S3 (finding, not implemented in S1): the spec's Design says worktrees resolve the log path through the main checkout so every process writes one file. In S1 the path is literally `$SMILE_ROOT/.factory/events.jsonl` as the brief states; the driver spike must either pass the main checkout as `SMILE_ROOT` to workers or add a git-common-dir resolution to the events module.

## 4. Commands (S1)

Every command reads `SMILE_ROOT` from the environment. Stdout carries only the lines named here; diagnostics go to stderr. Commands take no flags other than those listed. Any argument not listed is exit 2 with a one-line stderr message. Any other failure (I/O error, a tool crashing): exit 1.

| command | stdout | side effects | exit |
| --- | --- | --- | --- |
| `smile doctor` | Eight lines, one per check, in this order: `uv`, `git`, `gh`, `gh-auth`, `claude`, `bd`, `treehouse`, `mux`. Each line is `ok <tool>` or `missing <tool> <reason>`. The mux line names the backend picked: `ok mux tmux`. | None. Doctor is read-only; it never creates `.factory/` or touches bd. | 0 all ok; 1 any missing. |
| `smile init` | One line per action, in this order: `.beads`, `treehouse.toml`, `.worktreeinclude`, `.factory`, `.factory/events.jsonl`. Each line is `created <thing>` or `exists <thing>`. | See Init below. Idempotent. | 0. |
| `smile event <name> [bead=<id>] [pr=<n>] [sha=<s>] [actor=<a>] [detail=<text>]` | Nothing. | Appends one event line per section 3. Unset fields are `null`. | 0; 2 when `<name>` is not one of the seventeen, an argument is not `key=value` with one of the five keys, or `pr` is not an integer. |
| `smile config get <key>` | The value followed by a newline; the default when the key is absent from the file; an empty line when the value is empty. | None. Prints nothing on exit 3. | 0; 2 when `<key>` is missing from the argument list; 3 when `<key>` is not in the schema table. |
| `smile pause` | `paused` when `.factory/pause` was created; `already paused` when it existed. | Creates `.factory/` if absent, then `.factory/pause` (empty file). Appends `driver.paused` only when the file did not exist. | 0. |
| `smile resume` | `resumed` when `.factory/pause` was removed; `not paused` when it did not exist. | Removes `.factory/pause`. Appends `driver.resumed` only when the file existed. | 0. |
| `smile status` | Three sections, see Status below. | None. | 0. |

Detail per command.

**doctor.** A tool is `ok` when `command -v <tool>` finds it on PATH. Reasons for missing lines are one short phrase:

	missing uv not on PATH
	missing git not on PATH
	missing gh not on PATH
	missing gh-auth gh not on PATH            (when gh itself is missing)
	missing gh-auth gh auth status failed     (gh present, `gh auth status` exits non-zero)
	missing claude not on PATH
	missing bd not on PATH
	missing treehouse not on PATH
	missing mux none of tmux, cmux, herdr on PATH
	missing mux <backend> not on PATH         (config `backend` names one that is absent)

The mux check honors `backend` from config: when set, only that backend is checked and the ok line is `ok mux <backend>`; when empty, the first of `tmux`, `cmux`, `herdr` on PATH is picked. A `backend` value outside `tmux`, `cmux`, `herdr` prints `missing mux unknown backend <value>`. Doctor prints all eight lines even after a failure; it does not stop early.

`uv` is the first line because nothing else in SMILE runs without it: the shim, the runtime, the installer, and the tests all go through `uv run`. `python3` is not a prerequisite and doctor does not check for one; uv fetches whatever interpreter `requires-python` asks for.

**init.** Each step creates its thing only when absent and prints `created <thing>` or `exists <thing>`.

1. `.beads`: when `$SMILE_ROOT/.beads/` is absent, run (note: bd 1.0.5 also writes `CLAUDE.md`, `AGENTS.md`, `.claude/settings.json`, `.agents/`, and `.codex/` into the repo and prints about twenty lines even with `-q`; the runtime discards that stdout and leaves those files alone) `BD_NON_INTERACTIVE=1 bd init --prefix <p> -q` in `$SMILE_ROOT`, where `<p>` is the basename ASCII-lowercased with every character outside `[a-z0-9]` removed, then the first two characters; fewer than two characters left: `sm`.
2. `treehouse.toml`: when absent, run `treehouse init` in `$SMILE_ROOT` (it requires a git repo and writes `treehouse.toml` there). Discard its stdout.
3. `.worktreeinclude`: when absent, write exactly `.env\nsmile.config.yaml\n`.
4. `.factory`: `mkdir` when absent.
5. `.factory/events.jsonl`: create empty when absent.

When `bd init` or `treehouse init` fails, init prints one stderr line, exits 1, and runs no later step. `smile init` appends no event. Reconciled: the spec's "appends a `campaign.start` placeholder only when asked" is covered by `smile event campaign.start`; init has no flag for it.

**event.** Arguments after `<name>` are `key=value` tokens in any order; the value is everything after the first `=`, untrimmed, and may contain spaces when quoted by the shell. An empty value is the empty string, not null. A key given more than once is exit 2. `ts` is taken at append time. `actor` defaults to null when not given.

**config get.** Parse per section 2. The lookup order is file value, then default. The runtime carries the defaults table of section 2; the template file is not the source of defaults at runtime.

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
| 2 | usage: unknown command, bad arguments, unknown event name |
| 3 | unknown config key |

## 6. Installer

`uv run install.py <target-repo> [--force]` at the SMILE repo root, stdlib only. `install.py` is an entry point, so it carries the PEP 723 header of the Interpreter note above (`#!/usr/bin/env -S uv run`, `requires-python = ">=3.12"`, `dependencies = []`). Being stdlib-only it still runs under a bare `python3` new enough to parse it, but `uv run install.py` is the documented form and the one every doc and script uses. It copies the `templates/` tree into the target, preserving relative paths and file modes, skipping `__pycache__/` and `.DS_Store`. One stdout line per file, sorted by path components: `stamped <path>` (new), `unchanged <path>` (byte-identical; mode re-applied), `drifted <path>, use --force` (differs, left alone), `replaced <path>` (differs, `--force`), or `drifted <path>, symlink` (the destination is a symlink; counted as drift even with `--force`, never written through). A template that is itself a symlink is skipped with one stderr line. Then one line for `.gitignore`: `appended .gitignore` when it added `.factory/`, `unchanged .gitignore` when the line was present. Exit 1 when any file drifted without `--force` or on an I/O error (one stderr line), 2 on usage error, else 0. It touches nothing outside the templates image plus `.gitignore`.

The runtime writers add their files under `templates/smile/py/`; the installer picks them up with no change. Executable bits are taken from the file mode in the checkout, so `chmod +x` an entry script and commit the mode.

## 7. Mux seam (S2)

The driver spawns and reaps panes only through `smile mux`. One backend file per pane tool implements three verbs. The backend for `spawn` comes from the config key `backend`, or auto-detect in the order tmux, cmux, herdr when it is empty. The backend for `alive` and `kill` comes from the handle, never from config, so a pane can be killed after the config changes.

| command | stdout | exit |
| --- | --- | --- |
| `smile mux spawn <name> <cwd> <command> [args...]` | The handle, one line. | 0; 1 when the backend is missing or the tool refuses, with one stderr line; 2 usage. |
| `smile mux alive <handle>` | Nothing. | 0 while the pane exists and its process has not exited; 1 otherwise; 2 malformed handle or unknown backend. |
| `smile mux kill <handle>` | Nothing. | 0, also when the pane is already gone; 1 when the tool is not on PATH (the pane may still be alive), with one stderr line; 2 malformed handle or unknown backend. |

Handle grammar: `<backend>:<rest>`, where `<backend>` is `tmux`, `cmux`, or `herdr` and `<rest>` is opaque to the caller. A handle is a single line with no whitespace, and both parts are non-empty. A `<rest>` the backend cannot parse is a malformed handle, exit 2, the same as a handle with no colon.

Edge rules:

| case | behaviour |
| --- | --- |
| `smile mux` with no verb, or an unknown verb | usage on stderr, exit 2. |
| `spawn` when `<cwd>` is not a directory | one stderr line, exit 1, nothing spawned (tmux would accept it and leave a dead window). |
| `spawn` when config names a backend that has no file, or auto-detect finds none of the three on PATH | `unknown backend <name>` exit 2 in the first case; `missing` and exit 1 in the second. |
| `spawn` when the tool for the chosen backend is not on PATH | one stderr line, exit 1. |
| `alive` or `kill` when the tool is not on PATH | one stderr line `missing <tool> not on PATH`, exit 1, no traceback. |
| a leading dash in `<command>` or its args (`--foo`) | passed through unchanged after `--`. |

Backend layout: `smile/py/backends/<backend>.py`. A backend name is checked against the three names before it becomes a path component, so `../config` or `TMUX` is never resolved to a file; a name outside the three, or one of the three whose file has not landed, is `unknown backend <name>`, exit 2.

The spawned command runs with `<cwd>` as its working directory and inherits the caller's environment. `<command>` and its args are passed to the tool as one argv, never re-joined through a shell, so spaces in arguments survive. tmux hands a lone word to `sh -c`, so when exactly one word is given the backend prefixes `env`, which execs it directly; a lone word with a space is therefore a program that does not exist, not a shell string. `<name>` labels the pane for humans; it need not be unique.

Session name: `smile-<basename of SMILE_ROOT>`, overridden by the environment variable `SMILE_MUX_SESSION` when set and non-empty (the verification harness sets it to its own session). Before the name reaches the tool, every `.`, `:`, and whitespace character in it is replaced with `_` (tmux rewrites the first two itself and a space would break the one-word handle rule). The handle still carries the name the tool reports back, never the name that was asked for, so `alive` and `kill` always resolve.

**tmux backend.** `spawn` tries `tmux new-window -d -P -F '#{session_name}:#{window_id}' -t =<session> -n <name> -c <cwd> -- <command> [args...]` first; when that fails because the session does not exist it runs `new-session -d -P -F '#{session_name}:#{window_id}' -s <session> -n <name> -c <cwd> -- ...`, and when `new-session` reports `duplicate session` (a concurrent spawn won the race) it retries `new-window` once. The handle is `tmux:<rest>` where `<rest>` is exactly that printed line, `<session_name>:<window_id>` with the tmux window id (`@N`). `alive` and `kill` reject a `<rest>` that does not match `<session>:@<digits>` (session non-empty, no whitespace) as a malformed handle, exit 2, so a truncated handle can never target another window. The window has `remain-on-exit` off, so it disappears when the command exits. `spawn` sets `remain-on-exit off` on its own window only and never changes a session or global option, so a session shared with other tooling is left as found. `alive` is one call: `tmux list-windows -t "=<session>" -F '#{window_id} #{pane_dead}'` must contain the exact line `<window_id> 0` (`display -p` is never used, its target cannot fail). `kill` runs `tmux kill-window -t "=<session>:<window_id>"` and ignores a missing window. A `<rest>` with no colon, or an empty session or window part, is a malformed handle. All `-t` session targets use the `=` exact-match prefix.

The cmux and Herdr backends are specified in S8 against the same verbs and handle grammar.

## 8. Driver (S3)

`smile run [--once] [--interval <seconds>]` is the loop. Default interval 60. `--once` runs one tick and exits. `<seconds>` must match `^[1-9][0-9]*$` (ASCII digits, no leading zero), else exit 2; a repeated flag is allowed and the last value wins; `--interval=5` and any other argument are exit 2. `max_parallel` from config must match the same pattern, else one stderr line `bad max_parallel <value>` and exit 1 before anything is touched.

**Factory directory.** From S3 on, the runtime resolves the factory directory as the parent of `git -C "$SMILE_ROOT" rev-parse --path-format=absolute --git-common-dir`, so a linked worktree of the repo writes the same `.factory/` as the main checkout. For a plain checkout that is `$SMILE_ROOT/.factory`. The event log, pause file, pid file, and run state below all live there. The runtime updates its S1 code, `init` included (it creates that `.factory/`, not `$SMILE_ROOT/.factory`), to use this resolution; `smile status`, `pause`, `resume`, and `event` run identically from a worktree.

**Singleton.** `.factory/driver.pid` holds the runtime's pid, the `os.getpid()` of the Python interpreter that `uv run` launched, not the pid of `uv` itself; that is the process to signal. SIGTERM sent to the `uv` parent is forwarded to the runtime; SIGKILL of the parent is not and orphans it, so tooling signals the pid in the file. It is created atomically with the pid already inside: write `<pid>\n` to a temporary file in the same directory and hard-link it to `driver.pid` (`os.link`), so the name never exists empty (an `O_EXCL` create leaves a moment where a racing driver reads an empty file as stale). When the file already exists the driver reads it: a positive integer naming a live process means a second `smile run`, which prints one stderr line ending `driver already running (pid <n>)` (the prefix is the runtime's own; stderr text is not byte-contractual, stdout and exit codes are) and exits 1; anything else (dead pid, non-positive, unparsable) is stale, so the driver removes it and creates its own exclusively, once. The file is removed on every exit, including SIGINT and SIGTERM, where the driver prints one stderr line `driver stopped` and exits 1 with no traceback; removal tolerates the file being already gone.

**Start.** The driver appends `campaign.start` with `actor` `driver` and `detail` the interval only when `.factory/runs/` holds no live run state file (a fresh campaign); a driver that resumes over live runs, including a second `--once`, appends nothing. Then it runs ticks until `campaign.complete` or `--once`.

**Working directory.** The driver runs every tool (`bd`, `treehouse`, `git`, `smile mux`) with the main checkout (the factory directory's parent) as working directory, wherever `smile run` was started from, so a driver started in a linked worktree or a subdirectory claims the same beads. `SMILE_ROOT` stays whatever the shim resolved. No environment variable overrides the factory directory.

**Tick, in this order.** Bead status for step 1 is read once per tick from `bd list --all --json`, not one `bd show` per run file; when that call fails the tick aborts before reap with one stderr line and exit 1, so a bd outage never turns finished workers into crashes. A pane still alive whose bead is already closed is left alone and reaped on the tick after it exits. `bd show <id> --json` returns a one-element JSON list; the runtime reads element 0.

1. Reap. For each run state file in `.factory/runs/<bead>.json`, a file that is not valid JSON, lacks one of the six keys, or names a bead `bd list --all --json` does not list is moved to `.factory/runs/crashed/` with one `worker.crashed` event (`bead` the file's basename, `detail` `unreadable`) and the tick continues; `smile mux alive` exiting 2 counts as dead. Otherwise: when `smile mux alive <handle>` is 1 and the bead's status is `closed`, run `smile mux kill <handle>` (a lingering dead window under a user's global `remain-on-exit on` is removed here), then `treehouse return --force <worktree>`, append `pane.reaped` (`bead`, `detail` the handle), and move the state file to `.factory/runs/done/`. When the pane is dead, the bead is not closed, and either the log holds a `pr.opened` event for that bead or `gh pr list --state all --json number,body --limit 200` shows a PR whose body has the line `Bead: <id>` (a PR merged by hand before any tick counts), the worker finished a round and is waiting on review: move the state file to `.factory/runs/waiting/` with no event, keep the worktree leased, and touch nothing else (S4 moves it back). When the pane is dead, the bead is not closed, and neither exists for the bead, append `worker.crashed` (`bead`, `detail` `attempt <n>`); if `attempts` is 1, respawn: no new claim, no new worktree, no `bead.claimed` or `worktree.acquired`; the run state file is rewritten with `attempts` 2 first, then the same work order is spawned again per step 3 and a second `pane.spawned` carries the new handle and the file gets the new handle and a fresh `spawned_at` (a respawn that fails is exit 1 like any spawn failure, and the file already says 2, so the next tick escalates); if `attempts` is 2, append a second `worker.crashed` with `detail` `escalated`, move the state file to `.factory/runs/crashed/`, and leave the bead claimed.
2. Review. `review_pending()` is a hook point that S4 fills. In S3 it does nothing.
3. Claim and spawn. When `.factory/pause` exists, skip this step (the pause command already logged `driver.paused`; the driver logs nothing about pausing). Otherwise read `bd ready --json`, and for each bead until the count of live run state files reaches `max_parallel`: claim with `bd update <id> --claim`; append `bead.claimed`; acquire a worktree with `treehouse get --lease --lease-holder <id>` (stdout is the path); append `worktree.acquired` (`detail` the path); write the work order to `.factory/orders/<id>.md` by substituting, in one pass so a value that itself contains a placeholder is left alone, `{{bead_id}}`, `{{bead_title}}`, `{{bead_description}}` (from `bd show <id> --json`, the strings exactly as bd prints them, trailing newlines included), `{{spec_path}}` (the newest by mtime of `docs/*SPEC*.md` and `docs/*DESIGN*.md` in the main checkout, written repo-relative, ties broken by the greater path string, else empty), and `{{base_branch}}` in `prompts/worker.md` read from the main checkout; mark the worktree trusted (below); spawn with `smile mux spawn <id> <worktree> <command...>`; append `pane.spawned` (`detail` the handle); write `.factory/runs/<id>.json` with keys `bead`, `worktree`, `handle`, `order`, `attempts`, `spawned_at` as one line of compact JSON with sorted keys (`json.dumps(state, sort_keys=True, separators=(",", ":"))`) plus a trailing newline; `attempts` is a JSON number, `spawned_at` the very timestamp written as `ts` on that `pane.spawned` event (taken once, used for both).
A failure inside step 3 after the claim (`treehouse get`, the order, the trust edit, or `smile mux spawn` failing) releases the claim with `bd update <id> --status open` (the assignee field may stay set; only status matters to `bd ready`), returns the worktree with `treehouse return --force` when one was acquired, prints one stderr line, writes no run state file, appends no further event (`bead.claimed` and, when the acquire succeeded, `worktree.acquired` have already been written and stay), and continues with the next ready bead; the tick still exits 0, and the bead is ready again next tick (a full treehouse pool is the normal case here, not an error).

4. Complete. When `bd list --json` (open, in_progress, blocked) is empty and no run state file is live in `runs/` or `runs/waiting/`, append `campaign.complete`, remove the pid file, exit 0.

**Worker command.** Default argv: `claude --model <worker.model> --permission-mode <worker.permission_mode> <order text>` where the order text is the file contents as one argument, byte for byte, trailing newline included. When `SMILE_WORKER_CMD` is set and non-empty, its value is split on whitespace into argv with no glob expansion and the order path is appended as the last argument. The four variables `SMILE_BEAD`, `SMILE_BEAD_TITLE`, `SMILE_REPO` (the main checkout, the factory directory's parent), and `SMILE_BASE_BRANCH` reach the worker on the command line: the argv handed to `smile mux spawn` is `env SMILE_BEAD=<id> SMILE_BEAD_TITLE=<title> SMILE_REPO=<path> SMILE_BASE_BRANCH=<branch> <worker argv...>`, in that order, because a tmux window inherits the server's environment, not the spawning client's. The pane's working directory is the worktree.

**Trust.** Before spawning, the driver sets `projects["<worktree absolute path>"].hasTrustDialogAccepted` to `true` in `~/.claude.json`, creating the project entry when absent and leaving every other key untouched. When the file is absent the driver creates it with only that entry. The file is written as `json.dump(..., indent=2, ensure_ascii=False)` plus a trailing newline, to `~/.claude.json.tmp` first and then renamed over the original, so a kill mid-write cannot empty the file. The project key is the worktree path exactly as `treehouse get` printed it. The driver reads the file once at start, before the pid file: absent is fine, a JSON object is fine, anything else is one stderr line `bad ~/.claude.json` and exit 1 before anything is touched. A read that fails mid-campaign (Claude Code rewrites the file) is a step 3 failure for that bead, handled as above; the driver never writes a file it could not parse.

**Events per bead, in order, in S3 with the stub worker and no review lane:** `bead.claimed`, `worktree.acquired`, `pane.spawned`, then the worker's own `pr.opened` is S4's business; S3 ends at `pane.spawned` and the reap path.

## 9. Review lane (S4)

The review lane is tick step 2, `review_pending()`, plus three commands: `smile review <pr>`, `smile gate ...`, `smile audit`. The reviewer is the normal signed-in `claude` in print mode; no API key, no separate config directory. GitHub is reached only through `gh`.

**Step 2, review.** The driver runs `gh pr list --state open --json number,headRefOid,body,labels --limit 200` in the main checkout. A pull request is a factory PR when its body contains a line `Bead: <id>` (the last such line wins). For each factory PR, in ascending number order: when the log holds no `pr.opened` event with that `pr`, append `pr.opened` (`bead`, `pr`, `sha` the head, `actor` `driver`). When the log holds no `review.verdict` event with that `pr` and `sha` equal to the current head, first count the `review.started` events at that `pr` and `sha` that no `review.verdict` at the same pair follows; when the count is 3 or more, skip the PR and, unless the log already holds one for that pair, append `watch.escalation` (`bead`, `pr`, `sha`, `actor` `driver`, `detail` `review failed 3 times`); otherwise run `smile review <n>` as a subprocess and wait; a non-zero exit is one stderr line and the tick continues with the next PR. Then the close path: the driver lists merged factory PRs (`gh pr list --state merged --json number,body,mergeCommit --limit 200`, the `Bead:` line as above); for each whose bead has no `bead.closed` in the log, whether or not it carries `smile:approved`: `bd close <id>`, append `pr.merged` (`bead`, `pr`, `sha` the merge commit from `mergeCommit.oid`, `actor` `human`; skipped when a `pr.merged` for that `pr` is already logged) and `bead.closed` (`bead`, `pr`, `actor` `driver`). A PR a human merged without a verdict is closed here and reported by `smile audit`; it is never a crash.

**`smile review <n>`.** Exit 2 unless `<n>` is one positive integer. Reads `gh pr view <n> --json number,title,state,headRefOid,headRefName,baseRefName,body`; the body must carry a `Bead:` line and `state` must be `OPEN`, else one stderr line and exit 1 with nothing logged. Takes the lock `<factory>/review/<n>.lock`, created exclusively with its pid inside and removed on every exit path; an existing lock naming a live pid is one stderr line ending `review already running (pid <p>)` and exit 1 with nothing logged, and any other existing lock is stale and replaced. Fetches the base and the head (`git fetch origin <baseRefName> <headRefName>`), runs `git worktree remove --force <factory>/review/<n>` and ignores its failure (a review killed mid-run leaves the path registered), creates a detached worktree there at the head SHA with `git worktree add --detach`, and removes it with `git worktree remove --force` on every exit path, success or failure. Appends `review.started` (`bead`, `pr`, `sha`, `actor` `reviewer`, `detail` the first reviewer model, or `custom` when `SMILE_REVIEW_CMD` is set). Renders `prompts/reviewer.md` from the main checkout with one-pass substitution of `{{pr_number}}`, `{{pr_title}}`, `{{bead_id}}`, `{{base_branch}}`, `{{spec_path}}` (as in section 8), `{{diff}}` (`git diff origin/<base>...<head>` run in the main checkout after the fetch above, so a stale local base branch never pads the diff, with `--stat` first then the patch, or the text `diff too large` when the patch exceeds 200000 bytes), and `{{issues}}` (for every open issue labeled `review` whose body has the line `PR: #<n>`: its number, title, body, and comments in order, separated by a line of dashes; the text `none` when there are none). Runs the reviewer with the rendered prompt on stdin and the review worktree as working directory: default argv `claude -p --model <first entry of reviewer.models> --permission-mode plan` (the reviewer reads and never edits); when `SMILE_REVIEW_CMD` is set and non-empty, its value split on whitespace with no glob expansion. The reviewer's environment carries `SMILE_PR`, `SMILE_REPO`, `SMILE_BEAD`, `SMILE_SHA`, `SMILE_BASE_BRANCH` on top of the caller's environment (a subprocess, not a pane, so `env` prefixing is not needed). Stdout is the review. The reviewer gets `reviewer.timeout` seconds (config below); on expiry the runtime kills it and that counts as a non-zero exit. The verdict is the first line matching `^Verdict: (APPROVE|REQUEST CHANGES)$`; blocking findings are every later line matching `^- \[(Critical|Important)\] (.+)$`. No verdict line, the reviewer exiting non-zero, or the timeout writes whatever the reviewer printed on stdout and stderr to `<factory>/reviews/<n>-<sha>.failed.md` (overwriting), then is one stderr line and exit 1 with nothing further logged, so the PR is reviewed again next tick, up to the cap in step 2. The full review text is written to `<factory>/reviews/<n>-<sha>.md` before the verdict is acted on.

On `REQUEST CHANGES`: ensure the label `review` exists (`gh label create review --force` is idempotent); for each blocking finding in order: when an open `review` issue already exists whose body's first line is that finding line and which carries `PR: #<n>` and `SHA: <sha>` (a retry after a partial failure), reuse it and log nothing; otherwise `gh issue create --title "PR #<n>: <finding text cut to 80 characters>" --label review --body "<finding line>\n\nPR: #<n>\nSHA: <sha>\nBead: <id>"` and append `issue.opened` (`bead`, `pr`, `sha`, `actor` `reviewer`, `detail` the issue number); then one PR comment listing the issue URLs one per line (`gh pr comment <n> --body`); then append `review.verdict` (`bead`, `pr`, `sha`, `actor` `reviewer`, `detail` `REQUEST CHANGES <k>` with `k` the number of blocking findings). A review that finds `REQUEST CHANGES` with no blocking finding lines is treated as no verdict (exit 1).

On `APPROVE`: for every open `review` issue whose body has `PR: #<n>`, listed afresh now rather than taken from the `{{issues}}` read before the reviewer ran, `gh issue close <i> --comment "Resolved at <sha>"` and append `issue.resolved` (`bead`, `pr`, `sha`, `actor` `reviewer`, `detail` the issue number); then append `review.verdict` (`detail` `APPROVE`). Then the gate decides: the PR is gated when the gate mode is `all`, or the mode is `auto` and the bead is gated, or the PR carries the label `human-gate`. Gated: `gh pr edit <n> --add-label smile:approved` (create the label with `gh label create --force` first) and stop; the merge is the human's. Not gated, and config `merge` is `auto`: `gh pr merge <n> --squash --delete-branch`, then append `pr.merged` (`bead`, `pr`, `sha` the merge commit from `gh pr view <n> --json mergeCommit`, `actor` `driver`), `bd close <id>`, append `bead.closed` (`bead`, `pr`, `actor` `driver`). Config `merge` set to anything but `auto` behaves as gated. A merge that fails (branch protection, conflict) is one stderr line and exit 1 with `review.verdict` already logged, so the PR is not re-reviewed; the watchtower (S5) reports a verdict without a merge.

Fix rounds. After `review.verdict` `REQUEST CHANGES` for bead X, `smile review` (still inside the same call) moves `runs/waiting/X.json` back to `runs/` and respawns the worker exactly as section 8's respawn does (same worktree, same order, `attempts` reset to 1, a new `pane.spawned`); the worker's order tells it that when its pull request already exists it must read the open `review` issues naming that PR, fix them, commit with `addresses #<i>`, push, and exit. A new head SHA has no verdict, so the next tick reviews it with `{{issues}}` filled. The lane does not parse `addresses`. After `bead.closed`, the waiting file is reaped by section 8 step 1 on the next tick (closed bead, dead pane: kill, return the worktree, `pane.reaped`, `runs/done/`); step 1 must therefore also walk `runs/waiting/`.

**`smile gate`.** State lives in `<factory>/gate.json`: `{"mode": "auto", "beads": ["<id>", ...]}` written compact with sorted keys plus a newline; absent means mode `auto` with no beads. `smile gate status` prints `mode <m>` then one line `bead <id>` per gated bead, sorted. `smile gate all|none|auto` sets the mode and prints nothing. `smile gate bead <id> on|off` adds or removes the bead and prints nothing. Anything else is exit 2. Gate changes append no event.

**`smile audit`.** Lists factory PRs (`gh pr list --state merged --json number,body,mergeCommit,headRefOid --limit 200`) whose log has no `review.verdict` with `detail` `APPROVE` at `sha` equal to `headRefOid`, one line each `#<n> <headRefOid> <bead>`, ascending; prints nothing when there are none; exit 0 unless `gh` fails (1). Extra arguments are exit 2.

**Config.** `reviewer.models`: comma-separated, default `opus`; S4 uses the first entry only. `merge`: `auto` (default) or `manual`. `reviewer.timeout`: seconds, default `600`, validated like `interval`. The reviewer always runs in `plan` permission mode; `worker.permission_mode` is not reused.

**Prompt and skill.** `templates/prompts/reviewer.md` is the rendered prompt and carries the execution rules the reviewer follows (read the diff against the spec, judge with the rubric, name principles by name, end with the `Principles applied` line, then the verdict line at column 0, then the finding lines, in the exact grammar above). `templates/.claude/skills/smile-code-reviewer/SKILL.md` is the same rules for a human-driven interactive review and is not read by the lane. S7 upgrades both.

**Events per bead through S4 with the stub worker and the stub reviewer forced to change once:** `bead.claimed`, `worktree.acquired`, `pane.spawned`, `pr.opened`, `review.started`, `issue.opened`, `review.verdict` (`REQUEST CHANGES 1`), then after the fix push `review.started`, `issue.resolved`, `review.verdict` (`APPROVE`), `pr.merged`, `bead.closed`, `pane.reaped`.

## 10. Evidence standard

This section is normative on what proves a behaviour. A `docs/SPEC.md` **Verify, live** box is checked by a fresh verifier agent that drives a fixture with the verify-smile primitives and pastes evidence into the pull request. Four things are that evidence.

1. The per-bead event sequences of sections 8 and 9, read from `.factory/events.jsonl`, with their `ts`, `event`, `bead`, `pr`, `sha`, `actor`, and `detail` fields, in the order those sections name.
2. The run-file locations under the factory directory: which bead files sit in `runs/`, `runs/waiting/`, `runs/done/`, and `runs/crashed/`, and when they moved.
3. The pane counts and handles reported by the mux backend, before and after each spawn and kill, in the handle grammar of section 7.
4. The pull request and issue states read back from GitHub through `gh`: open, merged with a merge commit, labelled, and the `review` issues with their `PR: #<n>` lines, open or closed.

A verifier's claim without such evidence is not a verified box. Neither is a script printing `PASS`, a driver log line saying it merged, or any summary written by the process under test. Evidence is read from the three stores, never from the driver's own stdout.

## 11. Watchtower (S5)

The watchtower is one long-lived pane per campaign that observes the event log and reports; it never edits code, beads, or GitHub. It speaks to the runtime only through `smile event`, `smile pause`, and the files below.

**Spawn.** In the tick, right after `campaign.start` is appended (that is, on the first tick with no live runs) and before the pause check of step 3, so a paused campaign keeps its observer, when config `watchtower` is `on` and `<factory>/watchtower.json` is absent or names a handle `smile mux alive` reports dead: render `prompts/watchtower.md` from the main checkout with one-pass substitution of `{{spec_path}}` and `{{base_branch}}` (as in section 8) and `{{repo}}` (the main checkout path), write it to `<factory>/orders/watchtower.md`, spawn with `smile mux spawn watchtower <main checkout> env SMILE_REPO=<path> SMILE_BASE_BRANCH=<branch> SMILE_ACTOR=watchtower <watchtower argv...>`, append `pane.spawned` (`bead` null, `actor` `driver`, `detail` the handle), and write `<factory>/watchtower.json` as `{"handle": "<handle>", "spawned_at": "<ts>"}` compact with sorted keys plus a newline. A dead watchtower is respawned the same way on any later tick, with a new `pane.spawned`; there is no attempt cap. When `watchtower` is `off` nothing is spawned and no event is written. Spawn failure is one stderr line and the tick continues; the bead steps are unaffected.

**Command.** Default argv: `claude --model <watchtower.model> --permission-mode plan <order text>` with the order text as one argument, byte for byte. When `SMILE_WATCHTOWER_CMD` is set and non-empty, its value is split on whitespace into argv with no glob expansion and the order path is appended as the last argument. The pane's working directory is the main checkout.

**Reap.** In step 4, before `campaign.complete` is appended: when `watchtower.json` exists, `smile mux kill <handle>` (a dead handle is not an error), append `pane.reaped` (`bead` null, `actor` `driver`, `detail` the handle), and remove the file. `campaign.complete` follows.

**Duties.** The watchtower tails `<factory>/events.jsonl` from the end of the file at start and appends to `<factory>/watch.md`, creating it: one line `<ts> <event> <bead> <detail>` per new event (null fields as `-`), so the file grows whenever the log grows. On seeing `worker.crashed` with `detail` `escalated` for bead X, and once per bead: append `watch.escalation` via `smile event watch.escalation bead=X actor=watchtower detail="crashed twice"` (section 4's `smile event` leaves unset fields null, so the actor is passed explicitly; `smile pause` signs itself from `SMILE_ACTOR`), then run `smile pause` (which appends `driver.paused` with `actor` `watchtower` when the pause file did not exist). On seeing `watch.escalation` with `detail` `review failed 3 times` (written by the driver, section 9) it writes the line to `watch.md` and does nothing else. It never removes the pause file; resuming is the human's `smile resume`. It runs `smile` as `$SMILE_REPO/smile/smile`, falling back to `smile` on PATH. Everything else it notices goes to `watch.md` only.

**Config.** `watchtower`: `on` (default) or `off`. `watchtower.model`: default `opus`; the fixture pins the command to the stub through `SMILE_WATCHTOWER_CMD`.

**Prompt and skill.** `templates/prompts/watchtower.md` is the rendered order and carries the duties above verbatim as instructions plus the intervention ladder from the ported skill (observe, never touch the build, escalate rather than act). `templates/.claude/skills/watchtower/SKILL.md` is the same for a human-driven interactive watch. Discord, the Downloads notepad, and predictions are dropped.

**Events with the stub worker set to crash twice on bead B, in order:** `campaign.start`, `pane.spawned` (bead null, the watchtower), then B's `bead.claimed`, `worktree.acquired`, `pane.spawned`, `worker.crashed` (`attempt 1`), `pane.spawned`, `worker.crashed` (`attempt 2`), `worker.crashed` (`escalated`), then the watchtower's `watch.escalation` (bead B, actor `watchtower`, detail `crashed twice`) and `driver.paused` (actor `watchtower`); after that no tick claims a bead until `smile resume` appends `driver.resumed`; at the end `pane.reaped` (bead null) precedes `campaign.complete`.
