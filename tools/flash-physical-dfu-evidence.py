#!/usr/bin/env python3
"""Fail-closed compatibility tombstone for the retired Firmware writer.

Historical qualification records still name this path, so it remains present
to make their provenance legible.  The implementation that accessed a device
was retired when physical-install ownership moved to standalone TinySA_Flasher.
This module deliberately imports no USB, serial, or process-execution API.
"""

from __future__ import annotations

import sys
from typing import Iterable


MESSAGE = (
    "TinySA_Firmware cannot access or write a device. "
    "Package a committed custom build with tools/package-flasher-build.sh, "
    "then select its tinysa-flasher-build-v1.json manifest in "
    "standalone ../TinySA_Flasher."
)


def main(argv: Iterable[str] | None = None) -> int:
    # Consume nothing: legacy arguments must never regain meaning here.
    del argv
    print(f"error: {MESSAGE}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
