#!/usr/bin/env python3
"""Compare all tinySA4 built-in self-test LCD results against a reference.

The framebuffer files are RGB565 little-endian dumps produced by the Renode
ST7796S model.  PNG screenshots are retained for human review; the raw dumps
make the automated comparison independent of PNG encoder details.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import html
import json
import math
import re
import statistics
import struct
import sys
import zlib
from pathlib import Path


WIDTH = 480
HEIGHT = 320
FRAME_BYTES = WIDTH * HEIGHT * 2
CASES = range(1, 15)
TRACE_MEMORY_PLANES = ("actual", "stored", "stored2", "raw")
TRACE_MEMORY_POINTS = 450
TRACE_MEMORY_BYTES = len(TRACE_MEMORY_PLANES) * TRACE_MEMORY_POINTS * 4
POPULATED_TRACE_EPSILON = 0.000001

# The standard tinySA palette's primary trace is yellow.  Shape analysis is
# deliberately limited to the plot rectangle. The top marker banner and
# frequency labels are excluded so yellow text cannot masquerade as a trace.
TRACE_RGB565 = 0xFFE0
TRACE_X0 = 30
# The 450 sweep points occupy columns 30..479 inclusive.  Keeping the final
# thirty columns out of the physical trace mask made a partial trace look more
# complete than it was and disagreed with the zero-span grid geometry below.
TRACE_X1 = 479
TRACE_Y0 = 30
TRACE_Y1 = 309

# Cases 12 and 13 are zero-span tests: their horizontal axis is elapsed sweep
# time rather than frequency.  The pinned v0.2 image can retain grid geometry
# calculated before the completed sweep updates actual_sweep_time_us.  A newer
# image is therefore allowed to differ only when its rendered grid exactly
# matches the same integer formula used by the firmware.
TIME_GRID_CASES = {12, 13}
TIME_GRID_COLOR = 0x8410
TIME_GRID_INTERSECTION_COLOR = 0xFFF0
TIME_GRIDLINES = 6
TIME_GRID_PLOT_WIDTH = 450
TIME_GRID_X0 = 30
TIME_GRID_X1 = 479
TIME_GRID_Y0 = 0
TIME_GRID_Y1 = 309
TIME_GRID_COLUMN_MIN_PIXELS = 100
# The official c979 build and the direct pre-ChibiOS lab descendant can render
# different elapsed-time digit widths. Keep the region and color-pair proof
# strict, require zero unexplained pixels, and allow at most one small glyph's
# additional bounded text delta over the original 160-pixel budget.
TIME_GRID_MAX_TIME_TEXT_DELTA_PIXELS = 192
# RC4 intentionally avoids a redundant zero-span grid redraw. The exact c979
# capture therefore performs 0.5101% more case pixel writes while producing the
# same full readback, trace memory and explained final frame. Preserve a narrow
# symmetric activity band that still rejects a one-percent loss.
DISPLAY_PIXEL_WRITE_RATIO_MIN = 0.994
DISPLAY_PIXEL_WRITE_RATIO_MAX = 1.005
TIME_GRID_ALLOWED_LEGACY_FAILURES = {
    12: {"visual-equivalence", "display-readback-activity"},
    13: {"visual-equivalence"},
}

SUPPRESSION_CASES = {1, 2, 5, 9}
ABOVE_CASES = {6}
CAL_ACTIVE_CASES = {3, 4, 6, 7, 8, 9, 10, 11, 12, 13, 14}
EXPECTED_CAL_HZ = {
    1: 0.0,
    2: 0.0,
    3: 30_000_000.0,
    4: 30_000_000.0,
    5: 0.0,
    6: 30_000_000.0,
    7: 30_000_000.0,
    8: 30_000_000.0,
    9: 15_000_000.0,
    10: 15_000_000.0,
    11: 30_000_000.0,
    12: 30_000_000.0,
    13: 30_000_000.0,
    14: 30_000_000.0,
}
CASE_KIND = {
    1: "suppression",
    2: "suppression",
    3: "signal",
    4: "signal-ultra",
    5: "noise-floor",
    6: "direct-harmonic",
    7: "bpf-loss",
    8: "bpf-flatness",
    9: "lpf-rejection",
    10: "lpf-passband",
    11: "switch-isolation",
    12: "display-readback",
    13: "attenuator-steps",
    14: "lna-gain",
}

STATUS_RE = re.compile(r"ZS407_TWIN_SELFTEST_STATUS\s+(.*)$")
PAIR_RE = re.compile(r"([a-zA-Z0-9_]+)=([^\s]*)")
MEASURED_RE = re.compile(r"^([-+0-9.eE]+)@([0-9]+)$")
CAL_RE = re.compile(r"^([01])@([-+0-9.eE]+)$")
REQUIRED_INTEGER_STATUS = {
    "case",
    "status",
    "peak_hz",
    "peak_index",
    "sweep_time_us",
    "points",
    "width15",
    "populated",
    "finite",
    "samples",
    "fixture",
    "cal_enabled",
    "nonblack",
    "pixel_writes",
    "case_pixel_writes",
    "display_read_bytes",
    "case_display_read_bytes",
    "attenuator_latches",
    "case_attenuator_latches",
    "measured_peak_index",
}
REQUIRED_FLOAT_STATUS = {
    "peak_dbm",
    "measured_peak_dbm",
    "measured_min",
    "measured_max",
    "dynamic_range_db",
    "mean",
    "stddev",
    "cal_hz",
    "attenuation_db",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--reference-bin", type=Path)
    parser.add_argument("--reference-elf", type=Path)
    parser.add_argument("--candidate-bin", type=Path)
    parser.add_argument("--candidate-elf", type=Path)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_frame(path: Path) -> list[int]:
    payload = path.read_bytes()
    if len(payload) != FRAME_BYTES:
        raise ValueError(f"{path} is {len(payload)} bytes; expected {FRAME_BYTES}")
    return list(struct.unpack(f"<{WIDTH * HEIGHT}H", payload))


def load_trace_memory(path: Path) -> dict[str, object]:
    """Decode an observational float32 dump of measured[4][450]."""
    payload = path.read_bytes()
    if len(payload) != TRACE_MEMORY_BYTES:
        raise ValueError(
            f"{path} is {len(payload)} bytes; expected {TRACE_MEMORY_BYTES}"
        )
    value_count = len(TRACE_MEMORY_PLANES) * TRACE_MEMORY_POINTS
    words = struct.unpack(f"<{value_count}I", payload)
    values = struct.unpack(f"<{value_count}f", payload)
    traces: dict[str, dict[str, object]] = {}
    for plane, name in enumerate(TRACE_MEMORY_PLANES):
        start = plane * TRACE_MEMORY_POINTS
        trace_values = values[start : start + TRACE_MEMORY_POINTS]
        finite_values = [value for value in trace_values if math.isfinite(value)]
        traces[name] = {
            "finite": len(finite_values),
            "populated": sum(
                abs(value) > POPULATED_TRACE_EPSILON for value in finite_values
            ),
            "minimum": min(finite_values) if finite_values else None,
            "maximum": max(finite_values) if finite_values else None,
        }

    actual_start = TRACE_MEMORY_PLANES.index("actual") * TRACE_MEMORY_POINTS
    raw_start = TRACE_MEMORY_PLANES.index("raw") * TRACE_MEMORY_POINTS
    exact_mismatches = 0
    nonfinite_pairs = 0
    maximum_delta = 0.0
    for index in range(TRACE_MEMORY_POINTS):
        actual_word = words[actual_start + index]
        raw_word = words[raw_start + index]
        if actual_word != raw_word:
            exact_mismatches += 1
        actual_value = values[actual_start + index]
        raw_value = values[raw_start + index]
        if not math.isfinite(actual_value) or not math.isfinite(raw_value):
            nonfinite_pairs += 1
            continue
        maximum_delta = max(maximum_delta, abs(raw_value - actual_value))

    return {
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
        "format": "float32 little-endian",
        "planes": list(TRACE_MEMORY_PLANES),
        "points_per_plane": TRACE_MEMORY_POINTS,
        "traces": traces,
        "raw_actual": {
            "exact_mismatches": exact_mismatches,
            "nonfinite_pairs": nonfinite_pairs,
            "maximum_absolute_delta": maximum_delta if nonfinite_pairs == 0 else None,
        },
    }


def rgb565_to_rgb(value: int) -> tuple[int, int, int]:
    red = ((value >> 11) & 0x1F) * 255 // 31
    green = ((value >> 5) & 0x3F) * 255 // 63
    blue = (value & 0x1F) * 255 // 31
    return red, green, blue


def frame_metrics(frame: list[int]) -> dict[str, object]:
    colors = collections.Counter(frame)
    trace_rows: dict[int, list[int]] = {}
    for y in range(TRACE_Y0, TRACE_Y1 + 1):
        row = y * WIDTH
        for x in range(TRACE_X0, TRACE_X1 + 1):
            if frame[row + x] == TRACE_RGB565:
                trace_rows.setdefault(x, []).append(y)

    # The topmost primary-trace pixel in a column follows the acquired trace
    # even where the line renderer also draws a long vertical connector.
    profile = {x: min(rows) for x, rows in trace_rows.items()}
    profile_values = list(profile.values())
    if profile_values:
        peak_y = min(profile_values)
        peak_candidates = [x for x, y in profile.items() if y == peak_y]
        peak_x = int(statistics.median(peak_candidates))
        floor_y = float(statistics.median(profile_values))
        vertical_span = max(profile_values) - min(profile_values)
    else:
        peak_y = None
        peak_x = None
        floor_y = None
        vertical_span = 0

    return {
        "sha256": hashlib.sha256(struct.pack(f"<{len(frame)}H", *frame)).hexdigest(),
        "nonblack_pixels": len(frame) - colors[0],
        "unique_colors": len(colors),
        "trace_color": f"0x{TRACE_RGB565:04X}",
        "trace_pixels": sum(len(rows) for rows in trace_rows.values()),
        "trace_active_columns": len(profile),
        "trace_peak_x": peak_x,
        "trace_peak_y": peak_y,
        "trace_floor_y": floor_y,
        "trace_vertical_span": vertical_span,
        "trace_profile": profile,
    }


def expected_time_grid_layout(sweep_time_us: int) -> dict[str, object]:
    """Reproduce plot.c's config.gridlines=6 zero-span integer geometry."""
    if type(sweep_time_us) is not int or sweep_time_us <= 0:
        raise ValueError(f"invalid zero-span sweep time: {sweep_time_us!r}")

    gdigit = 1_000_000_000
    grid = 1
    selected = False
    while gdigit > 1 and not selected:
        for multiplier in (5, 2, 1):
            grid = multiplier * gdigit
            if sweep_time_us // grid >= TIME_GRIDLINES:
                selected = True
                break
        if not selected:
            gdigit //= 10

    # Firmware stores ten-times-pixel spacing so rectangular_grid_x() can
    # represent fractional column intervals with integer modulo arithmetic.
    scaled_width = max(1, TIME_GRID_PLOT_WIDTH * 10 * grid // sweep_time_us)
    columns = [
        TIME_GRID_X0 + local_x
        for local_x in range(TIME_GRID_PLOT_WIDTH)
        if (local_x * 10) % scaled_width < 10
    ]
    return {
        "sweep_time_us": sweep_time_us,
        "gridlines": TIME_GRIDLINES,
        "plot_width": TIME_GRID_PLOT_WIDTH,
        "grid_span_us": grid,
        "scaled_grid_width": scaled_width,
        "columns": columns,
    }


def observed_time_grid_columns(frame: list[int]) -> list[int]:
    """Extract full-height gray vertical grid columns from the plot area."""
    columns = []
    for x in range(TIME_GRID_X0, TIME_GRID_X1 + 1):
        count = sum(
            frame[y * WIDTH + x] == TIME_GRID_COLOR
            for y in range(TIME_GRID_Y0, TIME_GRID_Y1 + 1)
        )
        if count >= TIME_GRID_COLUMN_MIN_PIXELS:
            columns.append(x)
    return columns


def analyze_time_grid_improvement(
    reference: list[int],
    candidate: list[int],
    reference_sweep_time_us: int,
    candidate_sweep_time_us: int,
) -> dict[str, object]:
    reference_expected = expected_time_grid_layout(reference_sweep_time_us)
    candidate_expected = expected_time_grid_layout(candidate_sweep_time_us)
    reference_observed = observed_time_grid_columns(reference)
    candidate_observed = observed_time_grid_columns(candidate)

    # Grid movement may change gray/background pixels and the yellow shade at
    # a trace/grid intersection.  The only other intentional changes are the
    # marker, status-column and footer time readouts.  This pixel classifier
    # prevents an unrelated screen defect from hiding behind a low aggregate
    # similarity score.
    grid_columns = set(reference_observed) | set(candidate_expected["columns"])
    grid_pairs = {
        frozenset((0, TIME_GRID_COLOR)),
        frozenset((TRACE_RGB565, TIME_GRID_INTERSECTION_COLOR)),
    }
    time_text_pairs = {
        frozenset((0, 0xFFFF)),
        frozenset((0, TRACE_RGB565)),
    }
    grid_delta_pixels = 0
    time_text_delta_pixels = 0
    unexplained_count = 0
    unexplained: list[dict[str, object]] = []
    for index, (reference_pixel, candidate_pixel) in enumerate(
        zip(reference, candidate)
    ):
        if reference_pixel == candidate_pixel:
            continue
        x = index % WIDTH
        y = index // WIDTH
        pair = frozenset((reference_pixel, candidate_pixel))
        if y <= TIME_GRID_Y1 and x in grid_columns and pair in grid_pairs:
            grid_delta_pixels += 1
            continue
        in_time_text_region = y < 16 or x < TIME_GRID_X0 or y > TIME_GRID_Y1
        if in_time_text_region and pair in time_text_pairs:
            time_text_delta_pixels += 1
            continue
        unexplained_count += 1
        if len(unexplained) < 16:
            unexplained.append(
                {
                    "x": x,
                    "y": y,
                    "reference": f"0x{reference_pixel:04X}",
                    "candidate": f"0x{candidate_pixel:04X}",
                }
            )

    candidate_current = candidate_observed == candidate_expected["columns"]
    reference_current = reference_observed == reference_expected["columns"]
    delta_explained = (
        unexplained_count == 0
        and time_text_delta_pixels <= TIME_GRID_MAX_TIME_TEXT_DELTA_PIXELS
    )
    return {
        "reference": {
            "expected": reference_expected,
            "observed_columns": reference_observed,
            "current": reference_current,
        },
        "candidate": {
            "expected": candidate_expected,
            "observed_columns": candidate_observed,
            "current": candidate_current,
        },
        "visual_delta": {
            "grid_pixels": grid_delta_pixels,
            "time_text_pixels": time_text_delta_pixels,
            "time_text_pixel_limit": TIME_GRID_MAX_TIME_TEXT_DELTA_PIXELS,
            "unexplained_pixels": unexplained_count,
            "unexplained_examples": unexplained,
            "explained": delta_explained,
        },
        "mathematically_better": candidate_current and not reference_current,
    }


def parse_statuses(path: Path) -> dict[int, dict[str, object]]:
    statuses: dict[int, dict[str, object]] = {}
    for line in path.read_text(errors="replace").splitlines():
        match = STATUS_RE.search(line)
        if not match:
            continue
        fields: dict[str, object] = {
            key: value for key, value in PAIR_RE.findall(match.group(1))
        }
        try:
            case = int(str(fields["case"]))
        except (KeyError, ValueError) as error:
            raise ValueError(f"malformed status line in {path}: {line}") from error

        for key in (
            "case",
            "status",
            "peak_hz",
            "peak_index",
            "sweep_time_us",
            "points",
            "width15",
            "samples",
            "finite",
            "populated",
            "fixture",
            "pixel_writes",
            "case_pixel_writes",
            "display_read_bytes",
            "case_display_read_bytes",
            "attenuator_latches",
            "case_attenuator_latches",
            "nonblack",
        ):
            if key in fields and str(fields[key]):
                fields[key] = int(str(fields[key]))
        for key in (
            "peak_dbm",
            "measured_min",
            "measured_max",
            "dynamic_range_db",
            "mean",
            "stddev",
            "attenuation_db",
        ):
            if key in fields and str(fields[key]):
                fields[key] = float(str(fields[key]))
        measured = MEASURED_RE.match(str(fields.get("measured_peak", "")))
        if measured:
            fields["measured_peak_dbm"] = float(measured.group(1))
            fields["measured_peak_index"] = int(measured.group(2))
        calibration = CAL_RE.match(str(fields.get("cal", "")))
        if calibration:
            fields["cal_enabled"] = int(calibration.group(1))
            fields["cal_hz"] = float(calibration.group(2))
        statuses[case] = fields
    return statuses


def ratio(value: float, reference: float) -> float:
    return value / reference if reference else (1.0 if value == 0 else math.inf)


def compare_profiles(
    reference: dict[int, int], candidate: dict[int, int]
) -> dict[str, float | int | None]:
    ref_columns = set(reference)
    candidate_columns = set(candidate)
    intersection = ref_columns & candidate_columns
    union = ref_columns | candidate_columns
    if intersection:
        errors = [candidate[x] - reference[x] for x in intersection]
        rmse = math.sqrt(sum(error * error for error in errors) / len(errors))
        median_delta = float(statistics.median(errors))
    else:
        rmse = None
        median_delta = None
    return {
        "trace_column_iou": len(intersection) / len(union) if union else 1.0,
        "trace_shape_rmse_px": rmse,
        "trace_shape_median_delta_px": median_delta,
        "trace_common_columns": len(intersection),
    }


def compare_frames(reference: list[int], candidate: list[int]) -> dict[str, object]:
    changed = 0
    content_union = 0
    content_changed = 0
    absolute_rgb_error = 0
    for ref_pixel, candidate_pixel in zip(reference, candidate):
        if ref_pixel != candidate_pixel:
            changed += 1
        if ref_pixel != 0 or candidate_pixel != 0:
            content_union += 1
            if ref_pixel != candidate_pixel:
                content_changed += 1
        ref_rgb = rgb565_to_rgb(ref_pixel)
        candidate_rgb = rgb565_to_rgb(candidate_pixel)
        absolute_rgb_error += sum(
            abs(left - right) for left, right in zip(ref_rgb, candidate_rgb)
        )
    return {
        "changed_pixels": changed,
        "exact_pixel_ratio": 1.0 - changed / len(reference),
        "content_pixel_similarity": (
            1.0 - content_changed / content_union if content_union else 1.0
        ),
        "mean_absolute_rgb_error": absolute_rgb_error / (len(reference) * 3),
    }


def add_check(checks: list[dict[str, object]], name: str, passed: bool, detail: str) -> None:
    checks.append({"name": name, "pass": bool(passed), "detail": detail})


def status_schema_errors(case: int, status: dict[str, object]) -> list[str]:
    errors = []
    for field in sorted(REQUIRED_INTEGER_STATUS):
        if type(status.get(field)) is not int:
            errors.append(f"{field} is missing/not integer")
    for field in sorted(REQUIRED_FLOAT_STATUS):
        if type(status.get(field)) is not float or not math.isfinite(float(status[field])):
            errors.append(f"{field} is missing/not finite float")
    if status.get("case") != case:
        errors.append(f"case={status.get('case')} expected={case}")
    if status.get("points") != 450:
        errors.append(f"points={status.get('points')} expected=450")
    if status.get("cause") != "":
        errors.append(f"cause={status.get('cause')!r} expected empty")
    if not errors:
        if status["finite"] != status["points"] or status["populated"] != status["points"]:
            errors.append(
                f"finite/populated={status['finite']}/{status['populated']} points={status['points']}"
            )
        if int(status["sweep_time_us"]) <= 0:
            errors.append(f"sweep_time_us={status['sweep_time_us']} expected positive")
        if abs(float(status["measured_max"]) - float(status["measured_peak_dbm"])) > 0.011:
            errors.append("measured_max does not equal measured_peak")
        if abs(float(status["dynamic_range_db"]) - (float(status["measured_max"]) - float(status["measured_min"]))) > 0.03:
            errors.append("dynamic_range does not equal max-min")
        if case not in SUPPRESSION_CASES:
            # Some activity-oriented tests leave an intentionally flat
            # measurement array.  Every point is then an equally valid maximum,
            # so live and captured-array scans may select different indices.
            # Their dBm/range and dedicated activity gates remain strict.
            peak_is_unique = float(status["dynamic_range_db"]) > 0.011
            if peak_is_unique and int(status["peak_index"]) != int(status["measured_peak_index"]):
                errors.append(
                    f"peak_index={status['peak_index']} measured_index={status['measured_peak_index']}"
                )
            if abs(float(status["peak_dbm"]) - float(status["measured_peak_dbm"])) > 0.011:
                errors.append(
                    f"peak_dbm={status['peak_dbm']} measured_peak={status['measured_peak_dbm']}"
                )
    return errors


def trace_memory_population_detail(memory: dict[str, object]) -> str:
    traces = memory["traces"]
    return " ".join(
        f"{name}={traces[name]['finite']}/{traces[name]['populated']}"
        for name in TRACE_MEMORY_PLANES
    )


def trace_memory_complete(memory: dict[str, object]) -> bool:
    if (
        memory.get("bytes") != TRACE_MEMORY_BYTES
        or memory.get("points_per_plane") != TRACE_MEMORY_POINTS
        or memory.get("planes") != list(TRACE_MEMORY_PLANES)
    ):
        return False
    traces = memory.get("traces")
    if not isinstance(traces, dict):
        return False
    return all(
        isinstance(traces.get(name), dict)
        and traces[name].get("finite") == TRACE_MEMORY_POINTS
        and traces[name].get("populated") == TRACE_MEMORY_POINTS
        for name in TRACE_MEMORY_PLANES
    )


def raw_actual_exact(memory: dict[str, object]) -> bool:
    comparison = memory.get("raw_actual")
    if not isinstance(comparison, dict):
        return False
    maximum_delta = comparison.get("maximum_absolute_delta")
    return (
        comparison.get("exact_mismatches") == 0
        and comparison.get("nonfinite_pairs") == 0
        and isinstance(maximum_delta, float)
        and math.isfinite(maximum_delta)
        and maximum_delta == 0.0
    )


def compare_case(
    case: int,
    reference_frame: list[int],
    candidate_frame: list[int],
    reference_status: dict[str, object],
    candidate_status: dict[str, object],
    reference_trace_memory: dict[str, object] | None = None,
    candidate_trace_memory: dict[str, object] | None = None,
) -> dict[str, object]:
    reference_metrics = frame_metrics(reference_frame)
    candidate_metrics = frame_metrics(candidate_frame)
    comparison = compare_frames(reference_frame, candidate_frame)
    comparison.update(
        compare_profiles(
            reference_metrics["trace_profile"], candidate_metrics["trace_profile"]
        )
    )
    checks: list[dict[str, object]] = []
    objective_checks: list[dict[str, object]] = []

    reference_schema_errors = status_schema_errors(case, reference_status)
    candidate_schema_errors = status_schema_errors(case, candidate_status)
    add_check(
        checks,
        "reference-status-schema",
        not reference_schema_errors,
        "complete" if not reference_schema_errors else "; ".join(reference_schema_errors),
    )
    add_check(
        checks,
        "candidate-status-schema",
        not candidate_schema_errors,
        "complete" if not candidate_schema_errors else "; ".join(candidate_schema_errors),
    )

    if reference_trace_memory is not None or candidate_trace_memory is not None:
        reference_memory_ok = (
            reference_trace_memory is not None
            and trace_memory_complete(reference_trace_memory)
        )
        candidate_memory_ok = (
            candidate_trace_memory is not None
            and trace_memory_complete(candidate_trace_memory)
        )
        add_check(
            checks,
            "reference-trace-memory-complete",
            reference_memory_ok,
            "missing"
            if reference_trace_memory is None
            else trace_memory_population_detail(reference_trace_memory),
        )
        add_check(
            checks,
            "candidate-trace-memory-complete",
            candidate_memory_ok,
            "missing"
            if candidate_trace_memory is None
            else trace_memory_population_detail(candidate_trace_memory),
        )
        reference_raw_exact = (
            reference_trace_memory is not None
            and raw_actual_exact(reference_trace_memory)
        )
        candidate_raw_exact = (
            candidate_trace_memory is not None
            and raw_actual_exact(candidate_trace_memory)
        )
        add_check(
            checks,
            "reference-raw-actual-exact",
            reference_raw_exact,
            "missing"
            if reference_trace_memory is None
            else (
                f"mismatches={reference_trace_memory['raw_actual']['exact_mismatches']} "
                f"nonfinite={reference_trace_memory['raw_actual']['nonfinite_pairs']} "
                f"max_delta={reference_trace_memory['raw_actual']['maximum_absolute_delta']}"
            ),
        )
        add_check(
            checks,
            "candidate-raw-actual-exact",
            candidate_raw_exact,
            "missing"
            if candidate_trace_memory is None
            else (
                f"mismatches={candidate_trace_memory['raw_actual']['exact_mismatches']} "
                f"nonfinite={candidate_trace_memory['raw_actual']['nonfinite_pairs']} "
                f"max_delta={candidate_trace_memory['raw_actual']['maximum_absolute_delta']}"
            ),
        )
        count_parity = reference_memory_ok and candidate_memory_ok and all(
            reference_trace_memory["traces"][name]["finite"]
            == candidate_trace_memory["traces"][name]["finite"]
            and reference_trace_memory["traces"][name]["populated"]
            == candidate_trace_memory["traces"][name]["populated"]
            for name in TRACE_MEMORY_PLANES
        )
        add_check(
            checks,
            "trace-memory-count-parity",
            count_parity,
            (
                "missing"
                if reference_trace_memory is None or candidate_trace_memory is None
                else f"reference=({trace_memory_population_detail(reference_trace_memory)}) "
                f"candidate=({trace_memory_population_detail(candidate_trace_memory)})"
            ),
        )
        byte_parity = (
            reference_memory_ok
            and candidate_memory_ok
            and reference_trace_memory["sha256"]
            == candidate_trace_memory["sha256"]
        )
        add_check(
            checks,
            "trace-memory-byte-parity",
            byte_parity,
            "missing"
            if reference_trace_memory is None or candidate_trace_memory is None
            else (
                f"reference={reference_trace_memory['sha256']} "
                f"candidate={candidate_trace_memory['sha256']}"
            ),
        )

    add_check(
        checks,
        "reference-status",
        reference_status.get("status") == 1,
        f"reference status={reference_status.get('status')}",
    )
    add_check(
        checks,
        "reference-capture-valid",
        int(reference_metrics["nonblack_pixels"]) >= 1000
        and int(reference_metrics["unique_colors"]) >= 4,
        f"nonblack={reference_metrics['nonblack_pixels']} colors={reference_metrics['unique_colors']}",
    )
    add_check(
        checks,
        "firmware-status",
        candidate_status.get("status") == 1,
        f"candidate status={candidate_status.get('status')}",
    )
    add_check(
        checks,
        "not-blank",
        int(candidate_metrics["nonblack_pixels"]) >= 1000
        and int(candidate_metrics["unique_colors"]) >= 4,
        f"nonblack={candidate_metrics['nonblack_pixels']} colors={candidate_metrics['unique_colors']}",
    )
    add_check(
        checks,
        "fixture-selection",
        candidate_status.get("fixture") == case
        and reference_status.get("fixture") == case,
        f"reference={reference_status.get('fixture')} candidate={candidate_status.get('fixture')} expected={case}",
    )
    expected_calibration = 1 if case in CAL_ACTIVE_CASES else 0
    expected_calibration_hz = EXPECTED_CAL_HZ[case]
    calibration_ok = (
        candidate_status.get("cal_enabled") == expected_calibration
        and reference_status.get("cal_enabled") == expected_calibration
    )
    if expected_calibration:
        reference_cal_hz = reference_status.get("cal_hz")
        candidate_cal_hz = candidate_status.get("cal_hz")
        calibration_ok = calibration_ok and (
            isinstance(reference_cal_hz, float)
            and isinstance(candidate_cal_hz, float)
            and abs(reference_cal_hz - expected_calibration_hz) <= 1.0
            and abs(candidate_cal_hz - expected_calibration_hz) <= 1.0
        )
    else:
        calibration_ok = calibration_ok and (
            reference_status.get("cal_hz") == 0.0
            and candidate_status.get("cal_hz") == 0.0
        )
    add_check(
        checks,
        "cal-fixture-state",
        calibration_ok,
        f"reference={reference_status.get('cal')} candidate={candidate_status.get('cal')} "
        f"expected={expected_calibration}@{expected_calibration_hz:.0f}",
    )

    reference_trace_pixels = int(reference_metrics["trace_pixels"])
    candidate_trace_pixels = int(candidate_metrics["trace_pixels"])
    reference_columns = int(reference_metrics["trace_active_columns"])
    candidate_columns = int(candidate_metrics["trace_active_columns"])
    # Some legitimate suppression cases are clipped below the plot and leave
    # only a handful of trace pixels at its left edge. Do not invent absolute
    # coverage that the original frame does not have; retain at least the
    # reference-relative shape. Signal cases naturally have broad coverage.
    minimum_pixels = math.ceil(reference_trace_pixels * 0.98)
    minimum_columns = math.ceil(reference_columns * 0.98)
    add_check(
        checks,
        "trace-coverage",
        candidate_trace_pixels >= minimum_pixels
        and candidate_columns >= minimum_columns,
        f"pixels={candidate_trace_pixels}/{reference_trace_pixels} "
        f"columns={candidate_columns}/{reference_columns}",
    )

    reference_span = int(reference_metrics["trace_vertical_span"])
    candidate_span = int(candidate_metrics["trace_vertical_span"])
    # A legitimately flat reference is compared by coverage and pixels.  A
    # reference with visible structure may not collapse into a flat line.
    nonflat_ok = reference_span < 5 or candidate_span >= max(3, math.ceil(reference_span * 0.95))
    add_check(
        checks,
        "trace-not-degraded-to-flat",
        nonflat_ok,
        f"vertical_span={candidate_span}px reference={reference_span}px",
    )

    exact = reference_metrics["sha256"] == candidate_metrics["sha256"]
    shape_rmse = comparison["trace_shape_rmse_px"]
    visual_equivalent = exact or (
        float(comparison["content_pixel_similarity"]) >= 0.98
        and float(comparison["trace_column_iou"]) >= 0.99
        and shape_rmse is not None
        and float(shape_rmse) <= 1.0
    )
    add_check(
        checks,
        "visual-equivalence",
        visual_equivalent,
        "exact framebuffer"
        if exact
        else (
            f"content_similarity={comparison['content_pixel_similarity']:.4f} "
            f"trace_iou={comparison['trace_column_iou']:.4f} "
            f"shape_rmse={shape_rmse}"
        ),
    )

    time_grid = None
    reference_sweep_time = reference_status.get("sweep_time_us")
    candidate_sweep_time = candidate_status.get("sweep_time_us")
    if (
        case in TIME_GRID_CASES
        and type(reference_sweep_time) is int
        and type(candidate_sweep_time) is int
        and reference_sweep_time > 0
        and candidate_sweep_time > 0
    ):
        time_grid = analyze_time_grid_improvement(
            reference_frame,
            candidate_frame,
            reference_sweep_time,
            candidate_sweep_time,
        )
        candidate_grid = time_grid["candidate"]
        reference_grid = time_grid["reference"]
        add_check(
            objective_checks,
            "time-grid-current",
            bool(candidate_grid["current"]),
            f"expected={candidate_grid['expected']['columns']} "
            f"observed={candidate_grid['observed_columns']}",
        )
        add_check(
            objective_checks,
            "time-grid-visual-delta-explained",
            bool(time_grid["visual_delta"]["explained"]),
            f"grid_pixels={time_grid['visual_delta']['grid_pixels']} "
            f"time_text_pixels={time_grid['visual_delta']['time_text_pixels']} "
            f"unexplained={time_grid['visual_delta']['unexplained_pixels']} "
            f"reference_current={int(bool(reference_grid['current']))}",
        )

    schema_complete = not reference_schema_errors and not candidate_schema_errors
    ref_peak = reference_status.get("measured_peak_dbm")
    candidate_peak = candidate_status.get("measured_peak_dbm")
    peak_ok = False
    peak_detail = f"candidate={candidate_peak} reference={ref_peak}"
    if schema_complete:
        if case in SUPPRESSION_CASES:
            peak_ok = float(candidate_peak) <= float(ref_peak) + 0.75
            peak_detail += " (lower is better)"
        elif case in ABOVE_CASES:
            peak_ok = float(candidate_peak) >= float(ref_peak) - 0.75
            peak_detail += " (higher is acceptable)"
        else:
            peak_ok = abs(float(candidate_peak) - float(ref_peak)) <= 0.75
    add_check(checks, "measured-peak-level", peak_ok, peak_detail)

    ref_index = reference_status.get("measured_peak_index")
    candidate_index = candidate_status.get("measured_peak_index")
    index_tolerance = 2
    index_ok = schema_complete and abs(int(candidate_index) - int(ref_index)) <= index_tolerance
    add_check(
        checks,
        "measured-peak-position",
        index_ok,
        f"candidate={candidate_index} reference={ref_index} tolerance={index_tolerance}",
    )

    ref_width = reference_status.get("width15")
    candidate_width = candidate_status.get("width15")
    width_tolerance = max(1, math.ceil(int(ref_width) * 0.03)) if schema_complete else 1
    add_check(
        checks,
        "measured-peak-width",
        schema_complete and abs(int(candidate_width) - int(ref_width)) <= width_tolerance,
        f"candidate={candidate_width} reference={ref_width} tolerance={width_tolerance}",
    )

    ref_dynamic = reference_status.get("dynamic_range_db")
    candidate_dynamic = candidate_status.get("dynamic_range_db")
    dynamic_ok = schema_complete and (
        abs(float(candidate_dynamic) - float(ref_dynamic)) <= 0.75
        if float(ref_dynamic) < 2.0
        else float(candidate_dynamic) >= float(ref_dynamic) * 0.95
        and float(candidate_dynamic) <= float(ref_dynamic) * 1.05 + 0.5
    )
    add_check(
        checks,
        "measured-trace-range",
        dynamic_ok,
        f"candidate={candidate_dynamic}dB reference={ref_dynamic}dB",
    )

    reference_samples = reference_status.get("samples")
    candidate_samples = candidate_status.get("samples")
    add_check(
        checks,
        "rf-sample-coverage",
        schema_complete
        and int(candidate_samples) >= math.ceil(int(reference_samples) * 0.95),
        f"candidate={candidate_samples} reference={reference_samples}",
    )

    add_check(
        checks,
        "measured-trace-populated",
        schema_complete
        and candidate_status["finite"] == 450
        and candidate_status["populated"] == 450,
        f"finite={candidate_status.get('finite')} populated={candidate_status.get('populated')} points={candidate_status.get('points')}",
    )
    add_check(
        checks,
        "reference-trace-populated",
        schema_complete
        and reference_status["finite"] == 450
        and reference_status["populated"] == 450,
        f"finite={reference_status.get('finite')} populated={reference_status.get('populated')} points={reference_status.get('points')}",
    )
    add_check(
        checks,
        "frame-counter-consistency",
        schema_complete
        and reference_status["nonblack"] == reference_metrics["nonblack_pixels"]
        and candidate_status["nonblack"] == candidate_metrics["nonblack_pixels"],
        f"reference={reference_status.get('nonblack')}/{reference_metrics['nonblack_pixels']} "
        f"candidate={candidate_status.get('nonblack')}/{candidate_metrics['nonblack_pixels']}",
    )
    add_check(
        checks,
        "global-peak-frequency",
        schema_complete
        and abs(int(candidate_status["peak_hz"]) - int(reference_status["peak_hz"])) <= 1,
        f"candidate={candidate_status.get('peak_hz')} reference={reference_status.get('peak_hz')}",
    )
    add_check(
        checks,
        "sweep-time-not-slower",
        schema_complete
        and int(candidate_status["sweep_time_us"])
        <= int(reference_status["sweep_time_us"]),
        f"candidate={candidate_status.get('sweep_time_us')}us "
        f"reference={reference_status.get('sweep_time_us')}us",
    )

    if case == 8:
        flatness_ok = schema_complete and (
            abs(float(candidate_status["stddev"]) - float(reference_status["stddev"])) <= 0.25
            and abs(int(candidate_status["width15"]) - int(reference_status["width15"])) <= 1
            and abs(float(candidate_status["dynamic_range_db"]) - float(reference_status["dynamic_range_db"])) <= 0.75
            and comparison["trace_shape_rmse_px"] is not None
            and float(comparison["trace_shape_rmse_px"]) <= 1.0
            and float(comparison["trace_column_iou"]) >= 0.99
        )
        add_check(
            checks,
            "bpf-flatness-quality",
            flatness_ok,
            f"stddev={reference_status.get('stddev')}/{candidate_status.get('stddev')} "
            f"width={reference_status.get('width15')}/{candidate_status.get('width15')} "
            f"range={reference_status.get('dynamic_range_db')}/{candidate_status.get('dynamic_range_db')}",
        )
    elif case == 12:
        minimum_display_bytes = WIDTH * HEIGHT * 2
        display_numeric_ok = schema_complete and (
            int(reference_status["case_display_read_bytes"]) >= minimum_display_bytes
            and int(candidate_status["case_display_read_bytes"]) >= minimum_display_bytes
            and abs(
                int(candidate_status["case_display_read_bytes"])
                - int(reference_status["case_display_read_bytes"])
            ) <= 2
            and int(reference_status["case_pixel_writes"]) >= WIDTH * HEIGHT
            and int(candidate_status["case_pixel_writes"]) >= WIDTH * HEIGHT
            and ratio(
                int(candidate_status["case_pixel_writes"]),
                int(reference_status["case_pixel_writes"]),
            ) >= DISPLAY_PIXEL_WRITE_RATIO_MIN
            and ratio(
                int(candidate_status["case_pixel_writes"]),
                int(reference_status["case_pixel_writes"]),
            ) <= DISPLAY_PIXEL_WRITE_RATIO_MAX
        )
        add_check(
            checks,
            "display-readback-numeric-activity",
            display_numeric_ok,
            f"read_bytes={reference_status.get('case_display_read_bytes')}/"
            f"{candidate_status.get('case_display_read_bytes')} pixel_writes="
            f"{reference_status.get('case_pixel_writes')}/{candidate_status.get('case_pixel_writes')}",
        )
        # Preserve the original strict gate.  The additive release classifier
        # may supersede only this embedded similarity term, and only after the
        # numeric activity check and exact time-grid proof above both pass.
        display_ok = display_numeric_ok and float(
            comparison["content_pixel_similarity"]
        ) >= 0.99
        add_check(
            checks,
            "display-readback-activity",
            display_ok,
            f"read_bytes={reference_status.get('case_display_read_bytes')}/"
            f"{candidate_status.get('case_display_read_bytes')} pixel_writes="
            f"{reference_status.get('case_pixel_writes')}/{candidate_status.get('case_pixel_writes')}",
        )
    elif case == 13:
        attenuator_ok = schema_complete and (
            int(reference_status["case_attenuator_latches"]) >= 7
            and int(candidate_status["case_attenuator_latches"])
            == int(reference_status["case_attenuator_latches"])
            and abs(
                float(candidate_status["attenuation_db"])
                - float(reference_status["attenuation_db"])
            ) <= 0.1
            and abs(float(candidate_peak) - float(ref_peak)) <= 0.5
            and comparison["trace_shape_rmse_px"] is not None
            and float(comparison["trace_shape_rmse_px"]) <= 1.0
        )
        add_check(
            checks,
            "attenuator-step-activity",
            attenuator_ok,
            f"case_latches={reference_status.get('case_attenuator_latches')}/"
            f"{candidate_status.get('case_attenuator_latches')} attenuation_db="
            f"{reference_status.get('attenuation_db')}/{candidate_status.get('attenuation_db')}",
        )

    reference_metrics.pop("trace_profile")
    candidate_metrics.pop("trace_profile")
    return {
        "case": case,
        "kind": CASE_KIND[case],
        "pass": all(bool(check["pass"]) for check in checks),
        "exact_framebuffer": exact,
        "reference": {
            "frame": reference_metrics,
            "firmware": reference_status,
            "trace_memory": reference_trace_memory,
        },
        "candidate": {
            "frame": candidate_metrics,
            "firmware": candidate_status,
            "trace_memory": candidate_trace_memory,
        },
        "comparison": comparison,
        "time_grid": time_grid,
        "objective_checks": objective_checks,
        "checks": checks,
    }


def classify_release(results: list[dict[str, object]]) -> dict[str, object]:
    """Classify strict equivalence or a narrowly proven time-grid improvement."""
    strict_pass = all(bool(result["pass"]) for result in results)
    failures = {
        int(result["case"]): [
            str(check["name"])
            for check in result["checks"]
            if not bool(check["pass"])
        ]
        for result in results
    }
    if strict_pass:
        return {
            "pass": True,
            "mode": "strict-equivalent",
            "strict_legacy_pass": True,
            "failures": failures,
            "checks": [
                {
                    "name": "strict-legacy-equivalence",
                    "pass": True,
                    "detail": "all strict per-case gates passed",
                }
            ],
        }

    by_case = {int(result["case"]): result for result in results}
    checks: list[dict[str, object]] = []
    required_present = TIME_GRID_CASES <= set(by_case)
    add_check(
        checks,
        "time-grid-cases-present",
        required_present,
        f"required={sorted(TIME_GRID_CASES)} observed={sorted(by_case)}",
    )

    allowed_only = required_present
    visual_failures_present = required_present
    for case, names in failures.items():
        allowed = TIME_GRID_ALLOWED_LEGACY_FAILURES.get(case, set())
        if not set(names) <= allowed:
            allowed_only = False
    if required_present:
        visual_failures_present = all(
            "visual-equivalence" in failures.get(case, [])
            for case in TIME_GRID_CASES
        )
    add_check(
        checks,
        "only-documented-grid-visual-failures",
        allowed_only and visual_failures_present,
        f"observed={failures} allowed={TIME_GRID_ALLOWED_LEGACY_FAILURES}",
    )

    grid_current = required_present and all(
        isinstance(by_case[case].get("time_grid"), dict)
        and bool(by_case[case]["time_grid"]["candidate"]["current"])
        for case in TIME_GRID_CASES
    )
    baseline_stale = required_present and all(
        isinstance(by_case[case].get("time_grid"), dict)
        and not bool(by_case[case]["time_grid"]["reference"]["current"])
        for case in TIME_GRID_CASES
    )
    deltas_explained = required_present and all(
        isinstance(by_case[case].get("time_grid"), dict)
        and bool(by_case[case]["time_grid"]["visual_delta"]["explained"])
        for case in TIME_GRID_CASES
    )
    add_check(
        checks,
        "candidate-time-grid-mathematically-current",
        grid_current and baseline_stale,
        "candidate matches formula and original is stale"
        if grid_current and baseline_stale
        else f"candidate_current={grid_current} original_stale={baseline_stale}",
    )
    add_check(
        checks,
        "grid-visual-delta-pixel-explained",
        deltas_explained,
        "all changed pixels are grid movement/intersections or bounded time text"
        if deltas_explained
        else "unexplained framebuffer differences remain",
    )

    display_numeric = required_present and any(
        check["name"] == "display-readback-numeric-activity"
        and bool(check["pass"])
        for check in by_case[12]["checks"]
    )
    add_check(
        checks,
        "display-readback-numeric-activity-preserved",
        display_numeric,
        "case 12 read bytes and pixel-write ratio remain strict",
    )

    release_pass = all(bool(check["pass"]) for check in checks)
    return {
        "pass": release_pass,
        "mode": "mathematically-better-time-grid" if release_pass else "rejected",
        "strict_legacy_pass": False,
        "failures": failures,
        "allowed_legacy_failures": {
            str(case): sorted(names)
            for case, names in TIME_GRID_ALLOWED_LEGACY_FAILURES.items()
        },
        "checks": checks,
    }


def png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def write_rgb_png(
    path: Path, pixels: list[tuple[int, int, int]], width: int = WIDTH, height: int = HEIGHT
) -> None:
    if len(pixels) != width * height:
        raise ValueError(f"{path} has {len(pixels)} pixels; expected {width * height}")
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for red, green, blue in pixels[y * width : (y + 1) * width]:
            rows.extend((red, green, blue))
    payload = b"\x89PNG\r\n\x1a\n"
    payload += png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    payload += png_chunk(b"IDAT", zlib.compress(bytes(rows), 9))
    payload += png_chunk(b"IEND", b"")
    path.write_bytes(payload)


def diff_pixels(
    reference: list[int], candidate: list[int]
) -> list[tuple[int, int, int]]:
    pixels: list[tuple[int, int, int]] = []
    for ref_pixel, candidate_pixel in zip(reference, candidate):
        if ref_pixel == candidate_pixel:
            red, green, blue = rgb565_to_rgb(ref_pixel)
            gray = (red * 30 + green * 59 + blue * 11) // 100 // 5
            pixels.append((gray, gray, gray))
            continue
        ref_rgb = rgb565_to_rgb(ref_pixel)
        candidate_rgb = rgb565_to_rgb(candidate_pixel)
        ref_luma = (ref_rgb[0] * 30 + ref_rgb[1] * 59 + ref_rgb[2] * 11) // 100
        candidate_luma = (
            candidate_rgb[0] * 30 + candidate_rgb[1] * 59 + candidate_rgb[2] * 11
        ) // 100
        pixels.append((max(72, ref_luma), candidate_luma, candidate_luma))
    return pixels


def write_diff(path: Path, reference: list[int], candidate: list[int]) -> None:
    write_rgb_png(path, diff_pixels(reference, candidate))


def write_contact_sheet(
    path: Path, frames: list[tuple[list[int], list[int]]]
) -> None:
    width = WIDTH * 3
    height = HEIGHT * len(frames)
    canvas = [(0, 0, 0)] * (width * height)
    for row_index, (reference, candidate) in enumerate(frames):
        sources = (
            [rgb565_to_rgb(pixel) for pixel in reference],
            [rgb565_to_rgb(pixel) for pixel in candidate],
            diff_pixels(reference, candidate),
        )
        for column_index, source in enumerate(sources):
            for y in range(HEIGHT):
                destination = (row_index * HEIGHT + y) * width + column_index * WIDTH
                source_offset = y * WIDTH
                canvas[destination : destination + WIDTH] = source[
                    source_offset : source_offset + WIDTH
                ]
    write_rgb_png(path, canvas, width, height)


def artifact_metadata(paths: dict[str, Path | None]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, path in paths.items():
        if path is not None:
            result[name] = {"path": str(path.resolve()), "sha256": sha256(path)}
    return result


def write_reports(output: Path, report: dict[str, object]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    markdown = [
        "# tinySA4 self-test visual regression",
        "",
        f"Strict legacy overall: **{'PASS' if report['pass'] else 'FAIL'}**",
        f"Release classifier: **{'PASS' if report['release_classification']['pass'] else 'FAIL'}** "
        f"(`{report['release_classification']['mode']}`)",
        "",
        "## Firmware artifacts",
        "",
    ]
    for name, artifact in report["artifacts"].items():
        markdown.append(f"- `{name}`: `{artifact['sha256']}` — `{artifact['path']}`")
    markdown.extend(
        [
        "",
        "## Per-case metrics",
        "",
        "| Case | Kind | Result | Exact | Changed px | Similarity | Trace cols R/C | Span R/C | Peak dBm R/C | Peak index R/C | Width15 R/C | Range dB R/C | Sweep us R/C |",
        "|---:|:---|:---:|:---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for case_result in report["cases"]:
        reference = case_result["reference"]
        candidate = case_result["candidate"]
        ref_peak = reference["firmware"].get("measured_peak_dbm")
        candidate_peak = candidate["firmware"].get("measured_peak_dbm")
        peak_text = (
            f"{ref_peak:.2f}/{candidate_peak:.2f} dBm"
            if isinstance(ref_peak, float) and isinstance(candidate_peak, float)
            else "n/a"
        )
        index_text = (
            f"{reference['firmware'].get('measured_peak_index')}/"
            f"{candidate['firmware'].get('measured_peak_index')}"
        )
        width_text = (
            f"{reference['firmware'].get('width15')}/"
            f"{candidate['firmware'].get('width15')}"
        )
        range_text = (
            f"{reference['firmware'].get('dynamic_range_db')}/"
            f"{candidate['firmware'].get('dynamic_range_db')}"
        )
        sweep_time_text = (
            f"{reference['firmware'].get('sweep_time_us')}/"
            f"{candidate['firmware'].get('sweep_time_us')}"
        )
        markdown.append(
            f"| {case_result['case']} | {case_result['kind']} | {'PASS' if case_result['pass'] else 'FAIL'} | "
            f"{'yes' if case_result['exact_framebuffer'] else 'no'} | "
            f"{case_result['comparison']['changed_pixels']} | "
            f"{case_result['comparison']['content_pixel_similarity']:.4f} | "
            f"{reference['frame']['trace_active_columns']}/{candidate['frame']['trace_active_columns']} | "
            f"{reference['frame']['trace_vertical_span']}/{candidate['frame']['trace_vertical_span']} px | "
            f"{peak_text} | {index_text} | {width_text} | {range_text} | {sweep_time_text} |"
        )
    markdown.extend(
        [
            "",
            "## Post-case trace-memory evidence",
            "",
            "Each A/S/S2/R entry is `finite/populated` for ACTUAL, STORED, STORED2, and RAW/TEMP respectively.",
            "",
            "| Case | Reference A/S/S2/R | Candidate A/S/S2/R | RAW≠ACTUAL exact R/C | Max abs delta R/C |",
            "|---:|:---|:---|---:|---:|",
        ]
    )
    for case_result in report["cases"]:
        reference_memory = case_result["reference"]["trace_memory"]
        candidate_memory = case_result["candidate"]["trace_memory"]
        reference_counts = " ".join(
            f"{reference_memory['traces'][name]['finite']}/{reference_memory['traces'][name]['populated']}"
            for name in TRACE_MEMORY_PLANES
        )
        candidate_counts = " ".join(
            f"{candidate_memory['traces'][name]['finite']}/{candidate_memory['traces'][name]['populated']}"
            for name in TRACE_MEMORY_PLANES
        )
        markdown.append(
            f"| {case_result['case']} | {reference_counts} | {candidate_counts} | "
            f"{reference_memory['raw_actual']['exact_mismatches']}/"
            f"{candidate_memory['raw_actual']['exact_mismatches']} | "
            f"{reference_memory['raw_actual']['maximum_absolute_delta']}/"
            f"{candidate_memory['raw_actual']['maximum_absolute_delta']} |"
        )
    grid_cases = [result for result in report["cases"] if result["time_grid"]]
    if grid_cases:
        markdown.extend(
            [
                "",
                "## Zero-span time-grid evidence",
                "",
                "The expected columns reproduce the firmware's config.gridlines=6, WIDTH=450 integer formula.",
                "",
                "| Case | Sweep us R/C | Scaled width R/C | Original current | Candidate current | Candidate expected columns | Candidate observed columns | Pixel delta explained |",
                "|---:|---:|---:|:---:|:---:|:---|:---|:---:|",
            ]
        )
        for case_result in grid_cases:
            grid = case_result["time_grid"]
            markdown.append(
                f"| {case_result['case']} | "
                f"{grid['reference']['expected']['sweep_time_us']}/"
                f"{grid['candidate']['expected']['sweep_time_us']} | "
                f"{grid['reference']['expected']['scaled_grid_width']}/"
                f"{grid['candidate']['expected']['scaled_grid_width']} | "
                f"{'yes' if grid['reference']['current'] else 'no'} | "
                f"{'yes' if grid['candidate']['current'] else 'no'} | "
                f"{grid['candidate']['expected']['columns']} | "
                f"{grid['candidate']['observed_columns']} | "
                f"{'yes' if grid['visual_delta']['explained'] else 'no'} |"
            )
    markdown.extend(
        [
            "",
            "Red pixels in a diff image are reference-only; cyan pixels are candidate-only. Exact pixels are dimmed gray.",
            "",
        ]
    )
    for case_result in report["cases"]:
        failures = [check for check in case_result["checks"] if not check["pass"]]
        if failures:
            markdown.append(f"## Case {case_result['case']} failures")
            markdown.append("")
            for failure in failures:
                markdown.append(f"- {failure['name']}: {failure['detail']}")
            markdown.append("")
    markdown.extend(
        [
            "## Release-classifier checks",
            "",
        ]
    )
    for check in report["release_classification"]["checks"]:
        markdown.append(
            f"- {'PASS' if check['pass'] else 'FAIL'} `{check['name']}`: {check['detail']}"
        )
    markdown.append("")
    (output / "report.md").write_text("\n".join(markdown))

    rows = []
    for case_result in report["cases"]:
        case = case_result["case"]
        case_details = {
            "visual": case_result["comparison"],
            "time_grid": case_result["time_grid"],
            "time_grid_checks": case_result["objective_checks"],
            "trace_memory": {
                "reference": case_result["reference"]["trace_memory"],
                "candidate": case_result["candidate"]["trace_memory"],
            },
        }
        failed_checks = [
            f"{check['name']}: {check['detail']}"
            for check in case_result["checks"]
            if not check["pass"]
        ]
        rows.append(
            "<section class='case'>"
            f"<h2>Case {case:02d} ({case_result['kind']}): {'PASS' if case_result['pass'] else 'FAIL'}</h2>"
            "<div class='frames'>"
            f"<figure><img src='../reference/case-{case:02d}.png'><figcaption>Original</figcaption></figure>"
            f"<figure><img src='../candidate/case-{case:02d}.png'><figcaption>ChibiOS candidate</figcaption></figure>"
            f"<figure><img src='case-{case:02d}-diff.png'><figcaption>Difference</figcaption></figure>"
            "</div>"
            f"<pre>{html.escape(json.dumps(case_details, indent=2))}</pre>"
            + (
                "<ul>" + "".join(f"<li>{html.escape(item)}</li>" for item in failed_checks) + "</ul>"
                if failed_checks
                else ""
            )
            + "</section>"
        )
    page = f"""<!doctype html>
<meta charset="utf-8">
<title>tinySA4 self-test visual regression</title>
<style>
body {{ background:#111; color:#eee; font:14px system-ui,sans-serif; margin:24px; }}
.summary {{ color:{'#7fda8b' if report['pass'] else '#ff8278'}; }}
.release {{ color:{'#7fda8b' if report['release_classification']['pass'] else '#ff8278'}; }}
.case {{ border-top:1px solid #555; margin-top:28px; padding-top:12px; }}
.frames {{ display:flex; flex-wrap:wrap; gap:16px; }}
figure {{ margin:0; }} img {{ width:480px; max-width:100%; image-rendering:pixelated; border:1px solid #777; }}
figcaption {{ text-align:center; margin-top:4px; }}
pre {{ white-space:pre-wrap; }}
</style>
<h1>tinySA4 self-test visual regression</h1>
<h2 class="summary">Strict legacy: {'PASS' if report['pass'] else 'FAIL'}</h2>
<h2 class="release">Release classifier: {'PASS' if report['release_classification']['pass'] else 'FAIL'} ({html.escape(report['release_classification']['mode'])})</h2>
{''.join(rows)}
"""
    (output / "index.html").write_text(page)


def main() -> int:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    reference_statuses = parse_statuses(args.reference / "run.log")
    candidate_statuses = parse_statuses(args.candidate / "run.log")
    missing_reference = set(CASES) - set(reference_statuses)
    missing_candidate = set(CASES) - set(candidate_statuses)
    if missing_reference or missing_candidate:
        raise ValueError(
            f"missing status reports: reference={sorted(missing_reference)} "
            f"candidate={sorted(missing_candidate)}"
        )

    results = []
    captured_frames: list[tuple[list[int], list[int]]] = []
    for case in CASES:
        reference_png = args.reference / f"case-{case:02d}.png"
        candidate_png = args.candidate / f"case-{case:02d}.png"
        if not reference_png.is_file() or not candidate_png.is_file():
            raise ValueError(f"case {case} screenshot is missing")
        reference_frame = load_frame(args.reference / f"case-{case:02d}.rgb565")
        candidate_frame = load_frame(args.candidate / f"case-{case:02d}.rgb565")
        reference_trace_memory = load_trace_memory(
            args.reference / f"case-{case:02d}-measured.f32le"
        )
        candidate_trace_memory = load_trace_memory(
            args.candidate / f"case-{case:02d}-measured.f32le"
        )
        # Renode's indexed-color PNG encoder can emit a palette that some
        # decoders render almost entirely black even though panel GRAM is
        # complete. Canonicalize both screenshots from the authoritative raw
        # RGB565 capture as truecolor PNG before human review and checksums.
        write_rgb_png(
            reference_png, [rgb565_to_rgb(pixel) for pixel in reference_frame]
        )
        write_rgb_png(
            candidate_png, [rgb565_to_rgb(pixel) for pixel in candidate_frame]
        )
        captured_frames.append((reference_frame, candidate_frame))
        write_diff(args.output / f"case-{case:02d}-diff.png", reference_frame, candidate_frame)
        results.append(
            compare_case(
                case,
                reference_frame,
                candidate_frame,
                reference_statuses[case],
                candidate_statuses[case],
                reference_trace_memory,
                candidate_trace_memory,
            )
        )

    write_contact_sheet(args.output / "contact-cases-01-07.png", captured_frames[:7])
    write_contact_sheet(args.output / "contact-cases-08-14.png", captured_frames[7:])

    strict_pass = all(result["pass"] for result in results)
    release_classification = classify_release(results)
    report = {
        "schema": "tinysa-selftest-visual-regression-v2",
        "pass": strict_pass,
        "release_classification": release_classification,
        "frame": {"width": WIDTH, "height": HEIGHT, "format": "RGB565 little-endian"},
        "trace_roi": {"x0": TRACE_X0, "x1": TRACE_X1, "y0": TRACE_Y0, "y1": TRACE_Y1},
        "artifacts": artifact_metadata(
            {
                "reference_bin": args.reference_bin,
                "reference_elf": args.reference_elf,
                "candidate_bin": args.candidate_bin,
                "candidate_elf": args.candidate_elf,
            }
        ),
        "cases": results,
    }
    write_reports(args.output, report)
    print(f"selftest_visual_regression={'passed' if report['pass'] else 'failed'}")
    print(
        "selftest_release_classifier="
        f"{'passed' if release_classification['pass'] else 'failed'} "
        f"mode={release_classification['mode']}"
    )
    print(f"report={args.output / 'report.md'}")
    print(f"html={args.output / 'index.html'}")
    for result in results:
        comparison = result["comparison"]
        print(
            f"case={result['case']:02d} result={'PASS' if result['pass'] else 'FAIL'} "
            f"exact={int(result['exact_framebuffer'])} "
            f"similarity={comparison['content_pixel_similarity']:.4f} "
            f"trace_iou={comparison['trace_column_iou']:.4f} "
            f"raw_actual_mismatches={result['candidate']['trace_memory']['raw_actual']['exact_mismatches']}"
        )
    return 0 if release_classification["pass"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2)
