# Laziness protocol

Name: `laziness-protocol`.

The smallest complete change that satisfies the order. Complete is the hard word: laziness is not an
excuse for a half-change that leaves the caller broken or the test suite red.

## The rules

1. **Do the smallest complete change.** Solve the problem that was asked, all the way, and stop.
   Fewer changed lines is the tiebreaker between two correct designs, never a reason to ship a
   partial one.
2. **No speculative abstraction.** An interface, a base class, a plugin point, or a configuration
   knob with exactly one caller is not an abstraction; it is indirection. Write the concrete thing.
   Abstract on the second real caller, not on the imagined one.
3. **No unrequested features.** Extra flags, extra endpoints, extra "while I was in there"
   improvements, and error handling for cases that cannot happen all widen the diff and the review.
   If you think something else is needed, say so in the pull request body; do not build it.
4. **Touch only what you must.** Do not reformat, rename, or restructure code adjacent to your
   change. Match the surrounding style even where you would have chosen differently. Pre-existing
   dead code gets mentioned, not deleted.
5. **Remove what your change orphans.** An import, a helper, a branch, a constant, or a test that
   only your change made unused goes in the same commit. Cleaning up after yourself is not scope
   creep; cleaning up after someone else is.

## The test

Every changed line traces to a sentence in the order or the spec. A line you cannot trace is either
a finding waiting to happen or a thing to say out loud rather than commit.
