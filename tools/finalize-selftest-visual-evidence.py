#!/usr/bin/env python3
"""Finalize hash-bound, all-14 tinySA self-test visual evidence.

This tool consumes completed Renode capture directories. It does not run
Renode. It reproduces both the historical conservative comparison and the
current exact-or-better comparison, validates their machine-readable reports,
and writes a self-contained evidence tree for the RC release sealer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
COMPARATOR = ROOT / "tools/compare-selftest-visuals.py"
ADVERSARIAL_TEST = ROOT / "tools/test-selftest-visual-comparator.py"
HISTORICAL_COMMIT = "7a89f9943a52e471ca3dcd4688e47897c2698cd3"
HISTORICAL_BLOB = "6c587ca4cd3b6534133b8b61024b180ac8bc5a76"
HISTORICAL_SHA256 = "f590bd5370b8dcf1e408661dd1b76c233e11277964dbab3399a330fdf6c1f3e3"

FRAME_BYTES = 480 * 320 * 2
TRACE_BYTES = 4 * 450 * 4
CASES = tuple(range(1, 15))
NONFLAT_CASES = {1, 2, 3, 4, 5, 6, 7, 8, 10, 11, 14}
ALLOWED_FAILURES = {
    12: {"visual-equivalence", "display-readback-activity"},
    13: {"visual-equivalence"},
}
REQUIRED_RELEASE_CHECKS = {
    "time-grid-cases-present",
    "only-documented-grid-visual-failures",
    "candidate-time-grid-mathematically-current",
    "grid-visual-delta-pixel-explained",
    "display-readback-numeric-activity-preserved",
}
CRITICAL_CASE_CHECKS = {
    "reference-status-schema",
    "candidate-status-schema",
    "reference-trace-memory-complete",
    "candidate-trace-memory-complete",
    "reference-raw-actual-exact",
    "candidate-raw-actual-exact",
    "trace-memory-count-parity",
    "trace-memory-byte-parity",
    "reference-status",
    "reference-capture-valid",
    "firmware-status",
    "not-blank",
    "fixture-selection",
    "cal-fixture-state",
    "trace-coverage",
    "trace-not-degraded-to-flat",
    "measured-trace-populated",
    "reference-trace-populated",
    "frame-counter-consistency",
    "sweep-time-not-slower",
}
ERROR_PATTERN = re.compile(
    r"Errors during compilation|There was an error executing command|"
    r"No such command or device:| assertion failed|Unhandled exception|"
    r"ZS407_TWIN_[A-Z0-9_]*=FAIL"
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SCENARIO_ASSIGNMENT_RE = re.compile(r"^\$(bin|elf|symbols)\s*=\s*@(.+?)\s*$")
SCENARIO_INCLUDE_RE = re.compile(r"^include\s+@(.+?)\s*$")
SCENARIO_SYMBOL_DIRECTIVE_RE = re.compile(r"^\$symbols\b")
TWIN_PROVENANCE_RE = re.compile(
    r"^# twin_(source_commit|renode_tree|tools_tree|bootstrap_blob)=([0-9a-f]{40})$"
)
TWIN_RUNTIME_SOURCE_RE = re.compile(
    r"^# twin_(runtime_source)=(twin-bootstrap|caller-supplied)$"
)
TWIN_RUNTIME_HASH_RE = re.compile(
    r"^# twin_(runtime_sha256)=([0-9a-f]{64})$"
)
PINNED_LAB_SYMBOL_DEFAULT = (
    "$symbols ?= $ORIGIN/symbols/v0.2.0-protocol-v2.symbols"
)

BASELINES = {
    "lab": {
        "release": "lab-v0.2.0-protocol",
        "source_commit": "d12bd826555eee51505542a55fd184ade5817d58",
        "bin": "a1dbaa03978a25b2a8b2a0e85f60029a6cc736481732eff68e93362724683dd7",
        "elf": "3a8732fcaac5595e8ad21fe656ecb7e7300a12a760f453c3c1c296b733f72f43",
        "symbols": "4d91ed7abdc26b1df4c575901e629d2d3f067758ee74ea86560af0b1e75421c1",
    },
    "official-c979": {
        "release": "official tinySA4 v1.4-224-gc979386",
        "source_commit": "c979386",
        "bin": "3c9847ff4d7b80561df2f2f1030a112703a083409ffb2ee11361b2413b7c1e41",
        "elf": "d74099496ba074f41f91358cbc1ff3f92ea388c0b7b60221da59cb61f64c397d",
        "symbols": "117d3c0f998b70d65f48ec28f3367767a1f9058833e9749c443b7dffa1f064c6",
    },
}


class FinalizeError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=sorted(BASELINES), required=True)
    parser.add_argument(
        "--twin-root",
        type=Path,
        required=True,
        help="TinySA_Twin checkout containing the commit recorded by each capture",
    )
    parser.add_argument("--reference-capture", type=Path, required=True)
    parser.add_argument("--candidate-capture", type=Path, required=True)
    parser.add_argument("--reference-bin", type=Path, required=True)
    parser.add_argument("--reference-elf", type=Path, required=True)
    parser.add_argument("--reference-symbols", type=Path, required=True)
    parser.add_argument("--candidate-bin", type=Path, required=True)
    parser.add_argument("--candidate-elf", type=Path, required=True)
    parser.add_argument("--candidate-symbols", type=Path, required=True)
    parser.add_argument("--candidate-bin-sha256", required=True)
    parser.add_argument("--candidate-elf-sha256", required=True)
    parser.add_argument("--candidate-symbols-sha256", required=True)
    parser.add_argument("--candidate-release", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--human-review",
        choices=("PASS", "FAIL"),
        required=True,
        help="explicit contact-sheet review result; FAIL is rejected",
    )
    parser.add_argument("--human-reviewer", required=True)
    parser.add_argument("--human-review-attestation", required=True)
    return parser.parse_args()


def reject(condition: bool, message: str) -> None:
    if not condition:
        raise FinalizeError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_expected_hash(value: str, label: str) -> str:
    reject(bool(SHA256_RE.fullmatch(value)), f"{label} is not a lowercase SHA-256")
    return value


def validate_hashed_file(path: Path, expected: str, label: str) -> Path:
    path = path.expanduser().resolve()
    reject(path.is_file() and not path.is_symlink(), f"{label} is not a regular file: {path}")
    actual = sha256(path)
    reject(actual == expected, f"{label} SHA-256 is {actual}; expected {expected}")
    return path


def safe_text(value: str, label: str, minimum: int = 1) -> str:
    normalized = " ".join(value.split())
    reject(len(normalized) >= minimum, f"{label} is too short")
    reject("=" not in normalized, f"{label} must not contain '='")
    return normalized


def required_capture_names() -> list[str]:
    names = ["run.log", "run.raw.log", "run.resc"]
    for case in CASES:
        names.extend(
            (
                f"case-{case:02d}.png",
                f"case-{case:02d}.rgb565",
                f"case-{case:02d}-measured.f32le",
            )
        )
    return names


def png_dimensions(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    reject(
        len(header) == 24
        and header[:8] == b"\x89PNG\r\n\x1a\n"
        and header[12:16] == b"IHDR",
        f"invalid PNG header: {path}",
    )
    return struct.unpack(">II", header[16:24])


def twin_paths(twin_root: Path) -> tuple[Path, Path, Path]:
    renode = twin_root / "digital-twin/renode"
    return (
        (renode / "zs407.resc").resolve(),
        (renode / "tests/selftest-visual-body.resc").resolve(),
        (renode / "symbols/v0.2.0-protocol-v2.symbols").resolve(),
    )


def scenario_twin_identity(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(errors="strict").splitlines():
        match = TWIN_PROVENANCE_RE.fullmatch(line)
        if not match:
            match = TWIN_RUNTIME_SOURCE_RE.fullmatch(line)
        if not match:
            match = TWIN_RUNTIME_HASH_RE.fullmatch(line)
        if not match:
            continue
        name, value = match.groups()
        reject(name not in values, f"duplicate twin provenance {name} in {path}")
        values[name] = value
    reject(
        set(values)
        == {
            "source_commit",
            "renode_tree",
            "tools_tree",
            "bootstrap_blob",
            "runtime_source",
            "runtime_sha256",
        },
        f"{path} does not contain complete post-split twin provenance",
    )
    return values


def validate_twin_identity(twin_root: Path, identity: dict[str, str]) -> None:
    reject(
        twin_root.is_dir() and not twin_root.is_symlink(),
        f"twin root is not a regular directory: {twin_root}",
    )
    commit = git_output(
        "rev-parse", f"{identity['source_commit']}^{{commit}}", root=twin_root
    ).decode().strip()
    reject(commit == identity["source_commit"], "recorded twin commit is not exact")
    tree = git_output(
        "rev-parse",
        f"{commit}:digital-twin/renode",
        root=twin_root,
    ).decode().strip()
    bootstrap = git_output(
        "rev-parse",
        f"{commit}:tools/bootstrap-renode.sh",
        root=twin_root,
    ).decode().strip()
    tools_tree = git_output(
        "rev-parse",
        f"{commit}:tools",
        root=twin_root,
    ).decode().strip()
    reject(tree == identity["renode_tree"], "recorded twin Renode tree does not match its commit")
    reject(
        tools_tree == identity["tools_tree"],
        "recorded twin tools tree does not match its commit",
    )
    reject(
        bootstrap == identity["bootstrap_blob"],
        "recorded twin bootstrap blob does not match its commit",
    )


def prove_lab_default_symbols(
    path: Path,
    supplied_symbols: Path,
    twin_root: Path,
    twin_identity: dict[str, str],
) -> Path:
    main_scenario, visual_body, pinned_symbols = twin_paths(twin_root)
    reject(
        supplied_symbols.resolve() == pinned_symbols,
        "implicit lab symbols require the exact twin-pinned symbol file",
    )
    validate_hashed_file(
        pinned_symbols, BASELINES["lab"]["symbols"], "pinned lab symbols"
    )

    scenario_lines = path.read_text(errors="strict").splitlines()
    includes = []
    for line in scenario_lines:
        match = SCENARIO_INCLUDE_RE.match(line)
        if not match:
            continue
        include_path = Path(match.group(1))
        if not include_path.is_absolute():
            include_path = path.parent / include_path
        includes.append(include_path.resolve())
    reject(
        includes == [main_scenario, visual_body],
        "implicit lab symbols require only the exact main zs407.resc followed "
        "by the exact self-test visual body",
    )
    reject(
        main_scenario.is_file() and not main_scenario.is_symlink(),
        "main zs407.resc is not a regular twin file",
    )
    reject(
        visual_body.is_file() and not visual_body.is_symlink(),
        "self-test visual body is not a regular twin file",
    )
    commit = twin_identity["source_commit"]
    scenario_bytes = git_output(
        "show", f"{commit}:digital-twin/renode/zs407.resc", root=twin_root
    )
    visual_body_bytes = git_output(
        "show",
        f"{commit}:digital-twin/renode/tests/selftest-visual-body.resc",
        root=twin_root,
    )
    recorded_symbol_bytes = git_output(
        "show",
        f"{commit}:digital-twin/renode/symbols/v0.2.0-protocol-v2.symbols",
        root=twin_root,
    )
    reject(
        hashlib.sha256(recorded_symbol_bytes).hexdigest()
        == BASELINES["lab"]["symbols"],
        "recorded twin commit's lab symbols do not match the baseline",
    )
    reject(
        pinned_symbols.read_bytes() == recorded_symbol_bytes,
        "current pinned lab symbols differ from the recorded twin commit",
    )
    default_count = scenario_bytes.decode(errors="strict").splitlines().count(
        PINNED_LAB_SYMBOL_DEFAULT
    )
    reject(
        default_count == 1,
        "main zs407.resc does not contain the exact pinned lab-symbol default",
    )
    reject(bool(visual_body_bytes), "recorded self-test visual body is empty")
    return pinned_symbols


def scenario_artifacts(
    path: Path,
    *,
    allow_lab_default_symbols: bool,
    supplied_symbols: Path,
    twin_root: Path,
) -> tuple[dict[str, Path], str, dict[str, str]]:
    twin_identity = scenario_twin_identity(path)
    validate_twin_identity(twin_root, twin_identity)
    assignments: dict[str, Path] = {}
    for line in path.read_text(errors="strict").splitlines():
        match = SCENARIO_ASSIGNMENT_RE.match(line)
        if not match:
            reject(
                SCENARIO_SYMBOL_DIRECTIVE_RE.match(line) is None,
                f"unrecognized symbol directive in {path}: {line}",
            )
            continue
        name, raw_path = match.groups()
        reject(name not in assignments, f"duplicate ${name} assignment in {path}")
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = path.parent / candidate
        assignments[name] = candidate.resolve()
    binding = "explicit"
    if "symbols" not in assignments:
        reject(
            allow_lab_default_symbols,
            f"{path} must bind symbols explicitly",
        )
        assignments["symbols"] = prove_lab_default_symbols(
            path, supplied_symbols, twin_root, twin_identity
        )
        binding = "zs407-pinned-default"
    reject(
        set(assignments) == {"bin", "elf", "symbols"},
        f"{path} must bind bin, elf, and symbols",
    )
    return assignments, binding, twin_identity


def marker_count(log: str, marker: str) -> int:
    return sum(marker in line for line in log.splitlines())


def capture_counts(log: str) -> dict[str, int]:
    return {
        "pass": marker_count(log, "ZS407_TWIN_SELFTEST=PASS case="),
        "ready": marker_count(log, "ZS407_TWIN_SELFTEST_VISUAL=READY case="),
        "settled": marker_count(log, "ZS407_TWIN_SELFTEST_DISPLAY=VISUALLY_SETTLED case="),
        "status": marker_count(log, "ZS407_TWIN_SELFTEST_STATUS case="),
        "screens": marker_count(log, "ZS407_TWIN_SCREEN=SAVED"),
        "traces": marker_count(log, "ZS407_TWIN_SELFTEST_TRACE_MEMORY=SAVED case="),
    }


def validate_capture(
    capture: Path,
    label: str,
    artifact_hashes: dict[str, str],
    symbol_profile: Path,
    twin_root: Path,
    *,
    allow_lab_default_symbols: bool = False,
) -> tuple[dict[str, int], str, dict[str, str]]:
    capture = capture.expanduser().resolve()
    reject(capture.is_dir() and not capture.is_symlink(), f"{label} capture is not a directory: {capture}")
    expected_names = set(required_capture_names())
    actual_case_names = {path.name for path in capture.glob("case-*")}
    reject(
        actual_case_names == {name for name in expected_names if name.startswith("case-")},
        f"{label} capture case files are missing or unexpected",
    )
    for name in expected_names:
        path = capture / name
        reject(path.is_file() and not path.is_symlink() and path.stat().st_size > 0, f"missing or empty {label} artifact: {path}")

    for case in CASES:
        raw = capture / f"case-{case:02d}.rgb565"
        measured = capture / f"case-{case:02d}-measured.f32le"
        png = capture / f"case-{case:02d}.png"
        payload = raw.read_bytes()
        reject(len(payload) == FRAME_BYTES, f"{raw} is not a complete 480x320 RGB565 frame")
        nonblack = sum(payload[offset] != 0 or payload[offset + 1] != 0 for offset in range(0, len(payload), 2))
        reject(nonblack >= 1000, f"{label} case {case:02d} is blank ({nonblack} nonblack pixels)")
        trace_payload = measured.read_bytes()
        reject(len(trace_payload) == TRACE_BYTES, f"{measured} is not a complete four-plane trace matrix")
        values = struct.unpack("<1800f", trace_payload)
        planes: list[tuple[float, ...]] = []
        for plane in range(4):
            plane_values = values[plane * 450 : (plane + 1) * 450]
            planes.append(plane_values)
            reject(all(math.isfinite(value) for value in plane_values), f"{label} case {case:02d} trace plane {plane} is nonfinite")
            reject(all(abs(value) > 0.000001 for value in plane_values), f"{label} case {case:02d} trace plane {plane} is blank/unpopulated")
        if case in NONFLAT_CASES:
            reject(
                max(planes[0]) - min(planes[0]) > 0.000001,
                f"{label} case {case:02d} measured trace is flat",
            )
        reject(png_dimensions(png) == (480, 320), f"{png} is not 480x320")

    normalized_bytes = (capture / "run.log").read_bytes()
    raw_bytes = (capture / "run.raw.log").read_bytes()
    reject(
        raw_bytes.replace(b"\r", b"") == normalized_bytes,
        f"{label} run.log is not the CR-normalized raw log",
    )
    log = normalized_bytes.decode(errors="strict")
    counts = capture_counts(log)
    reject(all(value == 14 for value in counts.values()), f"{label} capture counters are incomplete: {counts}")
    reject(ERROR_PATTERN.search(log) is None, f"{label} run.log contains a harness/error marker")
    reject("Renode is quitting" in log, f"{label} run.log does not contain a clean Renode quit")
    loaded_profile_marker = (
        f"ZS407_TWIN_SYMBOLS=LOADED profile={symbol_profile.name}"
    )
    loaded_profile_count = sum(
        line == loaded_profile_marker or line.startswith(loaded_profile_marker + " ")
        for line in log.splitlines()
    )
    reject(
        loaded_profile_count == 1,
        f"{label} run.log has {loaded_profile_count} exact loaded-symbol-profile markers; expected 1",
    )
    raw_log = raw_bytes.decode(errors="strict")
    reject(ERROR_PATTERN.search(raw_log) is None, f"{label} run.raw.log contains a harness/error marker")

    assignments, symbol_binding, twin_identity = scenario_artifacts(
        capture / "run.resc",
        allow_lab_default_symbols=allow_lab_default_symbols,
        supplied_symbols=symbol_profile,
        twin_root=twin_root,
    )
    for name, expected in artifact_hashes.items():
        validate_hashed_file(assignments[name], expected, f"{label} scenario ${name}")
    return counts, symbol_binding, twin_identity


def capture_inventory_hash(capture: Path) -> str:
    payload = "".join(
        f"{sha256(capture / name)}  ./{name}\n" for name in sorted(required_capture_names())
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def copy_capture(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True)
    for name in required_capture_names():
        shutil.copyfile(source.resolve() / name, destination / name)


def git_output(
    *arguments: str,
    input_bytes: bytes | None = None,
    root: Path = ROOT,
) -> bytes:
    process = subprocess.run(
        ["git", "-C", str(root), *arguments],
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    reject(process.returncode == 0, f"git {' '.join(arguments)} failed: {process.stderr.decode(errors='replace').strip()}")
    return process.stdout


def write_comparator_record(directory: Path, command: list[str], process: subprocess.CompletedProcess[str]) -> None:
    evidence_root = directory.parent
    normalized_command = [
        argument.replace(str(evidence_root), "$EVIDENCE") for argument in command
    ]
    normalized_command[0] = "$PYTHON"
    normalized_stdout = process.stdout.replace(str(evidence_root), "$EVIDENCE")
    normalized_stderr = process.stderr.replace(str(evidence_root), "$EVIDENCE")
    record = [
        f"exit_status={process.returncode}",
        "pythonhashseed=0",
        "command=" + " ".join(normalized_command),
        "stdout:",
        normalized_stdout.rstrip(),
        "stderr:",
        normalized_stderr.rstrip(),
        "",
    ]
    (directory / "COMPARATOR_RUN.txt").write_text("\n".join(record))


def run_comparator(
    script: Path,
    reference: Path,
    candidate: Path,
    output: Path,
    artifacts: dict[str, Path],
) -> subprocess.CompletedProcess[str]:
    output.mkdir(parents=True)
    command = [
        sys.executable,
        str(script),
        "--reference",
        str(reference),
        "--candidate",
        str(candidate),
        "--output",
        str(output),
        "--reference-bin",
        str(artifacts["reference_bin"]),
        "--reference-elf",
        str(artifacts["reference_elf"]),
        "--candidate-bin",
        str(artifacts["candidate_bin"]),
        "--candidate-elf",
        str(artifacts["candidate_elf"]),
    ]
    environment = os.environ.copy()
    environment["PYTHONHASHSEED"] = "0"
    process = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        env=environment,
    )
    write_comparator_record(output, command, process)
    return process


def artifact_report_hashes(report: dict[str, object]) -> dict[str, str | None]:
    metadata = report.get("artifacts", {})
    reject(isinstance(metadata, dict), "comparator artifact metadata is missing")
    result: dict[str, str | None] = {}
    for name in ("reference_bin", "reference_elf", "candidate_bin", "candidate_elf"):
        item = metadata.get(name)
        result[name] = item.get("sha256") if isinstance(item, dict) else None
    return result


def load_report(path: Path) -> dict[str, object]:
    try:
        report = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise FinalizeError(f"cannot load comparator report {path}: {error}") from error
    reject(report.get("schema") == "tinysa-selftest-visual-regression-v2", f"unexpected report schema in {path}")
    return report


def validate_historical_report(
    path: Path,
    expected_artifacts: dict[str, str],
    require_rejection: bool,
) -> dict[str, object]:
    report = load_report(path)
    reject(artifact_report_hashes(report) == expected_artifacts, "historical report is not bound to the exact firmware artifacts")
    cases = report.get("cases")
    reject(isinstance(cases, list) and [item.get("case") for item in cases] == list(CASES), "historical report does not contain cases 1 through 14")
    classification = report.get("release_classification", {})
    if require_rejection:
        reject(classification.get("pass") is False and classification.get("mode") == "rejected", "official-c979 historical comparator did not reproduce the reviewed rejection")
    return report


def validate_current_report(
    path: Path,
    root: Path,
    expected_artifacts: dict[str, str],
) -> dict[str, object]:
    report = load_report(path)
    reject(artifact_report_hashes(report) == expected_artifacts, "current report is not bound to the exact firmware artifacts")
    classification = report.get("release_classification", {})
    reject(classification.get("pass") is True, "current release classifier did not pass")
    reject(classification.get("mode") == "mathematically-better-time-grid", "current classifier mode is not the reviewed exact-or-better mode")
    release_checks = classification.get("checks", [])
    release_by_name = {item.get("name"): item.get("pass") for item in release_checks}
    reject(set(release_by_name) == REQUIRED_RELEASE_CHECKS and all(release_by_name.values()), "release-classifier checks are missing, extra, or failed")

    cases = report.get("cases")
    reject(isinstance(cases, list) and [item.get("case") for item in cases] == list(CASES), "current report does not contain cases 1 through 14")
    for item in cases:
        case = item["case"]
        checks = item.get("checks", [])
        by_name = {check.get("name"): check.get("pass") for check in checks}
        reject(CRITICAL_CASE_CHECKS <= set(by_name), f"case {case:02d} lacks critical visual/trace checks")
        failures = {name for name, passed in by_name.items() if passed is not True}
        reject(failures == ALLOWED_FAILURES.get(case, set()), f"case {case:02d} failures are {sorted(failures)}")
        if case == 8:
            reject(by_name.get("bpf-flatness-quality") is True, "case 08 lacks the BPF-flatness quality gate")
        if case == 12:
            reject(by_name.get("display-readback-numeric-activity") is True, "case 12 lacks exact display-read activity")
        if case == 13:
            reject(by_name.get("attenuator-step-activity") is True, "case 13 lacks attenuator-step activity")
        if case in (12, 13):
            objective = {check.get("name"): check.get("pass") for check in item.get("objective_checks", [])}
            reject(objective == {"time-grid-current": True, "time-grid-visual-delta-explained": True}, f"case {case:02d} lacks objective time-grid proof")

        trace_hashes = []
        for variant in ("reference", "candidate"):
            data = item.get(variant, {})
            firmware = data.get("firmware", {})
            frame = data.get("frame", {})
            trace = data.get("trace_memory", {})
            reject(firmware.get("fixture") == case and firmware.get("status") == 1, f"case {case:02d} {variant} firmware status/fixture is invalid")
            reject(frame.get("nonblack_pixels", 0) >= 1000, f"case {case:02d} {variant} frame is blank")
            if case in NONFLAT_CASES:
                reject(frame.get("trace_vertical_span", 0) > 0, f"case {case:02d} {variant} visible trace is flat")
            reject(trace.get("bytes") == TRACE_BYTES and trace.get("points_per_plane") == 450, f"case {case:02d} {variant} trace matrix is incomplete")
            reject(trace.get("planes") == ["actual", "stored", "stored2", "raw"], f"case {case:02d} {variant} trace plane order is invalid")
            exact = trace.get("raw_actual", {})
            reject(exact.get("exact_mismatches") == 0 and exact.get("nonfinite_pairs") == 0, f"case {case:02d} {variant} raw/actual trace planes differ")
            for plane in trace["planes"]:
                metrics = trace.get("traces", {}).get(plane, {})
                reject(metrics.get("finite") == 450 and metrics.get("populated") == 450, f"case {case:02d} {variant} {plane} trace is blank/incomplete")
            number = f"{case:02d}"
            raw = root / variant / f"case-{number}.rgb565"
            measured = root / variant / f"case-{number}-measured.f32le"
            reject(sha256(raw) == frame.get("sha256"), f"case {case:02d} {variant} frame hash mismatch")
            reject(sha256(measured) == trace.get("sha256"), f"case {case:02d} {variant} trace hash mismatch")
            trace_hashes.append(trace.get("sha256"))
        reject(trace_hashes[0] == trace_hashes[1], f"case {case:02d} trace matrices are not byte-identical")
        reject((root / "comparison" / f"case-{case:02d}-diff.png").is_file(), f"case {case:02d} diff is missing")
    for name in ("contact-cases-01-07.png", "contact-cases-08-14.png"):
        reject((root / "comparison" / name).is_file(), f"contact sheet is missing: {name}")
    return report


def compressed_cases(cases: list[int]) -> str:
    if not cases:
        return "none"
    groups: list[tuple[int, int]] = []
    start = previous = cases[0]
    for case in cases[1:]:
        if case == previous + 1:
            previous = case
            continue
        groups.append((start, previous))
        start = previous = case
    groups.append((start, previous))
    return ",".join(f"{start:02d}" if start == end else f"{start:02d}-{end:02d}" for start, end in groups)


def report_values(report: dict[str, object]) -> dict[str, object]:
    cases = report["cases"]
    strict_pass = [item["case"] for item in cases if item.get("pass") is True]
    strict_fail = [item["case"] for item in cases if item.get("pass") is not True]
    spans = [
        (item["case"], item["reference"]["frame"]["trace_vertical_span"], item["candidate"]["frame"]["trace_vertical_span"])
        for item in cases
    ]
    parity = sum(item["reference"]["trace_memory"]["sha256"] == item["candidate"]["trace_memory"]["sha256"] for item in cases)
    raw_exact = sum(
        all(
            item[variant]["trace_memory"]["raw_actual"]["exact_mismatches"] == 0
            and item[variant]["trace_memory"]["raw_actual"]["nonfinite_pairs"] == 0
            for variant in ("reference", "candidate")
        )
        for item in cases
    )
    return {
        "strict_pass": strict_pass,
        "strict_fail": strict_fail,
        "spans": spans,
        "parity": parity,
        "raw_exact": raw_exact,
        "case12": cases[11],
        "case13": cases[12],
    }


def write_human_review(stage: Path, reviewer: str, attestation: str) -> None:
    (stage / "HUMAN_REVIEW.txt").write_text(
        "status=PASS\n"
        f"reviewer={reviewer}\n"
        "scope=all 14 reference/candidate/difference panels in the two generated contact sheets\n"
        "attestation:\n"
        f"{attestation}\n"
    )


def write_summary(
    stage: Path,
    args: argparse.Namespace,
    baseline: dict[str, str],
    candidate_hashes: dict[str, str],
    reference_counts: dict[str, int],
    candidate_counts: dict[str, int],
    reference_symbol_binding: str,
    candidate_symbol_binding: str,
    report: dict[str, object],
    historical: dict[str, object],
) -> None:
    values = report_values(report)
    case12 = values["case12"]
    case13 = values["case13"]
    spans = ",".join(f"{case:02d}:{reference}/{candidate}" for case, reference, candidate in values["spans"])
    historical_classification = historical["release_classification"]
    current_report_hash = sha256(stage / "comparison/report.json")
    historical_report_hash = sha256(stage / "comparison-original-rejected/report.json")
    review_hash = sha256(stage / "HUMAN_REVIEW.txt")
    counter_names = {
        "pass": "selftest_pass",
        "ready": "visual_ready",
        "settled": "visually_settled",
        "status": "status",
        "screens": "screen_raw_saved",
        "traces": "trace_memory_saved",
    }
    counter = lambda counts: ",".join(f"{counter_names[name]}:{counts[name]}/14" for name in counter_names)
    common = [
        "schema=tinysa-selftest-visual-finalized-v1",
        f"baseline_mode={args.mode}",
        f"candidate_release={args.candidate_release}",
        "qualification_scope=Renode digital-twin paired all-14 self-test visual and four-plane trace comparison",
        "hardware_qualified=false",
        f"reference_release={baseline['release']}",
        f"reference_source_commit={baseline['source_commit']}",
        f"reference_bin_sha256={baseline['bin']}",
        f"reference_elf_sha256={baseline['elf']}",
        f"reference_symbol_profile_sha256={baseline['symbols']}",
        f"candidate_bin_sha256={candidate_hashes['bin']}",
        f"candidate_elf_sha256={candidate_hashes['elf']}",
        f"candidate_symbol_profile_sha256={candidate_hashes['symbols']}",
        f"reference_symbol_binding={reference_symbol_binding}",
        f"candidate_symbol_binding={candidate_symbol_binding}",
        f"reference_counters={counter(reference_counts)}",
        f"candidate_counters={counter(candidate_counts)}",
        "reference_error_patterns=0",
        "candidate_error_patterns=0",
        "release_classifier=PASS",
        "release_classifier_mode=mathematically-better-time-grid",
        f"strict_legacy_comparator_pass={str(report['pass']).lower()}",
        "release_classification_pass=true",
        f"strict_legacy_cases_pass={compressed_cases(values['strict_pass'])}",
        f"strict_legacy_cases_fail={compressed_cases(values['strict_fail'])}",
        f"historical_classifier_pass={str(historical_classification['pass']).lower()}",
        f"historical_classifier_mode={historical_classification['mode']}",
        f"historical_report_sha256={historical_report_hash}",
        f"final_report_sha256={current_report_hash}",
        f"trace_memory_matrix_parity={values['parity']}/14",
        "trace_memory_matrix_per_case=7200 bytes;4 planes x 450 float32 points",
        f"trace_raw_actual_plane_exact={values['raw_exact']}/14",
        "nonflat_real_trace_gate=PASS;structured cases 01,02,03,04,05,06,07,08,10,11,14 retain nonzero visible spans",
        f"reference_candidate_trace_spans_px={spans}",
        f"case_12_reference_grid_columns={','.join(map(str, case12['time_grid']['reference']['observed_columns']))}",
        f"case_12_candidate_expected_observed_grid_columns={','.join(map(str, case12['time_grid']['candidate']['observed_columns']))}",
        f"case_12_grid_pixels={case12['time_grid']['visual_delta']['grid_pixels']}",
        f"case_12_time_text_pixels={case12['time_grid']['visual_delta']['time_text_pixels']}",
        f"case_12_unexplained_pixels={case12['time_grid']['visual_delta']['unexplained_pixels']}",
        f"case_13_reference_grid_columns={','.join(map(str, case13['time_grid']['reference']['observed_columns']))}",
        f"case_13_candidate_expected_observed_grid_columns={','.join(map(str, case13['time_grid']['candidate']['observed_columns']))}",
        f"case_13_grid_pixels={case13['time_grid']['visual_delta']['grid_pixels']}",
        f"case_13_time_text_pixels={case13['time_grid']['visual_delta']['time_text_pixels']}",
        f"case_13_unexplained_pixels={case13['time_grid']['visual_delta']['unexplained_pixels']}",
        "manual_contact_sheet_review=PASS",
        f"human_review_attestation_sha256={review_hash}",
        "human_review_attestation=HUMAN_REVIEW.txt",
        "canonical_report=comparison/report.json",
        "contact_sheets=comparison/contact-cases-01-07.png,comparison/contact-cases-08-14.png",
    ]
    if args.mode == "lab":
        common.extend(
            (
                "reference_role=direct_pre_chibios_behavioral_ancestor_not_official_c979_rollback",
                "trace_memory_byte_parity=14/14 exact lab-baseline-vs-candidate matrices",
            )
        )
    else:
        reference_log = (stage / "reference/run.log").read_text()
        candidate_log = (stage / "candidate/run.log").read_text()
        reference_warnings = marker_count(reference_log, "[WARNING]")
        candidate_warnings = marker_count(candidate_log, "[WARNING]")
        reference_writes = case12["reference"]["firmware"]["case_pixel_writes"]
        candidate_writes = case12["candidate"]["firmware"]["case_pixel_writes"]
        ratio = candidate_writes / reference_writes
        common.extend(
            (
                f"reference_pass={reference_counts['pass']}/14",
                f"reference_ready={reference_counts['ready']}/14",
                f"reference_visually_settled={reference_counts['settled']}/14",
                f"reference_status={reference_counts['status']}/14",
                f"reference_raw_screens={reference_counts['screens']}/14",
                f"reference_trace_matrices={reference_counts['traces']}/14",
                f"candidate_pass={candidate_counts['pass']}/14",
                f"candidate_ready={candidate_counts['ready']}/14",
                f"candidate_visually_settled={candidate_counts['settled']}/14",
                f"candidate_status={candidate_counts['status']}/14",
                f"candidate_raw_screens={candidate_counts['screens']}/14",
                f"candidate_trace_matrices={candidate_counts['traces']}/14",
                "harness_error_markers=0",
                f"reference_model_warning_lines={reference_warnings}",
                f"candidate_model_warning_lines={candidate_warnings}",
                f"trace_matrix_byte_parity={values['parity']}/14",
                f"strict_visual_cases_pass={compressed_cases(values['strict_pass'])}",
                f"strict_visual_cases_fail={compressed_cases(values['strict_fail'])}",
                "original_conservative_release_classifier=REJECTED_PRESERVED",
                f"original_rejected_report_sha256={historical_report_hash}",
                "final_release_classifier=PASS",
                "final_release_classifier_mode=mathematically-better-time-grid",
                "engineering_assessment=PASS_EXACT_OR_BETTER",
                f"case12_display_read_bytes={case12['reference']['firmware']['case_display_read_bytes']}/{case12['candidate']['firmware']['case_display_read_bytes']}",
                f"case12_pixel_writes={reference_writes}/{candidate_writes}",
                f"case12_candidate_write_ratio={ratio:.9f}",
                f"case12_unexplained_pixels={case12['time_grid']['visual_delta']['unexplained_pixels']}",
                f"case13_time_text_pixels={case13['time_grid']['visual_delta']['time_text_pixels']}",
                f"case13_maximum_bounded_time_text_pixels={case13['time_grid']['visual_delta']['time_text_pixel_limit']}",
                f"case13_unexplained_pixels={case13['time_grid']['visual_delta']['unexplained_pixels']}",
                "candidate_time_grid_current=12,13",
                "official_time_grid_stale=12,13",
                "human_contact_sheet_review=PASS",
                "candidate_firmware_bytes_modified=false",
                "classifier_adversarial_boundary_test=PASS",
            )
        )
    (stage / "SUMMARY.txt").write_text("\n".join(common) + "\n")


def write_provenance(
    stage: Path,
    args: argparse.Namespace,
    baseline: dict[str, str],
    artifacts: dict[str, Path],
    candidate_hashes: dict[str, str],
    historical_blob_sha256: str,
    current_blob: str,
    current_commit: str,
    current_sha256: str,
    adversarial_blob: str,
    adversarial_sha256: str,
    reference_capture: Path,
    candidate_capture: Path,
    reference_capture_hash: str,
    candidate_capture_hash: str,
    reference_symbol_binding: str,
    candidate_symbol_binding: str,
    twin_root: Path,
    twin_identity: dict[str, str],
) -> None:
    lines = [
        "schema=tinysa-selftest-visual-provenance-v1",
        f"purpose=Finalize all-14 {args.mode} reference/candidate screenshots and four-plane trace matrices",
        f"reference_release={baseline['release']}",
        f"reference_bin={artifacts['reference_bin']}",
        f"reference_bin_sha256={baseline['bin']}",
        f"reference_elf={artifacts['reference_elf']}",
        f"reference_elf_sha256={baseline['elf']}",
        f"reference_symbol_profile={artifacts['reference_symbols']}",
        f"reference_symbol_profile_sha256={baseline['symbols']}",
        f"packaged_reference_symbol_profile=reference/{artifacts['reference_symbols'].name}",
        f"reference_symbol_binding={reference_symbol_binding}",
        f"reference_capture_source={reference_capture}",
        f"reference_capture_source_inventory_sha256={reference_capture_hash}",
        f"candidate_release={args.candidate_release}",
        f"candidate_bin={artifacts['candidate_bin']}",
        f"candidate_bin_sha256={candidate_hashes['bin']}",
        f"candidate_elf={artifacts['candidate_elf']}",
        f"candidate_elf_sha256={candidate_hashes['elf']}",
        f"candidate_symbol_profile={artifacts['candidate_symbols']}",
        f"candidate_symbol_profile_sha256={candidate_hashes['symbols']}",
        f"packaged_candidate_symbol_profile=candidate/{artifacts['candidate_symbols'].name}",
        f"candidate_symbol_binding={candidate_symbol_binding}",
        f"candidate_capture_source={candidate_capture}",
        f"candidate_capture_source_inventory_sha256={candidate_capture_hash}",
        f"twin_root={twin_root}",
        f"twin_source_commit={twin_identity['source_commit']}",
        f"twin_renode_tree={twin_identity['renode_tree']}",
        f"twin_tools_tree={twin_identity['tools_tree']}",
        f"twin_bootstrap_blob={twin_identity['bootstrap_blob']}",
        f"renode_runtime_source={twin_identity['runtime_source']}",
        f"renode_runtime_sha256={twin_identity['runtime_sha256']}",
        f"historical_comparator_commit={HISTORICAL_COMMIT}",
        f"historical_comparator_git_blob={HISTORICAL_BLOB}",
        f"historical_comparator_sha256={historical_blob_sha256}",
        f"current_comparator_source_commit={current_commit}",
        f"current_comparator_git_blob={current_blob}",
        f"current_comparator_sha256={current_sha256}",
        f"current_adversarial_test_git_blob={adversarial_blob}",
        f"current_adversarial_test_sha256={adversarial_sha256}",
        "historical_comparison=comparison-original-rejected/report.json",
        "current_comparison=comparison/report.json",
        "human_review_status=PASS",
        "human_review_attestation=HUMAN_REVIEW.txt",
        "candidate_firmware_bytes_modified=false",
    ]
    (stage / "PROVENANCE.txt").write_text("\n".join(lines) + "\n")


def write_supplemental(stage: Path, args: argparse.Namespace, report: dict[str, object], historical: dict[str, object]) -> None:
    values = report_values(report)
    case12 = values["case12"]
    case13 = values["case13"]
    reference_writes = case12["reference"]["firmware"]["case_pixel_writes"]
    candidate_writes = case12["candidate"]["firmware"]["case_pixel_writes"]
    ratio = candidate_writes / reference_writes
    spans = "; ".join(f"{case:02d} {reference}/{candidate}" for case, reference, candidate in values["spans"])
    historical_classification = historical["release_classification"]
    text = f"""Supplemental {args.mode} visual comparison analysis
