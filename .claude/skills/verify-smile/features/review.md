# Review

Review is the lane that judges every open pull request at its head commit, turns blocking findings into GitHub issues the worker resolves, re-reviews the fix, and merges on a verified approve.

## Sub-features

- `review-trigger` reviews each open PR carrying a `Bead:` trailer that has no verdict at its head SHA, once, and logs `pr.opened` the first time it sees the PR.
- `review-changes` opens one issue labeled `review` per blocking finding and comments on the PR with the links.
- `review-fix` moves the waiting run back under `.factory/runs/`, respawns the worker for a fix round, and re-reviews the new head with the issue thread in the prompt.
- `review-approve` closes the open findings, squash-merges, and closes the bead.
- `review-real` runs the real headless reviewer and records a non-empty verdict detail.
- `review-manual` reviews one PR by hand with `smile review <pr>`.

## How to get to it (user POV)

- Let `smile run` review automatically each tick.
- Run `smile review <pr>` in the stamped repo to review one PR by hand.
- Open the `review` issues on GitHub to read findings and the worker's replies.

## Driving it with verify-smile

Preconditions:

- A fixture with `install: stamped` and at least one seeded bead whose worker has opened a PR (one claim tick).
- The stub reviewer approves on sight unless the tick passes `--reviewer-changes-once`, which makes it answer `REQUEST CHANGES` with one `- [Critical]` finding the first time it sees a given PR and approve after.

- **Open the PR.** `verify-smile tick` claims the bead and the stub worker opens its pull request.
- **Request changes.** `verify-smile tick --reviewer-changes-once`. The tick's events carry `pr.opened`, `review.started`, `issue.opened`, `review.verdict` (`REQUEST CHANGES 1`), and the fix round's own `pane.spawned`.
- **Fix round.** The respawned stub worker reads the open `review` issue naming its PR, pushes a `fix: address review` commit with an `addresses #<issue>` line, and exits. Give GitHub a few seconds; its commit list lags a push.
- **Approve and merge.** `verify-smile tick --reviewer-changes-once` again. The new head has no verdict, so the lane reviews it, finds the stub now approving, closes the issue, merges, and closes the bead: `review.started`, `issue.resolved`, `review.verdict` (`APPROVE`), `pr.merged`, `bead.closed`.
- **Reap.** One more `verify-smile tick` logs `pane.reaped` and `campaign.complete`.
- **Real reviewer.** Not reachable through `tick`, which always wires the stub. Drive it by hand: set `SMILE_REVIEW_CMD` empty and run `smile review <pr>` in the fixture with the signed-in `claude` on PATH. Expect minutes and real tokens. Pass when a `review.verdict` for the bead carries a non-empty `detail`; what it decides is its own business.
- **Manual review.** `verify-smile time review <pr> --n 1` runs `smile review <pr>` once through the shim and prints its exit and stdout. A bead with no waiting run spawns nothing on `REQUEST CHANGES`, which is why the lane is normally driven through ticks.

## Evidence that proves it

- The bead's full sequence from `verify-smile events --bead <id>`, in this order and no other:
  `bead.claimed worktree.acquired pane.spawned pr.opened review.started issue.opened review.verdict pane.spawned review.started issue.resolved review.verdict pr.merged bead.closed pane.reaped`.
  That is the contract's section 9 sequence with the fix round's own `pane.spawned` between the `REQUEST CHANGES` verdict and the second review.
- The two `review.verdict` details, in order: `REQUEST CHANGES 1` then `APPROVE`.
- `verify-smile prs`: the PR carrying that bead is `"state": "MERGED"` with a non-null `mergedAt`. GitHub's own answer is the merge proof; a `pr.merged` event alone is the driver's word.
- `verify-smile issues`: exactly one issue whose `pr` is that PR number, `"state": "CLOSED"`, none left `OPEN`.
- The PR carries a comment naming the issue URL (`gh pr view <n> --json comments`).
- The bead is `closed` in `beads.json` in the evidence directory, or from `verify-smile close-bead`'s read-back shape.
- `<fixture>/.factory/reviews/<pr>-<sha>.md` holds the full review text for each verdict, one file per head SHA, and lands in the evidence directory as `factory/reviews/`.

## Gotchas

- The real reviewer takes minutes and spends tokens. Run it on one bead, never for every bead in a fixture.
- A verdict at an older head SHA is not a verdict: the lane keys on `(pr, sha)`, so a fix push is always reviewed again. `tests/test_review.py` proves the filter.
- The stub reviewer's counter lives under `.factory/stub/`, keyed by PR number, so `--reviewer-changes-once` requests changes once per PR, not once per fixture. A second fixture starts clean.
- Pass `--reviewer-changes-once` on every tick of the round. It shapes the stub for that tick only; dropping it mid-round makes the first review of a later PR an approve.
- The worker only wakes for a fix round because `smile review` moved `.factory/runs/waiting/<bead>.json` back and respawned it. Reviewing a PR by hand with no waiting run spawns nothing.
- `review.started`'s `detail` is `custom` whenever `SMILE_REVIEW_CMD` is set, which it always is under `tick`. A `detail` naming a model means the real reviewer ran.
- A tick that exits non-zero because a review named no verdict is normal: nothing is logged and the next tick reviews the same head again.
