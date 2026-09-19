#!/usr/bin/env bash
# The live suite: tests that create and delete real GitHub repos. Minutes, not seconds, and it needs
# a logged-in `gh`. Never part of tests/all.sh (docs/PROCESS.md, "Unit suite rules"); the verifier
# runs it as the harness self-test before driving a branch.
set -uo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
FAILS=0
LOGS=$(mktemp -d "${TMPDIR:-/tmp}/smile-live.XXXXXX")
printf 'logs: %s\n' "$LOGS"
for t in "$ROOT"/tests/live/*.test.sh; do
	name=$(basename "$t")
	start=$SECONDS
	if bash "$t" > "$LOGS/$name.log" 2>&1; then
		printf 'ok   %s %ss\n' "$name" "$((SECONDS - start))"
	else
		printf 'FAIL %s %ss (log: %s/%s.log)\n' "$name" "$((SECONDS - start))" "$LOGS" "$name"
		FAILS=$((FAILS + 1))
	fi
done
[ "$FAILS" -eq 0 ] && printf 'all live tests passed\n' || { printf '%s live test file(s) failed\n' "$FAILS"; exit 1; }
