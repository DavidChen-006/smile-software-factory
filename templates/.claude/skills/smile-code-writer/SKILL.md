---
name: smile-code-writer
description: >-
  How a SMILE factory worker writes code: three pillars — flow (separate deciding from doing;
  functional core, imperative shell), abstraction (general-purpose, deep modules that hide
  decisions), and side effects (pushed to the edges, fewest intermediate states) — plus the worker
  process that turns one bead into one reviewable pull request. Use when working a bead, designing a
  module, or deciding how to structure a change. The lane itself does not read this file; it renders
  `prompts/worker.md`, which names this skill.
---

# SMILE code writer

You are writing code, not just making it work. Structure is decided at writing time; these three
pillars decide it. They compound: flow makes side effects separable, separation makes modules
testable, deep modules keep the flow readable.

Two references carry the principles you name in your `Principles applied` line:

- [`references/laziness-protocol.md`](references/laziness-protocol.md) — `laziness-protocol`
- [`references/test-behavior.md`](references/test-behavior.md) — `test-behavior`

## Pillar 1 — Flow: separate deciding from doing

Every piece of code is one of two things: **deciding** (pure logic on plain data) or **doing**
(touching the world — files, network, database, clock). Keep them in separate units. This is the
functional core, imperative shell shape.

```
external state
     |
[shell] reads the facts      <- data in
     |
[core]  decides the action   <- pure logic
     |
[shell] executes it          <- data out
```

Logic never touches the world. Data crosses the boundary as plain values: the shell hands the core
facts, the core hands back a decision, the shell carries it out. When you catch a function both
computing and calling out, split it along that line.

## Pillar 2 — Abstraction: general and deep

Two orthogonal axes:

- **Generality** — how many use cases one module serves. One general module that does the work of
  several specialized ones beats them. Ask "what is the simplest interface that covers all my
  current needs?", not "what does this one caller want?"
- **Depth** — interface size versus what it hides. Small interface, large hidden implementation: the
  caller writes one line to get hundreds. Do less externally, more internally.

**Hide decisions — every parameter is a decision pushed onto the caller.**

```
shallow:  send(to, subj, body, retries=3, timeout=30, tls="1.2", encoding="utf8", pool=conn)
deep:     send(to, subj, body)
```

The deep version decides retry, timeout, and TLS policy inside the module: once, and changeable in
one place. Expose only what genuinely varies per call and give everything else an internal default.
The parameters that remain get precise types, so the signature documents the contract.

## Pillar 3 — Side effects: classified, then minimized

- **Classify.** Separate pure functions from effectful ones. Pure logic tests with plain values;
  effects isolated at the edge test with one seam. Logic tangled with effects tests with neither.
- **Minimize intermediate states.** More intermediate steps means more edge cases and more places
  for bugs. Prefer the sandwich — **effects, pure, effects** — and treat every extra pure/effect
  alternation as a cost to justify, not a neutral choice.

## The worker process

You own one bead and nothing else. The bead's description and the frozen spec are the whole scope.

1. **Ground.** Read the spec section the bead names and the code it touches. Trace the real path
   before you change it. Naming a file is not grounding.
2. **Decide the shape.** When the change admits more than one structure (error handling, where a
   seam goes, how the tests are organized), sketch at least two candidates in a few lines each, pick
   one, and say in the pull request body why. Do not fold the design decision silently into the
   implementation.
3. **Name the data.** Choose the organizing structure before you write logic: a state machine over
   scattered booleans, a table or registry over branching, a typed model over repeated shape
   assumptions.
4. **Write the smallest complete change.** `laziness-protocol` governs here: nothing speculative,
   nothing unrequested, and whatever your change orphans goes with it.
5. **Test the behaviour.** `test-behavior` governs here: observable behaviour through the public
   surface, one behaviour per test, fakes only at process boundaries.
6. **Verify on the matching surface.** Run the suite the change belongs to. "Inconclusive" or the
   wrong surface is not a pass; say so rather than claiming green.
7. **Sequence the commits.** Small, ordered commits, each one building and passing before the next.
8. **Open the pull request** on the branch the order names, with the `Bead: <id>` trailer on its own
   line, and stop. Never merge, never close the bead, never run the driver.

On a fix round you do not re-open a pull request. Read every open issue labeled `review` that names
your pull request, fix each finding, commit with `addresses #<issue>` in the message, push, stop.

## Rules

1. Every unit is deciding or doing — never both. Split along that line.
2. Default flow: shell reads facts, core decides, shell executes.
3. One general module over several specialized ones; design the interface for the need, not the
   caller.
4. Small interface, deep implementation. A new parameter is a decision you failed to hide.
5. Effects live at the edges; aim for effects–pure–effects and justify every extra alternation.
6. Remaining parameters carry precise types — the signature is the contract.
7. The smallest complete change, and nothing your change orphans left behind.
8. End your work with the line `Principles applied: <name>, <name>, ...`, naming each principle by
   the name this skill gives it. `none` is a valid value.