====================================================

Evidence completeness
---------------------
Both firmware variants produced 14/14 PASS, READY, VISUALLY_SETTLED, STATUS,
complete 307,200-byte LCD captures, and complete 7,200-byte four-plane trace
matrices. All {values['parity']}/14 reference/candidate trace matrices are
byte-identical, and all {values['raw_exact']}/14 raw/actual plane pairs are
exact. Blank frames, unpopulated trace planes, missing captures, and a flat
candidate in any structurally non-flat reference case are rejected.

Visible trace spans
-------------------
Reference/candidate vertical spans in pixels are: {spans}.
The legitimately flat display cases remain backed by populated measured
memory, exact trace parity, fixture/status gates, and activity-specific gates;
success is not inferred from a flat LCD line.

Historical and current classifiers
----------------------------------
The exact comparator blob at commit {HISTORICAL_COMMIT} produced
pass={str(historical_classification['pass']).lower()} and
mode={historical_classification['mode']}; its complete output is preserved in
comparison-original-rejected/. The current comparator produced the reviewed
PASS mode mathematically-better-time-grid in comparison/.

Case 12
-------
The candidate performed {case12['candidate']['firmware']['case_display_read_bytes']:,}
display-read bytes versus {case12['reference']['firmware']['case_display_read_bytes']:,}
for the reference. Candidate/reference case pixel writes were
{candidate_writes:,}/{reference_writes:,} (ratio {ratio:.9f}). The candidate
grid is formula-current. Its frame delta contains
{case12['time_grid']['visual_delta']['grid_pixels']:,} grid/intersection pixels,
{case12['time_grid']['visual_delta']['time_text_pixels']:,} bounded time-text
pixels, and {case12['time_grid']['visual_delta']['unexplained_pixels']} unexplained
pixels.

