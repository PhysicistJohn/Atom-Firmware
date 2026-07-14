#!/usr/bin/env python3
"""Compare complete physical official/candidate self-test capture inventories."""

from __future__ import annotations

import argparse
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
SFDR_GATED_CASES = frozenset((3, 4, 10, 11, 14))
# 23 bins on either side is just over five percent of a 450-point sweep.  It
# clears the widest official -30 dB carrier lobe (19 bins in case 11) while
# retaining more than 89 percent of every sweep for secondary-response search.
SFDR_GUARD_BINS = 23
SFDR_REGRESSION_TOLERANCE_DB = 3.0


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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def add_check(checks: list[dict[str, Any]], name: str, passed: bool,
              detail: str) -> None:
    checks.append({"name": name, "pass": bool(passed), "detail": detail})


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
    if not isinstance(config_commands, list) or not config_commands:
        raise ValueError(f"{path} has no persisted-config observations")
    for phase in ("before", "after"):
        hashes = config_integrity.get(f"{phase}_sha256")
        if not isinstance(hashes, dict):
            raise ValueError(f"{path} has malformed {phase} config hashes")
        for command in config_commands:
            config_path = root / "persisted-config" / (
                f"{phase}-{CAPTURE.command_slug(command)}.txt"
            )
            if not config_path.is_file() or hashes.get(command) != sha256_file(config_path):
                raise ValueError(
                    f"{path} persisted-config evidence does not match: {phase} {command}"
                )
    if expected_variant is not None and metadata.get("variant") != expected_variant:
        raise ValueError(
            f"{path} variant is {metadata.get('variant')!r}, expected {expected_variant!r}"
        )
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
    gated = case in SFDR_GATED_CASES
    if not gated:
        return {
            "pass": True,
            "gated": False,
            "detail": (
                f"diagnostic-only kind={VISUAL.CASE_KIND[case]}; "
                f"reference_sfdr={reference['sfdr_db']:.2f}dB "
                f"candidate_sfdr={candidate['sfdr_db']:.2f}dB"
            ),
        }
    sfdr_floor = float(reference["sfdr_db"]) - SFDR_REGRESSION_TOLERANCE_DB
    secondary_ceiling = (
        float(reference["secondary_level_dbm"])
        + SFDR_REGRESSION_TOLERANCE_DB
    )
    passed = (
        float(candidate["sfdr_db"]) >= sfdr_floor
        and float(candidate["secondary_level_dbm"]) <= secondary_ceiling
    )
    return {
        "pass": passed,
        "gated": True,
        "detail": (
            f"guard=+/-{SFDR_GUARD_BINS}bins "
            f"sfdr={reference['sfdr_db']:.2f}/{candidate['sfdr_db']:.2f}dB "
            f"minimum={sfdr_floor:.2f}dB; secondary="
            f"{reference['secondary_level_dbm']:.2f}/"
            f"{candidate['secondary_level_dbm']:.2f}dBm "
            f"ceiling={secondary_ceiling:.2f}dBm"
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

    checks: list[dict[str, Any]] = []
    add_check(checks, "reference-paired-readback", reference_capture["stable_pair"],
              f"attempt={reference_capture['settle_attempt']} sha={reference_capture['panel_sha256']}")
    add_check(checks, "candidate-paired-readback", candidate_capture["stable_pair"],
              f"attempt={candidate_capture['settle_attempt']} sha={candidate_capture['panel_sha256']}")
    add_check(checks, "reference-shell-evidence", reference_capture["shell_evidence"]["pass"],
              json.dumps(reference_capture["shell_evidence"], sort_keys=True))
    add_check(checks, "candidate-shell-evidence", candidate_capture["shell_evidence"]["pass"],
              json.dumps(candidate_capture["shell_evidence"], sort_keys=True))
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

    exact_frame = reference_capture["comparator_sha256"] == candidate_capture["comparator_sha256"]
    reference_pixels = int(reference_frame_metrics["trace_pixels"])
    candidate_pixels = int(candidate_frame_metrics["trace_pixels"])
    reference_columns = int(reference_frame_metrics["trace_active_columns"])
    candidate_columns = int(candidate_frame_metrics["trace_active_columns"])
    reference_span = int(reference_frame_metrics["trace_vertical_span"])
    candidate_span = int(candidate_frame_metrics["trace_vertical_span"])
    coverage_ok = (
        candidate_pixels >= math.floor(reference_pixels * 0.85)
        and candidate_columns >= math.floor(reference_columns * 0.85)
    )
    reference_visible_trace = reference_pixels >= 50 and reference_columns >= 50
    candidate_visible_trace = candidate_pixels >= 50 and candidate_columns >= 50
    add_check(checks, "reference-visible-screen-trace", reference_visible_trace,
              f"yellow_plot_pixels={reference_pixels} active_columns={reference_columns}")
    add_check(checks, "candidate-visible-screen-trace", candidate_visible_trace,
              f"yellow_plot_pixels={candidate_pixels} active_columns={candidate_columns}")
    nonflat_ok = reference_span < 5 or candidate_span >= max(3, math.floor(reference_span * 0.80))
    visual_ok = exact_frame or (
        float(frame_comparison["content_pixel_similarity"]) >= 0.95
        and coverage_ok and nonflat_ok
    )
    add_check(checks, "trace-coverage", coverage_ok,
              f"pixels={reference_pixels}/{candidate_pixels} columns={reference_columns}/{candidate_columns}")
    add_check(checks, "trace-not-degraded-to-flat", nonflat_ok,
              f"span={reference_span}/{candidate_span}px")
    add_check(checks, "physical-visual-equivalence", visual_ok,
              "exact framebuffer" if exact_frame else
              f"content_similarity={frame_comparison['content_pixel_similarity']:.4f} trace_iou={frame_comparison['trace_column_iou']:.4f} shape_rmse={frame_comparison['trace_shape_rmse_px']}")

    reference_peak = float(reference_actual["maximum"])
    candidate_peak = float(candidate_actual["maximum"])
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
              f"reference={reference_peak:.2f} candidate={candidate_peak:.2f}; {peak_rule}")

    reference_range = float(reference_actual["range"])
    candidate_range = float(candidate_actual["range"])
    if reference_range < 2.0:
        range_ok = abs(candidate_range - reference_range) <= 1.0
    else:
        range_ok = (
            candidate_range >= reference_range * 0.85
            and candidate_range <= reference_range * 1.15 + 1.0
        )
    add_check(checks, "measured-trace-range", range_ok,
              f"reference={reference_range:.3f}dB candidate={candidate_range:.3f}dB")

    add_check(
        checks, "measured-secondary-response-sfdr",
        bool(secondary_comparison["pass"]),
        str(secondary_comparison["detail"]),
    )

    if case in STRUCTURED_CASES:
        peak_position_ok = abs(
            int(candidate_actual["peak_index"]) - int(reference_actual["peak_index"])
        ) <= 3
        correlation = actual_comparison["pearson"]
        numeric_shape_ok = (
            isinstance(correlation, float) and correlation >= 0.95
            and float(actual_comparison["rmse"]) <= 2.0
        )
        add_check(checks, "measured-peak-position", peak_position_ok,
                  f"reference={reference_actual['peak_index']} candidate={candidate_actual['peak_index']} tolerance=3")
        add_check(checks, "measured-trace-shape", numeric_shape_ok,
                  f"pearson={correlation} rmse={actual_comparison['rmse']:.3f}dB")
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
            "trace_planes": dict(zip(PLANES, reference_trace_metrics)),
            "secondary_response": reference_secondary,
            "sweeptime_seconds": reference_sweeptime,
        },
        "candidate": {
            "capture": candidate_capture,
            "frame": candidate_frame_metrics,
            "trace_planes": dict(zip(PLANES, candidate_trace_metrics)),
            "secondary_response": candidate_secondary,
            "sweeptime_seconds": candidate_sweeptime,
        },
        "comparison": {
            "frame": frame_comparison,
            "trace_planes": dict(zip(PLANES, trace_comparison)),
            "frequency_grid_exact": reference_frequencies == candidate_frequencies,
            "secondary_response": secondary_comparison,
        },
        "_frames": (reference_frame, candidate_frame),
    }


