# SMILE software factory build plan

SMILE turns a spec into merged, reviewed code with agents in visible panes and a deterministic script driving them. This document freezes the design agreed on 2026-09-18 and lays out the spikes that build it. Two runtimes, bash and Python, are built side by side through spike 4 and measured. One survives. Spikes run in this order. S0 verification harness, S1 core, S2 mux seam, S3 driver, S4 review, S5 watchtower, S6 narration, S7 skills, S8 backends, S9 dogfood.

## How to read this

One box is one unit of work. Every box names the evidence that checks it. A nested box is a sub-step of the box above it. Check a box only when its evidence exists, a file, a log line, a transcript, a test run, or a SHA. The body is a how-to. The appendices explain and record.

The program runs under the Orchestrate playbook in `.claude/skills/poteto-mode/playbooks/orchestrate.md`, adapted as the Program checklist below says. The orchestrator merges. David approves this document once and reviews the dogfood in S9.

Tests alone are not sufficient verification. A spike is verified only when its unit and live boxes are all checked.

## Design

This section is the frozen design. Every spike implements a part of it. A spike that finds the design wrong stops and reports rather than quietly diverging.

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

`smile doctor` refuses to run with a named reason when any of these is missing. git, gh with a logged-in account, claude, bd, treehouse, and at least one of tmux, cmux, or herdr.

### What the installer stamps

`install.py` in the skill repo copies these into the target repo. A force flag replaces stamped files that drifted.

- `smile/smile`, the entry script. It reads `runtime` from the config and dispatches to `smile/bash/` or `smile/py/`.
- `smile/bash/` and `smile/py/`, the two runtimes. Each exposes the same commands. `doctor`, `init`, `run`, `review`, `gate`, `audit`, `pause`, `resume`, `status`, and `mux`.
- `.claude/skills/` with campaign, preflight, watchtower, smile-code-writer, smile-code-reviewer, test-writer, draftspec, grilling, and architect.
- `smile.config.yaml` with the keys `runtime`, `backend`, `worker.model`, `worker.permission_mode`, `reviewer.models`, `max_parallel`, `watchtower`, `merge`, and `base_branch`.
- `prompts/worker.md`, `prompts/reviewer.md`, and `prompts/watchtower.md`.
- A `.gitignore` line for `.factory/`.

`smile init` runs once per repo. It runs `bd init`, writes the treehouse config and `.worktreeinclude`, and creates `.factory/`.

### The bakeoff

Both runtimes implement the same command set and emit the same events, so the verification harness drives either one through the `runtime` key. `docs/bakeoff.tsv` records one row per spike per runtime with these columns, measured by the orchestrator after both pull requests merge. `spike`, `runtime`, `verify_result`, `verify_seconds`, `lines`, `files`, `reader_load`, and `notes`. `reader_load` is the cold reviewer's score from 1 to 5 on the two axes in the minimize-reader-load principle, layers to trace and state to hold, averaged. After S4 the orchestrator writes a recommendation in Appendix E and David picks the runtime. The other runtime is deleted before S5 begins.

### Cuts

Not built. Discord and the OpenClaw gateway, remote workers through crabbox and E2B, pane nudges, push-to-main review, git hooks, and state under the home directory.

## Program checklist

### Arm the program

- [ ] Post this plan to David and continue with S0, which no design detail can invalidate. Fold his corrections into a revision before S1 starts.
- [ ] Keep the trail in `docs/decisions.tsv` through `.claude/skills/show-me-your-work/scripts/log.sh`. One row per spike verdict, pivot, or gate.
- [ ] Standing orders for every writer, pasted verbatim into every brief. Read `docs/SPEC.md` first. Write only inside the paths the brief names. Never merge. Never edit `docs/SPEC.md`. Run the named verify command and paste its output. Report deviations from the design as findings, not as silent fixes. Cite by name each pstack principle that shaped a choice. If a tool call is denied by the permission system, stop, do not work around it with another tool, and report the denial.
- [ ] Post a status line to David at each spike merge. Spike, runtime, verdict, PR link.

