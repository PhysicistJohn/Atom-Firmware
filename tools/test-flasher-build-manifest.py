#!/usr/bin/env python3
"""Black-box tests for the no-flash local-build manifest writer."""

from __future__ import annotations

import hashlib
import json
import subprocess
import struct
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WRITER = ROOT / "tools" / "write-flasher-build-manifest.py"
COMMIT = "1234567" + "a" * 33
VERSION = "tinySA4_lab-v9.0.0-g1234567"


class FlasherBuildManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="tinysa-flasher-manifest-")
        self.directory = Path(self.temporary.name)
        self.binary = self.directory / "input.bin"
        self.output = self.directory / "output"
        self.binary.write_bytes(firmware_bytes())
        self.binary.chmod(0o600)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_writes_one_strict_content_addressed_package(self) -> None:
        completed = self.run_writer()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        manifest_path = next(self.output.rglob("tinysa-flasher-build-v1.json"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        digest = hashlib.sha256(self.binary.read_bytes()).hexdigest()
        self.assertEqual(manifest["artifact"]["sha256"], digest)
        self.assertEqual(manifest["firmware"]["sourceCommit"], COMMIT)
        self.assertEqual(manifest["artifact"]["initialStackPointer"], "0x2000a000")
        self.assertFalse(manifest["flashPolicy"]["automatedFlash"])
        self.assertEqual((manifest_path.parent / manifest["artifact"]["filename"]).read_bytes(), self.binary.read_bytes())
        self.assertEqual(self.run_writer().returncode, 0)

    def test_rejects_stale_revision_bad_vectors_symlinks_and_reserved_oem_identity(self) -> None:
        self.assertNotEqual(self.run_writer(version="tinySA4_lab-v9.0.0-g7654321").returncode, 0)

        invalid = bytearray(firmware_bytes())
        struct.pack_into("<I", invalid, 4, 0x08000008)
        self.binary.write_bytes(invalid)
        self.assertNotEqual(self.run_writer().returncode, 0)

        self.binary.unlink()
        real = self.directory / "real.bin"
        real.write_bytes(firmware_bytes())
        self.binary.symlink_to(real)
        self.assertNotEqual(self.run_writer().returncode, 0)

        self.binary.unlink()
        self.binary.write_bytes(firmware_bytes(version="tinySA4_v1.4-224-gc979386"))
        self.assertNotEqual(self.run_writer(
            version="tinySA4_v1.4-224-gc979386",
            commit="c979386" + "b" * 33,
        ).returncode, 0)

    def test_rejects_create_once_collision(self) -> None:
        self.assertEqual(self.run_writer().returncode, 0)
        manifest_path = next(self.output.rglob("tinysa-flasher-build-v1.json"))
        manifest_path.write_text("conflict", encoding="utf-8")
        self.assertNotEqual(self.run_writer().returncode, 0)
        self.assertEqual(manifest_path.read_text(encoding="utf-8"), "conflict")

    def run_writer(self, *, version: str = VERSION, commit: str = COMMIT) -> subprocess.CompletedProcess[str]:
        return subprocess.run([
            "python3", str(WRITER),
            "--binary", str(self.binary),
            "--version", version,
            "--source-commit", commit,
            "--chibios-commit", "b" * 40,
            "--source-date-epoch", "1750000000",
            "--toolchain", "arm-none-eabi-gcc 11.3.1",
            "--output-root", str(self.output),
            "--simulation-passed",
        ], text=True, capture_output=True, check=False)


def firmware_bytes(version: str = VERSION) -> bytes:
    value = bytearray(8_192)
    struct.pack_into("<II", value, 0, 0x2000A000, 0x08000009)
    value[100:100 + len(version)] = version.encode("ascii")
    value[200:207] = b"+ ZS407"
    return bytes(value)


if __name__ == "__main__":
    unittest.main()
