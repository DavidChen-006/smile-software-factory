# SMILE software factory build plan

SMILE turns a spec into merged, reviewed code with agents in visible panes and a deterministic script driving them. This document freezes the design agreed on 2026-09-18 and lays out the spikes that build it. Two runtimes, bash and Python, were built side by side and measured; Python won and is the only runtime. Spikes run in this order. S0 verification harness, S1 core, S2 mux seam, S3 driver, S4 review, S5 watchtower, S6 narration, S7 skills, S8 backends, S9 dogfood.

## How to read this

One box is one unit of work. Every box names the evidence that checks it. A nested box is a sub-step of the box above it. Check a box only when its evidence exists, a file, a log line, a transcript, a test run, or a SHA. The body is a how-to. The appendices explain and record.

The program runs under the Orchestrate playbook in `.claude/skills/poteto-mode/playbooks/orchestrate.md`, adapted as the Program checklist below says. The orchestrator merges. David approves this document once and reviews the dogfood in S9.

Tests alone are not sufficient verification. A spike is verified only when its unit and live boxes are all checked, and the two kinds of box are checked by different people.

A **Verify, unit** box is the builder's. The builder runs the named test command itself and pastes its output into the pull request. Builders no longer drive live features.

A **Verify, live** box names a behaviour and the observable evidence that proves it. It is checked by a fresh verifier agent, not by the builder. The verifier reads the feature map page for that behaviour under `.claude/skills/verify-smile/features/`, brings up a fixture, composes the verify-smile primitives the page names, and pastes the evidence into the pull request before the cold review verdict is written. A live box is never satisfied by a script printing `PASS`. It is satisfied only by evidence a reader can check against the event sequences, run-file locations, pane counts, and pull request and issue states in `docs/RUNTIME-CONTRACT.md`, section 10 of which is normative on what counts as evidence.

## Design

This section is the frozen design. Every spike implements a part of it. A spike that finds the design wrong stops and reports rather than quietly diverging.

Both runtimes were built side by side through S2 and half of S3. On 2026-09-18 the owner chose Python, and the bash runtime was removed in the PR that carries this paragraph. Everything below names py files only. `docs/bakeoff.tsv` stays as the record of the measurements, and Appendix E records the decision.

### How verification works

Decided 2026-09-18, after S3 and during S4. The verification harness stopped being a set of canned `verify-smile feature <name>` scripts that each print `PASS`. A canned script is thin and gameable. Its `PASS` is one line a reader cannot check, it hides what it did not assert, and a script that must generalise across every spike cannot test what is unique to one. So the harness became a lever instead of a verdict. `.claude/skills/verify-smile/` exposes a CLI of composable primitives with JSON output, `up`, `stamp`, `seed`, `tick`, `events`, `runs`, `panes`, `prs`, `issues`, `gate`, `close-bead`, `kill-pane`, `time`, `trust`, `evidence`, `doctor`, `down`, `list`, and `gc`, and a feature map under `features/`, one page per behaviour with the sections `Sub-features`, `How to get to it (user POV)`, `Driving it with verify-smile`, `Gotchas`, and `Evidence that proves it`. A fresh verifier agent per pull request reads the map page for the behaviour that pull request claims, brings up a fixture, composes the primitives to drive it, and pastes the evidence into the pull request. Builders keep their unit tests and no longer run live features themselves. The evidence standard is `docs/RUNTIME-CONTRACT.md` section 10.

### Four lanes

- Planning is an advisory ladder. Grill, then architect, then preflight, then campaign. Only the spec freeze is enforced. Campaign refuses to run without a frozen spec in `docs/`.
- Graph is bd. The bead graph holds the work. `bd ready` never shows a bead whose blockers are open.
- Loop is the driver. Each tick the driver claims ready beads, acquires a treehouse worktree per bead, spawns a worker pane through the mux seam, reviews open pull requests that have no verdict at their head commit, merges verified approvals, closes beads, and reaps panes.
- Watcher is the watchtower. The driver spawns it as one more pane at campaign start. It reads the event log, writes escalation events, and can pause the driver.

### The bus

Agents never message each other. Three stores carry all state.

- The event log at `.factory/events.jsonl` in the target repo. One JSON object per line with the fields `ts`, `event`, `bead`, `pr`, `sha`, `actor`, and `detail`. Worktrees resolve the path through the main checkout so every process writes the same file.
- The bd database.
- GitHub pull requests and issues.

The event names are `campaign.start`, `bead.claimed`, `worktree.acquired`, `pane.spawned`, `pr.opened`, `review.started`, `review.verdict`, `issue.opened`, `issue.resolved`, `pr.merged`, `bead.closed`, `pane.reaped`, `worker.crashed`, `watch.escalation`, `driver.paused`, `driver.resumed`, and `campaign.complete`. The planner session that started the driver tails this file and narrates it to the user.

### The mux seam

The driver spawns and reaps panes only through three verbs.

	smile mux spawn <name> <cwd> <command>   prints an opaque handle
	smile mux alive <handle>                 exit 0 when the pane is alive
	smile mux kill <handle>

One file per backend implements the verbs. The config key `backend` selects one. When the key is absent the doctor picks the first installed backend in the order tmux, cmux, herdr. The tmux backend is the default and the one the verification harness drives.

### The worker contract

The driver launches a worker in its worktree with the configured worker model and a work order built from the bead. The worker commits on branch `smile/<bead-id>`, opens a pull request whose body ends with the trailer `Bead: <bead-id>`, and then polls its pull request for review issues. A fix commit carries `addresses #<issue>` in its message. The worker never merges and never touches bd.

