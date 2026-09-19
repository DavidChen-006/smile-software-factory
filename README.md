# SMILE software factory

SMILE turns a queue of issues into a queue of reviewed pull requests. You write a spec, break it
into beads (issues in the `bd` tracker), and start the driver; it claims each ready bead, gives it
its own worktree and its own agent pane, and waits for the pull request. A second agent reviews
every pull request against the spec, opens an issue per blocking finding, sends the worker back for
a fix round, and merges only what it approved.

## Prerequisites

`smile doctor` checks all of them and prints one line each, in this order:

- `uv` — the runtime runs as `uv run`, so nothing is installed into your Python.
- `git` — the repo, and one worktree per running bead.
- `gh`, signed in — every pull request, issue, label and merge goes through it.
- `claude` — the worker, the reviewer and the watchtower are all agent processes.
- `bd` — the issue tracker the bead graph lives in.
- `treehouse` — the worktree pool the driver leases from.
- a multiplexer — one of tmux, cmux or Herdr; each agent runs in a pane of its own.

Anything missing prints `missing <tool> <reason>` and doctor exits 1.

## From a clean repo to a running campaign

```
uv run install.py /path/to/your/repo   # stamp the runtime, prompts and skills into the repo
cd /path/to/your/repo
smile/smile init                       # create .factory/ and the config file
bd create "add a health endpoint" --description "..."   # one bead per unit of work
smile/smile run                        # the driver loop; --once for a single tick
```

`smile init` writes `smile.config.yaml`. The settings you are most likely to touch are
`max_parallel` (how many beads run at once), `merge` (`auto`, or `manual` to leave every approved
pull request for you), and `backend` (which multiplexer to use).

Beads are ordinary `bd` issues, so ordering is ordinary dependencies: `bd create "..." --deps <id>`
keeps a bead out of the ready list until its blocker closes. The driver only ever claims what
`bd ready` lists.

## Watching it

- `smile narrate` prints every event since the last call, escalations first. It is the one command
  to run when you come back to a campaign: call it, read the lines, call it again later.
- `smile status` prints the current state and the last ten events.
- The panes are real: attach to the multiplexer and you can read over a worker's shoulder.
- The watchtower writes `.factory/watch.md`, a running log of the campaign, one line per event.
- `smile audit` prints every merged factory pull request that no review ever approved. It should
  print nothing.

## Stopping it

- `smile pause` claims no new beads; work already running finishes and reviews still happen.
- `smile resume` lifts it. The watchtower pauses the campaign by itself when a bead crashes twice,
  and never resumes: that decision stays yours.
- The driver runs until every bead is closed, then exits on its own.

## Next

`docs/HOW-IT-WORKS.md` explains the machine: the lanes, the event log, the tick, the review lane,
the watchtower, the multiplexer seam and the one invariant the audit guards.
