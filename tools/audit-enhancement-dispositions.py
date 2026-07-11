#!/usr/bin/env python3
"""Require one final disposition for every enhancement-register row."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parent.parent
REGISTER = ROOT / "docs/ENHANCEMENT_RISK_REGISTER.md"
DISPOSITIONS = ROOT / "docs/ENHANCEMENT_DISPOSITION.md"
ALLOWED = {
    "implemented",
    "experimental",
    "host-only",
    "specified",
    "blocked-hardware",
    "avoided",
}


def register_names() -> list[str]:
    names: list[str] = []
    for line in REGISTER.read_text(encoding="utf-8").splitlines():
        fields = [field.strip() for field in line.split("|")]
        if len(fields) == 7 and fields[1] not in ("", "Enhancement") and \
                not fields[1].startswith("---"):
            names.append(fields[1])
    return names


def disposition_rows() -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    row_pattern = re.compile(r"^\| (E\d{3}) \|")
    for line in DISPOSITIONS.read_text(encoding="utf-8").splitlines():
        if not row_pattern.match(line):
            continue
        fields = [field.strip() for field in line.split("|")]
        if len(fields) != 6:
            raise ValueError(f"malformed disposition row: {line}")
        rows.append((fields[1], fields[2], fields[3]))
    return rows


def main() -> int:
    try:
        expected = register_names()
        rows = disposition_rows()
        if len(expected) != 140:
            raise ValueError(
                f"risk-register parser expected 140 rows, found {len(expected)}"
            )
        if len(rows) != len(expected):
            raise ValueError(
                f"expected {len(expected)} dispositions, found {len(rows)}"
            )
        for index, (identifier, name, state) in enumerate(rows, 1):
            wanted_identifier = f"E{index:03d}"
            if identifier != wanted_identifier:
                raise ValueError(
                    f"row {index}: expected {wanted_identifier}, found {identifier}"
                )
            if name != expected[index - 1]:
                raise ValueError(
                    f"{identifier}: register name mismatch: {name!r} != "
                    f"{expected[index - 1]!r}"
                )
            if state not in ALLOWED:
                raise ValueError(f"{identifier}: invalid disposition {state!r}")
        counts = Counter(state for _, _, state in rows)
        summary = " ".join(f"{state}={counts[state]}" for state in sorted(ALLOWED))
        print(f"enhancement dispositions: passed rows={len(rows)} {summary}")
        return 0
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