### The reviewer contract

The driver runs the reviewer headless with the normal signed-in Claude. The reviewer runs inside a detached worktree pinned at the pull request head and receives the reviewer skill, the diff, the frozen spec, and any open issue thread. It answers `APPROVE` or `REQUEST CHANGES` with findings. Only verified findings block. On `REQUEST CHANGES` the driver opens one GitHub issue per blocking finding with the label `review`, whose body carries the line `PR: #<n>` on its own line, and comments on the pull request with the issue links. On `APPROVE` with `merge` set to `auto`, the driver squash-merges the pull request and closes the bead. With `merge` set to `human`, or when the bead carries the label `human-gate`, the driver labels the pull request `smile:approved` and closes the bead when a human merges it. The config key `reviewer.models` is a list. One review runs per model and a lead-judgment step merges the findings. The default list has one entry.

### Prerequisites

`smile doctor` refuses to run with a named reason when any of these is missing. uv, git, gh with a logged-in account, claude, bd, treehouse, and at least one of tmux, cmux, or herdr. Doctor prints eight lines, `uv` first.

uv owns the interpreter. Every entry-point script, the runtime's `smile/py/smile.py` and the repo's `install.py`, carries PEP 723 inline script metadata with `requires-python = ">=3.12"` and `dependencies = []`, and runs through `uv run`, so uv chooses and fetches the interpreter and the machine's own python never matters. The shim execs `uv run`, and so do the tests. There is no Python version to install and no second test pass. `docs/RUNTIME-CONTRACT.md` is normative on this.

### What the installer stamps

`install.py` in the skill repo copies these into the target repo. A force flag replaces stamped files that drifted.

- `smile/smile`, the entry script. It finds the repo root and dispatches to `smile/py/`.
- `smile/py/`, the runtime. It exposes the commands `doctor`, `init`, `run`, `review`, `gate`, `audit`, `pause`, `resume`, `status`, and `mux`.
- `.claude/skills/` with campaign, preflight, watchtower, smile-code-writer, smile-code-reviewer, test-writer, draftspec, grilling, and architect.
- `smile.config.yaml` with the keys `backend`, `worker.model`, `worker.permission_mode`, `reviewer.models`, `max_parallel`, `watchtower`, `merge`, and `base_branch`.
- `prompts/worker.md`, `prompts/reviewer.md`, and `prompts/watchtower.md`.
- A `.gitignore` line for `.factory/`.

`smile init` runs once per repo. It runs `bd init`, writes the treehouse config and `.worktreeinclude`, and creates `.factory/`.

### The bakeoff

Both runtimes implemented the same command set and emitted the same events, so the verification harness could drive either one. `docs/bakeoff.tsv` records one row per spike per runtime with these columns, measured by the orchestrator after both pull requests merge. `spike`, `runtime`, `verify_result`, `verify_seconds`, `lines`, `files`, `reader_load`, and `notes`. `reader_load` is the cold reviewer's score from 1 to 5 on the two axes in the minimize-reader-load principle, layers to trace and state to hold, averaged. After S4 the orchestrator writes a recommendation in Appendix E and David picks the runtime. The other runtime is deleted before S5 begins.

### Cuts

Not built. Discord and the OpenClaw gateway, remote workers through crabbox and E2B, pane nudges, push-to-main review, git hooks, and state under the home directory.

## Program checklist

### Arm the program

- [ ] Post this plan to David and continue with S0, which no design detail can invalidate. Fold his corrections into a revision before S1 starts.
- [ ] Keep the trail in `docs/decisions.tsv` through `.claude/skills/show-me-your-work/scripts/log.sh`. One row per spike verdict, pivot, or gate.
- [ ] Standing orders for every writer, pasted verbatim into every brief. Read `docs/SPEC.md` first. Write only inside the paths the brief names. Never merge. Never edit `docs/SPEC.md`. Run the spike's unit test command and paste its output; the live boxes are a fresh verifier agent's, not yours. Report deviations from the design as findings, not as silent fixes. Cite by name each pstack principle that shaped a choice. If a tool call is denied by the permission system, stop, do not work around it with another tool, and report the denial.
- [ ] Post a status line to David at each spike merge. Spike, runtime, verdict, PR link.

### Spawn owners

