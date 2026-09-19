# Gate

Gate is the human hold. With the gate mode `all`, with `merge` set to anything but `auto`, or with a `human-gate` label on the pull request, an approved pull request is labeled `smile:approved` and stays open until a person merges it, and the bead closes on the next tick after the merge. (landed in S4)

## Sub-features

- `gate-status` prints the repo mode and the gated beads.
- `gate-all` holds every approve.
- `gate-none` merges every approve.
- `gate-auto` (the default) holds only the beads `smile gate bead <id> on` names, and any pull request labeled `human-gate`.
- `gate-bead` turns the hold on or off for one bead.
- `gate-release` closes the bead once a person merges the held pull request.

## How to get to it (user POV)

- Run `smile gate status|all|none|auto` and `smile gate bead <id> on|off` in the stamped repo.
- Set `merge: manual` in `smile.config.yaml`, which holds every approve whatever the gate says.
- Merge the held pull request on GitHub or with `gh pr merge`.

## Driving it with verify-smile

Preconditions:

- A fixture with `install: stamped`. The helper runs `smile init` and builds the same scratch world the review feature uses, with the stub worker and the stub reviewer (which approves on sight).

- **Hold.** Run `verify-smile feature gate`. The helper closes bead B, runs `smile gate all`, asserts `smile gate status` prints exactly `mode all`, then ticks until a `review.verdict` for bead A exists. `gh pr view <A-pr> --json state,labels` must then show state `OPEN` with the label `smile:approved`, and the log must hold no `pr.merged` for A.
- **Release.** The helper runs `gh pr merge <A-pr> --squash --delete-branch`, then ticks until a `bead.closed` for A exists, and asserts `bd list --all --json` shows A `closed`. That close is the driver's step 2 close path: the `pr.merged` it appends carries `actor` `human` and the merge commit.
- **Status.** `smile gate status` is asserted as exact stdout, `mode all` with no bead lines; the matrix of mode, bead, label, and `merge` config is proved in `tests/test_review.py`, where all seven combinations run through a real verdict.
- **Proof.** `~/.smile-verify/<runid>/gate.log` holds the pull request view before and after the manual merge, and the bead's event sequence.

## Gotchas

- The mode is read at verdict time. Changing it mid-loop applies to the next verdict, not to a pull request already labeled.
- A held pull request that a person closes without merging leaves the bead claimed. That is the expected escalation path, not a bug: the close path only fires on `mergedAt`.
- The gate file is `<factory>/gate.json`, written compact with sorted keys; an absent file means mode `auto` with no beads, and `smile gate status` never creates it.
- The driver finds the human's merge by listing closed pull requests that carry `smile:approved`. A person who strips that label before merging leaves the bead open.
