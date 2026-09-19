#!/usr/bin/env bash
# Runs the py runtime's S1 core tests (tests/test_core.py) from the repo root so tests/all.sh picks them up.
# One pass, through uv run: uv resolves the interpreter, so the test interpreter follows the runtime's rule.
set -uo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
if (cd "$ROOT" && uv run python -m unittest tests.test_core -v); then
	printf 'PASS core-py.test.sh\n'
else
	printf 'FAIL core-py.test.sh\n'
	exit 1
fi
