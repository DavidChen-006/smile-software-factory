# `/smile status` — where the repo stands

Read-only. Nothing is created, nothing is started.

## The five checks

Run them from the main checkout, in this order, and keep each answer.

```bash
SPEC=$(ls -t docs/*SPEC*.md docs/*DESIGN*.md 2>/dev/null | head -1)   # newest by mtime
[ -n "$SPEC" ] || echo "no spec"

git log -1 -- "$SPEC"                    # a commit printed means it was committed
git status --porcelain -- "$SPEC"        # empty output means the working copy is unchanged
                                         # frozen = both: a commit AND empty porcelain

grep -q '^## Architecture' "$SPEC"       # exit 0 means the architecture section is there

PRE="docs/$(basename "$SPEC" .md).preflight.md"
test -f "$PRE" && git log -1 -- "$PRE"   # exists and committed

# campaign: a campaign.start newer than the spec's last commit
SPEC_TS=$(git log -1 --format=%cI -- "$SPEC")
grep '"campaign.start"' .factory/events.jsonl 2>/dev/null | tail -1
# compare its ts field with $SPEC_TS; newer means a campaign already ran for this spec
```

## Print

One line per row of the state table in the parent skill, each with a tick or a
cross and the fact that decided it:

```
[x] spec          docs/FOO-DESIGN.md
[x] frozen        3c43b99, working copy clean
[ ] architecture  no ## Architecture heading
[ ] preflight     docs/FOO-DESIGN.preflight.md missing
[ ] campaign      no campaign.start after 2026-09-19T10:00:00
```

Then run `smile/smile status` and relay its output unchanged. Then stop: do not
offer to fix a cross, and do not run the stage the first cross names. The user
asked where things stand, not for a run.
