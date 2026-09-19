#!/usr/bin/env bash
# S7: the stamped skills. Contract section 13 — every templates/.claude/skills/*/SKILL.md carries
# frontmatter whose `name` equals its directory, and a `description`; no skill names a tool, a
# service, or a home-directory path that does not exist in a target repo; both rendered prompts
# require the `Principles applied:` line. Pure file inspection, no uv, under five seconds.
set -uo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
SKILLS="$ROOT/templates/.claude/skills"
FAILS=0

fail() {
	printf 'not ok: %s\n' "$1"
	FAILS=$((FAILS + 1))
}

# 1. every skill has well-formed frontmatter with a matching name and a description
found=0
for skill in "$SKILLS"/*/SKILL.md; do
	[ -f "$skill" ] || continue
	found=$((found + 1))
	dir=$(basename "$(dirname "$skill")")
	[ "$(head -n 1 "$skill")" = "---" ] || fail "$dir/SKILL.md does not open with a --- frontmatter fence"
	# the frontmatter block: lines between the first --- and the next one
	front=$(awk 'NR==1 && $0=="---" {inside=1; next} inside && $0=="---" {exit} inside' "$skill")
	name=$(printf '%s\n' "$front" | awk -F': *' '/^name:/ {print $2; exit}')
	[ "$name" = "$dir" ] || fail "$dir/SKILL.md frontmatter name is '$name', expected '$dir'"
	printf '%s\n' "$front" | grep -q '^description:' || fail "$dir/SKILL.md frontmatter has no description"
done
[ "$found" -ge 7 ] || fail "expected at least 7 stamped skills, found $found"

# 2. no skill mentions a tool, a service, or a home-directory path from the authoring machine
hits=$(grep -rli "cursor\|discord\|Downloads\|openclaw\|/Users/" "$SKILLS")
[ -z "$hits" ] || fail "forbidden words in: $(printf '%s' "$hits" | tr '\n' ' ')"

# 3. both prompts require the principles line
for p in worker reviewer; do
	grep -q 'Principles applied:' "$ROOT/templates/prompts/$p.md" ||
		fail "templates/prompts/$p.md does not require 'Principles applied:'"
done

if [ "$FAILS" -eq 0 ]; then
	printf 'PASS skills.test.sh (%s skills)\n' "$found"
else
	printf 'FAIL skills.test.sh (%s failures)\n' "$FAILS"
	exit 1
fi