Case 13
-------
Both variants performed the required attenuator-step activity. The candidate
grid is formula-current. Its frame delta contains
{case13['time_grid']['visual_delta']['grid_pixels']:,} grid/intersection pixels,
{case13['time_grid']['visual_delta']['time_text_pixels']:,} bounded time-text
pixels (limit {case13['time_grid']['visual_delta']['time_text_pixel_limit']}), and
{case13['time_grid']['visual_delta']['unexplained_pixels']} unexplained pixels.

Review attestation
------------------
The finalizer did not infer human review. It was invoked with the explicit
PASS review argument and preserves the supplied reviewer and attestation in
HUMAN_REVIEW.txt. The generated contact sheets remain in comparison/.

Conclusion
----------
The current exact-or-better classifier passes all adversarial boundary tests,
all 14 trace matrices remain exact, structured traces remain non-flat, and the
only admitted strict visual differences are fully explained current time-grid
and bounded time-text changes in cases 12 and 13. Firmware artifacts were
hash-checked before and after comparison and were not modified.
"""
    (stage / "SUPPLEMENTAL_ANALYSIS.txt").write_text(text)


def write_inventory(root: Path) -> None:
    inventory = root / "SHA256SUMS"
    inventory.unlink(missing_ok=True)
    paths: list[Path] = []
    for path in root.rglob("*"):
        reject(not path.is_symlink(), f"evidence contains a symlink: {path}")
        if path.is_file():
            paths.append(path)
        else:
            reject(path.is_dir(), f"evidence contains a non-regular node: {path}")
    relative_paths = sorted((path.relative_to(root) for path in paths), key=lambda path: str(path))
    inventory.write_text("".join(f"{sha256(root / relative)}  ./{relative.as_posix()}\n" for relative in relative_paths))
    listed = [line.split("  ", 1)[1] for line in inventory.read_text().splitlines()]
    actual = [f"./{path.as_posix()}" for path in relative_paths]
    reject(listed == actual and "./SHA256SUMS" not in listed, "SHA256SUMS inventory is not exhaustive/self-excluding")


def install_stage(stage: Path, output: Path) -> None:
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    backup: Path | None = None
    if output.exists():
        reject(output.is_dir() and not output.is_symlink(), f"output is not a regular directory: {output}")
        backup = Path(tempfile.mkdtemp(prefix=f".{output.name}.backup.", dir=output.parent))
        backup.rmdir()
        os.replace(output, backup)
    try:
        os.replace(stage, output)
    except BaseException:
        if backup is not None and not output.exists():
            os.replace(backup, output)
        raise
    if backup is not None:
        shutil.rmtree(backup)


def main() -> int:
    args = parse_args()
    baseline = BASELINES[args.mode]
    twin_root = args.twin_root.expanduser().resolve()
    reject(args.human_review == "PASS", "human contact-sheet review did not pass")
    reviewer = safe_text(args.human_reviewer, "human reviewer", 2)
    attestation = safe_text(args.human_review_attestation, "human review attestation", 20)
    candidate_release = safe_text(args.candidate_release, "candidate release", 2)
    args.candidate_release = candidate_release

    candidate_hashes = {
        "bin": validate_expected_hash(args.candidate_bin_sha256, "candidate BIN hash"),
        "elf": validate_expected_hash(args.candidate_elf_sha256, "candidate ELF hash"),
        "symbols": validate_expected_hash(args.candidate_symbols_sha256, "candidate symbol hash"),
    }
    artifacts = {
        "reference_bin": validate_hashed_file(args.reference_bin, baseline["bin"], "reference BIN"),
        "reference_elf": validate_hashed_file(args.reference_elf, baseline["elf"], "reference ELF"),
        "reference_symbols": validate_hashed_file(args.reference_symbols, baseline["symbols"], "reference symbols"),
        "candidate_bin": validate_hashed_file(args.candidate_bin, candidate_hashes["bin"], "candidate BIN"),
        "candidate_elf": validate_hashed_file(args.candidate_elf, candidate_hashes["elf"], "candidate ELF"),
        "candidate_symbols": validate_hashed_file(args.candidate_symbols, candidate_hashes["symbols"], "candidate symbols"),
    }
    reference_capture = args.reference_capture.expanduser().resolve()
    candidate_capture = args.candidate_capture.expanduser().resolve()
    reference_counts, reference_symbol_binding, reference_twin_identity = validate_capture(
        reference_capture,
        "reference",
        {"bin": baseline["bin"], "elf": baseline["elf"], "symbols": baseline["symbols"]},
        artifacts["reference_symbols"],
        twin_root,
        allow_lab_default_symbols=args.mode == "lab",
    )
    candidate_counts, candidate_symbol_binding, candidate_twin_identity = validate_capture(
        candidate_capture,
        "candidate",
        {"bin": candidate_hashes["bin"], "elf": candidate_hashes["elf"], "symbols": candidate_hashes["symbols"]},
        artifacts["candidate_symbols"],
        twin_root,
    )
    reject(
        reference_twin_identity == candidate_twin_identity,
        "reference and candidate captures used different twin identities",
    )
    reference_capture_hash = capture_inventory_hash(reference_capture)
    candidate_capture_hash = capture_inventory_hash(candidate_capture)

    historical_bytes = git_output("show", f"{HISTORICAL_COMMIT}:tools/compare-selftest-visuals.py")
    historical_blob = git_output("rev-parse", f"{HISTORICAL_COMMIT}:tools/compare-selftest-visuals.py").decode().strip()
    reject(historical_blob == HISTORICAL_BLOB, f"historical comparator blob changed: {historical_blob}")
    reject(hashlib.sha256(historical_bytes).hexdigest() == HISTORICAL_SHA256, "historical comparator SHA-256 changed")
    current_bytes = COMPARATOR.read_bytes()
    adversarial_bytes = ADVERSARIAL_TEST.read_bytes()
    current_sha256 = hashlib.sha256(current_bytes).hexdigest()
    adversarial_sha256 = hashlib.sha256(adversarial_bytes).hexdigest()
    current_blob = git_output("hash-object", "--stdin", input_bytes=current_bytes).decode().strip()
    adversarial_blob = git_output("hash-object", "--stdin", input_bytes=adversarial_bytes).decode().strip()
    tracked_current_blob = git_output(
        "rev-parse", "HEAD:tools/compare-selftest-visuals.py"
    ).decode().strip()
    tracked_adversarial_blob = git_output(
        "rev-parse", "HEAD:tools/test-selftest-visual-comparator.py"
    ).decode().strip()
    reject(current_blob == tracked_current_blob, "current comparator has uncommitted modifications")
    reject(
        adversarial_blob == tracked_adversarial_blob,
        "current comparator adversarial test has uncommitted modifications",
    )
    current_commit = git_output(
        "log", "-1", "--format=%H", "--", "tools/compare-selftest-visuals.py"
    ).decode().strip()

    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{output.name}.finalize.", dir=output.parent))
    installed = False
    try:
        copy_capture(reference_capture, stage / "reference")
        copy_capture(candidate_capture, stage / "candidate")
        reject(
            capture_inventory_hash(stage / "reference") == reference_capture_hash,
            "reference capture changed while it was copied",
        )
        reject(
            capture_inventory_hash(stage / "candidate") == candidate_capture_hash,
            "candidate capture changed while it was copied",
        )
        shutil.copyfile(artifacts["reference_symbols"], stage / "reference" / artifacts["reference_symbols"].name)
        shutil.copyfile(artifacts["candidate_symbols"], stage / "candidate" / artifacts["candidate_symbols"].name)
        reject(
            sha256(stage / "reference" / artifacts["reference_symbols"].name)
            == baseline["symbols"],
            "reference symbol profile changed while it was copied",
        )
        reject(
            sha256(stage / "candidate" / artifacts["candidate_symbols"].name)
            == candidate_hashes["symbols"],
            "candidate symbol profile changed while it was copied",
        )
        write_human_review(stage, reviewer, attestation)

        scripts = stage / ".finalizer-scripts"
        scripts.mkdir()
        historical_script = scripts / "historical-compare-selftest-visuals.py"
        current_script = scripts / "compare-selftest-visuals.py"
        adversarial_script = scripts / "test-selftest-visual-comparator.py"
        historical_script.write_bytes(historical_bytes)
        current_script.write_bytes(current_bytes)
        adversarial_script.write_bytes(adversarial_bytes)

        comparator_artifacts = {
            "reference_bin": artifacts["reference_bin"],
            "reference_elf": artifacts["reference_elf"],
            "candidate_bin": artifacts["candidate_bin"],
            "candidate_elf": artifacts["candidate_elf"],
        }
        historical_process = run_comparator(
            historical_script,
            stage / "reference",
            stage / "candidate",
            stage / "comparison-original-rejected",
            comparator_artifacts,
        )
        reject(historical_process.returncode in (0, 1), f"historical comparator failed with status {historical_process.returncode}")
        current_process = run_comparator(
            current_script,
            stage / "reference",
            stage / "candidate",
            stage / "comparison",
            comparator_artifacts,
        )
        reject(current_process.returncode == 0, f"current comparator rejected the evidence with status {current_process.returncode}")

        adversarial_environment = os.environ.copy()
        adversarial_environment["PYTHONHASHSEED"] = "0"
        adversarial = subprocess.run(
            [sys.executable, str(adversarial_script)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env=adversarial_environment,
        )
        (stage / "COMPARATOR_ADVERSARIAL.txt").write_text(
            f"exit_status={adversarial.returncode}\npythonhashseed=0\n"
            f"stdout:\n{adversarial.stdout.rstrip()}\nstderr:\n{adversarial.stderr.rstrip()}\n"
        )
        reject(adversarial.returncode == 0 and "selftest_visual_comparator_adversarial=passed" in adversarial.stdout, "current comparator adversarial suite failed")

        expected_report_artifacts = {
            "reference_bin": baseline["bin"],
            "reference_elf": baseline["elf"],
            "candidate_bin": candidate_hashes["bin"],
            "candidate_elf": candidate_hashes["elf"],
        }
        historical_report = validate_historical_report(
            stage / "comparison-original-rejected/report.json",
            expected_report_artifacts,
            require_rejection=args.mode == "official-c979",
        )
        current_report = validate_current_report(
            stage / "comparison/report.json", stage, expected_report_artifacts
        )
        reject(sha256(artifacts["candidate_bin"]) == candidate_hashes["bin"], "candidate BIN changed during comparison")
        reject(sha256(artifacts["candidate_elf"]) == candidate_hashes["elf"], "candidate ELF changed during comparison")
        reject(sha256(artifacts["candidate_symbols"]) == candidate_hashes["symbols"], "candidate symbols changed during comparison")
        validate_twin_identity(twin_root, reference_twin_identity)

        shutil.rmtree(scripts)
        write_summary(
            stage,
            args,
            baseline,
            candidate_hashes,
            reference_counts,
            candidate_counts,
            reference_symbol_binding,
            candidate_symbol_binding,
            current_report,
            historical_report,
        )
        write_provenance(
            stage,
            args,
            baseline,
            artifacts,
            candidate_hashes,
            HISTORICAL_SHA256,
            current_blob,
            current_commit,
            current_sha256,
            adversarial_blob,
            adversarial_sha256,
            reference_capture,
            candidate_capture,
            reference_capture_hash,
            candidate_capture_hash,
            reference_symbol_binding,
            candidate_symbol_binding,
            twin_root,
            reference_twin_identity,
        )
        write_supplemental(stage, args, current_report, historical_report)
        write_inventory(stage)
        install_stage(stage, output)
        installed = True
    finally:
        if not installed and stage.exists():
            shutil.rmtree(stage)

    print("selftest_visual_evidence_finalized=PASS")
    print(f"mode={args.mode}")
    print(f"output={output}")
    print(f"candidate_bin_sha256={candidate_hashes['bin']}")
    print("hardware_qualified=false")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except FinalizeError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
