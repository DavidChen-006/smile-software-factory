# Narration

`smile narrate` is what a planner session calls on every wake: it prints the events appended since
its last call, one line each, escalations first, and remembers where it stopped in a byte-offset
cursor at `.factory/narrate.cursor`. It reads the log and the cursor and appends nothing.

## Sub-features

- `narrate-new` prints every complete log line appended since the cursor, rendered
  `<ts> <event> <bead> <pr> <actor> <detail>` with null fields as `-` and `detail` verbatim.
- `narrate-cursor` writes the byte offset it consumed to `narrate.cursor.tmp` and renames it over
  `narrate.cursor` after printing; an absent cursor is 0 and an offset past the end of the log is 0.
- `narrate-quiet` prints nothing and leaves the cursor byte-identical when nothing is new, exit 0.
- `narrate-partial` leaves a trailing line without its newline for the next call and prints it once
  it is complete.
- `narrate-escalation-first` prints `watch.escalation`, `driver.paused`, and `worker.crashed` with
  `detail` `escalated` ahead of the call's other lines, log order inside each group.
- `narrate-unreadable` prints a line that does not parse as a section 3 event as
  `<byte offset> unreadable` rather than dropping it.
- `narrate-badcursor` is one stderr line `bad narrate.cursor` and exit 1 with nothing printed; an
  extra argument is exit 2.

## How to get to it (user POV)

- Run `/campaign`: the skill starts `nohup smile/smile run > .factory/driver.log 2>&1 &` from the
  main checkout and then calls `smile narrate` on every wake, relaying each printed line.
- By hand, from the repo: `smile/smile narrate` any time, from any session. The cursor is in the
  repo, not in the session, so a fresh session resumes where the last one stopped.
- `rm .factory/narrate.cursor` re-narrates the whole log from the beginning.

## Driving it with verify-smile

Preconditions: a fixture with `install: stamped` and at least one seeded bead.

- **Baseline.** `verify-smile narrate` once before any tick: whatever the stamp and seed left in the
  log is consumed, and the cursor is set. Everything after this is the loop's own narration.
- **Across a loop.** `verify-smile tick`, then `verify-smile narrate`; tick again, narrate again;
  tick again, narrate again. Each `tick` prints the events it appended, so the tick JSON and the
  narrate JSON can be read side by side.
- **Nothing new.** Call `verify-smile narrate` twice with no tick in between: the second call's
  `lines` is `[]` and its `cursor` equals the first call's.
- **Escalation.** `verify-smile tick --worker-crash <bead>` twice, then narrate: the call that
  covers the `worker.crashed` `escalated` line prints it first.
- **The whole log.** `verify-smile events` prints every line of the log, which is what the
  concatenated narrations are checked against.
- **Not driven live.** The bad cursor, the extra argument, the partial trailing line, and the
  unreadable line are proved offline by `tests/narrate.test.sh`.

## Evidence that proves it

- Three `verify-smile narrate` calls across a loop (one after each `tick`), their `lines` arrays
  concatenated in call order, equal `verify-smile events` rendered exactly once as
  `<ts> <event> <bead> <pr> <actor> <detail>`: every event line appears once, none is missing, and
  the order matches the log except where the escalation-first rule moved a line inside one call.
- The `cursor` of each call equals the byte length of the log consumed so far: after the last call
  it equals `wc -c < <fixture>/.factory/events.jsonl` when the log ends in a newline.
- A `verify-smile narrate` made with no `tick` since the previous one prints `"lines": []` and its
  `cursor` is byte-identical to the previous call's.
- In the escalation call, the first entry of `lines` is the `worker.crashed ... escalated`,
  `watch.escalation`, or `driver.paused` line, and the `verify-smile events` output shows those same
  lines appended after the ordinary lines that printed below them.
- Every call's `exit` is 0.

## Gotchas

- `stamp` and `seed` write nothing to `events.jsonl`; the log is empty until the first `tick`, so a `narrate` before it prints nothing and leaves no cursor file (verified 2026-09-19, run 7abd).
- The cursor counts bytes, not lines: a `detail` with multi-byte characters makes the cursor larger
  than the character count. Compare it with `wc -c`, never `wc -l`.
- `smile narrate` appends no event, so a `verify-smile events --since <n>` taken around a narrate
  call is empty. That is the contract.
- Narration is per-repo, not per-session: another session (or a stray `verify-smile narrate`)
  consumes lines this one will never see. Only one narrator per fixture during the drive.
- The factory directory resolves through the git common dir, so a narrate run from a worktree reads
  the main checkout's log and cursor.
