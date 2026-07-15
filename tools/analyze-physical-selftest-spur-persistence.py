#!/usr/bin/env python3
"""Diagnose repeat-to-repeat persistence of physical self-test spurs.

This tool consumes exactly three independently captured physical self-test
inventories for each firmware.  It is intentionally diagnostic: frequency
coherence is evidence that a secondary response is repeatable, but this report
does not create a release pass/fail gate and does not infer that a response is
a harmonic of any particular source.

The main-carrier exclusion and frequency-alignment bounds are imported from
``compare-physical-selftest-captures.py`` so the repeat analysis uses the same
semantics as the single-sweep A/B report.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import statistics
import struct
import sys
from typing import Any, Iterable, Sequence

TOOL_PATH = Path(__file__).resolve()


def load_comparator() -> Any:
    path = TOOL_PATH.with_name("compare-physical-selftest-captures.py")
    spec = importlib.util.spec_from_file_location(
        "physical_selftest_spur_comparator_support", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load comparator support from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


COMPARATOR = load_comparator()

ELIGIBLE_CASES = tuple(sorted(COMPARATOR.SFDR_ELIGIBLE_CASES))
INDEPENDENT_SWEEPS = COMPARATOR.SFDR_MINIMUM_INDEPENDENT_SWEEPS
TRACE_POINTS = COMPARATOR.TRACE_POINTS
TRACE_PLANES = len(COMPARATOR.PLANES)
TRACE_BYTES = TRACE_PLANES * TRACE_POINTS * 4
MAIN_GUARD_BINS = COMPARATOR.SFDR_GUARD_BINS
COHERENCE_TOLERANCE_BINS = COMPARATOR.STRUCTURED_ALIGNMENT_BINS

# A local peak must clear both this absolute floor and a robust, sweep-local
# noise threshold (median prominence + six MAD) before it participates in
# persistence clustering.  Six MAD is about four standard deviations for
# Gaussian data, while the median/MAD remain stable when a minority of bins are
# real comb responses.  These are diagnostic detection bounds, not firmware
# acceptance thresholds.
MINIMUM_LOCAL_PROMINENCE_DB = 6.0
PROMINENCE_MAD_MULTIPLIER = 6.0
MINIMUM_LOCAL_PEAKS_FOR_MAD = 20
LOCAL_BACKGROUND_RADIUS_BINS = 12
LOCAL_PEAK_EXCLUSION_BINS = 2
MINIMUM_BACKGROUND_SAMPLES = 6

CAPTURE_SCHEMA = "tinysa-physical-selftest-capture-v1"
REPORT_SCHEMA = "tinysa-physical-selftest-spur-persistence-v1"
REQUIRED_RUN_FILES = (
    "run.log",
    "run-transcript.md",
    "device-version-before.txt",
    "device-version-after.txt",
    "device-info-before.txt",
    "device-info-after.txt",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_utc(value: Any, field: str, path: Path) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{path} has no string {field}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{path} has invalid {field}: {value!r}") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{path} {field} is not timezone-aware")
    return parsed


def validate_checksum_inventory(root: Path) -> dict[str, Any]:
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
        candidate = Path(relative)
        if candidate.is_absolute() or ".." in candidate.parts or relative in declared:
            malformed.append(line)
            continue
        declared[relative] = match.group(1)
    actual = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS"
    )
    missing = sorted(set(actual) - set(declared))
    extra = sorted(set(declared) - set(actual))
    mismatched = sorted(
        relative for relative in set(actual) & set(declared)
        if sha256_file(root / relative) != declared[relative]
    )
    if malformed or missing or extra or mismatched:
        raise ValueError(
            f"{root} checksum inventory is invalid: malformed={malformed} "
            f"missing={missing} extra={extra} mismatched={mismatched}"
        )
    return {
        "sha256": sha256_file(inventory),
        "entries": len(declared),
    }


def parse_frequencies(path: Path) -> list[int]:
    values = [
        int(line) for line in path.read_bytes().replace(b"\r", b"").split(b"\n")
        if re.fullmatch(rb"[0-9]+", line)
    ]
    if len(values) != TRACE_POINTS:
        raise ValueError(f"{path} has {len(values)} frequencies; expected {TRACE_POINTS}")
    if any(right <= left for left, right in zip(values, values[1:])):
        raise ValueError(f"{path} frequency grid is not strictly increasing")
    return values


def parse_trace_one(path: Path) -> list[float]:
    pattern = re.compile(
        rb"trace 1 value ([0-9]+) ([-+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][-+]?[0-9]+)?)"
    )
    indexed: dict[int, float] = {}
    for line in path.read_bytes().replace(b"\r", b"").split(b"\n"):
        match = pattern.fullmatch(line)
        if match:
            indexed[int(match.group(1))] = float(match.group(2))
    if sorted(indexed) != list(range(TRACE_POINTS)):
        raise ValueError(f"{path} does not contain {TRACE_POINTS} contiguous trace points")
    return [indexed[index] for index in range(TRACE_POINTS)]


def load_actual_trace(root: Path, case: int, record: dict[str, Any]) -> list[float]:
    path = root / f"case-{case:02d}-measured.f32le"
    payload = path.read_bytes()
    if len(payload) != TRACE_BYTES:
        raise ValueError(f"{path} has {len(payload)} bytes; expected {TRACE_BYTES}")
    shell_evidence = record.get("shell_evidence")
    if not isinstance(shell_evidence, dict):
        raise ValueError(f"{root} case {case} has no shell-evidence record")
    if (
        shell_evidence.get("trace_dump_bytes") != TRACE_BYTES
        or shell_evidence.get("trace_dump_sha256") != hashlib.sha256(payload).hexdigest()
    ):
        raise ValueError(f"{root} case {case} trace dump does not match run.json")
    values = list(struct.unpack(f"<{TRACE_PLANES * TRACE_POINTS}f", payload))
    actual = values[:TRACE_POINTS]
    if not all(math.isfinite(value) for value in actual):
        raise ValueError(f"{path} actual plane contains a non-finite value")
    shell = parse_trace_one(root / f"case-{case:02d}-shell/trace-1-value.txt")
    if struct.pack(f"<{TRACE_POINTS}f", *shell) != payload[:TRACE_POINTS * 4]:
        raise ValueError(f"{path} actual plane does not match retained trace-1 output")
    return actual


def validate_persisted_config(root: Path, metadata: dict[str, Any]) -> None:
    integrity = metadata.get("persisted_config_integrity")
    if not isinstance(integrity, dict) or integrity.get("pass") is not True:
        raise ValueError(f"{root / 'run.json'} lacks passing config-integrity evidence")
    commands = integrity.get("commands")
    before = integrity.get("before_sha256")
    after = integrity.get("after_sha256")
    expected_commands = [
        "color",
        *(f"correction {table}" for table in COMPARATOR.CAPTURE.CORRECTION_TABLES),
    ]
    if commands != expected_commands:
        raise ValueError(
            f"{root / 'run.json'} does not contain the exact 13-command config inventory"
        )
    if integrity.get("mismatches") != []:
        raise ValueError(f"{root / 'run.json'} declares config mismatches")
    if not isinstance(before, dict) or not isinstance(after, dict):
        raise ValueError(f"{root / 'run.json'} has malformed config hashes")
    if set(before) != set(commands) or set(after) != set(commands):
        raise ValueError(f"{root / 'run.json'} has incomplete config hash sets")
    phase_payloads: dict[str, dict[str, bytes]] = {"before": {}, "after": {}}
    for phase, hashes in (("before", before), ("after", after)):
        for command in commands:
            if not isinstance(command, str):
                raise ValueError(f"{root / 'run.json'} has a non-string config command")
            path = root / "persisted-config" / (
                f"{phase}-{COMPARATOR.CAPTURE.command_slug(command)}.txt"
            )
            if not path.is_file():
                raise ValueError(f"{root} config evidence is missing: {phase} {command}")
            payload = path.read_bytes()
            phase_payloads[phase][command] = payload
            if hashes.get(command) != hashlib.sha256(payload).hexdigest():
                raise ValueError(f"{root} config evidence does not match: {phase} {command}")
    changed = [
        command for command in commands
        if phase_payloads["before"][command] != phase_payloads["after"][command]
    ]
    if changed:
        raise ValueError(
            f"{root} config changed despite PASS metadata: {changed}"
        )


def load_capture(root: Path) -> dict[str, Any]:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"capture root is not a directory: {root}")
    checksum = validate_checksum_inventory(root)
    for name in REQUIRED_RUN_FILES:
        if not (root / name).is_file():
            raise ValueError(f"{root} is missing run evidence: {name}")
    run_path = root / "run.json"
    metadata = json.loads(run_path.read_text(encoding="utf-8"))
    if metadata.get("schema") != CAPTURE_SCHEMA or metadata.get("result") != "PASS":
        raise ValueError(f"{run_path} is not a completed physical self-test capture")
    started = parse_utc(metadata.get("started_utc"), "started_utc", run_path)
    finished = parse_utc(metadata.get("finished_utc"), "finished_utc", run_path)
    if finished <= started:
        raise ValueError(f"{run_path} finished_utc does not follow started_utc")
    variant = metadata.get("variant")
    version = metadata.get("expected_version")
    identity = metadata.get("usb_identity")
    if not isinstance(variant, str) or not variant:
        raise ValueError(f"{run_path} has no variant")
    if not isinstance(version, str) or not version:
        raise ValueError(f"{run_path} has no expected_version")
    COMPARATOR.CAPTURE.require_variant_version(variant, version)
    if (
        not isinstance(identity, dict)
        or type(identity.get("vid")) is not int
        or type(identity.get("pid")) is not int
        or not isinstance(identity.get("serial_number"), str)
        or not identity["serial_number"]
        or not isinstance(identity.get("location"), str)
        or not identity["location"]
    ):
        raise ValueError(f"{run_path} has no stable USB identity")
    for name in ("device-version-before.txt", "device-version-after.txt"):
        try:
            COMPARATOR.CAPTURE.require_version((root / name).read_bytes(), version)
        except AssertionError as error:
            raise ValueError(f"{root / name} does not authenticate the capture: {error}") from error
    validate_persisted_config(root, metadata)

    records = metadata.get("cases")
    if not isinstance(records, list):
        raise ValueError(f"{run_path} has no case records")
    by_case: dict[int, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            raise ValueError(f"{run_path} contains a malformed case record")
        case = record.get("selftest_argument")
        if type(case) is not int or record.get("zero_based_case") != case - 1:
            raise ValueError(f"{run_path} contains an invalid case record: {record!r}")
        if record.get("result") != "PASS" or case in by_case:
            raise ValueError(f"{run_path} case {case} is incomplete or duplicated")
        by_case[case] = record
    missing_cases = sorted(set(ELIGIBLE_CASES) - set(by_case))
    if missing_cases:
        raise ValueError(f"{run_path} lacks eligible cases: {missing_cases}")

    observations: dict[int, dict[str, Any]] = {}
    for case in ELIGIBLE_CASES:
        record = by_case[case]
        case_started = parse_utc(
            record.get("started_utc"), f"case {case} started_utc", run_path
        )
        case_finished = parse_utc(
            record.get("finished_utc"), f"case {case} finished_utc", run_path
        )
        if case_finished <= case_started:
            raise ValueError(f"{run_path} case {case} has invalid timestamps")
        if case_started < started or case_finished > finished:
            raise ValueError(
                f"{run_path} case {case} timestamps fall outside the capture interval"
            )
        display = record.get("display")
        if not isinstance(display, dict):
            raise ValueError(f"{run_path} case {case} lacks stable-display evidence")
        settle_attempt = display.get("settle_attempt")
        if type(settle_attempt) is not int or settle_attempt < 1:
            raise ValueError(f"{run_path} case {case} has invalid settle-attempt evidence")
        final_frame_path = root / f"case-{case:02d}.rgb565be"
        pair_a_path = root / f"case-{case:02d}-settle-{settle_attempt:02d}-a.rgb565be"
        pair_b_path = root / f"case-{case:02d}-settle-{settle_attempt:02d}-b.rgb565be"
        if not all(path.is_file() for path in (final_frame_path, pair_a_path, pair_b_path)):
            raise ValueError(f"{run_path} case {case} lacks its retained stable frame pair")
        final_frame = final_frame_path.read_bytes()
        if (
            len(final_frame) != COMPARATOR.FRAME_BYTES
            or display.get("bytes") != COMPARATOR.FRAME_BYTES
            or display.get("sha256") != hashlib.sha256(final_frame).hexdigest()
            or pair_a_path.read_bytes() != final_frame
            or pair_b_path.read_bytes() != final_frame
        ):
            raise ValueError(f"{run_path} case {case} stable frame pair does not match")
        comparator_frame_path = root / f"case-{case:02d}.rgb565"
        if (
            not comparator_frame_path.is_file()
            or record.get("comparator_rgb565_sha256")
            != sha256_file(comparator_frame_path)
        ):
            raise ValueError(f"{run_path} case {case} comparator frame does not match")
        pass_literal = COMPARATOR.inspect_pass_literal(root, case)
        if not pass_literal["pass"]:
            raise ValueError(
                f"{run_path} case {case} does not contain the exact green factory PASS literal"
            )
        observations[case] = {
            "frequencies": parse_frequencies(
                root / f"case-{case:02d}-shell/frequencies.txt"
            ),
            "actual": load_actual_trace(root, case, record),
            "started_utc": case_started.astimezone(timezone.utc).isoformat(),
            "_started_dt": case_started,
            "_finished_dt": case_finished,
            "trace_sha256": record["shell_evidence"]["trace_dump_sha256"],
            "factory_pass_literal": pass_literal,
        }
    return {
        "path": str(root),
        "variant": variant,
        "expected_version": version,
        "started_utc": started.astimezone(timezone.utc).isoformat(),
        "finished_utc": finished.astimezone(timezone.utc).isoformat(),
        "_started_dt": started,
        "_finished_dt": finished,
        "usb_identity": identity,
        "checksums": checksum,
        "observations": observations,
    }


def stable_usb_key(capture: dict[str, Any]) -> tuple[Any, Any, Any, Any]:
    identity = capture["usb_identity"]
    return (
        identity["vid"], identity["pid"],
        identity["serial_number"], identity["location"],
    )


def validate_group(captures: Sequence[dict[str, Any]], label: str) -> None:
    if len(captures) != INDEPENDENT_SWEEPS:
        raise ValueError(
            f"{label} requires exactly {INDEPENDENT_SWEEPS} captures; got {len(captures)}"
        )
    roots = [capture["path"] for capture in captures]
    starts = [capture["_started_dt"] for capture in captures]
    if len(set(roots)) != INDEPENDENT_SWEEPS:
        raise ValueError(f"{label} capture roots are not distinct")
    if len(set(starts)) != INDEPENDENT_SWEEPS:
        raise ValueError(f"{label} captures do not have distinct acquisition starts")
    intervals = sorted(
        (capture["_started_dt"], capture["_finished_dt"]) for capture in captures
    )
    for previous, current in zip(intervals, intervals[1:]):
        if current[0] < previous[1]:
            raise ValueError(f"{label} capture intervals overlap")
    versions = {capture["expected_version"] for capture in captures}
    identities = {stable_usb_key(capture) for capture in captures}
    if len(versions) != 1:
        raise ValueError(f"{label} captures contain different firmware versions: {versions}")
    if len(identities) != 1:
        raise ValueError(f"{label} captures contain different USB identities: {identities}")
    for case in ELIGIBLE_CASES:
        case_starts = [capture["observations"][case]["_started_dt"] for capture in captures]
        if len(set(case_starts)) != INDEPENDENT_SWEEPS:
            raise ValueError(f"{label} case {case} observations are not independently timestamped")


def local_peak_metrics(
    values: Sequence[float], frequencies: Sequence[int], index: int,
    guard_first: int, guard_last: int,
) -> dict[str, Any]:
    """Measure one plateau-aware peak against the median of nearby flanks."""
    if index < 0 or index >= len(values):
        raise ValueError(f"peak index is outside trace: {index}")
    level = float(values[index])
    first = index
    last = index
    while first > 0 and values[first - 1] == level:
        first -= 1
    while last + 1 < len(values) and values[last + 1] == level:
        last += 1
    local_maximum = (
        first > 0 and last + 1 < len(values)
        and values[first - 1] < level and values[last + 1] < level
    )
    center = (first + last) // 2
    background = [
        float(values[neighbor])
        for neighbor in range(
            max(0, center - LOCAL_BACKGROUND_RADIUS_BINS),
            min(len(values), center + LOCAL_BACKGROUND_RADIUS_BINS + 1),
        )
        if (
            neighbor < first - LOCAL_PEAK_EXCLUSION_BINS
            or neighbor > last + LOCAL_PEAK_EXCLUSION_BINS
        )
        and not guard_first <= neighbor <= guard_last
    ]
    baseline = float(statistics.median(background)) if background else None
    prominence = level - baseline if baseline is not None else None
    width_first = center
    width_last = center
    threshold = level - 3.0
    while width_first > 0 and values[width_first - 1] >= threshold:
        width_first -= 1
    while width_last + 1 < len(values) and values[width_last + 1] >= threshold:
        width_last += 1
    return {
        "index": center,
        "frequency_hz": int(frequencies[center]),
        "level_dbm": level,
        "local_peak": local_maximum,
        "plateau_first_index": first,
        "plateau_last_index": last,
        "width_3db_bins": width_last - width_first + 1,
        "background_samples": len(background),
        "local_background_dbm": baseline,
        "local_prominence_db": prominence,
    }


def detect_significant_peaks(
    values: Sequence[float], frequencies: Sequence[int],
    secondary: dict[str, Any],
) -> dict[str, Any]:
    guard_first = int(secondary["guard_first_index"])
    guard_last = int(secondary["guard_last_index"])
    primary_level = float(secondary["primary_level_dbm"])
    primary_frequency = int(secondary["primary_frequency_hz"])
    local_peaks: list[dict[str, Any]] = []
    index = 1
    while index < len(values) - 1:
        level = values[index]
        plateau_last = index
        while plateau_last + 1 < len(values) and values[plateau_last + 1] == level:
            plateau_last += 1
        center = (index + plateau_last) // 2
        outside_guard = plateau_last < guard_first or index > guard_last
        if outside_guard:
            metrics = local_peak_metrics(
                values, frequencies, center, guard_first, guard_last
            )
            prominence = metrics["local_prominence_db"]
            if (
                metrics["local_peak"]
                and metrics["background_samples"] >= MINIMUM_BACKGROUND_SAMPLES
                and isinstance(prominence, float)
            ):
                metrics.update({
                    "primary_offset_hz": metrics["frequency_hz"] - primary_frequency,
                    "sfdr_db": primary_level - metrics["level_dbm"],
                })
                local_peaks.append(metrics)
        index = plateau_last + 1
    prominences = [float(peak["local_prominence_db"]) for peak in local_peaks]
    if len(prominences) >= MINIMUM_LOCAL_PEAKS_FOR_MAD:
        median_prominence = float(statistics.median(prominences))
        prominence_mad = float(statistics.median(
            abs(value - median_prominence) for value in prominences
        ))
        adaptive_threshold = (
            median_prominence + PROMINENCE_MAD_MULTIPLIER * prominence_mad
        )
        adaptive_estimator_used = True
    else:
        median_prominence = (
            float(statistics.median(prominences)) if prominences else None
        )
        prominence_mad = None
        adaptive_threshold = MINIMUM_LOCAL_PROMINENCE_DB
        adaptive_estimator_used = False
    threshold = max(MINIMUM_LOCAL_PROMINENCE_DB, adaptive_threshold)
    significant = sorted(
        (
            peak for peak in local_peaks
            if float(peak["local_prominence_db"]) >= threshold
        ),
        key=lambda peak: (-peak["level_dbm"], peak["index"]),
    )
    return {
        "absolute_floor_db": MINIMUM_LOCAL_PROMINENCE_DB,
        "mad_multiplier": PROMINENCE_MAD_MULTIPLIER,
        "minimum_local_peaks_for_mad": MINIMUM_LOCAL_PEAKS_FOR_MAD,
        "adaptive_estimator_used": adaptive_estimator_used,
        "local_peak_count": len(local_peaks),
        "local_prominence_median_db": median_prominence,
        "local_prominence_mad_db": prominence_mad,
        "effective_threshold_db": threshold,
        "significant_peaks": significant,
    }


def coherent_indices(indices: Sequence[int]) -> tuple[bool, int, int]:
    center = int(statistics.median(indices))
    maximum_deviation = max(abs(index - center) for index in indices)
    return maximum_deviation <= COHERENCE_TOLERANCE_BINS, center, maximum_deviation


def cluster_persistent_peaks(
    sweeps: Sequence[dict[str, Any]], frequencies: Sequence[int]
) -> list[dict[str, Any]]:
    anchors = sorted({
        int(peak["index"])
        for sweep in sweeps for peak in sweep["significant_peaks"]
    })
    candidates: dict[tuple[int, ...], dict[str, Any]] = {}
    for anchor in anchors:
        members: list[dict[str, Any]] = []
        for sweep_index, sweep in enumerate(sweeps):
            nearby = [
                peak for peak in sweep["significant_peaks"]
                if abs(int(peak["index"]) - anchor) <= COHERENCE_TOLERANCE_BINS
            ]
            if not nearby:
                break
            peak = min(
                nearby,
                key=lambda item: (
                    abs(int(item["index"]) - anchor),
                    -float(item["local_prominence_db"]),
                    -float(item["level_dbm"]),
                ),
            )
            members.append({"sweep": sweep_index + 1, **peak})
        if len(members) != INDEPENDENT_SWEEPS:
            continue
        indices = [int(member["index"]) for member in members]
        coherent, center, deviation = coherent_indices(indices)
        if not coherent:
            continue
        signature = tuple(indices)
        levels = [float(member["level_dbm"]) for member in members]
        prominences = [float(member["local_prominence_db"]) for member in members]
        sfdr_values = [float(member["sfdr_db"]) for member in members]
        candidates[signature] = {
            "center_index": center,
            "center_frequency_hz": int(frequencies[center]),
            "maximum_deviation_bins": deviation,
            "frequency_span_bins": max(indices) - min(indices),
            "frequency_span_hz": max(
                int(member["frequency_hz"]) for member in members
            ) - min(int(member["frequency_hz"]) for member in members),
            "median_level_dbm": float(statistics.median(levels)),
            "level_span_db": max(levels) - min(levels),
            "median_local_prominence_db": float(statistics.median(prominences)),
            "minimum_local_prominence_db": min(prominences),
            "median_sfdr_db": float(statistics.median(sfdr_values)),
            "members": members,
        }

    # Nearby candidate anchors can describe the same peak.  Resolve them
    # deterministically while allowing two distinct nearby peaks when each has
    # its own member in all three sweeps.
    ordered = sorted(
        candidates.values(),
        key=lambda cluster: (
            -cluster["median_local_prominence_db"],
            -cluster["median_level_dbm"],
            cluster["center_index"],
        ),
    )
    retained: list[dict[str, Any]] = []
    used: set[tuple[int, int]] = set()
    for cluster in ordered:
        keys = {
            (int(member["sweep"]), int(member["index"]))
            for member in cluster["members"]
        }
        if keys & used:
            continue
        retained.append(cluster)
        used.update(keys)
    return sorted(retained, key=lambda cluster: cluster["center_index"])


def analyze_group_case(
    captures: Sequence[dict[str, Any]], case: int
) -> dict[str, Any]:
    frequencies = captures[0]["observations"][case]["frequencies"]
    sweeps: list[dict[str, Any]] = []
    for ordinal, capture in enumerate(captures, 1):
        observation = capture["observations"][case]
        if observation["frequencies"] != frequencies:
            raise ValueError(f"case {case} has different frequency grids within a group")
        values = observation["actual"]
        secondary = COMPARATOR.secondary_response_metrics(
            values, frequencies, guard_bins=MAIN_GUARD_BINS
        )
        detection = detect_significant_peaks(values, frequencies, secondary)
        peaks = detection["significant_peaks"]
        strongest_local = local_peak_metrics(
            values,
            frequencies,
            int(secondary["secondary_index"]),
            int(secondary["guard_first_index"]),
            int(secondary["guard_last_index"]),
        )
        sweeps.append({
            "sweep": ordinal,
            "capture_path": capture["path"],
            "variant": capture["variant"],
            "started_utc": observation["started_utc"],
            "trace_sha256": observation["trace_sha256"],
            "primary": {
                key: secondary[key] for key in (
                    "primary_index", "primary_frequency_hz", "primary_level_dbm"
                )
            },
            "strongest_secondary": {
                key: secondary[key] for key in (
                    "secondary_index", "secondary_frequency_hz",
                    "secondary_offset_hz", "secondary_level_dbm",
                    "secondary_is_local_peak", "secondary_width_3db_bins", "sfdr_db",
                )
            } | {
                "local_background_dbm": strongest_local["local_background_dbm"],
                "local_prominence_db": strongest_local["local_prominence_db"],
            },
            "peak_detection": {
                key: detection[key] for key in (
                    "absolute_floor_db", "mad_multiplier", "local_peak_count",
                    "minimum_local_peaks_for_mad", "adaptive_estimator_used",
                    "local_prominence_median_db", "local_prominence_mad_db",
                    "effective_threshold_db",
                )
            },
            "significant_peaks": peaks,
        })

    primary_indices = [int(sweep["primary"]["primary_index"]) for sweep in sweeps]
    primary_coherent, primary_center, primary_deviation = coherent_indices(primary_indices)
    secondary_indices = [
        int(sweep["strongest_secondary"]["secondary_index"]) for sweep in sweeps
    ]
    secondary_coherent, secondary_center, secondary_deviation = coherent_indices(
        secondary_indices
    )
    secondary_prominent = all(
        sweep["strongest_secondary"]["secondary_is_local_peak"]
        and isinstance(sweep["strongest_secondary"]["local_prominence_db"], float)
        and sweep["strongest_secondary"]["local_prominence_db"]
        >= sweep["peak_detection"]["effective_threshold_db"]
        for sweep in sweeps
    )
    if secondary_coherent and secondary_prominent:
        strongest_classification = "PERSISTENT_FREQUENCY_COHERENT"
    elif secondary_coherent:
        strongest_classification = "FREQUENCY_COHERENT_LOW_PROMINENCE"
    else:
        strongest_classification = "STOCHASTIC_OR_NONPERSISTENT"

    clusters = cluster_persistent_peaks(sweeps, frequencies)
    if not primary_coherent:
        classification = "PRIMARY_UNSTABLE_ANALYSIS_LIMITED"
    elif clusters:
        classification = "PERSISTENT_FREQUENCY_COHERENT"
    elif any(sweep["significant_peaks"] for sweep in sweeps):
        classification = "STOCHASTIC_OR_NONPERSISTENT"
    else:
        classification = "NO_SIGNIFICANT_SECONDARY_PEAK"
    return {
        "classification": classification,
        "release_gate": False,
        "frequency_grid": {
            "points": len(frequencies),
            "start_hz": frequencies[0],
            "stop_hz": frequencies[-1],
            "median_step_hz": float(statistics.median(
                right - left for left, right in zip(frequencies, frequencies[1:])
            )),
        },
        "primary_coherence": {
            "coherent": primary_coherent,
            "indices": primary_indices,
            "center_index": primary_center,
            "maximum_deviation_bins": primary_deviation,
        },
        "strongest_secondary_coherence": {
            "classification": strongest_classification,
            "indices": secondary_indices,
            "center_index": secondary_center,
            "maximum_deviation_bins": secondary_deviation,
            "all_locally_prominent": secondary_prominent,
        },
        "significant_peak_counts": [len(sweep["significant_peaks"]) for sweep in sweeps],
        "persistent_clusters": clusters,
        "persistent_cluster_count": len(clusters),
        "unclustered_significant_peak_count": (
            sum(len(sweep["significant_peaks"]) for sweep in sweeps)
            - len(clusters) * INDEPENDENT_SWEEPS
        ),
        "sweeps": sweeps,
    }


def compare_persistent_clusters(
    reference: dict[str, Any], candidate: dict[str, Any]
) -> dict[str, Any]:
    reference_clusters = reference["persistent_clusters"]
    candidate_clusters = candidate["persistent_clusters"]
    possible = sorted(
        (
            abs(int(left["center_index"]) - int(right["center_index"])),
            left_index,
            right_index,
        )
        for left_index, left in enumerate(reference_clusters)
        for right_index, right in enumerate(candidate_clusters)
        if abs(int(left["center_index"]) - int(right["center_index"]))
        <= COHERENCE_TOLERANCE_BINS
    )
    used_reference: set[int] = set()
    used_candidate: set[int] = set()
    shared: list[dict[str, Any]] = []
    for distance, left_index, right_index in possible:
        if left_index in used_reference or right_index in used_candidate:
            continue
        left = reference_clusters[left_index]
        right = candidate_clusters[right_index]
        used_reference.add(left_index)
        used_candidate.add(right_index)
        shared.append({
            "reference_center_index": left["center_index"],
            "candidate_center_index": right["center_index"],
            "center_distance_bins": distance,
            "reference_center_frequency_hz": left["center_frequency_hz"],
            "candidate_center_frequency_hz": right["center_frequency_hz"],
            "candidate_minus_reference_median_level_db": (
                right["median_level_dbm"] - left["median_level_dbm"]
            ),
            "candidate_minus_reference_median_sfdr_db": (
                right["median_sfdr_db"] - left["median_sfdr_db"]
            ),
        })
    return {
        "release_gate": False,
        "shared_persistent_clusters": shared,
        "reference_only_persistent_clusters": [
            cluster for index, cluster in enumerate(reference_clusters)
            if index not in used_reference
        ],
        "candidate_only_persistent_clusters": [
            cluster for index, cluster in enumerate(candidate_clusters)
            if index not in used_candidate
        ],
        "interpretation": (
            "Cluster matching is diagnostic. Candidate-only or level-delta "
            "observations are not automatic regressions."
        ),
    }


def capture_summary(capture: dict[str, Any]) -> dict[str, Any]:
    return {
        key: capture[key] for key in (
            "path", "variant", "expected_version", "started_utc",
            "finished_utc", "usb_identity", "checksums",
        )
    }


def write_markdown(output: Path, report: dict[str, Any]) -> None:
    lines = [
        "# tinySA4 physical self-test spur persistence",
        "",
        "Overall: **DIAGNOSTIC COMPLETE (NON-GATING)**",
        "",
        "Three independent physical sweeps per firmware were analyzed. A "
        "secondary response is called frequency-coherent only when a locally "
        "prominent peak clears a robust sweep-local threshold and recurs in "
        f"all three sweeps within +/-"
        f"{COHERENCE_TOLERANCE_BINS} frequency bins. This report does not "
        "change firmware release status.",
        "",
        "## Captures",
        "",
        "| Group | Sweep | Variant | Version | Started UTC | Inventory SHA-256 |",
        "|:---|---:|:---|:---|:---|:---|",
    ]
    for group_name in ("reference", "candidate"):
        group = report[group_name]
        for ordinal, capture in enumerate(group["captures"], 1):
            lines.append(
                f"| {group['label']} | {ordinal} | `{capture['variant']}` | "
                f"`{capture['expected_version']}` | `{capture['started_utc']}` | "
                f"`{capture['checksums']['sha256']}` |"
            )
    lines.extend((
        "",
        "## Case summary",
        "",
        "| Case | Reference classification | Ref clusters | Candidate classification | Cand clusters | Shared | Ref-only | Cand-only |",
        "|---:|:---|---:|:---|---:|---:|---:|---:|",
    ))
    for case in report["cases"]:
        comparison = case["comparison"]
        lines.append(
            f"| {case['case']} | {case['reference']['classification']} | "
            f"{case['reference']['persistent_cluster_count']} | "
            f"{case['candidate']['classification']} | "
            f"{case['candidate']['persistent_cluster_count']} | "
            f"{len(comparison['shared_persistent_clusters'])} | "
            f"{len(comparison['reference_only_persistent_clusters'])} | "
            f"{len(comparison['candidate_only_persistent_clusters'])} |"
        )
    lines.extend((
        "",
        "## Persistent observations",
        "",
        "| Case | Group | Center MHz | Span bins | Median level dBm | Median prominence dB | Median SFDR dB |",
        "|---:|:---|---:|---:|---:|---:|---:|",
    ))
    cluster_rows = 0
    for case in report["cases"]:
        for group_name in ("reference", "candidate"):
            for cluster in case[group_name]["persistent_clusters"]:
                cluster_rows += 1
                lines.append(
                    f"| {case['case']} | {report[group_name]['label']} | "
                    f"{cluster['center_frequency_hz'] / 1e6:.6f} | "
                    f"{cluster['frequency_span_bins']} | "
                    f"{cluster['median_level_dbm']:.2f} | "
                    f"{cluster['median_local_prominence_db']:.2f} | "
                    f"{cluster['median_sfdr_db']:.2f} |"
                )
    if not cluster_rows:
        lines.append("| - | - | - | - | - | - | - |")
    lines.extend((
        "",
        "## Interpretation limits",
        "",
        "- `PERSISTENT_FREQUENCY_COHERENT` means a local peak cleared both the "
        f"{MINIMUM_LOCAL_PROMINENCE_DB:g} dB floor and median+"
        f"{PROMINENCE_MAD_MULTIPLIER:g}-MAD sweep threshold (when at least "
        f"{MINIMUM_LOCAL_PEAKS_FOR_MAD} local peaks were available), then remained "
        "frequency-coherent across all three captures; it is not a release failure.",
        "- `STOCHASTIC_OR_NONPERSISTENT` means significant local maxima moved "
        "outside the bounded frequency window or did not occur in every sweep.",
        "- A coherent response is called a spur observation only. Harmonic "
        "attribution requires stimulus/clock mapping and is not attempted here.",
        "- Three sweeps establish short-run recurrence, not long-term rate, "
        "temperature, cable-position, or population statistics.",
        "- This diagnostic does not convert the A/B report's pending "
        "single-sweep SFDR field into a release gate or pass result.",
        "",
    ))
    (output / "report.md").write_text("\n".join(lines), encoding="utf-8")


def is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def analyze(
    reference_roots: Sequence[Path], candidate_roots: Sequence[Path],
    output: Path, reference_label: str, candidate_label: str,
) -> dict[str, Any]:
    all_roots = [root.resolve() for root in (*reference_roots, *candidate_roots)]
    output_resolved = output.resolve()
    if any(
        is_within(output_resolved, root) or is_within(root, output_resolved)
        for root in all_roots
    ):
        raise ValueError("analysis output must not overlap any capture inventory")
    if output.exists():
        if not output.is_dir():
            raise ValueError(f"analysis output is not a directory: {output}")
        if any(output.iterdir()):
            raise ValueError(f"analysis output directory is not empty: {output}")
    if len(set(all_roots)) != 2 * INDEPENDENT_SWEEPS:
        raise ValueError("all six capture roots must be distinct")

    reference_captures = [load_capture(root) for root in reference_roots]
    candidate_captures = [load_capture(root) for root in candidate_roots]
    validate_group(reference_captures, reference_label)
    validate_group(candidate_captures, candidate_label)
    reference_locations = {
        capture["usb_identity"]["location"] for capture in reference_captures
    }
    candidate_locations = {
        capture["usb_identity"]["location"] for capture in candidate_captures
    }
    if reference_locations != candidate_locations:
        raise ValueError(
            "reference/candidate USB location differs; captures are not bound "
            "to the same physical test path"
        )
    for field, expected in (("vid", 0x0483), ("pid", 0x5740)):
        observed = {
            capture["usb_identity"][field]
            for capture in (*reference_captures, *candidate_captures)
        }
        if observed != {expected}:
            raise ValueError(
                f"reference/candidate USB {field} is not the expected tinySA identity: "
                f"{observed}"
            )

    case_results: list[dict[str, Any]] = []
    for case in ELIGIBLE_CASES:
        reference_grid = reference_captures[0]["observations"][case]["frequencies"]
        candidate_grid = candidate_captures[0]["observations"][case]["frequencies"]
        if reference_grid != candidate_grid:
            raise ValueError(f"case {case} reference/candidate frequency grids differ")
        reference = analyze_group_case(reference_captures, case)
        candidate = analyze_group_case(candidate_captures, case)
        case_results.append({
            "case": case,
            "kind": COMPARATOR.VISUAL.CASE_KIND[case],
            "release_gate": False,
            "reference": reference,
            "candidate": candidate,
            "comparison": compare_persistent_clusters(reference, candidate),
        })

    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "result": "DIAGNOSTIC_COMPLETE",
        "release_gate": False,
        "evidence_scope": "physical hardware repeatability; separate from simulation qualification",
        "reference": {
            "label": reference_label,
            "captures": [capture_summary(capture) for capture in reference_captures],
        },
        "candidate": {
            "label": candidate_label,
            "captures": [capture_summary(capture) for capture in candidate_captures],
        },
        "method": {
            "independent_sweeps_per_firmware": INDEPENDENT_SWEEPS,
            "eligible_cases": list(ELIGIBLE_CASES),
            "main_carrier_guard_bins_each_side": MAIN_GUARD_BINS,
            "frequency_coherence_tolerance_bins": COHERENCE_TOLERANCE_BINS,
            "absolute_local_prominence_floor_db": MINIMUM_LOCAL_PROMINENCE_DB,
            "local_prominence_mad_multiplier": PROMINENCE_MAD_MULTIPLIER,
            "minimum_local_peaks_for_mad": MINIMUM_LOCAL_PEAKS_FOR_MAD,
            "effective_local_prominence_threshold": (
                f"max({MINIMUM_LOCAL_PROMINENCE_DB:g} dB, median + "
                f"{PROMINENCE_MAD_MULTIPLIER:g}*MAD) per sweep when at least "
                f"{MINIMUM_LOCAL_PEAKS_FOR_MAD} local peaks exist; otherwise "
                "the absolute floor"
            ),
            "local_background_radius_bins": LOCAL_BACKGROUND_RADIUS_BINS,
            "local_peak_exclusion_bins": LOCAL_PEAK_EXCLUSION_BINS,
            "classification_is_release_gate": False,
        },
        "cases": case_results,
        "limitations": [
            "frequency coherence does not identify a response's physical source",
            "harmonic attribution is not attempted",
            "three sweeps do not characterize long-term, thermal, cable, or unit-to-unit behavior",
            "candidate-only observations and level differences remain diagnostic",
            "this report does not close the A/B report's pending single-sweep SFDR status",
        ],
    }
    output.mkdir(parents=True, exist_ok=True)
    implementation_dir = output / "implementation"
    implementation_dir.mkdir()
    implementation_sources = {
        "analyze-physical-selftest-spur-persistence.py": TOOL_PATH,
        "compare-physical-selftest-captures.py": COMPARATOR.TOOL_PATH,
        "capture-physical-selftests.py": COMPARATOR.CAPTURE_PATH,
        "compare-selftest-visuals.py": COMPARATOR.VISUAL_PATH,
        "Font5x7.c": COMPARATOR.FONT_PATH,
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
    report["implementation"] = implementation
    (output / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    write_markdown(output, report)
    paths = sorted(
        path for path in output.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS"
    )
    (output / "SHA256SUMS").write_text(
        "".join(
            f"{sha256_file(path)}  {path.relative_to(output)}\n" for path in paths
        ),
        encoding="utf-8",
    )
    return report


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "diagnose frequency persistence across three physical self-test "
            "captures per firmware (non-gating)"
        )
    )
    parser.add_argument("--reference", nargs=INDEPENDENT_SWEEPS, type=Path,
                        required=True, metavar="CAPTURE")
    parser.add_argument("--candidate", nargs=INDEPENDENT_SWEEPS, type=Path,
                        required=True, metavar="CAPTURE")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference-label", default="official")
    parser.add_argument("--candidate-label", default="candidate")
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()
    try:
        report = analyze(
            args.reference, args.candidate, args.output,
            args.reference_label, args.candidate_label,
        )
        print(f"spur_persistence={report['result'].lower()}")
        print("release_gate=false")
        print(f"report={args.output / 'report.md'}")
        return 0
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
