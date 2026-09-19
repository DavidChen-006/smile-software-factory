# Gate

Gate is the human hold. With the gate mode `all`, with `merge` set to anything but `auto`, or with a `human-gate` label on the pull request, an approved pull request is labeled `smile:approved` and stays open until a person merges it; the bead closes on the next tick after that merge.

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
- Put the `human-gate` label on a pull request.
- Merge the held pull request on GitHub or with `gh pr merge`.

## Driving it with verify-smile

Preconditions:

- A fixture with `install: stamped` and one seeded bead. One bead is the whole lane.

- **Set the mode.** `verify-smile gate all` prints `"exit": 0` with an empty `stdout`. `verify-smile gate status` prints `"stdout": ["mode all"]`.
- **Gate one bead instead.** `verify-smile gate bead <id> on` then `verify-smile gate status` prints `["mode auto", "bead <id>"]`. `verify-smile gate bead <id> off` removes the line.
- **Hold.** Tick until the bead has a verdict: `verify-smile tick` claims and the worker opens its PR, another `verify-smile tick` reviews and approves. With the gate holding, the lane labels instead of merging.
- **Nothing merged.** `verify-smile prs` shows the PR still `"state": "OPEN"` carrying the label `smile:approved`, and `verify-smile events --bead <id>` holds no `pr.merged`.
- **Release.** Merge as a person would: `gh pr merge <n> --squash` in the fixture. Then `verify-smile tick` finds the merge and closes the bead.
- **Modes matrix.** Not driven live. `tests/test_review.py` runs all seven combinations of mode, gated bead, `human-gate` label, and the `merge` config key through a real verdict.

## Evidence that proves it

- `verify-smile gate status` printing exactly `{"argv": ["status"], "exit": 0, "stdout": ["mode all"]}`; no bead lines for a repo-wide hold.
- `verify-smile prs` for the held PR: `"state": "OPEN"`, `"labels": ["smile:approved"]`, `"mergedAt": null`, at a point where `verify-smile events --bead <id>` already holds a `review.verdict` with `detail` `APPROVE`.
- The absence of `pr.merged` in that bead's events while the PR is held, and its presence afterwards with `"actor": "human"` and the merge commit in `sha`.
- The bead's sequence ending `review.verdict pr.merged bead.closed pane.reaped`, with no `pr.merged` between the verdict and the human's `gh pr merge`.
- `<factory>/gate.json` in the evidence directory's `factory/`, compact with sorted keys, holding the mode and the gated bead ids.

## Gotchas

- The mode is read at verdict time. Changing it mid-loop applies to the next verdict, not to a pull request already labeled.
- A held pull request that a person closes without merging leaves the bead claimed. That is the expected escalation path, not a bug: the close path only fires on `mergedAt`.
- An absent `gate.json` means mode `auto` with no beads, and `smile gate status` never creates it. A missing file is not a missing feature.
- The driver finds the human's merge by listing closed pull requests that carry `smile:approved`. A person who strips that label before merging leaves the bead open.
- `verify-smile gate` runs in the run world, so it writes the same `gate.json` the ticks read. Setting the mode with a bare `smile gate` in another shell works too, but only if it resolves the same factory directory.
