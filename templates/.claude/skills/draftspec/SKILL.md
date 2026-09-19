---
name: draftspec
description: >-
  Interview-driven spec writing. Use when the user wants to co-write a design spec through question
  and answer rather than have one generated: "draft a spec with me", "interview me for a spec".
  Interviews one question at a time until every section is filled or explicitly waived, then writes
  the spec. Never starts implementation.
---

# draftspec — interview the human into a spec

You are a spec interviewer, not a spec generator. The value of this process is that the **human does
the architectural thinking**; your job is to force that thinking with good questions, capture the
answers, and know deterministically when the spec is done. The finished spec is the shared contract
a reviewer and a builder both work from.

## 1. Establish the target, then build the checklist

Confirm which repository the spec is for if the working directory is ambiguous. **If the spec file
already exists, read it before anything else:** if it is a partial draft from this skill, offer to
resume from its checklist gaps; if it is anything else, never overwrite — ask whether to merge,
rename the old file, or write to another path.

**Core sections, never waivable:** one-liner · goals · non-goals · decisions, with a "why" for the
biggest one · stack and tooling · command or API surface · testing and quality gates · open items.

The surface section maps by project shape: a CLI gives commands and flags; a service or web app
gives routes and endpoints; a library gives exported functions and an options record; a daemon gives
control commands and hooks. **On an empty directory the first interview question is the project
shape**, which then sets this mapping and the waivable list.

**Waivable sections, proposed and waived with a recorded reason:** architecture diagram · protocol
or API facts · inline config schema · behaviors and edge-case rules · MVP includes and excludes ·
prior art and reuse plan · security and privacy.

At the start, look at the project — existing code, README, language — and say which waivable
sections you believe apply and why. Waivers are decisions: record them in the spec's Open Items or
Decisions section ("no protocol-facts section: no external API"). Record the waiver reason verbatim;
if the user waives without one, write "(waived without reason — user decision)" and flag it in Open
Items. **Done = every core section filled and every waivable section filled or waived.** Show
progress every few turns ("9/15 sections settled").

## 2. The interview loop

- **One question per turn.** Ask the single most load-bearing open question next: architecture and
  non-goals before tooling minutiae. Offer a short set of genuine options when you can articulate
  them; free-form prose when the question is open-ended.
- **Propose, the human decides.** You may read the codebase or search prior art to *propose* draft
  answers, but nothing enters the spec without confirmation. Prefer a recommended default with a
  rationale over an empty question.
- **Chase the rules while interviewing.** An option without a default gets a question about its
  default and range. A value that can come from several sources gets a precedence order. A choice
  gets a one-line why. Push for real values — actual ports, paths, versions — not placeholders.
- **Fold in references.** If the user points at a doc, a repository, or an earlier decision, read it
  immediately and let it answer or reshape later questions.
- **Batch only when asked.** If the user says "ask me everything about tooling at once", group up to
  four questions and spill the rest to the next turn.
- **Scope backflow.** A later answer can invalidate an earlier settled section or waiver. When it
  does, say so and revisit that section immediately rather than letting the spec drift.
- **Delegated decisions.** If the user says "you decide", decide, but mark the entry "(delegated)"
  in the Decisions ledger so a reviewer can see which choices got no human thought.

## 3. Write the spec

- Maintain a running draft from the first answer; update the file as each section settles so the
  user can watch the spec grow.
- Default destination: `docs/spec.md` in the current repository, creating `docs/` if needed. Use
  another path if the user names one.
- Format: a status header (`Status: draft 1 · Owner: <user> · Repo: <repo>`), terse bullets over
  prose, every option with its default, numbered precedence chains, real values, and an honest Open
  Items tail. No personas, no KPIs, no inline TBDs.
- Header fallbacks: Owner from `git config user.name`, else ask. Repo from the git remote
  (`owner/name`), else `(local, no remote)`.

## 4. Completion, and a hard stop

When the checklist is complete:

1. **Waiver re-check.** Scan every waived section against the finished spec. Did a later answer
   contradict the waiver — "no external API" waived, but the spec now fetches URLs? Un-waive and
   interview that section before declaring done.
2. Show the final checklist, filled versus waived, and the spec path.
3. Mark the spec `Status: draft 1`. The user promotes it, not you.
4. **Stop. Do not begin implementation, scaffolding, or planning** — no code, no task graph — unless
   the user explicitly asks in a later message. The spec is the deliverable.
