#!/usr/bin/env python3
"""Hardware-free checks for physical spur-persistence analysis."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("analyze-physical-selftest-spur-persistence.py")
SPEC = importlib.util.spec_from_file_location("physical_spur_persistence", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def trace_with_peaks(
    persistent_index: int | None = None,
    persistent_level: float = -72.0,
    moving_index: int | None = None,
    moving_level: float = -65.0,
    primary_index: int = 225,
) -> list[float]:
    values = [-100.0] * MODULE.TRACE_POINTS
    values[primary_index] = -30.0
    if persistent_index is not None:
        values[persistent_index] = persistent_level
    if moving_index is not None:
        values[moving_index] = moving_level
    return values


def memory_captures(traces: list[list[float]], case: int = 3) -> list[dict[str, object]]:
    frequencies = [29_500_000 + index * 2_000 for index in range(MODULE.TRACE_POINTS)]
    captures: list[dict[str, object]] = []
    for ordinal, trace in enumerate(traces, 1):
        captures.append({
            "path": f"/capture-{ordinal}",
            "variant": f"variant-repeat-{ordinal}",
            "observations": {
                case: {
                    "frequencies": frequencies,
                    "actual": trace,
                    "started_utc": f"2026-01-01T00:0{ordinal}:00+00:00",
                    "trace_sha256": f"trace-{ordinal}",
                }
            },
        })
    return captures


def write_checksum_inventory(root: Path) -> None:
    paths = sorted(
        path for path in root.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS"
    )
    (root / "SHA256SUMS").write_text(
        "".join(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  "
            f"{path.relative_to(root)}\n"
            for path in paths
        ),
        encoding="utf-8",
    )


def write_capture(
    root: Path,
    group: str,
    ordinal: int,
    persistent_index: int,
    moving_index: int,
) -> None:
    root.mkdir(parents=True)
    if group == "reference":
        variant = "official-c979" if ordinal == 1 else f"official-c979-spur-repeat{ordinal}"
        version = "tinySA4_v1.4-224-gc979386"
        serial_number = "400"
    else:
        variant = "rc5" if ordinal == 1 else f"rc5-spur-repeat{ordinal}"
        version = "tinySA4_v0.4-chibios21-rc5"
        serial_number = "706"
    started = datetime(
        2026, 1, 1, 0 if group == "reference" else 2, (ordinal - 1) * 20,
        tzinfo=timezone.utc,
    )
    for name in MODULE.REQUIRED_RUN_FILES:
        if name.startswith("device-version-"):
            payload = (
                f"version\r\n{version}\r\n"
                "HW Version:V0.5.4 max2871\r\nch> "
            )
        else:
            payload = f"synthetic {name}\n"
        (root / name).write_text(payload, encoding="utf-8")

    config_commands = [
        "color",
        *(f"correction {table}" for table in MODULE.COMPARATOR.CAPTURE.CORRECTION_TABLES),
    ]
    config_hashes: dict[str, str] = {}
    (root / "persisted-config").mkdir()
    for command in config_commands:
        if command == "color":
            config = b"color\r\n21: 0x00FF00\r\nch> "
        else:
            config = f"{command}\r\nsynthetic stable payload\r\nch> ".encode("ascii")
        config_hashes[command] = hashlib.sha256(config).hexdigest()
        slug = MODULE.COMPARATOR.CAPTURE.command_slug(command)
        (root / f"persisted-config/before-{slug}.txt").write_bytes(config)
        (root / f"persisted-config/after-{slug}.txt").write_bytes(config)

    records: list[dict[str, object]] = []
    for case in MODULE.ELIGIBLE_CASES:
        frequencies = [case * 10_000_000 + index * 1_000 for index in range(MODULE.TRACE_POINTS)]
        trace = trace_with_peaks(
            persistent_index=persistent_index,
            moving_index=moving_index,
        )
        payload = struct.pack(
            f"<{MODULE.TRACE_PLANES * MODULE.TRACE_POINTS}f",
            *(trace * MODULE.TRACE_PLANES),
        )
        trace_hash = hashlib.sha256(payload).hexdigest()
        (root / f"case-{case:02d}-measured.f32le").write_bytes(payload)
        shell = root / f"case-{case:02d}-shell"
        shell.mkdir()
        (shell / "frequencies.txt").write_bytes(
            b"frequencies\r\n"
            + b"".join(f"{value}\r\n".encode("ascii") for value in frequencies)
            + b"ch> "
        )
        (shell / "trace-1-value.txt").write_bytes(
            b"trace 1 value\r\n"
            + b"".join(
                f"trace 1 value {index} {value:.2f}\r\n".encode("ascii")
                for index, value in enumerate(trace)
            )
            + b"ch> "
        )
        frame = bytearray(MODULE.COMPARATOR.FRAME_BYTES)
        on, _ = MODULE.COMPARATOR.literal_pixels(
            f"Test {case}: Pass",
            MODULE.COMPARATOR.PASS_LITERAL_X,
            MODULE.COMPARATOR.PASS_LITERAL_Y0
            + (case - 1) * MODULE.COMPARATOR.PASS_LITERAL_SPACING,
        )
        for x, y in on:
            offset = 2 * (y * 480 + x)
            frame[offset:offset + 2] = b"\x07\xe0"
        final_frame = bytes(frame)
        frame_hash = hashlib.sha256(final_frame).hexdigest()
        (root / f"case-{case:02d}.rgb565be").write_bytes(final_frame)
        (root / f"case-{case:02d}-settle-01-a.rgb565be").write_bytes(final_frame)
        (root / f"case-{case:02d}-settle-01-b.rgb565be").write_bytes(final_frame)
        comparator_frame = MODULE.COMPARATOR.CAPTURE.rgb565be_to_rgb565le(final_frame)
        (root / f"case-{case:02d}.rgb565").write_bytes(comparator_frame)
        case_started = started + timedelta(seconds=case * 10)
        records.append({
            "zero_based_case": case - 1,
            "selftest_argument": case,
            "started_utc": case_started.isoformat(),
            "finished_utc": (case_started + timedelta(seconds=5)).isoformat(),
            "result": "PASS",
            "display": {
                "bytes": MODULE.COMPARATOR.FRAME_BYTES,
                "sha256": frame_hash,
                "settle_attempt": 1,
                "pair_interval_seconds": 0.75,
                "nonblack_pixels": len(on),
                "unique_rgb565_colors": 2,
            },
            "comparator_rgb565_sha256": hashlib.sha256(comparator_frame).hexdigest(),
            "shell_evidence": {
                "trace_dump_bytes": len(payload),
                "trace_dump_sha256": trace_hash,
            },
        })

    metadata = {
        "schema": MODULE.CAPTURE_SCHEMA,
        "started_utc": started.isoformat(),
        "finished_utc": (started + timedelta(minutes=10)).isoformat(),
        "result": "PASS",
        "variant": variant,
        "expected_version": version,
        "zero_based_cases": [case - 1 for case in MODULE.ELIGIBLE_CASES],
        "arguments": {},
        "port_history": [],
        "usb_identity": {
            "vid": 0x0483,
            "pid": 0x5740,
            "serial_number": serial_number,
            "location": "0-1",
        },
        "persisted_config_integrity": {
            "pass": True,
            "commands": config_commands,
            "mismatches": [],
            "before_sha256": config_hashes,
            "after_sha256": config_hashes,
        },
        "cases": records,
    }
    (root / "run.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    write_checksum_inventory(root)


class SpurPersistenceTest(unittest.TestCase):
    def test_persistent_peak_is_frequency_coherent(self) -> None:
        captures = memory_captures([
            trace_with_peaks(persistent_index=70),
            trace_with_peaks(persistent_index=72),
            trace_with_peaks(persistent_index=71),
        ])
        result = MODULE.analyze_group_case(captures, 3)
        self.assertEqual(result["classification"], "PERSISTENT_FREQUENCY_COHERENT")
        self.assertEqual(result["persistent_cluster_count"], 1)
        cluster = result["persistent_clusters"][0]
        self.assertEqual(cluster["center_index"], 71)
        self.assertEqual(cluster["frequency_span_bins"], 2)
        self.assertGreaterEqual(
            cluster["minimum_local_prominence_db"],
            MODULE.MINIMUM_LOCAL_PROMINENCE_DB,
        )
        self.assertFalse(result["release_gate"])

    def test_moving_maxima_are_stochastic_or_nonpersistent(self) -> None:
        captures = memory_captures([
            trace_with_peaks(moving_index=40),
            trace_with_peaks(moving_index=140),
            trace_with_peaks(moving_index=390),
        ])
        result = MODULE.analyze_group_case(captures, 3)
        self.assertEqual(result["classification"], "STOCHASTIC_OR_NONPERSISTENT")
        self.assertEqual(result["persistent_cluster_count"], 0)
        self.assertEqual(
            result["strongest_secondary_coherence"]["classification"],
            "STOCHASTIC_OR_NONPERSISTENT",
        )

    def test_lower_persistent_spur_survives_moving_stronger_maxima(self) -> None:
        captures = memory_captures([
            trace_with_peaks(persistent_index=90, moving_index=40),
            trace_with_peaks(persistent_index=91, moving_index=150),
            trace_with_peaks(persistent_index=89, moving_index=390),
        ])
        result = MODULE.analyze_group_case(captures, 3)
        self.assertEqual(
            result["strongest_secondary_coherence"]["classification"],
            "STOCHASTIC_OR_NONPERSISTENT",
        )
        self.assertEqual(result["classification"], "PERSISTENT_FREQUENCY_COHERENT")
        self.assertEqual(result["persistent_clusters"][0]["center_index"], 90)

    def test_flat_floor_has_no_significant_secondary_peak(self) -> None:
        captures = memory_captures([
            trace_with_peaks(),
            trace_with_peaks(),
            trace_with_peaks(),
        ])
        result = MODULE.analyze_group_case(captures, 3)
        self.assertEqual(result["classification"], "NO_SIGNIFICANT_SECONDARY_PEAK")
        self.assertEqual(result["significant_peak_counts"], [0, 0, 0])

    def test_low_prominence_coherence_is_not_called_a_spur(self) -> None:
        traces = []
        for index in (70, 71, 72):
            trace = trace_with_peaks()
            trace[index] = -98.0
            traces.append(trace)
        result = MODULE.analyze_group_case(memory_captures(traces), 3)
        self.assertEqual(result["classification"], "NO_SIGNIFICANT_SECONDARY_PEAK")
        self.assertEqual(
            result["strongest_secondary_coherence"]["classification"],
            "FREQUENCY_COHERENT_LOW_PROMINENCE",
        )

    def test_robust_noise_threshold_rejects_excursions_below_six_mad(self) -> None:
        frequencies = [29_500_000 + index * 2_000 for index in range(MODULE.TRACE_POINTS)]
        trace = trace_with_peaks()
        peak_indices = list(range(8, 440, 16))
        for ordinal, index in enumerate(peak_indices):
            trace[index] = -100.0 + (2.0, 3.0, 4.0)[ordinal % 3]
        trace[24] = -92.0
        trace[40] = -85.0
        secondary = MODULE.COMPARATOR.secondary_response_metrics(
            trace, frequencies, guard_bins=MODULE.MAIN_GUARD_BINS
        )
        detection = MODULE.detect_significant_peaks(trace, frequencies, secondary)
        self.assertTrue(detection["adaptive_estimator_used"])
        self.assertGreater(detection["effective_threshold_db"], 8.0)
        detected_indices = {
            peak["index"] for peak in detection["significant_peaks"]
        }
        self.assertNotIn(24, detected_indices)
        self.assertIn(40, detected_indices)

    def test_unstable_primary_limits_interpretation(self) -> None:
        captures = memory_captures([
            trace_with_peaks(persistent_index=70, primary_index=200),
            trace_with_peaks(persistent_index=70, primary_index=225),
            trace_with_peaks(persistent_index=70, primary_index=250),
        ])
        result = MODULE.analyze_group_case(captures, 3)
        self.assertEqual(result["classification"], "PRIMARY_UNSTABLE_ANALYSIS_LIMITED")
        self.assertFalse(result["primary_coherence"]["coherent"])

    def test_candidate_only_cluster_remains_diagnostic(self) -> None:
        reference = MODULE.analyze_group_case(memory_captures([
            trace_with_peaks(), trace_with_peaks(), trace_with_peaks(),
        ]), 3)
        candidate = MODULE.analyze_group_case(memory_captures([
            trace_with_peaks(persistent_index=80),
            trace_with_peaks(persistent_index=81),
            trace_with_peaks(persistent_index=79),
        ]), 3)
        comparison = MODULE.compare_persistent_clusters(reference, candidate)
        self.assertFalse(comparison["release_gate"])
        self.assertEqual(len(comparison["candidate_only_persistent_clusters"]), 1)
        self.assertIn("not automatic regressions", comparison["interpretation"])

    def test_complete_six_capture_report_is_non_gating_and_checksums_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            references: list[Path] = []
            candidates: list[Path] = []
            for ordinal, (persistent, moving) in enumerate(
                zip((70, 71, 69), (40, 140, 390)), 1
            ):
                reference = root / f"reference-{ordinal}"
                candidate = root / f"candidate-{ordinal}"
                write_capture(reference, "reference", ordinal, persistent, moving)
                write_capture(candidate, "candidate", ordinal, persistent + 1, moving)
                references.append(reference)
                candidates.append(candidate)
            output = root / "report"
            report = MODULE.analyze(
                references, candidates, output, "official", "rc5"
            )
            self.assertEqual(report["result"], "DIAGNOSTIC_COMPLETE")
            self.assertFalse(report["release_gate"])
            self.assertEqual(len(report["cases"]), len(MODULE.ELIGIBLE_CASES))
            self.assertTrue((output / "report.json").is_file())
            self.assertTrue((output / "report.md").is_file())
            inventory = (output / "SHA256SUMS").read_text(encoding="utf-8")
            self.assertIn("report.json", inventory)
            self.assertIn("report.md", inventory)
            markdown = (output / "report.md").read_text(encoding="utf-8")
            self.assertIn("DIAGNOSTIC COMPLETE (NON-GATING)", markdown)
            self.assertIn("Harmonic attribution", markdown)

    def test_capture_checksum_tampering_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "capture"
            write_capture(root, "reference", 1, 70, 40)
            with (root / "case-03-measured.f32le").open("ab") as target:
                target.write(b"tamper")
            with self.assertRaisesRegex(ValueError, "checksum inventory is invalid"):
                MODULE.load_capture(root)

    def test_capture_recomputes_persisted_config_equality(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "capture"
            write_capture(root, "reference", 1, 70, 40)
            changed = b"color\r\nchanged payload\r\nch> "
            path = root / "persisted-config/after-color.txt"
            path.write_bytes(changed)
            run_path = root / "run.json"
            metadata = json.loads(run_path.read_text(encoding="utf-8"))
            metadata["persisted_config_integrity"]["after_sha256"]["color"] = (
                hashlib.sha256(changed).hexdigest()
            )
            run_path.write_text(
                json.dumps(metadata, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            write_checksum_inventory(root)
            with self.assertRaisesRegex(ValueError, "config changed despite PASS"):
                MODULE.load_capture(root)

    def test_capture_requires_stable_exact_green_factory_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "capture"
            write_capture(root, "reference", 1, 70, 40)
            blank = bytes(MODULE.COMPARATOR.FRAME_BYTES)
            for name in (
                "case-03.rgb565be",
                "case-03-settle-01-a.rgb565be",
                "case-03-settle-01-b.rgb565be",
            ):
                (root / name).write_bytes(blank)
            comparator_frame = MODULE.COMPARATOR.CAPTURE.rgb565be_to_rgb565le(blank)
            (root / "case-03.rgb565").write_bytes(comparator_frame)
            run_path = root / "run.json"
            metadata = json.loads(run_path.read_text(encoding="utf-8"))
            record = next(
                item for item in metadata["cases"]
                if item["selftest_argument"] == 3
            )
            record["display"]["sha256"] = hashlib.sha256(blank).hexdigest()
            record["comparator_rgb565_sha256"] = hashlib.sha256(
                comparator_frame
            ).hexdigest()
            run_path.write_text(
                json.dumps(metadata, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            write_checksum_inventory(root)
            with self.assertRaisesRegex(ValueError, "exact green factory PASS"):
                MODULE.load_capture(root)

    def test_duplicate_acquisition_timestamps_are_not_independent(self) -> None:
        started = datetime(2026, 1, 1, tzinfo=timezone.utc)
        raw_starts = (
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:00:00+00:00",
            "2025-12-31T16:00:00-08:00",
        )
        captures = [
            {
                "path": f"/capture-{ordinal}",
                "expected_version": "same",
                "started_utc": raw_starts[ordinal],
                "_started_dt": started,
                "_finished_dt": started + timedelta(minutes=1),
                "usb_identity": {
                    "vid": 1, "pid": 2, "serial_number": "3", "location": "0-1"
                },
                "observations": {
                    case: {"started_utc": f"same-{case}", "_started_dt": started}
                    for case in MODULE.ELIGIBLE_CASES
                },
            }
            for ordinal in range(3)
        ]
        with self.assertRaisesRegex(ValueError, "distinct acquisition starts"):
            MODULE.validate_group(captures, "reference")

    def test_group_rejects_overlapping_capture_intervals(self) -> None:
        captures: list[dict[str, object]] = []
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for ordinal in range(3):
            started = base + timedelta(minutes=ordinal * 5)
            captures.append({
                "path": f"/capture-{ordinal}",
                "expected_version": "same",
                "started_utc": started.isoformat(),
                "_started_dt": started,
                "_finished_dt": started + timedelta(minutes=10),
                "usb_identity": {
                    "vid": 1, "pid": 2, "serial_number": "3", "location": "0-1"
                },
                "observations": {
                    case: {
                        "started_utc": started.isoformat(),
                        "_started_dt": started + timedelta(seconds=case),
                    }
                    for case in MODULE.ELIGIBLE_CASES
                },
            })
        with self.assertRaisesRegex(ValueError, "intervals overlap"):
            MODULE.validate_group(captures, "reference")

    def test_group_rejects_usb_location_drift(self) -> None:
        captures = [
            {
                "path": f"/capture-{ordinal}",
                "expected_version": "same",
                "started_utc": f"2026-01-01T00:0{ordinal}:00+00:00",
                "_started_dt": datetime(
                    2026, 1, 1, 0, ordinal * 2, tzinfo=timezone.utc
                ),
                "_finished_dt": datetime(
                    2026, 1, 1, 0, ordinal * 2 + 1, tzinfo=timezone.utc
                ),
                "usb_identity": {
                    "vid": 0x0483,
                    "pid": 0x5740,
                    "serial_number": "400",
                    "location": f"0-{ordinal}",
                },
                "observations": {
                    case: {
                        "started_utc": f"capture-{ordinal}-case-{case}",
                        "_started_dt": datetime(
                            2026, 1, 1, 0, ordinal * 2, case,
                            tzinfo=timezone.utc,
                        ),
                    }
                    for case in MODULE.ELIGIBLE_CASES
                },
            }
            for ordinal in range(1, 4)
        ]
        with self.assertRaisesRegex(ValueError, "different USB identities"):
            MODULE.validate_group(captures, "reference")

    def test_analysis_rejects_different_physical_usb_location(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            references: list[Path] = []
            candidates: list[Path] = []
            for ordinal in range(1, 4):
                reference = root / f"reference-{ordinal}"
                candidate = root / f"candidate-{ordinal}"
                write_capture(reference, "reference", ordinal, 70, 40 + ordinal)
                write_capture(candidate, "candidate", ordinal, 70, 40 + ordinal)
                metadata_path = candidate / "run.json"
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                metadata["usb_identity"]["location"] = "0-2"
                metadata_path.write_text(
                    json.dumps(metadata, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                write_checksum_inventory(candidate)
                references.append(reference)
                candidates.append(candidate)
            with self.assertRaisesRegex(ValueError, "same physical test path"):
                MODULE.analyze(
                    references, candidates, root / "output", "official", "rc5"
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
