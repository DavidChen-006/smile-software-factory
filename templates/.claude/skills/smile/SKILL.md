---
name: smile
description: >-
  Run the SMILE software factory from one entry point. Use on `/smile full`,
  `/smile dark`, `/smile build <prompt>`, `/smile status`, "run the factory",
  or "start a campaign from this prompt". Routes the request to one procedure
  page and to the stage skill that owns that step; it never does the stage work
  itself.
argument-hint: "[full | dark | build <prompt> | status]"
---

# /smile — the factory router

One skill on top of the stage skills. It reads the repository to decide where a
run starts, then hands each step to the skill that owns it. The ladder
(smile-grilling, smile-draftspec, smile-architect, smile-preflight, smile-campaign) is advisory; the spec
freeze is the only enforced gate. This skill sequences and narrates: it plans no
graph, writes no spec, and creates no bead of its own except in `build`.

## Verbs

| Verb | What it does | Page |
|---|---|---|
| `full` | walk the ladder top to bottom, one question between stages | [references/full.md](references/full.md) |
| `dark` | frozen spec straight to a campaign, no approval wait | [references/dark.md](references/dark.md) |
| `build <prompt>` | one bead from the prompt, driver up, narrate to done | [references/build.md](references/build.md) |
| `status` | the state table with a tick per row, then `smile status` | [references/status.md](references/status.md) |

**Unknown verb, or none: print this table and stop.** Do not guess a verb.

Load exactly one page, the one for the verb given. The pages are not read at
startup.

## State, not memory

Where a run starts is decided by what exists in the repository, never by what
this session remembers. Check in order:

| Check, in order | Fact | Next stage |
|---|---|---|
| spec | newest `docs/*SPEC*.md` or `docs/*DESIGN*.md` by mtime, ties broken by the greater path string | absent: `smile-grilling`, then `smile-draftspec` writes it |
| frozen | `git log -1 -- <spec>` prints a commit and the working tree copy is unchanged | not frozen: ask the user to commit it; this skill never commits a spec |
| architecture | the spec contains a `## Architecture` heading | absent: `smile-architect`, which appends that section to the spec (a second freeze commit follows) |
| preflight | `docs/preflight/<spec basename>` exists and is committed (a directory, so the spec glob never matches it) | absent: `smile-preflight`, whose notepad is written to that path; this skill then commits it |
| campaign | `.factory/events.jsonl` holds a `campaign.start` newer than the spec's last commit | absent: `smile-campaign` |

## The one rule

**Load the stamped stage skill by its prefixed name and follow it. Never do
stage work yourself, and never a skill of a similar name from elsewhere.**
Every stage skill lives at `.claude/skills/smile-<stage>/SKILL.md` in this
repository. When the table says `smile-draftspec`, load the stamped skill
`smile-draftspec` (`.claude/skills/smile-draftspec/SKILL.md` in this repo) and
run its interview; do not write a spec from this file. When it says
`smile-campaign`, load the stamped skill `smile-campaign`
(`.claude/skills/smile-campaign/SKILL.md` in this repo); never a skill of a
similar name from elsewhere. Follow every step of it, including its refusal
without a frozen spec. Each
stage is entered fresh: nothing is carried between stages except the files they
leave in the repository.
