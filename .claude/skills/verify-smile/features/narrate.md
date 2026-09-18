# Narrate

Narrate prints the events that arrived since the last call, one line each, escalations first, so the planner session can relay progress to the user without re-reading the log. (lands in S6)

## Sub-features

- `narrate-new` prints only lines newer than the cursor in `.factory/narrate.cursor`.
- `narrate-empty` prints nothing when no event arrived.
- `narrate-escalation-first` prints `watch.escalation` lines before the rest of a batch.
- `narrate-resume` works from any later session because the cursor is a file.

## How to get to it (user POV)

- Run `smile narrate` in the stamped repo, repeatedly.
- The campaign skill calls it on each wake and relays the lines in chat.

## Driving it with verify-smile

Preconditions:

- A fixture with `install: stamped` and stubs configured.

- **Three calls.** Run `verify-smile feature narrate`. The helper runs the loop and calls `smile narrate` three times at different points, capturing each output.
- **No duplicates.** The concatenated outputs, sorted, equal the event log rendered once through the same formatter, sorted. No line appears twice.
- **Empty call.** A fourth call after `campaign.complete` prints nothing and exits 0.
- **Proof.** `~/.smile-verify/<runid>/narrate.log` holds the three outputs and the comparison.

## Gotchas

- The cursor is a byte offset or a line count. A truncated log invalidates it. Never truncate `events.jsonl` in a recipe.
- Escalation-first reorders within one batch only. Do not assert global ordering across calls.
