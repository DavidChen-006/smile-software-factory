# `/smile full` — walk the ladder

Walk the state table top to bottom. For every row whose fact is false, run the
stage it names by loading that stage's skill and following it. Never do the
stage work from this page.

## 1. Read the state

The five checks, exactly as in [status.md](status.md):

```bash
SPEC=$(ls -t docs/*SPEC*.md docs/*DESIGN*.md 2>/dev/null | head -1)
git log -1 -- "$SPEC"; git status --porcelain -- "$SPEC"   # frozen = commit AND empty
grep -q '^## Architecture' "$SPEC"
PRE="docs/$(basename "$SPEC" .md).preflight.md"; test -f "$PRE" && git log -1 -- "$PRE"
SPEC_TS=$(git log -1 --format=%cI -- "$SPEC")
grep '"campaign.start"' .factory/events.jsonl 2>/dev/null | tail -1   # ts newer than $SPEC_TS?
```

## 2. The gate between stages

Before entering each stage, ask exactly one question and wait:

```
Next: <stage>. Continue, skip, or stop?
```

- **continue** — load the stage skill by name (`grilling`, `draftspec`,
  `architect`, `preflight`, `campaign`) and follow it to its end. The interview
  stages talk to the user one question at a time as their own skills say.
- **skip** — append a line `skipped <stage> <reason>` to
  `docs/<spec basename without .md>.ladder.md` (create the file if absent), then
  move to the next row. When no spec exists yet there is nothing to skip past:
  `grilling` is the only skippable stage before the spec, and its line is
  recorded once the spec file has a name.
- **stop** — print the state table as `status` prints it and end the run. Record
  nothing.

Each stage is entered fresh. Nothing is carried from one to the next except the
files the stage left in the repository; re-read the state after every stage
rather than trusting what the previous one said.

## 3. Rows that this page never fixes

**not frozen** — the spec has uncommitted changes or no commit at all. Say so,
name the file, and ask the user to commit it. This skill never commits a spec
and never runs a stage past an unfrozen one.

**architecture** — `architect` appends the `## Architecture` section to the
spec, which makes the spec dirty again; the freeze row is re-checked and the
user commits a second time before `preflight`.

## 4. End

When the campaign row goes true, the campaign skill owns the run from there: its
narration loop, not this page. Say the ladder is walked and stop.
