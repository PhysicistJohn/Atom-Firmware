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


if __name__ == "__main__":
    unittest.main()
