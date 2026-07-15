#!/usr/bin/env python3
"""Hardware-free adversarial tests for flash-physical-dfu-evidence.py."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).with_name("flash-physical-dfu-evidence.py")
SPEC = importlib.util.spec_from_file_location("physical_dfu_flash_evidence", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


LISTING = """dfu-util 0.11
Found DFU: [0483:df11] ver=2200, devnum=1, cfg=1, intf=0, path=\"0-1\", alt=1, name=\"@Option Bytes  /0x1FFFF800/01*016 e\", serial=\"2066365B2036\"
Found DFU: [0483:df11] ver=2200, devnum=1, cfg=1, intf=0, path=\"0-1\", alt=0, name=\"@Internal Flash  /0x08000000/128*0002Kg\", serial=\"2066365B2036\"
"""


def completed(arguments: list[str], returncode: int, stdout: str = "",
              stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(arguments, returncode, stdout, stderr)


def candidate_fixture() -> bytes:
    payload = bytearray(512)
    struct.pack_into("<II", payload, 0, 0x20000400, 0x08000041)
    payload[64:64 + len(MODULE.ADMITTED_VERSION_MARKER)] = MODULE.ADMITTED_VERSION_MARKER
    payload[128:128 + len(MODULE.ADMITTED_HARDWARE_MARKER)] = MODULE.ADMITTED_HARDWARE_MARKER
    return bytes(payload)


class PhysicalDfuFlashEvidenceTests(unittest.TestCase):
    def make_args(self, root: Path, **overrides: object) -> argparse.Namespace:
        dfu = root / "dfu-util"
        candidate = root / "candidate.bin"
        if not dfu.exists():
            dfu.write_bytes(b"test dfu executable")
        if not candidate.exists():
            candidate.write_bytes(candidate_fixture())
        values: dict[str, object] = {
            "dfu_util": dfu,
            "candidate_bin": candidate,
            "expected_candidate_sha256": MODULE.sha256_file(candidate),
            "expected_dfu_location": "0-1",
            "expected_dfu_serial": "2066365B2036",
            "expected_normal_location": "0-1",
            "expected_normal_serial": "706",
            "output": root / "evidence",
            "timeout": 30.0,
            "confirm": MODULE.CONFIRMATION,
        }
        values.update(overrides)
        return argparse.Namespace(**values)

    def admitted_fixture(self, args: argparse.Namespace):
        return mock.patch.multiple(
            MODULE,
            ADMITTED_CANDIDATE_SHA256=MODULE.sha256_file(args.candidate_bin),
            ADMITTED_CANDIDATE_BYTES=args.candidate_bin.stat().st_size,
            ADMITTED_DFU_UTIL_SHA256=MODULE.sha256_file(args.dfu_util),
            ADMITTED_DFU_UTIL_BYTES=args.dfu_util.stat().st_size,
        )

    def test_listing_admits_only_exact_alt0_internal_flash_device(self) -> None:
        admitted = MODULE.admit_dfu_device(
            MODULE.parse_dfu_listing(LISTING), "0-1", "2066365B2036"
        )
        self.assertEqual(admitted["selected_alt"], 0)
        self.assertEqual(admitted["rejected_alt"], 1)

        duplicate = LISTING + LISTING.replace('path="0-1"', 'path="0-2"')
        with self.assertRaisesRegex(ValueError, "not the one admitted target"):
            MODULE.admit_dfu_device(
                MODULE.parse_dfu_listing(duplicate), "0-1", "2066365B2036"
            )
        with self.assertRaisesRegex(ValueError, "alternates 0 and 1"):
            MODULE.admit_dfu_device(
                [record for record in MODULE.parse_dfu_listing(LISTING)
                 if record["alt"] == 1],
                "0-1", "2066365B2036",
            )

    def test_success_runs_one_exact_alt0_download_and_seals_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = self.make_args(root)
            calls: list[list[str]] = []

            def fake_run(arguments: list[str], timeout: float):
                calls.append(arguments)
                if arguments[-1] == "--version":
                    return completed(arguments, 0, "dfu-util 0.11\n")
                if arguments[-1] == "-l":
                    return completed(arguments, 0, LISTING)
                if "-U" in arguments:
                    target = Path(arguments[arguments.index("-U") + 1])
                    target.write_bytes((args.output / "candidate.snapshot.bin").read_bytes())
                    return completed(arguments, 0, "Upload done.\n")
                return completed(
                    arguments, 0,
                    "Download done.\nFile downloaded successfully\n",
                )

            normal = {
                "device": "/dev/cu.usbmodem7061",
                "vid": MODULE.NORMAL_VID,
                "pid": MODULE.NORMAL_PID,
                "serial_number": "706",
                "location": "0-1",
            }
            with self.admitted_fixture(args), \
                 mock.patch.object(MODULE, "run_process", side_effect=fake_run), \
                 mock.patch.object(MODULE, "wait_for_normal_identity", return_value=normal):
                self.assertEqual(MODULE.flash(args), 0)

            downloads = [call for call in calls if "-D" in call]
            self.assertEqual(len(downloads), 1)
            self.assertEqual(downloads[0][downloads[0].index("-p") + 1], "0-1")
            self.assertEqual(
                downloads[0][downloads[0].index("-S") + 1], "2066365B2036"
            )
            self.assertEqual(downloads[0][downloads[0].index("-c") + 1], "1")
            self.assertEqual(downloads[0][downloads[0].index("-i") + 1], "0")
            self.assertIn("-a", downloads[0])
            self.assertEqual(downloads[0][downloads[0].index("-a") + 1], "0")
            self.assertNotIn("1", downloads[0][downloads[0].index("-a") + 1:])
            uploads = [call for call in calls if "-U" in call]
            self.assertEqual(len(uploads), 1)
            self.assertEqual(uploads[0][uploads[0].index("-p") + 1], "0-1")
            self.assertEqual(
                uploads[0][uploads[0].index("-S") + 1], "2066365B2036"
            )
            self.assertEqual(
                uploads[0][uploads[0].index("-s") + 1],
                f"{MODULE.FLASH_ADDRESS}:{args.candidate_bin.stat().st_size}:leave",
            )
            metadata = json.loads((args.output / "run.json").read_text())
            self.assertEqual(metadata["result"], "PASS")
            self.assertEqual(metadata["download"]["attempt_count"], 1)
            self.assertTrue(metadata["device_byte_binding"]["readback_performed"])
            self.assertTrue(metadata["readback"]["exact_byte_match"])
            self.assertEqual(
                MODULE.sha256_file(args.output / "candidate.snapshot.bin"),
                args.expected_candidate_sha256,
            )
            self.assertIn("run.json", (args.output / "SHA256SUMS").read_text())

    def test_failed_download_is_never_retried(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = self.make_args(root)
            calls: list[list[str]] = []

            def fake_run(arguments: list[str], timeout: float):
                calls.append(arguments)
                if arguments[-1] == "--version":
                    return completed(arguments, 0, "dfu-util 0.11\n")
                if arguments[-1] == "-l":
                    return completed(arguments, 0, LISTING)
                return completed(arguments, 1, "download failed\n")

            with self.admitted_fixture(args), \
                 mock.patch.object(MODULE, "run_process", side_effect=fake_run):
                self.assertEqual(MODULE.flash(args), 1)
            self.assertEqual(sum("-D" in call for call in calls), 1)
            metadata = json.loads((args.output / "run.json").read_text())
            self.assertEqual(metadata["result"], "FAIL")
            self.assertEqual(metadata["download"]["attempt_count"], 1)

    def test_readback_mismatch_fails_without_retry_or_normal_boot_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = self.make_args(root)
            calls: list[list[str]] = []

            def fake_run(arguments: list[str], timeout: float):
                calls.append(arguments)
                if arguments[-1] == "--version":
                    return completed(arguments, 0, "dfu-util 0.11\n")
                if arguments[-1] == "-l":
                    return completed(arguments, 0, LISTING)
                if "-U" in arguments:
                    target = Path(arguments[arguments.index("-U") + 1])
                    payload = bytearray((args.output / "candidate.snapshot.bin").read_bytes())
                    payload[-1] ^= 0x01
                    target.write_bytes(payload)
                    return completed(arguments, 0, "Upload done.\n")
                return completed(
                    arguments, 0,
                    "Download done.\nFile downloaded successfully\n",
                )

            with self.admitted_fixture(args), \
                 mock.patch.object(MODULE, "run_process", side_effect=fake_run), \
                 mock.patch.object(MODULE, "wait_for_normal_identity") as wait_normal:
                self.assertEqual(MODULE.flash(args), 1)
            self.assertEqual(sum("-D" in call for call in calls), 1)
            self.assertEqual(sum("-U" in call for call in calls), 1)
            wait_normal.assert_not_called()
            metadata = json.loads((args.output / "run.json").read_text())
            self.assertEqual(metadata["result"], "FAIL")
            self.assertEqual(metadata["readback"]["attempt_count"], 1)
            self.assertIs(metadata["normal_mode"], None)

    def test_real_production_pins_reject_arbitrary_candidate_and_tool(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = self.make_args(root)
            with self.assertRaisesRegex(ValueError, "not the sealed RC5 release"):
                MODULE.flash(args)
            self.assertFalse(args.output.exists())

            # Admit only the synthetic candidate to reach the still-production
            # executable provenance check; the arbitrary tool must remain rejected.
            with mock.patch.multiple(
                MODULE,
                ADMITTED_CANDIDATE_SHA256=MODULE.sha256_file(args.candidate_bin),
                ADMITTED_CANDIDATE_BYTES=args.candidate_bin.stat().st_size,
            ), self.assertRaisesRegex(ValueError, "does not match the admitted arm64"):
                MODULE.flash(args)
            self.assertFalse(args.output.exists())

    def test_hash_confirmation_and_nonfinite_timeout_reject_before_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index, overrides in enumerate((
                {"expected_candidate_sha256": "0" * 64},
                {"confirm": "yes"},
                {"timeout": float("nan")},
                {"expected_normal_location": "0-2"},
            )):
                output = root / f"evidence-{index}"
                args = self.make_args(root, output=output, **overrides)
                with self.subTest(overrides=overrides), self.admitted_fixture(args), \
                     self.assertRaises(ValueError):
                    MODULE.flash(args)
                self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