def write_markdown(output: Path, report: dict[str, Any]) -> None:
    lines = [
        "# tinySA4 physical self-test A/B comparison",
        "",
        f"Overall: **{'PASS' if report['pass'] else 'FAIL'}**",
        "",
        "This report compares physical official-c979 and RC5 observations. "
        "It does not substitute simulation evidence or require framebuffer/trace "
        "byte identity unless identity was actually observed.",
        "",
        "## Inventory",
        "",
        f"- Reference: `{report['reference']['variant']}` / `{report['reference']['expected_version']}`; "
        f"checksums **{'PASS' if report['reference']['checksums']['pass'] else 'FAIL'}** "
        f"({report['reference']['checksums']['entries']} entries)",
        f"- Candidate: `{report['candidate']['variant']}` / `{report['candidate']['expected_version']}`; "
        f"checksums **{'PASS' if report['candidate']['checksums']['pass'] else 'FAIL'}** "
        f"({report['candidate']['checksums']['entries']} entries)",
        "",
        "## Cases",
        "",
        "| Case | Kind | Result | Exact frame | Changed px | Content similarity | Trace span R/C | Peak dBm R/C | Range dB R/C | Sweep s R/C |",
        "|---:|:---|:---:|:---:|---:|---:|---:|---:|---:|---:|",
    ]
    for case in report["cases"]:
        reference_actual = case["reference"]["trace_planes"]["actual"]
        candidate_actual = case["candidate"]["trace_planes"]["actual"]
        lines.append(
            f"| {case['case']} | {case['kind']} | {'PASS' if case['pass'] else 'FAIL'} | "
            f"{'yes' if case['exact_framebuffer'] else 'no'} | "
            f"{case['comparison']['frame']['changed_pixels']} | "
            f"{case['comparison']['frame']['content_pixel_similarity']:.4f} | "
            f"{case['reference']['frame']['trace_vertical_span']}/{case['candidate']['frame']['trace_vertical_span']} | "
            f"{reference_actual['maximum']:.2f}/{candidate_actual['maximum']:.2f} | "
            f"{reference_actual['range']:.2f}/{candidate_actual['range']:.2f} | "
            f"{case['reference']['sweeptime_seconds']}/{case['candidate']['sweeptime_seconds']} |"
        )
    failures = [
        f"- Case {case['case']} `{check['name']}`: {check['detail']}"
        for case in report["cases"] for check in case["checks"] if not check["pass"]
    ]
    lines.extend((
        "", "## Secondary-response diagnostics", "",
        "SFDR is a release gate only for the five unambiguous single-carrier "
        "cases. All other rows are recorded for diagnosis only; in particular, "
        "case 6 deliberately exercises a harmonic path.", "",
        "| Case | Kind | Gate | Primary MHz R/C | Secondary MHz R/C | "
        "Secondary dBm R/C | SFDR dB R/C |",
        "|---:|:---|:---:|---:|---:|---:|---:|",
    ))
    for case in report["cases"]:
        reference = case["reference"]["secondary_response"]
        candidate = case["candidate"]["secondary_response"]
        lines.append(
            f"| {case['case']} | {case['kind']} | "
            f"{'yes' if case['comparison']['secondary_response']['gated'] else 'no'} | "
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


def compare(reference_root: Path, candidate_root: Path, output: Path,
            reference_variant: str | None,
            candidate_variant: str | None) -> dict[str, Any]:
    if output.resolve() in (reference_root.resolve(), candidate_root.resolve()):
        raise ValueError("comparison output must be separate from both capture inventories")
    output.mkdir(parents=True, exist_ok=True)
    reference_checksums = validate_checksums(reference_root)
    candidate_checksums = validate_checksums(candidate_root)
    reference_metadata = load_metadata(reference_root, reference_variant)
    candidate_metadata = load_metadata(candidate_root, candidate_variant)
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
        "schema": "tinysa-physical-selftest-ab-v1",
        "pass": (
            reference_checksums["pass"] and candidate_checksums["pass"]
            and all(result["pass"] for result in case_results)
        ),
        "evidence_scope": "physical hardware; separate from Renode qualification",
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
            "content_pixel_similarity": 0.95,
            "minimum_visible_trace_pixels_and_columns": 50,
            "trace_coverage_ratio": 0.85,
            "structured_trace_pearson": 0.95,
            "structured_trace_rmse_db": 2.0,
            "peak_level_tolerance_db": 2.0,
            "sfdr_gated_cases": sorted(SFDR_GATED_CASES),
            "sfdr_guard_bins_each_side": SFDR_GUARD_BINS,
            "sfdr_regression_tolerance_db": SFDR_REGRESSION_TOLERANCE_DB,
            "secondary_level_regression_tolerance_db": (
                SFDR_REGRESSION_TOLERANCE_DB
            ),
            "timing_limit": "candidate <= reference*1.10 + 0.010 seconds",
        },
        "cases": case_results,
    }
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
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = compare(
            args.reference, args.candidate, args.output,
            args.reference_variant, args.candidate_variant,
        )
        print(f"physical_selftest_ab={'passed' if report['pass'] else 'failed'}")
        print(f"report={args.output / 'report.md'}")
        return 0 if report["pass"] else 1
    except (OSError, RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
