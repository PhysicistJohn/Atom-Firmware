#!/usr/bin/env python3
"""Adversarial checks for the self-test visual comparator."""

from __future__ import annotations

import copy
import importlib.util
import math
import struct
import tempfile
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


def synthetic_frame(
    flat: bool = False,
    blank: bool = False,
    grid_columns: list[int] | None = None,
) -> list[int]:
    frame = [0] * (COMPARATOR.WIDTH * COMPARATOR.HEIGHT)
    if blank:
        return frame
    if grid_columns is None:
        grid_columns = list(range(30, 450, 50))
    for x in grid_columns:
        for y in range(COMPARATOR.TIME_GRID_Y1 + 1):
            frame[y * COMPARATOR.WIDTH + x] = COMPARATOR.TIME_GRID_COLOR
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
        "sweep_time_us": 5400,
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


def synthetic_trace_memory(
    raw_delta: float = 0.0, zero_plane: str | None = None
) -> dict[str, object]:
    actual = [-115.0 + 0.02 * index for index in range(COMPARATOR.TRACE_MEMORY_POINTS)]
    traces = {
        "actual": actual,
        "stored": [value + 3.0 for value in actual],
        "stored2": [value - 3.0 for value in actual],
        "raw": list(actual),
    }
    if raw_delta:
        traces["raw"][17] += raw_delta
    if zero_plane is not None:
        traces[zero_plane] = [0.0] * COMPARATOR.TRACE_MEMORY_POINTS
    payload = struct.pack(
        f"<{len(COMPARATOR.TRACE_MEMORY_PLANES) * COMPARATOR.TRACE_MEMORY_POINTS}f",
        *(value for name in COMPARATOR.TRACE_MEMORY_PLANES for value in traces[name]),
    )
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "measured.f32le"
        path.write_bytes(payload)
        return COMPARATOR.load_trace_memory(path)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def failed(result: dict[str, object], name: str) -> bool:
    return any(
        check["name"] == name and not check["pass"]
        for check in result["checks"] + result.get("objective_checks", [])
    )


def compare(
    case: int,
    reference_frame: list[int],
    candidate_frame: list[int],
    mutate=None,
    candidate_trace_memory: dict[str, object] | None = None,
    reference_mutate=None,
) -> dict[str, object]:
    reference_status = status(case, reference_frame)
    candidate_status = status(case, candidate_frame)
    if reference_mutate is not None:
        reference_mutate(reference_status)
    if mutate is not None:
        mutate(candidate_status)
    reference_trace_memory = synthetic_trace_memory()
    if candidate_trace_memory is None:
        candidate_trace_memory = synthetic_trace_memory()
    return COMPARATOR.compare_case(
        case,
        reference_frame,
        candidate_frame,
        reference_status,
        candidate_status,
        reference_trace_memory,
        candidate_trace_memory,
    )


