"""smile.config.yaml: the schema table and the flat `key: value` parser (contract section 2)."""
from __future__ import annotations  # PEP 604 unions in annotations on the 3.9 floor

import re

# key -> default. This table is the schema; a key not in it is unknown.
SCHEMA = {
    "runtime": "bash",
    "backend": "",
    "worker.model": "opus",
    "worker.permission_mode": "acceptEdits",
    "reviewer.models": "opus",
    "max_parallel": "3",
    "watchtower": "on",
    "merge": "auto",
    "base_branch": "main",
}
KEY_LINE = re.compile(r"^[A-Za-z0-9_.]+:")
BLANK = " \t\r"


def read(root: str) -> dict[str, str]:
    """Every key present in the file, first occurrence wins, values trimmed of space/tab/CR."""
    values: dict[str, str] = {}
    with open(f"{root}/smile.config.yaml", encoding="utf-8", errors="surrogateescape") as f:
        for line in f.read().split("\n"):
            if line.lstrip(BLANK).startswith("#") or not KEY_LINE.match(line):
                continue
            key, _, value = line.partition(":")
            values.setdefault(key, value.strip(BLANK))
    return values


def get(root: str, key: str) -> str:
    """File value, else the schema default. KeyError when the key is not in the schema."""
    return read(root).get(key, SCHEMA[key])