### Spawn owners

- [ ] One fresh agent per spike per runtime, at high effort, with a self-contained brief: the spike section, the contracts it must honor, the standing orders, conventions, file pointers, and the branch name. No inherited chat. David's call after S0: a good brief beats a fork.
- [ ] Runtime spikes S1 to S4 spawn a bash writer and a Python writer in parallel from the same brief, per the arena skill. Shared runtime-neutral pieces (installer, shim, config format, `docs/RUNTIME-CONTRACT.md`) were written once first, in S1, so the two runtimes implement one contract.
- [ ] S0, S5 to S9 spawn one writer each. S5 and later target the runtime David picked.
- [ ] Each writer works on its own branch in an isolated git worktree of this repo. Branch names are `spike/<id>-<runtime>` or `spike/<id>`.
- [ ] Dependencies. S1 after S0. S2 after S1. S3 after S2. S4 after S3. S5, S6, and S7 after S4 and the bakeoff decision, in parallel. S8 after S5. S9 after S6, S7, and S8.

### PR mechanics, for every spike

- [ ] The writer commits through `~/.claude/skills/git-ops/scripts/commit.sh` with a conventional message and pushes through `push.sh`.
- [ ] The writer opens the pull request with `gh pr create`. The body names what it built, the verify command and its output, deviations, and the principles it cited.
- [ ] A fresh non-fork subagent reviews the pull request cold with `.claude/skills/interrogate/references/rubric.md` and `code-quality-review.md`, then the orchestrator applies `lead-judgment.md`. Findings with the category Act On go back to the writer as a follow-up commit.
- [ ] The orchestrator reads the diff and the verify evidence itself before merging. A writer's summary is not evidence.

### Verdict and merge, for every spike

- [ ] Verify, unit and Verify, live boxes checked with pasted output.
- [ ] No open Act On finding.
- [ ] The orchestrator squash-merges through `gh pr merge --squash --delete-branch` and logs a trail row with the merge SHA and the verdict.
- [ ] For S1 to S4 the orchestrator also writes both bakeoff rows.

### Boot recipe, for every live verify

- [ ] `verify-smile` from S0 creates a private repo `smile-verify-<runid>` under David's GitHub account, clones it to a temp directory, stamps SMILE from the branch under test, runs `smile init`, seeds a two-bead graph where bead B depends on bead A, and starts the driver with the stub worker.
- [ ] Panes open in a tmux session named `smile-verify-<runid>`.
- [ ] Evidence is copied to `~/.smile-verify/<runid>/` before cleanup. `events.jsonl`, the pull request list as JSON, the bd list, and the driver log.
- [ ] Cleanup kills that tmux session, deletes the repo through `gh repo delete --yes`, and removes the temp directory. Evidence survives.

## Build the verification harness (S0)

**Depends on.** None.

**Files.**

- [ ] Create `.claude/skills/verify-smile/SKILL.md`.
- [ ] Create `.claude/skills/verify-smile/features/README.md` and one file per feature. `install.md`, `doctor.md`, `loop.md`, `review.md`, `gate.md`, `watchtower.md`.
- [ ] Create `.claude/skills/verify-smile/scripts/verify-smile`, the helper.
- [ ] Create `.claude/skills/verify-smile/scripts/stub-worker`, a script that behaves as a worker. It writes one file, commits on `smile/<bead-id>`, opens a pull request with the bead trailer, and exits. On a rerun where the pull request exists, it appends a line, commits with `addresses #<issue>` for each open `review` issue naming that pull request, pushes, and exits.
- [ ] Create `.claude/skills/verify-smile/scripts/stub-reviewer`, a script that answers `APPROVE` for any diff. The `--real-review` flag of the helper uses the real reviewer instead.

**Build.**

