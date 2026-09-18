# Review

Review is the lane that judges every open pull request at its head commit, turns blocking findings into GitHub issues the worker resolves, and merges on a verified approve. (lands in S4)

## Sub-features

- `review-trigger` reviews each open PR carrying a `Bead:` trailer that has no verdict at its head SHA, once.
- `review-changes` opens one issue labeled `review` per blocking finding and comments on the PR with the links.
- `review-fix` re-reviews a push whose commit message says `addresses #N` with the issue thread in the prompt, and closes the issue on approve.
- `review-approve` squash-merges and closes the bead.
- `review-real` runs the real headless reviewer and records a non-empty verdict detail.
- `review-audit` lists PRs merged without a verdict at their merge SHA.

## How to get to it (user POV)

- Let `smile run` review automatically each tick.
- Run `smile review <pr>` in the stamped repo to review one PR by hand.
- Run `smile audit` to list unreviewed merges.
- Open the `review` issues on GitHub to read findings and the worker's replies.

## Driving it with verify-smile

Preconditions:

- A fixture with `install: stamped` and the stub worker and stub reviewer configured.
- For the changes path, `SMILE_STUB_CHANGES_ONCE=1`.

- **Changes then approve.** Run `verify-smile feature review --runtime bash`. The helper runs the loop with the stub reviewer rejecting once. `gh issue list --label review --state all --json number,state` shows one issue per bead that was first `OPEN` and is now `CLOSED`. Each PR has a comment linking its issue. Both PRs end `MERGED`.
- **Fix round.** The stub worker's fix commit message contains `addresses #<issue>`. The event log has `issue.opened` then `issue.resolved` for that issue number.
- **Real reviewer.** Run `verify-smile feature review --runtime bash --real-review`. One bead runs with the real reviewer. The `review.verdict` event has a non-empty `detail` and, from S7 on, that detail contains a `Principles applied` line.
- **Audit.** Merge a throwaway PR by hand with `gh pr merge`, run `smile audit`. Its number is listed. After the driver reviews and merges normally, `smile audit` prints nothing.
- **Proof.** `~/.smile-verify/<runid>/review.log` holds the issue and PR listings. `factory/events.jsonl` holds the verdict lines.

## Gotchas

- The real reviewer takes minutes. Run it in one lane, never for every bead.
- A verdict at an older head SHA is not a verdict. Assert the SHA in the event matches `gh pr view --json headRefOid`.
- The stub reviewer's counter lives under `.factory/stub/`. A second fixture starts clean.
