#!/usr/bin/env python3
"""Hardware-free adversarial tests for package-physical-qualification-bundle.py."""

from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import importlib.util
import io
import json
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).with_name("package-physical-qualification-bundle.py")
SPEC = importlib.util.spec_from_file_location("physical_bundle", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
bundle = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = bundle
SPEC.loader.exec_module(bundle)


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def payload(label: str) -> bytes:
    return (label + "\n").encode("utf-8")


def fake_digest(label: str) -> str:
    return digest(payload(label))


def config_integrity() -> dict[str, Any]:
    values = {command: fake_digest(f"config:{command}") for command in bundle.CONFIG_COMMANDS}
    return {
        "before_sha256": values,
        "after_sha256": dict(values),
        "commands": sorted(bundle.CONFIG_COMMANDS),
        "mismatches": [],
        "pass": True,
    }


RESET_TRANSPORT = b"transport ended after reset: SerialException: Device not configured\n"


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_inventory(root: Path) -> str:
    inventory = root / "SHA256SUMS"
    inventory.unlink(missing_ok=True)
    files = sorted(path for path in root.rglob("*") if path.is_file())
    value = "".join(f"{digest(path.read_bytes())}  {path.relative_to(root).as_posix()}\n" for path in files)
    inventory.write_text(value, encoding="utf-8")
    return digest(value.encode("utf-8"))


class SyntheticRepository:
    def __init__(self, root: Path) -> None:
        self.root = root
        bundle.TOOLING_PATHS = ("tooling/capture.py", "tooling/comparator.py", "tooling/font.c")
        bundle.RELEASE_INPUT_BLOCKERS = ()
        for tooling_path in bundle.TOOLING_PATHS:
            path = root / tooling_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload(tooling_path))
        self.source_path = "sealed/rc5"
        self.source = root / self.source_path
        self.source.mkdir(parents=True)
        self.candidate = self.firmware_image(bundle.EXPECTED_VERSION, "+ ZS407", 12_288)
        self.rollback = self.firmware_image(bundle.EXPECTED_ROLLBACK_VERSION, "+ ZS407", 11_264)

        bundle.EXPECTED_CANDIDATE_SIZE = len(self.candidate)
        bundle.EXPECTED_CANDIDATE_SHA256 = digest(self.candidate)
        bundle.EXPECTED_ROLLBACK_SIZE = len(self.rollback)
        bundle.EXPECTED_ROLLBACK_SHA256 = digest(self.rollback)
        self.dfu_util = b"synthetic admitted dfu-util\n" + b"D" * (
            bundle.EXPECTED_DFU_UTIL_SIZE - len(b"synthetic admitted dfu-util\n")
        )
        bundle.EXPECTED_DFU_UTIL_SHA256 = digest(self.dfu_util)

        (self.source / bundle.EXPECTED_CANDIDATE_NAME).write_bytes(self.candidate)
        (self.source / bundle.EXPECTED_ROLLBACK_NAME).write_bytes(self.rollback)
        self.write_source_metadata()
        self.reseal_source()
        self.evidence_objects: dict[str, dict[str, Any]] = {}
        self.create_evidence()

    @staticmethod
    def firmware_image(version: str, target: str, size: int) -> bytes:
        value = bytearray(b"\xff" * size)
        struct.pack_into("<II", value, 0, 0x2000_0400, 0x0800_0009)
        identity = f"Version: {version}\x00{version}\x00{target}\x00".encode("ascii")
        value[128 : 128 + len(identity)] = identity
        return bytes(value)

    def write_source_metadata(self, *, commit: str | None = None, version: str | None = None) -> None:
        manifest = {
            "release_id": bundle.EXPECTED_RELEASE_ID,
            "version": version or bundle.EXPECTED_VERSION,
            "release_commit": commit or bundle.EXPECTED_RELEASE_COMMIT,
            "implementation_commit": bundle.EXPECTED_IMPLEMENTATION_COMMIT,
            "chibios_commit": bundle.EXPECTED_CHIBIOS_COMMIT,
            "binary_size": str(bundle.EXPECTED_CANDIDATE_SIZE),
            "binary_sha256": bundle.EXPECTED_CANDIDATE_SHA256,
            "f072_binary_sha256": "0" * 64,
            "official_rollback_commit": bundle.EXPECTED_ROLLBACK_COMMIT,
            "official_rollback_binary_size": str(bundle.EXPECTED_ROLLBACK_SIZE),
            "official_rollback_binary_sha256": bundle.EXPECTED_ROLLBACK_SHA256,
            "simulation_qualification": "SIMULATION_PASS_HARDWARE_PENDING",
            "hardware_qualified": "false",
            "hardware_flash_performed": "false",
            "automated_flash": "false",
        }
        qualification = {
            "release_id": bundle.EXPECTED_RELEASE_ID,
            "simulation_qualification": "SIMULATION_PASS_HARDWARE_PENDING",
            "hardware_qualified": "false",
            "hardware_flash_performed": "false",
            "result": "PASS",
            "candidate_binary_sha256": bundle.EXPECTED_CANDIDATE_SHA256,
            "simulation_package_seal": "PASS",
        }
        (self.source / "manifest.txt").write_text(
            "".join(f"{key}={value}\n" for key, value in manifest.items()), encoding="utf-8"
        )
        (self.source / "qualification.txt").write_text(
            "".join(f"{key}={value}\n" for key, value in qualification.items()), encoding="utf-8"
        )

    def reseal_source(self, *, trust_manifest: bool = True) -> None:
        manifest = (self.source / "manifest.txt").read_bytes()
        qualification = (self.source / "qualification.txt").read_bytes()
        if trust_manifest:
            bundle.EXPECTED_SOURCE_MANIFEST_SHA256 = digest(manifest)
            bundle.EXPECTED_SOURCE_QUALIFICATION_SHA256 = digest(qualification)
        bundle.EXPECTED_SOURCE_SEAL_SHA256 = write_inventory(self.source)

    @staticmethod
    def selftest(variant: str, version: str, start: str, serial: str) -> dict[str, Any]:
        cases = []
        for number in range(1, 15):
            prefix = f"{variant}:case:{number}"
            cases.append(
                {
                    "selftest_argument": number,
                    "zero_based_case": number - 1,
                    "result": "PASS",
                    "comparator_rgb565_sha256": fake_digest(f"{prefix}:rgb565"),
                    "png_sha256": fake_digest(f"{prefix}:png"),
                    "display": {
                        "bytes": 307_200,
                        "nonblack_pixels": 1_000 + number,
                        "unique_rgb565_colors": 8,
                        "sha256": fake_digest(f"{prefix}:rgb565be"),
                    },
                    "shell_evidence": {
                        "data_points": [450, 450, 450],
                        "frequency_points": 450,
                        "trace_dump_bytes": 7_200,
                        "trace_dump_sha256": fake_digest(f"{prefix}:measured"),
                        "trace_metrics": [
                            {"points": 450, "finite": 450, "range": float(index + 1)} for index in range(4)
                        ],
                    },
                }
            )
        return {
            "schema": "tinysa-physical-selftest-capture-v1",
            "variant": variant,
            "expected_version": version,
            "result": "PASS",
            "started_utc": start,
            "finished_utc": start + "-finished",
            "usb_identity": {"vid": 0x0483, "pid": 0x5740, "location": "0-1", "serial_number": serial},
            "zero_based_cases": list(range(14)),
            "cases": cases,
            "persisted_config_integrity": config_integrity(),
        }

    @staticmethod
    def negative(recovery: bool) -> dict[str, Any]:
        phase = "recovery" if recovery else "disconnected"
        literal = {
            "pass": True,
            "text": "Test 3: Pass" if recovery else "Test 3: Signal level Fail",
            "expected_rgb565": "0x07e0" if recovery else "0xfc10",
        }
        screen = {
            "pass": True,
            "gate": True,
            "literal_match": True,
            "method": "exact-font-mask-and-observed-palette-rgb565",
            "literals": [literal],
        }
        trace = {
            "pass": True,
            "threshold_dbm": -60.0,
            "actual_trace_maximum_dbm": -35.0 if recovery else -108.0,
        }
        prefix = f"negative:{phase}:case:3"
        case = {
            "selftest_argument": 3,
            "zero_based_case": 2,
            "result": "PASS",
            "comparator_rgb565_sha256": fake_digest(f"{prefix}:rgb565"),
            "png_sha256": fake_digest(f"{prefix}:png"),
            "display": {
                "bytes": 307_200,
                "nonblack_pixels": 1_200,
                "unique_rgb565_colors": 8,
                "sha256": fake_digest(f"{prefix}:rgb565be"),
            },
            "shell_evidence": {
                "data_points": [450, 450, 450],
                "frequency_points": 450,
                "trace_dump_bytes": 7_200,
                "trace_dump_sha256": fake_digest(f"{prefix}:measured"),
                "trace_metrics": [{"points": 450, "finite": 450} for _ in range(4)],
            },
            "screen_condition": screen,
            "trace_condition": trace,
        }
        return {
            "schema": "tinysa-physical-selftest-negative-v1",
            "variant": "rc5-cal-loopback-control",
            "expected_version": bundle.EXPECTED_VERSION,
            "result": "PASS",
            "phase": phase,
            "confirmation": "CAL-RF-LOOPBACK-RECONNECTED" if recovery else "CAL-RF-LOOPBACK-DISCONNECTED",
            "selftest_argument": 3,
            "started_utc": "2026-07-15T02:00:00Z" if recovery else "2026-07-15T01:00:00Z",
            "usb_identity": {"vid": 0x0483, "pid": 0x5740, "location": "0-1", "serial_number": "706"},
            "screen_condition": screen,
            "trace_condition": trace,
            "cases": [case],
            "persisted_config_integrity": config_integrity(),
        }

    @staticmethod
    def candidate_binding(flash_spec: Any | None = None) -> dict[str, Any]:
        candidate = {
            "sha256": bundle.EXPECTED_CANDIDATE_SHA256,
            "bytes": bundle.EXPECTED_CANDIDATE_SIZE,
            "local_hash_match": True,
        }
        if flash_spec is not None:
            candidate.update(
                {
                    "device_byte_binding": True,
                    "flash_evidence": {
                        "schema": bundle.EXPECTED_FLASH_SCHEMA,
                        "path": "/synthetic/flash-evidence",
                        "inventory_sha256": flash_spec.inventory_sha256,
                        "run_json_sha256": flash_spec.primary_sha256,
                        "candidate_sha256": bundle.EXPECTED_CANDIDATE_SHA256,
                        "dfu_location": bundle.EXPECTED_DFU_LOCATION,
                        "dfu_serial": bundle.EXPECTED_DFU_SERIAL,
                        "selected_alt": 0,
                        "normal_usb_identity": SyntheticRepository.usb_identity(),
                        "readback_performed": True,
                        "readback_sha256": bundle.EXPECTED_CANDIDATE_SHA256,
                        "exact_byte_match": True,
                    },
                }
            )
        return candidate

    @staticmethod
    def usb_identity() -> dict[str, Any]:
        return {"vid": 0x0483, "pid": 0x5740, "serial_number": "706", "location": "0-1"}

    @classmethod
    def usb_runtime(cls, tag: str = "usb", flash_spec: Any | None = None) -> dict[str, Any]:
        version_digest = fake_digest("device-version")
        identity = {
            "pass": True,
            "version": bundle.EXPECTED_VERSION,
            "version_response_sha256": version_digest,
            "usb_identity": cls.usb_identity(),
        }
        authentication = dict(identity)
        authentication["wire_reassembled_ascii"] = "version\\r"
        frames = [
            {
                "index": index,
                "bytes": 307_200,
                "nonblack_pixels": 1_000 + index,
                "unique_rgb565_colors": 8,
                "sha256": fake_digest(f"{tag}:frame:{index}"),
            }
            for index in range(1, 3)
        ]
        commands = ["frequencies", "trace", "trace 1 value", "data 2", "sweeptime", "status", "threads"]
        responses = {command: fake_digest(f"{tag}:runtime:{command}") for command in commands}
        return {
            "schema": "tinysa-physical-usb-runtime-v2" if flash_spec is not None else "tinysa-physical-usb-runtime-v1",
            "started_utc": "2026-07-15T04:00:00+00:00",
            "finished_utc": "2026-07-15T04:05:00+00:00",
            "result": "PASS",
            "candidate_binary": cls.candidate_binding(flash_spec),
            "authentication": authentication,
            "final_identity": identity,
            "frame_series": {"complete_frames": 2, "distinct_frame_hashes": 2, "total_bytes": 614_400},
            "frames": frames,
            "persisted_config_integrity": config_integrity(),
            "runtime_observations": {
                "acquisition_state": "Resumed",
                "frequency_points": 450,
                "frequency_start_hz": 0,
                "frequency_stop_hz": 900_000_000,
                "trace_1_metrics": {"points": 450, "finite": 450, "range": 42.0},
                "trace_1_interior_range_db": 41.0,
                "trace_1_robust_range_db": 35.0,
                "data_trace_maximum_delta_db": 0.001,
                "data_2_points": 450,
                "required_threads": ["main", "idle", "sweep", "shell"],
                "commands": commands,
                "response_sha256": responses,
            },
        }

    @classmethod
    def reset_retention(cls, flash_spec: Any) -> dict[str, Any]:
        retention = {
            "pass": True,
            "reset_sent_exactly_once": True,
            "same_frequency_grid": True,
            "same_info_response": True,
            "same_sweep_configuration": True,
            "same_usb_identity": True,
            "same_version_response": True,
            "sweep_performance_retained": True,
            "config_mismatches": [],
            "reset_attempted_exactly_once": True,
            "reset_wire_write_completed": True,
            "reset_transport_disconnect_observed": True,
        }
        config = {command: fake_digest(f"config:{command}") for command in bundle.CONFIG_COMMANDS}

        def observation(phase: str) -> dict[str, Any]:
            return {
                "usb_identity": cls.usb_identity(),
                "status": "Resumed",
                "frequency_points": 450,
                "frequency_start_hz": 0,
                "frequency_stop_hz": 900_000_000,
                "frequency_sha256": fake_digest("reset:frequencies"),
                "info_sha256": fake_digest("reset:info"),
                "sweep_configuration_sha256": fake_digest("reset:sweep"),
                "version_sha256": fake_digest("device-version"),
                "frame": {
                    "bytes": 307_200,
                    "nonblack_pixels": 1_000,
                    "unique_rgb565_colors": 8,
                    "sha256": fake_digest(f"reset:{phase}:frame"),
                },
                "config_sha256": config,
            }

        return {
            "schema": "tinysa-physical-reset-retention-v2",
            "started_utc": "2026-07-15T05:00:00+00:00",
            "finished_utc": "2026-07-15T05:05:00+00:00",
            "result": "PASS",
            "arguments": {
                "expected_version": bundle.EXPECTED_VERSION,
                "expected_usb_serial": "706",
                "expected_usb_location": "0-1",
            },
            "candidate_binary": cls.candidate_binding(flash_spec),
            "retention": retention,
            "before": observation("before"),
            "after": observation("after"),
            "reset": {
                "sent_count": 1,
                "attempted_count": 1,
                "wire_hex": "72657365740d",
                "wire_write_completed": True,
                "transport_disconnect_observed": True,
                "response_sha256": digest(RESET_TRANSPORT),
                "attempted_utc": "2026-07-15T00:00:00Z",
                "transport_completed_utc": "2026-07-15T00:00:01Z",
            },
            "port_history": ["/dev/cu.usbmodem7061"],
        }

    @staticmethod
    def dfu_flash() -> dict[str, Any]:
        tool = "/synthetic/flash/dfu-util.snapshot"
        candidate = "/synthetic/flash/candidate.snapshot.bin"
        readback = "/synthetic/flash/candidate.readback.bin"
        alternates = [
            {
                "vid": bundle.EXPECTED_DFU_VID,
                "pid": bundle.EXPECTED_DFU_PID,
                "path": bundle.EXPECTED_DFU_LOCATION,
                "cfg": 1,
                "intf": 0,
                "alt": 0,
                "name": "@Internal Flash  /0x08000000/128*0002Kg",
                "serial": bundle.EXPECTED_DFU_SERIAL,
            },
            {
                "vid": bundle.EXPECTED_DFU_VID,
                "pid": bundle.EXPECTED_DFU_PID,
                "path": bundle.EXPECTED_DFU_LOCATION,
                "cfg": 1,
                "intf": 0,
                "alt": 1,
                "name": "@Option Bytes  /0x1FFFF800/01*016 e",
                "serial": bundle.EXPECTED_DFU_SERIAL,
            },
        ]
        return {
            "schema": bundle.EXPECTED_FLASH_SCHEMA,
            "started_utc": "2026-07-15T03:30:00+00:00",
            "finished_utc": "2026-07-15T03:35:00+00:00",
            "result": "PASS",
            "target": "tinySA Ultra+ ZS407 / STM32F303",
            "candidate": {
                "path": "/synthetic/source/candidate.bin",
                "bytes": bundle.EXPECTED_CANDIDATE_SIZE,
                "sha256": bundle.EXPECTED_CANDIDATE_SHA256,
                "staged_path": "candidate.snapshot.bin",
                "staged_sha256": bundle.EXPECTED_CANDIDATE_SHA256,
            },
            "dfu_tool": {
                "path": "/synthetic/bin/dfu-util",
                "sha256": bundle.EXPECTED_DFU_UTIL_SHA256,
                "bytes": bundle.EXPECTED_DFU_UTIL_SIZE,
                "expected_version": bundle.EXPECTED_DFU_UTIL_VERSION,
                "staged_path": "dfu-util.snapshot",
            },
            "preflight": {
                "pass": True,
                "vid": bundle.EXPECTED_DFU_VID,
                "pid": bundle.EXPECTED_DFU_PID,
                "path": bundle.EXPECTED_DFU_LOCATION,
                "serial": bundle.EXPECTED_DFU_SERIAL,
                "alternates": alternates,
                "selected_alt": 0,
                "rejected_alt": 1,
            },
            "download": {
                "attempt_count": 1,
                "selected_alt": 0,
                "started_utc": "2026-07-15T03:31:00+00:00",
                "finished_utc": "2026-07-15T03:32:00+00:00",
                "argv": [
                    tool, "-d", "0483:df11", "-p", bundle.EXPECTED_DFU_LOCATION,
                    "-S", bundle.EXPECTED_DFU_SERIAL, "-c", "1", "-i", "0",
                    "-a", "0", "-s", "0x08000000", "-D", candidate,
                ],
                "exit_code": 0,
                "success_markers": ["Download done.", "File downloaded successfully"],
                "pass": True,
                "retry_performed": False,
            },
            "readback": {
                "attempt_count": 1,
                "selected_alt": 0,
                "started_utc": "2026-07-15T03:33:00+00:00",
                "finished_utc": "2026-07-15T03:34:00+00:00",
                "argv": [
                    tool, "-d", "0483:df11", "-p", bundle.EXPECTED_DFU_LOCATION,
                    "-S", bundle.EXPECTED_DFU_SERIAL, "-c", "1", "-i", "0",
                    "-a", "0", "-s", f"0x08000000:{bundle.EXPECTED_CANDIDATE_SIZE}:leave",
                    "-U", readback,
                ],
                "leave_requested_after_upload": True,
                "exit_code": 0,
                "bytes": bundle.EXPECTED_CANDIDATE_SIZE,
                "sha256": bundle.EXPECTED_CANDIDATE_SHA256,
                "exact_byte_match": True,
                "pass": True,
                "retry_performed": False,
            },
            "normal_mode": {"pass": True, "device": "/dev/cu.synthetic", **SyntheticRepository.usb_identity()},
            "device_byte_binding": {
                "scope": "synthetic exact candidate range readback",
                "candidate_sha256": bundle.EXPECTED_CANDIDATE_SHA256,
                "readback_sha256": bundle.EXPECTED_CANDIDATE_SHA256,
                "readback_performed": True,
                "exact_byte_match": True,
            },
        }

    @staticmethod
    def manual_controls(post_controls: Any) -> dict[str, Any]:
        return {
            "schema": "tinysa-physical-manual-controls-attestation-v1",
            "result": "PASS",
            "candidate": {
                "binary_sha256": bundle.EXPECTED_CANDIDATE_SHA256,
                "version": bundle.EXPECTED_VERSION,
            },
            "operator_attestation": {
                "response": "Passed",
                "checks": [
                    "physical resistive touch opened the right-side menu from blank plot space",
                    "physical touch on blank plot space left of the menu closed it",
                    "physical jog press opened the menu",
                    "one clockwise detent moved the highlight",
                    "one counterclockwise detent moved the highlight",
                    "blank plot touch exited without selecting or saving a menu item",
                ],
            },
            "usb_identity": {"vid": "0x0483", "pid": "0x5740", "serial_number": "706", "location": "0-1"},
            "post_control_read_only_evidence": {
                "path": "../rc5-post-controls-readonly",
                "result": "PASS",
                "run_json_sha256": post_controls.primary_sha256,
                "sha256sums_sha256": post_controls.inventory_sha256,
            },
        }

    @staticmethod
    def put(root: Path, name: str, label: str) -> None:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload(label))

    def write_config_support(self, root: Path, prefix: str, *, persisted: bool = False) -> None:
        for command in bundle.CONFIG_COMMANDS:
            if persisted:
                name = f"persisted-config/{prefix}-{command.replace(' ', '-')}.txt"
            else:
                name = bundle.config_artifact_name(prefix, command)
            self.put(root, name, f"config:{command}")

    def write_case_support(self, root: Path, case: dict[str, Any], number: int, prefix: str) -> None:
        stem = f"case-{number:02d}"
        self.put(root, f"{stem}.rgb565be", f"{prefix}:rgb565be")
        self.put(root, f"{stem}.rgb565", f"{prefix}:rgb565")
        self.put(root, f"{stem}.png", f"{prefix}:png")
        self.put(root, f"{stem}-measured.f32le", f"{prefix}:measured")
        for name in (
            "data-0.txt",
            "data-1.txt",
            "data-2.txt",
            "frequencies.txt",
            "status.txt",
            "sweeptime.txt",
            "threads.txt",
            "trace-1-value.txt",
            "trace-2-value.txt",
            "trace-3-value.txt",
            "trace-4-value.txt",
            "trace.txt",
        ):
            self.put(root, f"{stem}-shell/{name}", f"{prefix}:shell:{name}")

    def write_support(self, root: Path, role: str, validator: str, value: dict[str, Any]) -> None:
        if validator in {"rc5_selftest", "official_selftest"}:
            variant = value["variant"]
            for number, case in enumerate(value["cases"], 1):
                self.write_case_support(root, case, number, f"{variant}:case:{number}")
            for phase in ("before", "after"):
                self.write_config_support(root, phase, persisted=True)
            for name in (
                "device-info-before.txt",
                "device-info-after.txt",
                "device-version-before.txt",
                "device-version-after.txt",
                "run.log",
                "run-transcript.md",
            ):
                self.put(root, name, f"{role}:{name}")
        elif validator in {"cal_disconnected", "cal_reconnected"}:
            phase = value["phase"]
            self.write_case_support(root, value["cases"][0], 3, f"negative:{phase}:case:3")
            for config_phase in ("before", "after"):
                self.write_config_support(root, config_phase, persisted=True)
            for name in (
                "device-info-before.txt",
                "device-info-after.txt",
                "device-version-before.txt",
                "device-version-after.txt",
                "run.log",
                "run-transcript.md",
            ):
                self.put(root, name, f"{role}:{name}")
        elif validator == "ab_report":
            for number in range(1, 15):
                self.put(root, f"case-{number:02d}-diff.png", f"{role}:case:{number}:diff")
            for name in ("contact-cases-01-07.png", "contact-cases-08-14.png", "report.md"):
                self.put(root, name, f"{role}:{name}")
            for name in value["implementation"]:
                self.put(root, f"implementation/{name}", f"ab:implementation:{name}")
            rc5 = self.evidence_objects["rc5-all-14-selftests"]
            official = self.evidence_objects["official-c979-all-14-selftests"]
            document = {
                "schema": "tinysa-physical-cold-boot-attestation-v1",
                "evidence_type": "operator-attested",
                "cal_rf_fixture": "CAL-RF-LOOPBACK-CONNECTED",
                "events": [
                    {
                        "role": "reference",
                        "variant": "official-c979",
                        "expected_version": bundle.EXPECTED_ROLLBACK_VERSION,
                        "capture_inventory_sha256": value["reference"]["checksums"]["sha256"],
                        "capture_started_utc": official["started_utc"],
                        "usb_location": "0-1",
                        "boot_mode": "normal",
                        "operator_confirmed": True,
                        "minimum_power_off_seconds": 5,
                    },
                    {
                        "role": "candidate",
                        "variant": "rc5",
                        "expected_version": bundle.EXPECTED_VERSION,
                        "capture_inventory_sha256": value["candidate"]["checksums"]["sha256"],
                        "capture_started_utc": rc5["started_utc"],
                        "usb_location": "0-1",
                        "boot_mode": "normal",
                        "operator_confirmed": True,
                        "minimum_power_off_seconds": 5,
                    },
                ],
            }
            attestation_path = root / "operator-attestation/cold-boot.json"
            attestation_path.parent.mkdir(parents=True, exist_ok=True)
            write_json(attestation_path, document)
        elif validator == "dfu_flash":
            (root / "candidate.snapshot.bin").write_bytes(self.candidate)
            (root / "candidate.readback.bin").write_bytes(self.candidate)
            (root / "dfu-util.snapshot").write_bytes(self.dfu_util)
            (root / "dfu-util-version.stdout.txt").write_text(
                bundle.EXPECTED_DFU_UTIL_VERSION + "\n", encoding="utf-8"
            )
            (root / "dfu-util-version.stderr.txt").write_bytes(b"")
            listing = (
                f'dfu-util 0.11\nFound DFU: [0483:df11] cfg=1, intf=0, path="{bundle.EXPECTED_DFU_LOCATION}", '
                f'alt=0, name="@Internal Flash  /0x08000000/128*0002Kg", serial="{bundle.EXPECTED_DFU_SERIAL}"\n'
                f'Found DFU: [0483:df11] cfg=1, intf=0, path="{bundle.EXPECTED_DFU_LOCATION}", '
                f'alt=1, name="@Option Bytes  /0x1FFFF800/01*016 e", serial="{bundle.EXPECTED_DFU_SERIAL}"\n'
            )
            (root / "dfu-util-list.stdout.txt").write_text(listing, encoding="utf-8")
            (root / "dfu-util-list.stderr.txt").write_bytes(b"")
            (root / "dfu-util-download.stdout.txt").write_text(
                "Download done.\nFile downloaded successfully\n", encoding="utf-8"
            )
            (root / "dfu-util-download.stderr.txt").write_bytes(b"")
            (root / "dfu-util-readback.stdout.txt").write_text("Upload done.\n", encoding="utf-8")
            (root / "dfu-util-readback.stderr.txt").write_bytes(b"")
        elif validator == "usb_runtime":
            self.put(root, "device-version-fragmented.txt", "device-version")
            self.put(root, "device-version-final.txt", "device-version")
            for frame in value["frames"]:
                self.put(root, f"frame-{frame['index']:02d}.rgb565be", f"{role}:frame:{frame['index']}")
            for phase in ("config-before", "config-after"):
                self.write_config_support(root, phase)
            for command in value["runtime_observations"]["commands"]:
                self.put(root, bundle.runtime_response_artifact(command), f"{role}:runtime:{command}")
            for name in ("run.log", "run-transcript.md"):
                self.put(root, name, f"{role}:{name}")
        elif validator == "reset_retention":
            (root / "reset-reset.txt").write_bytes(RESET_TRANSPORT)
            for phase in ("before", "after"):
                self.put(root, f"{phase}-frame.rgb565be", f"reset:{phase}:frame")
                self.put(root, f"{phase}-frequencies.txt", "reset:frequencies")
                self.put(root, f"{phase}-info.txt", "reset:info")
                self.put(root, f"{phase}-sweep.txt", "reset:sweep")
                self.put(root, f"{phase}-version.txt", "device-version")
                self.put(root, f"{phase}-connect.txt", f"reset:{phase}:connect")
                self.put(root, f"{phase}-status.txt", f"reset:{phase}:status")
                self.write_config_support(root, phase)
            for name in ("run.log", "run-transcript.md"):
                self.put(root, name, f"{role}:{name}")

    def add_evidence(self, role: str, schema: str, validator: str, primary: str, value: dict[str, Any]) -> Any:
        relative = f"evidence/{role}"
        root = self.root / relative
        root.mkdir(parents=True)
        write_json(root / primary, value)
        self.write_support(root, role, validator, value)
        primary_sha = digest((root / primary).read_bytes())
        inventory_sha = write_inventory(root)
        self.evidence_objects[role] = value
        return bundle.EvidenceSpec(role, relative, inventory_sha, primary, primary_sha, schema, validator)

    def create_evidence(self) -> None:
        specs: list[Any] = []
        rc5 = self.selftest("rc5", bundle.EXPECTED_VERSION, "2026-07-15T00:00:00Z", "706")
        rc5_spec = self.add_evidence(
            "rc5-all-14-selftests", "tinysa-physical-selftest-capture-v1", "rc5_selftest", "run.json", rc5
        )
        specs.append(rc5_spec)
        specs.append(
            self.add_evidence(
                "rc5-cal-disconnected-negative",
                "tinysa-physical-selftest-negative-v1",
                "cal_disconnected",
                "run.json",
                self.negative(False),
            )
        )
        specs.append(
            self.add_evidence(
                "rc5-cal-reconnected-recovery",
                "tinysa-physical-selftest-negative-v1",
                "cal_reconnected",
                "run.json",
                self.negative(True),
            )
        )
        official = self.selftest(
            "official-c979", bundle.EXPECTED_ROLLBACK_VERSION, "2026-07-15T03:00:00Z", "400"
        )
        official_spec = self.add_evidence(
            "official-c979-all-14-selftests",
            "tinysa-physical-selftest-capture-v1",
            "official_selftest",
            "run.json",
            official,
        )
        specs.append(official_spec)
        cold_boot_document = {
            "schema": "tinysa-physical-cold-boot-attestation-v1",
            "evidence_type": "operator-attested",
            "cal_rf_fixture": "CAL-RF-LOOPBACK-CONNECTED",
            "events": [
                {
                    "role": "reference",
                    "variant": "official-c979",
                    "expected_version": bundle.EXPECTED_ROLLBACK_VERSION,
                    "capture_inventory_sha256": official_spec.inventory_sha256,
                    "capture_started_utc": official["started_utc"],
                    "usb_location": "0-1",
                    "boot_mode": "normal",
                    "operator_confirmed": True,
                    "minimum_power_off_seconds": 5,
                },
                {
                    "role": "candidate",
                    "variant": "rc5",
                    "expected_version": bundle.EXPECTED_VERSION,
                    "capture_inventory_sha256": rc5_spec.inventory_sha256,
                    "capture_started_utc": rc5["started_utc"],
                    "usb_location": "0-1",
                    "boot_mode": "normal",
                    "operator_confirmed": True,
                    "minimum_power_off_seconds": 5,
                },
            ],
        }
        cold_boot_bytes = (json.dumps(cold_boot_document, indent=2, sort_keys=True) + "\n").encode("utf-8")
        implementation_names = (
            "compare-physical-selftest-captures.py",
            "capture-physical-selftests.py",
            "compare-selftest-visuals.py",
            "Font5x7.c",
        )
        ab = {
            "schema": "tinysa-physical-selftest-ab-v3",
            "pass": True,
            "qualification_eligible": True,
            "qualification_pass": True,
            "diagnostic_reasons": [],
            "implementation": {
                name: {
                    "path": f"implementation/{name}",
                    "sha256": fake_digest(f"ab:implementation:{name}"),
                }
                for name in implementation_names
            },
            "cold_boot_attestation": {
                "schema": "tinysa-physical-cold-boot-attestation-v1",
                "evidence_type": "operator-attested",
                "path": "operator-attestation/cold-boot.json",
                "sha256": digest(cold_boot_bytes),
                "limitation": "operator-attested",
            },
            "reference": {
                "variant": "official-c979",
                "expected_version": bundle.EXPECTED_ROLLBACK_VERSION,
                "path": "/captures/official",
                "checksums": {"pass": True, "sha256": official_spec.inventory_sha256},
            },
            "candidate": {
                "variant": "rc5",
                "expected_version": bundle.EXPECTED_VERSION,
                "path": "/captures/rc5",
                "checksums": {"pass": True, "sha256": rc5_spec.inventory_sha256},
            },
            "cases": [
                {
                    "case": number,
                    "pass": True,
                    "checks": [
                        {"name": name, "pass": True}
                        for name in sorted(
                            {
                                "reference-paired-readback",
                                "candidate-paired-readback",
                                "reference-shell-evidence",
                                "candidate-shell-evidence",
                                "reference-factory-pass-literal",
                                "candidate-factory-pass-literal",
                                "reference-frame-populated",
                                "candidate-frame-populated",
                                "reference-trace-matrix-populated",
                                "candidate-trace-matrix-populated",
                                "frequency-grid-parity",
                                "reference-visible-screen-trace",
                                "candidate-visible-screen-trace",
                                "trace-coverage",
                                "trace-not-degraded-to-flat",
                                "physical-visual-equivalence",
                                "measured-peak-level",
                                "measured-trace-range",
                                "measured-secondary-response-diagnostic",
                                "sweep-time-not-materially-slower",
                            }
                        )
                    ],
                }
                for number in range(1, 15)
            ],
        }
        specs.append(
            self.add_evidence(
                "official-c979-vs-rc5-ab",
                "tinysa-physical-selftest-ab-v3",
                "ab_report",
                "report.json",
                ab,
            )
        )
        flash_spec = self.add_evidence(
            "rc5-dfu-flash-readback",
            bundle.EXPECTED_FLASH_SCHEMA,
            "dfu_flash",
            "run.json",
            self.dfu_flash(),
        )
        specs.append(flash_spec)
        specs.append(
            self.add_evidence(
                "rc5-usb-runtime",
                "tinysa-physical-usb-runtime-v2",
                "usb_runtime",
                "run.json",
                self.usb_runtime("rc5-usb-runtime", flash_spec),
            )
        )
        specs.append(
            self.add_evidence(
                "rc5-reset-retention",
                "tinysa-physical-reset-retention-v2",
                "reset_retention",
                "run.json",
                self.reset_retention(flash_spec),
            )
        )
        post_controls = self.add_evidence(
            "rc5-post-controls-readonly",
            "tinysa-physical-usb-runtime-v1",
            "usb_runtime",
            "run.json",
            self.usb_runtime("rc5-post-controls-readonly"),
        )
        manual_controls = self.add_evidence(
            "rc5-manual-controls",
            "tinysa-physical-manual-controls-attestation-v1",
            "manual_controls",
            "attestation.json",
            self.manual_controls(post_controls),
        )
        specs.extend((manual_controls, post_controls))
        bundle.EVIDENCE_SPECS = tuple(specs)

    def replace_evidence(self, role: str, value: dict[str, Any], *, trust: bool) -> None:
        spec = next(item for item in bundle.EVIDENCE_SPECS if item.role == role)
        root = self.root / spec.default_path
        write_json(root / spec.primary_file, value)
        inventory_sha = write_inventory(root)
        self.evidence_objects[role] = value
        if trust:
            replacement = dataclasses.replace(
                spec,
                inventory_sha256=inventory_sha,
                primary_sha256=digest((root / spec.primary_file).read_bytes()),
            )
            bundle.EVIDENCE_SPECS = tuple(replacement if item.role == role else item for item in bundle.EVIDENCE_SPECS)


