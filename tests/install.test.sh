#!/usr/bin/env bash
# Exercises install.py against a temp directory: first stamp, idempotent second run, drift
# refusal, --force replacement, and the .gitignore line. Also drives the stamped smile shim's
# dispatch and error paths with a throwaway bash command.
set -uo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
INSTALL="$ROOT/install.py"
# cd && pwd normalizes the path (macOS TMPDIR ends in a slash) so it compares equal to SMILE_ROOT
TARGET=$(cd "$(mktemp -d "${TMPDIR:-/tmp}/smile-install-test.XXXXXX")" && pwd)
trap 'rm -rf "$TARGET"' EXIT
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

TEMPLATE_FILES=$(cd "$ROOT/templates" && find . -type f ! -name .DS_Store ! -path '*/__pycache__/*' | sed 's|^\./||' | sort)
N=$(printf '%s\n' "$TEMPLATE_FILES" | wc -l | tr -d ' ')

# ---------------------------------------------------------------- first stamp
OUT=$(python3 "$INSTALL" "$TARGET" 2>&1); RC=$?
check "first stamp exits 0" test "$RC" -eq 0
check "first stamp prints stamped per template file" test "$(grep -c '^stamped ' <<<"$OUT")" -eq "$N"
check "first stamp appends .gitignore" grep -qx 'appended .gitignore' <<<"$OUT"
check "first stamp prints exactly one line per file plus .gitignore" test "$(wc -l <<<"$OUT" | tr -d ' ')" -eq $((N + 1))
check "every template file exists in target" bash -c 'for f in $1; do [ -f "$2/$f" ] || exit 1; done' _ "$TEMPLATE_FILES" "$TARGET"
check "smile/smile is executable" test -x "$TARGET/smile/smile"
check "smile.config.yaml is byte-identical" cmp -s "$ROOT/templates/smile.config.yaml" "$TARGET/smile.config.yaml"
check ".gitignore holds .factory/" grep -qx '.factory/' "$TARGET/.gitignore"

# ---------------------------------------------------------------- second run
OUT=$(python3 "$INSTALL" "$TARGET" 2>&1); RC=$?
check "second run exits 0" test "$RC" -eq 0
check "second run prints unchanged per template file" test "$(grep -c '^unchanged ' <<<"$OUT")" -eq $((N + 1))
check "second run prints nothing else" test "$(grep -vc '^unchanged ' <<<"$OUT")" -eq 0
check ".gitignore line added once" test "$(grep -cx '.factory/' "$TARGET/.gitignore")" -eq 1

# ---------------------------------------------------------------- drift
printf '# local edit\n' >> "$TARGET/smile.config.yaml"
OUT=$(python3 "$INSTALL" "$TARGET" 2>&1); RC=$?
check "drift run exits 1" test "$RC" -eq 1
check "drift run names the file and the flag" grep -qx 'drifted smile.config.yaml, use --force' <<<"$OUT"
check "drift run leaves the edit in place" grep -q '# local edit' "$TARGET/smile.config.yaml"
check "drift run reports the other files unchanged" test "$(grep -c '^unchanged ' <<<"$OUT")" -eq "$N"

# ---------------------------------------------------------------- force
OUT=$(python3 "$INSTALL" "$TARGET" --force 2>&1); RC=$?
check "force run exits 0" test "$RC" -eq 0
check "force run prints replaced for the drifted file" grep -qx 'replaced smile.config.yaml' <<<"$OUT"
check "force run restores the template bytes" cmp -s "$ROOT/templates/smile.config.yaml" "$TARGET/smile.config.yaml"
check ".gitignore still has the line once after force" test "$(grep -cx '.factory/' "$TARGET/.gitignore")" -eq 1

# ---------------------------------------------------------------- usage
python3 "$INSTALL" >/dev/null 2>&1; check "no target exits 2" test $? -eq 2
python3 "$INSTALL" "$TARGET/does-not-exist" >/dev/null 2>&1; check "missing target exits 2" test $? -eq 2

# ---------------------------------------------------------------- shim dispatch
SHIM="$TARGET/smile/smile"
"$SHIM" >/dev/null 2>&1; check "shim with no args exits 1" test $? -eq 1
"$SHIM" nosuch >/dev/null 2>&1; check "shim with unknown command exits 2" test $? -eq 2
"$SHIM" ../x >/dev/null 2>&1; check "shim rejects a path as command" test $? -eq 2
mkdir -p "$TARGET/smile/bash"
printf '#!/usr/bin/env bash\nprintf "%%s|%%s\\n" "$SMILE_ROOT" "$*"\n' > "$TARGET/smile/bash/probe"
chmod +x "$TARGET/smile/bash/probe"
GOT=$(cd / && "$SHIM" probe a b 2>&1)
check "shim execs smile/bash/<command> with args and SMILE_ROOT" test "$GOT" = "$TARGET|a b"
sed -i '' 's/^runtime: bash$/runtime: py/' "$TARGET/smile.config.yaml"
"$SHIM" probe >/dev/null 2>&1; check "py runtime without smile.py exits 2" test $? -eq 2
sed -i '' 's/^runtime: py$/runtime: ruby/' "$TARGET/smile.config.yaml"
"$SHIM" probe >/dev/null 2>&1; check "unknown runtime exits 2" test $? -eq 2

if [ "$FAILS" -eq 0 ]; then
	printf 'PASS install.test.sh\n'
else
	printf 'FAIL install.test.sh: %s failure(s)\n' "$FAILS"
	exit 1
fi
