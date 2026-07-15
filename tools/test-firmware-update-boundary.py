#!/usr/bin/env python3
"""Regression checks for the Firmware -> standalone Flasher ownership boundary."""

from __future__ import annotations

import hashlib
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
CANONICAL_MANIFEST_SCHEMA_SHA256 = "ae64bcc0db88a5e6fbecbcff6ee9d15b3a56777ced716a69ace80df3e537c77c"


class FirmwareUpdateBoundaryTests(unittest.TestCase):
    def test_direct_write_entrypoints_fail_without_device_access(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        flash_recipe = makefile.split(".PHONY: flash", 1)[1].split("dfu:", 1)[0]
        self.assertNotIn("dfu-util", flash_recipe)
        self.assertNotIn("usbmodem", flash_recipe)
        completed = subprocess.run(
            ["make", "flash"], cwd=ROOT, text=True, capture_output=True, check=False
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("TinySA_Flasher", completed.stderr)

        program = (ROOT / "prog.sh").read_text(encoding="utf-8")
        self.assertNotIn("dfu-util", program)
        completed = subprocess.run(
            [str(ROOT / "prog.sh")], cwd=ROOT, text=True, capture_output=True, check=False
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("TinySA_Flasher", completed.stderr)

    def test_packaging_profile_is_fixed_and_environment_is_sanitized(self) -> None:
        packaging = (ROOT / "tools" / "package-flasher-build.sh").read_text(encoding="utf-8")
        self.assertNotIn("make_arguments", packaging)
        self.assertGreaterEqual(packaging.count("env -i"), 2)
        self.assertGreaterEqual(packaging.count("TARGET=F303 PHASE=6"), 2)
        self.assertGreaterEqual(packaging.count("RELEASE_PROFILE= RELEASE_HARD_FAULT_VENEER=no"), 2)

        completed = subprocess.run(
            [str(ROOT / "tools" / "package-flasher-build.sh"), "invalid", "--", "CC=malicious"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 1)
        self.assertIn("unknown package option", completed.stderr)

    def test_firmware_copy_of_manifest_schema_is_canonical(self) -> None:
        schema = (ROOT / "contracts" / "tinysa-firmware-build-manifest-v1.schema.json").read_bytes()
        self.assertEqual(hashlib.sha256(schema).hexdigest(), CANONICAL_MANIFEST_SCHEMA_SHA256)

    def test_ci_never_publishes_or_mutates_build_inputs(self) -> None:
        config = (ROOT / ".circleci" / "config.yml").read_text(encoding="utf-8")
        for forbidden in ("GITHUB_TOKEN", "ghr ", "publish-github-release", "submodule update --remote"):
            self.assertNotIn(forbidden, config)
        self.assertIn("test-firmware-update-boundary.py", config)


if __name__ == "__main__":
    unittest.main()
