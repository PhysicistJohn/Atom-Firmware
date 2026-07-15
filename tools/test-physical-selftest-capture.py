#!/usr/bin/env python3
"""Hardware-free unit checks for capture-physical-selftests.py."""

from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path
import random
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest


SCRIPT = Path(__file__).with_name("capture-physical-selftests.py")
SPEC = importlib.util.spec_from_file_location("physical_selftest_capture", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

COMPARE_SCRIPT = Path(__file__).with_name("compare-physical-selftest-captures.py")
COMPARE_SPEC = importlib.util.spec_from_file_location(
    "physical_selftest_comparison", COMPARE_SCRIPT
)
assert COMPARE_SPEC is not None and COMPARE_SPEC.loader is not None
COMPARE = importlib.util.module_from_spec(COMPARE_SPEC)
sys.modules[COMPARE_SPEC.name] = COMPARE
COMPARE_SPEC.loader.exec_module(COMPARE)


class CaptureHelpersTest(unittest.TestCase):
    @staticmethod
    def port(device: str, serial: str, location: str = "0-1") -> SimpleNamespace:
        return SimpleNamespace(
            device=device,
            vid=MODULE.DEFAULT_VID,
            pid=MODULE.DEFAULT_PID,
            serial_number=serial,
            location=location,
        )

    def test_explicit_port_is_strict_and_serial_pinned(self) -> None:
        events: list[str] = []
        locator = MODULE.PortLocator(
            "/dev/requested",
            MODULE.DEFAULT_VID,
            MODULE.DEFAULT_PID,
            "706",
            0.1,
            events.append,
        )
        locator._ports = lambda: [
            self.port("/dev/requested", "wrong"),
            self.port("/dev/other", "706"),
        ]
        self.assertEqual(
            [port.device for port in locator._matching_ports()],
            ["/dev/requested"],
        )
        with self.assertRaisesRegex(RuntimeError, "USB serial"):
            locator.resolve()
        self.assertEqual(events, [])

        locator = MODULE.PortLocator(
            "/dev/absent",
            MODULE.DEFAULT_VID,
            MODULE.DEFAULT_PID,
            "706",
            0.1,
            events.append,
        )
        locator._ports = lambda: [self.port("/dev/other", "706")]
        self.assertEqual(locator._matching_ports(), [])

    def test_reenumeration_never_falls_back_from_pinned_serial_to_location(self) -> None:
        locator = MODULE.PortLocator(
            "auto",
            MODULE.DEFAULT_VID,
            MODULE.DEFAULT_PID,
            None,
            0.1,
            lambda unused: None,
        )
        locator.identity = MODULE.UsbIdentity(
            MODULE.DEFAULT_VID, MODULE.DEFAULT_PID, "706", "0-1"
        )
        locator._ports = lambda: [self.port("/dev/replacement", "999", "0-1")]
        self.assertEqual(locator._matching_ports(), [])

    def test_case_parser(self) -> None:
        self.assertEqual(MODULE.parse_case_set("0-2,5,13"), [0, 1, 2, 5, 13])
        with self.assertRaises(ValueError):
            MODULE.parse_case_set("1-0")
        with self.assertRaises(ValueError):
            MODULE.parse_case_set("14")

    def test_panel_order_conversion_and_png(self) -> None:
        # One repeating red/blue pair is enough to prove byte order without a
        # dependency on a PNG image library.
        pixels = MODULE.WIDTH * MODULE.HEIGHT
        frame = (b"\xf8\x00\x00\x1f" * ((pixels + 1) // 2))[:pixels * 2]
        little = MODULE.rgb565be_to_rgb565le(frame)
        self.assertEqual(little[:4], b"\x00\xf8\x1f\x00")
        self.assertEqual(len(little), MODULE.PIXEL_BYTES)
        png = MODULE.rgb565be_to_png(frame)
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertIn(b"IHDR", png)
        self.assertTrue(png.endswith(b"IEND\xaeB`\x82"))

    def test_shell_parsers_and_trace_pack_order(self) -> None:
        frequencies = b"frequencies\r\n100\r\n200\r\nch> "
        self.assertEqual(MODULE.parse_frequency_response(frequencies), [100, 200])
        trace = (
            b"trace 3 value\r\n"
            b"trace 3 value 0 -1.25\r\n"
            b"trace 3 value 1 2.50\r\nch> "
        )
        values = MODULE.parse_trace_response(trace, 3)
        self.assertEqual(values, [-1.25, 2.5])
        self.assertEqual(struct.pack("<2f", *values), b"\x00\x00\xa0\xbf\x00\x00 @")
        data = b"data 0\r\n-1.000000e+00\r\n2.500000e+00\r\nch> "
        self.assertEqual(MODULE.parse_data_response(data), [-1.0, 2.5])

    def test_known_chprintf_etoa_defect_is_narrow_and_trace_checked(self) -> None:
        defects: list[dict[str, object]] = []
        data = b"data 0\r\n-9.500000e+01\r\n-:.000000e+01\r\nch> "
        self.assertEqual(
            MODULE.parse_data_response(data, defects), [-95.0, -100.0]
        )
        self.assertEqual(defects, [{
            "kind": "chprintf-etoa-power-of-ten",
            "point_index": 1,
            "raw_ascii": "-:.000000e+01",
            "decoded_value": -100.0,
        }])
        traces = [[0.0, 0.0] for _ in range(4)]
        traces[3] = [-95.0, -100.0]
        validated = MODULE.validate_data_formatter_defects(0, defects, traces)
        self.assertEqual(validated[0]["mapped_trace"], 4)
        self.assertEqual(validated[0]["trace_cross_check"], "PASS")

        traces[3][1] = -99.5
        with self.assertRaises(AssertionError):
            MODULE.validate_data_formatter_defects(0, defects, traces)

    def test_data_parser_rejects_unknown_malformed_output(self) -> None:
        malformed = b"data 0\r\n-9x.000000e+01\r\nch> "
        with self.assertRaises(AssertionError):
            MODULE.parse_data_response(malformed)

    def test_version_identity_is_exact_and_clean(self) -> None:
        expected = "tinySA4_v0.4-chibios21-rc5"
        MODULE.require_version(
            b"version\r\ntinySA4_v0.4-chibios21-rc5\r\n"
            b"HW Version:V0.5.4 max2871\r\nch> ",
            expected,
        )
        with self.assertRaises(AssertionError):
            MODULE.require_version(
                b"version\r\ntinySA4_v0.4-chibios21-rc5-other\r\nch> ",
                expected,
            )
        with self.assertRaises(AssertionError):
            MODULE.require_version(
                b"stale\r\nversion\r\ntinySA4_v0.4-chibios21-rc5\r\nch> ",
                expected,
            )

    def test_reserved_variant_family_is_bound_to_exact_version(self) -> None:
        MODULE.require_variant_version(
            "official-c979-spur-repeat2",
            "tinySA4_v1.4-224-gc979386",
        )
        MODULE.require_variant_version(
            "rc5-spur-repeat3",
            "tinySA4_v0.4-chibios21-rc5",
        )
        with self.assertRaises(ValueError):
            MODULE.require_variant_version(
                "rc5",
                "tinySA4_v1.4-224-gc979386",
            )

    def test_populated_frame_guard(self) -> None:
        with self.assertRaises(AssertionError):
            MODULE.frame_metrics(bytes(MODULE.PIXEL_BYTES))

    def test_physical_trace_comparison_metrics(self) -> None:
        reference = [-100.0, -90.0, -80.0, -90.0]
        candidate = [-99.5, -89.5, -79.5, -89.5]
        comparison = COMPARE.compare_sequences(reference, candidate)
        self.assertEqual(comparison["exact_points"], 0)
        self.assertAlmostEqual(comparison["mean_delta"], 0.5)
        self.assertAlmostEqual(comparison["rmse"], 0.5)
        self.assertAlmostEqual(comparison["pearson"], 1.0)

    def test_robust_structured_comparison_accepts_independent_noise(self) -> None:
        first = random.Random(407)
        second = random.Random(979)
        envelope = [
            -108.0 + 72.0 * math.exp(-((index - 224.0) / 8.0) ** 2)
            for index in range(COMPARE.TRACE_POINTS)
        ]
        reference = [value + first.uniform(-4.0, 4.0) for value in envelope]
        candidate = [value + second.uniform(-4.0, 4.0) for value in envelope]
        raw = COMPARE.compare_sequences(reference, candidate)
        robust = COMPARE.compare_smoothed_aligned(reference, candidate)
        self.assertGreater(raw["rmse"], COMPARE.STRUCTURED_ALIGNED_RMSE_MAX_DB)
        self.assertGreaterEqual(
            robust["pearson"], COMPARE.STRUCTURED_CORRELATION_MIN
        )
        self.assertLessEqual(
            robust["aligned_rmse_db"],
            COMPARE.STRUCTURED_ALIGNED_RMSE_MAX_DB,
        )

    def test_robust_structured_comparison_rejects_substituted_shape(self) -> None:
        reference = [
            -108.0 + 72.0 * math.exp(-((index - 224.0) / 8.0) ** 2)
            for index in range(COMPARE.TRACE_POINTS)
        ]
        flat = [-108.0] * COMPARE.TRACE_POINTS
        shifted = [
            -108.0 + 72.0 * math.exp(-((index - 244.0) / 8.0) ** 2)
            for index in range(COMPARE.TRACE_POINTS)
        ]
        for candidate in (flat, shifted):
            result = COMPARE.compare_smoothed_aligned(reference, candidate)
            shape_pass = (
                isinstance(result["pearson"], float)
                and result["pearson"] >= COMPARE.STRUCTURED_CORRELATION_MIN
                and result["aligned_rmse_db"]
                <= COMPARE.STRUCTURED_ALIGNED_RMSE_MAX_DB
            )
            self.assertFalse(shape_pass, result)

    def test_robust_range_ignores_one_startup_transient(self) -> None:
        reference = [-36.0] * COMPARE.TRACE_POINTS
        candidate = [-36.0] * COMPARE.TRACE_POINTS
        reference[0] = -54.0
        candidate[0] = -50.0
        self.assertEqual(max(reference) - min(reference), 18.0)
        self.assertEqual(max(candidate) - min(candidate), 14.0)
        self.assertEqual(
            COMPARE.robust_sequence_metrics(reference)["robust_range_q99_q01"],
            0.0,
        )
        self.assertEqual(
            COMPARE.robust_sequence_metrics(candidate)["robust_range_q99_q01"],
            0.0,
        )

    def test_exact_green_factory_pass_literal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "persisted-config").mkdir()
            (root / "persisted-config/before-color.txt").write_bytes(
                b"color\r\n21: 0x00FF00\r\nch> "
            )
            for case in range(1, 15):
                text = f"Test {case}: Pass"
                y = COMPARE.PASS_LITERAL_Y0 + (
                    case - 1
                ) * COMPARE.PASS_LITERAL_SPACING
                on, _ = COMPARE.literal_pixels(
                    text, COMPARE.PASS_LITERAL_X, y
                )
                frame = bytearray(COMPARE.FRAME_BYTES)
                for x, row in on:
                    offset = 2 * (row * 480 + x)
                    frame[offset:offset + 2] = b"\x07\xe0"
                path = root / f"case-{case:02d}.rgb565be"
                path.write_bytes(frame)
                result = COMPARE.inspect_pass_literal(root, case)
                self.assertTrue(result["pass"], result)

                x, row = next(iter(on))
                offset = 2 * (row * 480 + x)
                frame[offset:offset + 2] = b"\x00\x00"
                path.write_bytes(frame)
                self.assertFalse(COMPARE.inspect_pass_literal(root, case)["pass"])

    def test_trace_roi_covers_all_450_display_columns(self) -> None:
        frame = [0] * (COMPARE.VISUAL.WIDTH * COMPARE.VISUAL.HEIGHT)
        for x in range(COMPARE.VISUAL.TRACE_X0, COMPARE.VISUAL.TRACE_X1 + 1):
            frame[100 * COMPARE.VISUAL.WIDTH + x] = COMPARE.VISUAL.TRACE_RGB565
        metrics = COMPARE.VISUAL.frame_metrics(frame)
        self.assertEqual(COMPARE.VISUAL.TRACE_X1, 479)
        self.assertEqual(metrics["trace_active_columns"], COMPARE.TRACE_POINTS)

    def test_zero_span_grid_uses_own_sweep_time(self) -> None:
        sweep_seconds = 0.0557
        layout = COMPARE.VISUAL.expected_time_grid_layout(55_700)
        frame = [0] * (COMPARE.VISUAL.WIDTH * COMPARE.VISUAL.HEIGHT)
        for x in layout["columns"]:
            for y in range(
                COMPARE.VISUAL.TIME_GRID_Y0,
                COMPARE.VISUAL.TIME_GRID_Y1 + 1,
            ):
                frame[y * COMPARE.VISUAL.WIDTH + x] = (
                    COMPARE.VISUAL.TIME_GRID_COLOR
                )
        self.assertTrue(
            COMPARE.zero_span_grid_metrics(frame, sweep_seconds)["pass"]
        )
        wrong = list(frame)
        removed = layout["columns"][-1]
        for y in range(
            COMPARE.VISUAL.TIME_GRID_Y0,
            COMPARE.VISUAL.TIME_GRID_Y1 + 1,
        ):
            wrong[y * COMPARE.VISUAL.WIDTH + removed] = 0
        self.assertFalse(
            COMPARE.zero_span_grid_metrics(wrong, sweep_seconds)["pass"]
        )

    def test_zero_span_grid_allows_shell_rounding_interval(self) -> None:
        displayed_seconds = 0.378
        rounded_layout = COMPARE.VISUAL.expected_time_grid_layout(378_000)
        compatible_layout = COMPARE.VISUAL.expected_time_grid_layout(377_500)
        self.assertNotEqual(
            rounded_layout["columns"], compatible_layout["columns"]
        )
        frame = [0] * (COMPARE.VISUAL.WIDTH * COMPARE.VISUAL.HEIGHT)
        for x in compatible_layout["columns"]:
            for y in range(
                COMPARE.VISUAL.TIME_GRID_Y0,
                COMPARE.VISUAL.TIME_GRID_Y1 + 1,
            ):
                frame[y * COMPARE.VISUAL.WIDTH + x] = (
                    COMPARE.VISUAL.TIME_GRID_COLOR
                )
        metrics = COMPARE.zero_span_grid_metrics(frame, displayed_seconds)
        self.assertTrue(metrics["pass"])
        self.assertIsNotNone(metrics["matched_actual_sweep_time_us"])

    def test_suppression_trace_gate_allows_quieter_nonflat_result(self) -> None:
        self.assertTrue(COMPARE.trace_nonflat_ok(2, 96, 70))
        self.assertTrue(COMPARE.trace_range_ok(2, 25.341, 18.582))
        self.assertFalse(COMPARE.trace_nonflat_ok(2, 96, 0))
        self.assertFalse(COMPARE.trace_range_ok(2, 25.341, 0.0))

    def test_signal_trace_gate_still_requires_reference_coverage(self) -> None:
        self.assertFalse(COMPARE.trace_nonflat_ok(3, 96, 70))
        self.assertFalse(COMPARE.trace_range_ok(3, 25.341, 18.582))

    def test_secondary_response_metric_excludes_main_lobe_guard(self) -> None:
        values = [-100.0] * 80
        values[38:43] = [-50.0, -30.0, -20.0, -30.0, -50.0]
        values[65:68] = [-80.0, -60.0, -80.0]
        frequencies = [1_000_000 + index * 1_000 for index in range(80)]
        metrics = COMPARE.secondary_response_metrics(
            values, frequencies, guard_bins=5
        )
        self.assertEqual(metrics["primary_index"], 40)
        self.assertEqual(metrics["secondary_index"], 66)
        self.assertEqual(metrics["secondary_offset_hz"], 26_000)
        self.assertEqual(metrics["secondary_width_3db_bins"], 1)
        self.assertTrue(metrics["secondary_is_local_peak"])
        self.assertAlmostEqual(metrics["sfdr_db"], 40.0)

    def test_single_sweep_secondary_response_is_never_a_gate(self) -> None:
        reference = {"sfdr_db": 50.0, "secondary_level_dbm": -70.0}
        for case in COMPARE.SFDR_ELIGIBLE_CASES:
            result = COMPARE.compare_secondary_response(
                case, reference,
                {"sfdr_db": 0.0, "secondary_level_dbm": 0.0},
            )
            self.assertTrue(result["pass"])
            self.assertFalse(result["gated"])
            self.assertTrue(result["eligible_with_repeats"])
            self.assertEqual(result["status"], "PENDING")
            self.assertEqual(
                result["minimum_independent_sweeps"],
                COMPARE.SFDR_MINIMUM_INDEPENDENT_SWEEPS,
            )
        for case in (1, 2, 5, 6, 7, 8, 9, 12, 13):
            result = COMPARE.compare_secondary_response(
                case, reference,
                {"sfdr_db": 0.0, "secondary_level_dbm": 0.0},
            )
            self.assertTrue(result["pass"])
            self.assertFalse(result["gated"])
            self.assertFalse(result["eligible_with_repeats"])
            self.assertEqual(result["status"], "DIAGNOSTIC_ONLY")

    def test_secondary_response_rejects_invalid_shapes(self) -> None:
        with self.assertRaises(ValueError):
            COMPARE.secondary_response_metrics([1.0], [1], guard_bins=1)
        with self.assertRaises(ValueError):
            COMPARE.secondary_response_metrics(
                [0.0] * 10, list(range(9)), guard_bins=1
            )

    def test_physical_sweeptime_parses_seconds_and_milliseconds(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shell = root / "case-01-shell"
            shell.mkdir()
            response = shell / "sweeptime.txt"
            response.write_bytes(
                b"sweeptime\r\nusage: sweeptime 0.003..60\r\n1.925s\r\nch> "
            )
            self.assertAlmostEqual(COMPARE.load_sweeptime(root, 1), 1.925)
            response.write_bytes(
                b"sweeptime\r\nusage: sweeptime 0.003..60\r\n 55.6ms\r\nch> "
            )
            self.assertAlmostEqual(COMPARE.load_sweeptime(root, 1), 0.0556)
            response.write_bytes(b"sweeptime\r\nunparseable\r\nch> ")
            self.assertIsNone(COMPARE.load_sweeptime(root, 1))

    def test_ab_qualification_requires_distinct_exact_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            reference = root / "official"
            candidate = root / "rc5"
            checksums = {"sha256": "a" * 64}
            candidate_checksums = {"sha256": "b" * 64}
            reference_metadata = {
                "variant": "official-c979",
                "expected_version": "tinySA4_v1.4-224-gc979386",
                "usb_identity": {
                    "vid": 0x0483,
                    "pid": 0x5740,
                    "serial_number": "400",
                    "location": "0-1",
                },
            }
            candidate_metadata = {
                "variant": "rc5",
                "expected_version": "tinySA4_v0.4-chibios21-rc5",
                "usb_identity": {
                    "vid": 0x0483,
                    "pid": 0x5740,
                    "serial_number": "706",
                    "location": "0-1",
                },
            }
            self.assertEqual(
                COMPARE.qualification_diagnostic_reasons(
                    reference,
                    candidate,
                    checksums,
                    candidate_checksums,
                    reference_metadata,
                    candidate_metadata,
                ),
                [],
            )

            candidate_metadata["variant"] = "rc5-readback-final"
            self.assertEqual(
                COMPARE.qualification_diagnostic_reasons(
                    reference,
                    candidate,
                    checksums,
                    candidate_checksums,
                    reference_metadata,
                    candidate_metadata,
                ),
                [],
            )

            reasons = COMPARE.qualification_diagnostic_reasons(
                reference,
                reference,
                checksums,
                checksums,
                reference_metadata,
                reference_metadata,
            )
            self.assertTrue(any("same capture root" in reason for reason in reasons))
            self.assertTrue(any("inventories are identical" in reason for reason in reasons))
            self.assertTrue(any("versions are identical" in reason for reason in reasons))

            candidate_metadata["usb_identity"]["location"] = "0-2"
            reasons = COMPARE.qualification_diagnostic_reasons(
                reference,
                candidate,
                checksums,
                candidate_checksums,
                reference_metadata,
                candidate_metadata,
            )
            self.assertTrue(any("same test path" in reason for reason in reasons))

    def test_ab_output_must_not_overlap_capture_inventories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            reference = root / "reference"
            candidate = root / "candidate"
            reference.mkdir()
            candidate.mkdir()
            with self.assertRaisesRegex(ValueError, "must not overlap"):
                COMPARE.compare(
                    reference, candidate, reference / "report",
                    "official-c979", "rc5",
                )
            with self.assertRaisesRegex(ValueError, "must not overlap"):
                COMPARE.compare(
                    reference, candidate, root,
                    "official-c979", "rc5",
                )

    def test_cold_boot_attestation_binds_both_capture_inventories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "attestation.json"
            reference = {
                "variant": "official-c979",
                "expected_version": "tinySA4_v1.4-224-gc979386",
                "started_utc": "2026-01-01T00:00:00+00:00",
                "usb_identity": {"location": "0-1"},
            }
            candidate = {
                "variant": "rc5",
                "expected_version": "tinySA4_v0.4-chibios21-rc5",
                "started_utc": "2026-01-01T01:00:00+00:00",
                "usb_identity": {"location": "0-1"},
            }
            document = {
                "schema": "tinysa-physical-cold-boot-attestation-v1",
                "evidence_type": "operator-attested",
                "cal_rf_fixture": "CAL-RF-LOOPBACK-CONNECTED",
                "events": [
                    {
                        "role": "reference",
                        "variant": reference["variant"],
                        "expected_version": reference["expected_version"],
                        "capture_inventory_sha256": "a" * 64,
                        "capture_started_utc": reference["started_utc"],
                        "usb_location": "0-1",
                        "boot_mode": "normal",
                        "minimum_power_off_seconds": 5,
                        "operator_confirmed": True,
                    },
                    {
                        "role": "candidate",
                        "variant": candidate["variant"],
                        "expected_version": candidate["expected_version"],
                        "capture_inventory_sha256": "b" * 64,
                        "capture_started_utc": candidate["started_utc"],
                        "usb_location": "0-1",
                        "boot_mode": "normal",
                        "minimum_power_off_seconds": 5,
                        "operator_confirmed": True,
                    },
                ],
            }
            path.write_text(json.dumps(document), encoding="utf-8")
            result = COMPARE.validate_cold_boot_attestation(
                path,
                reference,
                candidate,
                {"sha256": "a" * 64},
                {"sha256": "b" * 64},
            )
            self.assertEqual(result["evidence_type"], "operator-attested")
            document["events"][1]["minimum_power_off_seconds"] = 4
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "candidate mismatch"):
                COMPARE.validate_cold_boot_attestation(
                    path,
                    reference,
                    candidate,
                    {"sha256": "a" * 64},
                    {"sha256": "b" * 64},
                )


if __name__ == "__main__":
    unittest.main()
