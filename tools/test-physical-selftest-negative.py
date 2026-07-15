#!/usr/bin/env python3
"""Hardware-free checks for capture-physical-selftest-negative.py."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).with_name("capture-physical-selftest-negative.py")
SPEC = importlib.util.spec_from_file_location("physical_selftest_negative", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


COLOR_RESPONSE = (
    b"color\r\nusage: color {id} {rgb24}\r\n"
    b"  0: 0x000000\r\n"
    b" 19: 0x0000F8\r\n"
    b" 20: 0xF88080\r\n"
    b" 21: 0x00FC00\r\nch> "
)


def paint_phase_frame(phase: MODULE.PhaseSpec) -> bytes:
    frame = bytearray(MODULE.CAPTURE.PIXEL_BYTES)
    # Populate an unrelated corner with several colors so the common physical
    # frame guard sees a real-looking, nonblank LCD in the orchestration test.
    colors = (0xFFFF, 0xFFE0, 0x07E0, 0x001F)
    for y in range(40):
        for x in range(40):
            value = colors[(x + y) % len(colors)]
            offset = 2 * (y * MODULE.CAPTURE.WIDTH + x)
            frame[offset] = value >> 8
            frame[offset + 1] = value & 0xFF

    palette = MODULE.parse_palette(COLOR_RESPONSE)
    glyphs = MODULE.load_font_rows()
    for literal in phase.literals:
        value = palette[literal.palette_index]
        on, _ = MODULE.literal_pixels(literal, glyphs)
        for x, y in on:
            offset = 2 * (y * MODULE.CAPTURE.WIDTH + x)
            frame[offset] = value >> 8
            frame[offset + 1] = value & 0xFF
    return bytes(frame)


def frequencies_response() -> bytes:
    values = [29_500_000 + index * 2_227 for index in range(450)]
    return b"frequencies\r\n" + b"\r\n".join(
        str(value).encode("ascii") for value in values
    ) + b"\r\nch> "


def trace_values(phase: str) -> list[float]:
    values = [-100.0] * 450
    values[225] = -90.0 if phase == "disconnected" else -35.3
    return values


def trace_response(trace: int, phase: str) -> bytes:
    lines = [f"trace {trace} value".encode("ascii")]
    lines.extend(
        f"trace {trace} value {index} {value:.2f}".encode("ascii")
        for index, value in enumerate(trace_values(phase))
    )
    return b"\r\n".join(lines) + b"\r\nch> "


def data_response(plane: int, phase: str) -> bytes:
    lines = [f"data {plane}".encode("ascii")]
    lines.extend(f"{value:.6e}".encode("ascii") for value in trace_values(phase))
    return b"\r\n".join(lines) + b"\r\nch> "


class FakeLocator:
    def __init__(self, requested, vid, pid, usb_serial, timeout, event):
        self.history = ["/dev/fake-tinysa"]
        self.identity = MODULE.CAPTURE.UsbIdentity(
            vid, pid, usb_serial or "fake-serial", "fake-location"
        )


class MismatchedLocator(FakeLocator):
    def __init__(self, requested, vid, pid, usb_serial, timeout, event):
        super().__init__(requested, vid, pid, usb_serial, timeout, event)
        self.identity = MODULE.CAPTURE.UsbIdentity(
            vid, pid, "different-serial", "different-location"
        )


class FakeSession:
    instances: list["FakeSession"] = []

    def __init__(self, locator, store):
        self.locator = locator
        self.store = store
        self.phase = store.metadata["phase"]
        self.commands: list[str] = []
        self.frame = paint_phase_frame(MODULE.PHASES[self.phase])
        self.closed = False
        self.__class__.instances.append(self)

    def connect(self) -> bytes:
        return b"ch> "

    def close(self) -> None:
        self.closed = True

    def capture_frame(self) -> bytes:
        return self.frame

    def command(self, command: str, timeout=30.0, retry_read_only=False) -> bytes:
        self.commands.append(command)
        if command == "version":
            expected = self.store.metadata["expected_version"].encode("ascii")
            return b"version\r\n" + expected + b"\r\nch> "
        if command == "info":
            return b"info\r\ntinySA ULTRA+ ZS407\r\nch> "
        if command == "color":
            return COLOR_RESPONSE
        if command.startswith("correction "):
            return command.encode("ascii") + b"\r\n0 1000000 0.00\r\nch> "
        if command == "frequencies":
            return frequencies_response()
        if command.startswith("trace ") and command.endswith(" value"):
            return trace_response(int(command.split()[1]), self.phase)
        if command.startswith("data "):
            return data_response(int(command.split()[1]), self.phase)
        if command == "trace":
            return b"trace\r\ntrace 1 enabled\r\nch> "
        if command in ("sweeptime", "status", "threads"):
            return command.encode("ascii") + b"\r\nmock\r\nch> "
        if command in MODULE.RAM_ONLY_ACTION_COMMANDS:
            return command.encode("ascii") + b"\r\nch> "
        raise AssertionError(f"unexpected fake command: {command}")


class LostTouchSession(FakeSession):
    def command(self, command: str, timeout=30.0, retry_read_only=False) -> bytes:
        if command == "touch 200 150":
            self.commands.append(command)
            raise TimeoutError("injected lost touch response")
        return super().command(command, timeout, retry_read_only)


class DamagedFailureScreenSession(FakeSession):
    def __init__(self, locator, store):
        super().__init__(locator, store)
        glyphs = MODULE.load_font_rows()
        on, _ = MODULE.literal_pixels(
            MODULE.PHASES["disconnected"].literals[0], glyphs
        )
        x, y = next(iter(on))
        damaged = bytearray(self.frame)
        offset = 2 * (y * MODULE.CAPTURE.WIDTH + x)
        damaged[offset : offset + 2] = b"\x00\x00"
        self.frame = bytes(damaged)


def make_args(
    output: Path,
    phase: str,
    prior: Path | None = None,
    confirmation: str | None = None,
) -> argparse.Namespace:
    spec = MODULE.PHASES[phase]
    return argparse.Namespace(
        phase=phase,
        port="auto",
        usb_serial="fake-serial",
        vid=MODULE.CAPTURE.DEFAULT_VID,
        pid=MODULE.CAPTURE.DEFAULT_PID,
        variant="rc5-test",
        expected_version="tinySA4_vtest-rc5",
        output=output,
        prior_disconnected_evidence=prior,
        case_wait=30.0,
        pair_interval=0.75,
        settle_attempts=3,
        settle_retry_wait=5.0,
        ack_hold=1.5,
        reenumeration_timeout=30.0,
        confirm=confirmation if confirmation is not None else spec.confirmation,
    )


class NegativeCaptureTest(unittest.TestCase):
    def setUp(self) -> None:
        FakeSession.instances.clear()

    def test_confirmation_tokens_and_recovery_order_are_mandatory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wrong = make_args(root / "wrong", "disconnected", confirmation="yes")
            with self.assertRaisesRegex(ValueError, MODULE.DISCONNECTED_TOKEN):
                MODULE.validate_arguments(wrong)

            recovery = make_args(root / "recovery", "recovery")
            with self.assertRaisesRegex(ValueError, "prior-disconnected-evidence"):
                MODULE.validate_arguments(recovery)

    def test_exact_version_line_does_not_accept_substrings(self) -> None:
        expected = "tinySA4_vexact"
        MODULE.require_exact_version(
            b"version\r\ntinySA4_vexact\r\nch> ", expected
        )
        with self.assertRaises(AssertionError):
            MODULE.require_exact_version(
                b"version\r\ntinySA4_vexact-extra\r\nch> ", expected
            )
        with self.assertRaises(AssertionError):
            MODULE.require_exact_version(
                b"stale\r\nversion\r\ntinySA4_vexact\r\nch> ", expected
            )
        with self.assertRaises(AssertionError):
            MODULE.require_exact_version(
                b"version\r\ntinySA4_vother\r\ntinySA4_vexact\r\nch> ",
                expected,
            )

    def test_literal_failure_screen_match_is_pixel_exact(self) -> None:
        phase = MODULE.PHASES["disconnected"]
        self.assertEqual(
            phase.literals,
            (
                MODULE.ScreenLiteral(
                    "Test 3: Signal level Fail",
                    55,
                    76,
                    MODULE.BRIGHT_RED_PALETTE_INDEX,
                ),
            ),
        )
        frame = paint_phase_frame(phase)
        result = MODULE.inspect_phase_screen(frame, phase, COLOR_RESPONSE)
        self.assertTrue(result["literal_match"])
        self.assertFalse(result["manual_review_required"])
        self.assertTrue(result["gate"])
        self.assertEqual(result["qualification"], "PASS")

        glyphs = MODULE.load_font_rows()
        on, _ = MODULE.literal_pixels(phase.literals[0], glyphs)
        x, y = next(iter(on))
        damaged = bytearray(frame)
        offset = 2 * (y * MODULE.CAPTURE.WIDTH + x)
        damaged[offset : offset + 2] = b"\x00\x00"
        result = MODULE.inspect_phase_screen(bytes(damaged), phase, COLOR_RESPONSE)
        self.assertFalse(result["literal_match"])
        self.assertTrue(result["manual_review_required"])
        self.assertTrue(result["gate"])
        self.assertEqual(result["qualification"], "FAIL")

    def test_trace_condition_mirrors_firmware_sixty_dbm_branch(self) -> None:
        disconnected = {"trace_metrics": [{"maximum": -60.01}]}
        self.assertTrue(
            MODULE.inspect_trace_condition(
                MODULE.PHASES["disconnected"], disconnected
            )["pass"]
        )
        self.assertIn(
            "0.01 dB",
            MODULE.inspect_trace_condition(
                MODULE.PHASES["disconnected"], disconnected
            )["rounding_caveat"],
        )

    def test_timing_values_must_be_finite_and_safe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = make_args(Path(temporary) / "capture", "disconnected")
            invalid = (
                ("case_wait", float("nan")),
                ("pair_interval", float("inf")),
                ("settle_retry_wait", -0.01),
                ("ack_hold", -1.0),
                ("reenumeration_timeout", 0.0),
            )
            for field, value in invalid:
                args = argparse.Namespace(**vars(base))
                setattr(args, field, value)
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    MODULE.validate_arguments(args)

    def test_usb_identity_matching_is_exact_for_available_stable_fields(self) -> None:
        prior = {
            "vid": 0x0483,
            "pid": 0x5740,
            "serial_number": "400",
            "location": "0-1",
        }
        result = MODULE.require_same_usb_identity(dict(prior), dict(prior))
        self.assertTrue(result["pass"])
        self.assertEqual(
            result["compared_fields"],
            ["vid", "pid", "serial_number", "location"],
        )
        for field, value in (("pid", 0x5741), ("serial_number", "401"), ("location", "0-2")):
            changed = dict(prior)
            changed[field] = value
            with self.subTest(field=field), self.assertRaises(AssertionError):
                MODULE.require_same_usb_identity(changed, prior)
        with self.assertRaises(ValueError):
            MODULE.require_same_usb_identity(
                {**prior, "serial_number": None, "location": None},
                {**prior, "serial_number": None, "location": None},
            )

    def test_prior_and_output_must_not_overlap_in_either_direction(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prior = root / "prior"
            self.assertTrue(MODULE.paths_overlap(prior, prior / "recovery"))
            self.assertTrue(MODULE.paths_overlap(root, prior))
            self.assertFalse(MODULE.paths_overlap(prior, root / "sibling"))
        with self.assertRaises(AssertionError):
            MODULE.inspect_trace_condition(
                MODULE.PHASES["disconnected"],
                {"trace_metrics": [{"maximum": -60.0}]},
            )
        self.assertTrue(
            MODULE.inspect_trace_condition(
                MODULE.PHASES["recovery"],
                {"trace_metrics": [{"maximum": -35.3}]},
            )["pass"]
        )

    def test_shell_allowlist_rejects_persistence_and_dfu_before_io(self) -> None:
        session = MODULE.SafeShellSession(object(), object())
        for command in ("save", "reset", "clearconfig", "correction low 0 1", "dfu"):
            with self.assertRaises(ValueError):
                session.command(command)
        self.assertFalse(
            any(
                command in MODULE.ALLOWED_COMMANDS
                for command in ("save", "reset", "clearconfig", "dfu")
            )
        )

    def test_full_disconnected_then_bound_recovery_flow_without_hardware(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            disconnected = root / "disconnected"
            recovery = root / "recovery"
            with mock.patch.object(MODULE, "PORT_LOCATOR_CLASS", FakeLocator), mock.patch.object(
                MODULE, "SESSION_CLASS", FakeSession
            ), mock.patch.object(MODULE.time, "sleep", return_value=None):
                self.assertEqual(
                    MODULE.capture_run(make_args(disconnected, "disconnected")), 0
                )
                with self.assertRaisesRegex(ValueError, "ancestors, or descendants"):
                    MODULE.validate_arguments(
                        make_args(
                            disconnected / "nested-recovery",
                            "recovery",
                            prior=disconnected,
                        )
                    )
                self.assertEqual(
                    MODULE.capture_run(
                        make_args(recovery, "recovery", prior=disconnected)
                    ),
                    0,
                )

            for evidence, phase in (
                (disconnected, "disconnected"),
                (recovery, "recovery"),
            ):
                metadata = json.loads((evidence / "run.json").read_text())
                self.assertEqual(metadata["result"], "PASS")
                self.assertEqual(metadata["phase"], phase)
                self.assertTrue(metadata["trace_condition"]["pass"])
                self.assertTrue(metadata["persisted_config_integrity"]["pass"])
                self.assertEqual(metadata["cases"][0]["result"], "PASS")
                self.assertTrue(metadata["screen_condition"]["pass"])
                self.assertFalse(
                    metadata["screen_condition"]["manual_review_required"]
                )
                self.assertEqual((evidence / "case-03.rgb565be").stat().st_size, 307200)
                self.assertTrue((evidence / "case-03.png").is_file())
                self.assertTrue(MODULE.validate_checksum_inventory(evidence)["pass"])
                self.assertEqual(
                    metadata["command_policy"]["read_only_capture_transport"][
                        "wire_command"
                    ],
                    "capture",
                )

            recovery_metadata = json.loads((recovery / "run.json").read_text())
            prior = recovery_metadata["prior_disconnected_evidence"]
            self.assertEqual(prior["result"], "PASS")
            self.assertEqual(len(prior["sha256sums_sha256"]), 64)
            self.assertEqual(prior["usb_identity"]["serial_number"], "fake-serial")
            self.assertTrue(recovery_metadata["recovery_usb_identity_binding"]["pass"])
            self.assertEqual(
                MODULE.PHASES["recovery"].literals,
                (
                    MODULE.ScreenLiteral(
                        "Test 3: Pass",
                        55,
                        76,
                        MODULE.BRIGHT_GREEN_PALETTE_INDEX,
                    ),
                ),
            )

            issued = [
                command
                for session in FakeSession.instances
                for command in session.commands
            ]
            self.assertIn("selftest 0 3", issued)
            self.assertIn("touch 200 150", issued)
            self.assertIn("release", issued)
            self.assertTrue(set(issued) <= MODULE.ALLOWED_COMMANDS)

    def test_recovery_identity_mismatch_fails_before_selftest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            disconnected = root / "disconnected"
            recovery = root / "wrong-device"
            with mock.patch.object(MODULE, "PORT_LOCATOR_CLASS", FakeLocator), mock.patch.object(
                MODULE, "SESSION_CLASS", FakeSession
            ), mock.patch.object(MODULE.time, "sleep", return_value=None):
                self.assertEqual(
                    MODULE.capture_run(make_args(disconnected, "disconnected")), 0
                )
            with mock.patch.object(
                MODULE, "PORT_LOCATOR_CLASS", MismatchedLocator
            ), mock.patch.object(MODULE, "SESSION_CLASS", FakeSession), mock.patch.object(
                MODULE.time, "sleep", return_value=None
            ):
                self.assertEqual(
                    MODULE.capture_run(
                        make_args(recovery, "recovery", prior=disconnected)
                    ),
                    1,
                )
            metadata = json.loads((recovery / "run.json").read_text())
            self.assertEqual(metadata["result"], "FAIL")
            self.assertEqual(FakeSession.instances[-1].commands, [])

    def test_disconnected_literal_mismatch_fails_after_safe_release(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "bad-screen"
            with mock.patch.object(MODULE, "PORT_LOCATOR_CLASS", FakeLocator), mock.patch.object(
                MODULE, "SESSION_CLASS", DamagedFailureScreenSession
            ), mock.patch.object(MODULE.time, "sleep", return_value=None):
                self.assertEqual(
                    MODULE.capture_run(make_args(output, "disconnected")), 1
                )
            metadata = json.loads((output / "run.json").read_text())
            self.assertEqual(metadata["result"], "FAIL")
            self.assertFalse(metadata["screen_condition"]["pass"])
            issued = FakeSession.instances[-1].commands
            self.assertIn("release", issued)

    def test_uncertain_touch_fails_but_still_releases(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "lost-touch"
            with mock.patch.object(MODULE, "PORT_LOCATOR_CLASS", FakeLocator), mock.patch.object(
                MODULE, "SESSION_CLASS", LostTouchSession
            ), mock.patch.object(MODULE.time, "sleep", return_value=None):
                self.assertEqual(
                    MODULE.capture_run(make_args(output, "disconnected")), 1
                )
            metadata = json.loads((output / "run.json").read_text())
            self.assertEqual(metadata["result"], "FAIL")
            issued = FakeSession.instances[-1].commands
            self.assertIn("touch 200 150", issued)
            self.assertIn("release", issued)
            self.assertNotIn(
                "ZS407_PHYSICAL_NEGATIVE_ACK=PASS",
                (output / "run.log").read_text(),
            )


if __name__ == "__main__":
    unittest.main()
