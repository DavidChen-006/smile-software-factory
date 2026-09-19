#!/usr/bin/env bash
# Runs the py runtime's S6 narration tests (tests/test_narrate.py) from the repo root so
# tests/all.sh picks them up.
set -uo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
if (cd "$ROOT" && uv run python -m unittest tests.test_narrate -v); then
	printf 'PASS narrate.test.sh\n'
else
	printf 'FAIL narrate.test.sh\n'
	exit 1
fi
