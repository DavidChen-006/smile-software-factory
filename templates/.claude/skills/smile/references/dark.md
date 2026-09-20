# `/smile dark` — frozen spec to campaign, no questions

The unattended path. No interviews, no architect, no graph approval. It still
refuses without a frozen spec: the freeze is the only gate the factory enforces
and `dark` does not lift it.

## 1. Require a frozen spec

```bash
SPEC=$(ls -t docs/*SPEC*.md docs/*DESIGN*.md 2>/dev/null | head -1)
git log -1 -- "$SPEC"              # must print a commit
git status --porcelain -- "$SPEC"  # must print nothing
```

If there is no spec, or `git log -1` prints nothing, or the porcelain output is
non-empty, print exactly one line and stop:

```
dark needs a frozen spec in docs/
```

Do not commit the spec, do not start an interview, do not offer to write one.

## 2. Skip the interviews and the architect

`grilling`, `draftspec`, and `architect` are not run in `dark`, whether or not
the spec has a `## Architecture` heading. Nothing is recorded in the ladder file
for them: `dark` is a mode, not a skipped stage.

## 3. Preflight, only when its file is missing

```bash
PRE="docs/$(basename "$SPEC" .md).preflight.md"
test -f "$PRE" || echo "preflight needed"
```

When the file is missing, load the `preflight` skill and follow it, with `$PRE`
as the notepad path it writes. When the file is there, move on without reading
it.

## 4. Campaign in dark mode

Check whether a campaign already ran for this spec:

```bash
SPEC_TS=$(git log -1 --format=%cI -- "$SPEC")
grep '"campaign.start"' .factory/events.jsonl 2>/dev/null | tail -1
```

A `campaign.start` whose `ts` is newer than `$SPEC_TS` means this spec already
has a campaign: say so and stop rather than starting a second one.

Otherwise load the `campaign` skill and follow it **in `dark` mode**: tell it
`dark` as you enter. It prints the bead graph and creates the beads without
waiting for approval, and everything else in that skill is unchanged — the
preflight refusals, the carve law, the work-order rules, ignition, and the
narration loop.

## 5. Narrate

From ignition on, the campaign skill's narration loop owns the run: `smile
narrate` on every wake, escalations relayed first. An escalation still parks the
campaign and still needs the user's ruling; `dark` pre-approves the graph, not
the escalations.
