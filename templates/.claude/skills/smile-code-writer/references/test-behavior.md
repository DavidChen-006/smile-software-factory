# Test behaviour

Name: `test-behavior`.

A test earns its place by failing when the behaviour breaks and by surviving every refactor that
keeps the behaviour. A test coupled to how the code is written fails on both counts: it goes red on
a rename and stays green on a real regression.

## The rules

1. **Test observable behaviour through the public surface.** Call the module the way a caller calls
   it and assert on what the caller can see: the return value, the raised error, the file written,
   the event emitted. Never reach through to a private function, an internal attribute, or a
   module-level variable to make an assertion possible.
2. **One behaviour per test.** One arrange, one act, one claim, and a name that states the claim in
   plain language. When a test needs the word "and" to describe it, it is two tests.
3. **No tests of implementation details.** Call counts, the order of internal helpers, the exact
   shape of an intermediate structure, and the presence of a named private method are not
   behaviour. If the only way to break a test is to rewrite working code, delete the test.
4. **Fakes at process boundaries only.** Fake the network, the clock, the filesystem when it is slow
   or shared, and the external command — the things you do not own. Faking your own module tests
   the interaction you imagined instead of the outcome you need.
5. **See it fail for the right reason.** Write the assertion before the code, watch it go red, and
   read the failure message. An assertion that passes on empty or wrong output proves nothing; that
   is itself a finding in review.
6. **Expected values come from an independent source.** The spec, a worked example, a known-good
   literal. Never recompute the expected value the same way the code computes it.
7. **Never weaken a test to make it pass.** Fix the code, or change the test because the behaviour
   was genuinely respecified — and say which.

## Scope

Give each behaviour the smallest scope that can verify it: in-process and deterministic by default,
a real seam only when the claim lives at the seam, the assembled system only for what nothing
smaller can prove.
