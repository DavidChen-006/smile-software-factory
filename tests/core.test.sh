#!/usr/bin/env bash
# Drives the stamped smile shim against a scratch git repo, per docs/RUNTIME-CONTRACT.md: doctor
# (all ok, tools missing from a symlink-built PATH, backend variants, read-only), config get, init
# (twice, .worktreeinclude bytes, bd ready), event (byte-exact lines, escapes, rejections, truncation),
# pause and resume with their events, and status (sections, unavailable, raw-line fallback).
set -uo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
TMP=$(cd "$(mktemp -d "${TMPDIR:-/tmp}/smile-core-test.XXXXXX")" && pwd)
trap 'rm -rf "$TMP"' EXIT
FAILS=0

check() {   # check <description> <command...>
	local desc="$1"; shift
	if "$@" >/dev/null 2>&1; then
		printf 'ok   %s\n' "$desc"
	else
		printf 'FAIL %s\n' "$desc"
		FAILS=$((FAILS + 1))
	fi
}

# ---------------------------------------------------------------- scratch repo
REPO="$TMP/Core-Repo.1"   # basename lowercased and filtered gives the bd prefix "co"
mkdir -p "$REPO"
git -C "$REPO" init -q
git -C "$REPO" -c user.email=core@test -c user.name=core commit -q --allow-empty -m init
python3 "$ROOT/install.py" "$REPO" >/dev/null
export SMILE_ROOT="$REPO"
unset SMILE_ACTOR
SMILE="$REPO/smile/smile"
CONFIG="$REPO/smile.config.yaml"
LOG="$REPO/.factory/events.jsonl"
TS_RE='[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z'

in_repo() { (cd "$REPO" && "$@"); }
set_key() { sed -i.bak "s|^$1:.*|$1: $2|" "$CONFIG" && rm -f "$CONFIG.bak"; }   # rewrite one config line
lines() { wc -l < "$LOG" | tr -d ' '; }
last() { tail -1 "$LOG" | sed -E "s/^\{\"ts\":\"$TS_RE\"/{\"ts\":\"TS\"/"; }   # last event, ts normalized

# mkbin <dir> <tool...>: a PATH root holding only what the shim needs plus one stub per named tool.
# Stubs exit $STUB_RC (default 0); doctor only runs gh, so STUB_RC=1 means `gh auth status` failed.
mkbin() {
	local dir="$1" t; shift
	mkdir -p "$dir"
	for t in bash sed dirname; do ln -s "$(command -v "$t")" "$dir/$t"; done
	for t in "$@"; do printf '#!/bin/sh\nexit "${STUB_RC:-0}"\n' > "$dir/$t"; chmod +x "$dir/$t"; done
}
# gh stand-in for status: prints $GH_PRS as the pr list, exits 1 when it is unset
GHBIN="$TMP/bin-gh"; mkdir -p "$GHBIN"
printf '#!/bin/sh\n[ -n "${GH_PRS:-}" ] || exit 1\nprintf "%%s" "$GH_PRS"\n' > "$GHBIN/gh"; chmod +x "$GHBIN/gh"

# ---------------------------------------------------------------- doctor
mkbin "$TMP/bin-all" git gh claude bd treehouse tmux
OUT=$(PATH="$TMP/bin-all" "$SMILE" doctor 2>/dev/null); RC=$?
check "doctor all ok exits 0" test "$RC" -eq 0
check "doctor all ok prints the seven lines in order" test "$OUT" = $'ok git\nok gh\nok gh-auth\nok claude\nok bd\nok treehouse\nok mux tmux'
check "doctor creates nothing" test ! -e "$REPO/.factory"

mkbin "$TMP/bin-no-treehouse" git gh claude bd tmux
OUT=$(PATH="$TMP/bin-no-treehouse" "$SMILE" doctor 2>/dev/null); RC=$?
check "doctor with treehouse missing exits 1" test "$RC" -eq 1
check "doctor names the missing tool on its line" test "$(sed -n 6p <<<"$OUT")" = "missing treehouse not on PATH"
check "doctor still prints seven lines" test "$(wc -l <<<"$OUT" | tr -d ' ')" -eq 7

