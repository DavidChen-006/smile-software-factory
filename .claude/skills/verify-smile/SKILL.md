---
name: verify-smile
description: >-
  Drive the SMILE software factory against a throwaway GitHub fixture repo and keep the proof.
  Use when a pull request touching the runtime (install, doctor, mux, the driver loop, the review
  lane, gate, audit) needs its behavior proved live, or when a spike's "Verify, live" box has to be
  checked. A CLI of composable primitives plus a feature map: you compose the primitives to prove
  one specific behavior and paste the JSON. Creates and deletes a private repo named
  smile-verify-<runid> under the logged-in GitHub account.
---

# verify-smile

SMILE is a CLI stamped into a target repo. Its user path is a git repo with a bead graph, a tmux
session of worker panes, and pull requests and issues on GitHub. This skill drives that path with
a disposable fixture and asserts the observable end state, never the driver's own summary.

It is a lever, not a test suite. `scripts/verify-smile` is a CLI of primitives with machine-readable
output; [`features/`](features/README.md) is the map that says how to reach each behavior and what
end state proves it. Nothing here decides PASS or FAIL except `doctor`. The verifier decides.

	.claude/skills/verify-smile/scripts/verify-smile              usage
	.claude/skills/verify-smile/scripts/verify-smile <verb> --help

State for one run is one manifest at `~/.smile-verify/<runid>/manifest.json`. Set
`SMILE_VERIFY_ROOT` to move that directory. Every verb takes `--run <runid>` and uses the newest
run when it is left out, prints JSON on stdout (one object, or one object per line for a listing),
and prints one stderr line and exits non-zero on failure.

Prerequisites on the driving machine: `uv`, `git`, `gh` logged in, `bd`, `treehouse`, and `tmux`.
The fixture never runs the runtime directly. It runs it the way a user does, through the stamped
shim `<fixture>/smile/smile`, which execs `uv run` on `smile/py/smile.py`. uv picks the interpreter
from each entry point's PEP 723 header, so the machine's `python3` is not a prerequisite of SMILE.

## Launch

	verify-smile up
	verify-smile stamp
	verify-smile seed --beads 2

1. `up` creates a private repo `smile-verify-<runid>` under the logged-in account, clones it to a
   temp directory, commits a README so `main` exists, runs `BD_NON_INTERACTIVE=1 bd init --prefix
   sv`, and opens a detached tmux session named `smile-verify-<runid>` rooted at the fixture.
   `<runid>` is a UTC timestamp plus four hex characters. It stamps nothing and seeds no bead.
2. `stamp` runs `uv run <checkout>/install.py <fixture>`, commits and pushes the stamp as a user
   would, then runs `smile init`. `--from <checkout>` picks what to stamp; the default is the
   checkout this skill lives in, so a spike branch stamps itself.
3. `seed --beads <n>` creates the beads. `--deps <id>` blocks the new beads on that one, which is
   how the loop's ordering behavior is set up. `--title <text>` and `--description <text>` replace
   the throwaway title and give the bead a real work order, which is what a real worker needs; both
   apply to every bead the call creates, so a dogfood bead is seeded one call at a time.

Two fixtures can run side by side. Each has its own repo, temp dir, tmux session, and manifest.
Never drive a fixture this skill did not create.

**Pin `--run` whenever another fixture might be alive.** A verb with no `--run` resolves the newest
run, which is whichever fixture came up last on this machine, not necessarily yours. Two agents
driving at once, and the second one's `up` silently steals every later unpinned call: its ticks run
in your fixture, its events land in your log, and your reads answer for its world. Capture the
`runid` that `up` printed and pass `--run <runid>` on every verb of the drive, including `doctor`,
`events`, and `down`. Every page below writes the primitives without it for brevity; add it.

## Doctor

	verify-smile doctor

The one verb that judges. Read-only: the driving machine's tools, `gh auth`, the manifest state,
the repo on GitHub (exists and private), the tmux session, the fixture clone, `bd ready`, and, when
the fixture is stamped, `smile doctor` through the stamped shim. Prints `{"ok": true|false,
"checks": [...]}`; exit 0 when every check passed, 1 when any failed.

If any check fails, run `down` on that run and start a new one. Do not repair a fixture in place.

## Drive

Compose the primitives the map page names. The full list is in the usage; the ones that change the
world:

	verify-smile tick [--worker real] [--reviewer real] [--reviewer-changes-once]
	                  [--worker-crash <bead>] [--worker-sleep <s>]
	verify-smile review <n> [--reviewer stub|real|<argv...>]
	verify-smile gate <status|all|none|auto|bead <id> on|off>
	verify-smile close-bead <id>
	verify-smile kill-pane <bead>
	verify-smile time <smile args...> [--n 5]

`tick` is one `smile run --once` in the run's scratch world, with both stubs wired in. It prints
the tick's exit code and every event appended during it. A non-zero exit is reported, not raised: a
gh hiccup is normal and the next tick re-reads the world. Drive a multi-step behavior by ticking
until the end state appears.

`time` runs any `smile` command through the stamped shim n times and reports the median wall
milliseconds, plus the last run's exit and stdout. `--n 1` is how you run a command once and read
its output.

The two stubs under `scripts/` let a run exercise the lane without spending model tokens.

- `stub-worker` replaces the worker pane. It commits one file on `smile/<bead>`, pushes, and opens
  a PR with the trailer `Bead: <bead>`. Run again while that PR is open, it looks for open issues
  labeled `review` whose body has a line `PR: #<n>` naming the PR, appends a line, commits
  `fix: address review` with one `addresses #<issue>` body line per issue, and pushes. With no such
  issue it exits 4. `--worker-crash <bead>` makes it exit 3 for that bead; `--worker-sleep <s>`
  makes it sleep first, so its pane is still alive on the next tick.
