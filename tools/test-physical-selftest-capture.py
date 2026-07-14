#!/usr/bin/env python3
"""Hardware-free unit checks for capture-physical-selftests.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import struct
import sys
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

    def test_secondary_response_gate_is_narrowly_scoped(self) -> None:
        reference = {"sfdr_db": 50.0, "secondary_level_dbm": -70.0}
        candidate_ok = {"sfdr_db": 47.0, "secondary_level_dbm": -67.0}
        candidate_bad = {"sfdr_db": 46.99, "secondary_level_dbm": -66.99}
        for case in COMPARE.SFDR_GATED_CASES:
            self.assertTrue(
                COMPARE.compare_secondary_response(
                    case, reference, candidate_ok
                )["pass"]
            )
            self.assertFalse(
                COMPARE.compare_secondary_response(
                    case, reference, candidate_bad
                )["pass"]
            )
        # Broad passbands and the deliberate harmonic case remain diagnostics,
        # even for a deliberately awful synthetic regression.
        for case in (1, 2, 5, 6, 7, 8, 9, 12, 13):
            result = COMPARE.compare_secondary_response(
                case, reference,
                {"sfdr_db": 0.0, "secondary_level_dbm": 0.0},
            )
            self.assertTrue(result["pass"])
            self.assertFalse(result["gated"])

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


if __name__ == "__main__":
    unittest.main()
