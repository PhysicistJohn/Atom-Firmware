#!/usr/bin/env python3
"""Compare complete physical official/candidate self-test capture inventories."""

from __future__ import annotations

import argparse
import functools
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import statistics
import struct
import sys
from typing import Any


CASES = range(1, 15)
PLANES = ("actual", "stored", "stored2", "raw")
FRAME_BYTES = 480 * 320 * 2
TRACE_POINTS = 450
TRACE_BYTES = len(PLANES) * TRACE_POINTS * 4
SUPPRESSION_CASES = frozenset((1, 2, 5, 9))
ABOVE_CASES = frozenset((6,))
STRUCTURED_CASES = frozenset((3, 4, 6, 7, 8, 10, 11, 14))
# Only these factory cases contain one intended, narrow carrier whose largest
# out-of-lobe response has an unambiguous SFDR interpretation.  The other
# cases are still measured below, but are diagnostic-only: suppression/noise
# tests have no wanted carrier, cases 7/8 are broad filter responses, case 6
# deliberately exercises a harmonic path, and cases 12/13 are zero-span.
SFDR_ELIGIBLE_CASES = frozenset((3, 4, 10, 11, 14))
# 23 bins on either side is just over five percent of a 450-point sweep.  It
# clears the widest official -30 dB carrier lobe (19 bins in case 11) while
# retaining more than 89 percent of every sweep for secondary-response search.
SFDR_GUARD_BINS = 23

# Physical traces are independent RF acquisitions.  A nine-bin boxcar removes
# point-to-point detector noise while retaining features wider than two percent
# of a 450-point sweep.  The thresholds below were checked against the
# same-RC5 case-3 capture/recovery repeat: raw RMSE was 2.605 dB, while the
# filtered, median-offset comparison was 1.034 dB with correlation 0.9949.
# That repeat is diagnostic calibration only, not official-vs-RC5 evidence.
STRUCTURED_SMOOTHING_BINS = 9
STRUCTURED_ALIGNMENT_BINS = 3
STRUCTURED_CORRELATION_MIN = 0.94
STRUCTURED_ALIGNED_RMSE_MAX_DB = 2.0

# All physical result screens should cover almost the complete 450-column plot.
# Existing valid captures contain 417..450 active columns when the complete
# x=30..479 plot is inspected.  Four hundred leaves room for text/grid
# intersections while rejecting blank, truncated, or token traces.
MINIMUM_TRACE_COLUMNS = 400
MINIMUM_TRACE_PIXELS = 400
# Suppression/noise tests have no wanted carrier, so a quieter candidate can
# legitimately have less vertical spread than the reference.  Keep an
# absolute activity floor that is far above a flat/disconnected trace instead
# of requiring it to reproduce a fixed percentage of the reference noise.
MINIMUM_SUPPRESSION_TRACE_SPAN_PIXELS = 20
MINIMUM_SUPPRESSION_ROBUST_RANGE_DB = 5.0

TOOL_PATH = Path(__file__).resolve()
CAPTURE_PATH = TOOL_PATH.with_name("capture-physical-selftests.py")
VISUAL_PATH = TOOL_PATH.with_name("compare-selftest-visuals.py")
FONT_PATH = TOOL_PATH.parents[1] / "Font5x7.c"
FONT_START = 0x16
FONT_HEIGHT = 7
PASS_LITERAL_X = 55
PASS_LITERAL_Y0 = 50
PASS_LITERAL_SPACING = 13
BRIGHT_GREEN_PALETTE_INDEX = 21
SFDR_MINIMUM_INDEPENDENT_SWEEPS = 3
AB_REPORT_SCHEMA = "tinysa-physical-selftest-ab-v3"


def load_tool(name: str, filename: str) -> Any:
    path = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CAPTURE = load_tool("physical_selftest_capture_support", "capture-physical-selftests.py")
VISUAL = load_tool("selftest_visual_compare_support", "compare-selftest-visuals.py")


def parse_palette(response: bytes) -> dict[int, int]:
    """Decode the observed shell palette to exact RGB565 values."""
    palette: dict[int, int] = {}
    pattern = re.compile(rb"[ \t]*([0-9]+):[ \t]*0x([0-9A-Fa-f]{6})[ \t]*")
    for line in response.replace(b"\r", b"").split(b"\n"):
        match = pattern.fullmatch(line)
        if not match:
            continue
        index = int(match.group(1))
        rgb24 = int(match.group(2), 16)
        red = (rgb24 >> 16) & 0xFF
        green = (rgb24 >> 8) & 0xFF
        blue = rgb24 & 0xFF
        palette[index] = ((red >> 3) << 11) | ((green >> 2) << 5) | (blue >> 3)
    return palette