mkbin "$TMP/bin-no-gh" git claude bd treehouse tmux
OUT=$(PATH="$TMP/bin-no-gh" "$SMILE" doctor 2>/dev/null)
check "doctor without gh fails gh and gh-auth" test "$(sed -n 2,3p <<<"$OUT")" = $'missing gh not on PATH\nmissing gh-auth gh not on PATH'
OUT=$(STUB_RC=1 PATH="$TMP/bin-all" "$SMILE" doctor 2>/dev/null)
check "doctor with gh logged out fails only gh-auth" test "$(sed -n 2,3p <<<"$OUT")" = $'ok gh\nmissing gh-auth gh auth status failed'

mkbin "$TMP/bin-no-mux" git gh claude bd treehouse
OUT=$(PATH="$TMP/bin-no-mux" "$SMILE" doctor 2>/dev/null)
check "doctor without any backend names all three" test "$(sed -n 7p <<<"$OUT")" = "missing mux none of tmux, cmux, herdr on PATH"
set_key backend cmux
OUT=$(PATH="$TMP/bin-all" "$SMILE" doctor 2>/dev/null); RC=$?
check "doctor with backend set to an absent backend fails mux" test "$(sed -n 7p <<<"$OUT")" = "missing mux cmux not on PATH"
check "doctor with backend absent exits 1" test "$RC" -eq 1
mkbin "$TMP/bin-cmux" git gh claude bd treehouse tmux cmux
OUT=$(PATH="$TMP/bin-cmux" "$SMILE" doctor 2>/dev/null)
check "doctor honors backend over the detect order" test "$(sed -n 7p <<<"$OUT")" = "ok mux cmux"
set_key backend screen
OUT=$(PATH="$TMP/bin-all" "$SMILE" doctor 2>/dev/null); RC=$?
check "doctor with an unknown backend names it" test "$(sed -n 7p <<<"$OUT")" = "missing mux unknown backend screen"
check "doctor with an unknown backend exits 1" test "$RC" -eq 1
set_key backend ""

# ---------------------------------------------------------------- config get
check "config get returns a file value" test "$("$SMILE" config get worker.model)" = opus
check "config get prints an empty line for an empty value" test "$("$SMILE" config get backend; printf x)" = $'\nx'
sed -i.bak '/^max_parallel:/d' "$CONFIG" && rm -f "$CONFIG.bak"
check "config get returns the default for an absent key" test "$("$SMILE" config get max_parallel)" = 3
OUT=$("$SMILE" config get no.such.key 2>/dev/null); RC=$?
check "config get with an unknown key exits 3" test "$RC" -eq 3
check "config get with an unknown key prints nothing" test -z "$OUT"
"$SMILE" config get >/dev/null 2>&1; check "config get without a key exits 2" test $? -eq 2
"$SMILE" config >/dev/null 2>&1; check "config without get exits 2" test $? -eq 2
cp "$CONFIG" "$TMP/config.orig"
printf '# comment\nmerge:\t human \t\r\n merge: indented\nmerge: second\nbase_branch:dev\n' > "$CONFIG"
check "config get trims space, tab, and CR and takes the first key" test "$("$SMILE" config get merge)" = human
check "config get needs no space after the colon" test "$("$SMILE" config get base_branch)" = dev
cp "$TMP/config.orig" "$CONFIG"

# ---------------------------------------------------------------- init
OUT=$("$SMILE" init 2>/dev/null); RC=$?
check "init exits 0" test "$RC" -eq 0
check "init prints five created lines in order" test "$OUT" = $'created .beads\ncreated treehouse.toml\ncreated .worktreeinclude\ncreated .factory\ncreated .factory/events.jsonl'
check ".worktreeinclude bytes are exact" test "$(cat "$REPO/.worktreeinclude"; printf x)" = $'.env\nsmile.config.yaml\nx'
check "events.jsonl is created empty" test ! -s "$LOG"
check "bd ready works after init" in_repo bd ready
ID=$(in_repo bd create "probe bead" --silent 2>/dev/null)
check "init derives the bd prefix from the basename" test "${ID%%-*}" = co
OUT=$("$SMILE" init 2>/dev/null)
check "second init prints five exists lines" test "$OUT" = $'exists .beads\nexists treehouse.toml\nexists .worktreeinclude\nexists .factory\nexists .factory/events.jsonl'
check "init appends no event" test ! -s "$LOG"