- `stub-reviewer` replaces the headless reviewer, prompt on stdin. It prints `Verdict: APPROVE`.
  With `--reviewer-changes-once` it prints `Verdict: REQUEST CHANGES` and one `- [Critical]`
  finding the first time it sees a PR, then approves.

`tick --worker real` drops `SMILE_WORKER_CMD` so the driver spawns its own `claude -p` in the pane,
and `tick --reviewer real` drops `SMILE_REVIEW_CMD` so every review that tick runs uses the
signed-in `claude -p`. Either flag runs the whole tick under the caller's real `HOME`, because the
scratch one is not signed in; `GH_TOKEN` and `GH_CONFIG_DIR` still ride the fixture tmux session, so
the pushes and pull requests land on the fixture repo and nothing else. Expect minutes per bead.

`review <n>` is one `smile review <n>` on one pull request, which is the only way to choose the
reviewer. `--reviewer real` runs the signed-in `claude -p` with the user's real `HOME` for that
subprocess, because the run's scratch HOME is not signed in and every attempt there fails. Expect
minutes and real tokens; see [features/review.md](features/review.md).

## Evidence

	verify-smile events [--bead <id>] [--since <n>]
	verify-smile runs | panes | prs | issues | trust
	verify-smile evidence

Proof standards.

- **Real user path.** Drive the stamped shim and the real `gh`, `bd`, and tmux. Never an internal
  setter, never a test-only entry point. The stubs stand in only for the two model processes, the
  boundary the runtime already isolates behind `SMILE_WORKER_CMD` and `SMILE_REVIEW_CMD`.
- **Action plus resulting state.** Paste the primitive invocations and the JSON they printed, in
  order. The end state alone does not show how it was reached; the commands alone do not show it
  worked.
- **Side effects.** A behavior is not proved by its event line alone. Check what it touched:
  `prs` for GitHub's own PR state and `mergedAt`, `issues` for the finding issues, `runs` for the
  run state files and the directory each sits in, `panes` for the window count, `trust` for the
  `~/.claude.json` entries, `evidence` for the files on disk.
- **Second view on a mutation.** A merged PR is proved by `prs`, not by `pr.merged`. A closed bead
  is proved by `beads.json` or `close-bead`'s read-back, not by `bead.closed`.
- **The evidence directory.** `~/.smile-verify/<runid>/` holds the manifest, the installer
  transcript, the tick log, the run's scratch `home/`, and, after `down`, `beads.json`, `prs.json`,
  and the fixture's whole `.factory/` as `factory/` (event log, reviews, gate file, run state).
  It survives `down`. It is where a proof is pasted from, and the paths in it stay quotable after
  the fixture repo is gone.

A behavior whose map page lists several entry points is verified only when each was driven, or the
proof names which were skipped and why.

## Cleanup

	verify-smile down [--dry-run]
	verify-smile gc [--dry-run]

`down` collects evidence first, then kills only the tmux session it created, removes only its own
temp directory, and deletes the repo with `gh repo delete --yes`. When deletion fails (a token
without `delete_repo`) it falls back to renaming the repo to `smile-verify-<runid>-trash` and
archiving it, and prints the `gh auth refresh` command that enables real deletion. `--dry-run`
prints what it would dispose of and touches nothing.

Evidence survives. `down` is safe to run twice, refuses a runid with no manifest, and refuses to
mark a run down until the repo is really gone, so a partial teardown stays retryable. A failed `up`
tears itself down from what its manifest already records.

`gc --dry-run` lists leftover `smile-verify-*-trash` repos from the fallback path; without the flag
it deletes them.

Kill every tmux session you opened. `down` owns the fixture's; any session of your own is yours.

## Helpers

	scripts/verify-smile      the primitives; `<verb> --help` for each
	scripts/stub-worker       worker stand-in, see Drive
	scripts/stub-reviewer     reviewer stand-in, see Drive

	tests/live/verify-smile.test.sh   the harness self-test: proves the primitives against a real fixture
	tests/live.sh                     runs it (and any other live test file); minutes, needs a logged-in gh

`tests/all.sh` is the offline unit suite and does not run it. Run the self-test yourself
(`bash tests/live.sh`) when the pull request under verification touches this skill's scripts, or when
a primitive misbehaves and you need to know whether the harness or the runtime is at fault.

## How a verifier uses this

You are proving one specific pull request's behavior, cold.

1. **Read the map page** for the behavior under test, in [`features/`](features/README.md). It
   names the sub-features, every user entry point, the exact primitive invocations, the observable
   end state that proves it, and the traps. If the PR changes a behavior the map does not describe,
   say so: that is a finding against the map.
2. **Launch.** `up`, `stamp`, `seed --beads <n>`. Stamp the branch under test, not `main`.
3. **Doctor.** `verify-smile doctor`. A failing check means a new fixture, not a repair.
4. **Drive with the primitives only.** Compose what the page names. Do not add a step the page does
   not describe without saying you did.
5. **Capture.** Keep every invocation and the JSON it printed, in order, plus the end-state reads
   the page's `Evidence that proves it` section lists.
6. **Clean up.** `verify-smile down`. Then `verify-smile evidence` to confirm the directory
   survived, and `gh repo list <owner>` to confirm the fixture repo is gone.
7. **Paste.** The commands, the JSON, and the end state, as evidence. Say what you drove, what you
   skipped, and what you could not reach. Do not write PASS; write what the state was.
