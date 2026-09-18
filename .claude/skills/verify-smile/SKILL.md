---
name: verify-smile
description: >-
  Drive the SMILE software factory against a throwaway GitHub fixture repo and keep the proof.
  Use to verify any SMILE command (install, doctor, mux, loop, review, gate, watchtower,
  narrate) the way a user would run it, or when a spike PR needs its "Verify, live" box
  checked. Creates and removes a private repo named smile-verify-<runid> under the logged-in
  GitHub account.
---

# verify-smile

SMILE is a CLI stamped into a target repo. Its user path is a git repo with a bead graph, a
tmux session of worker panes, and pull requests on GitHub. This skill drives that path with a
disposable fixture and asserts the observable end state, never the driver's own summary.

Run everything through the helper. Its usage prints with no arguments.

	.claude/skills/verify-smile/scripts/verify-smile

State for one run is one manifest at `~/.smile-verify/<runid>/manifest.json`. Set
`SMILE_VERIFY_ROOT` to move that directory.

## Launch

`verify-smile up` builds a fixture and prints `fixture ready <runid> <path>`.

1. Creates a private repo `smile-verify-<runid>` under the logged-in account and clones it to a
   temp directory. `<runid>` is a UTC timestamp plus four hex characters.
2. Commits a README so `main` exists and pushes it.
3. Runs `BD_NON_INTERACTIVE=1 bd init --prefix sv`, then seeds two beads. Bead B depends on bead A,
   so `bd ready --json` lists only A. Their ids are in the manifest as `bead_a` and `bead_b`.
4. Opens a detached tmux session named `smile-verify-<runid>` rooted at the fixture.
5. Stamps SMILE with `python3 <smile-repo>/install.py <fixture>` when that file exists. The
   smile repo is the checkout this skill lives in, so a spike branch is what gets stamped.
   Until S1 lands there is no `install.py` and the manifest records `install: skipped`.

Two fixtures can run side by side. Each has its own repo, temp dir, tmux session, and manifest.
Never drive a fixture this skill did not create.

## Doctor

Before driving, answer "is this fixture worth driving?" read-only.

	verify-smile list                       runs and their state (up, down)
	gh repo view <owner/smile-verify-runid> exists and is private
	tmux has-session -t smile-verify-<runid>
	(cd <fixture> && bd ready --json)      lists exactly bead A

If any check fails, run `down` on that run and start a new one. Do not repair a fixture in place.

## Drive

`verify-smile feature <name> --runtime <bash|py> [--real-review] [--backend <b>] [--run <runid>]`
drives one feature from the map under `features/` and prints `PASS <name> ...` or
`FAIL <name>: <reason>`. Without `--run` it uses the newest run. A feature that has not landed
yet prints `NOT IMPLEMENTED <name>` and exits 2.

Exit codes. 0 pass, 1 fail, 2 not implemented.

The two stubs under `scripts/` let a run exercise the loop without spending model tokens.

- `stub-worker` replaces the worker pane. The driver launches it with `SMILE_WORKER_CMD`. It
  commits one file on `smile/<bead>`, pushes, and opens a PR with the trailer `Bead: <bead>`.
  Run again while that PR is open, it looks for open issues labeled `review` whose body has a
  line `PR: #<n>` naming the PR, appends a line, commits `fix: address review` with one
  `addresses #<issue>` body line per issue, and pushes. With no such issue it exits 4. The
  `PR: #<n>` line is the contract the review lane honors when it opens finding issues.
  `SMILE_STUB_CRASH_BEADS="<id>"` makes it exit 3 for that bead, `SMILE_STUB_CRASH_TIMES` times.
- `stub-reviewer` replaces the headless reviewer. The review lane launches it with
  `SMILE_REVIEW_CMD`, prompt on stdin. It prints `Verdict: APPROVE`. With
  `SMILE_STUB_CHANGES_ONCE=1` it prints `Verdict: REQUEST CHANGES` and one `- [Critical]` finding
  the first time it sees a PR, then approves.

`--real-review` runs the real headless reviewer instead of the stub for that feature. Expect
minutes, not seconds.

## Evidence

Every feature run appends to `~/.smile-verify/<runid>/<feature>.log`. `down` adds
`beads.json` (`bd list --json`), `prs.json` (`gh pr list --state all --json ...`), the fixture's
`.factory/` directory as `factory/` when it exists (event log, watch report), and the stamp log.

Proof standards. Assert the user-visible end state: PR state on GitHub, bead status in bd,
lines in `.factory/events.jsonl`. A driver log line saying it merged is not proof that the PR
merged. A feature that lists several entry points in its map file is verified only when each
was driven, or the log names which were skipped and why.

## Cleanup

`verify-smile down <runid>` collects evidence first, then kills only the tmux session it
created, removes only its own temp directory, and deletes the repo with
`gh repo delete --yes`. When the token lacks the `delete_repo` scope, it renames the repo to
`smile-verify-<runid>-trash` and archives it, and prints the `gh auth refresh` command that
enables deletion. Evidence survives. `down` prints `evidence kept at <dir>` and is safe to run
twice. It refuses a runid with no manifest.

`verify-smile gc --dry-run` lists leftover `smile-verify-*-trash` repos. Without the flag it deletes
them when the token has `delete_repo`, and otherwise prints the count and the refresh command.

A failed `up` tears itself down from what its manifest already records, so a run whose manifest
says `state: down` with a `stage` before `stamp` was a failed launch, not a driven fixture. `down`
refuses to mark a run down until the repo is gone or renamed and archived, so a partial
teardown stays retryable.

## Helpers

	scripts/verify-smile      up | feature | down | list
	scripts/stub-worker       worker stand-in, see Drive
	scripts/stub-reviewer     reviewer stand-in, see Drive
	scripts/live-check        runs Launch, Doctor, Drive install, Evidence, Cleanup once and prints each command; the proof to paste in a PR

`tests/verify-smile.test.sh` proves this skill against a real fixture. `tests/all.sh` runs it
with the other test files.
