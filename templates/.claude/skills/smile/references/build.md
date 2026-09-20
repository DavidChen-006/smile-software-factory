# `/smile build <prompt>` — one bead, start to pull request

The small path: one prompt, one bead, one pull request. No spec is needed and
none is read. The state table is not walked.

## 1. Preflight

```bash
smile/smile doctor           # every line must read ok
test -d .beads || echo "smile init needed"
gh repo view >/dev/null      # the review lane needs a GitHub remote
```

If one fails, say what is missing and stop. Do not stamp the runtime or run
`bd init` as a side effect.

## 2. Create exactly one bead

Title is the prompt's first line. Description is the rest of the prompt; when
the prompt is a single line, the description is that whole line. Plain text
only — no `$`, no backticks, no double quotes — because the driver expands work
orders through the shell.

```bash
bd create "<first line>" -d "<the rest, or the whole prompt>"   # capture the id
```

One bead, no edges, no graph gate. Do not decompose the prompt.

With no spec, the worker order's spec path is empty, which the runtime allows,
and the reviewer judges the diff against the bead text alone. Say this in one
line so the user knows what the verdict will be measured against.

## 3. Ignition

From the main checkout, never from a worktree:

```bash
cd <repo> && nohup smile/smile run > .factory/driver.log 2>&1 &
```

Record the pid it printed: `kill <pid>` stops the campaign, `smile pause` parks
it.

## 4. Narrate until that bead is done

On every wake:

```bash
smile/smile narrate
```

Relay each printed line in the order printed, escalations first. Nothing printed
means nothing happened: say nothing. Never read `.factory/events.jsonl` or
`.factory/driver.log` yourself — `narrate` is the only narration surface and it
remembers its own offset in the event log.

Stop the loop on the first of:

- `bead.closed` for that bead id — print the pull request URL from the events
  narrate relayed, and say the build is merged.
- `worker.crashed` with detail `escalated` for that bead — print the escalation
  and ask the user for their ruling. The run is parked; do not restart it.
- `campaign.complete` — the driver finished. Print what narrate last relayed
  and stop.

Then this page is done. Nothing else is supervised from here.
