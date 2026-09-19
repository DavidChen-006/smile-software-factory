# How it works

## Four lanes

A campaign is four kinds of process, and no others.

- **Planning.** A human session, or the campaign skill, turns a frozen spec into a bead graph and
  stops. Planning never writes code.
- **Work.** One agent per claimed bead, in its own worktree, in its own pane, with a work order
  rendered from the bead and the spec. It ends by pushing a branch and opening one pull request.
- **Review.** One agent per pull request head, reading the diff against the spec and answering in a
  fixed grammar: a verdict line, and one line per blocking finding.
- **Watch.** One long-lived observer per campaign. It reads and reports; it never edits code,
  beads or pull requests.

The lanes never call each other. They meet in the event log.

## The event log is the only shared truth

Every lane appends to `.factory/events.jsonl`, one JSON object per line: timestamp, event name,
bead, pull request, SHA, actor, detail. Nothing else is shared state. The driver decides what to do
next by reading the log, the bead tracker and GitHub — never by remembering. That is what makes a
tick restartable: kill the driver mid-campaign, start it again, and it picks up from what the three
stores say, because it kept nothing in memory that mattered.

Run state lives beside the log as one small file per bead, moved between directories rather than
edited: `runs/` while the pane is alive, `runs/waiting/` once the pull request is open,
`runs/done/` after the bead closes, `runs/crashed/` when it failed twice. Where a file sits is the
bead's status, readable with `ls`.

## The tick, in four steps

`smile run` repeats one tick, by default every sixty seconds.

1. **Reap.** For each run file: a live pane on a closed bead gets killed, its worktree returned, and
   the file moved to `done/`. A dead pane whose pull request exists means the worker finished a
   round, so the file moves to `waiting/`. A dead pane with no pull request is a crash: log it and
   respawn once with the same worktree and the same order; a second crash escalates and the file
   moves to `crashed/`.
2. **Review.** Every open factory pull request whose head has no verdict yet is handed to the review
   lane, below. Merged pull requests close their beads here.
3. **Claim and spawn.** Unless the campaign is paused, take ready beads until `max_parallel` live
   runs: claim the bead, lease a worktree, render the work order, spawn the pane, write the run
   file. Any failure after the claim releases the bead so the next tick can try again.
4. **Complete.** When no bead is open and no run file is live, the observer is reaped and
   `campaign.complete` is logged.

A pull request belongs to the factory when its body carries a `Bead: <id>` line. That one line is
the whole link between GitHub and the bead graph.

## The review lane and the fix round

For one pull request the lane takes a lock, fetches base and head, builds a detached worktree at the
head SHA, and renders the reviewer prompt with the diff, the spec, and the text of every open review
issue naming that pull request. The reviewer reads and never edits.

On `REQUEST CHANGES` the lane opens one labelled issue per blocking finding, comments the issue
links on the pull request, logs the verdict, and starts a **fix round**: the bead's run file moves
back from `waiting/`, and the worker is respawned in the same worktree with the same order. Its
order tells it to read the open issues naming its pull request, fix them, commit referencing each
issue, push and exit. The new head has no verdict, so the next tick reviews it again. Nothing parses
the commit messages; the next review is what decides.

On `APPROVE` the lane closes the review issues, logs the verdict, and then the gate decides. Gated
work (gate mode `all`, a gated bead in mode `auto`, a human-gate label, or `merge: manual`) gets an
approval label and stops there for a human. Otherwise the lane squash-merges, closes the bead, and
logs the merge.

A review that names no verdict, crashes, or times out logs nothing and is retried next tick, three
times, after which the pull request is skipped with an escalation rather than reviewed forever.

## The watchtower and narration

The observer is spawned on the first tick of a campaign and killed just before completion. It tails
the event log, appends one line per event to `.factory/watch.md`, and has exactly two powers: it can
append an escalation event, and it can pause the campaign. It does that when a bead crashes twice.
It never resumes — lifting a pause is a human decision.

`smile narrate` is the other half: it prints the events appended since it last ran, escalations
first, and remembers how far it got. A planner session that wakes up every few minutes calls it and
relays what it prints, so nobody has to read the raw log.

## The multiplexer seam

Agents run in panes, and which multiplexer supplies the pane is one three-verb seam:
`smile mux spawn <name> <cwd> <argv...>` prints a handle, `smile mux alive <handle>` exits 0 or 1,
and `smile mux kill <handle>` ends it. A handle is `<backend>:<rest>`, so it names its own backend
and nothing else has to track which one is in use.

Three backends implement it. **tmux** uses one window per agent in a named session and is the
default. **cmux** and **Herdr** each use one pane per agent. Their differences live behind the seam,
with one consequence worth knowing: a tmux window inherits the server's environment, so the driver
passes what a worker needs on the command line rather than exporting it.

Everything the driver learns about a worker comes through `alive`. That is why a worker runs in
print mode: an interactive agent never exits, so its pane would never die and the driver would wait
forever.

## The invariant

`smile audit` lists every merged factory pull request with no approving verdict at the SHA that was
merged. The event log says what the lane judged; GitHub says what landed. Where they disagree,
something was merged that review never approved. An empty audit is the factory's one promise:
nothing reached the base branch that a reviewer had not approved at exactly that SHA.