- [ ] `verify-smile up` creates the fixture per the boot recipe and prints the run id and paths.
- [ ] `verify-smile feature <name> --runtime <bash|py> [--real-review]` drives one mapped feature and asserts its end state.
- [ ] `verify-smile down <runid>` runs cleanup and confirms the evidence directory still exists.
- [ ] Assertions read `events.jsonl`, `gh pr list --json`, and `bd list --json`. Never the driver's own summary.

**You see.**

- [ ] `verify-smile up` prints `fixture ready <runid> <path>` and `gh repo view smile-verify-<runid>` succeeds.
- [ ] `verify-smile down <runid>` prints `evidence kept at ~/.smile-verify/<runid>` and `gh repo view` fails with not found.

**Verify, unit.** Tests alone are not sufficient verification. A spike is verified only when its unit and live boxes are all checked.

- [ ] `tests/verify-smile.test.sh` runs `up`, asserts the fixture layout, runs `down`, asserts the repo is gone and the evidence remains. Run `bash tests/verify-smile.test.sh`.

**Verify, live.** Tests alone are not sufficient verification. A spike is verified only when its unit and live boxes are all checked.

- [ ] Run the generated skill's own instructions once end to end. Launch, doctor, drive the `install` feature against an empty stamp, capture evidence, clean up. Pass when the evidence directory lists `beads.json` and `prs.json` after cleanup and `beads.json` names both seeded beads. `events.jsonl` first exists after S1.

**Review gate.** None. S0 is not review-gated.

**Merge.**

- [ ] Cold review has no open Act On finding.
- [ ] Squash-merged, trail row written.

## Build the core: log, config, doctor, init, installer (S1)

**Depends on.** S0.

**Files.**

- [ ] Create `templates/smile/smile`.
- [ ] Create `templates/smile/bash/` with `doctor`, `init`, `status`, `pause`, `resume`, and `lib/events`, `lib/config`. Python fork creates `templates/smile/py/smile.py` and the `smile/py/` package with the same commands.
- [ ] Create `templates/smile.config.yaml`, `templates/prompts/`, and `templates/.claude/skills/` placeholders.
- [ ] Create `install.py` at the repo root and `.claude/skills/smile/SKILL.md`, the skill that runs it.
- [ ] Create `tests/core.test.sh` and `tests/test_core.py`.

**Build.**

- [ ] `install.py <repo> [--force]` stamps the files listed in Design and refuses to overwrite a drifted file without the flag.
- [ ] `smile doctor` checks each prerequisite and prints one line per check with `ok` or `missing <reason>`. Exit 1 on any missing.
- [ ] `smile init` runs `bd init`, writes the treehouse config, writes `.worktreeinclude`, creates `.factory/`, and appends a `campaign.start` placeholder only when asked.
- [ ] `lib/events` appends one JSON line with the schema in Design. Concurrent writers append whole lines.
- [ ] `lib/config` reads `smile.config.yaml` and prints one key. Missing keys fall back to defaults named in the template.
- [ ] `smile pause` creates `.factory/pause`. `smile resume` removes it. `smile status` prints bead counts, open pull requests, and the last ten events.

**You see.**

- [ ] `python3 install.py /tmp/x` prints one line per stamped file. A second run prints `unchanged` per file. Editing a stamped file and re-running prints `drifted, use --force`.
- [ ] `smile doctor` in a repo with everything installed prints all `ok` and exits 0.

**Verify, unit.** Tests alone are not sufficient verification. A spike is verified only when its unit and live boxes are all checked.

- [ ] `tests/core.test.sh` covers install, drift refusal, force, doctor with a missing tool on PATH, events schema, config defaults, pause and resume. Run `bash tests/core.test.sh`. Python fork runs `python3 -m pytest tests/test_core.py`.

**Verify, live.** Tests alone are not sufficient verification. A spike is verified only when its unit and live boxes are all checked.