- [ ] One fresh agent per spike per runtime, on Opus 5 at high effort (reviewers stay on the orchestrator's model), with a self-contained brief: the spike section, the contracts it must honor, the standing orders, conventions, file pointers, and the branch name. No inherited chat. David's call after S0: a good brief beats a fork.
- [ ] Runtime spikes S1 to S4 spawn a bash writer and a Python writer in parallel from the same brief, per the arena skill. Shared runtime-neutral pieces (installer, shim, config format, `docs/RUNTIME-CONTRACT.md`) were written once first, in S1, so the two runtimes implement one contract.
- [ ] S0, S5 to S9 spawn one writer each. S5 and later target the runtime David picked.
- [ ] Each writer works on its own branch in an isolated git worktree of this repo. Branch names are `spike/<id>-<runtime>` or `spike/<id>`.
- [ ] Dependencies. S1 after S0. S2 after S1. S3 after S2. S4 after S3. S5, S6, and S7 after S4 and the bakeoff decision, in parallel. S8 after S5. S9 after S6, S7, and S8.

### PR mechanics, for every spike

- [ ] The writer commits through `~/.claude/skills/git-ops/scripts/commit.sh` with a conventional message and pushes through `push.sh`.
- [ ] The writer opens the pull request with `gh pr create`. The body names what it built, the unit test command and its output, deviations, and the principles it cited.
- [ ] A fresh verifier agent, never the writer and never a fork of it, checks the live boxes. It reads the feature map page each box names, brings up a fixture, composes the verify-smile primitives, and pastes the evidence into the pull request. It writes no code.
- [ ] A fresh non-fork subagent reviews the pull request cold with `.claude/skills/interrogate/references/rubric.md` and `code-quality-review.md`, then the orchestrator applies `lead-judgment.md`. Findings with the category Act On go back to the writer as a follow-up commit.
- [ ] The orchestrator reads the diff and the verify evidence itself before merging. A writer's summary is not evidence.

### Verdict and merge, for every spike

- [ ] Verify, unit boxes checked with the builder's pasted test output, and Verify, live boxes checked with the verifier's pasted evidence. A `PASS` line is not evidence.
- [ ] No open Act On finding.
- [ ] The orchestrator squash-merges through `gh pr merge --squash --delete-branch` and logs a trail row with the merge SHA and the verdict.
- [ ] For S1 to S4 the orchestrator also writes both bakeoff rows.

### Boot recipe, for every live verify

- [ ] The verifier composes the `verify-smile` primitives from S0. `up` creates a private repo `smile-verify-<runid>` under David's GitHub account and clones it to a temp directory, `stamp` stamps SMILE from the branch under test and runs `smile init`, `seed` seeds a two-bead graph where bead B depends on bead A, and `tick` runs the driver with the stub worker. `events`, `runs`, `panes`, `prs`, and `issues` read the state back as JSON.
- [ ] Panes open in a tmux session named `smile-verify-<runid>`.
- [ ] Evidence is copied to `~/.smile-verify/<runid>/` before cleanup. `events.jsonl`, the pull request list as JSON, the bd list, and the driver log.
- [ ] Cleanup kills that tmux session, deletes the repo through `gh repo delete --yes`, and removes the temp directory. Evidence survives.

## Build the verification harness (S0)

**Depends on.** None.

**Files.**

- [ ] Create `.claude/skills/verify-smile/SKILL.md`.
- [ ] Create `.claude/skills/verify-smile/features/README.md` and one page per behaviour. `install.md`, `doctor.md`, `mux.md`, `loop.md`, `review.md`, `gate.md`, `watchtower.md`, `narrate.md`. Each page carries the sections `Sub-features`, `How to get to it (user POV)`, `Driving it with verify-smile`, `Gotchas`, and `Evidence that proves it`.
- [ ] Create `.claude/skills/verify-smile/scripts/verify-smile`, the helper.
- [ ] Create `.claude/skills/verify-smile/scripts/stub-worker`, a script that behaves as a worker. It writes one file, commits on `smile/<bead-id>`, opens a pull request with the bead trailer, and exits. On a rerun where the pull request exists, it appends a line, commits with `addresses #<issue>` for each open `review` issue naming that pull request, pushes, and exits.
- [ ] Create `.claude/skills/verify-smile/scripts/stub-reviewer`, a script that answers `APPROVE` for any diff. The `--real-review` flag of the helper uses the real reviewer instead.

**Build.**

- [ ] `verify-smile up` creates the fixture per the boot recipe and prints the run id and paths.
- [ ] `verify-smile` exposes composable primitives with JSON output, `up`, `stamp`, `seed`, `tick`, `events`, `runs`, `panes`, `prs`, `issues`, `gate`, `close-bead`, `kill-pane`, `time`, `trust`, `evidence`, `doctor`, `down`, `list`, and `gc`, which a verifier composes per a feature map page. No primitive prints a verdict.
- [ ] `verify-smile down <runid>` runs cleanup and confirms the evidence directory still exists.
- [ ] Assertions read `events.jsonl`, `gh pr list --json`, and `bd list --json`. Never the driver's own summary.

**You see.**

- [ ] `verify-smile up` prints `fixture ready <runid> <path>` and `gh repo view smile-verify-<runid>` succeeds.
- [ ] `verify-smile down <runid>` prints `evidence kept at ~/.smile-verify/<runid>` and `gh repo view` fails with not found.

**Verify, unit.** Tests alone are not sufficient verification. A spike is verified only when its unit and live boxes are all checked.

- [ ] `tests/verify-smile.test.sh` runs `up`, asserts the fixture layout, runs `down`, asserts the repo is gone and the evidence remains. Run `bash tests/verify-smile.test.sh`.

**Verify, live.** Tests alone are not sufficient verification. A live box is checked by a fresh verifier agent that drives the fixture with the verify-smile primitives per the feature map page the box names, and pastes the evidence. A script printing `PASS` is not evidence.

- [ ] Verifier drives the harness itself per `features/install.md` and shows the run through `up`, `stamp`, `seed`, `evidence`, and `down` end to end, showing the `up` line naming the runid and path, `gh repo view smile-verify-<runid>` succeeding while up and failing with not found after `down`, and the evidence directory listing `beads.json` and `prs.json` after cleanup with `beads.json` naming both seeded beads. `events.jsonl` first exists after S1.

**Review gate.** None. S0 is not review-gated.

**Merge.**

- [ ] Cold review has no open Act On finding.
- [ ] Squash-merged, trail row written.

## Build the core: log, config, doctor, init, installer (S1)

**Depends on.** S0.

**Files.**

- [ ] Create `templates/smile/smile`. It execs `uv run` on the runtime and exits 2 with `smile: uv is not on PATH` when uv is absent.
- [ ] Create `templates/smile/py/smile.py`, carrying the PEP 723 header with `requires-python = ">=3.12"` and `dependencies = []`, and the `smile/py/` package with the commands `doctor`, `init`, `status`, `pause`, `resume`, plus the events and config modules. Only the entry point carries the header; the imported modules do not.
- [ ] Create `templates/smile.config.yaml`, `templates/prompts/`, and `templates/.claude/skills/` placeholders.
- [ ] Create `install.py` at the repo root, carrying the same PEP 723 header, and `.claude/skills/smile/SKILL.md`, the skill that runs it.
- [ ] Create `tests/test_core.py` and the wrapper `tests/core-py.test.sh`, which runs the suite once through `uv run python -m unittest tests.test_core`.

**Build.**

- [ ] `install.py <repo> [--force]` stamps the files listed in Design and refuses to overwrite a drifted file without the flag.
- [ ] `smile doctor` checks each prerequisite and prints one line per check with `ok` or `missing <reason>`, eight lines with `uv` first. Exit 1 on any missing.
- [ ] `smile init` runs `bd init`, writes the treehouse config, writes `.worktreeinclude`, creates `.factory/`, and appends a `campaign.start` placeholder only when asked.
- [ ] `lib/events` appends one JSON line with the schema in Design. Concurrent writers append whole lines.
- [ ] `lib/config` reads `smile.config.yaml` and prints one key. Missing keys fall back to defaults named in the template.
- [ ] `smile pause` creates `.factory/pause`. `smile resume` removes it. `smile status` prints bead counts, open pull requests, and the last ten events.

**You see.**

- [ ] `uv run install.py /tmp/x` prints one line per stamped file. A second run prints `unchanged` per file. Editing a stamped file and re-running prints `drifted, use --force`.
- [ ] `smile doctor` in a repo with everything installed prints all `ok` and exits 0.

**Verify, unit.** Tests alone are not sufficient verification. A spike is verified only when its unit and live boxes are all checked.

- [ ] `tests/test_core.py` covers install, drift refusal, force, doctor with a missing tool on PATH, events schema, config defaults, pause and resume. Run `bash tests/core-py.test.sh`, which runs the suite once through `uv run`.

**Verify, live.** Tests alone are not sufficient verification. A live box is checked by a fresh verifier agent that drives the fixture with the verify-smile primitives per the feature map page the box names, and pastes the evidence. A script printing `PASS` is not evidence.

- [ ] Verifier drives install and doctor per `features/install.md` and `features/doctor.md` and shows the installer's per-file lines on a first stamp, the `unchanged` lines on a second, the `drifted <path>, use --force` line after editing a stamped file and the `replaced` line under `--force`; and, on a PATH with no `python3`, the eight doctor lines in contract order, `uv` first, all `ok` with exit 0, plus one run with a prerequisite removed showing its `missing <tool> <reason>` line and exit 1. The doctor transcript is in the evidence directory. The verifier also pastes a timing table for the uv runtime, with wall-clock seconds for the first `uv run` of the shim on a cold uv cache, the same call warm, and one `tests/core-py.test.sh` pass, so the cost of the new prerequisite is on the record next to the bakeoff numbers.

**Review gate.** None. S1 is not review-gated.

**Merge.**

- [ ] Cold review has no open Act On finding.
- [ ] Both bakeoff rows written. Squash-merged, trail row written.

## Build the mux seam with the tmux backend (S2)

**Depends on.** S1.

**Files.**

- [ ] Create the `mux` module and `backends/tmux.py` under `templates/smile/py/`.
- [ ] Create `tests/test_mux.py`.

**Build.**

- [ ] `smile mux spawn <name> <cwd> <command>` opens a tmux window in the session named by config or `smile-<repo>`, runs the command in `<cwd>`, and prints the handle `tmux:<session>:<window-id>`.
- [ ] `smile mux alive <handle>` exits 0 while the window exists and its pane's process is running.
- [ ] `smile mux kill <handle>` kills the window and exits 0 even when it is already gone.
- [ ] The backend file is selected from `backend` in config, or from the doctor's auto-detect order.
- [ ] Workers launch with the target folder pre-trusted so no trust prompt appears. The setting is recorded in Appendix A.

**You see.**

- [ ] `smile mux spawn t /tmp sleep 30` prints a handle, `tmux list-windows -t smile-<repo>` shows `t`, `alive` exits 0, `kill` removes it, `alive` exits 1.

**Verify, unit.** Tests alone are not sufficient verification. A spike is verified only when its unit and live boxes are all checked.

- [ ] `tests/test_mux.py` covers spawn, alive on a running and an exited command, kill, double kill, and a missing backend name. Run `bash tests/mux-py.test.sh`, which runs the suite once through `uv run`.

**Verify, live.** Tests alone are not sufficient verification. A live box is checked by a fresh verifier agent that drives the fixture with the verify-smile primitives per the feature map page the box names, and pastes the evidence. A script printing `PASS` is not evidence.

- [ ] Verifier drives the mux seam per `features/mux.md` and shows the window count in the fixture session before any spawn, the three handles printed by the three `smile mux spawn` calls in `tmux:<session>:@<id>` form, the window count after, three higher, with `panes` listing each handle's window, `alive` exiting 0 for each, then `kill-pane` on each, `alive` exiting 1 for each, and the window count back at the starting number.

**Review gate.** None. S2 is not review-gated.

**Merge.**

- [ ] Cold review has no open Act On finding.
- [ ] Both bakeoff rows written. Squash-merged, trail row written.

## Build the driver (S3)

**Depends on.** S2.

**Files.**

- [ ] Create `run.py` and `worktree.py` under `templates/smile/py/`.
- [ ] Create `templates/prompts/worker.md`.
- [ ] Create `tests/test_driver.py`.

**Build.**

- [ ] `smile run [--once] [--interval N]` holds a singleton pidfile per repo and refuses a second instance.
- [ ] Each tick, when `.factory/pause` is absent, the driver lists ready beads through `bd ready --json` and claims with `bd update <id> --claim`, claims up to `max_parallel` minus running, acquires a worktree per claim through `treehouse get`, writes the work order from `prompts/worker.md` and the bead, spawns the worker through `smile mux spawn`, and logs `bead.claimed`, `worktree.acquired`, and `pane.spawned`.
- [ ] Each tick the driver reaps panes whose bead is closed, returns their worktree through `treehouse return`, and logs `pane.reaped`.
- [ ] A pane that dies with its bead still open is logged `worker.crashed`. The bead is respawned once. A second crash leaves the bead claimed and logs an escalation.
- [ ] The worker command is `claude --model <worker.model> --permission-mode <worker.permission_mode> "<work order>"` by default and `SMILE_WORKER_CMD` when set, which the harness uses for the stub. Before spawning, the driver marks the worktree path trusted in `~/.claude.json`.
- [ ] The driver exits with `campaign.complete` when no bead is open.

**You see.**

- [ ] With two beads seeded and the stub worker, `smile run --once` logs two claims, two spawns, and two pull requests appear in `gh pr list`.

**Verify, unit.** Tests alone are not sufficient verification. A spike is verified only when its unit and live boxes are all checked.

- [ ] `tests/test_driver.py` covers singleton refusal, pause skips claims, max_parallel cap, crash respawn once, and event order. bd and treehouse are real. The mux backend is a fake that records calls. Run `bash tests/driver-py.test.sh`, which runs the suite once through `uv run`.

**Verify, live.** Tests alone are not sufficient verification. A live box is checked by a fresh verifier agent that drives the fixture with the verify-smile primitives per the feature map page the box names, and pastes the evidence. A script printing `PASS` is not evidence.

- [ ] Verifier drives the loop per `features/loop.md` and shows, for each bead, the event lines from `events` in the contract order of section 8's last paragraph, `bead.claimed`, `worktree.acquired`, `pane.spawned`, with their `ts`, `bead`, `actor`, and `detail` fields; the run files from `runs` moving from `runs/` to `runs/waiting/` once the worker has opened its pull request and to `runs/done/` after the bead is closed and the pane reaped; the pane count from `panes` rising by two after the first `tick` and falling back to the starting count after the second; the two pull requests from `prs` each carrying a `Bead: <id>` trailer; and, after `close-bead` on both and a second `tick`, two `pane.reaped` lines and one `campaign.complete`. The full sequence through review and merge is S4's live box.

**Review gate.** None. S3 is not review-gated.

**Merge.**

- [ ] Cold review has no open Act On finding.
- [ ] Both bakeoff rows written. Squash-merged, trail row written.

## Build the review lane (S4)

**Depends on.** S3.

**Files.**

- [ ] Create the `review`, `gate`, and `audit` modules under `templates/smile/py/`.
- [ ] Create `templates/prompts/reviewer.md` and `templates/.claude/skills/smile-code-reviewer/SKILL.md` as a first version with the current reviewer execution rules. S7 upgrades the rubric.
- [ ] Create `tests/test_review.py`.

**Build.**

- [ ] Each driver tick lists open pull requests with the `Bead:` trailer and no `review.verdict` event at their head SHA, and runs `smile review <pr>` for each, serially.
- [ ] `smile review <pr>` creates a detached worktree at the head, runs the reviewer command, parses the verdict, logs `review.started` and `review.verdict`, and removes the worktree on exit. The reviewer command is `claude -p` with the reviewer skill inlined and `SMILE_REVIEW_CMD` when set.
- [ ] On `REQUEST CHANGES` the driver opens one issue per blocking finding with the label `review`, comments on the pull request with the issue links, and logs `issue.opened`.
- [ ] A fix commit whose message contains `addresses #N` re-triggers review with the issue thread in the prompt. An `APPROVE` on a fix closes the issue and logs `issue.resolved`.
- [ ] On `APPROVE` with `merge` set to `auto` and no `human-gate` label, the driver squash-merges, closes the bead with `bd close`, and logs `pr.merged` and `bead.closed`.
- [ ] `smile gate status|all|none|auto` and `smile gate bead <id> on|off` set the human gate, read at verdict time.
- [ ] With the gate on, an `APPROVE` labels the pull request `smile:approved` and the next tick that finds it merged closes the bead.
- [ ] `smile audit` lists pull requests merged without a verdict at their merge SHA.

**You see.**

- [ ] With the stub reviewer forced to `REQUEST CHANGES` once, the fixture shows one issue labeled `review`, a comment on the pull request, then after a fix push the issue closed and the pull request merged.

**Verify, unit.** Tests alone are not sufficient verification. A spike is verified only when its unit and live boxes are all checked.

- [ ] `tests/test_review.py` covers verdict parsing, the no-verdict-at-head filter, issue creation from findings, the human gate matrix, and audit. GitHub calls go through a recorded fake of `gh`. Run `bash tests/review-py.test.sh`, which runs the suite once through `uv run`.

**Verify, live.** Tests alone are not sufficient verification. A live box is checked by a fresh verifier agent that drives the fixture with the verify-smile primitives per the feature map page the box names, and pastes the evidence. A script printing `PASS` is not evidence.

- [ ] Verifier drives the changes-then-approve path per `features/review.md` with the stub reviewer forced to request changes once, and shows the `review.verdict` line with `detail` `REQUEST CHANGES 1` at the first head SHA; the issue from `issues`, labeled `review`, with the `PR: #<n>` line in its body; the pull request comment carrying that issue URL; the fix round, the run file returning from `runs/waiting/` to `runs/`, the second `pane.spawned`, and the fix commit whose message contains `addresses #<issue>` at a new head SHA; the `issue.resolved` line and the issue closed in `issues`; the `review.verdict` line with `detail` `APPROVE` at that SHA; and the merge, `prs` showing the pull request merged with its merge commit and `close-bead` unnecessary because the bead is already closed. The pasted `events` output is the full per-bead sequence of the contract's section 9 last paragraph, in that exact order. `bead.claimed`, `worktree.acquired`, `pane.spawned`, `pr.opened`, `review.started`, `issue.opened`, `review.verdict`, `review.started`, `issue.resolved`, `review.verdict`, `pr.merged`, `bead.closed`, `pane.reaped`.
- [ ] Verifier drives one bead with the real reviewer on the stub worker's trivial diff per `features/review.md` and shows the `review.started` line naming the model, the review text written to `<factory>/reviews/<n>-<sha>.md`, and the `review.verdict` line at the pull request head with a non-empty `detail`.
- [ ] Verifier drives the human gate per `features/gate.md` and shows `gate` reporting the mode it set, the `review.verdict` `APPROVE` line, the pull request in `prs` carrying the label `smile:approved` and still open with no `pr.merged` event, then after a human `gh pr merge` and one more `tick`, the `pr.merged` line with `actor` `human`, the `bead.closed` line, and the bead closed in the bd listing.

**Review gate.** None. S4 is not review-gated.

**Merge.**

- [ ] Cold review has no open Act On finding.
- [ ] Both bakeoff rows written. Appendix E recommendation written. Squash-merged, trail row written.
- [ ] David picks the runtime. The other runtime is deleted in a follow-up commit before S5.

## Build the watchtower (S5)

**Depends on.** S4 and the runtime decision.

**Files.**

- [ ] Create `templates/prompts/watchtower.md` and `templates/.claude/skills/watchtower/SKILL.md`, ported from `~/zasti/agent-skills/skills/watchtower/SKILL.md` with Discord and the Downloads notepad removed.
- [ ] Edit the driver to spawn the watchtower pane when `watchtower` is `on`.
- [ ] Create `tests/watchtower.test.sh`.

**Build.**

- [ ] The watchtower pane runs claude with the watchtower skill, tails `events.jsonl`, and writes its report to `.factory/watch.md`.
- [ ] It appends `watch.escalation` events with a reason and may create `.factory/pause`. It never edits code, bd, or GitHub.
- [ ] `smile pause` and `smile resume` log `driver.paused` and `driver.resumed`; the driver itself logs nothing about pausing and only skips claims while the file exists.

**You see.**

- [ ] With `watchtower` on, `tmux list-windows` shows a `watchtower` window and `.factory/watch.md` grows during a loop.

**Verify, unit.** Tests alone are not sufficient verification. A spike is verified only when its unit and live boxes are all checked.

- [ ] `tests/watchtower.test.sh` covers pause and resume events and the spawn flag. Run `bash tests/watchtower.test.sh`.

**Verify, live.** Tests alone are not sufficient verification. A live box is checked by a fresh verifier agent that drives the fixture with the verify-smile primitives per the feature map page the box names, and pastes the evidence. A script printing `PASS` is not evidence.

- [ ] Verifier drives escalation per `features/watchtower.md` with the stub worker set to crash twice on bead B, and shows `panes` listing a `watchtower` window in the fixture session; `.factory/watch.md` non-empty and growing across ticks; the two `worker.crashed` lines for bead B with `detail` `attempt 1` then `escalated`, and its run file moved to `runs/crashed/`; the `watch.escalation` line naming bead B with its reason in `detail`; the pause file present; and the `driver.paused` line, after which a `tick` claims no new bead, with `runs` unchanged, until `resume`.

**Review gate.** None. S5 is not review-gated.

**Merge.**

- [ ] Cold review has no open Act On finding.
- [ ] Squash-merged, trail row written.

## Build planner narration (S6)

**Depends on.** S4 and the runtime decision.

**Files.**

- [ ] Create `templates/.claude/skills/campaign/SKILL.md`, ported from `~/zasti/agent-skills/skills/campaign/SKILL.md`.
- [ ] Create the `narrate` module under `templates/smile/py/`, a helper that prints new events since a cursor in one line each.

**Build.**

- [ ] The campaign skill ends by starting `smile run` as a background process and instructs the session to call `smile narrate` on each wake and relay new lines to the user. Escalations are relayed first.
- [ ] `smile narrate` keeps its cursor in `.factory/narrate.cursor` so any later session resumes narration.

**You see.**

- [ ] `smile narrate` prints only lines newer than the last call. A second call with no new events prints nothing.

**Verify, unit.** Tests alone are not sufficient verification. A spike is verified only when its unit and live boxes are all checked.

- [ ] `tests/narrate.test.sh` covers cursor persistence and escalation-first ordering. Run `bash tests/narrate.test.sh`.

**Verify, live.** Tests alone are not sufficient verification. A live box is checked by a fresh verifier agent that drives the fixture with the verify-smile primitives per the feature map page the box names, and pastes the evidence. A script printing `PASS` is not evidence.

- [ ] Verifier drives narration per `features/narrate.md` across a loop and shows the three `smile narrate` outputs side by side with the `events` lines they cover and the `.factory/narrate.cursor` value after each call. The three outputs concatenated equal the event log rendered exactly once, in order, with no line repeated and none missing, a call made with no new events prints nothing and leaves the cursor unchanged, and an escalation line appears before the other lines of the same call.

**Review gate.** None. S6 is not review-gated.

**Merge.**

- [ ] Cold review has no open Act On finding.
- [ ] Squash-merged, trail row written.

## Port and upgrade the skills (S7)

**Depends on.** S4 and the runtime decision.

**Files.**

- [ ] Create `templates/.claude/skills/smile-code-writer/SKILL.md` with the three pillars from `~/zasti/agent-skills/skills/code-writer/SKILL.md`, a worker process section adapted from `.claude/skills/poteto-mode/playbooks/feature.md`, and references `laziness-protocol.md` and `test-behavior.md` copied from the pstack principles. No Makefile rule.
- [ ] Edit `templates/.claude/skills/smile-code-reviewer/SKILL.md`. Keep the Execution section and closure rules. Replace the five dimensions with `.claude/skills/interrogate/references/rubric.md` and `code-quality-review.md`. Add `lead-judgment.md` as the step before the verdict. Remove the praise rule.
- [ ] Create `templates/.claude/skills/architect/SKILL.md` from `.claude/skills/architect/` with the arena and Cursor model references replaced by a single-session sketch of at least two candidates.
- [ ] Create `templates/.claude/skills/preflight/SKILL.md`, `draftspec`, `grilling`, and `test-writer` from the local copies with Downloads paths and David-specific wording removed.
- [ ] Edit `templates/prompts/worker.md` and `templates/prompts/reviewer.md` to require a `Principles applied` line naming each principle by name.

**Build.**

- [ ] Every ported skill has frontmatter with `name` and `description` and no reference to Cursor, Discord, cmux, or a home-directory path.

**You see.**

- [ ] `grep -rl "cursor\|discord\|Downloads\|openclaw" templates/.claude/skills` prints nothing.

**Verify, unit.** Tests alone are not sufficient verification. A spike is verified only when its unit and live boxes are all checked.

- [ ] `tests/skills.test.sh` checks frontmatter presence and the forbidden-word grep. Run `bash tests/skills.test.sh`.

**Verify, live.** Tests alone are not sufficient verification. A live box is checked by a fresh verifier agent that drives the fixture with the verify-smile primitives per the feature map page the box names, and pastes the evidence. A script printing `PASS` is not evidence.

- [ ] Verifier drives the real reviewer on the upgraded rubric per `features/review.md` and shows the rendered `prompts/reviewer.md` reaching the reviewer, the review text at `<factory>/reviews/<n>-<sha>.md` containing a `Principles applied` line that names each principle, the verdict line in the contract's exact grammar, and the `review.verdict` event at the pull request head carrying that verdict in `detail`.

**Review gate.** None. S7 is not review-gated.

**Merge.**

- [ ] Cold review has no open Act On finding.
- [ ] Squash-merged, trail row written.

## Build the cmux and Herdr backends (S8)

**Depends on.** S5.

**Files.**

- [ ] Create `backends/cmux.py` and `backends/herdr.py`.
- [ ] Extend `tests/test_mux.py` with a backend matrix that skips absent backends and prints `skipped <backend>` rather than passing silently.

**Build.**

- [ ] The cmux backend spawns a pane in a workspace named after the repo, passing `--workspace` on close as the 2026-07-20 finding requires.
- [ ] The Herdr backend spawns a tab through the Herdr CLI. The writer prototypes the exact commands first and records them in Appendix A.

**You see.**

- [ ] With `backend` set to `cmux`, `smile mux spawn` opens a pane visible in cmux. Same for `herdr`.

**Verify, unit.** Tests alone are not sufficient verification. A spike is verified only when its unit and live boxes are all checked.

- [ ] `bash tests/mux-py.test.sh` on this machine runs all three backends.

**Verify, live.** Tests alone are not sufficient verification. A live box is checked by a fresh verifier agent that drives the fixture with the verify-smile primitives per the feature map page the box names, and pastes the evidence. A script printing `PASS` is not evidence.

- [ ] Verifier drives the loop once per backend per `features/mux.md` and `features/loop.md`, with `backend` set to `cmux` and then to `herdr`, and shows for each the doctor mux line naming that backend, the handles in `cmux:` and `herdr:` form, the pane counts from `panes` before and after spawn and after kill, and the per-bead event sequence of the contract's section 8 ending in `campaign.complete`, identical across the two backends and to the tmux run. David watches the Herdr run.

**Review gate.** David reviews the Herdr run in chat before merge.

- [ ] Copy the Herdr and cmux transcripts to `~/.smile-verify/<runid>/` and post the paths in chat as the screenshot and video equivalents. The operator confirms the panes appeared.

**Merge.**

- [ ] Cold review has no open Act On finding.
- [ ] Squash-merged, trail row written.

## Dogfood and document (S9)

**Depends on.** S6, S7, S8.

**Files.**

- [ ] Rewrite `README.md` as the install how-to.
- [ ] Create `docs/HOW-IT-WORKS.md` as the explanation.

**Build.**

- [ ] Run a real two-bead campaign on a fresh fixture repo with real workers on the configured model and the real reviewer. Beads are small. One adds a CLI flag, the other adds a test for it.
- [ ] Run `/maintain-verification-skill` against `verify-smile` and land its corrections.

**You see.**

- [ ] Two merged pull requests written by real workers, both beads closed, a watchtower report, and a narration transcript.

**Verify, unit.** Tests alone are not sufficient verification. A spike is verified only when its unit and live boxes are all checked.

- [ ] Every `tests/*.test.sh` green on main. Run `bash tests/all.sh`.

**Verify, live.** Tests alone are not sufficient verification. A live box is checked by a fresh verifier agent that drives the fixture with the verify-smile primitives per the feature map page the box names, and pastes the evidence. A script printing `PASS` is not evidence.

- [ ] Verifier drives the dogfood campaign per `features/loop.md` and `features/review.md` with real workers and the real reviewer, and shows the full per-bead sequence from `events` for both beads in the contract's section 9 order ending in `campaign.complete`; `prs` showing both pull requests merged with `actor` `driver` on each `pr.merged`; both beads closed in the bd listing; every run file in `runs/done/`; `panes` back to no worker windows; and `smile audit` printing nothing, which is the claim that no pull request merged without a verdict at its merge SHA.

**Review gate.** David reviews the dogfood in chat before the repo goes public.

- [ ] Post the two pull request links, the watchtower report path, and the narration transcript path. The operator reads them and says go.

**Merge.**

- [ ] Squash-merged, trail row written.
- [ ] Repo visibility flipped to public.

## Close the program

- [ ] Every box above is checked with its evidence.
- [ ] `docs/decisions.tsv` audited against the transcript and cross-reviewed by a non-fork subagent.
- [ ] Reply to David with the spike table, the bakeoff result, the dogfood links, and open risks.

## Appendix A. Prototype evidence

Open questions each fork settles by running something before building on it. Answers land here with the commit that recorded them.

- How to pre-trust a folder for a headless-launched claude so no trust prompt blocks a worker pane. Settled 2026-09-18. `~/.claude.json` holds `projects[<absolute path>].hasTrustDialogAccepted`. The driver sets it for each worktree path before spawning. The worker's permission mode is the config key `worker.permission_mode`, passed as `--permission-mode`.
- The exact Herdr CLI commands to open, probe, and close a tab. Settled from `herdr 0.8.0 --help`, live JSON shape pending S8. `herdr tab create --cwd <path> --label <name> --no-focus` returns JSON with `tab_id`, `herdr pane run <pane_id> <command>` starts the command, `herdr pane get <pane_id>` probes, `herdr tab close <tab_id>` closes.
- Whether `treehouse get` seeds `.worktreeinclude` files before the worker's first command. Open. The driver acquires with `treehouse get --lease --lease-holder <bead-id>`, which prints only the path, and releases with `treehouse return --force <path>`. Settled from `treehouse 2.0.1 --help`.
- Which interpreter the runtime runs on. Settled 2026-09-18, after the Python 3.9 floor (the macOS system interpreter) forced every py test wrapper to run its suite twice, once on the ambient python and once on the floor. SMILE follows super-simple-software-factory's shape instead. Every entry-point script carries PEP 723 inline script metadata (`requires-python = ">=3.12"`, `dependencies = []`) and runs through `uv run`, so uv chooses and fetches the interpreter. The cost is one new prerequisite, `uv`, which `smile doctor` checks first. The benefit is one interpreter everywhere and one test pass per suite. This docs change lands before the code change; a code PR implements it against this wording.
- Whether `gh pr merge --squash` on a private repo from a script needs a `--admin` flag when no branch protection exists. Open.
- Whether the driver's per-tick pull request scan through `gh pr list --json` stays under the GitHub secondary rate limit at a 60 second interval with 8 open pull requests. Open.

## Appendix B. Alternatives rejected

- A git pre-push review hook. The old factory used one. Hooks run inside the worker's worktree, inherit git's hook environment, and broke `git worktree add` once. The driver already polls, so it scans pull requests instead.
- One global install with a per-repo init, the firstmate shape. David chose per-repo stamping so users can edit their copy.
- Only bash or only Python. David chose to build both and measure.
- Discord for progress. Requires an account users may not have. The planner session narrates the event log instead.
- Orchestrator agent as the driver. Replaced by a script so sequencing costs no tokens and behaves the same every run.

## Appendix C. Risks

- Treehouse pooling and worktree hooks are untested together. Lands in S3. The writer watches for a stale pool entry keeping a worker's branch checked out.
- Herdr tab control is known only from its README. Lands in S8. The writer prototypes first.
- The real reviewer on a trivial diff may still take minutes. Lands in S4. The stub reviewer keeps the loop fast and the real one runs in a single lane.
- Two runtimes double the writer cost through S4. Accepted by David for the bakeoff.
- GitHub repo creation and deletion in David's account per verify run. Names carry the `smile-verify-` prefix and the cleanup asserts deletion.

## Appendix D. Links and reading list

- The old factory scripts for reference. `~/zasti/agent-skills/scripts/bead-driver`, `review`, `gate`, `review-audit`.
- pstack playbooks and principles under `.claude/skills/`. Every fork reads `principle-prove-it-works`, `principle-sequence-verifiable-units`, `principle-laziness-protocol`, and `principle-model-the-domain` before writing.
- Treehouse. https://github.com/kunchenguid/treehouse
- SSSF, the shape this installer copies. https://github.com/disler/super-simple-software-factory
- Firstmate backend routing, for the cmux and Herdr adapters. https://github.com/kunchenguid/firstmate

## Appendix E. Bakeoff recommendation

Decided 2026-09-18, early, to stop paying for two runtimes through the rest of S3. Through S2 the two runtimes were behaviourally indistinguishable, with byte-identical stdout and exit codes on every box the harness drove. Python was shorter by lines and carried one more file, and slower per call, roughly 80 ms against bash's 40 ms, which is noise next to a tick interval measured in seconds. Python drew fewer review findings per round, which is the axis that decides who can maintain this, so David chose Python and the bash runtime was removed in the PR that added this appendix. `docs/bakeoff.tsv` keeps the per-spike rows.
