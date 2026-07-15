#!/usr/bin/env python3
"""Regression checks for the Firmware -> standalone Flasher ownership boundary."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
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

        retired = ROOT / "tools" / "flash-physical-dfu-evidence.py"
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "evidence"
            completed = subprocess.run(
                [sys.executable, str(retired), "--output", str(output)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 2)
            self.assertIn("TinySA_Flasher", completed.stderr)
            self.assertFalse(output.exists())

        retired_source = retired.read_text(encoding="utf-8")
        for forbidden in ("import subprocess", "from serial", "run_process(", '"-D"', '"-U"'):
            self.assertNotIn(forbidden, retired_source)

    def test_maintained_shell_and_editor_paths_cannot_program(self) -> None:
        maintained_shell = [
            ROOT / "prog.sh",
            *sorted((ROOT / "tools").glob("*.sh")),
            *sorted((ROOT / "experiments").rglob("*.sh")),
            *sorted(path for path in (ROOT / ".githooks").glob("*") if path.is_file()),
        ]
        for path in maintained_shell:
            source = path.read_text(encoding="utf-8")
            with self.subTest(path=path.relative_to(ROOT)):
                for forbidden in ("dfu-util", "STM32CubeProgrammer", "st-flash", "pyocd flash"):
                    self.assertNotIn(forbidden, source)

        production_python = [
            *sorted(path for path in (ROOT / "tools").glob("*.py") if not path.name.startswith("test-")),
            *sorted((ROOT / "python").glob("*.py")),
        ]
        process_capabilities = ("import subprocess", "from subprocess", "os.system", "Popen(")
        device_writer_tokens = ("dfu-util", "STM32CubeProgrammer", "st-flash", '"-D"', "'-D'")
        for path in production_python:
            source = path.read_text(encoding="utf-8")
            with self.subTest(path=path.relative_to(ROOT)):
                has_process_capability = any(token in source for token in process_capabilities)
                has_writer_token = any(token in source for token in device_writer_tokens)
                self.assertFalse(
                    has_process_capability and has_writer_token,
                    f"{path.relative_to(ROOT)} combines child-process execution with device-write tokens",
                )

        tasks = json.loads((ROOT / ".vscode" / "tasks.json").read_text(encoding="utf-8"))
        serialized_tasks = json.dumps(tasks)
        self.assertNotIn("make dfu flash", serialized_tasks)
        self.assertNotIn('"label": "flash"', serialized_tasks)
        self.assertIn("package-flasher-build.sh", serialized_tasks)

        launch = json.loads((ROOT / ".vscode" / "launch.json").read_text(encoding="utf-8"))
        self.assertTrue(launch["configurations"])
        self.assertTrue(all(item["request"] == "attach" for item in launch["configurations"]))
        self.assertNotIn('"request": "launch"', json.dumps(launch))

    def test_generated_artifacts_never_publish_raw_write_instructions(self) -> None:
        candidate_builder = (ROOT / "tools" / "build-chibios-release-candidate.sh").read_text(encoding="utf-8")
        self.assertNotIn("dfu-util", candidate_builder)
        self.assertNotIn("FLASHING.txt", candidate_builder)
        self.assertIn("INSTALLATION.txt", candidate_builder)
        self.assertIn("installable_by_current_flasher=false", candidate_builder)

        packager = (ROOT / "tools" / "package-physical-qualification-bundle.py").read_text(encoding="utf-8")
        installation_renderer = packager.split("def render_installation_boundary()", 1)[1].split(
            "def open_child_directory", 1
        )[0]
        for forbidden in ("dfu-util -", " -D ", " -U ", "FLASHING.txt"):
            self.assertNotIn(forbidden, installation_renderer)
        self.assertIn("TinySA_Flasher", installation_renderer)
        self.assertIn('"flash_execution": "standalone-tinysa-flasher-only"', packager)
        self.assertIn('"candidate_currently_admissible": False', packager)

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
        self.assertIn("test-physical-dfu-flash-evidence.py", config)
        self.assertIn("test-physical-qualification-bundle.py", config)


if __name__ == "__main__":
    unittest.main()
