#!/usr/bin/env python3
"""Adversarial checks for the self-test visual comparator."""

from __future__ import annotations

import copy
import importlib.util
import math
from pathlib import Path


def load_comparator():
    path = Path(__file__).with_name("compare-selftest-visuals.py")
    spec = importlib.util.spec_from_file_location("selftest_visual_comparator", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


COMPARATOR = load_comparator()


def synthetic_frame(flat: bool = False, blank: bool = False) -> list[int]:
    frame = [0] * (COMPARATOR.WIDTH * COMPARATOR.HEIGHT)
    if blank:
        return frame
    for x in range(30, 450, 50):
        for y in range(COMPARATOR.HEIGHT):
            frame[y * COMPARATOR.WIDTH + x] = 0x8410
    for y in range(0, 310, 31):
        for x in range(30, 450):
            frame[y * COMPARATOR.WIDTH + x] = 0x8410
    for x in range(30, 450):
        y = 200 if flat else 160 + round(55 * math.sin((x - 30) / 35.0))
        frame[y * COMPARATOR.WIDTH + x] = COMPARATOR.TRACE_RGB565
    # Four additional palette colors emulate labels/status text and keep the
    # synthetic screen representative enough for the blank-frame gate.
    for index, color in enumerate((0xFFFF, 0x07E0, 0x001F, 0xF810)):
        for x in range(30 + index * 50, 70 + index * 50):
            frame[(40 + index * 8) * COMPARATOR.WIDTH + x] = color
    return frame


def erase_trace(frame: list[int]) -> list[int]:
    return [0 if pixel == COMPARATOR.TRACE_RGB565 else pixel for pixel in frame]


def remove_trace_columns(frame: list[int], count: int) -> list[int]:
    result = copy.copy(frame)
    for x in range(COMPARATOR.TRACE_X0, COMPARATOR.TRACE_X0 + count):
        for y in range(COMPARATOR.TRACE_Y0, COMPARATOR.TRACE_Y1 + 1):
            offset = y * COMPARATOR.WIDTH + x
            if result[offset] == COMPARATOR.TRACE_RGB565:
                result[offset] = 0
    return result


def status(case: int, frame: list[int]) -> dict[str, object]:
    cal_hz = COMPARATOR.EXPECTED_CAL_HZ[case]
    cal_enabled = int(cal_hz != 0)
    nonblack = COMPARATOR.frame_metrics(frame)["nonblack_pixels"]
    return {
        "case": case,
        "status": 1,
        "peak_dbm": -40.0,
        "peak_hz": 30_000_000,
        "peak_index": 210,
        "points": 450,
        "cause": "",
        "measured_peak_dbm": -40.0,
        "measured_peak_index": 210,
        "width15": 20,
        "measured_min": -100.0,
        "measured_max": -40.0,
        "dynamic_range_db": 60.0,
        "mean": -90.0,
        "stddev": 10.0,
        "populated": 450,
        "finite": 450,
        "samples": 1000,
        "fixture": case,
        "cal": f"{cal_enabled}@{cal_hz:.0f}",
        "cal_enabled": cal_enabled,
        "cal_hz": cal_hz,
        "nonblack": nonblack,
        "pixel_writes": 1_000_000,
        "case_pixel_writes": 200_000,
        "display_read_bytes": 400_000,
        "case_display_read_bytes": 307_520,
        "attenuation_db": 16.0,
        "attenuator_latches": 20,
        "case_attenuator_latches": 7,
    }


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def failed(result: dict[str, object], name: str) -> bool:
    return any(
        check["name"] == name and not check["pass"] for check in result["checks"]
    )


def compare(
    case: int,
    reference_frame: list[int],
    candidate_frame: list[int],
    mutate=None,
) -> dict[str, object]:
    reference_status = status(case, reference_frame)
    candidate_status = status(case, candidate_frame)
    if mutate is not None:
        mutate(candidate_status)
    return COMPARATOR.compare_case(
        case,
        reference_frame,
        candidate_frame,
        reference_status,
        candidate_status,
    )


def main() -> int:
    shaped = synthetic_frame()
    flat = synthetic_frame(flat=True)
    blank = synthetic_frame(blank=True)

    valid = compare(3, shaped, copy.copy(shaped))
    require(valid["pass"], "identical populated signal frame must pass")

    blank_result = compare(3, shaped, blank)
    require(not blank_result["pass"] and failed(blank_result, "not-blank"),
            "blank candidate was not rejected")

    flat_result = compare(3, shaped, flat)
    require(not flat_result["pass"] and failed(flat_result, "trace-not-degraded-to-flat"),
            "flat candidate trace was not rejected")

    erased_result = compare(3, shaped, erase_trace(shaped))
    require(not erased_result["pass"] and failed(erased_result, "trace-coverage"),
            "erased trace was not rejected")

    five_percent_columns = math.ceil(
        COMPARATOR.frame_metrics(shaped)["trace_active_columns"] * 0.05
    )
    column_loss_result = compare(
        3, shaped, remove_trace_columns(shaped, five_percent_columns)
    )
    require(not column_loss_result["pass"] and failed(column_loss_result, "trace-coverage"),
            "five-percent trace-column loss was not rejected")

    missing_result = compare(
        3, shaped, copy.copy(shaped), lambda candidate: candidate.pop("dynamic_range_db")
    )
    require(not missing_result["pass"] and failed(missing_result, "candidate-status-schema"),
            "missing numeric status field was not rejected")

    def flatten_measured_array(candidate: dict[str, object]) -> None:
        candidate["measured_min"] = -40.0
        candidate["measured_max"] = -40.0
        candidate["dynamic_range_db"] = 0.0
        candidate["mean"] = -40.0
        candidate["stddev"] = 0.0

    measured_flat_result = compare(3, shaped, copy.copy(shaped), flatten_measured_array)
    require(not measured_flat_result["pass"] and failed(measured_flat_result, "measured-trace-range"),
            "flat measured array was not rejected")

    fixture_result = compare(
        3, shaped, copy.copy(shaped), lambda candidate: candidate.update(fixture=4)
    )
    require(not fixture_result["pass"] and failed(fixture_result, "fixture-selection"),
            "wrong RF fixture was not rejected")

    def disable_cal(candidate: dict[str, object]) -> None:
        candidate["cal"] = "0@0"
        candidate["cal_enabled"] = 0
        candidate["cal_hz"] = 0.0

    cal_result = compare(3, shaped, copy.copy(shaped), disable_cal)
    require(not cal_result["pass"] and failed(cal_result, "cal-fixture-state"),
            "wrong CAL state was not rejected")

    def degrade_flatness(candidate: dict[str, object]) -> None:
        candidate["width15"] = 30
        candidate["measured_min"] = -90.0
        candidate["dynamic_range_db"] = 50.0
        candidate["stddev"] = 5.0

    flatness_result = compare(8, shaped, flat, degrade_flatness)
    require(not flatness_result["pass"] and failed(flatness_result, "bpf-flatness-quality"),
            "degraded BPF flatness was not rejected")

    def remove_display_activity(candidate: dict[str, object]) -> None:
        candidate["case_display_read_bytes"] = 0
        candidate["case_pixel_writes"] = 100

    display_result = compare(12, shaped, copy.copy(shaped), remove_display_activity)
    require(not display_result["pass"] and failed(display_result, "display-readback-activity"),
            "missing display readback activity was not rejected")

    attenuator_result = compare(
        13,
        shaped,
        copy.copy(shaped),
        lambda candidate: candidate.update(case_attenuator_latches=0),
    )
    require(not attenuator_result["pass"] and failed(attenuator_result, "attenuator-step-activity"),
            "missing attenuator steps were not rejected")

    print("selftest_visual_comparator_adversarial=passed")
    print(
        "rejected=blank,flat-image,trace-erased,trace-columns-5pct,"
        "missing-status,flat-measured-array,wrong-fixture,wrong-cal,"
        "bpf-flatness,display-readback,attenuator-steps"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
