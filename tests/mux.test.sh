#!/usr/bin/env bash
# Drives the stamped smile shim's mux seam against a real tmux server, per
# docs/RUNTIME-CONTRACT.md section 7: spawn (handle shape, window name, cwd, argv with a space, a
# lone word, a session name tmux would rewrite, ten at once), alive (running, exited, killed),
# kill (idempotent), handle and usage rejections, backend selection, and the exact stderr line
# each fixed failure prints.
#
# Every session this file opens is named by SMILE_MUX_SESSION or derived from it, and the exit
# trap kills each one it created. It never touches a session it did not open.
set -uo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
TMP=$(cd "$(mktemp -d "${TMPDIR:-/tmp}/smile-mux-test.XXXXXX")" && pwd)
export SMILE_MUX_SESSION="smile-test-$$"
SESSIONS="$SMILE_MUX_SESSION"
cleanup() {
	local s
	for s in $SESSIONS; do tmux kill-session -t "=$s" >/dev/null 2>&1; done
	rm -rf "$TMP"
}
trap cleanup EXIT
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

command -v tmux >/dev/null 2>&1 || { printf 'FAIL mux.test.sh: tmux not on PATH\n'; exit 1; }

# ---------------------------------------------------------------- scratch repo
REPO="$TMP/mux-repo"
mkdir -p "$REPO"
git -C "$REPO" init -q
git -C "$REPO" -c user.email=mux@test -c user.name=mux commit -q --allow-empty -m init
python3 "$ROOT/install.py" "$REPO" >/dev/null
SMILE="$REPO/smile/smile"
CONFIG="$REPO/smile.config.yaml"
WORK="$TMP/work"; mkdir -p "$WORK"
WORK_REAL=$(cd "$WORK" && pwd -P)
set_key() { sed -i.bak "s|^$1:.*|$1: $2|" "$CONFIG" && rm -f "$CONFIG.bak"; }

rc_of() { "$@" >/dev/null 2>&1; printf '%s' "$?"; }              # exit code of a command
stderr_of() { "$@" 2>&1 >/dev/null; }                            # its stderr alone
nlines() { printf '%s' "$1" | grep -c ''; }                      # lines in a string, 0 when empty
win_target() { printf '%s' "${1#tmux:}"; }                       # handle -> tmux <session>:<window_id>
windows() { tmux list-windows -t "=$1" -F '#{window_id}' 2>/dev/null; }
has_window() { grep -qxF "$2" <<<"$(windows "$1")"; }
MISSING_TMUX='smile mux: missing tmux not on PATH'

# poll_gone <handle>: wait up to ~5s for alive to report exactly 1 (gone), never another code
poll_gone() {
	local i=0 rc
	while [ "$i" -lt 50 ]; do
		rc=$(rc_of "$SMILE" mux alive "$1")
		[ "$rc" -eq 1 ] && return 0
		[ "$rc" -eq 0 ] || return 1
		sleep 0.1
		i=$((i + 1))
	done
	return 1
}

# ---------------------------------------------------------------- spawn
H=$("$SMILE" mux spawn w1 "$WORK" sleep 300); SPAWN_RC=$?
check "spawn exits 0" test "$SPAWN_RC" -eq 0
check "spawn prints a well-formed handle" grep -qE '^tmux:[^ :]+:@[0-9]+$' <<<"$H"
check "spawn prints exactly one line" test "$(nlines "$H")" -eq 1
check "spawn names the handle's session after SMILE_MUX_SESSION" test "$H" != "${H#tmux:$SMILE_MUX_SESSION:}"
check "spawn opens the window in that session" has_window "$SMILE_MUX_SESSION" "${H##*:}"
check "spawn labels the window with <name>" \
	test "$(tmux display -p -t "$(win_target "$H")" '#{window_name}')" = w1
check "spawn runs the command in <cwd>" \
	test "$(tmux display -p -t "$(win_target "$H")" '#{pane_current_path}')" = "$WORK_REAL"
check "spawn leaves remain-on-exit off" \
	test "$(tmux show-window-options -t "$(win_target "$H")" -v remain-on-exit)" = off

