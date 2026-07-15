#!/usr/bin/env python3
"""Hardware-free tests for capture-physical-reset-retention.py."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).with_name("capture-physical-reset-retention.py")
SPEC = importlib.util.spec_from_file_location("physical_reset_retention", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
RUNNER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = RUNNER
SPEC.loader.exec_module(RUNNER)

VERSION = "tinySA4_v0.4-chibios21-rc5"


def populated_frame() -> bytes:
    payload = bytearray(RUNNER.CORE.PIXEL_BYTES)
    for pixel in range(len(payload) // 2):
        value = 1 + pixel % 5
        payload[2 * pixel] = value >> 8
        payload[2 * pixel + 1] = value & 0xFF
    return bytes(payload)


FRAME = populated_frame()


def version_response(version: str = VERSION) -> bytes:
    return (
        b"version\r\n" + version.encode("ascii")
        + b"\r\nHW Version:V0.5.4 max2871\r\nch> "
    )


def write_flash_evidence(root: Path, candidate_path: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    candidate_payload = candidate_path.read_bytes()
    candidate_sha256 = hashlib.sha256(candidate_payload).hexdigest()
    dfu_payload = b"synthetic dfu-util 0.11\n"
    (root / "candidate.snapshot.bin").write_bytes(candidate_payload)
    (root / "candidate.readback.bin").write_bytes(candidate_payload)
    (root / "dfu-util.snapshot").write_bytes(dfu_payload)
    transcripts = {
        "dfu-util-version.stdout.txt": b"dfu-util 0.11\n",
        "dfu-util-version.stderr.txt": b"",
        "dfu-util-list.stdout.txt": (
            b'Found DFU: [0483:df11] cfg=1, intf=0, path="0-1", alt=0, '
            b'name="@Internal Flash  /0x08000000/128*0002Kg"\n'
            b'Found DFU: [0483:df11] cfg=1, intf=0, path="0-1", alt=1, '
            b'name="@Option Bytes  /0x1FFFF800/01*016 e"\n'
        ),
        "dfu-util-list.stderr.txt": b"",
        "dfu-util-download.stdout.txt": b"Download done.\nFile downloaded successfully\n",
        "dfu-util-download.stderr.txt": b"",
        "dfu-util-readback.stdout.txt": b"Upload done.\n",
        "dfu-util-readback.stderr.txt": b"",
    }
    for name, payload in transcripts.items():
        (root / name).write_bytes(payload)
    metadata = {
        "schema": RUNNER.USB.FLASH_EVIDENCE_SCHEMA,
        "result": "PASS",
        "candidate": {
            "bytes": len(candidate_payload),
            "sha256": candidate_sha256,
            "staged_path": "candidate.snapshot.bin",
            "staged_sha256": candidate_sha256,
        },
        "dfu_tool": {
            "bytes": len(dfu_payload),
            "expected_version": "dfu-util 0.11",
            "sha256": hashlib.sha256(dfu_payload).hexdigest(),
            "staged_path": "dfu-util.snapshot",
        },
        "preflight": {
            "pass": True,
            "vid": 0x0483,
            "pid": 0xDF11,
            "path": "0-1",
            "serial": "2066365B2036",
            "selected_alt": 0,
            "rejected_alt": 1,
        },
        "download": {
            "pass": True,
            "attempt_count": 1,
            "selected_alt": 0,
            "retry_performed": False,
        },
        "readback": {
            "pass": True,
            "attempt_count": 1,
            "selected_alt": 0,
            "retry_performed": False,
            "leave_requested_after_upload": True,
            "bytes": len(candidate_payload),
            "sha256": candidate_sha256,
            "exact_byte_match": True,
        },
        "normal_mode": {
            "pass": True,
            "vid": RUNNER.CORE.DEFAULT_VID,
            "pid": RUNNER.CORE.DEFAULT_PID,
            "serial_number": "706",
            "location": "0-1",
        },
        "device_byte_binding": {
            "candidate_sha256": candidate_sha256,
            "readback_sha256": candidate_sha256,
            "readback_performed": True,
            "exact_byte_match": True,
        },
    }
    run_path = root / "run.json"
    run_path.write_text(json.dumps(metadata, sort_keys=True) + "\n", encoding="utf-8")
    inventory = root / "SHA256SUMS"
    inventory.unlink(missing_ok=True)
    paths = sorted(path for path in root.iterdir() if path.is_file())
    inventory.write_text(
        "".join(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
            for path in paths
        ),
        encoding="utf-8",
    )
    return root


class FakeLocator:
    def __init__(self, *, after_location: str | None = None) -> None:
        self.history = ["/dev/fake"]
        self.calls = 0
        self.after_location = after_location

    def resolve(self) -> str:
        return "/dev/fake"

    def _ports(self) -> list[SimpleNamespace]:
        self.calls += 1
        location = "0-1"
        if self.after_location and self.calls >= 2:
            location = self.after_location
        return [SimpleNamespace(
            device="/dev/fake", vid=RUNNER.CORE.DEFAULT_VID,
            pid=RUNNER.CORE.DEFAULT_PID, serial_number="706", location=location,
        )]


def fake_session_type(*, version: str = VERSION, config_mismatch: bool = False,
                      frequency_mismatch: bool = False, reset_failure: bool = False,
                      disconnect_observed: bool = True):
    class FakeSession:
        def __init__(self, locator: FakeLocator, store: RUNNER.ResetStore) -> None:
            self.locator = locator
            self.store = store
            self.reset_attempted = False
            self.reset_sent = False
            self.phase = 0
            self.config_counts: dict[str, int] = {}

        def connect(self) -> bytes:
            self.phase += 1
            return b"\r\nch> "

        def command(self, command: str, timeout: float = 30.0,
                    retry_read_only: bool = False) -> bytes:
            if command == "version":
                return version_response(version)
            if command == "info":
                return b"info\r\ntinySA ULTRA+ ZS407\r\nKernel: 7.0.6\r\nch> "
            if command == "sweep":
                return b"sweep\r\n0 900000000 450\r\nch> "
            if command == "frequencies":
                values = list(range(450))
                if frequency_mismatch and self.phase >= 2:
                    values[-1] += 1
                return ("frequencies\r\n" + "\r\n".join(map(str, values))
                        + "\r\nch> ").encode("ascii")
            if command == "sweeptime":
                return b"sweeptime\r\n659ms\r\nch> "
            if command == "status":
                return b"status\r\nResumed\r\nch> "
            if command in RUNNER.CONFIG_COMMANDS:
                count = self.config_counts.get(command, 0) + 1
                self.config_counts[command] = count
                value = f"stable-{command}"
                if config_mismatch and command == "color" and count == 2:
                    value = "changed-color"
                return f"{command}\r\n{value}\r\nch> ".encode("ascii")
            raise AssertionError(command)

        def capture_frame(self) -> bytes:
            return FRAME

        def send_reset_once(self) -> dict[str, object]:
            if self.reset_attempted:
                raise RuntimeError("reset retry")
            self.reset_attempted = True
            if reset_failure:
                raise OSError("injected reset write failure")
            self.reset_sent = True
            response = (
                b"transport ended after reset: SerialException: device disappeared\n"
                if disconnect_observed else b"reset\r\nch> "
            )
            return {
                "response": response,
                "wire_write_completed": True,
                "transport_disconnect_observed": disconnect_observed,
                "reset_banner_observed": False,
                "prompt_observed": not disconnect_observed,
                "terminal_error": (
                    "SerialException: device disappeared"
                    if disconnect_observed else None
                ),
            }

        def close(self) -> None:
            pass

    return FakeSession


class ResetRetentionTests(unittest.TestCase):
    def args(self, output: Path, **overrides: object) -> argparse.Namespace:
        candidate_sha256 = RUNNER.CORE.sha256_file(SCRIPT)
        flash_evidence = write_flash_evidence(
            output.parent / "flash-evidence", SCRIPT
        )
        values: dict[str, object] = {
            "confirm": RUNNER.CONFIRMATION,
            "port": "auto",
            "vid": RUNNER.CORE.DEFAULT_VID,
            "pid": RUNNER.CORE.DEFAULT_PID,
            "expected_usb_serial": "706",
            "expected_usb_location": "0-1",
            "expected_version": VERSION,
            "candidate_bin": SCRIPT,
            "expected_candidate_sha256": candidate_sha256,
            "flash_evidence": flash_evidence,
            "expected_flash_inventory_sha256": RUNNER.CORE.sha256_file(
                flash_evidence / "SHA256SUMS"
            ),
            "expected_flash_run_sha256": RUNNER.CORE.sha256_file(
                flash_evidence / "run.json"
            ),
            "output": output,
            "reset_wait": 2.0,
            "reenumeration_timeout": 1.0,
        }
        values.update(overrides)
        return argparse.Namespace(**values)

    def run_fake(self, output: Path, *, locator: FakeLocator | None = None,
                 session_type: type | None = None, **overrides: object) -> int:
        fake_locator = locator or FakeLocator()
        fake_session = session_type or fake_session_type()
        with mock.patch.object(RUNNER.CORE, "PortLocator", return_value=fake_locator), \
             mock.patch.object(RUNNER, "ResetSession", fake_session), \
             mock.patch.object(RUNNER.time, "sleep", return_value=None):
            return RUNNER.capture_run(self.args(output, **overrides))

    def test_pass_is_hash_bound_and_reset_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "evidence"
            self.assertEqual(self.run_fake(output), 0)
            metadata = json.loads((output / "run.json").read_text())
            self.assertEqual(metadata["schema"], "tinysa-physical-reset-retention-v2")
            self.assertEqual(metadata["result"], "PASS")
            self.assertTrue(metadata["retention"]["pass"])
            self.assertEqual(metadata["reset"]["sent_count"], 1)
            self.assertTrue(metadata["reset"]["transport_disconnect_observed"])
            self.assertEqual(metadata["before"]["frequency_points"], 450)
            candidate = metadata["candidate_binary"]
            self.assertTrue(candidate["device_byte_binding"])
            self.assertEqual(
                candidate["flash_evidence"]["candidate_sha256"],
                RUNNER.CORE.sha256_file(SCRIPT),
            )
            self.assertEqual(candidate["flash_evidence"]["dfu_location"], "0-1")
            self.assertEqual(
                candidate["flash_evidence"]["normal_usb_identity"]["serial_number"],
                "706",
            )
            self.assertIn("run.json", (output / "SHA256SUMS").read_text())

    def test_flash_evidence_tamper_is_rejected_before_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "evidence"
            args = self.args(output)
            run_path = args.flash_evidence / "run.json"
            run_path.write_text(run_path.read_text() + " ", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "caller-pinned trust root"):
                RUNNER.capture_run(args)
            self.assertFalse(output.exists())

    def test_reset_confirmation_is_exact_and_checked_before_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "evidence"
            with self.assertRaisesRegex(ValueError, "--confirm must be exactly"):
                RUNNER.capture_run(self.args(output, confirm="RESET"))
            self.assertFalse(output.exists())

    def test_cli_requires_flash_evidence(self) -> None:
        required = [
            "--expected-usb-serial", "706",
            "--expected-usb-location", "0-1",
            "--expected-version", VERSION,
            "--candidate-bin", str(SCRIPT),
            "--expected-candidate-sha256", RUNNER.CORE.sha256_file(SCRIPT),
            "--expected-flash-inventory-sha256", "0" * 64,
            "--expected-flash-run-sha256", "1" * 64,
            "--confirm", RUNNER.CONFIRMATION,
            "--output", "unused",
        ]
        with mock.patch.object(RUNNER.sys, "stderr"), self.assertRaises(SystemExit):
            RUNNER.parse_args(required)
        parsed = RUNNER.parse_args([
            *required,
            "--flash-evidence", "sealed-flash-evidence",
        ])
        self.assertEqual(parsed.flash_evidence, Path("sealed-flash-evidence"))

    def test_forbidden_commands(self) -> None:
        for command in ("save", "touch 1 1", "dfu", "reset", "correction"):
            with self.subTest(command=command), self.assertRaises(ValueError):
                RUNNER.require_read_only(command)

    def test_stale_output_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "evidence"
            output.mkdir()
            with self.assertRaises(RuntimeError):
                RUNNER.capture_run(self.args(output))

    def test_version_mismatch_fails_before_reset(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "evidence"
            self.assertEqual(
                self.run_fake(output, session_type=fake_session_type(version=VERSION + "x")), 1
            )
            metadata = json.loads((output / "run.json").read_text())
            self.assertEqual(metadata["reset"]["sent_count"], 0)

    def test_config_mismatch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "evidence"
            self.assertEqual(
                self.run_fake(output, session_type=fake_session_type(config_mismatch=True)), 1
            )

    def test_frequency_mismatch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "evidence"
            self.assertEqual(
                self.run_fake(output, session_type=fake_session_type(frequency_mismatch=True)), 1
            )

    def test_final_usb_identity_mismatch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "evidence"
            self.assertEqual(
                self.run_fake(output, locator=FakeLocator(after_location="0-2")), 1
            )

    def test_reset_write_failure_is_not_retried(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "evidence"
            self.assertEqual(
                self.run_fake(output, session_type=fake_session_type(reset_failure=True)), 1
            )

    def test_prompt_without_usb_disconnect_cannot_pass_as_reset(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "evidence"
            self.assertEqual(
                self.run_fake(
                    output,
                    session_type=fake_session_type(disconnect_observed=False),
                ),
                1,
            )
            metadata = json.loads((output / "run.json").read_text())
            self.assertFalse(metadata["retention"]["pass"])
            self.assertFalse(
                metadata["retention"]["reset_transport_disconnect_observed"]
            )

    def test_real_reset_method_writes_literal_once(self) -> None:
        class Port:
            def __init__(self) -> None:
                self.writes: list[bytes] = []

            def write(self, payload: bytes) -> None:
                self.writes.append(payload)

            def flush(self) -> None:
                pass

        session = object.__new__(RUNNER.ResetSession)
        session.reset_attempted = False
        session.reset_sent = False
        session.port = Port()
        session.ensure_connected = lambda: None
        session.close = lambda: None
        with mock.patch.object(
            RUNNER.CORE.SCREEN_TOOL, "read_until", side_effect=OSError("device gone")
        ):
            delivery = session.send_reset_once()
        self.assertIn(b"transport ended after reset", delivery["response"])
        self.assertTrue(delivery["transport_disconnect_observed"])
        self.assertEqual(session.port.writes, [RUNNER.RESET_WIRE])
        with self.assertRaises(RuntimeError):
            session.send_reset_once()
        self.assertEqual(session.port.writes, [RUNNER.RESET_WIRE])


if __name__ == "__main__":
    unittest.main(verbosity=2)
