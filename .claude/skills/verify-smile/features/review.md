# Review

Review is the lane that judges every open pull request at its head commit, turns blocking findings into GitHub issues the worker resolves, and merges on a verified approve. (landed in S4)

## Sub-features

- `review-trigger` reviews each open PR carrying a `Bead:` trailer that has no verdict at its head SHA, once, and logs `pr.opened` the first time it sees the PR.
- `review-changes` opens one issue labeled `review` per blocking finding and comments on the PR with the links.
- `review-fix` moves the waiting run back under `.factory/runs/`, respawns the worker for a fix round, and re-reviews the new head with the issue thread in the prompt.
- `review-approve` closes the open findings, squash-merges, and closes the bead.
- `review-real` runs the real headless reviewer and records a non-empty verdict detail.
- `review-audit` lists PRs merged without an `APPROVE` verdict at their head SHA.

## How to get to it (user POV)

- Let `smile run` review automatically each tick.
- Run `smile review <pr>` in the stamped repo to review one PR by hand.
- Run `smile audit` to list unreviewed merges.
- Open the `review` issues on GitHub to read findings and the worker's replies.

## Driving it with verify-smile

Preconditions:

- A fixture with `install: stamped`. The helper runs `smile init` itself, so the treehouse pool and `.factory/` exist.
- The helper builds the run's scratch world (`world_up`) and points `SMILE_WORKER_CMD` at a wrapper around `scripts/stub-worker` and `SMILE_REVIEW_CMD` at a wrapper around `scripts/stub-reviewer`, with `SMILE_STUB_CHANGES_ONCE=1`. Both wrappers re-enter the scratch `HOME`, the run's git config, and `GH_TOKEN`, because a pane inherits the multiplexer session's environment and `smile review` hands the reviewer its own.

- **Changes then approve.** Run `verify-smile feature review`. The helper closes bead B (one bead is the whole lane), then runs `<fixture>/smile/smile run --once` every ten seconds until bead A is reaped, or ten minutes pass. It asserts, against GitHub and the event log and never the driver's summary: the PR carrying A's trailer is `MERGED`; exactly one `review` issue exists, it is `CLOSED`, and none is left open; the PR carries a comment naming an issue URL; `bd list --all --json` shows A `closed`.
- **The sequence.** A's events, in order, must be exactly
  `bead.claimed worktree.acquired pane.spawned pr.opened review.started issue.opened review.verdict pane.spawned review.started issue.resolved review.verdict pr.merged bead.closed pane.reaped`.
  That is the contract's section 9 sequence with the fix round's own `pane.spawned` between the `REQUEST CHANGES` verdict and the second review: the contract's last paragraph omits it while its Fix rounds paragraph requires it, so the harness asserts the sequence the runtime actually has to produce.
- **Real reviewer.** Run `verify-smile feature review --real-review`. The stub reviewer is cleared, so `smile review` runs `claude -p` with the configured model. It ticks for up to fifteen minutes and passes when a `review.verdict` for bead A carries a non-empty `detail`; the review text under `<fixture>/.factory/reviews/` is printed into the log. What the reviewer decides is its own business: an `APPROVE` merges, a `REQUEST CHANGES` opens issues, and either is a pass here.
- **Audit.** Not driven live. `tests/test_review.py` covers `smile audit` against merged PRs with no `APPROVE` at their head SHA.
- **Proof.** `~/.smile-verify/<runid>/review.log` holds every tick, the issue and PR listings, the per-bead sequence, and for `--real-review` the review the reviewer wrote. `factory/events.jsonl` in the evidence directory holds the verdict lines.

## Gotchas

- The real reviewer takes minutes and spends tokens. Run it in one lane, never for every bead.
- A verdict at an older head SHA is not a verdict: the lane keys on `(pr, sha)`, so a fix push is always reviewed again. `tests/test_review.py` proves the filter.
- The stub reviewer's counter lives under `.factory/stub/`, keyed by PR number. A second fixture starts clean.
- The worker only wakes for a fix round because `smile review` moved `.factory/runs/waiting/<bead>.json` back and respawned it. A bead reviewed by hand with no waiting run spawns nothing, which is why this feature never calls `smile review` directly.
- A tick that exits non-zero (a gh hiccup, a review that named no verdict) is printed and the loop goes on: the next tick re-reads the world. Only the end state decides the verdict.
