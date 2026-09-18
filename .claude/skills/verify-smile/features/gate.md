# Gate

Gate is the human hold. With `merge: human` in the config, or a `human-gate` label on the bead, an approved pull request is labeled `smile:approved` and stays open until a person merges it, and the bead closes on the next tick after the merge. (lands in S4)

## Sub-features

- `gate-status` prints the repo mode and the gated beads.
- `gate-all` holds every approve.
- `gate-none` merges every approve, the default.
- `gate-auto` holds only beads carrying the `human-gate` label.
- `gate-bead` turns the hold on or off for one bead.
- `gate-release` closes the bead once a person merges the held PR.

## How to get to it (user POV)

- Run `smile gate status|all|none|auto` and `smile gate bead <id> on|off` in the stamped repo.
- Set `merge: human` in `smile.config.yaml`.
- Merge the held PR on GitHub or with `gh pr merge`.

## Driving it with verify-smile

Preconditions:

- A fixture with `install: stamped` and stubs configured.

- **Hold.** Run `verify-smile feature gate`. The helper runs `smile gate all`, then the loop. After the `review.verdict` event for bead A, `gh pr view <A-pr> --json state,labels` shows state `OPEN` and a label `smile:approved`. `bd list --json` still shows A `open`.
- **Release.** The helper runs `gh pr merge <A-pr> --squash`. On the next tick the event log gains `pr.merged` and `bead.closed` for A, and B becomes ready.
- **Status.** `smile gate status` prints `mode: all` before and the held PR number while it is held.
- **Proof.** `~/.smile-verify/<runid>/gate.log` holds the PR view before and after the manual merge.

## Gotchas

- The mode is read at verdict time. Changing it mid-loop applies to the next verdict, not the held one.
- A held PR that a person closes without merging leaves the bead claimed. That is the expected escalation path, not a bug.