- [ ] `verify-smile feature install --runtime <r>` and `verify-smile feature doctor --runtime <r>`. Pass when both print `PASS` and the evidence directory has the doctor transcript.

**Review gate.** None. S1 is not review-gated.

**Merge.**

- [ ] Cold review has no open Act On finding.
- [ ] Both bakeoff rows written. Squash-merged, trail row written.

## Build the mux seam with the tmux backend (S2)

**Depends on.** S1.

**Files.**

- [ ] Create `templates/smile/bash/mux` and `templates/smile/bash/mux.d/tmux`. Python fork creates the `mux` module and `backends/tmux.py`.
- [ ] Create `tests/mux.test.sh` and `tests/test_mux.py`.

**Build.**

- [ ] `smile mux spawn <name> <cwd> <command>` opens a tmux window in the session named by config or `smile-<repo>`, runs the command in `<cwd>`, and prints the handle `tmux:<session>:<window-id>`.
- [ ] `smile mux alive <handle>` exits 0 while the window exists and its pane's process is running.
- [ ] `smile mux kill <handle>` kills the window and exits 0 even when it is already gone.
- [ ] The backend file is selected from `backend` in config, or from the doctor's auto-detect order.
- [ ] Workers launch with the target folder pre-trusted so no trust prompt appears. The fork finds the setting that does this and records it in Appendix A.

**You see.**

- [ ] `smile mux spawn t /tmp 'sleep 30'` prints a handle, `tmux list-windows -t smile-<repo>` shows `t`, `alive` exits 0, `kill` removes it, `alive` exits 1.

**Verify, unit.** Tests alone are not sufficient verification. A spike is verified only when its unit and live boxes are all checked.

- [ ] `tests/mux.test.sh` covers spawn, alive on a running and an exited command, kill, double kill, and a missing backend name. Run `bash tests/mux.test.sh`. Python fork runs `python3 -m pytest tests/test_mux.py`.

**Verify, live.** Tests alone are not sufficient verification. A spike is verified only when its unit and live boxes are all checked.

- [ ] `verify-smile feature mux --runtime <r>` spawns three panes in the fixture session, asserts three windows, kills them, asserts zero. Pass when it prints `PASS`.

**Review gate.** None. S2 is not review-gated.

**Merge.**

- [ ] Cold review has no open Act On finding.
- [ ] Both bakeoff rows written. Squash-merged, trail row written.

## Build the driver (S3)

**Depends on.** S2.

**Files.**

- [ ] Create `templates/smile/bash/run` and `templates/smile/bash/lib/worktree`. Python fork creates `run.py` and `worktree.py`.
- [ ] Create `templates/prompts/worker.md`.
- [ ] Create `tests/driver.test.sh` and `tests/test_driver.py`.

**Build.**

- [ ] `smile run [--once] [--interval N]` holds a singleton pidfile per repo and refuses a second instance.
- [ ] Each tick, when `.factory/pause` is absent, the driver lists ready beads through `bd ready --json`, claims up to `max_parallel` minus running, acquires a worktree per claim through `treehouse get`, writes the work order from `prompts/worker.md` and the bead, spawns the worker through `smile mux spawn`, and logs `bead.claimed`, `worktree.acquired`, and `pane.spawned`.
- [ ] Each tick the driver reaps panes whose bead is closed, returns their worktree through `treehouse return`, and logs `pane.reaped`.
- [ ] A pane that dies with its bead still open is logged `worker.crashed`. The bead is respawned once. A second crash leaves the bead claimed and logs an escalation.
- [ ] The worker command is `claude --model <worker.model> --permission-mode <worker.permission_mode> "<work order>"` by default and `SMILE_WORKER_CMD` when set, which the harness uses for the stub. Before spawning, the driver marks the worktree path trusted in `~/.claude.json`.
- [ ] The driver exits with `campaign.complete` when no bead is open.

**You see.**

- [ ] With two beads seeded and the stub worker, `smile run --once` logs two claims, two spawns, and two pull requests appear in `gh pr list`.

