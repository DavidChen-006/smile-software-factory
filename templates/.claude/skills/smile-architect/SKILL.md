---
name: smile-architect
description: >-
  Sketch types, signatures, and module structure before code, then stay in the loop while the
  implementation fills it in. Design it twice: at least two structurally distinct candidates in one
  session before you commit to a shape. Use for "architect this", "design this", or any non-trivial
  work where jumping to code would lock in the wrong shape.
---

# Architect

Design before implementing. Sketch types, function signatures, class shapes, and module boundaries
with `not implemented` bodies and pseudocode. Sketch more than one shape, pick one on stated
grounds, then fill in code against the chosen sketch. If the implementation proves the sketch wrong,
throw it out and redesign.

Five phases: ground, sketch, agree, implement, scrap.

## Phase A: Ground the problem

Build a real mental model of every system the new code touches. Trace the existing path end to end:
who calls it, what data crosses each boundary, who owns the state, what the current shape is
protecting. Naming a file is not grounding; produce the traced model.

If the design redefines ownership or layering, also recover the rationale for the existing shape, so
it becomes a constraint rather than a guess.

Skip Phase A only when the work is genuinely greenfield with no surrounding system to integrate.

## Phase B: Sketch, in one session, at least twice

Do the sketching yourself, in this session. No parallel runners, no second model, no arena.

1. **Candidate one.** Write the caller's usage first, then derive the type sketch from it: the
   public signatures, the data shapes, the module boundaries, bodies left as `not implemented`.
2. **Candidate two.** Sketch a structurally distinct alternative — a whole different shape, not a
   point fix inside the first. Move the seam, invert who owns the state, replace branching with a
   table, collapse two modules into one, split one into two. Do this even when the first candidate
   looks sufficient; the second is what makes the first a choice rather than a default.
3. **More when the stakes justify it.** A third candidate is worth the minutes when the decision is
   hard to reverse.

Screen every candidate against [`references/design-red-flags.md`](references/design-red-flags.md)
before you choose. Reject or revise shallow modules, information leakage, temporal decomposition,
and pass-through methods.

Compare the surviving candidates on interface depth. Prefer the design that hides more complexity
behind a smaller, simpler public surface. A rich interface can keep call chains short by
concentrating capability instead of scattering it across layers.

Then decide, in writing: a short table of the candidates, the axes you compared them on, the one you
picked, and the one sentence that decided it. That table is the synthesis; it ships with the
rationale.

## Phase C: Agree (opt-in)

Default: go straight to implementation with the chosen design. No human checkpoint.

Opt in to a checkpoint when the invoker asks for one ("stop and show me before implementing"). Then
surface the chosen sketch and the comparison table, and pause for sign-off.

Either way the sketch can ship as its own commit, scaffold first. If the human pushes back on the
shape, in a checkpoint or after the fact, treat that as Phase A evidence: re-ground and re-sketch
before writing more code.

## Phase D: Implement against the sketch

Replace `not implemented` bodies with code and pseudocode with logic. The chosen sketch is the
contract.

Deviations from the sketch are signal worth surfacing, not friction to absorb silently. If a
function needs a parameter the sketch did not anticipate, ask whether the sketch was wrong, the
requirement was missed, or the implementation is overreaching.

## Phase E: Scrap when the architecture is wrong

If the implementation keeps producing friction the sketch cannot absorb, throw the sketch out. Do
not bolt fixes onto a wrong design. The signal is a *pattern*, not a single instance. Tells:

- The same shape of workaround appearing repeatedly across unrelated code.
- Several unrelated edge cases that all need special-case branches.
- Types that need escape hatches — casts, `any`, optional fields always set in practice — to compile.
- The "we need a lock" reflex when the sketch said the state was not shared.
- Callers having to know the abstraction's internal rules to use it.
- Two or more independent Phase D deviations of the same shape.

Use judgment. A few edge cases do not condemn an architecture, some problems are legitimately
complex, and complexity in the data is not complexity in the design.

When you scrap: re-trace what has been built, redesign as if the new constraints had been day-one
assumptions, subtract before you add — the new sketch should be smaller than the old one before it
grows — and return to Phase B for a fresh pair of candidates.

## Outputs

The caller's usage written first, the type sketch derived from it. One file of new types and
signatures for a small change; a module map plus type definitions for larger work. The rationale
ships alongside: the usage sketch, the candidate table, and the sentence that decided the pick.
