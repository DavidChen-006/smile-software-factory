# Audit

Audit lists the factory pull requests that were merged without an `APPROVE` verdict at the commit that was merged. It is the after-the-fact check that nothing slipped past the review lane.

## Sub-features

- `audit-clean` prints nothing and exits 0 when every merged factory PR has an `APPROVE` verdict at its head SHA.
- `audit-unreviewed` prints one line `#<n> <headRefOid> <bead>` per merged factory PR with no such verdict, ascending by number.
- `audit-sha` treats a verdict at an older head SHA as no verdict, so a PR approved and then force-pushed before merge is reported.
- `audit-args` rejects extra arguments with exit 2.

## How to get to it (user POV)

- Run `smile audit` in the stamped repo, usually at the end of a campaign.
- Read it as the campaign's closing check: a clean campaign prints nothing.

## Driving it with verify-smile

Preconditions:

- A fixture with `install: stamped` that has driven at least one bead through the review lane to a merge.

- **Clean.** After a full lane run (see [review](./review.md)), `verify-smile time audit --n 1` prints the command's exit and stdout. A campaign the lane merged itself prints an empty `stdout` and `"exit": 0`.
- **Unreviewed merge.** Stage one by hand: with a fixture whose worker has opened a PR that has no verdict yet, merge it yourself, `gh pr merge <n> --squash` in the fixture. Then `verify-smile time audit --n 1` lists that PR.
- **Bad arguments.** `verify-smile time audit extra --n 1` prints `"exit": 2`.

## Evidence that proves it

- For a clean campaign: `verify-smile time audit --n 1` printing `{"argv": ["audit"], "exit": 0, "stdout": []}`, paired with `verify-smile prs` showing those same PRs `MERGED`, so the empty output is a real answer about real merges and not an empty repo.
- For a staged unreviewed merge: a `stdout` line `#<n> <sha> <bead>` whose `<n>` matches the PR you merged by hand in `verify-smile prs`, and whose `<sha>` matches that PR's head.
- `verify-smile events --bead <id>` for the reported bead holds no `review.verdict` with `detail` `APPROVE` at that `sha`, which is exactly what audit claims.
- The extra-argument case: `"exit": 2` with an empty `stdout`.

## Gotchas

- Audit reads the event log, so it only knows about merges in the same repo's `.factory/`. A fixture torn down and a new one raised starts blank.
- A verdict at an older head SHA does not count. That is the point: comparing to `headRefOid` is what makes a force-push before merge visible.
- Audit has no live box of its own in the spec; `tests/test_review.py` covers the SHA filter and the argument rejection. Driving it live is worth doing anyway, because a clean campaign's empty output is the strongest single proof the lane merged nothing unreviewed.
- An empty output is indistinguishable from a broken audit unless you also show the merged PRs. Always paste `prs` next to it.