**Verify, unit.** Tests alone are not sufficient verification. A spike is verified only when its unit and live boxes are all checked.

- [ ] `tests/driver.test.sh` covers singleton refusal, pause skips claims, max_parallel cap, crash respawn once, and event order. bd and treehouse are real. The mux backend is a fake that records calls. Run `bash tests/driver.test.sh`. Python fork runs `python3 -m pytest tests/test_driver.py`.

**Verify, live.** Tests alone are not sufficient verification. A spike is verified only when its unit and live boxes are all checked.

- [ ] `verify-smile feature loop --runtime <r>` runs the driver against the fixture with the stub worker and the stub reviewer until `campaign.complete` or a 10 minute timeout. Pass when both beads are closed, both pull requests are merged, and the event sequence per bead is claimed, worktree, spawned, pr.opened, review.started, review.verdict, pr.merged, bead.closed, pane.reaped.

**Review gate.** None. S3 is not review-gated.

**Merge.**

- [ ] Cold review has no open Act On finding.
- [ ] Both bakeoff rows written. Squash-merged, trail row written.

## Build the review lane (S4)

**Depends on.** S3.

**Files.**

- [ ] Create `templates/smile/bash/review`, `templates/smile/bash/gate`, and `templates/smile/bash/audit`. Python fork creates the matching modules.
- [ ] Create `templates/prompts/reviewer.md` and `templates/.claude/skills/smile-code-reviewer/SKILL.md` as a first version with the current reviewer execution rules. S7 upgrades the rubric.
- [ ] Create `tests/review.test.sh` and `tests/test_review.py`.

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

- [ ] `tests/review.test.sh` covers verdict parsing, the no-verdict-at-head filter, issue creation from findings, the human gate matrix, and audit. GitHub calls go through a recorded fake of `gh`. Run `bash tests/review.test.sh`. Python fork runs `python3 -m pytest tests/test_review.py`.

**Verify, live.** Tests alone are not sufficient verification. A spike is verified only when its unit and live boxes are all checked.

- [ ] `verify-smile feature review --runtime <r>` runs the changes-then-approve path with the stub reviewer. Pass when the issue is opened and closed and the pull request merges.
- [ ] `verify-smile feature review --runtime <r> --real-review` runs one bead with the real reviewer on the stub worker's trivial diff. Pass when a verdict event exists with a non-empty `detail`.
- [ ] `verify-smile feature gate --runtime <r>`. Pass when the pull request carries `smile:approved` and stays open, and a manual `gh pr merge` closes the bead on the next tick.

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
- [ ] The driver logs `driver.paused` on the first tick it sees the pause file and `driver.resumed` when it is gone.

**You see.**

- [ ] With `watchtower` on, `tmux list-windows` shows a `watchtower` window and `.factory/watch.md` grows during a loop.

**Verify, unit.** Tests alone are not sufficient verification. A spike is verified only when its unit and live boxes are all checked.

- [ ] `tests/watchtower.test.sh` covers pause and resume events and the spawn flag. Run `bash tests/watchtower.test.sh`.

**Verify, live.** Tests alone are not sufficient verification. A spike is verified only when its unit and live boxes are all checked.

- [ ] `verify-smile feature watchtower` runs a loop with a stub worker that crashes twice on bead B. Pass when a `watch.escalation` event names bead B and the driver logs `driver.paused` after the watchtower touches the pause file.

**Review gate.** None. S5 is not review-gated.

**Merge.**

- [ ] Cold review has no open Act On finding.
- [ ] Squash-merged, trail row written.

## Build planner narration (S6)

**Depends on.** S4 and the runtime decision.

**Files.**

- [ ] Create `templates/.claude/skills/campaign/SKILL.md`, ported from `~/zasti/agent-skills/skills/campaign/SKILL.md`.
- [ ] Create `templates/smile/bash/narrate` or the Python equivalent, a helper that prints new events since a cursor in one line each.

