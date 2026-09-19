---
name: factory-clock
description: >-
  Print where each subagent's wall time went (model time, live fixtures, unit tests, git,
  reading, editing, killed calls) for a Claude Code session, from its transcripts. Use after
  every spike of the SMILE factory build, or whenever a build feels slow and you want the
  table instead of a guess.
---

# factory-clock

Deterministic. Reads `~/.claude/projects/<project>/<session>.jsonl` for agent names and the
subagent transcripts under `/private/tmp/claude-<uid>/<project>/<session>/tasks/` and
`~/.claude/projects/<project>/<session>/subagents/`, pairs every `tool_use` with its
`tool_result`, and buckets the gap. The gap between a tool result and the next tool call is
model time (thinking plus writing).

## Run

```
.claude/skills/factory-clock/scripts/factory-clock                 # newest session of this project
.claude/skills/factory-clock/scripts/factory-clock <session-id>    # a specific session
.claude/skills/factory-clock/scripts/factory-clock --tsv > clock.tsv
```

Output is a markdown table, one row per agent that ran longer than two minutes, a totals
row, and the three longest tool calls per agent. `--min <seconds>` changes the cutoff.

## Reading it

- **model** high and everything else low: the brief was too big or the agent re-read the
  world. Shrink the brief.
- **unit tests** in minutes: the suite is slow, fix the suite (see `docs/PROCESS.md`).
- **live suite/fixture** in a builder's row: the builder ran the verifier's job. The brief
  must forbid it.
- **killed mid-call**: a stray Escape (see the herdr server log) or a stop. Resume, do not
  rebuild.