# ---------------------------------------------------------------- alive and kill
check "alive exits 0 for a running command" "$SMILE" mux alive "$H"
check "kill exits 0" "$SMILE" mux kill "$H"
check "kill removes the window from tmux" test "$(rc_of has_window "$SMILE_MUX_SESSION" "${H##*:}")" -eq 1
check "alive exits 1 after kill" test "$(rc_of "$SMILE" mux alive "$H")" -eq 1
check "a second kill on a gone handle exits 0" "$SMILE" mux kill "$H"
check "a third kill is still 0" "$SMILE" mux kill "$H"

HT=$("$SMILE" mux spawn short "$WORK" true)
check "alive exits 1 once the command has exited" poll_gone "$HT"

# ---------------------------------------------------------------- argv, not a shell string
HS=$("$SMILE" mux spawn spaced "$WORK" sh -c 'printf "%s" "$1" > out.txt' _ 'a b')
poll_gone "$HS"
check "an argument containing a space reaches the command intact" test "$(cat "$WORK/out.txt")" = 'a b'

HL=$("$SMILE" mux spawn lone "$WORK" 'no such program'); LONE_RC=$?
check "a lone-word command spawns" test "$LONE_RC" -eq 0
check "a lone word with a space is a program name, not a shell string" poll_gone "$HL"

HE=$("$SMILE" mux spawn echoer "$WORK" true)
check "a lone-word command that exists still runs" test "$(rc_of poll_gone "$HE")" -eq 0

# ---------------------------------------------------------------- session names tmux rewrites
CTRL=$("$SMILE" mux spawn ctrl "$WORK" sleep 300)     # the control window, must survive to the end
for raw in "$SMILE_MUX_SESSION.dot" "$SMILE_MUX_SESSION sp"; do
	clean=${raw//[[:space:].:]/_}
	SESSIONS="$SESSIONS $clean"
	HD=$(SMILE_MUX_SESSION="$raw" "$SMILE" mux spawn dotted "$WORK" sleep 300)
	check "a session name with '.' or ' ' spawns" test -n "$HD"
	check "the handle carries the name tmux reports ($clean)" test "$HD" = "tmux:$clean:${HD##*:}"
	check "that handle has no space" test "$HD" = "${HD// /}"
	check "alive resolves that handle" "$SMILE" mux alive "$HD"
	check "kill resolves that handle" "$SMILE" mux kill "$HD"
	check "alive exits 1 after that kill" test "$(rc_of "$SMILE" mux alive "$HD")" -eq 1
done

# ---------------------------------------------------------------- handle rejections
for h in nope tmux: cmux:x:y 'tmux:a b' '../lib/config:x:@1' 'TMUX:a:@1' \
	"tmux:$SMILE_MUX_SESSION:@1:extra" "tmux:$SMILE_MUX_SESSION:notawindow" "tmux:$SMILE_MUX_SESSION:"; do
	check "alive rejects the handle '$h' with exit 2" test "$(rc_of "$SMILE" mux alive "$h")" -eq 2
	check "kill rejects the handle '$h' with exit 2" test "$(rc_of "$SMILE" mux kill "$h")" -eq 2
	check "the rejection of '$h' is one stderr line" test "$(nlines "$(stderr_of "$SMILE" mux alive "$h")")" -eq 1
done
check "a rejected handle kills nothing" "$SMILE" mux alive "$CTRL"
check "an S8 backend with no file names it" \
	test "$(stderr_of "$SMILE" mux alive cmux:x:y)" = 'smile mux: unknown backend cmux'
check "a backend name that is a path names it" \
	test "$(stderr_of "$SMILE" mux alive '../lib/config:x:@1')" = 'smile mux: unknown backend ../lib/config'
check "a malformed handle names itself" \
	test "$(stderr_of "$SMILE" mux alive nope)" = 'smile mux: malformed handle nope'
check "a rest with a trailing colon is malformed" \
	test "$(stderr_of "$SMILE" mux alive "tmux:$SMILE_MUX_SESSION:")" = "smile mux: malformed handle tmux:$SMILE_MUX_SESSION:"

# ---------------------------------------------------------------- spawn failures
check "spawn with a missing cwd exits 1" test "$(rc_of "$SMILE" mux spawn w "$TMP/absent" true)" -eq 1
check "spawn with a missing cwd prints one stderr line" \
	test "$(nlines "$(stderr_of "$SMILE" mux spawn w "$TMP/absent" true)")" -eq 1

# ---------------------------------------------------------------- ten at once
CONC="$SMILE_MUX_SESSION-conc"
SESSIONS="$SESSIONS $CONC"
i=0
while [ "$i" -lt 10 ]; do
	( SMILE_MUX_SESSION="$CONC" "$SMILE" mux spawn "c$i" "$WORK" sleep 300 > "$TMP/conc.$i" 2>"$TMP/conc.$i.err" \
		|| printf 'rc=%s\n' "$?" >> "$TMP/conc.$i" ) &
	i=$((i + 1))
done
wait
CONC_OUT=$(cat "$TMP"/conc.[0-9])
check "ten concurrent spawns each print one handle" test "$(nlines "$CONC_OUT")" -eq 10
check "ten concurrent spawns all succeeded" test "$(grep -c '^tmux:' <<<"$CONC_OUT")" -eq 10
check "the ten handles are distinct" test "$(sort -u <<<"$CONC_OUT" | grep -c '')" -eq 10
check "the session lists ten windows" test "$(windows "$CONC" | grep -c '')" -eq 10

# ---------------------------------------------------------------- backend selection
H2=$("$SMILE" mux spawn auto "$WORK" sleep 300)
check "auto-detect picks tmux when backend is empty" grep -q '^tmux:' <<<"$H2"
"$SMILE" mux kill "$H2" >/dev/null 2>&1

set_key backend screen
check "a backend outside the three names exits 2" test "$(rc_of "$SMILE" mux spawn w "$WORK" true)" -eq 2
check "it names the unknown backend" \
	test "$(stderr_of "$SMILE" mux spawn w "$WORK" true)" = 'smile mux: unknown backend screen'
set_key backend cmux
check "a config backend whose file has not landed exits 2" test "$(rc_of "$SMILE" mux spawn w "$WORK" true)" -eq 2
set_key backend tmux
H3=$("$SMILE" mux spawn named "$WORK" sleep 300)
check "an explicit tmux backend spawns" grep -q '^tmux:' <<<"$H3"
"$SMILE" mux kill "$H3" >/dev/null 2>&1
set_key backend ""

# ---------------------------------------------------------------- tmux off PATH
# A PATH holding only what the shim and mux need, and no multiplexer.
BIN="$TMP/bin-no-tmux"; mkdir -p "$BIN"
for t in bash sed dirname basename grep; do ln -sf "$(command -v "$t")" "$BIN/$t"; done
check "no backend on PATH makes spawn exit 1" test "$(PATH="$BIN"; rc_of "$SMILE" mux spawn w "$WORK" true)" -eq 1
check "no backend on PATH says which are missing" \
	test "$(PATH="$BIN"; stderr_of "$SMILE" mux spawn w "$WORK" true)" = 'smile mux: missing backend, none of tmux, cmux, herdr on PATH'
set_key backend tmux
check "a named backend missing from PATH makes spawn exit 1" test "$(PATH="$BIN"; rc_of "$SMILE" mux spawn w "$WORK" true)" -eq 1
check "spawn without tmux prints the missing line" \
	test "$(PATH="$BIN"; stderr_of "$SMILE" mux spawn w "$WORK" true)" = "$MISSING_TMUX"
check "alive without tmux exits 1" test "$(PATH="$BIN"; rc_of "$SMILE" mux alive "$CTRL")" -eq 1
check "alive without tmux prints the missing line" \
	test "$(PATH="$BIN"; stderr_of "$SMILE" mux alive "$CTRL")" = "$MISSING_TMUX"
check "kill without tmux exits 1" test "$(PATH="$BIN"; rc_of "$SMILE" mux kill "$CTRL")" -eq 1
check "kill without tmux prints the missing line" \
	test "$(PATH="$BIN"; stderr_of "$SMILE" mux kill "$CTRL")" = "$MISSING_TMUX"
check "kill without tmux killed nothing" "$SMILE" mux alive "$CTRL"
set_key backend ""

# ---------------------------------------------------------------- usage
check "no verb exits 2" test "$(rc_of "$SMILE" mux)" -eq 2
check "an unknown verb exits 2" test "$(rc_of "$SMILE" mux wiggle)" -eq 2
check "spawn without a command exits 2" test "$(rc_of "$SMILE" mux spawn w "$WORK")" -eq 2
check "alive without a handle exits 2" test "$(rc_of "$SMILE" mux alive)" -eq 2
check "alive with two handles exits 2" test "$(rc_of "$SMILE" mux alive a b)" -eq 2
check "kill without a handle exits 2" test "$(rc_of "$SMILE" mux kill)" -eq 2

# ---------------------------------------------------------------- session default
SESSIONS="$SESSIONS smile-mux-repo"
H4=$(SMILE_MUX_SESSION= "$SMILE" mux spawn dflt "$WORK" sleep 300)
check "an empty SMILE_MUX_SESSION falls back to smile-<basename of SMILE_ROOT>" \
	grep -qE '^tmux:smile-mux-repo:@[0-9]+$' <<<"$H4"
"$SMILE" mux kill "$H4" >/dev/null 2>&1

check "the control window survived every rejection" "$SMILE" mux alive "$CTRL"
"$SMILE" mux kill "$CTRL" >/dev/null 2>&1

if [ "$FAILS" -eq 0 ]; then
	printf 'PASS mux.test.sh\n'
else
	printf 'FAIL mux.test.sh: %s failure(s)\n' "$FAILS"
	exit 1
fi
