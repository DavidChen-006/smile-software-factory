---
name: smile-campaign
description: >-
  Trigger when the user runs `/smile-campaign` or asks to execute a spec/plan with the
  SMILE factory ("run this as a campaign", "execute this spec with the fleet",
  "send the agents at this"). Plans a bead graph FROM a frozen spec, gates the
  graph past the user, creates the beads, starts `smile run` in the background,
  and narrates the campaign with `smile narrate` on every wake.
---

# /smile-campaign — execute a frozen spec with the SMILE factory

Turn a frozen spec into a reviewable bead graph, get it approved, create the
beads, start the driver. The factory does the work: `smile run` claims one
ready bead per tick, spawns one worker per pane, and the review lane closes
beads. This skill is the ignition and the narrator, not the engine.

Division of labor (structural, do not blur):
- **This session (planner)**: judgment — read the spec, design the graph, and
  relay what `smile narrate` prints.
- **`smile run`**: transport — claim, spawn, reap, reconcile.
- **the review lane**: closure — a verified APPROVE merges the PR and closes
  the bead.

For graph-walk mechanics (backward walk from the goal, dependency direction),
see the beads skill's planning notes — but its task-sizing doctrine does NOT
apply here. Campaign decomposition has its own law, below.

## Step 1 — Preflight (refuse, don't work around)

All must hold before anything mutates. If one fails, tell the user what's
missing and stop — never `bd init` or stamp the runtime silently as a side
effect.

```bash
cd <repo>
ls docs/*DESIGN*.md docs/spec.md 2>/dev/null | head -1 | grep -q . || echo "NO FROZEN SPEC"   # or the spec path the user names
git log --oneline -1 -- docs/                        # spec must be COMMITTED
smile/smile doctor                                   # every line must read `ok`
test -d .beads || echo "smile init needed"
gh repo view >/dev/null || echo "no GitHub remote (the review lane needs gh)"
```

Also warn if a live agent (a pane or interactive session) is currently editing
this checkout: it must be parked for the campaign — same-worktree agents
cross-contaminate commits.

**No spec, no campaign.** If the user has only a goal in their head, the spec
gets frozen first (their design session writes `docs/<X>-DESIGN.md` with
acceptance criteria, committed `wip:`). A campaign without acceptance criteria
gives the reviewer nothing to verify against.

## Step 2 — Propose the graph, then STOP

Read the spec. Carve beads by this law:

**One bead per independently-verifiable gate — never per file, module, or
section header.** A bead is a done-claim the reviewer can verify alone. Ask of
every candidate split: could this pass its own review with its own commit,
with zero reference to the other half? If the spec defines one joint gate
(shared golden tests, a single-commit rule), that is ONE bead no matter how
many modules it contains. If two pieces have separate acceptance criteria and
could ship separately, they are two beads.

**Acceptance atomicity — every spec acceptance sentence has exactly one owner
bead.** A sentence naming two surfaces ("the eval runner AND local worker
runs") must not be split across beads: assign the whole sentence to one bead,
or amend the spec into two sentences first, then assign each. Before
proposing, write the owner bead next to every acceptance line; a line with
two owners or zero owners means the carve is wrong. A straddled sentence
becomes a contested finding at review time — the reviewer holds whichever
bead it is judging to the WHOLE sentence, the builder contests scope, and a
human has to arbitrate. Catch it here for the price of a sentence.

**Live-model gates sample by default.** Any acceptance gate that runs a
live model per case (evals, judged suites) must specify a seeded per-run
sample (SHA-derived seed, ~15-20 cases) with the full registry reserved for
explicit release gates. A fix-round loop that re-spends the full registry
per round is a spec bug — catch it at carve time.

Edges: `needs` mirrors verification order, not narrative order. Parallel roots
are allowed ONLY when the beads are file-disjoint — when in doubt, chain them.

**Human gates.** Ask alongside the graph: which beads (if any) need the
user's personal sign-off before they close? Default is fully autonomous.
When presenting, state the stall cost of any gated bead — everything
downstream of it waits for the human ruling, so gating a root parks the
whole campaign until they act. Mechanics on approval: `smile gate bead <id>
on` for specific beads, `smile gate all` for every bead, `smile gate none`
for explicit none; `smile gate status` prints where the gate stands and
`smile gate` flips it mid-campaign.

Present the proposal to the user: each bead with a one-line justification tied
to the spec's acceptance structure, plus the edges. **Do not run bd create
before explicit approval.** *(Exception: `dark` mode, below.)* The graph is a judgment artifact and the user
reviews it — this gate is the entire reason the skill exists. If the user
argues, the resolution may be upstream: amend the spec's acceptance criteria,
then re-derive the graph.

### `dark` mode — print the graph, skip the wait

When the user says `dark`, or the `/smile` router enters this skill in `dark`
mode, the approval wait is pre-approved: print the graph exactly as above, with
the same per-bead justifications and edges, then go straight to Step 3 without
asking. Nothing else changes. Step 1 still refuses without a frozen spec, the
carve law, the human-gate default, the work-order rules, ignition, and the
narration all stand. Dark pre-approves the graph, not an escalation: a parked
campaign still waits for the user's ruling.

## Step 3 — On approval: create the beads

Descriptions are work orders: goal, spec pointer, constraints, non-goals,
proof expected. Rules:

- **Plain text only — no `$`, backticks, or double quotes** in descriptions
  (the driver expands work orders through the shell).
- Every description's first line is the imperative: "Read docs/<spec-file> in
  full before writing any code." It then states the definition of done in
  terms of the spec's acceptance section.
- Include the standing constraints: one worktree per bead, commits carry the
  Bead trailer and a Spec trailer naming the spec file (Spec: docs/<spec-file>),
  the review lane owns closure.
- **Test-first where it earns its keep**: beads whose core is new logic or a
  bug fix get the description line "Build test-first: read the tdd skill
  before writing implementation code." Skip it for config, wiring, and docs
  beads — red-green there is ceremony, not verification.

```bash
bd create "<title>" -d "<work order>"          # capture each id
bd dep add <dependent-id> <blocker-id>         # edges from Step 2
bd ready --json                                # verify: exactly the roots are ready
```

## Step 4 — Ignition

Start the driver as a background process, from the main checkout, never from a
worktree:

```bash
cd <repo> && nohup smile/smile run > .factory/driver.log 2>&1 &
```

Record the pid it printed in this session: it is how the user stops the
campaign (`kill <pid>`), and `smile pause` is how they park it without
killing it.

## Step 5 — Narrate every wake

On every wake from here on, call:

```bash
smile/smile narrate
```

It prints the events appended since the last call, one line each, escalations
first. Relay **each printed line** to the user, in the order printed — the
escalation lines first, exactly as they came. Nothing printed means nothing
happened: say nothing. Never tail `.factory/events.jsonl` or
`.factory/driver.log` yourself; `smile narrate` is the only narration surface,
and it remembers its place in the event log so a later session resumes from
that offset.

An escalation line (`watch.escalation`, `driver.paused`, or `worker.crashed`
with detail `escalated`) means the campaign is parked and the user's ruling is
the next move: relay it and ask.

## Step 6 — This skill is done

Say so and stop. Supervision belongs to the driver's loop, verdicts to the
review lane, escalation to the watchtower, and the final anchor to the user
(run the spec's acceptance tests yourself before believing a completed
campaign). This skill owns nothing after the driver is up but the narration.
