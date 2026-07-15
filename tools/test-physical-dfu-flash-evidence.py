#!/usr/bin/env python3
"""Regression checks for the retired Firmware-side physical writer."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("flash-physical-dfu-evidence.py")


class RetiredPhysicalDfuWriterTests(unittest.TestCase):
    def test_every_invocation_fails_closed_without_creating_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "must-not-exist"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--candidate-bin",
                    "candidate.bin",
                    "--output",
                    str(output),
                    "--confirm",
                    "legacy-confirmation",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 2)
            self.assertIn("TinySA_Flasher", completed.stderr)
            self.assertIn("tinysa-flasher-build-v1.json", completed.stderr)
            self.assertFalse(output.exists())

    def test_tombstone_has_no_device_or_child_process_capability(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        for forbidden in (
            "import subprocess",
            "from subprocess",
            "import serial",
            "from serial",
            "os.system",
            "Popen(",
            "run_process(",
            '"-D"',
            '"-U"',
        ):
            self.assertNotIn(forbidden, source)
        self.assertNotIn("def flash(", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