@functools.lru_cache(maxsize=1)
def load_font_rows() -> dict[int, tuple[int, tuple[int, ...]]]:
    """Load the active 5x7 glyph table used by the retained test overlay."""
    source = FONT_PATH.read_text(encoding="utf-8")
    marker = "// Char 0x16 width = 8"
    if marker not in source:
        raise ValueError(f"active font-table marker is missing from {FONT_PATH}")
    active = source.split(marker, 1)[1]
    tokens = re.findall(
        r"^[ \t]*0b([01]{8})(?:\|CW_([0-9]{2}))?,", active, re.MULTILINE
    )
    if not tokens or len(tokens) % FONT_HEIGHT:
        raise ValueError(
            f"active font table has {len(tokens)} rows; expected a multiple of "
            f"{FONT_HEIGHT}"
        )
    glyphs: dict[int, tuple[int, tuple[int, ...]]] = {}
    for glyph_index in range(len(tokens) // FONT_HEIGHT):
        rows: list[int] = []
        for bits, width_macro in tokens[
            glyph_index * FONT_HEIGHT:(glyph_index + 1) * FONT_HEIGHT
        ]:
            value = int(bits, 2)
            if width_macro:
                width = int(width_macro)
                if width < 1 or width > 8:
                    raise ValueError(f"invalid font width macro CW_{width_macro}")
                value |= 8 - width
            rows.append(value)
        width = 8 - (rows[0] & 0x07)
        if width < 1 or width > 8:
            raise ValueError(f"invalid encoded font width {width}")
        glyphs[FONT_START + glyph_index] = (width, tuple(rows))
    return glyphs


def literal_pixels(text: str, x0: int, y0: int) -> tuple[set[tuple[int, int]],
                                                          set[tuple[int, int]]]:
    """Return foreground/background pixels for one exact firmware-font string."""
    glyphs = load_font_rows()
    on: set[tuple[int, int]] = set()
    off: set[tuple[int, int]] = set()
    x = x0
    for character in text:
        code = ord(character)
        if code not in glyphs:
            raise ValueError(f"font table does not contain {character!r} (0x{code:02x})")
        width, rows = glyphs[code]
        for row, bits in enumerate(rows):
            y = y0 + row
            for column in range(width):
                coordinate = (x + column, y)
                if not (0 <= coordinate[0] < 480 and 0 <= y < 320):
                    raise ValueError(f"literal {text!r} leaves the LCD at {coordinate}")
                if bits & (0x80 >> column):
                    on.add(coordinate)
                else:
                    off.add(coordinate)
        x += width
    off.difference_update(on)
    return on, off


def frame_pixel_be(frame: bytes, x: int, y: int) -> int:
    offset = 2 * (y * 480 + x)
    return (frame[offset] << 8) | frame[offset + 1]


def inspect_pass_literal(root: Path, case: int) -> dict[str, Any]:
    """Prove that the retained screen says exact green ``Test N: Pass``.

    A case record marked PASS only proves that capture orchestration completed;
    the firmware's factory verdict is on the LCD.  Bind that verdict to the
    captured frame using the observed palette and exact firmware glyphs.
    """
    frame = (root / f"case-{case:02d}.rgb565be").read_bytes()
    if len(frame) != FRAME_BYTES:
        raise ValueError(f"case {case}: invalid panel frame length {len(frame)}")
    color_path = root / "persisted-config/before-color.txt"
    palette = parse_palette(color_path.read_bytes())
    if BRIGHT_GREEN_PALETTE_INDEX not in palette:
        raise ValueError(
            f"{color_path} has no palette index {BRIGHT_GREEN_PALETTE_INDEX}"
        )
    expected = palette[BRIGHT_GREEN_PALETTE_INDEX]
    text_value = f"Test {case}: Pass"
    y = PASS_LITERAL_Y0 + (case - 1) * PASS_LITERAL_SPACING
    on, off = literal_pixels(text_value, PASS_LITERAL_X, y)
    matched = sum(frame_pixel_be(frame, x, row) == expected for x, row in on)
    off_collisions = sum(
        frame_pixel_be(frame, x, row) == expected for x, row in off
    )
    passed = bool(on) and matched == len(on) and off_collisions == 0
    return {
        "pass": passed,
        "text": text_value,
        "x": PASS_LITERAL_X,
        "y": y,
        "palette_index": BRIGHT_GREEN_PALETTE_INDEX,
        "expected_rgb565": f"0x{expected:04x}",
        "ink_pixels": len(on),
        "matched_ink_pixels": matched,
        "background_pixels": len(off),
        "foreground_collisions_in_background": off_collisions,
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def add_check(checks: list[dict[str, Any]], name: str, passed: bool,
              detail: str) -> None:
    checks.append({"name": name, "pass": bool(passed), "detail": detail})


def trace_nonflat_ok(case: int, reference_span: int, candidate_span: int) -> bool:
    if case in SUPPRESSION_CASES:
        return candidate_span >= MINIMUM_SUPPRESSION_TRACE_SPAN_PIXELS
    return reference_span < 5 or candidate_span >= max(
        3, math.floor(reference_span * 0.80)
    )


def trace_range_ok(case: int, reference_range: float, candidate_range: float) -> bool:
    if case in SUPPRESSION_CASES:
        return (
            candidate_range >= MINIMUM_SUPPRESSION_ROBUST_RANGE_DB
            and candidate_range <= reference_range * 1.15 + 1.0
        )
    if reference_range < 2.0:
        return abs(candidate_range - reference_range) <= 1.0
    return (
        candidate_range >= reference_range * 0.85
        and candidate_range <= reference_range * 1.15 + 1.0
    )


def validate_checksums(root: Path) -> dict[str, Any]:
    inventory = root / "SHA256SUMS"
    if not inventory.is_file():
        raise ValueError(f"missing checksum inventory: {inventory}")
    declared: dict[str, str] = {}
    malformed: list[str] = []
    for line in inventory.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match:
            malformed.append(line)
            continue
        relative = match.group(2)
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts or relative in declared:
            malformed.append(line)
            continue
        declared[relative] = match.group(1)
    actual_paths = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS"
    )
    missing = sorted(set(actual_paths) - set(declared))
    extra = sorted(set(declared) - set(actual_paths))
    mismatched: list[str] = []
    for relative in sorted(set(actual_paths) & set(declared)):
        if sha256_file(root / relative) != declared[relative]:
            mismatched.append(relative)
    return {
        "pass": not malformed and not missing and not extra and not mismatched,
        "sha256": sha256_file(inventory),
        "entries": len(declared),
        "malformed": malformed,
        "missing": missing,
        "extra": extra,
        "mismatched": mismatched,
    }


def load_metadata(root: Path, expected_variant: str | None) -> dict[str, Any]:
    path = root / "run.json"
    required_run_files = (
        "run.log", "run-transcript.md", "device-version-before.txt",
        "device-version-after.txt", "device-info-before.txt",
        "device-info-after.txt",
    )
    missing_run_files = [name for name in required_run_files
                         if not (root / name).is_file()]
    if missing_run_files:
        raise ValueError(f"{root} is missing run evidence: {missing_run_files}")
    metadata = json.loads(path.read_text(encoding="utf-8"))
    if metadata.get("schema") != "tinysa-physical-selftest-capture-v1":
        raise ValueError(f"{path} has an unsupported schema")
    if metadata.get("result") != "PASS":
        raise ValueError(f"{path} is not a completed PASS capture")
    config_integrity = metadata.get("persisted_config_integrity")
    if not isinstance(config_integrity, dict) or not config_integrity.get("pass"):
        raise ValueError(f"{path} lacks passing persisted-config integrity evidence")
    config_commands = config_integrity.get("commands")
    expected_config_commands = [
        "color", *(f"correction {table}" for table in CAPTURE.CORRECTION_TABLES)
    ]
    if config_commands != expected_config_commands:
        raise ValueError(
            f"{path} persisted-config inventory is not the exact 13-command set"
        )
    if config_integrity.get("mismatches") != []:
        raise ValueError(f"{path} declares persisted-config mismatches")
    phase_payloads: dict[str, dict[str, bytes]] = {}
    for phase in ("before", "after"):
        hashes = config_integrity.get(f"{phase}_sha256")
        if not isinstance(hashes, dict):
            raise ValueError(f"{path} has malformed {phase} config hashes")
        if set(hashes) != set(config_commands):
            raise ValueError(f"{path} has an incomplete {phase} config hash set")
        phase_payloads[phase] = {}
        for command in config_commands:
            config_path = root / "persisted-config" / (
                f"{phase}-{CAPTURE.command_slug(command)}.txt"
            )
            if not config_path.is_file():
                raise ValueError(
                    f"{path} persisted-config evidence is missing: {phase} {command}"
                )
            payload = config_path.read_bytes()
            phase_payloads[phase][command] = payload
            if hashes.get(command) != hashlib.sha256(payload).hexdigest():
                raise ValueError(
                    f"{path} persisted-config evidence does not match: {phase} {command}"
                )
    changed_commands = [
        command for command in config_commands
        if phase_payloads["before"][command] != phase_payloads["after"][command]
    ]
    if changed_commands:
        raise ValueError(
            f"{path} persisted config changed despite PASS metadata: {changed_commands}"
        )
    if expected_variant is not None and metadata.get("variant") != expected_variant:
        raise ValueError(
            f"{path} variant is {metadata.get('variant')!r}, expected {expected_variant!r}"
        )
    variant = metadata.get("variant")
    expected_version = metadata.get("expected_version")
    if not isinstance(variant, str) or not isinstance(expected_version, str):
        raise ValueError(f"{path} lacks string variant/version provenance")
    CAPTURE.require_variant_version(variant, expected_version)
    for name in ("device-version-before.txt", "device-version-after.txt"):
        try:
            CAPTURE.require_version((root / name).read_bytes(), expected_version)
        except AssertionError as error:
            raise ValueError(f"{root / name} does not authenticate the capture: {error}") from error
    records = metadata.get("cases")
    if not isinstance(records, list) or len(records) != 14:
        raise ValueError(f"{path} does not contain fourteen case records")
    by_case: dict[int, dict[str, Any]] = {}
    for record in records:
        case = record.get("selftest_argument")
        zero_based = record.get("zero_based_case")
        if type(case) is not int or case not in CASES or zero_based != case - 1:
            raise ValueError(f"{path} contains an invalid case record: {record!r}")
        if record.get("result") != "PASS" or case in by_case:
            raise ValueError(f"{path} case {case} is incomplete or duplicated")
        by_case[case] = record
    if set(by_case) != set(CASES):
        raise ValueError(f"{path} case inventory is incomplete")
    metadata["case_records"] = by_case
    return metadata


def load_frequencies(root: Path, case: int) -> list[int]:
    path = root / f"case-{case:02d}-shell/frequencies.txt"
    values = CAPTURE.parse_frequency_response(path.read_bytes())
    if len(values) != TRACE_POINTS:
        raise ValueError(f"{path} has {len(values)} points; expected {TRACE_POINTS}")
    return values


def load_sweeptime(root: Path, case: int) -> float | None:
    path = root / f"case-{case:02d}-shell/sweeptime.txt"
    response = path.read_bytes().replace(b"\r", b"")
    matches = re.findall(
        rb"(?:^|\n)[ \t]*([0-9]+(?:\.[0-9]+)?)(ms|s)[ \t]*(?:\n|ch> )",
        response,
    )
    if not matches:
        return None
    value, unit = matches[-1]
    seconds = float(value)
    return seconds / 1000.0 if unit == b"ms" else seconds


def zero_span_grid_metrics(frame: list[int], sweeptime_seconds: float) -> dict[str, Any]:
    """Validate a grid against the precision of the shell's sweep-time text.

    The renderer uses ``actual_sweep_time_us`` while the shell rounds that
    value to milliseconds.  Near an integer grid-width boundary, treating the
    displayed value as an exact microsecond value can therefore move alternate
    grid columns by one pixel.  Admit only layouts produced by an underlying
    microsecond value inside the displayed value's half-millisecond rounding
    interval.
    """
    sweep_time_us = int(round(sweeptime_seconds * 1_000_000.0))
    expected = VISUAL.expected_time_grid_layout(sweep_time_us)
    observed = VISUAL.observed_time_grid_columns(frame)
    compatible: dict[tuple[int, ...], int] = {}
    for actual_us in range(max(1, sweep_time_us - 500), sweep_time_us + 501):
        layout = VISUAL.expected_time_grid_layout(actual_us)
        compatible.setdefault(tuple(layout["columns"]), actual_us)
    matched_us = compatible.get(tuple(observed))
    return {
        "pass": matched_us is not None,
        "sweep_time_us": sweep_time_us,
        "expected_columns": expected["columns"],
        "observed_columns": observed,
        "compatible_actual_sweep_time_us": [
            max(1, sweep_time_us - 500), sweep_time_us + 500
        ],
        "compatible_layout_count": len(compatible),
        "matched_actual_sweep_time_us": matched_us,
    }


def load_trace_planes(root: Path, case: int) -> list[list[float]]:
    path = root / f"case-{case:02d}-measured.f32le"
    payload = path.read_bytes()
    if len(payload) != TRACE_BYTES:
        raise ValueError(f"{path} has {len(payload)} bytes; expected {TRACE_BYTES}")
    values = struct.unpack(f"<{len(PLANES) * TRACE_POINTS}f", payload)
    planes = [
        list(values[plane * TRACE_POINTS:(plane + 1) * TRACE_POINTS])
        for plane in range(len(PLANES))
    ]
    shell_values = [
        CAPTURE.parse_trace_response(
            (root / f"case-{case:02d}-shell/trace-{trace}-value.txt").read_bytes(),
            trace,
        )
        for trace in range(1, 5)
    ]
    shell_payload = struct.pack(
        f"<{len(PLANES) * TRACE_POINTS}f",
        *(value for plane in shell_values for value in plane),
    )
    if shell_payload != payload:
        raise ValueError(
            f"{path} does not exactly match the four retained shell trace responses"
        )
    return planes


def validate_shell_evidence(root: Path, case: int) -> dict[str, Any]:
    shell = root / f"case-{case:02d}-shell"
    required = [f"{CAPTURE.command_slug(command)}.txt"
                for command in CAPTURE.EVIDENCE_COMMANDS]
    missing = [name for name in required if not (shell / name).is_file()]
    data_points = []
    if not missing:
        for plane in range(3):
            values = CAPTURE.parse_data_response((shell / f"data-{plane}.txt").read_bytes())
            data_points.append(len(values))
    status = (shell / "status.txt").read_bytes() if (shell / "status.txt").is_file() else b""
    threads = (shell / "threads.txt").read_bytes() if (shell / "threads.txt").is_file() else b""
    valid = (
        not missing
        and data_points == [TRACE_POINTS, TRACE_POINTS, TRACE_POINTS]
        and status.endswith(CAPTURE.PROMPT)
        and threads.endswith(CAPTURE.PROMPT)
        and b"stklimit" in threads
    )
    return {
        "pass": valid,
        "missing": missing,
        "data_points": data_points,
        "status_prompt": status.endswith(CAPTURE.PROMPT),
        "threads_prompt": threads.endswith(CAPTURE.PROMPT),
        "threads_header": b"stklimit" in threads,
    }


def sequence_metrics(values: list[float]) -> dict[str, Any]:
    finite = [value for value in values if math.isfinite(value)]
    if not finite:
        return {
            "points": len(values), "finite": 0, "populated": 0,
            "minimum": None, "maximum": None, "range": None,
            "mean": None, "stddev": None, "peak_index": None,
        }
    maximum = max(finite)
    return {
        "points": len(values),
        "finite": len(finite),
        "populated": sum(abs(value) > 0.000001 for value in finite),
        "minimum": min(finite),
        "maximum": maximum,
        "range": maximum - min(finite),
        "mean": statistics.fmean(finite),
        "stddev": statistics.pstdev(finite),
        "peak_index": values.index(maximum),
    }


def quantile(values: list[float], fraction: float) -> float:
    """Return a linearly interpolated finite-sample quantile."""
    if not 0.0 <= fraction <= 1.0:
        raise ValueError(f"quantile fraction is outside 0..1: {fraction}")
    ordered = sorted(value for value in values if math.isfinite(value))
    if not ordered:
        raise ValueError("quantile requires at least one finite value")
    position = (len(ordered) - 1) * fraction
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return float(ordered[lower])
    weight = position - lower
    return float(ordered[lower] * (1.0 - weight) + ordered[upper] * weight)


def robust_sequence_metrics(values: list[float]) -> dict[str, float]:
    """Summarize a trace without letting one startup/noise bin define range."""
    q01 = quantile(values, 0.01)
    q05 = quantile(values, 0.05)
    q50 = quantile(values, 0.50)
    q95 = quantile(values, 0.95)
    q99 = quantile(values, 0.99)
    top = sorted((value for value in values if math.isfinite(value)), reverse=True)
    if len(top) < 5:
        raise ValueError("robust trace metrics require at least five finite points")
    return {
        "q01": q01,
        "q05": q05,
        "median": q50,
        "q95": q95,
        "q99": q99,
        "robust_range_q99_q01": q99 - q01,
        "top5_median": float(statistics.median(top[:5])),
    }


def moving_average(values: list[float], bins: int) -> list[float]:
    if bins < 1 or bins % 2 == 0:
        raise ValueError("moving-average width must be a positive odd integer")
    if not values or not all(math.isfinite(value) for value in values):
        raise ValueError("moving average requires a finite, non-empty sequence")
    radius = bins // 2
    return [
        statistics.fmean(values[max(0, index - radius):index + radius + 1])
        for index in range(len(values))
    ]


def compare_smoothed_aligned(
    reference: list[float], candidate: list[float],
    smoothing_bins: int = STRUCTURED_SMOOTHING_BINS,
    alignment_bins: int = STRUCTURED_ALIGNMENT_BINS,
) -> dict[str, Any]:
    """Compare physical envelopes after bounded bin and baseline alignment.

    Median offset is reported, not discarded: peak/floor gates still constrain
    absolute level.  Removing it only from the envelope residual prevents a
    harmless common calibration offset from masquerading as a shape change.
    """
    if len(reference) != len(candidate) or not reference:
        raise ValueError("aligned comparison requires equal non-empty sequences")
    filtered_reference = moving_average(reference, smoothing_bins)
    filtered_candidate = moving_average(candidate, smoothing_bins)
    candidates: list[dict[str, Any]] = []
    for shift in range(-alignment_bins, alignment_bins + 1):
        reference_start = max(0, -shift)
        candidate_start = max(0, shift)
        length = len(reference) - abs(shift)
        left = filtered_reference[reference_start:reference_start + length]
        right = filtered_candidate[candidate_start:candidate_start + length]
        deltas = [right_value - left_value
                  for left_value, right_value in zip(left, right)]
        median_offset = float(statistics.median(deltas))
        centered = [delta - median_offset for delta in deltas]
        correlation = pearson(left, right)
        candidates.append({
            "alignment_bins": shift,
            "points": length,
            "median_offset_db": median_offset,
            "aligned_rmse_db": math.sqrt(
                statistics.fmean(delta * delta for delta in centered)
            ),
            "pearson": correlation,
        })
    # RMSE is the primary alignment objective.  Correlation breaks a numerical
    # tie without ever allowing a large residual to win.
    return min(
        candidates,
        key=lambda item: (
            float(item["aligned_rmse_db"]),
            -float(item["pearson"]) if isinstance(item["pearson"], float) else math.inf,
            abs(int(item["alignment_bins"])),
        ),
    ) | {
        "smoothing_bins": smoothing_bins,
        "maximum_alignment_bins": alignment_bins,
    }


def pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or not left:
        return None
    left_mean = statistics.fmean(left)
    right_mean = statistics.fmean(right)
    left_delta = [value - left_mean for value in left]
    right_delta = [value - right_mean for value in right]
    denominator = math.sqrt(
        sum(value * value for value in left_delta)
        * sum(value * value for value in right_delta)
    )
    if denominator == 0:
        return 1.0 if left == right else None
    return sum(a * b for a, b in zip(left_delta, right_delta)) / denominator


def compare_sequences(reference: list[float], candidate: list[float]) -> dict[str, Any]:
    deltas = [candidate_value - reference_value
              for reference_value, candidate_value in zip(reference, candidate)]
    exact = sum(left == right for left, right in zip(reference, candidate))
    return {
        "exact_points": exact,
        "exact_point_ratio": exact / len(reference),
        "maximum_absolute_delta": max(abs(delta) for delta in deltas),
        "mean_delta": statistics.fmean(deltas),
        "rmse": math.sqrt(statistics.fmean(delta * delta for delta in deltas)),
        "pearson": pearson(reference, candidate),
    }


def secondary_response_metrics(values: list[float], frequencies: list[int],
                               guard_bins: int = SFDR_GUARD_BINS) -> dict[str, Any]:
    """Measure the strongest response outside a fixed main-carrier guard.

    The value is SFDR-like for the explicitly gated single-carrier cases.  It
    remains useful raw diagnostic data for every other case, but must not be
    interpreted as harmonic distortion or gated there.
    """
    if len(values) != len(frequencies) or not values:
        raise ValueError("trace values and frequencies must be non-empty and aligned")
    if guard_bins < 0 or len(values) <= 2 * guard_bins + 1:
        raise ValueError("secondary-response guard leaves no searchable trace")
    if not all(math.isfinite(value) for value in values):
        raise ValueError("secondary-response trace contains a non-finite value")

    primary_index = max(range(len(values)), key=values.__getitem__)
    guard_first = max(0, primary_index - guard_bins)
    guard_last = min(len(values) - 1, primary_index + guard_bins)
    searchable = [
        index for index in range(len(values))
        if index < guard_first or index > guard_last
    ]
    if not searchable:
        raise ValueError("secondary-response guard covers the complete trace")
    secondary_index = max(searchable, key=values.__getitem__)
    primary_level = float(values[primary_index])
    secondary_level = float(values[secondary_index])

    # Report whether the selected response is a strict local maximum (with
    # equal-valued plateaus treated as one peak) and its connected -3 dB width.
    plateau_first = secondary_index
    plateau_last = secondary_index
    while (plateau_first > 0
           and values[plateau_first - 1] == secondary_level):
        plateau_first -= 1
    while (plateau_last + 1 < len(values)
           and values[plateau_last + 1] == secondary_level):
        plateau_last += 1
    left_lower = (
        plateau_first > 0 and values[plateau_first - 1] < secondary_level
    )
    right_lower = (
        plateau_last < len(values) - 1
        and values[plateau_last + 1] < secondary_level
    )
    width_first = secondary_index
    width_last = secondary_index
    width_threshold = secondary_level - 3.0
    while width_first > 0 and values[width_first - 1] >= width_threshold:
        width_first -= 1
    while (width_last + 1 < len(values)
           and values[width_last + 1] >= width_threshold):
        width_last += 1

    positive_steps = [
        right - left for left, right in zip(frequencies, frequencies[1:])
        if right > left
    ]
    resolution_hz = statistics.median(positive_steps) if positive_steps else 0.0
    return {
        "guard_bins_each_side": guard_bins,
        "guard_first_index": guard_first,
        "guard_last_index": guard_last,
        "guard_start_hz": frequencies[guard_first],
        "guard_stop_hz": frequencies[guard_last],
        "frequency_resolution_hz": resolution_hz,
        "primary_index": primary_index,
        "primary_frequency_hz": frequencies[primary_index],
        "primary_level_dbm": primary_level,
        "secondary_index": secondary_index,
        "secondary_frequency_hz": frequencies[secondary_index],
        "secondary_offset_hz": (
            frequencies[secondary_index] - frequencies[primary_index]
        ),
        "secondary_level_dbm": secondary_level,
        "secondary_is_local_peak": left_lower and right_lower,
        "secondary_width_3db_bins": width_last - width_first + 1,
        "sfdr_db": primary_level - secondary_level,
    }


def compare_secondary_response(case: int, reference: dict[str, Any],
                               candidate: dict[str, Any]) -> dict[str, Any]:
    eligible = case in SFDR_ELIGIBLE_CASES
    # One physical sweep cannot distinguish a coherent spur from the moving
    # maximum of a noise floor.  Preserve the complete observation, but never
    # promote it to a release gate until at least three independent sweeps can
    # establish frequency persistence.
    return {
        "pass": True,
        "gated": False,
        "eligible_with_repeats": eligible,
        "status": "PENDING" if eligible else "DIAGNOSTIC_ONLY",
        "minimum_independent_sweeps": SFDR_MINIMUM_INDEPENDENT_SWEEPS,
        "observed_independent_sweeps": 1,
        "detail": (
            f"{'persistence pending' if eligible else 'diagnostic-only'} "
            f"kind={VISUAL.CASE_KIND[case]} guard=+/-{SFDR_GUARD_BINS}bins "
            f"sfdr={reference['sfdr_db']:.2f}/{candidate['sfdr_db']:.2f}dB "
            f"secondary={reference['secondary_level_dbm']:.2f}/"
            f"{candidate['secondary_level_dbm']:.2f}dBm; "
            f"requires>={SFDR_MINIMUM_INDEPENDENT_SWEEPS} independent sweeps"
        ),
    }


def validate_case_capture(root: Path, case: int,
                          record: dict[str, Any]) -> dict[str, Any]:
    display = record.get("display", {})
    attempt = display.get("settle_attempt")
    if type(attempt) is not int or attempt < 1:
        raise ValueError(f"case {case}: invalid settlement attempt")
    canonical_be = root / f"case-{case:02d}.rgb565be"
    canonical_le = root / f"case-{case:02d}.rgb565"
    png = root / f"case-{case:02d}.png"
    pair_a = root / f"case-{case:02d}-settle-{attempt:02d}-a.rgb565be"
    pair_b = root / f"case-{case:02d}-settle-{attempt:02d}-b.rgb565be"
    payload = canonical_be.read_bytes()
    pair_a_payload = pair_a.read_bytes()
    pair_b_payload = pair_b.read_bytes()
    little = canonical_le.read_bytes()
    png_payload = png.read_bytes()
    frame_hash = hashlib.sha256(payload).hexdigest()
    shell_evidence = validate_shell_evidence(root, case)
    trace_path = root / f"case-{case:02d}-measured.f32le"
    recorded_shell = record.get("shell_evidence", {})
    stable = (
        len(payload) == FRAME_BYTES
        and payload == pair_a_payload == pair_b_payload
        and little == CAPTURE.rgb565be_to_rgb565le(payload)
        and display.get("bytes") == FRAME_BYTES
        and display.get("sha256") == frame_hash
        and record.get("comparator_rgb565_sha256")
        == hashlib.sha256(little).hexdigest()
        and record.get("png_sha256") == hashlib.sha256(png_payload).hexdigest()
        and recorded_shell.get("trace_dump_bytes") == TRACE_BYTES
        and recorded_shell.get("trace_dump_sha256") == sha256_file(trace_path)
    )
    return {
        "stable_pair": stable,
        "shell_evidence": shell_evidence,
        "settle_attempt": attempt,
        "panel_sha256": frame_hash,
        "comparator_sha256": hashlib.sha256(little).hexdigest(),
        "png_sha256": hashlib.sha256(png_payload).hexdigest(),
        "png_signature_valid": png_payload.startswith(b"\x89PNG\r\n\x1a\n"),
    }


def compare_case(reference_root: Path, candidate_root: Path, case: int,
                 reference_record: dict[str, Any],
                 candidate_record: dict[str, Any], output: Path) -> dict[str, Any]:
    reference_capture = validate_case_capture(reference_root, case, reference_record)
    candidate_capture = validate_case_capture(candidate_root, case, candidate_record)
    reference_frame = VISUAL.load_frame(reference_root / f"case-{case:02d}.rgb565")
    candidate_frame = VISUAL.load_frame(candidate_root / f"case-{case:02d}.rgb565")
    reference_frame_metrics = VISUAL.frame_metrics(reference_frame)
    candidate_frame_metrics = VISUAL.frame_metrics(candidate_frame)
    frame_comparison = VISUAL.compare_frames(reference_frame, candidate_frame)
    frame_comparison.update(VISUAL.compare_profiles(
        reference_frame_metrics["trace_profile"],
        candidate_frame_metrics["trace_profile"],
    ))
    reference_pass_literal = inspect_pass_literal(reference_root, case)
    candidate_pass_literal = inspect_pass_literal(candidate_root, case)
    exact_frame = (
        reference_capture["comparator_sha256"]
        == candidate_capture["comparator_sha256"]
    )
    VISUAL.write_diff(
        output / f"case-{case:02d}-diff.png", reference_frame, candidate_frame
    )

    reference_frequencies = load_frequencies(reference_root, case)
    candidate_frequencies = load_frequencies(candidate_root, case)
    reference_planes = load_trace_planes(reference_root, case)
    candidate_planes = load_trace_planes(candidate_root, case)
    reference_trace_metrics = [sequence_metrics(values) for values in reference_planes]
    candidate_trace_metrics = [sequence_metrics(values) for values in candidate_planes]
    trace_comparison = [
        compare_sequences(reference, candidate)
        for reference, candidate in zip(reference_planes, candidate_planes)
    ]
    reference_actual = reference_trace_metrics[0]
    candidate_actual = candidate_trace_metrics[0]
    actual_comparison = trace_comparison[0]
    reference_robust = robust_sequence_metrics(reference_planes[0])
    candidate_robust = robust_sequence_metrics(candidate_planes[0])
    structured_comparison = compare_smoothed_aligned(
        reference_planes[0], candidate_planes[0]
    )
    reference_secondary = secondary_response_metrics(
        reference_planes[0], reference_frequencies
    )
    candidate_secondary = secondary_response_metrics(
        candidate_planes[0], candidate_frequencies
    )
    secondary_comparison = compare_secondary_response(
        case, reference_secondary, candidate_secondary
    )
    reference_sweeptime = load_sweeptime(reference_root, case)
    candidate_sweeptime = load_sweeptime(candidate_root, case)
    reference_zero_span = None
    candidate_zero_span = None
    if (
        case in VISUAL.TIME_GRID_CASES
        and reference_sweeptime is not None
        and candidate_sweeptime is not None
    ):
        reference_zero_span = zero_span_grid_metrics(
            reference_frame, reference_sweeptime
        )
        candidate_zero_span = zero_span_grid_metrics(
            candidate_frame, candidate_sweeptime
        )

    checks: list[dict[str, Any]] = []
    add_check(checks, "reference-paired-readback", reference_capture["stable_pair"],
              f"attempt={reference_capture['settle_attempt']} sha={reference_capture['panel_sha256']}")
    add_check(checks, "candidate-paired-readback", candidate_capture["stable_pair"],
              f"attempt={candidate_capture['settle_attempt']} sha={candidate_capture['panel_sha256']}")
    add_check(checks, "reference-shell-evidence", reference_capture["shell_evidence"]["pass"],
              json.dumps(reference_capture["shell_evidence"], sort_keys=True))
    add_check(checks, "candidate-shell-evidence", candidate_capture["shell_evidence"]["pass"],
              json.dumps(candidate_capture["shell_evidence"], sort_keys=True))
    add_check(
        checks, "reference-factory-pass-literal",
        bool(reference_pass_literal["pass"]),
        json.dumps(reference_pass_literal, sort_keys=True),
    )
    add_check(
        checks, "candidate-factory-pass-literal",
        bool(candidate_pass_literal["pass"]),
        json.dumps(candidate_pass_literal, sort_keys=True),
    )
    reference_populated = (
        int(reference_frame_metrics["nonblack_pixels"]) >= 1000
        and int(reference_frame_metrics["unique_colors"]) >= 4
    )
    candidate_populated = (
        int(candidate_frame_metrics["nonblack_pixels"]) >= 1000
        and int(candidate_frame_metrics["unique_colors"]) >= 4
    )
    add_check(checks, "reference-frame-populated", reference_populated,
              f"nonblack={reference_frame_metrics['nonblack_pixels']} colors={reference_frame_metrics['unique_colors']}")
    add_check(checks, "candidate-frame-populated", candidate_populated,
              f"nonblack={candidate_frame_metrics['nonblack_pixels']} colors={candidate_frame_metrics['unique_colors']}")

    reference_trace_complete = all(
        metrics["points"] == TRACE_POINTS and metrics["finite"] == TRACE_POINTS
        and metrics["populated"] == TRACE_POINTS
        for metrics in reference_trace_metrics
    )
    candidate_trace_complete = all(
        metrics["points"] == TRACE_POINTS and metrics["finite"] == TRACE_POINTS
        and metrics["populated"] == TRACE_POINTS
        for metrics in candidate_trace_metrics
    )
    add_check(checks, "reference-trace-matrix-populated", reference_trace_complete,
              ", ".join(f"{PLANES[i]}={m['finite']}/{m['populated']}" for i, m in enumerate(reference_trace_metrics)))
    add_check(checks, "candidate-trace-matrix-populated", candidate_trace_complete,
              ", ".join(f"{PLANES[i]}={m['finite']}/{m['populated']}" for i, m in enumerate(candidate_trace_metrics)))
    add_check(checks, "frequency-grid-parity",
              reference_frequencies == candidate_frequencies,
              f"reference={reference_frequencies[0]}..{reference_frequencies[-1]} candidate={candidate_frequencies[0]}..{candidate_frequencies[-1]}")

    reference_pixels = int(reference_frame_metrics["trace_pixels"])
    candidate_pixels = int(candidate_frame_metrics["trace_pixels"])
    reference_columns = int(reference_frame_metrics["trace_active_columns"])
    candidate_columns = int(candidate_frame_metrics["trace_active_columns"])
    reference_span = int(reference_frame_metrics["trace_vertical_span"])
    candidate_span = int(candidate_frame_metrics["trace_vertical_span"])
    coverage_ok = (
        reference_pixels >= MINIMUM_TRACE_PIXELS
        and candidate_pixels >= MINIMUM_TRACE_PIXELS
        and reference_columns >= MINIMUM_TRACE_COLUMNS
        and candidate_columns >= MINIMUM_TRACE_COLUMNS
        and candidate_pixels >= math.floor(reference_pixels * 0.85)
        and candidate_columns >= math.floor(reference_columns * 0.85)
    )
    reference_visible_trace = (
        reference_pixels >= MINIMUM_TRACE_PIXELS
        and reference_columns >= MINIMUM_TRACE_COLUMNS
    )
    candidate_visible_trace = (
        candidate_pixels >= MINIMUM_TRACE_PIXELS
        and candidate_columns >= MINIMUM_TRACE_COLUMNS
    )
    add_check(checks, "reference-visible-screen-trace", reference_visible_trace,
              f"yellow_plot_pixels={reference_pixels} active_columns={reference_columns}")
    add_check(checks, "candidate-visible-screen-trace", candidate_visible_trace,
              f"yellow_plot_pixels={candidate_pixels} active_columns={candidate_columns}")
    nonflat_ok = trace_nonflat_ok(case, reference_span, candidate_span)
    zero_span_ok = (
        case not in VISUAL.TIME_GRID_CASES
        or (
            candidate_zero_span is not None
            and (bool(candidate_zero_span["pass"]) or exact_frame)
        )
    )
    if case in VISUAL.TIME_GRID_CASES:
        add_check(
            checks, "zero-span-grid-semantics", zero_span_ok,
            json.dumps({
                "reference": reference_zero_span,
                "candidate": candidate_zero_span,
                "exact_framebuffer_legacy_self_check": exact_frame,
            }, sort_keys=True),
        )
    visual_ok = (
        bool(reference_pass_literal["pass"])
        and bool(candidate_pass_literal["pass"])
        and coverage_ok and nonflat_ok and zero_span_ok
    )
    add_check(checks, "trace-coverage", coverage_ok,
              f"pixels={reference_pixels}/{candidate_pixels} columns={reference_columns}/{candidate_columns}")
    add_check(checks, "trace-not-degraded-to-flat", nonflat_ok,
              f"span={reference_span}/{candidate_span}px")
    add_check(checks, "physical-visual-equivalence", visual_ok,
              "exact framebuffer" if exact_frame else
              "semantic pass/coverage/grid checks; raw diagnostic "
              f"content_similarity={frame_comparison['content_pixel_similarity']:.4f} "
              f"trace_iou={frame_comparison['trace_column_iou']:.4f} "
              f"shape_rmse={frame_comparison['trace_shape_rmse_px']}")
    add_check(
        checks, "raw-frame-similarity-diagnostic", True,
        f"not gated: exact_pixel_ratio={frame_comparison['exact_pixel_ratio']:.4f} "
        f"content_similarity={frame_comparison['content_pixel_similarity']:.4f}",
    )

    # A single startup/noise bin must not define the absolute-level gate.  The
    # median of the five highest bins remains sensitive to a real carrier while
    # matching the robust range treatment below.
    reference_peak = float(reference_robust["top5_median"])
    candidate_peak = float(candidate_robust["top5_median"])
    if case in SUPPRESSION_CASES:
        peak_ok = candidate_peak <= reference_peak + 2.0
        peak_rule = "lower is better; +2.0 dB tolerance"
    elif case in ABOVE_CASES:
        peak_ok = candidate_peak >= reference_peak - 2.0
        peak_rule = "higher is acceptable; -2.0 dB tolerance"
    else:
        peak_ok = abs(candidate_peak - reference_peak) <= 2.0
        peak_rule = "absolute tolerance 2.0 dB"
    add_check(checks, "measured-peak-level", peak_ok,
              f"top5_median reference={reference_peak:.2f} "
              f"candidate={candidate_peak:.2f}; {peak_rule}; raw_max="
              f"{reference_actual['maximum']:.2f}/{candidate_actual['maximum']:.2f}dBm")

    reference_range = float(reference_robust["robust_range_q99_q01"])
    candidate_range = float(candidate_robust["robust_range_q99_q01"])
    range_ok = trace_range_ok(case, reference_range, candidate_range)
    add_check(checks, "measured-trace-range", range_ok,
              f"q99-q01 reference={reference_range:.3f}dB "
              f"candidate={candidate_range:.3f}dB; raw min/max="
              f"{reference_actual['range']:.3f}/{candidate_actual['range']:.3f}dB")

    add_check(
        checks, "measured-secondary-response-diagnostic",
        bool(secondary_comparison["pass"]),
        str(secondary_comparison["detail"]),
    )

    if case in STRUCTURED_CASES:
        peak_position_ok = abs(
            int(candidate_actual["peak_index"]) - int(reference_actual["peak_index"])
        ) <= STRUCTURED_ALIGNMENT_BINS
        correlation = structured_comparison["pearson"]
        numeric_shape_ok = (
            isinstance(correlation, float)
            and correlation >= STRUCTURED_CORRELATION_MIN
            and float(structured_comparison["aligned_rmse_db"])
            <= STRUCTURED_ALIGNED_RMSE_MAX_DB
        )
        add_check(checks, "measured-peak-position", peak_position_ok,
                  f"reference={reference_actual['peak_index']} candidate={candidate_actual['peak_index']} "
                  f"tolerance={STRUCTURED_ALIGNMENT_BINS}")
        add_check(checks, "measured-trace-shape", numeric_shape_ok,
                  f"smoothed_pearson={correlation} "
                  f"aligned_rmse={structured_comparison['aligned_rmse_db']:.3f}dB "
                  f"median_offset={structured_comparison['median_offset_db']:.3f}dB "
                  f"alignment={structured_comparison['alignment_bins']}bins")
        add_check(
            checks, "raw-trace-shape-diagnostic", True,
            f"not gated: pearson={actual_comparison['pearson']} "
            f"rmse={actual_comparison['rmse']:.3f}dB",
        )
    else:
        add_check(checks, "measured-peak-position", True,
                  "not asserted for noise/suppression or intentionally horizontal response")
        add_check(checks, "measured-trace-shape", True,
                  f"summary comparison used; pearson={actual_comparison['pearson']} rmse={actual_comparison['rmse']:.3f}dB")

    if reference_sweeptime is not None and candidate_sweeptime is not None:
        timing_ok = candidate_sweeptime <= reference_sweeptime * 1.10 + 0.010
        timing_detail = (
            f"reference={reference_sweeptime:.3f}s candidate={candidate_sweeptime:.3f}s "
            "limit=reference*1.10+0.010s"
        )
    else:
        timing_ok = False
        timing_detail = f"unparsed reference={reference_sweeptime} candidate={candidate_sweeptime}"
    add_check(checks, "sweep-time-not-materially-slower", timing_ok, timing_detail)

    reference_frame_metrics.pop("trace_profile")
    candidate_frame_metrics.pop("trace_profile")
    return {
        "case": case,
        "kind": VISUAL.CASE_KIND[case],
        "pass": all(check["pass"] for check in checks),
        "exact_framebuffer": exact_frame,
        "checks": checks,
        "reference": {
            "capture": reference_capture,
            "frame": reference_frame_metrics,
            "factory_pass_literal": reference_pass_literal,
            "trace_planes": dict(zip(PLANES, reference_trace_metrics)),
            "actual_trace_robust": reference_robust,
            "secondary_response": reference_secondary,
            "sweeptime_seconds": reference_sweeptime,
            "zero_span_grid": reference_zero_span,
        },
        "candidate": {
            "capture": candidate_capture,
            "frame": candidate_frame_metrics,
            "factory_pass_literal": candidate_pass_literal,
            "trace_planes": dict(zip(PLANES, candidate_trace_metrics)),
            "actual_trace_robust": candidate_robust,
            "secondary_response": candidate_secondary,
            "sweeptime_seconds": candidate_sweeptime,
            "zero_span_grid": candidate_zero_span,
        },
        "comparison": {
            "frame": frame_comparison,
            "trace_planes": dict(zip(PLANES, trace_comparison)),
            "structured_trace": structured_comparison,
            "frequency_grid_exact": reference_frequencies == candidate_frequencies,
            "secondary_response": secondary_comparison,
        },
        "_frames": (reference_frame, candidate_frame),
    }


def write_markdown(output: Path, report: dict[str, Any]) -> None:
    if report["qualification_pass"]:
        overall = "PASS — QUALIFYING OFFICIAL/RC5 A/B"
    elif report["pass"]:
        overall = "PASS — NON-QUALIFYING DIAGNOSTIC"
    else:
        overall = "FAIL"
    lines = [
        "# tinySA4 physical self-test A/B comparison",
        "",
        f"Overall: **{overall}**",
        "",
        f"Qualification eligible: **{'yes' if report['qualification_eligible'] else 'no'}**.",
        "This report does not substitute simulation evidence or require "
        "framebuffer/trace byte identity unless identity was actually observed.",
        "",
        "## Inventory",
        "",
        f"- Reference: `{report['reference']['variant']}` / `{report['reference']['expected_version']}`; "
        f"checksums **{'PASS' if report['reference']['checksums']['pass'] else 'FAIL'}** "
        f"({report['reference']['checksums']['entries']} entries)",
        f"- Candidate: `{report['candidate']['variant']}` / `{report['candidate']['expected_version']}`; "
        f"checksums **{'PASS' if report['candidate']['checksums']['pass'] else 'FAIL'}** "
        f"({report['candidate']['checksums']['entries']} entries)",
        "- Comparator, capture support, visual support, and firmware font source "
        "are snapshotted under `implementation/` and hash-bound by this report.",
        (
            "- Cold boot: operator-attested evidence is copied under "
            "`operator-attestation/`; serial capture cannot independently sense "
            "power removal."
            if report["cold_boot_attestation"] is not None
            else "- Cold boot: no valid operator attestation supplied."
        ),
        "",
        "## Cases",
        "",
        "Raw content similarity and raw pointwise RMSE are diagnostic only. "
        "Factory verdicts, trace coverage, robust RF features, and semantic "
        "zero-span geometry are the release checks.",
        "",
        "| Case | Kind | Result | Exact frame | Changed px | Content similarity (diag) | Trace span R/C | Peak dBm R/C | Q99-Q01 dB R/C | Envelope corr/RMSE dB | Sweep s R/C |",
        "|---:|:---|:---:|:---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for case in report["cases"]:
        reference_actual = case["reference"]["trace_planes"]["actual"]
        candidate_actual = case["candidate"]["trace_planes"]["actual"]
        reference_robust = case["reference"]["actual_trace_robust"]
        candidate_robust = case["candidate"]["actual_trace_robust"]
        envelope = case["comparison"]["structured_trace"]
        lines.append(
            f"| {case['case']} | {case['kind']} | {'PASS' if case['pass'] else 'FAIL'} | "
            f"{'yes' if case['exact_framebuffer'] else 'no'} | "
            f"{case['comparison']['frame']['changed_pixels']} | "
            f"{case['comparison']['frame']['content_pixel_similarity']:.4f} | "
            f"{case['reference']['frame']['trace_vertical_span']}/{case['candidate']['frame']['trace_vertical_span']} | "
            f"{reference_actual['maximum']:.2f}/{candidate_actual['maximum']:.2f} | "
            f"{reference_robust['robust_range_q99_q01']:.2f}/{candidate_robust['robust_range_q99_q01']:.2f} | "
            f"{envelope['pearson']}/{envelope['aligned_rmse_db']:.3f} | "
            f"{case['reference']['sweeptime_seconds']}/{case['candidate']['sweeptime_seconds']} |"
        )
    failures = [
        f"- Case {case['case']} `{check['name']}`: {check['detail']}"
        for case in report["cases"] for check in case["checks"] if not check["pass"]
    ]
    lines.extend((
        "", "## Secondary-response diagnostics", "",
        "Single-sweep SFDR is never a release gate. The five unambiguous "
        "single-carrier cases become eligible only after at least three "
        "independent sweeps establish frequency persistence. All current rows "
        "are diagnostic; case 6 deliberately exercises a harmonic path.", "",
        "| Case | Kind | Status | Primary MHz R/C | Secondary MHz R/C | "
        "Secondary dBm R/C | SFDR dB R/C |",
        "|---:|:---|:---:|---:|---:|---:|---:|",
    ))
    for case in report["cases"]:
        reference = case["reference"]["secondary_response"]
        candidate = case["candidate"]["secondary_response"]
        lines.append(
            f"| {case['case']} | {case['kind']} | "
            f"{case['comparison']['secondary_response']['status']} | "
            f"{reference['primary_frequency_hz'] / 1e6:.6f}/"
            f"{candidate['primary_frequency_hz'] / 1e6:.6f} | "
            f"{reference['secondary_frequency_hz'] / 1e6:.6f}/"
            f"{candidate['secondary_frequency_hz'] / 1e6:.6f} | "
            f"{reference['secondary_level_dbm']:.2f}/"
            f"{candidate['secondary_level_dbm']:.2f} | "
            f"{reference['sfdr_db']:.2f}/{candidate['sfdr_db']:.2f} |"
        )
    lines.extend(("", "## Failed checks", ""))
    lines.extend(failures or ["None."])
    lines.extend((
        "", "## Review artifacts", "",
        "Each `case-XX-diff.png` renders reference-only pixels red, candidate-only "
        "pixels cyan, and identical pixels dim gray. The two contact sheets place "
        "official, RC5, and diff frames side by side.", "",
    ))
    (output / "report.md").write_text("\n".join(lines), encoding="utf-8")


def qualification_diagnostic_reasons(
    reference_root: Path,
    candidate_root: Path,
    reference_checksums: dict[str, Any],
    candidate_checksums: dict[str, Any],
    reference_metadata: dict[str, Any],
    candidate_metadata: dict[str, Any],
) -> list[str]:
    reasons: list[str] = []
    if reference_root.resolve() == candidate_root.resolve():
        reasons.append("reference and candidate resolve to the same capture root")
    if reference_checksums["sha256"] == candidate_checksums["sha256"]:
        reasons.append("reference and candidate checksum inventories are identical")
    if reference_metadata["expected_version"] == candidate_metadata["expected_version"]:
        reasons.append("reference and candidate firmware versions are identical")
    exact_role_pair = (
        reference_metadata["variant"] == "official-c979"
        and (
            candidate_metadata["variant"] == "rc5"
            or candidate_metadata["variant"].startswith("rc5-")
        )
        and reference_metadata["expected_version"]
        == CAPTURE.KNOWN_VARIANT_VERSIONS["official-c979"]
        and candidate_metadata["expected_version"]
        == CAPTURE.KNOWN_VARIANT_VERSIONS["rc5"]
    )
    if not exact_role_pair:
        reasons.append("pair is not exact official-c979 versus RC5 provenance")
    reference_usb = reference_metadata.get("usb_identity")
    candidate_usb = candidate_metadata.get("usb_identity")
    if not isinstance(reference_usb, dict) or not isinstance(candidate_usb, dict):
        reasons.append("one or both captures lack USB identity provenance")
    else:
        reference_location = reference_usb.get("location")
        candidate_location = candidate_usb.get("location")
        if not reference_location or reference_location != candidate_location:
            reasons.append("USB location does not bind both captures to the same test path")
        for field, expected in (("vid", 0x0483), ("pid", 0x5740)):
            if (reference_usb.get(field), candidate_usb.get(field)) != (expected, expected):
                reasons.append(f"USB {field} is not the expected tinySA CDC identity")
    return reasons


def validate_cold_boot_attestation(
    path: Path,
    reference_metadata: dict[str, Any],
    candidate_metadata: dict[str, Any],
    reference_checksums: dict[str, Any],
    candidate_checksums: dict[str, Any],
) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"cold-boot attestation is not a regular file: {path}")
    payload = path.read_bytes()
    document = json.loads(payload.decode("utf-8"))
    if document.get("schema") != "tinysa-physical-cold-boot-attestation-v1":
        raise ValueError("cold-boot attestation has an unsupported schema")
    if document.get("evidence_type") != "operator-attested":
        raise ValueError("cold-boot evidence must be explicitly operator-attested")
    if document.get("cal_rf_fixture") != "CAL-RF-LOOPBACK-CONNECTED":
        raise ValueError("cold-boot attestation does not bind the CAL-to-RF fixture")
    events = document.get("events")
    if not isinstance(events, list) or len(events) != 2:
        raise ValueError("cold-boot attestation must contain exactly two events")
    by_role = {
        event.get("role"): event for event in events if isinstance(event, dict)
    }
    if set(by_role) != {"reference", "candidate"}:
        raise ValueError("cold-boot attestation roles are incomplete or duplicated")
    expected = {
        "reference": (reference_metadata, reference_checksums),
        "candidate": (candidate_metadata, candidate_checksums),
    }
    for role, (metadata, checksums) in expected.items():
        event = by_role[role]
        required = {
            "variant": metadata["variant"],
            "expected_version": metadata["expected_version"],
            "capture_inventory_sha256": checksums["sha256"],
            "capture_started_utc": metadata["started_utc"],
            "usb_location": metadata["usb_identity"]["location"],
            "boot_mode": "normal",
            "operator_confirmed": True,
        }
        mismatches = {
            field: {"expected": value, "observed": event.get(field)}
            for field, value in required.items() if event.get(field) != value
        }
        seconds = event.get("minimum_power_off_seconds")
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 5:
            mismatches["minimum_power_off_seconds"] = {
                "expected": ">=5", "observed": seconds,
            }
        if mismatches:
            raise ValueError(f"cold-boot attestation {role} mismatch: {mismatches}")
    return {
        "schema": document["schema"],
        "evidence_type": document["evidence_type"],
        "sha256": hashlib.sha256(payload).hexdigest(),
        "source_path": str(path.resolve()),
        "limitation": (
            "Power removal is operator-attested; the serial capture cannot "
            "independently sense supply voltage."
        ),
        "document": document,
    }


def is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def compare(reference_root: Path, candidate_root: Path, output: Path,
            reference_variant: str | None,
            candidate_variant: str | None,
            allow_diagnostic: bool = False,
            cold_boot_attestation: Path | None = None) -> dict[str, Any]:
    output_resolved = output.resolve()
    capture_roots = (reference_root.resolve(), candidate_root.resolve())
    if any(
        is_within(output_resolved, root) or is_within(root, output_resolved)
        for root in capture_roots
    ):
        raise ValueError(
            "comparison output must not overlap either capture inventory"
        )
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("comparison output must be a new or empty directory")
    reference_checksums = validate_checksums(reference_root)
    candidate_checksums = validate_checksums(candidate_root)
    reference_metadata = load_metadata(reference_root, reference_variant)
    candidate_metadata = load_metadata(candidate_root, candidate_variant)
    diagnostic_reasons = qualification_diagnostic_reasons(
        reference_root,
        candidate_root,
        reference_checksums,
        candidate_checksums,
        reference_metadata,
        candidate_metadata,
    )
    attestation: dict[str, Any] | None = None
    if cold_boot_attestation is None:
        diagnostic_reasons.append("no operator-attested cold-boot provenance was supplied")
    else:
        try:
            attestation = validate_cold_boot_attestation(
                cold_boot_attestation,
                reference_metadata,
                candidate_metadata,
                reference_checksums,
                candidate_checksums,
            )
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
            diagnostic_reasons.append(f"cold-boot attestation is invalid: {error}")
    if diagnostic_reasons and not allow_diagnostic:
        raise ValueError(
            "non-qualifying comparison rejected: " + "; ".join(diagnostic_reasons)
            + "; pass --allow-diagnostic only for an explicitly non-qualifying self-check"
        )
    qualification_eligible = not diagnostic_reasons
    output.mkdir(parents=True, exist_ok=True)
    implementation_dir = output / "implementation"
    implementation_dir.mkdir()
    implementation_sources = {
        "compare-physical-selftest-captures.py": TOOL_PATH,
        "capture-physical-selftests.py": CAPTURE_PATH,
        "compare-selftest-visuals.py": VISUAL_PATH,
        "Font5x7.c": FONT_PATH,
    }
    implementation: dict[str, dict[str, str]] = {}
    for name, source in implementation_sources.items():
        payload = source.read_bytes()
        relative = Path("implementation") / name
        (output / relative).write_bytes(payload)
        implementation[name] = {
            "path": relative.as_posix(),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    attestation_summary: dict[str, Any] | None = None
    if attestation is not None:
        attestation_dir = output / "operator-attestation"
        attestation_dir.mkdir()
        attestation_relative = Path("operator-attestation/cold-boot.json")
        attestation_payload = cold_boot_attestation.read_bytes()
        (output / attestation_relative).write_bytes(attestation_payload)
        attestation_summary = {
            key: value for key, value in attestation.items() if key != "document"
        }
        attestation_summary["path"] = attestation_relative.as_posix()
    case_results = [
        compare_case(
            reference_root, candidate_root, case,
            reference_metadata["case_records"][case],
            candidate_metadata["case_records"][case], output,
        )
        for case in CASES
    ]
    frames = [result.pop("_frames") for result in case_results]
    VISUAL.write_contact_sheet(output / "contact-cases-01-07.png", frames[:7])
    VISUAL.write_contact_sheet(output / "contact-cases-08-14.png", frames[7:])
    report: dict[str, Any] = {
        "schema": AB_REPORT_SCHEMA,
        "pass": (
            reference_checksums["pass"] and candidate_checksums["pass"]
            and all(result["pass"] for result in case_results)
        ),
        "qualification_eligible": qualification_eligible,
        "qualification_pass": False,
        "diagnostic_reasons": diagnostic_reasons,
        "evidence_scope": "physical hardware; separate from Renode qualification",
        "implementation": implementation,
        "cold_boot_attestation": attestation_summary,
        "reference": {
            "path": str(reference_root.resolve()),
            "variant": reference_metadata["variant"],
            "expected_version": reference_metadata["expected_version"],
            "checksums": reference_checksums,
            "persisted_config_integrity": reference_metadata["persisted_config_integrity"],
        },
        "candidate": {
            "path": str(candidate_root.resolve()),
            "variant": candidate_metadata["variant"],
            "expected_version": candidate_metadata["expected_version"],
            "checksums": candidate_checksums,
            "persisted_config_integrity": candidate_metadata["persisted_config_integrity"],
        },
        "thresholds": {
            "factory_pass_literal": "exact firmware-font mask in observed bright-green palette color",
            "raw_content_pixel_similarity": "diagnostic only",
            "raw_pointwise_trace_rmse": "diagnostic only",
            "minimum_visible_trace_pixels": MINIMUM_TRACE_PIXELS,
            "minimum_visible_trace_columns": MINIMUM_TRACE_COLUMNS,
            "trace_coverage_ratio": 0.85,
            "structured_trace_smoothing_bins": STRUCTURED_SMOOTHING_BINS,
            "structured_trace_alignment_bins": STRUCTURED_ALIGNMENT_BINS,
            "structured_trace_pearson": STRUCTURED_CORRELATION_MIN,
            "structured_trace_aligned_rmse_db": STRUCTURED_ALIGNED_RMSE_MAX_DB,
            "structured_trace_offset": "median removed for shape only; absolute peak remains gated",
            "trace_range": "q99-q01; raw min/max retained diagnostically",
            "structured_threshold_calibration": (
                "same-RC5 case-3 repeat diagnostic: raw RMSE 2.605 dB; "
                "9-bin aligned RMSE 1.034 dB; correlation 0.9949"
            ),
            "peak_level_tolerance_db": 2.0,
            "sfdr_eligible_cases": sorted(SFDR_ELIGIBLE_CASES),
            "sfdr_status": "pending frequency persistence; one sweep is diagnostic only",
            "sfdr_minimum_independent_sweeps": SFDR_MINIMUM_INDEPENDENT_SWEEPS,
            "sfdr_guard_bins_each_side": SFDR_GUARD_BINS,
            "zero_span_grid": "candidate columns must match its measured sweep-time formula; exact-frame legacy self-check allowed",
            "timing_limit": "candidate <= reference*1.10 + 0.010 seconds",
        },
        "cases": case_results,
    }
    report["qualification_pass"] = bool(
        report["pass"] and report["qualification_eligible"]
    )
    (output / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    write_markdown(output, report)
    paths = sorted(path for path in output.rglob("*")
                   if path.is_file() and path.name != "SHA256SUMS")
    (output / "SHA256SUMS").write_text(
        "".join(
            f"{sha256_file(path)}  {path.relative_to(output)}\n"
            for path in paths
        ),
        encoding="utf-8",
    )
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="compare complete physical official/candidate self-test evidence"
    )
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--reference-variant", default="official-c979")
    parser.add_argument("--candidate-variant", default="rc5")
    parser.add_argument(
        "--allow-diagnostic",
        action="store_true",
        help="allow an explicitly non-qualifying same-image or non-official/RC5 self-check",
    )
    parser.add_argument(
        "--cold-boot-attestation",
        type=Path,
        help="operator-attested cold power-cycle evidence bound to both capture inventories",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = compare(
            args.reference, args.candidate, args.output,
            args.reference_variant, args.candidate_variant,
            args.allow_diagnostic,
            args.cold_boot_attestation,
        )
        if report["qualification_pass"]:
            status = "qualified"
        elif report["pass"]:
            status = "diagnostic-only"
        else:
            status = "failed"
        print(f"physical_selftest_ab={status}")
        print(f"report={args.output / 'report.md'}")
        return 0 if report["pass"] else 1
    except (OSError, RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