# ---------------------------------------------------------------- event
# trunc_len <detail>: byte length, newline included, of the line an event with that detail appends
trunc_len() { "$SMILE" event campaign.start "detail=$1" && tail -1 "$LOG" | wc -c | tr -d ' '; }
LONGX=$(printf 'x%.0s' $(seq 1 5000)); LONGT=$(printf '\t%.0s' $(seq 1 5000)); LONGE=$(printf 'é%.0s' $(seq 1 3000))
check "event cuts a 5000 x detail to a line of exactly 4096 bytes" test "$(trunc_len "$LONGX")" = 4096
check "event cuts 5000 tabs (2 bytes each escaped) to 4095 bytes" test "$(trunc_len "$LONGT")" = 4095
check "event cuts 3000 é (2 bytes each) to 4095 bytes without splitting one" test "$(trunc_len "$LONGE")" = 4095
export LC_ALL=C
check "event cuts 5000 x the same under LC_ALL=C" test "$(trunc_len "$LONGX")" = 4096
check "event cuts 3000 é the same under LC_ALL=C" test "$(trunc_len "$LONGE")" = 4095
check "event output under LC_ALL=C is valid UTF-8" python3 -c 'import sys; sys.stdin.buffer.read().decode()' < "$LOG"
unset LC_ALL
"$SMILE" event bead.claimed bead=sv-1 actor=driver detail='tick 3'; RC=$?
check "event exits 0" test "$RC" -eq 0
check "event ts is UTC to the second with a Z suffix" test "$(tail -1 "$LOG" | grep -Ec "^\{\"ts\":\"$TS_RE\",")" -eq 1
check "event line matches the contract example byte for byte" test "$(last)" = '{"ts":"TS","event":"bead.claimed","bead":"sv-1","pr":null,"sha":null,"actor":"driver","detail":"tick 3"}'
"$SMILE" event pr.opened bead=sv-1 pr=7 sha=abc123
check "event writes pr as a bare integer" test "$(last)" = '{"ts":"TS","event":"pr.opened","bead":"sv-1","pr":7,"sha":"abc123","actor":null,"detail":null}'
"$SMILE" event bead.closed detail=
check "event writes an empty detail as an empty string" test "$(last)" = '{"ts":"TS","event":"bead.closed","bead":null,"pr":null,"sha":null,"actor":null,"detail":""}'
"$SMILE" event review.verdict detail=$'a"b\\c\td\ne\x01f café/\x7f'
check "event escapes quote, backslash, tab, newline, and a control char; not slash, DEL, or café" \
	test "$(last)" = $'{"ts":"TS","event":"review.verdict","bead":null,"pr":null,"sha":null,"actor":null,"detail":"a\\"b\\\\c\\td\\ne\\u0001f café/\x7f"}'
N=$(lines)
reject() { "$SMILE" event "$@" >/dev/null 2>&1; test $? -eq 2; }
check "event rejects an unknown name" reject nope bead=sv-1
check "event rejects two names in one argument" reject 'bead.claimed worktree.acquired'
check "event rejects a non-integer pr" reject pr.opened pr=x
check "event rejects pr with a leading zero" reject pr.opened pr=07
check "event rejects an empty pr" reject pr.opened pr=
check "event rejects a duplicate key" reject pr.opened bead=a bead=b
check "event rejects an unknown key" reject pr.opened ts=now
check "event rejects an argument without =" reject pr.opened bead
check "event without a name exits 2" reject
check "rejected events append nothing" test "$(lines)" -eq "$N"

# ---------------------------------------------------------------- pause and resume
OUT=$("$SMILE" pause); check "pause prints paused" test "$OUT" = paused
check "pause creates .factory/pause" test -f "$REPO/.factory/pause"
check "pause logs driver.paused with actor human" test "$(last)" = '{"ts":"TS","event":"driver.paused","bead":null,"pr":null,"sha":null,"actor":"human","detail":null}'
N=$(lines)
OUT=$("$SMILE" pause); check "second pause prints already paused" test "$OUT" = "already paused"
check "second pause logs nothing" test "$(lines)" -eq "$N"
OUT=$(SMILE_ACTOR=watchtower "$SMILE" resume); check "resume prints resumed" test "$OUT" = resumed
check "resume removes .factory/pause" test ! -e "$REPO/.factory/pause"
check "resume logs driver.resumed with actor from SMILE_ACTOR" test "$(last)" = '{"ts":"TS","event":"driver.resumed","bead":null,"pr":null,"sha":null,"actor":"watchtower","detail":null}'
N=$(lines)
OUT=$("$SMILE" resume); check "second resume prints not paused" test "$OUT" = "not paused"
check "second resume logs nothing" test "$(lines)" -eq "$N"

