#!/usr/bin/env bash
# Runs the py runtime's S1 core tests (tests/test_core.py) from the repo root so tests/all.sh picks them up.
# Two passes: the ambient python3, then the 3.9 floor (/usr/bin/python3 on macOS), so a machine with no
# Homebrew python still gets a working factory. A scratch bin dir puts the floor interpreter first on PATH,
# so the stamped shim's bare `python3` resolves to it too.
set -uo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
FLOOR=/usr/bin/python3

(cd "$ROOT" && python3 -m unittest tests.test_core -v) || { printf 'FAIL core-py.test.sh\n'; exit 1; }

if [ -x "$FLOOR" ] && "$FLOOR" -c 'import sys; sys.exit(sys.version_info[:2] != (3, 9))'; then
	BIN=$(mktemp -d)
	trap 'rm -r -- "$BIN"' EXIT
	ln -s "$FLOOR" "$BIN/python3"
	(cd "$ROOT" && PATH="$BIN:$PATH" "$FLOOR" -m unittest tests.test_core -v) ||
		{ printf 'FAIL core-py.test.sh (python3.9 pass)\n'; exit 1; }
else
	printf 'skip python3.9 pass\n'
fi
printf 'PASS core-py.test.sh\n'
