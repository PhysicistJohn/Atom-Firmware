#!/usr/bin/env python3
"""Hardware-free tests for capture-physical-usb-runtime.py."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).with_name("capture-physical-usb-runtime.py")
SPEC = importlib.util.spec_from_file_location("capture_physical_usb_runtime", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
RUNTIME = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = RUNTIME
SPEC.loader.exec_module(RUNTIME)

EXPECTED_VERSION = "tinySA4_v0.4-chibios21-rc5"


def populated_frame() -> bytes:
    frame = bytearray(RUNTIME.PIXEL_BYTES)
    for pixel in range(RUNTIME.PIXEL_BYTES // 2):
        value = 1 + pixel % 5
        frame[2 * pixel] = value >> 8
        frame[2 * pixel + 1] = value & 0xFF
    return bytes(frame)


FRAME = populated_frame()


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
        "schema": RUNTIME.FLASH_EVIDENCE_SCHEMA,
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
            "vid": RUNTIME.DEFAULT_VID,
            "pid": RUNTIME.DEFAULT_PID,
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
    (root / "run.json").write_text(
        __import__("json").dumps(metadata, sort_keys=True) + "\n",
        encoding="utf-8",
    )
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


def version_response(version: str) -> bytes:
    return (
        b"version\r\n" + version.encode("ascii")
        + b"\r\nHW Version:V0.5.4 max2871\r\nch> "
    )


def runtime_response(command: str) -> bytes:
    if command == "frequencies":
        lines = [str(1_000_000 + index * 1_000) for index in range(450)]
    elif command == "trace 1 value":
        lines = [f"trace 1 value {index} {-110.0 + index * 0.05:.2f}" for index in range(450)]
    elif command == "data 2":
        lines = [f"{-110.0 + index * 0.05:.6e}" for index in range(450)]
    elif command == "trace":
        lines = ["trace 1 enabled", "trace 2 stored"]
    elif command == "sweeptime":
        lines = ["1716ms"]
    elif command == "status":
        lines = ["Resumed"]
    elif command == "threads":
        lines = ["main WTEXIT", "idle READY", "sweep READY", "shell CURRENT"]
    else:
        raise AssertionError(command)
    return (command + "\r\n" + "\r\n".join(lines) + "\r\nch> ").encode("ascii")


class FakeLocator:
    def __init__(self, *unused: object, serial: str = "706", location: str = "0-1",
                 final_location: str | None = None, **unused_keywords: object) -> None:
        self.history = ["/dev/fake"]
        self.serial = serial
        self.location = location
        self.final_location = final_location
        self.port_snapshots = 0

    def resolve(self) -> str:
        return "/dev/fake"

    def _ports(self) -> list[SimpleNamespace]:
        self.port_snapshots += 1
        location = self.location
        if self.final_location is not None and self.port_snapshots >= 2:
            location = self.final_location
        return [SimpleNamespace(
            device="/dev/fake", vid=RUNTIME.DEFAULT_VID, pid=RUNTIME.DEFAULT_PID,
            serial_number=self.serial, location=location,
        )]


def fake_session_type(*, fragmented_version: str = EXPECTED_VERSION,
                      final_version: str = EXPECTED_VERSION,
                      partial_frame: bool = False,
                      config_mismatch: bool = False,
                      error_command: str | None = None,
                      static_frames: bool = False):
    class FakeSession:
        def __init__(self, locator: FakeLocator, store: RUNTIME.RuntimeEvidenceStore) -> None:
            self.locator = locator
            self.store = store
            self.config_counts: dict[str, int] = {}
            self.frame_count = 0

        def connect(self) -> bytes:
            return b"\r\nch> "

        def command_fragmented(self, command: str, fragments: tuple[bytes, ...],
                               timeout: float, fragment_interval: float) -> bytes:
            if command != "version" or b"".join(fragments) != b"version\r":
                raise AssertionError("fragmented version contract was not honored")
            return version_response(fragmented_version)

        def command(self, command: str, timeout: float = 30.0,
                    retry_read_only: bool = False) -> bytes:
            if command == error_command:
                raise OSError("injected transport error")
            if command == "version":
                return version_response(final_version)
            if command in RUNTIME.CONFIG_COMMANDS:
                count = self.config_counts.get(command, 0) + 1
                self.config_counts[command] = count
                value = f"stable-{command}"
                if config_mismatch and command == "color" and count == 2:
                    value = "changed-color"
                return f"{command}\r\n{value}\r\nch> ".encode("ascii")
            return runtime_response(command)

        def capture_frame(self) -> bytes:
            if partial_frame:
                return FRAME[:-2]
            self.frame_count += 1
            if static_frames:
                return FRAME
            frame = bytearray(FRAME)
            frame[-1] = (frame[-1] + self.frame_count) & 0xFF
            return bytes(frame)

        def close(self) -> None:
            pass

    return FakeSession


class UsbRuntimeTests(unittest.TestCase):
    def args(self, output: Path, **overrides: object) -> argparse.Namespace:
        candidate_sha256 = RUNTIME.CORE.sha256_file(SCRIPT)
        flash_evidence = write_flash_evidence(
            output.parent / "flash-evidence", SCRIPT
        )
        values: dict[str, object] = {
            "port": "auto",
            "vid": RUNTIME.DEFAULT_VID,
            "pid": RUNTIME.DEFAULT_PID,
            "expected_usb_serial": "706",
            "expected_usb_location": "0-1",
            "expected_version": EXPECTED_VERSION,
            "candidate_bin": SCRIPT,
            "expected_candidate_sha256": candidate_sha256,
            "flash_evidence": flash_evidence,
            "expected_flash_inventory_sha256": RUNTIME.CORE.sha256_file(
                flash_evidence / "SHA256SUMS"
            ),
            "expected_flash_run_sha256": RUNTIME.CORE.sha256_file(
                flash_evidence / "run.json"
            ),
            "output": output,
            "frames": 2,
            "frame_interval": 1.0,
            "fragment_interval": 0.0,
            "reenumeration_timeout": 1.0,
        }
        values.update(overrides)
        return argparse.Namespace(**values)

    def run_fake(self, output: Path, *, locator: FakeLocator | None = None,
                 session_type: type | None = None, **arg_overrides: object) -> int:
        fake_locator = locator or FakeLocator()
        session = session_type or fake_session_type()
        with mock.patch.object(RUNTIME.CORE, "PortLocator", return_value=fake_locator), \
             mock.patch.object(RUNTIME, "ReadOnlyShellSession", session), \
             mock.patch.object(RUNTIME.time, "sleep", return_value=None):
            return RUNTIME.capture_run(self.args(output, **arg_overrides))

    def test_pass_writes_complete_hash_bound_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "evidence"
            self.assertEqual(self.run_fake(output), 0)
            metadata = __import__("json").loads((output / "run.json").read_text())
            self.assertEqual(metadata["schema"], RUNTIME.USB_RUNTIME_SCHEMA)
            self.assertEqual(metadata["result"], "PASS")
            self.assertTrue(metadata["authentication"]["pass"])
            self.assertTrue(metadata["candidate_binary"]["local_hash_match"])
            self.assertEqual(
                metadata["implementation"]["tool_sha256"],
                RUNTIME.CORE.sha256_file(SCRIPT),
            )
            self.assertEqual(metadata["frames"][0]["bytes"], RUNTIME.PIXEL_BYTES)
            self.assertEqual(metadata["runtime_observations"]["frequency_points"], 450)
            self.assertGreater(metadata["runtime_observations"]["trace_1_metrics"]["range"], 0.1)
            self.assertGreater(
                metadata["runtime_observations"]["trace_1_robust_range_db"], 0.25
            )
            self.assertEqual(metadata["runtime_observations"]["acquisition_state"], "Resumed")
            self.assertTrue(metadata["persisted_config_integrity"]["pass"])
            sums = (output / "SHA256SUMS").read_text()
            for required in ("run.json", "run.log", "run-transcript.md", "frame-01.rgb565be"):
                self.assertIn(required, sums)

    def test_flash_evidence_requires_external_inventory_and_run_pins(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "evidence"
            args = self.args(output)
            args.expected_flash_inventory_sha256 = "0" * 64
            with self.assertRaisesRegex(ValueError, "caller-pinned trust root"):
                RUNTIME.capture_run(args)
            self.assertFalse(output.exists())

    @staticmethod
    def reseal_flash_inventory(root: Path) -> str:
        inventory = root / "SHA256SUMS"
        inventory.unlink()
        members = sorted(path for path in root.iterdir() if path.is_file())
        inventory.write_text(
            "".join(
                f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
                for path in members
            ),
            encoding="utf-8",
        )
        return hashlib.sha256(inventory.read_bytes()).hexdigest()

    def test_reinventoried_payload_or_transcript_tamper_still_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "evidence"
            args = self.args(output)
            (args.flash_evidence / "candidate.readback.bin").write_bytes(b"tampered")
            args.expected_flash_inventory_sha256 = self.reseal_flash_inventory(
                args.flash_evidence
            )
            with self.assertRaisesRegex(ValueError, "staged/readback bytes"):
                RUNTIME.capture_run(args)
            self.assertFalse(output.exists())

            args = self.args(output)
            (args.flash_evidence / "dfu-util-download.stdout.txt").write_bytes(
                b"no success markers\n"
            )
            args.expected_flash_inventory_sha256 = self.reseal_flash_inventory(
                args.flash_evidence
            )
            with self.assertRaisesRegex(ValueError, "download transcript"):
                RUNTIME.capture_run(args)
            self.assertFalse(output.exists())

            args = self.args(output)
            args.expected_flash_run_sha256 = "0" * 64
            with self.assertRaisesRegex(ValueError, "caller-pinned trust root"):
                RUNTIME.capture_run(args)
            self.assertFalse(output.exists())

    def test_forbidden_command_is_rejected(self) -> None:
        RUNTIME.require_read_only_command("data 2")
        for command in (
            "reset", "touch 200 150", "dfu", "save", "correction", "data 0"
        ):
            with self.subTest(command=command), self.assertRaises(ValueError):
                RUNTIME.require_read_only_command(command)

    def test_stale_even_empty_output_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "evidence"
            output.mkdir()
            with self.assertRaises(RuntimeError):
                RUNTIME.capture_run(self.args(output))

    def test_candidate_hash_mismatch_is_rejected_before_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "evidence"
            with self.assertRaises(ValueError):
                RUNTIME.capture_run(self.args(
                    output, expected_candidate_sha256="0" * 64,
                ))
            self.assertFalse(output.exists())

    def test_single_frame_and_nonfinite_intervals_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index, overrides in enumerate((
                {"frames": 1},
                {"frame_interval": float("nan")},
                {"fragment_interval": float("nan")},
                {"reenumeration_timeout": float("nan")},
            )):
                output = root / f"evidence-{index}"
                with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                    RUNTIME.capture_run(self.args(output, **overrides))
                self.assertFalse(output.exists())

    def test_usb_identity_mismatch_fails_before_capture(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "evidence"
            self.assertEqual(self.run_fake(output, locator=FakeLocator(serial="wrong")), 1)
            self.assertEqual(__import__("json").loads((output / "run.json").read_text())["frames"], [])

    def test_exact_version_mismatch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "evidence"
            session = fake_session_type(fragmented_version=EXPECTED_VERSION + "-other")
            self.assertEqual(self.run_fake(output, session_type=session), 1)

    def test_stale_serial_prefix_cannot_authenticate(self) -> None:
        class StalePrefixSession(fake_session_type()):
            def command_fragmented(self, command: str, fragments: tuple[bytes, ...],
                                   timeout: float, fragment_interval: float) -> bytes:
                return b"stale prior command\r\n" + version_response(EXPECTED_VERSION)

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "evidence"
            self.assertEqual(self.run_fake(output, session_type=StalePrefixSession), 1)

    def test_partial_frame_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "evidence"
            self.assertEqual(
                self.run_fake(output, session_type=fake_session_type(partial_frame=True)), 1
            )

    def test_spaced_static_frames_fail_as_frozen(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "evidence"
            self.assertEqual(
                self.run_fake(
                    output,
                    frames=2,
                    session_type=fake_session_type(static_frames=True),
                ),
                1,
            )

    def test_read_error_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "evidence"
            self.assertEqual(
                self.run_fake(output, session_type=fake_session_type(error_command="status")), 1
            )

    def test_final_config_mismatch_fails_and_is_hash_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "evidence"
            self.assertEqual(
                self.run_fake(output, session_type=fake_session_type(config_mismatch=True)), 1
            )
            metadata = __import__("json").loads((output / "run.json").read_text())
            self.assertFalse(metadata["persisted_config_integrity"]["pass"])
            self.assertEqual(metadata["persisted_config_integrity"]["mismatches"], ["color"])

    def test_final_usb_identity_change_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "evidence"
            locator = FakeLocator(final_location="0-2")
            self.assertEqual(self.run_fake(output, locator=locator), 1)

    def test_fragmented_version_writes_exact_chunks(self) -> None:
        class Port:
            def __init__(self) -> None:
                self.writes: list[bytes] = []

            def write(self, payload: bytes) -> None:
                self.writes.append(payload)

            def flush(self) -> None:
                pass

        port = Port()
        session = object.__new__(RUNTIME.ReadOnlyShellSession)
        session.port = port
        session.ensure_connected = lambda: None
        response = version_response(EXPECTED_VERSION)
        with mock.patch.object(RUNTIME.CORE.SCREEN_TOOL, "read_until", return_value=response):
            actual = session.command_fragmented(
                "version", RUNTIME.VERSION_FRAGMENTS, fragment_interval=0.0
            )
        self.assertEqual(actual, response)
        self.assertEqual(port.writes, list(RUNTIME.VERSION_FRAGMENTS))
        RUNTIME.require_exact_version(actual, EXPECTED_VERSION)

    def test_cli_defaults_to_six_frames(self) -> None:
        args = RUNTIME.parse_args([
            "--expected-usb-serial", "706",
            "--expected-usb-location", "0-1",
            "--expected-version", EXPECTED_VERSION,
            "--candidate-bin", str(SCRIPT),
            "--expected-candidate-sha256", RUNTIME.CORE.sha256_file(SCRIPT),
            "--flash-evidence", "unused-flash-evidence",
            "--expected-flash-inventory-sha256", "0" * 64,
            "--expected-flash-run-sha256", "1" * 64,
            "--output", "unused",
        ])
        self.assertEqual(args.frames, 6)
        self.assertEqual(args.frame_interval, 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