**Build.**

- [ ] The campaign skill ends by starting `smile run` as a background process and instructs the session to call `smile narrate` on each wake and relay new lines to the user. Escalations are relayed first.
- [ ] `smile narrate` keeps its cursor in `.factory/narrate.cursor` so any later session resumes narration.

**You see.**

- [ ] `smile narrate` prints only lines newer than the last call. A second call with no new events prints nothing.

**Verify, unit.** Tests alone are not sufficient verification. A spike is verified only when its unit and live boxes are all checked.

- [ ] `tests/narrate.test.sh` covers cursor persistence and escalation-first ordering. Run `bash tests/narrate.test.sh`.

**Verify, live.** Tests alone are not sufficient verification. A spike is verified only when its unit and live boxes are all checked.

- [ ] `verify-smile feature narrate` runs a loop and calls `smile narrate` three times. Pass when the concatenated output equals the event log rendered once with no duplicates.

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

**Verify, live.** Tests alone are not sufficient verification. A spike is verified only when its unit and live boxes are all checked.

- [ ] `verify-smile feature review --real-review` again on the upgraded reviewer. Pass when the verdict detail contains a `Principles applied` line.

**Review gate.** None. S7 is not review-gated.

**Merge.**

- [ ] Cold review has no open Act On finding.
- [ ] Squash-merged, trail row written.

## Build the cmux and Herdr backends (S8)

**Depends on.** S5.

**Files.**

- [ ] Create `mux.d/cmux` and `mux.d/herdr` or the Python equivalents.
- [ ] Extend `tests/mux.test.sh` with a backend matrix that skips absent backends and prints `skipped <backend>` rather than passing silently.

**Build.**

- [ ] The cmux backend spawns a pane in a workspace named after the repo, passing `--workspace` on close as the 2026-07-20 finding requires.
- [ ] The Herdr backend spawns a tab through the Herdr CLI. The fork prototypes the exact commands first and records them in Appendix A.

**You see.**

- [ ] With `backend` set to `cmux`, `smile mux spawn` opens a pane visible in cmux. Same for `herdr`.

**Verify, unit.** Tests alone are not sufficient verification. A spike is verified only when its unit and live boxes are all checked.

- [ ] `bash tests/mux.test.sh` on this machine runs all three backends.

**Verify, live.** Tests alone are not sufficient verification. A spike is verified only when its unit and live boxes are all checked.

- [ ] `verify-smile feature loop --backend cmux` and `--backend herdr`. Pass when both reach `campaign.complete`. David watches the Herdr run.

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

**Verify, live.** Tests alone are not sufficient verification. A spike is verified only when its unit and live boxes are all checked.

- [ ] The dogfood campaign reaches `campaign.complete`. Pass when both pull requests were merged by the driver and `smile audit` prints nothing.

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
- Whether `gh pr merge --squash` on a private repo from a script needs a `--admin` flag when no branch protection exists. Open.
- Whether the driver's per-tick pull request scan through `gh pr list --json` stays under the GitHub secondary rate limit at a 60 second interval with 8 open pull requests. Open.

## Appendix B. Alternatives rejected

- A git pre-push review hook. The old factory used one. Hooks run inside the worker's worktree, inherit git's hook environment, and broke `git worktree add` once. The driver already polls, so it scans pull requests instead.
- One global install with a per-repo init, the firstmate shape. David chose per-repo stamping so users can edit their copy.
- Only bash or only Python. David chose to build both and measure.
- Discord for progress. Requires an account users may not have. The planner session narrates the event log instead.
- Orchestrator agent as the driver. Replaced by a script so sequencing costs no tokens and behaves the same every run.

## Appendix C. Risks

- Treehouse pooling and worktree hooks are untested together. Lands in S3. The fork watches for a stale pool entry keeping a worker's branch checked out.
- Herdr tab control is known only from its README. Lands in S8. The fork prototypes first.
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

Written after S4. Open.