class BundleTests(unittest.TestCase):
    GLOBALS = (
        "EXPECTED_CANDIDATE_SIZE",
        "EXPECTED_CANDIDATE_SHA256",
        "EXPECTED_ROLLBACK_SIZE",
        "EXPECTED_ROLLBACK_SHA256",
        "EXPECTED_DFU_UTIL_SHA256",
        "EXPECTED_SOURCE_MANIFEST_SHA256",
        "EXPECTED_SOURCE_QUALIFICATION_SHA256",
        "EXPECTED_SOURCE_SEAL_SHA256",
        "EVIDENCE_SPECS",
        "TOOLING_PATHS",
        "RELEASE_INPUT_BLOCKERS",
    )

    def setUp(self) -> None:
        self.saved = {name: getattr(bundle, name) for name in self.GLOBALS}
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.fixture = SyntheticRepository(self.root)

    def tearDown(self) -> None:
        for name, value in self.saved.items():
            setattr(bundle, name, value)
        self.temporary.cleanup()

    def package(self, output: str = "bundles/result") -> Path:
        return bundle.create_bundle(self.root, self.fixture.source_path, {}, output)

    def assert_bundle_inventory(self, root: Path) -> None:
        inventory = bundle.parse_inventory((root / "SHA256SUMS").read_bytes(), "bundle")
        actual = {
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file() and path != root / "SHA256SUMS"
        }
        self.assertEqual(set(inventory), actual)
        for name, expected in inventory.items():
            self.assertEqual(digest((root / name).read_bytes()), expected)

    def test_packages_exact_images_and_pending_status(self) -> None:
        source_before = {
            path.relative_to(self.fixture.source): digest(path.read_bytes())
            for path in self.fixture.source.rglob("*")
            if path.is_file()
        }
        output = self.package()
        self.assertEqual((output / "firmware" / bundle.EXPECTED_CANDIDATE_NAME).read_bytes(), self.fixture.candidate)
        self.assertEqual((output / "firmware" / bundle.EXPECTED_ROLLBACK_NAME).read_bytes(), self.fixture.rollback)
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        qualification = manifest["qualification"]
        self.assertEqual(qualification["status"], bundle.QUALIFICATION_STATUS)
        self.assertFalse(qualification["hardware_qualified"])
        self.assertIsNone(qualification["fault_injection_waiver"])
        self.assertEqual(qualification["physical_fault_injection"], "PENDING")
        self.assertEqual(qualification["spur_persistence"], "NON_GATING_PENDING")
        self.assertTrue(qualification["usb_data_plane_trace_mapping_claimed"])
        byte_binding = qualification["flash_and_linked_runtime_device_byte_binding"]
        self.assertTrue(byte_binding["pass"])
        self.assertFalse(byte_binding["historical_selftest_ab_byte_bound"])
        self.assertFalse(manifest["flash_policy"]["automated_flash"])
        self.assertFalse(manifest["firmware"]["f072_binary_included"])
        self.assertFalse(manifest["evidence_packaging"]["evidence_payloads_included"])
        self.assertFalse(manifest["evidence_packaging"]["bundle_self_contained"])
        self.assertTrue(all(not item["payload_included"] for item in manifest["evidence"]))
        self.assertTrue(manifest["qualification_tooling"]["payloads_included"])
        for item in manifest["qualification_tooling"]["files"]:
            self.assertEqual(digest((output / item["bundle_path"]).read_bytes()), item["sha256"])
        report = (output / "qualification-report.md").read_text(encoding="utf-8")
        self.assertIn("not a self-contained evidence archive", report)
        installation = (output / "INSTALLATION.txt").read_text(encoding="utf-8")
        self.assertIn("not a current installation bundle", installation)
        self.assertIn("TinySA_Flasher", installation)
        self.assertIn("tinysa-flasher-build-v1.json", installation)
        self.assertIn("not a raw BIN", installation)
        self.assertIn("grants no write authority", installation)
        self.assertNotIn("dfu-util -", installation)
        self.assertNotIn(" -D ", installation)
        self.assertNotIn(" -U ", installation)
        self.assertIn("Do not use either image on F072", installation)
        self.assertEqual(manifest["flash_policy"]["owner"], "TinySA_Flasher")
        self.assertEqual(
            manifest["flash_policy"]["flash_execution"],
            "standalone-tinysa-flasher-only",
        )
        self.assertFalse(manifest["flash_policy"]["candidate_currently_admissible"])
        self.assertEqual(
            (output / "source-seal" / "SHA256SUMS").read_bytes(),
            (self.fixture.source / "SHA256SUMS").read_bytes(),
        )
        source_after = {
            path.relative_to(self.fixture.source): digest(path.read_bytes())
            for path in self.fixture.source.rglob("*")
            if path.is_file()
        }
        self.assertEqual(source_before, source_after)
        self.assert_bundle_inventory(output)

    def test_output_is_deterministic_across_directories(self) -> None:
        first = self.package("bundles/first")
        second = self.package("bundles/second")
        first_files = {path.relative_to(first).as_posix(): path.read_bytes() for path in first.rglob("*") if path.is_file()}
        second_files = {path.relative_to(second).as_posix(): path.read_bytes() for path in second.rglob("*") if path.is_file()}
        self.assertEqual(first_files, second_files)

    def test_rejects_existing_output(self) -> None:
        self.package()
        with self.assertRaisesRegex(bundle.BundleError, "output already exists"):
            self.package()

    def test_refuses_release_while_required_trust_roots_are_stale(self) -> None:
        bundle.RELEASE_INPUT_BLOCKERS = ("fresh evidence pending",)
        with self.assertRaisesRegex(bundle.BundleError, "release input refresh pending"):
            self.package()

    def test_production_packager_is_blocked_by_fresh_v4_failure(self) -> None:
        production_blockers = self.saved["RELEASE_INPUT_BLOCKERS"]
        self.assertTrue(production_blockers)
        self.assertIn("v4 A/B", " ".join(production_blockers))
        bundle.RELEASE_INPUT_BLOCKERS = production_blockers
        with self.assertRaisesRegex(bundle.BundleError, "v4 A/B"):
            self.package()

    def test_rejects_output_traversal(self) -> None:
        with self.assertRaisesRegex(bundle.BundleError, "traversal"):
            self.package("../escape")

    def test_rejects_output_inside_sealed_input_without_creating_parent(self) -> None:
        unwanted = self.fixture.source / "new-parent"
        with self.assertRaisesRegex(bundle.BundleError, "inside an authenticated input tree"):
            self.package(f"{self.fixture.source_path}/new-parent/bundle")
        self.assertFalse(unwanted.exists())

    def test_rejects_inventory_path_traversal(self) -> None:
        malicious = f"{'0' * 64}  ../escape\n".encode()
        with self.assertRaisesRegex(bundle.BundleError, "traversal"):
            bundle.parse_inventory(malicious, "malicious")

    def test_rejects_symlinked_evidence_location(self) -> None:
        target = self.root / bundle.EVIDENCE_SPECS[0].default_path
        link = self.root / "evidence-link"
        link.symlink_to(target, target_is_directory=True)
        with self.assertRaisesRegex(bundle.BundleError, "symbolic link"):
            bundle.create_bundle(
                self.root,
                self.fixture.source_path,
                {bundle.EVIDENCE_SPECS[0].role: "evidence-link"},
                "bundles/result",
            )

    def test_rejects_tampered_source_manifest(self) -> None:
        manifest = self.fixture.source / "manifest.txt"
        manifest.write_text(manifest.read_text() + "tampered=true\n", encoding="utf-8")
        with self.assertRaisesRegex(bundle.BundleError, "SHA-256 mismatch"):
            self.package()

    def test_rejects_wrong_release_commit_even_with_regenerated_seal(self) -> None:
        self.fixture.write_source_metadata(commit="0" * 40)
        self.fixture.reseal_source(trust_manifest=True)
        with self.assertRaisesRegex(bundle.BundleError, "release_commit mismatch"):
            self.package()

    def test_rejects_wrong_version_even_with_regenerated_seal(self) -> None:
        self.fixture.write_source_metadata(version="tinySA4_wrong")
        self.fixture.reseal_source(trust_manifest=True)
        with self.assertRaisesRegex(bundle.BundleError, "version mismatch"):
            self.package()

    def test_rejects_f072_bytes_renamed_as_candidate(self) -> None:
        f072 = self.fixture.firmware_image("tinySA_v0.4-chibios21-rc5", "+ F072", len(self.fixture.candidate))
        (self.fixture.source / bundle.EXPECTED_CANDIDATE_NAME).write_bytes(f072)
        self.fixture.reseal_source(trust_manifest=False)
        with self.assertRaisesRegex(bundle.BundleError, "candidate hash mismatch"):
            self.package()

    def test_rejects_wrong_rollback_bytes(self) -> None:
        path = self.fixture.source / bundle.EXPECTED_ROLLBACK_NAME
        value = bytearray(path.read_bytes())
        value[-1] ^= 1
        path.write_bytes(value)
        self.fixture.reseal_source(trust_manifest=False)
        with self.assertRaisesRegex(bundle.BundleError, "rollback hash mismatch"):
            self.package()

    def test_rejects_tampered_evidence_file(self) -> None:
        spec = next(item for item in bundle.EVIDENCE_SPECS if item.role == "rc5-usb-runtime")
        path = self.root / spec.default_path / spec.primary_file
        value = json.loads(path.read_text())
        value["result"] = "FAIL"
        write_json(path, value)
        with self.assertRaisesRegex(bundle.BundleError, "SHA-256 mismatch"):
            self.package()

    def test_rejects_regenerated_untrusted_evidence_inventory(self) -> None:
        role = "rc5-usb-runtime"
        spec = next(item for item in bundle.EVIDENCE_SPECS if item.role == role)
        path = self.root / spec.default_path / spec.primary_file
        value = json.loads(path.read_text())
        value["extra"] = "edited"
        write_json(path, value)
        write_inventory(path.parent)
        with self.assertRaisesRegex(bundle.BundleError, "unexpected SHA256SUMS seal"):
            self.package()

    def test_rejects_flash_readback_bytes_after_inventory_refresh(self) -> None:
        role = "rc5-dfu-flash-readback"
        spec = next(item for item in bundle.EVIDENCE_SPECS if item.role == role)
        root = self.root / spec.default_path
        value = bytearray((root / "candidate.readback.bin").read_bytes())
        value[-1] ^= 1
        (root / "candidate.readback.bin").write_bytes(value)
        replacement = dataclasses.replace(spec, inventory_sha256=write_inventory(root))
        bundle.EVIDENCE_SPECS = tuple(replacement if item.role == role else item for item in bundle.EVIDENCE_SPECS)
        with self.assertRaisesRegex(bundle.BundleError, "readback hash mismatch"):
            self.package()

    def test_rejects_flash_option_bytes_selector_after_trust_root_refresh(self) -> None:
        role = "rc5-dfu-flash-readback"
        value = json.loads(json.dumps(self.fixture.evidence_objects[role]))
        argv = value["download"]["argv"]
        argv[argv.index("-a") + 1] = "1"
        self.fixture.replace_evidence(role, value, trust=True)
        with self.assertRaisesRegex(bundle.BundleError, "selectors/address mismatch"):
            self.package()

    def test_rejects_flash_without_sealed_upload_success_marker(self) -> None:
        role = "rc5-dfu-flash-readback"
        spec = next(item for item in bundle.EVIDENCE_SPECS if item.role == role)
        root = self.root / spec.default_path
        (root / "dfu-util-readback.stdout.txt").write_text("upload returned zero\n", encoding="utf-8")
        replacement = dataclasses.replace(spec, inventory_sha256=write_inventory(root))
        bundle.EVIDENCE_SPECS = tuple(replacement if item.role == role else item for item in bundle.EVIDENCE_SPECS)
        with self.assertRaisesRegex(bundle.BundleError, "upload success marker"):
            self.package()

    def test_rejects_usb_link_to_different_flash_run(self) -> None:
        role = "rc5-usb-runtime"
        value = json.loads(json.dumps(self.fixture.evidence_objects[role]))
        value["candidate_binary"]["flash_evidence"]["run_json_sha256"] = "f" * 64
        self.fixture.replace_evidence(role, value, trust=True)
        with self.assertRaisesRegex(bundle.BundleError, "flash run link does not match"):
            self.package()

    def test_rejects_reset_link_to_different_flash_inventory(self) -> None:
        role = "rc5-reset-retention"
        value = json.loads(json.dumps(self.fixture.evidence_objects[role]))
        value["candidate_binary"]["flash_evidence"]["inventory_sha256"] = "f" * 64
        self.fixture.replace_evidence(role, value, trust=True)
        with self.assertRaisesRegex(bundle.BundleError, "flash inventory link does not match"):
            self.package()

    def test_rejects_flash_runtime_timestamp_inversion(self) -> None:
        role = "rc5-usb-runtime"
        value = json.loads(json.dumps(self.fixture.evidence_objects[role]))
        value["started_utc"] = "2026-07-15T03:00:00+00:00"
        value["finished_utc"] = "2026-07-15T03:05:00+00:00"
        self.fixture.replace_evidence(role, value, trust=True)
        with self.assertRaisesRegex(bundle.BundleError, "not chronologically ordered"):
            self.package()

    def test_rejects_semantic_failure_even_with_new_trust_root(self) -> None:
        role = "rc5-usb-runtime"
        value = dict(self.fixture.evidence_objects[role])
        value["result"] = "FAIL"
        self.fixture.replace_evidence(role, value, trust=True)
        with self.assertRaisesRegex(bundle.BundleError, "result must be 'PASS'"):
            self.package()

    def test_rejects_ab_self_comparison_with_valid_inventory(self) -> None:
        role = "official-c979-vs-rc5-ab"
        value = json.loads(json.dumps(self.fixture.evidence_objects[role]))
        value["candidate"]["path"] = value["reference"]["path"]
        self.fixture.replace_evidence(role, value, trust=True)
        with self.assertRaisesRegex(bundle.BundleError, "self-comparison"):
            self.package()

    def test_rejects_ab_without_explicit_qualification_eligibility(self) -> None:
        role = "official-c979-vs-rc5-ab"
        value = json.loads(json.dumps(self.fixture.evidence_objects[role]))
        del value["qualification_eligible"]
        self.fixture.replace_evidence(role, value, trust=True)
        with self.assertRaisesRegex(bundle.BundleError, "qualification_eligible"):
            self.package()

    def test_rejects_ab_bound_to_wrong_candidate_inventory(self) -> None:
        role = "official-c979-vs-rc5-ab"
        value = json.loads(json.dumps(self.fixture.evidence_objects[role]))
        value["candidate"]["checksums"]["sha256"] = "f" * 64
        self.fixture.replace_evidence(role, value, trust=True)
        with self.assertRaisesRegex(bundle.BundleError, "candidate attestation inventory mismatch|not bound to the verified RC5 capture"):
            self.package()

    def test_rejects_ab_duplicate_cases_after_trust_root_refresh(self) -> None:
        role = "official-c979-vs-rc5-ab"
        value = json.loads(json.dumps(self.fixture.evidence_objects[role]))
        value["cases"] = [dict(value["cases"][0]) for _ in range(14)]
        self.fixture.replace_evidence(role, value, trust=True)
        with self.assertRaisesRegex(bundle.BundleError, "case sequence"):
            self.package()

    def test_rejects_usb_summary_without_linked_frame_payload(self) -> None:
        role = "rc5-usb-runtime"
        spec = next(item for item in bundle.EVIDENCE_SPECS if item.role == role)
        root = self.root / spec.default_path
        (root / "frame-02.rgb565be").unlink()
        replacement = dataclasses.replace(spec, inventory_sha256=write_inventory(root))
        bundle.EVIDENCE_SPECS = tuple(replacement if item.role == role else item for item in bundle.EVIDENCE_SPECS)
        with self.assertRaisesRegex(bundle.BundleError, "frame-02.rgb565be is not bound"):
            self.package()

    def test_rejects_reset_without_physical_transport_end_marker(self) -> None:
        role = "rc5-reset-retention"
        spec = next(item for item in bundle.EVIDENCE_SPECS if item.role == role)
        root = self.root / spec.default_path
        value = json.loads((root / spec.primary_file).read_text())
        weak_response = b"ch> \n"
        value["reset"]["response_sha256"] = digest(weak_response)
        write_json(root / spec.primary_file, value)
        (root / "reset-reset.txt").write_bytes(weak_response)
        replacement = dataclasses.replace(
            spec,
            primary_sha256=digest((root / spec.primary_file).read_bytes()),
            inventory_sha256=write_inventory(root),
        )
        bundle.EVIDENCE_SPECS = tuple(replacement if item.role == role else item for item in bundle.EVIDENCE_SPECS)
        with self.assertRaisesRegex(bundle.BundleError, "did not disconnect"):
            self.package()

    def test_rejects_cross_evidence_from_different_usb_unit(self) -> None:
        role = "rc5-reset-retention"
        value = json.loads(json.dumps(self.fixture.evidence_objects[role]))
        value["after"]["usb_identity"]["serial_number"] = "999"
        self.fixture.replace_evidence(role, value, trust=True)
        with self.assertRaisesRegex(bundle.BundleError, "wrong physical USB unit/path"):
            self.package()

    def test_rejects_manual_attestation_linked_to_wrong_post_control_hash(self) -> None:
        role = "rc5-manual-controls"
        value = json.loads(json.dumps(self.fixture.evidence_objects[role]))
        value["post_control_read_only_evidence"]["run_json_sha256"] = "0" * 64
        self.fixture.replace_evidence(role, value, trust=True)
        with self.assertRaisesRegex(bundle.BundleError, "post-control run hash mismatch"):
            self.package()

    def test_rejects_arbitrary_manual_check_labels(self) -> None:
        role = "rc5-manual-controls"
        value = json.loads(json.dumps(self.fixture.evidence_objects[role]))
        value["operator_attestation"]["checks"] = ["x"] * 6
        self.fixture.replace_evidence(role, value, trust=True)
        with self.assertRaisesRegex(bundle.BundleError, "manual check semantics"):
            self.package()

    def test_reservation_never_replaces_concurrent_empty_output(self) -> None:
        existing = self.root / "race" / "bundle"
        existing.mkdir(parents=True)
        with self.assertRaisesRegex(bundle.BundleError, "output already exists"):
            bundle.reserve_output_directory(self.root, "race/bundle")
        self.assertTrue(existing.is_dir())

    def test_rejects_unknown_evidence_role_and_cli_has_no_waiver_path(self) -> None:
        with self.assertRaisesRegex(bundle.BundleError, "unknown evidence role"):
            bundle.evidence_overrides(["invented=evidence/anything"])
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit):
            bundle.parse_args(["--output", "bundles/result", "--waiver"])
        self.assertIn("unrecognized arguments", stderr.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