def main() -> int:
    shaped = synthetic_frame()
    flat = synthetic_frame(flat=True)
    blank = synthetic_frame(blank=True)

    valid = compare(3, shaped, copy.copy(shaped))
    require(valid["pass"], "identical populated signal frame must pass")

    def choose_equal_display_maximum(candidate: dict[str, object]) -> None:
        candidate["peak_index"] = 449
        candidate["measured_peak_index"] = 0
        candidate["measured_min"] = -40.0
        candidate["measured_max"] = -40.0
        candidate["dynamic_range_db"] = 0.0
        candidate["mean"] = -40.0
        candidate["stddev"] = 0.0

    for activity_case in (12, 13):
        activity_status = status(activity_case, shaped)
        choose_equal_display_maximum(activity_status)
        require(not COMPARATOR.status_schema_errors(activity_case, activity_status),
                f"flat case {activity_case} may choose different equal-maximum indices")

    signal_status = status(3, shaped)
    signal_status["peak_index"] = 449
    require(any("peak_index=" in error for error in COMPARATOR.status_schema_errors(3, signal_status)),
            "non-flat signal peak-index disagreement was not rejected")

    slower_sweep_result = compare(
        3, shaped, copy.copy(shaped), lambda candidate: candidate.update(sweep_time_us=5401)
    )
    require(not slower_sweep_result["pass"] and failed(slower_sweep_result, "sweep-time-not-slower"),
            "slower candidate sweep time was not rejected")

    zero_sweep_result = compare(
        3, shaped, copy.copy(shaped), lambda candidate: candidate.update(sweep_time_us=0)
    )
    require(not zero_sweep_result["pass"] and failed(zero_sweep_result, "candidate-status-schema"),
            "zero/uninitialized candidate sweep time was not rejected")

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

    raw_mismatch_result = compare(
        3,
        shaped,
        copy.copy(shaped),
        candidate_trace_memory=synthetic_trace_memory(raw_delta=0.25),
    )
    require(
        not raw_mismatch_result["pass"]
        and failed(raw_mismatch_result, "candidate-raw-actual-exact"),
        "RAW/ACTUAL bit mismatch was not rejected",
    )

    empty_stored2_result = compare(
        3,
        shaped,
        copy.copy(shaped),
        candidate_trace_memory=synthetic_trace_memory(zero_plane="stored2"),
    )
    require(
        not empty_stored2_result["pass"]
        and failed(empty_stored2_result, "candidate-trace-memory-complete"),
        "empty STORED2 plane was not rejected",
    )

    # The v0.2 zero-span reference can retain a stale 50-pixel grid. A newer
    # candidate is releasable only when both factory CW cases render the exact
    # formula-derived columns and every remaining delta is attributable to the
    # grid/time readouts.
    stale_time_grid = synthetic_frame(grid_columns=list(range(30, 480, 50)))
    current_5300 = synthetic_frame(
        grid_columns=COMPARATOR.expected_time_grid_layout(5300)["columns"]
    )
    current_17700 = synthetic_frame(
        grid_columns=COMPARATOR.expected_time_grid_layout(17700)["columns"]
    )
    improved_12 = compare(
        12,
        stale_time_grid,
        current_5300,
        lambda candidate: candidate.update(sweep_time_us=5300),
    )
    improved_13 = compare(
        13,
        stale_time_grid,
        current_17700,
        lambda candidate: candidate.update(sweep_time_us=17700),
        reference_mutate=lambda reference: reference.update(sweep_time_us=17800),
    )
    improved_release = COMPARATOR.classify_release([improved_12, improved_13])
    require(
        not improved_12["pass"]
        and not improved_13["pass"]
        and improved_release["pass"]
        and improved_release["mode"] == "mathematically-better-time-grid",
        "exact formula-derived time-grid improvement was not accepted additively",
    )

    def retain_official_write_efficiency(candidate: dict[str, object]) -> None:
        candidate["sweep_time_us"] = 5300
        candidate["case_pixel_writes"] = 198_800

    efficient_grid_result = compare(
        12,
        stale_time_grid,
        current_5300,
        retain_official_write_efficiency,
    )
    require(
        not efficient_grid_result["pass"]
        and COMPARATOR.classify_release([efficient_grid_result, improved_13])["pass"],
        "bounded zero-span write reduction was not accepted",
    )

    def reduce_grid_writes_one_percent(candidate: dict[str, object]) -> None:
        candidate["sweep_time_us"] = 5300
        candidate["case_pixel_writes"] = 198_000

    low_write_grid_result = compare(
        12,
        stale_time_grid,
        current_5300,
        reduce_grid_writes_one_percent,
    )
    require(
        failed(low_write_grid_result, "display-readback-numeric-activity")
        and not COMPARATOR.classify_release([low_write_grid_result, improved_13])["pass"],
        "one-percent zero-span write loss was accepted",
    )

    stale_candidate_12 = compare(12, stale_time_grid, copy.copy(stale_time_grid))
    require(
        not COMPARATOR.classify_release([stale_candidate_12, improved_13])["pass"],
        "stale candidate time grid was accepted",
    )

    arbitrary = copy.copy(current_5300)
    arbitrary[237 * COMPARATOR.WIDTH + 251] = 0xFFFF
    arbitrary_result = compare(
        12,
        stale_time_grid,
        arbitrary,
        lambda candidate: candidate.update(sweep_time_us=5300),
    )
    require(
        failed(arbitrary_result, "time-grid-visual-delta-explained")
        and not COMPARATOR.classify_release([arbitrary_result, improved_13])["pass"],
        "arbitrary non-grid framebuffer difference was accepted",
    )

    flat_current = synthetic_frame(
        flat=True,
        grid_columns=COMPARATOR.expected_time_grid_layout(5300)["columns"],
    )
    flat_grid_result = compare(
        12,
        stale_time_grid,
        flat_current,
        lambda candidate: candidate.update(sweep_time_us=5300),
    )
    require(
        failed(flat_grid_result, "trace-not-degraded-to-flat")
        and not COMPARATOR.classify_release([flat_grid_result, improved_13])["pass"],
        "flat trace was accepted as a time-grid improvement",
    )

    def remove_numeric_display_activity(candidate: dict[str, object]) -> None:
        candidate["sweep_time_us"] = 5300
        candidate["case_display_read_bytes"] = 0
        candidate["case_pixel_writes"] = 100

    inactive_grid_result = compare(
        12,
        stale_time_grid,
        current_5300,
        remove_numeric_display_activity,
    )
    require(
        failed(inactive_grid_result, "display-readback-numeric-activity")
        and not COMPARATOR.classify_release([inactive_grid_result, improved_13])["pass"],
        "grid improvement bypassed numeric display activity",
    )

    mismatched_grid_trace = compare(
        12,
        stale_time_grid,
        current_5300,
        lambda candidate: candidate.update(sweep_time_us=5300),
        candidate_trace_memory=synthetic_trace_memory(raw_delta=0.25),
    )
    require(
        failed(mismatched_grid_trace, "trace-memory-byte-parity")
        and not COMPARATOR.classify_release([mismatched_grid_trace, improved_13])["pass"],
        "grid improvement bypassed four-plane trace parity",
    )

    print("selftest_visual_comparator_adversarial=passed")
    print(
        "rejected=blank,flat-image,trace-erased,trace-columns-5pct,"
        "missing-status,flat-measured-array,wrong-fixture,wrong-cal,"
        "bpf-flatness,display-readback,attenuator-steps,sweep-time,zero-sweep-time,"
        "raw-actual-mismatch,empty-stored2,stale-time-grid,arbitrary-grid-delta,"
        "flat-grid-trace,grid-display-activity,grid-trace-parity"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