# ---------------------------------------------------------------- status
in_repo bd create "second bead" --silent >/dev/null 2>&1
in_repo bd close "$ID" >/dev/null 2>&1
for i in 1 2 3; do "$SMILE" event campaign.start detail=$'x\ty'; done
printf 'not json' >> "$LOG"   # corrupt last line, no trailing newline
OUT=$(GH_PRS='[{"number":7},{"number":9}]' PATH="$GHBIN:$PATH" "$SMILE" status 2>/dev/null | sed -E "s/^  $TS_RE /  TS /"); RC=$?
check "status exits 0" test "$RC" -eq 0
check "status renders beads sorted, the pr count, and the last ten events with - for null and raw fallback" \
	test "$OUT" = $'beads:\n  closed 1\n  open 1\nprs:\n  open 2\nevents:\n  TS bead.claimed sv-1 - tick 3\n  TS pr.opened sv-1 7 -\n  TS bead.closed - - \n  TS review.verdict - - a"b\\c d e\x01f café/\x7f\n  TS driver.paused - - -\n  TS driver.resumed - - -\n  TS campaign.start - - x y\n  TS campaign.start - - x y\n  TS campaign.start - - x y\n  not json'
# bd stand-in: prints $BD_OUT as the list and exits 0, so status sees well-formed and malformed JSON
BDBIN="$TMP/bin-bd"; mkdir -p "$BDBIN"
printf '#!/bin/sh\nprintf "%%s" "$BD_OUT"\n' > "$BDBIN/bd"; chmod +x "$BDBIN/bd"
OUT=$(BD_OUT='[{"status":5}]' PATH="$BDBIN:$GHBIN:$PATH" "$SMILE" status 2>/dev/null | sed -n 1,2p); RC=$?
check "status with a non-string bead status prints unavailable and exits 0" test "$RC" -eq 0 -a "$OUT" = $'beads:\n  unavailable'
OUT=$(BD_OUT='nope' PATH="$BDBIN:$GHBIN:$PATH" "$SMILE" status 2>/dev/null | sed -n 1,2p); RC=$?
check "status with non-JSON from bd prints unavailable and exits 0" test "$RC" -eq 0 -a "$OUT" = $'beads:\n  unavailable'

# ---------------------------------------------------------------- pause under contention
printf '\n' >> "$LOG"   # end the corrupt line so the next event starts on its own line
SMILE_ACTOR= "$SMILE" pause >/dev/null
check "pause with SMILE_ACTOR set but empty logs actor human" test "$(last)" = '{"ts":"TS","event":"driver.paused","bead":null,"pr":null,"sha":null,"actor":"human","detail":null}'
"$SMILE" resume >/dev/null
N=$(lines)
for i in $(seq 1 20); do "$SMILE" pause >> "$TMP/pause.out" & done; wait
check "20 concurrent pauses print paused exactly once" test "$(grep -cx paused "$TMP/pause.out")" -eq 1
check "20 concurrent pauses print already paused 19 times" test "$(grep -cx 'already paused' "$TMP/pause.out")" -eq 19
check "20 concurrent pauses log exactly one event" test "$(lines)" -eq $((N + 1))

rm -rf "$REPO/.beads" "$REPO/.factory"
OUT=$(PATH="$GHBIN:$PATH" "$SMILE" status 2>/dev/null); RC=$?
check "status without .beads, gh, or a log exits 0" test "$RC" -eq 0
check "status prints unavailable for beads and prs and the bare events heading" test "$OUT" = $'beads:\n  unavailable\nprs:\n  unavailable\nevents:'

if [ "$FAILS" -eq 0 ]; then
	printf 'PASS core.test.sh\n'
else
	printf 'FAIL core.test.sh: %s failure(s)\n' "$FAILS"
	exit 1
fi
