#!/usr/bin/env python3
"""Package the sealed RC5 images with authenticated physical-evidence references.

This program only reads release/evidence artifacts and writes a new bundle.  It
does not build, flash, reset, or communicate with hardware.  Its original
evidence set predates the qualification-eligible fresh v4 A/B failure, so the
production entry point is now deliberately fail-closed.  Synthetic tests may
clear that blocker to exercise the immutable earlier bundle format.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import posixpath
import re
import stat
import struct
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping


BUNDLE_FORMAT = "tinysa-physical-qualification-bundle-v1"
QUALIFICATION_STATUS = "physical-runtime-pass_fault-injection-pending"

EXPECTED_RELEASE_ID = "v0.4-chibios21.11.5-rc5"
EXPECTED_VERSION = "tinySA4_v0.4-chibios21-rc5"
EXPECTED_RELEASE_COMMIT = "6fdf6f307ecb0cef2e3af478b0fc7b80a1fd13e2"
EXPECTED_IMPLEMENTATION_COMMIT = "d4c7ec8c2a6df9887bb0ab306346ebbf47688eef"
EXPECTED_CHIBIOS_COMMIT = "b3f82b396de7cf2a9e85bc8f1575fbd58e9428d9"
EXPECTED_CANDIDATE_NAME = "tinySA4_v0.4-chibios21.11.5-rc5.bin"
EXPECTED_CANDIDATE_SIZE = 193_980
EXPECTED_CANDIDATE_SHA256 = "1e3f45a9744b18985622d5abf6c2445524a4ad53a831316766c37de80ac96685"

EXPECTED_ROLLBACK_VERSION = "tinySA4_v1.4-224-gc979386"
EXPECTED_ROLLBACK_COMMIT = "c97938697b6c7485e7cab50bca9af76996b7d671"
EXPECTED_ROLLBACK_NAME = "ROLLBACK_OFFICIAL_tinySA4_v1.4-224-gc979386.bin"
EXPECTED_ROLLBACK_SIZE = 185_704
EXPECTED_ROLLBACK_SHA256 = "3c9847ff4d7b80561df2f2f1030a112703a083409ffb2ee11361b2413b7c1e41"

EXPECTED_SOURCE_SEAL_SHA256 = "053699915f33b968e7e18924086c841dacd944d78f3c355aba25c8d45b054216"
EXPECTED_SOURCE_MANIFEST_SHA256 = "5c88630b068b4f0246f3c40020503af218cc25d2ed1d31b835e216f6da939e4b"
EXPECTED_SOURCE_QUALIFICATION_SHA256 = "3fa3d3b4573f217352a58d3fff512371ff88cd3ddfbfd9f7eec7cbcb44db9ce1"

EXPECTED_DFU_VID = 0x0483
EXPECTED_DFU_PID = 0xDF11
EXPECTED_DFU_LOCATION = "0-1"
EXPECTED_DFU_SERIAL = "2066365B2036"
EXPECTED_NORMAL_VID = 0x0483
EXPECTED_NORMAL_PID = 0x5740
EXPECTED_NORMAL_SERIAL = "706"
EXPECTED_DFU_UTIL_SHA256 = "d650bcf7a3f1ad42eff139924c93aacdde53d0c61629bae5aa85c8e793f5d669"
EXPECTED_DFU_UTIL_SIZE = 227_304
EXPECTED_DFU_UTIL_VERSION = "dfu-util 0.11"
EXPECTED_FLASH_SCHEMA = "tinysa-physical-dfu-flash-evidence-v2"

DEFAULT_SOURCE_RELEASE = (
    ".artifacts/worktrees/chibios-rc5/.artifacts/chibios-releases/"
    "v0.4-chibios21.11.5-rc5/6fdf6f307ecb0cef2e3af478b0fc7b80a1fd13e2"
)

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
INVENTORY_LINE_RE = re.compile(r"^([0-9a-f]{64})  (.+)$")
MAX_TEXT_BYTES = 16 * 1024 * 1024
MAX_FILE_BYTES = 64 * 1024 * 1024
LOAD_ADDRESS = 0x0800_0000
CONFIG_COMMANDS = {
    "color",
    "correction low",
    "correction lna",
    "correction ultra",
    "correction ultra_lna",
    "correction direct",
    "correction direct_lna",
    "correction harm",
    "correction harm_lna",
    "correction out",
    "correction out_direct",
    "correction out_adf",
    "correction out_ultra",
}
TOOLING_PATHS = (
    "tools/package-physical-qualification-bundle.py",
    "tools/capture-physical-selftests.py",
    "tools/compare-physical-selftest-captures.py",
    "tools/capture-physical-selftest-negative.py",
    "tools/capture-physical-usb-runtime.py",
    "tools/capture-physical-reset-retention.py",
    "tools/flash-physical-dfu-evidence.py",
    "Font5x7.c",
)
RELEASE_INPUT_BLOCKERS: tuple[str, ...] = (
    "fresh qualification-eligible v4 A/B remains failed on case 2; the three "
    "passing repeats are supplemental and require a formal disposition before "
    "any current bundle can reuse the earlier fault-injection-only status",
)


class BundleError(RuntimeError):
    """Raised for an input-authentication or safe-packaging failure."""


@dataclass(frozen=True)
class EvidenceSpec:
    role: str
    default_path: str
    inventory_sha256: str
    primary_file: str
    primary_sha256: str
    schema: str
    validator: str


EVIDENCE_SPECS: tuple[EvidenceSpec, ...] = (
    EvidenceSpec(
        "rc5-all-14-selftests",
        ".artifacts/hardware-selftest/rc5",
        "1cebd9368c0f7ccc2198fcbe1bbb59fb61a467c65f21045256695cfe8fa1a14c",
        "run.json",
        "ef6b86d6e5eb27ff9da27c562d358d7fe257669eadae6f3c4da53a38145aad1d",
        "tinysa-physical-selftest-capture-v1",
        "rc5_selftest",
    ),
    EvidenceSpec(
        "rc5-cal-disconnected-negative",
        ".artifacts/hardware-selftest/rc5-cal-disconnected-20260714",
        "c5ba35c99f3d7dd766cda059167d62ef7c79b43610a134401ec6ec9b28f9a5c5",
        "run.json",
        "bf51452a72fa6071120f17853efd088d9eb2564cce8793e946a0d08d97589296",
        "tinysa-physical-selftest-negative-v1",
        "cal_disconnected",
    ),
    EvidenceSpec(
        "rc5-cal-reconnected-recovery",
        ".artifacts/hardware-selftest/rc5-cal-reconnected-20260714",
        "8bbc0d4854116920dd8c14d4f263666d4efece3ed7aa412c398a0b5d318e786a",
        "run.json",
        "51d6feaae16ba399cee3e1d49ba33c9244e295573b040d75b3f4ec2cc0a94a55",
        "tinysa-physical-selftest-negative-v1",
        "cal_reconnected",
    ),
    EvidenceSpec(
        "official-c979-all-14-selftests",
        ".artifacts/hardware-selftest/official-c979",
        "28b7ed7bc5f4214da8cbba7fc21340ef4b534437b3f66c7598f673ef0d0d2890",
        "run.json",
        "278da82fd158676d41c63bb45be08b397be31c7048dae611b447f1eab36ba41f",
        "tinysa-physical-selftest-capture-v1",
        "official_selftest",
    ),
    EvidenceSpec(
        "official-c979-vs-rc5-ab",
        ".artifacts/hardware-selftest/official-c979-vs-rc5-20260714-v3",
        "6f420450e023f98fc423ad62d5a9e256c541044f28c128be9358a84826022321",
        "report.json",
        "2f58569f30981c0076696680f256bd0788f587d2be0a22738167aff9993460ce",
        "tinysa-physical-selftest-ab-v3",
        "ab_report",
    ),
    EvidenceSpec(
        "rc5-dfu-flash-readback",
        ".artifacts/hardware-flash/rc5-dfu-flash-readback-20260714",
        "b96880fb1c5a5ce3eaac93e34bc24a994aa3ed41e358346f06b1f57b10573301",
        "run.json",
        "0657dd6f5e541eeeb7900c5ee42aa89ddb6f5d0efa4a1eb2e7552607d9d86565",
        EXPECTED_FLASH_SCHEMA,
        "dfu_flash",
    ),
    EvidenceSpec(
        "rc5-usb-runtime",
        ".artifacts/hardware-runtime/rc5-usb-runtime-20260714-v3",
        "508e94e28c768a6281801d2123769cff4076ea75332452dc56ba1aa6a2b005ee",
        "run.json",
        "f6b7f6357530ae03da4a4c20a8da433950adb59a334011f9bb96ba301da12bef",
        "tinysa-physical-usb-runtime-v2",
        "usb_runtime",
    ),
    EvidenceSpec(
        "rc5-reset-retention",
        ".artifacts/hardware-runtime/rc5-reset-retention-20260714-v3",
        "dd88b441a17c147b5ed4d64c19b933aa23448d24a62bb1b055fc8d64d07b6490",
        "run.json",
        "edad72220c7b1dd14eec553aabb050a05872bb91a0d26300ed3313aa8beba59a",
        "tinysa-physical-reset-retention-v2",
        "reset_retention",
    ),
    EvidenceSpec(
        "rc5-manual-controls",
        ".artifacts/hardware-controls/rc5-manual-controls-20260714",
        "6fecc54c64b08055b6dfbaa4edf0c96cd5bba745dccf3d50b360889617dcb894",
        "attestation.json",
        "ab5eb75423d5e8e2be7d85ecb9d234ceecf2545eacc70ba9f80525a9bae19d53",
        "tinysa-physical-manual-controls-attestation-v1",
        "manual_controls",
    ),
    EvidenceSpec(
        "rc5-post-controls-readonly",
        ".artifacts/hardware-controls/rc5-post-controls-20260714",
        "fa38924cf71035a44cd3c0c03743fb8128d82b60f0928fe57d0d0ef633d4856b",
        "run.json",
        "5beb4707c394180c325834acca9c21ac141e642aacebf2f0f37241eedbf22f62",
        "tinysa-physical-usb-runtime-v1",
        "usb_runtime",
    ),
)


@dataclass
class VerifiedEvidence:
    spec: EvidenceSpec
    repository_path: str
    root: Path
    inventory_bytes: bytes
    inventory: dict[str, str]
    primary: dict[str, Any]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise BundleError(message)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def is_sha256(value: Any) -> bool:
    return isinstance(value, str) and SHA256_RE.fullmatch(value) is not None


def validate_relative_path(value: str, label: str) -> PurePosixPath:
    require(bool(value) and "\x00" not in value, f"{label} must be a non-empty relative path")
    require("\\" not in value, f"{label} must use portable forward slashes")
    path = PurePosixPath(value)
    require(not path.is_absolute(), f"{label} must be repository-relative")
    require(value not in {".", "./"}, f"{label} must name a repository child")
    require(all(part not in {"", ".", ".."} for part in path.parts), f"{label} contains traversal")
    return path


def resolve_repository_input(repository_root: Path, relative: str, label: str) -> Path:
    pure = validate_relative_path(relative, label)
    current = repository_root
    for part in pure.parts:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError as error:
            raise BundleError(f"{label} does not exist: {relative}") from error
        require(not stat.S_ISLNK(mode), f"{label} crosses symbolic link: {current}")
    resolved = current.resolve(strict=True)
    require(resolved.is_relative_to(repository_root), f"{label} escapes repository root")
    return resolved


def resolve_output(repository_root: Path, relative: str) -> Path:
    pure = validate_relative_path(relative, "output")
    current = repository_root
    for part in pure.parts[:-1]:
        current = current / part
        if current.exists() or current.is_symlink():
            require(not current.is_symlink(), f"output crosses symbolic link: {current}")
            require(current.is_dir(), f"output parent is not a directory: {current}")
    output = repository_root.joinpath(*pure.parts)
    require(not output.exists() and not output.is_symlink(), f"output already exists: {relative}")
    require(output.resolve(strict=False).is_relative_to(repository_root), "output escapes repository root")
    return output


def read_regular_file(path: Path, maximum_bytes: int = MAX_FILE_BYTES, *, allow_empty: bool = False) -> bytes:
    require(not path.is_symlink(), f"symbolic-link input rejected: {path}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise BundleError(f"cannot open input: {path}: {error}") from error
    try:
        before = os.fstat(descriptor)
        require(stat.S_ISREG(before.st_mode), f"input is not a regular file: {path}")
        require(before.st_size <= maximum_bytes, f"input exceeds size bound: {path}")
        require(allow_empty or before.st_size > 0, f"input is empty: {path}")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, maximum_bytes + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            require(total <= maximum_bytes, f"input exceeds size bound: {path}")
        after = os.fstat(descriptor)
        identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
        identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
        require(identity_before == identity_after and total == before.st_size, f"input changed while read: {path}")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def hash_regular_file(path: Path) -> str:
    return sha256_bytes(read_regular_file(path, allow_empty=True))


def inventory_files(root: Path, excluded: Path) -> set[str]:
    files: set[str] = set()
    for directory, directory_names, file_names in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        for name in list(directory_names):
            path = directory_path / name
            mode = path.lstat().st_mode
            require(not stat.S_ISLNK(mode), f"inventory tree contains symbolic-link directory: {path}")
            require(stat.S_ISDIR(mode), f"inventory tree contains non-directory: {path}")
        for name in file_names:
            path = directory_path / name
            mode = path.lstat().st_mode
            require(not stat.S_ISLNK(mode), f"inventory tree contains symbolic-link file: {path}")
            require(stat.S_ISREG(mode), f"inventory tree contains special file: {path}")
            if path != excluded:
                files.add(path.relative_to(root).as_posix())
    return files


def parse_inventory(value: bytes, label: str) -> dict[str, str]:
    try:
        text = value.decode("utf-8")
    except UnicodeDecodeError as error:
        raise BundleError(f"{label} is not UTF-8") from error
    require(text.endswith("\n"), f"{label} must end with newline")
    result: dict[str, str] = {}
    for line_number, line in enumerate(text.splitlines(), 1):
        match = INVENTORY_LINE_RE.fullmatch(line)
        require(match is not None, f"{label}:{line_number}: malformed SHA256SUMS line")
        assert match is not None
        digest, raw_name = match.groups()
        name = raw_name[2:] if raw_name.startswith("./") else raw_name
        pure = validate_relative_path(name, f"{label}:{line_number} path")
        normalized = pure.as_posix()
        require(normalized not in result, f"{label}:{line_number}: duplicate path {normalized}")
        result[normalized] = digest
    require(bool(result), f"{label} is empty")
    return result


def verify_inventory(root: Path, expected_inventory_sha256: str) -> tuple[bytes, dict[str, str]]:
    inventory_path = root / "SHA256SUMS"
    inventory_bytes = read_regular_file(inventory_path, MAX_TEXT_BYTES)
    actual_inventory_sha256 = sha256_bytes(inventory_bytes)
    require(
        actual_inventory_sha256 == expected_inventory_sha256,
        f"unexpected SHA256SUMS seal for {root}: {actual_inventory_sha256}",
    )
    entries = parse_inventory(inventory_bytes, str(inventory_path))
    actual_files = inventory_files(root, inventory_path)
    require(set(entries) == actual_files, f"SHA256SUMS is not exhaustive/self-excluding for {root}")
    for name, expected_digest in entries.items():
        path = root.joinpath(*PurePosixPath(name).parts)
        actual_digest = hash_regular_file(path)
        require(actual_digest == expected_digest, f"SHA-256 mismatch for {path}")
    return inventory_bytes, entries


def parse_key_value(value: bytes, label: str) -> dict[str, str]:
    try:
        text = value.decode("utf-8")
    except UnicodeDecodeError as error:
        raise BundleError(f"{label} is not UTF-8") from error
    result: dict[str, str] = {}
    for line_number, line in enumerate(text.splitlines(), 1):
        require("=" in line, f"{label}:{line_number}: expected key=value")
        key, item = line.split("=", 1)
        require(bool(key) and key not in result, f"{label}:{line_number}: invalid or duplicate key")
        result[key] = item
    return result


def parse_json_object(value: bytes, label: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BundleError(f"{label} is not valid JSON: {error}") from error
    require(isinstance(parsed, dict), f"{label} must be a JSON object")
    return parsed


def validate_vectors(binary: bytes, label: str) -> None:
    require(len(binary) >= 8, f"{label} has no vector table")
    stack_pointer, reset_handler = struct.unpack_from("<II", binary)
    stack_in_sram = 0x2000_0000 <= stack_pointer <= 0x2000_A000
    stack_in_ccm = 0x1000_0000 <= stack_pointer <= 0x1000_2000
    require(stack_pointer & 3 == 0 and (stack_in_sram or stack_in_ccm), f"{label} has invalid F303 stack vector")
    reset_address = reset_handler & ~1
    require(
        bool(reset_handler & 1) and LOAD_ADDRESS + 8 <= reset_address < LOAD_ADDRESS + len(binary),
        f"{label} has invalid Thumb reset vector",
    )


def validate_source_release(root: Path) -> dict[str, Any]:
    seal_bytes, seal_entries = verify_inventory(root, EXPECTED_SOURCE_SEAL_SHA256)
    manifest_bytes = read_regular_file(root / "manifest.txt", MAX_TEXT_BYTES)
    qualification_bytes = read_regular_file(root / "qualification.txt", MAX_TEXT_BYTES)
    require(sha256_bytes(manifest_bytes) == EXPECTED_SOURCE_MANIFEST_SHA256, "source manifest trust-root mismatch")
    require(
        sha256_bytes(qualification_bytes) == EXPECTED_SOURCE_QUALIFICATION_SHA256,
        "source simulation qualification trust-root mismatch",
    )
    manifest = parse_key_value(manifest_bytes, "source manifest")
    qualification = parse_key_value(qualification_bytes, "source qualification")

    expected_manifest = {
        "release_id": EXPECTED_RELEASE_ID,
        "version": EXPECTED_VERSION,
        "release_commit": EXPECTED_RELEASE_COMMIT,
        "implementation_commit": EXPECTED_IMPLEMENTATION_COMMIT,
        "chibios_commit": EXPECTED_CHIBIOS_COMMIT,
        "binary_size": str(EXPECTED_CANDIDATE_SIZE),
        "binary_sha256": EXPECTED_CANDIDATE_SHA256,
        "official_rollback_commit": EXPECTED_ROLLBACK_COMMIT,
        "official_rollback_binary_size": str(EXPECTED_ROLLBACK_SIZE),
        "official_rollback_binary_sha256": EXPECTED_ROLLBACK_SHA256,
        "simulation_qualification": "SIMULATION_PASS_HARDWARE_PENDING",
        "hardware_qualified": "false",
        "hardware_flash_performed": "false",
        "automated_flash": "false",
    }
    for key, expected in expected_manifest.items():
        require(manifest.get(key) == expected, f"source manifest {key} mismatch")
    require(manifest.get("f072_binary_sha256") != EXPECTED_CANDIDATE_SHA256, "F072 image substituted for F303 candidate")

    expected_qualification = {
        "release_id": EXPECTED_RELEASE_ID,
        "simulation_qualification": "SIMULATION_PASS_HARDWARE_PENDING",
        "hardware_qualified": "false",
        "hardware_flash_performed": "false",
        "result": "PASS",
        "candidate_binary_sha256": EXPECTED_CANDIDATE_SHA256,
        "simulation_package_seal": "PASS",
    }
    for key, expected in expected_qualification.items():
        require(qualification.get(key) == expected, f"source qualification {key} mismatch")

    candidate = read_regular_file(root / EXPECTED_CANDIDATE_NAME)
    rollback = read_regular_file(root / EXPECTED_ROLLBACK_NAME)
    require(len(candidate) == EXPECTED_CANDIDATE_SIZE, "candidate size mismatch")
    require(sha256_bytes(candidate) == EXPECTED_CANDIDATE_SHA256, "candidate hash mismatch (F072/wrong image rejected)")
    require(EXPECTED_VERSION.encode("ascii") in candidate, "candidate version identity missing")
    require(b"+ ZS407" in candidate, "candidate is not a ZS407 image")
    validate_vectors(candidate, "candidate")
    require(len(rollback) == EXPECTED_ROLLBACK_SIZE, "rollback size mismatch")
    require(sha256_bytes(rollback) == EXPECTED_ROLLBACK_SHA256, "rollback hash mismatch")
    require(EXPECTED_ROLLBACK_VERSION.encode("ascii") in rollback, "rollback version identity missing")
    require(b"+ ZS407" in rollback, "rollback is not a ZS407 image")
    validate_vectors(rollback, "rollback")
    require(seal_entries.get(EXPECTED_CANDIDATE_NAME) == EXPECTED_CANDIDATE_SHA256, "source seal omits exact F303 binary")
    require(seal_entries.get(EXPECTED_ROLLBACK_NAME) == EXPECTED_ROLLBACK_SHA256, "source seal omits exact rollback binary")
    require(seal_entries.get("manifest.txt") == EXPECTED_SOURCE_MANIFEST_SHA256, "source seal does not bind manifest")
    require(
        seal_entries.get("qualification.txt") == EXPECTED_SOURCE_QUALIFICATION_SHA256,
        "source seal does not bind simulation qualification",
    )
    return {
        "seal_bytes": seal_bytes,
        "manifest_bytes": manifest_bytes,
        "qualification_bytes": qualification_bytes,
        "manifest": manifest,
        "candidate": candidate,
        "rollback": rollback,
        "entry_count": len(seal_entries),
    }


def require_json(data: Mapping[str, Any], key: str, expected: Any, role: str) -> None:
    require(data.get(key) == expected, f"{role}: {key} must be {expected!r}")


def candidate_binding(data: Mapping[str, Any], role: str) -> None:
    candidate = data.get("candidate_binary")
    require(isinstance(candidate, dict), f"{role}: candidate_binary missing")
    require(candidate.get("sha256") == EXPECTED_CANDIDATE_SHA256, f"{role}: candidate hash mismatch")
    require(candidate.get("bytes") == EXPECTED_CANDIDATE_SIZE, f"{role}: candidate size mismatch")
    require(candidate.get("local_hash_match") is True, f"{role}: local candidate was not authenticated")


def validate_config_integrity(value: Any, role: str) -> tuple[dict[str, str], dict[str, str]]:
    require(isinstance(value, dict) and value.get("pass") is True, f"{role}: config-integrity gate failed")
    before = value.get("before_sha256")
    after = value.get("after_sha256")
    commands = value.get("commands")
    require(isinstance(before, dict) and isinstance(after, dict), f"{role}: config digests missing")
    require(set(before) == CONFIG_COMMANDS and before == after, f"{role}: persisted config changed or is incomplete")
    require(all(is_sha256(item) for item in before.values()), f"{role}: invalid config digest")
    require(isinstance(commands, list) and set(commands) == CONFIG_COMMANDS and len(commands) == 13, f"{role}: config command inventory mismatch")
    require(value.get("mismatches") == [], f"{role}: config mismatch list is nonempty")
    return before, after


def validate_display_and_shell(case: Mapping[str, Any], role: str) -> None:
    display = case.get("display")
    require(isinstance(display, dict), f"{role}: display evidence missing")
    require(display.get("bytes") == 307_200, f"{role}: framebuffer byte count mismatch")
    require(isinstance(display.get("nonblack_pixels"), int) and display["nonblack_pixels"] >= 400, f"{role}: framebuffer is empty")
    require(isinstance(display.get("unique_rgb565_colors"), int) and display["unique_rgb565_colors"] >= 2, f"{role}: framebuffer lacks color content")
    require(SHA256_RE.fullmatch(str(display.get("sha256", ""))) is not None, f"{role}: framebuffer digest missing")
    shell = case.get("shell_evidence")
    require(isinstance(shell, dict), f"{role}: shell evidence missing")
    require(shell.get("data_points") == [450, 450, 450], f"{role}: data planes are incomplete")
    require(shell.get("frequency_points") == 450, f"{role}: frequency grid is incomplete")
    require(shell.get("trace_dump_bytes") == 7_200, f"{role}: trace matrix byte count mismatch")
    require(SHA256_RE.fullmatch(str(shell.get("trace_dump_sha256", ""))) is not None, f"{role}: trace digest missing")
    metrics = shell.get("trace_metrics")
    require(isinstance(metrics, list) and len(metrics) == 4, f"{role}: trace metrics are incomplete")
    require(all(isinstance(item, dict) and item.get("points") == 450 and item.get("finite") == 450 for item in metrics), f"{role}: non-finite/incomplete trace metrics")


def validate_selftest(data: Mapping[str, Any], role: str, variant: str, version: str) -> None:
    require_json(data, "result", "PASS", role)
    require_json(data, "variant", variant, role)
    require_json(data, "expected_version", version, role)
    cases = data.get("cases")
    require(isinstance(cases, list) and len(cases) == 14, f"{role}: expected all 14 self-tests")
    require(
        [case.get("selftest_argument") for case in cases if isinstance(case, dict)] == list(range(1, 15)),
        f"{role}: self-test sequence mismatch",
    )
    require(all(isinstance(case, dict) and case.get("result") == "PASS" for case in cases), f"{role}: a self-test did not pass")
    require([case.get("zero_based_case") for case in cases] == list(range(14)), f"{role}: zero-based case sequence mismatch")
    require(data.get("zero_based_cases") == list(range(14)), f"{role}: requested case sequence mismatch")
    for number, case in enumerate(cases, 1):
        validate_display_and_shell(case, f"{role} case {number}")
        for key in ("comparator_rgb565_sha256", "png_sha256"):
            require(SHA256_RE.fullmatch(str(case.get(key, ""))) is not None, f"{role} case {number}: {key} missing")
    validate_config_integrity(data.get("persisted_config_integrity"), role)


def validate_negative(data: Mapping[str, Any], role: str, recovery: bool) -> None:
    require_json(data, "result", "PASS", role)
    require_json(data, "variant", "rc5-cal-loopback-control", role)
    require_json(data, "expected_version", EXPECTED_VERSION, role)
    expected_phase = "recovery" if recovery else "disconnected"
    expected_confirmation = "CAL-RF-LOOPBACK-RECONNECTED" if recovery else "CAL-RF-LOOPBACK-DISCONNECTED"
    require_json(data, "phase", expected_phase, role)
    require_json(data, "confirmation", expected_confirmation, role)
    require_json(data, "selftest_argument", 3, role)
    for key in ("screen_condition", "trace_condition"):
        condition = data.get(key)
        require(isinstance(condition, dict) and condition.get("pass") is True, f"{role}: {key} failed")
    cases = data.get("cases")
    require(isinstance(cases, list) and len(cases) == 1 and isinstance(cases[0], dict) and cases[0].get("result") == "PASS", f"{role}: bounded case failed")
    case = cases[0]
    require(case.get("selftest_argument") == 3 and case.get("zero_based_case") == 2, f"{role}: wrong bounded case")
    require(case.get("screen_condition") == data.get("screen_condition"), f"{role}: screen condition is not bound to case")
    require(case.get("trace_condition") == data.get("trace_condition"), f"{role}: trace condition is not bound to case")
    validate_display_and_shell(case, role)
    screen = data["screen_condition"]
    require(screen.get("gate") is True and screen.get("literal_match") is True, f"{role}: exact screen literal gate failed")
    require(screen.get("method") == "exact-font-mask-and-observed-palette-rgb565", f"{role}: weak screen-literal method")
    literals = screen.get("literals")
    require(
        isinstance(literals, list)
        and len(literals) == 1
        and isinstance(literals[0], dict)
        and literals[0].get("pass") is True,
        f"{role}: status literal missing",
    )
    expected_text = "Test 3: Pass" if recovery else "Test 3: Signal level Fail"
    expected_color = "0x07e0" if recovery else "0xfc10"
    require(literals[0].get("text") == expected_text and literals[0].get("expected_rgb565") == expected_color, f"{role}: wrong status literal/color")
    trace = data["trace_condition"]
    require(trace.get("threshold_dbm") == -60.0, f"{role}: wrong signal threshold")
    maximum = trace.get("actual_trace_maximum_dbm")
    require(isinstance(maximum, (int, float)) and not isinstance(maximum, bool), f"{role}: trace maximum missing")
    require(maximum >= -60.0 if recovery else maximum < -60.0, f"{role}: trace does not corroborate branch")
    validate_config_integrity(data.get("persisted_config_integrity"), role)


def parse_utc(value: Any, label: str) -> datetime:
    require(isinstance(value, str), f"{label}: UTC timestamp missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise BundleError(f"{label}: invalid UTC timestamp") from error
    require(parsed.tzinfo is not None, f"{label}: timestamp must carry a UTC offset")
    parsed = parsed.astimezone(timezone.utc)
    return parsed


def require_dfu_transfer_argv(
    value: Any,
    role: str,
    transfer_flag: str,
    address: str,
    payload_name: str,
) -> None:
    require(isinstance(value, list) and all(isinstance(item, str) for item in value), f"{role}: transfer argv missing")
    expected_middle = [
        "-d", "0483:df11",
        "-p", EXPECTED_DFU_LOCATION,
        "-S", EXPECTED_DFU_SERIAL,
        "-c", "1",
        "-i", "0",
        "-a", "0",
        "-s", address,
        transfer_flag,
    ]
    require(len(value) == len(expected_middle) + 2, f"{role}: transfer argv has extra or missing selectors")
    require(value[1:-1] == expected_middle, f"{role}: transfer argv selectors/address mismatch")
    require("\\" not in value[0] and Path(value[0]).name == "dfu-util.snapshot", f"{role}: transfer did not use sealed dfu-util snapshot")
    require("\\" not in value[-1] and Path(value[-1]).name == payload_name, f"{role}: transfer payload path mismatch")


def validate_flash_reference(candidate: Mapping[str, Any], role: str) -> Mapping[str, Any]:
    require(candidate.get("device_byte_binding") is True, f"{role}: candidate/device byte binding is not asserted")
    reference = candidate.get("flash_evidence")
    require(isinstance(reference, dict), f"{role}: flash evidence reference missing")
    expected = {
        "schema": EXPECTED_FLASH_SCHEMA,
        "candidate_sha256": EXPECTED_CANDIDATE_SHA256,
        "dfu_location": EXPECTED_DFU_LOCATION,
        "dfu_serial": EXPECTED_DFU_SERIAL,
        "selected_alt": 0,
        "readback_performed": True,
        "readback_sha256": EXPECTED_CANDIDATE_SHA256,
        "exact_byte_match": True,
    }
    for key, item in expected.items():
        require(reference.get(key) == item, f"{role}: flash evidence {key} mismatch")
    require(is_sha256(reference.get("inventory_sha256")), f"{role}: flash inventory reference missing")
    require(is_sha256(reference.get("run_json_sha256")), f"{role}: flash run reference missing")
    normal = reference.get("normal_usb_identity")
    require(
        normalize_usb_identity(normal, f"{role} flash normal identity")
        == (EXPECTED_NORMAL_VID, EXPECTED_NORMAL_PID, EXPECTED_NORMAL_SERIAL, EXPECTED_DFU_LOCATION),
        f"{role}: flash normal USB identity mismatch",
    )
    return reference


def validate_dfu_flash(data: Mapping[str, Any], role: str) -> None:
    require_json(data, "result", "PASS", role)
    require_json(data, "target", "tinySA Ultra+ ZS407 / STM32F303", role)
    started = parse_utc(data.get("started_utc"), f"{role} started_utc")
    finished = parse_utc(data.get("finished_utc"), f"{role} finished_utc")
    require(started <= finished, f"{role}: finish precedes start")

    candidate = data.get("candidate")
    require(isinstance(candidate, dict), f"{role}: candidate record missing")
    expected_candidate = {
        "bytes": EXPECTED_CANDIDATE_SIZE,
        "sha256": EXPECTED_CANDIDATE_SHA256,
        "staged_path": "candidate.snapshot.bin",
        "staged_sha256": EXPECTED_CANDIDATE_SHA256,
    }
    for key, item in expected_candidate.items():
        require(candidate.get(key) == item, f"{role}: candidate {key} mismatch")

    tool = data.get("dfu_tool")
    require(isinstance(tool, dict), f"{role}: dfu tool record missing")
    expected_tool = {
        "sha256": EXPECTED_DFU_UTIL_SHA256,
        "bytes": EXPECTED_DFU_UTIL_SIZE,
        "expected_version": EXPECTED_DFU_UTIL_VERSION,
        "staged_path": "dfu-util.snapshot",
    }
    for key, item in expected_tool.items():
        require(tool.get(key) == item, f"{role}: dfu tool {key} mismatch")

    preflight = data.get("preflight")
    require(isinstance(preflight, dict) and preflight.get("pass") is True, f"{role}: DFU preflight failed")
    expected_preflight = {
        "vid": EXPECTED_DFU_VID,
        "pid": EXPECTED_DFU_PID,
        "path": EXPECTED_DFU_LOCATION,
        "serial": EXPECTED_DFU_SERIAL,
        "selected_alt": 0,
        "rejected_alt": 1,
    }
    for key, item in expected_preflight.items():
        require(preflight.get(key) == item, f"{role}: DFU preflight {key} mismatch")
    alternates = preflight.get("alternates")
    require(isinstance(alternates, list) and len(alternates) == 2 and all(isinstance(item, dict) for item in alternates), f"{role}: DFU alternate inventory incomplete")
    by_alt = {item.get("alt"): item for item in alternates}
    require(set(by_alt) == {0, 1}, f"{role}: expected exactly DFU alternates 0 and 1")
    expected_names = {
        0: "@Internal Flash  /0x08000000/128*0002Kg",
        1: "@Option Bytes  /0x1FFFF800/01*016 e",
    }
    for alt, item in by_alt.items():
        require(
            item.get("vid") == EXPECTED_DFU_VID
            and item.get("pid") == EXPECTED_DFU_PID
            and item.get("path") == EXPECTED_DFU_LOCATION
            and item.get("serial") == EXPECTED_DFU_SERIAL
            and item.get("cfg") == 1
            and item.get("intf") == 0
            and item.get("name") == expected_names[alt],
            f"{role}: DFU alternate {alt} identity/name mismatch",
        )

    download = data.get("download")
    require(isinstance(download, dict), f"{role}: download record missing")
    expected_download = {
        "attempt_count": 1,
        "selected_alt": 0,
        "exit_code": 0,
        "pass": True,
        "retry_performed": False,
        "success_markers": ["Download done.", "File downloaded successfully"],
    }
    for key, item in expected_download.items():
        require(download.get(key) == item, f"{role}: download {key} mismatch")
    require_dfu_transfer_argv(download.get("argv"), role, "-D", "0x08000000", "candidate.snapshot.bin")

    readback = data.get("readback")
    require(isinstance(readback, dict), f"{role}: readback record missing")
    expected_readback = {
        "attempt_count": 1,
        "selected_alt": 0,
        "exit_code": 0,
        "bytes": EXPECTED_CANDIDATE_SIZE,
        "sha256": EXPECTED_CANDIDATE_SHA256,
        "exact_byte_match": True,
        "pass": True,
        "retry_performed": False,
        "leave_requested_after_upload": True,
    }
    for key, item in expected_readback.items():
        require(readback.get(key) == item, f"{role}: readback {key} mismatch")
    require_dfu_transfer_argv(
        readback.get("argv"),
        role,
        "-U",
        f"0x08000000:{EXPECTED_CANDIDATE_SIZE}:leave",
        "candidate.readback.bin",
    )

    download_started = parse_utc(download.get("started_utc"), f"{role} download started")
    download_finished = parse_utc(download.get("finished_utc"), f"{role} download finished")
    readback_started = parse_utc(readback.get("started_utc"), f"{role} readback started")
    readback_finished = parse_utc(readback.get("finished_utc"), f"{role} readback finished")
    require(
        started <= download_started <= download_finished <= readback_started <= readback_finished <= finished,
        f"{role}: flash/readback timestamps are not ordered",
    )

    normal = data.get("normal_mode")
    require(isinstance(normal, dict) and normal.get("pass") is True, f"{role}: normal-mode re-enumeration failed")
    require(
        normalize_usb_identity(normal, f"{role} normal mode")
        == (EXPECTED_NORMAL_VID, EXPECTED_NORMAL_PID, EXPECTED_NORMAL_SERIAL, EXPECTED_DFU_LOCATION),
        f"{role}: normal-mode USB identity mismatch",
    )
    binding = data.get("device_byte_binding")
    require(isinstance(binding, dict), f"{role}: device-byte binding record missing")
    expected_binding = {
        "candidate_sha256": EXPECTED_CANDIDATE_SHA256,
        "readback_sha256": EXPECTED_CANDIDATE_SHA256,
        "readback_performed": True,
        "exact_byte_match": True,
    }
    for key, item in expected_binding.items():
        require(binding.get(key) == item, f"{role}: device-byte binding {key} mismatch")


def validate_ab_report(data: Mapping[str, Any], role: str) -> None:
    require_json(data, "pass", True, role)
    require_json(data, "qualification_eligible", True, role)
    require_json(data, "qualification_pass", True, role)
    require_json(data, "diagnostic_reasons", [], role)
    implementation = data.get("implementation")
    expected_implementation = {
        "compare-physical-selftest-captures.py",
        "capture-physical-selftests.py",
        "compare-selftest-visuals.py",
        "Font5x7.c",
    }
    require(isinstance(implementation, dict) and set(implementation) == expected_implementation, f"{role}: implementation provenance incomplete")
    for name, item in implementation.items():
        require(isinstance(item, dict), f"{role}: malformed implementation provenance for {name}")
        require(item.get("path") == f"implementation/{name}" and is_sha256(item.get("sha256")), f"{role}: invalid implementation binding for {name}")
    attestation = data.get("cold_boot_attestation")
    require(isinstance(attestation, dict), f"{role}: cold-boot attestation missing")
    require(attestation.get("schema") == "tinysa-physical-cold-boot-attestation-v1", f"{role}: wrong cold-boot schema")
    require(attestation.get("evidence_type") == "operator-attested", f"{role}: cold boot is not operator-attested")
    require(attestation.get("path") == "operator-attestation/cold-boot.json", f"{role}: cold-boot payload path mismatch")
    require(is_sha256(attestation.get("sha256")), f"{role}: cold-boot payload digest missing")
    reference = data.get("reference")
    candidate = data.get("candidate")
    require(isinstance(reference, dict) and isinstance(candidate, dict), f"{role}: missing A/B endpoints")
    require(reference.get("variant") == "official-c979", f"{role}: wrong reference variant")
    require(candidate.get("variant") == "rc5", f"{role}: wrong candidate variant")
    require(reference.get("expected_version") == EXPECTED_ROLLBACK_VERSION, f"{role}: wrong official version")
    require(candidate.get("expected_version") == EXPECTED_VERSION, f"{role}: wrong candidate version")
    reference_path = reference.get("path")
    candidate_path = candidate.get("path")
    require(isinstance(reference_path, str) and isinstance(candidate_path, str), f"{role}: endpoint paths missing")
    require(reference_path != candidate_path, f"{role}: self-comparison path rejected")
    require(Path(reference_path).expanduser().resolve(strict=False) != Path(candidate_path).expanduser().resolve(strict=False), f"{role}: resolved self-comparison rejected")
    reference_checksums = reference.get("checksums")
    candidate_checksums = candidate.get("checksums")
    require(isinstance(reference_checksums, dict) and reference_checksums.get("pass") is True, f"{role}: reference inventory failed")
    require(isinstance(candidate_checksums, dict) and candidate_checksums.get("pass") is True, f"{role}: candidate inventory failed")
    require(reference_checksums.get("sha256") != candidate_checksums.get("sha256"), f"{role}: identical capture inventories rejected")
    cases = data.get("cases")
    require(isinstance(cases, list) and len(cases) == 14, f"{role}: expected 14 A/B cases")
    require(all(isinstance(case, dict) and case.get("pass") is True for case in cases), f"{role}: an A/B case failed")
    require([case.get("case") for case in cases] == list(range(1, 15)), f"{role}: A/B case sequence is duplicated/incomplete")
    required_checks = {
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
    for number, case in enumerate(cases, 1):
        checks = case.get("checks")
        require(isinstance(checks, list), f"{role} case {number}: checks missing")
        names = [item.get("name") for item in checks if isinstance(item, dict)]
        require(len(names) == len(checks) and len(set(names)) == len(names), f"{role} case {number}: duplicate/malformed checks")
        require(required_checks.issubset(names), f"{role} case {number}: required check set incomplete")
        require(all(item.get("pass") is True for item in checks), f"{role} case {number}: a detailed check failed")


def validate_usb_runtime(data: Mapping[str, Any], role: str) -> None:
    require_json(data, "result", "PASS", role)
    candidate_binding(data, role)
    candidate = data["candidate_binary"]
    if role == "rc5-usb-runtime":
        validate_flash_reference(candidate, role)
        started = parse_utc(data.get("started_utc"), f"{role} started_utc")
        finished = parse_utc(data.get("finished_utc"), f"{role} finished_utc")
        require(started <= finished, f"{role}: finish precedes start")
    for key in ("authentication", "final_identity"):
        identity = data.get(key)
        require(isinstance(identity, dict) and identity.get("pass") is True, f"{role}: {key} failed")
        require(identity.get("version") == EXPECTED_VERSION, f"{role}: {key} version mismatch")
        require(SHA256_RE.fullmatch(str(identity.get("version_response_sha256", ""))) is not None, f"{role}: {key} response digest missing")
    authentication = data["authentication"]
    require(authentication.get("wire_reassembled_ascii") == "version\\r", f"{role}: fragmented version command mismatch")
    series = data.get("frame_series")
    require(isinstance(series, dict) and series.get("complete_frames", 0) >= 2, f"{role}: insufficient complete frames")
    require(series.get("distinct_frame_hashes", 0) >= 2, f"{role}: framebuffer did not change")
    frames = data.get("frames")
    require(isinstance(frames, list) and len(frames) == series.get("complete_frames"), f"{role}: frame records are incomplete")
    require([frame.get("index") for frame in frames] == list(range(1, len(frames) + 1)), f"{role}: frame indices are incomplete")
    frame_hashes: set[str] = set()
    for frame in frames:
        require(frame.get("bytes") == 307_200, f"{role}: truncated frame")
        require(frame.get("nonblack_pixels", 0) >= 400 and frame.get("unique_rgb565_colors", 0) >= 2, f"{role}: empty frame")
        require(SHA256_RE.fullmatch(str(frame.get("sha256", ""))) is not None, f"{role}: frame digest missing")
        frame_hashes.add(frame["sha256"])
    require(len(frame_hashes) == series.get("distinct_frame_hashes"), f"{role}: distinct-frame summary mismatch")
    require(series.get("total_bytes") == len(frames) * 307_200, f"{role}: total frame byte count mismatch")
    validate_config_integrity(data.get("persisted_config_integrity"), role)
    runtime = data.get("runtime_observations")
    require(isinstance(runtime, dict), f"{role}: runtime observations missing")
    require(runtime.get("acquisition_state") == "Resumed", f"{role}: acquisition not resumed")
    require(runtime.get("frequency_points") == 450, f"{role}: wrong frequency count")
    require(runtime.get("frequency_start_hz") == 0 and runtime.get("frequency_stop_hz") == 900_000_000, f"{role}: wrong frequency span")
    require(set(runtime.get("required_threads", [])) == {"main", "idle", "sweep", "shell"}, f"{role}: required thread set missing")
    responses = runtime.get("response_sha256")
    require(isinstance(responses, dict) and set(runtime.get("commands", [])) == set(responses), f"{role}: runtime response inventory mismatch")
    require(all(SHA256_RE.fullmatch(str(value)) for value in responses.values()), f"{role}: invalid runtime response digest")
    if role == "rc5-usb-runtime":
        expected_commands = ["frequencies", "trace", "trace 1 value", "data 2", "sweeptime", "status", "threads"]
        require(runtime.get("commands") == expected_commands, f"{role}: corrected TRACE_ACTUAL command sequence mismatch")
        require(runtime.get("data_2_points") == 450, f"{role}: data 2 did not return a complete TRACE_ACTUAL plane")
        delta = runtime.get("data_trace_maximum_delta_db")
        require(
            isinstance(delta, (int, float))
            and not isinstance(delta, bool)
            and 0.0 <= float(delta) <= 0.011,
            f"{role}: data 2 was not numerically bound to trace 1",
        )
        metrics = runtime.get("trace_1_metrics")
        require(
            isinstance(metrics, dict)
            and metrics.get("points") == 450
            and metrics.get("finite") == 450,
            f"{role}: trace 1 metrics are incomplete",
        )
        interior = runtime.get("trace_1_interior_range_db")
        robust = runtime.get("trace_1_robust_range_db")
        require(
            isinstance(interior, (int, float))
            and not isinstance(interior, bool)
            and float(interior) >= 0.10
            and isinstance(robust, (int, float))
            and not isinstance(robust, bool)
            and float(robust) >= 0.25,
            f"{role}: TRACE_ACTUAL observation is flat or invalid",
        )


def validate_reset_retention(data: Mapping[str, Any], role: str) -> None:
    require_json(data, "result", "PASS", role)
    candidate_binding(data, role)
    validate_flash_reference(data["candidate_binary"], role)
    arguments = data.get("arguments")
    require(isinstance(arguments, dict), f"{role}: capture arguments missing")
    require(arguments.get("expected_version") == EXPECTED_VERSION, f"{role}: expected version mismatch")
    require(arguments.get("expected_usb_serial") == EXPECTED_NORMAL_SERIAL, f"{role}: expected USB serial mismatch")
    require(arguments.get("expected_usb_location") == EXPECTED_DFU_LOCATION, f"{role}: expected USB location mismatch")
    started = parse_utc(data.get("started_utc"), f"{role} started_utc")
    finished = parse_utc(data.get("finished_utc"), f"{role} finished_utc")
    require(started <= finished, f"{role}: finish precedes start")
    retention = data.get("retention")
    require(isinstance(retention, dict) and retention.get("pass") is True, f"{role}: retention failed")
    for key in (
        "same_frequency_grid",
        "same_info_response",
        "same_sweep_configuration",
        "same_usb_identity",
        "same_version_response",
        "sweep_performance_retained",
    ):
        require(retention.get(key) is True, f"{role}: {key} failed")
    for key in (
        "reset_attempted_exactly_once",
        "reset_wire_write_completed",
        "reset_transport_disconnect_observed",
    ):
        require(retention.get(key) is True, f"{role}: {key} failed")
    require(retention.get("config_mismatches") == [], f"{role}: config changed across reset")
    reset = data.get("reset")
    require(isinstance(reset, dict), f"{role}: raw reset record missing")
    require(
        reset.get("attempted_count") == 1
        and reset.get("sent_count") == 1
        and reset.get("wire_hex") == "72657365740d"
        and reset.get("wire_write_completed") is True
        and reset.get("transport_disconnect_observed") is True,
        f"{role}: reset was not sent exactly once with a physical transport disconnect",
    )
    require(SHA256_RE.fullmatch(str(reset.get("response_sha256", ""))) is not None, f"{role}: reset response digest missing")
    require(isinstance(reset.get("attempted_utc"), str) and isinstance(reset.get("transport_completed_utc"), str), f"{role}: reset timing record missing")
    before = data.get("before")
    after = data.get("after")
    require(isinstance(before, dict) and isinstance(after, dict), f"{role}: before/after records missing")
    for phase, observation in (("before", before), ("after", after)):
        require(observation.get("status") == "Resumed", f"{role}: {phase} acquisition not resumed")
        require(observation.get("frequency_points") == 450, f"{role}: {phase} frequency grid incomplete")
        require(observation.get("frequency_start_hz") == 0 and observation.get("frequency_stop_hz") == 900_000_000, f"{role}: {phase} frequency span mismatch")
        frame = observation.get("frame")
        require(isinstance(frame, dict) and frame.get("bytes") == 307_200, f"{role}: {phase} frame missing")
        require(frame.get("nonblack_pixels", 0) >= 400 and frame.get("unique_rgb565_colors", 0) >= 2, f"{role}: {phase} frame empty")
        for key in ("frequency_sha256", "info_sha256", "sweep_configuration_sha256", "version_sha256"):
            require(SHA256_RE.fullmatch(str(observation.get(key, ""))) is not None, f"{role}: {phase} {key} missing")
        config = observation.get("config_sha256")
        require(
            isinstance(config, dict)
            and set(config) == CONFIG_COMMANDS
            and all(is_sha256(item) for item in config.values()),
            f"{role}: {phase} config record incomplete",
        )
    require(before["config_sha256"] == after["config_sha256"], f"{role}: config changed across reset")
    require(isinstance(data.get("port_history"), list) and len(data["port_history"]) >= 1, f"{role}: reconnect port history missing")


def validate_manual_controls(data: Mapping[str, Any], role: str) -> None:
    require_json(data, "result", "PASS", role)
    candidate = data.get("candidate")
    require(isinstance(candidate, dict), f"{role}: candidate binding missing")
    require(candidate.get("binary_sha256") == EXPECTED_CANDIDATE_SHA256, f"{role}: candidate hash mismatch")
    require(candidate.get("version") == EXPECTED_VERSION, f"{role}: candidate version mismatch")
    attestation = data.get("operator_attestation")
    require(isinstance(attestation, dict) and attestation.get("response") == "Passed", f"{role}: operator did not attest PASS")
    checks = attestation.get("checks")
    expected_checks = [
        "physical resistive touch opened the right-side menu from blank plot space",
        "physical touch on blank plot space left of the menu closed it",
        "physical jog press opened the menu",
        "one clockwise detent moved the highlight",
        "one counterclockwise detent moved the highlight",
        "blank plot touch exited without selecting or saving a menu item",
    ]
    require(checks == expected_checks, f"{role}: manual check semantics incomplete or altered")


VALIDATORS: dict[str, Callable[[Mapping[str, Any], str], None]] = {
    "rc5_selftest": lambda data, role: validate_selftest(data, role, "rc5", EXPECTED_VERSION),
    "official_selftest": lambda data, role: validate_selftest(data, role, "official-c979", EXPECTED_ROLLBACK_VERSION),
    "cal_disconnected": lambda data, role: validate_negative(data, role, False),
    "cal_reconnected": lambda data, role: validate_negative(data, role, True),
    "ab_report": validate_ab_report,
    "dfu_flash": validate_dfu_flash,
    "usb_runtime": validate_usb_runtime,
    "reset_retention": validate_reset_retention,
    "manual_controls": validate_manual_controls,
}


def validate_evidence(spec: EvidenceSpec, root: Path, repository_path: str) -> VerifiedEvidence:
    inventory_bytes, inventory = verify_inventory(root, spec.inventory_sha256)
    require(inventory.get(spec.primary_file) == spec.primary_sha256, f"{spec.role}: primary artifact is not bound by inventory")
    primary_bytes = read_regular_file(root.joinpath(*PurePosixPath(spec.primary_file).parts), MAX_TEXT_BYTES)
    require(sha256_bytes(primary_bytes) == spec.primary_sha256, f"{spec.role}: primary artifact trust-root mismatch")
    primary = parse_json_object(primary_bytes, f"{spec.role}/{spec.primary_file}")
    require_json(primary, "schema", spec.schema, spec.role)
    validator = VALIDATORS.get(spec.validator)
    require(validator is not None, f"{spec.role}: unknown semantic validator")
    assert validator is not None
    validator(primary, spec.role)
    validate_evidence_inventory_links(spec, inventory, primary, root)
    return VerifiedEvidence(spec, repository_path, root, inventory_bytes, inventory, primary)


def require_inventory_link(inventory: Mapping[str, str], name: str, digest_value: Any, role: str) -> None:
    require(SHA256_RE.fullmatch(str(digest_value or "")) is not None, f"{role}: invalid digest for {name}")
    require(inventory.get(name) == digest_value, f"{role}: {name} is not bound to its recorded digest")


def config_artifact_name(prefix: str, command: str) -> str:
    return f"{prefix}-{command.replace(' ', '-')}" + ".txt"


def runtime_response_artifact(command: str) -> str:
    if command.startswith("data ") and command[5:].isdigit():
        return f"runtime-data-{command[5:]}.txt"
    if command.startswith("trace ") and command.endswith(" value"):
        middle = command[6:-6]
        if middle.isdigit():
            return f"runtime-trace-{middle}-value.txt"
    return f"runtime-{command.replace(' ', '-')}.txt"


def validate_case_inventory(inventory: Mapping[str, str], case: Mapping[str, Any], number: int, role: str) -> None:
    stem = f"case-{number:02d}"
    require_inventory_link(inventory, f"{stem}.rgb565be", case["display"]["sha256"], role)
    require_inventory_link(inventory, f"{stem}.rgb565", case.get("comparator_rgb565_sha256"), role)
    require_inventory_link(inventory, f"{stem}.png", case.get("png_sha256"), role)
    require_inventory_link(inventory, f"{stem}-measured.f32le", case["shell_evidence"]["trace_dump_sha256"], role)
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
        require(f"{stem}-shell/{name}" in inventory, f"{role}: missing raw shell artifact {stem}-shell/{name}")


def validate_persisted_config_inventory(
    inventory: Mapping[str, str], integrity: Mapping[str, Any], role: str
) -> None:
    for phase in ("before", "after"):
        for command, item_digest in integrity[f"{phase}_sha256"].items():
            name = f"persisted-config/{phase}-{command.replace(' ', '-')}" + ".txt"
            require_inventory_link(inventory, name, item_digest, role)


def validate_evidence_inventory_links(
    spec: EvidenceSpec, inventory: Mapping[str, str], primary: Mapping[str, Any], root: Path
) -> None:
    role = spec.role
    if spec.validator in {"rc5_selftest", "official_selftest"}:
        for number, case in enumerate(primary["cases"], 1):
            validate_case_inventory(inventory, case, number, role)
        for name in ("device-info-before.txt", "device-info-after.txt", "device-version-before.txt", "device-version-after.txt", "run.log", "run-transcript.md"):
            require(name in inventory, f"{role}: missing capture artifact {name}")
        validate_persisted_config_inventory(inventory, primary["persisted_config_integrity"], role)
    elif spec.validator in {"cal_disconnected", "cal_reconnected"}:
        validate_case_inventory(inventory, primary["cases"][0], 3, role)
        for name in ("device-info-before.txt", "device-info-after.txt", "device-version-before.txt", "device-version-after.txt", "run.log", "run-transcript.md"):
            require(name in inventory, f"{role}: missing capture artifact {name}")
        validate_persisted_config_inventory(inventory, primary["persisted_config_integrity"], role)
    elif spec.validator == "dfu_flash":
        expected = {
            "candidate.readback.bin",
            "candidate.snapshot.bin",
            "dfu-util-download.stderr.txt",
            "dfu-util-download.stdout.txt",
            "dfu-util-list.stderr.txt",
            "dfu-util-list.stdout.txt",
            "dfu-util-readback.stderr.txt",
            "dfu-util-readback.stdout.txt",
            "dfu-util-version.stderr.txt",
            "dfu-util-version.stdout.txt",
            "dfu-util.snapshot",
            "run.json",
        }
        require(set(inventory) == expected, f"{role}: flash evidence inventory is incomplete or unexpected")
        require(inventory["candidate.snapshot.bin"] == EXPECTED_CANDIDATE_SHA256, f"{role}: staged candidate hash mismatch")
        require(inventory["candidate.readback.bin"] == EXPECTED_CANDIDATE_SHA256, f"{role}: readback hash mismatch")
        require(inventory["dfu-util.snapshot"] == EXPECTED_DFU_UTIL_SHA256, f"{role}: dfu-util snapshot hash mismatch")
        candidate_snapshot = read_regular_file(root / "candidate.snapshot.bin")
        candidate_readback = read_regular_file(root / "candidate.readback.bin")
        dfu_snapshot = read_regular_file(root / "dfu-util.snapshot")
        require(len(candidate_snapshot) == EXPECTED_CANDIDATE_SIZE, f"{role}: staged candidate size mismatch")
        require(len(candidate_readback) == EXPECTED_CANDIDATE_SIZE, f"{role}: readback size mismatch")
        require(candidate_snapshot == candidate_readback, f"{role}: readback bytes differ from staged candidate")
        require(len(dfu_snapshot) == EXPECTED_DFU_UTIL_SIZE, f"{role}: dfu-util snapshot size mismatch")

        def raw_text(stem: str) -> str:
            payload = b"".join(
                read_regular_file(root / f"{stem}.{stream}.txt", MAX_TEXT_BYTES, allow_empty=True)
                for stream in ("stdout", "stderr")
            )
            try:
                return payload.decode("utf-8")
            except UnicodeDecodeError as error:
                raise BundleError(f"{role}: {stem} transcript is not UTF-8") from error

        version_text = raw_text("dfu-util-version")
        version_lines = version_text.splitlines()
        require(bool(version_lines) and version_lines[0].strip() == EXPECTED_DFU_UTIL_VERSION, f"{role}: sealed dfu-util version transcript mismatch")
        listing_text = raw_text("dfu-util-list")
        for marker in (
            "Found DFU: [0483:df11]",
            "cfg=1, intf=0",
            f'path="{EXPECTED_DFU_LOCATION}"',
            f'serial="{EXPECTED_DFU_SERIAL}"',
            'alt=0, name="@Internal Flash  /0x08000000/128*0002Kg"',
            'alt=1, name="@Option Bytes  /0x1FFFF800/01*016 e"',
        ):
            require(marker in listing_text, f"{role}: DFU listing transcript lacks {marker!r}")
        require(listing_text.count("Found DFU: [") == 2, f"{role}: DFU listing contains an unexpected interface/device")
        require(listing_text.count("cfg=1, intf=0") == 2, f"{role}: DFU listing config/interface count mismatch")
        download_text = raw_text("dfu-util-download")
        require("Download done." in download_text and "File downloaded successfully" in download_text, f"{role}: sealed download transcript lacks success markers")
        readback_text = raw_text("dfu-util-readback")
        require("Upload done." in readback_text, f"{role}: sealed readback transcript lacks upload success marker")
    elif spec.validator == "ab_report":
        expected = {"report.json", "report.md", "contact-cases-01-07.png", "contact-cases-08-14.png"}
        expected.update(f"case-{number:02d}-diff.png" for number in range(1, 15))
        expected.update(f"implementation/{name}" for name in primary["implementation"])
        expected.add("operator-attestation/cold-boot.json")
        require(set(inventory) == expected, f"{role}: A/B output inventory is incomplete or unexpected")
        for name, item in primary["implementation"].items():
            require_inventory_link(inventory, f"implementation/{name}", item.get("sha256"), role)
        attestation = primary["cold_boot_attestation"]
        require_inventory_link(inventory, attestation["path"], attestation.get("sha256"), role)
        try:
            document = parse_json_object(
                read_regular_file(root / attestation["path"], MAX_TEXT_BYTES),
                f"{role} cold-boot attestation",
            )
        except KeyError as error:
            raise BundleError(f"{role}: malformed cold-boot attestation summary") from error
        require(document.get("schema") == "tinysa-physical-cold-boot-attestation-v1", f"{role}: attestation document schema mismatch")
        require(document.get("evidence_type") == "operator-attested", f"{role}: attestation evidence type mismatch")
        require(document.get("cal_rf_fixture") == "CAL-RF-LOOPBACK-CONNECTED", f"{role}: attestation fixture mismatch")
        events = document.get("events")
        require(isinstance(events, list) and len(events) == 2 and all(isinstance(item, dict) for item in events), f"{role}: attestation events incomplete")
        by_event_role = {item.get("role"): item for item in events}
        require(set(by_event_role) == {"reference", "candidate"}, f"{role}: attestation event roles incomplete")
        for event_role, endpoint in (("reference", primary["reference"]), ("candidate", primary["candidate"])):
            event = by_event_role[event_role]
            require(event.get("variant") == endpoint["variant"], f"{role}: {event_role} attestation variant mismatch")
            require(event.get("expected_version") == endpoint["expected_version"], f"{role}: {event_role} attestation version mismatch")
            require(event.get("capture_inventory_sha256") == endpoint["checksums"]["sha256"], f"{role}: {event_role} attestation inventory mismatch")
            require(event.get("usb_location") == "0-1" and event.get("boot_mode") == "normal", f"{role}: {event_role} boot path mismatch")
            require(event.get("operator_confirmed") is True, f"{role}: {event_role} boot was not confirmed")
            seconds = event.get("minimum_power_off_seconds")
            require(isinstance(seconds, (int, float)) and not isinstance(seconds, bool) and seconds >= 5, f"{role}: {event_role} power-off interval insufficient")
    elif spec.validator == "usb_runtime":
        require_inventory_link(
            inventory,
            "device-version-fragmented.txt",
            primary["authentication"].get("version_response_sha256"),
            role,
        )
        require_inventory_link(
            inventory,
            "device-version-final.txt",
            primary["final_identity"].get("version_response_sha256"),
            role,
        )
        for frame in primary["frames"]:
            require_inventory_link(inventory, f"frame-{frame['index']:02d}.rgb565be", frame.get("sha256"), role)
        integrity = primary["persisted_config_integrity"]
        for prefix, digests in (("config-before", integrity["before_sha256"]), ("config-after", integrity["after_sha256"])):
            for command, item_digest in digests.items():
                require_inventory_link(inventory, config_artifact_name(prefix, command), item_digest, role)
        for command, item_digest in primary["runtime_observations"]["response_sha256"].items():
            require_inventory_link(inventory, runtime_response_artifact(command), item_digest, role)
        for name in ("run.log", "run-transcript.md"):
            require(name in inventory, f"{role}: missing runtime artifact {name}")
    elif spec.validator == "reset_retention":
        require_inventory_link(inventory, "reset-reset.txt", primary["reset"].get("response_sha256"), role)
        try:
            reset_transport = read_regular_file(root / "reset-reset.txt", 16 * 1024).decode("utf-8")
        except UnicodeDecodeError as error:
            raise BundleError(f"{role}: reset transport record is not UTF-8") from error
        require("transport ended after reset:" in reset_transport, f"{role}: reset transport did not disconnect")
        require("Device not configured" in reset_transport, f"{role}: expected physical transport-end marker missing")
        for phase in ("before", "after"):
            observation = primary[phase]
            require_inventory_link(inventory, f"{phase}-frame.rgb565be", observation["frame"].get("sha256"), role)
            require_inventory_link(inventory, f"{phase}-frequencies.txt", observation.get("frequency_sha256"), role)
            require_inventory_link(inventory, f"{phase}-info.txt", observation.get("info_sha256"), role)
            require_inventory_link(inventory, f"{phase}-sweep.txt", observation.get("sweep_configuration_sha256"), role)
            require_inventory_link(inventory, f"{phase}-version.txt", observation.get("version_sha256"), role)
            for command, item_digest in observation["config_sha256"].items():
                require_inventory_link(inventory, config_artifact_name(phase, command), item_digest, role)
        for name in ("before-connect.txt", "after-connect.txt", "before-status.txt", "after-status.txt", "run.log", "run-transcript.md"):
            require(name in inventory, f"{role}: missing reset artifact {name}")


def validate_cross_evidence(evidence: Mapping[str, VerifiedEvidence]) -> None:
    rc5 = evidence["rc5-all-14-selftests"]
    official = evidence["official-c979-all-14-selftests"]
    ab = evidence["official-c979-vs-rc5-ab"].primary
    reference = ab["reference"]
    candidate = ab["candidate"]
    require(
        reference["checksums"].get("sha256") == official.spec.inventory_sha256,
        "A/B reference is not bound to the verified official capture",
    )
    require(
        candidate["checksums"].get("sha256") == rc5.spec.inventory_sha256,
        "A/B candidate is not bound to the verified RC5 capture",
    )
    for field in ("started_utc", "finished_utc"):
        left = rc5.primary.get(field)
        right = official.primary.get(field)
        require(isinstance(left, str) and isinstance(right, str), f"A/B captures lack {field}")
        require(left != right, f"A/B captures have identical {field}; self-comparison rejected")
    ab_evidence = evidence["official-c979-vs-rc5-ab"]
    attestation_path = ab["cold_boot_attestation"]["path"]
    attestation_document = parse_json_object(
        read_regular_file(ab_evidence.root / attestation_path, MAX_TEXT_BYTES),
        "A/B cold-boot attestation",
    )
    attestation_events = {
        item["role"]: item for item in attestation_document["events"] if isinstance(item, dict) and "role" in item
    }
    for event_role, capture in (("reference", official.primary), ("candidate", rc5.primary)):
        require(
            attestation_events[event_role].get("capture_started_utc") == capture.get("started_utc"),
            f"A/B {event_role} cold-boot attestation timestamp mismatch",
        )
    rc5_usb = rc5.primary.get("usb_identity")
    official_usb = official.primary.get("usb_identity")
    require(isinstance(rc5_usb, dict) and isinstance(official_usb, dict), "A/B captures lack USB identities")
    require(rc5_usb.get("location") == official_usb.get("location"), "A/B captures were not made at the same USB location")

    flash = evidence["rc5-dfu-flash-readback"]
    usb_runtime = evidence["rc5-usb-runtime"]
    reset_retention = evidence["rc5-reset-retention"]
    flash_finished = parse_utc(flash.primary.get("finished_utc"), "flash evidence finished_utc")
    usb_started = parse_utc(usb_runtime.primary.get("started_utc"), "USB runtime started_utc")
    usb_finished = parse_utc(usb_runtime.primary.get("finished_utc"), "USB runtime finished_utc")
    reset_started = parse_utc(reset_retention.primary.get("started_utc"), "reset retention started_utc")
    reset_finished = parse_utc(reset_retention.primary.get("finished_utc"), "reset retention finished_utc")
    require(
        flash_finished <= usb_started <= usb_finished <= reset_started <= reset_finished,
        "flash, USB runtime, and reset-retention evidence is not chronologically ordered",
    )
    require(reset_finished - flash_finished <= timedelta(hours=24), "flash-bound runtime evidence is unreasonably remote from the flash session")
    for label, record in (("USB runtime", usb_runtime), ("reset retention", reset_retention)):
        candidate_record = record.primary.get("candidate_binary")
        require(isinstance(candidate_record, dict), f"{label}: candidate binding missing")
        reference_record = candidate_record.get("flash_evidence")
        require(isinstance(reference_record, dict), f"{label}: flash evidence link missing")
        require(
            reference_record.get("inventory_sha256") == flash.spec.inventory_sha256,
            f"{label}: flash inventory link does not match pinned flash evidence",
        )
        require(
            reference_record.get("run_json_sha256") == flash.spec.primary_sha256,
            f"{label}: flash run link does not match pinned flash evidence",
        )

    disconnected = evidence["rc5-cal-disconnected-negative"].primary
    reconnected = evidence["rc5-cal-reconnected-recovery"].primary
    require(disconnected.get("started_utc") != reconnected.get("started_utc"), "CAL disconnect/recovery captures are not independent")
    require(disconnected.get("usb_identity") == reconnected.get("usb_identity"), "CAL recovery is not bound to the same USB unit")

    expected_identity = (0x0483, 0x5740, "706", "0-1")
    identity_records = {
        "RC5 self-test": rc5.primary.get("usb_identity"),
        "CAL disconnected": disconnected.get("usb_identity"),
        "CAL reconnected": reconnected.get("usb_identity"),
        "flash normal mode": flash.primary.get("normal_mode"),
        "USB runtime authentication": evidence["rc5-usb-runtime"].primary.get("authentication", {}).get("usb_identity"),
        "USB runtime final identity": evidence["rc5-usb-runtime"].primary.get("final_identity", {}).get("usb_identity"),
        "reset before": evidence["rc5-reset-retention"].primary.get("before", {}).get("usb_identity"),
        "reset after": evidence["rc5-reset-retention"].primary.get("after", {}).get("usb_identity"),
        "manual controls": evidence["rc5-manual-controls"].primary.get("usb_identity"),
        "post-controls authentication": evidence["rc5-post-controls-readonly"].primary.get("authentication", {}).get("usb_identity"),
        "post-controls final identity": evidence["rc5-post-controls-readonly"].primary.get("final_identity", {}).get("usb_identity"),
    }
    for label, identity in identity_records.items():
        require(normalize_usb_identity(identity, label) == expected_identity, f"{label}: wrong physical USB unit/path")

    manual = evidence["rc5-manual-controls"]
    post_controls = evidence["rc5-post-controls-readonly"]
    post_link = manual.primary.get("post_control_read_only_evidence")
    require(isinstance(post_link, dict), "manual controls: post-control evidence link missing")
    require(post_link.get("result") == "PASS", "manual controls: linked post-control evidence did not pass")
    require(
        post_link.get("sha256sums_sha256") == post_controls.spec.inventory_sha256,
        "manual controls: linked post-control inventory hash mismatch",
    )
    require(
        post_link.get("run_json_sha256") == post_controls.spec.primary_sha256,
        "manual controls: linked post-control run hash mismatch",
    )
    raw_link = post_link.get("path")
    require(isinstance(raw_link, str) and "\\" not in raw_link, "manual controls: invalid post-control path")
    linked_path = posixpath.normpath(f"{manual.repository_path}/{raw_link}")
    require(not linked_path.startswith("../") and not linked_path.startswith("/"), "manual controls: post-control path escapes repository")
    require(linked_path == post_controls.repository_path, "manual controls: post-control path points to different evidence")


def normalize_usb_identity(value: Any, label: str) -> tuple[int, int, str, str]:
    require(isinstance(value, dict), f"{label}: USB identity missing")

    def number(item: Any, field: str) -> int:
        if isinstance(item, int) and not isinstance(item, bool):
            return item
        if isinstance(item, str):
            try:
                return int(item, 0)
            except ValueError:
                pass
        raise BundleError(f"{label}: invalid USB {field}")

    serial = value.get("serial_number")
    location = value.get("location")
    require(isinstance(serial, (str, int)) and not isinstance(serial, bool), f"{label}: invalid USB serial")
    require(isinstance(location, str), f"{label}: invalid USB location")
    return number(value.get("vid"), "VID"), number(value.get("pid"), "PID"), str(serial), location


def semantic_scope(spec: EvidenceSpec) -> str:
    if spec.role == "rc5-usb-runtime":
        return "PASS: exact-readback-bound CDC identity, complete changing frames, TRACE_ACTUAL/data-2 parity, resumed acquisition, and config integrity"
    if spec.role == "rc5-post-controls-readonly":
        return "PASS: historical exact-version-bound post-control read-only identity/runtime/config observation"
    scopes = {
        "rc5_selftest": "PASS: all 14 physical self-tests, visible traces, and config integrity",
        "official_selftest": "PASS: all 14 official physical self-tests and config integrity",
        "cal_disconnected": "PASS: bounded disconnected-CAL negative branch",
        "cal_reconnected": "PASS: same-unit CAL recovery branch",
        "ab_report": "PASS: qualification-eligible official-vs-RC5 visual/trace A/B; single-sweep SFDR remains diagnostic",
        "dfu_flash": "PASS: exact admitted RC5 image-range download and same-device DFU readback",
        "usb_runtime": "PASS: CDC identity, complete changing frames, resumed acquisition, and config integrity",
        "reset_retention": "PASS: exact-readback-bound one-reset same-unit runtime/config retention",
        "manual_controls": "PASS: operator-attested touch and jog controls",
    }
    require(spec.validator in scopes, f"{spec.role}: missing semantic scope")
    return scopes[spec.validator]


def evidence_binding_scope(spec: EvidenceSpec) -> str:
    if spec.validator == "dfu_flash":
        return "exact candidate image range bound by same-device DFU readback"
    if spec.role in {"rc5-usb-runtime", "rc5-reset-retention"}:
        return "exact-readback-bound through pinned flash inventory and run hashes"
    return "historical exact-version-bound; cryptographic inventory authenticated"


def evidence_overrides(values: Iterable[str]) -> dict[str, str]:
    allowed = {spec.role for spec in EVIDENCE_SPECS}
    result: dict[str, str] = {}
    for value in values:
        require("=" in value, "--evidence must be ROLE=REPOSITORY_RELATIVE_PATH")
        role, path = value.split("=", 1)
        require(role in allowed, f"unknown evidence role: {role}")
        require(role not in result, f"duplicate evidence role: {role}")
        validate_relative_path(path, f"evidence {role}")
        result[role] = path
    return result


def render_report(evidence: Iterable[VerifiedEvidence]) -> bytes:
    lines = [
        "# tinySA RC5 physical qualification report",
        "",
        f"Status: `{QUALIFICATION_STATUS}`",
        "",
        "The exact local RC5 F303/ZS407 image was downloaded to the admitted device and the same 193,980-byte ",
        "flash range was read back byte-for-byte. Fresh USB/runtime and reset-retention records link the exact ",
        "flash inventory and run hashes, then authenticate the expected version on the same USB path. ",
        "It is **not fully hardware-qualified**: physical PSP/MSP forced-fault injection remains pending, ",
        "and this bundle records no waiver.",
        "",
        "That exact-byte claim is deliberately bounded. It covers the candidate image range and the fresh linked ",
        "USB/reset runs; it does not inspect flash bytes beyond the 193,980-byte image and does not retroactively ",
        "byte-bind the earlier self-test, A/B, negative-path, or manual-control observations. Those historical ",
        "records remain exact-version-bound. The A/B inventory seals an operator cold-boot attestation, not an ",
        "electrical measurement of supply removal. The corrected USB run establishes data 2 (TRACE_ACTUAL) parity ",
        "with trace 1 within its recorded tolerance. Spur persistence remains non-gating diagnostic work and does ",
        "not close the pending physical fault gate.",
        "",
        "The original simulation-qualified release directory was read and authenticated but not changed. ",
        "Its original `hardware_qualified=false` statement remains authoritative for that sealed package.",
        "",
        "## Authenticated physical-evidence references (payloads not included)",
        "",
        "This is not a self-contained evidence archive. It copies the authenticated inventory for each ",
        "evidence tree, not the referenced screenshots, traces, logs, or JSON payloads. Auditing or re-hashing ",
        "those payloads requires the named repository artifact directories.",
        "",
    ]
    for item in evidence:
        lines.append(
            f"- `{item.spec.role}`: `{item.repository_path}`; "
            f"SHA256SUMS `{item.spec.inventory_sha256}`; "
            f"{item.spec.primary_file} `{item.spec.primary_sha256}`"
        )
    lines.extend(
        [
            "",
            "## Remaining gate",
            "",
            "- Physical PSP-origin and nested-MSP forced-fault behavior has not been exercised on the device.",
            "- Executable-twin fault tests do not silently waive that physical gate.",
            "- No option in the packager can convert this bundle to full qualification or add a waiver.",
            "",
        ]
    )
    return "\n".join(lines).encode("utf-8")


def render_installation_boundary() -> bytes:
    text = f"""tinySA RC5 qualification-evidence archive

QUALIFICATION STATUS: {QUALIFICATION_STATUS}
FULL HARDWARE QUALIFICATION: NO (physical fault injection remains pending)

Target: tinySA Ultra+ ZS407 / STM32F303 only
Candidate: firmware/{EXPECTED_CANDIDATE_NAME}
Candidate SHA-256: {EXPECTED_CANDIDATE_SHA256}
Rollback: firmware/{EXPECTED_ROLLBACK_NAME}
Rollback SHA-256: {EXPECTED_ROLLBACK_SHA256}

This bundle preserves authenticated historical build and qualification facts.
It is not a current installation bundle and grants no write authority. Its raw
candidate predates the strict tinysa-flasher-build-v1.json custom-build
manifest, so standalone Atom-Flasher must reject it as a new custom target.
The qualification status above must not be interpreted as current artifact
admission or as a waiver of the pending physical fault-injection gate.

All new firmware installation is owned exclusively by standalone
../Atom-Flasher. For a current custom build:

1. Build a clean committed F303/ZS407 Phase 6 image with
   tools/package-flasher-build.sh.
2. In Atom-Flasher, select the emitted tinysa-flasher-build-v2.json manifest,
   not a raw BIN.
3. Let Atom-Flasher perform artifact admission, exact device preflight,
   native confirmation, the physical write, durable recovery journaling, and
   post-reboot continuity verification.

Do not use the retired Firmware-side physical-writer path or a direct device
utility. Use Atom-Flasher's pinned OEM target when restoring the official
{EXPECTED_ROLLBACK_VERSION} release. Repeating the legacy RC5 candidate would
require a reviewed manifest migration or a new reproducible manifested build;
this evidence archive intentionally provides neither shortcut.

Do not use either image on F072 hardware. No F072 binary is included.
"""
    return text.encode("utf-8")


def open_child_directory(parent_descriptor: int, name: str, *, create: bool) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    if create:
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent_descriptor)
        except FileExistsError:
            pass
    try:
        return os.open(name, flags, dir_fd=parent_descriptor)
    except OSError as error:
        raise BundleError(f"cannot safely open output directory component {name!r}: {error}") from error


def reserve_output_directory(repository_root: Path, relative: str) -> tuple[Path, int]:
    pure = validate_relative_path(relative, "output")
    root_descriptor = os.open(
        repository_root,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        current = os.dup(root_descriptor)
        try:
            for part in pure.parts[:-1]:
                next_descriptor = open_child_directory(current, part, create=True)
                os.close(current)
                current = next_descriptor
            leaf = pure.parts[-1]
            try:
                os.mkdir(leaf, mode=0o700, dir_fd=current)
            except FileExistsError as error:
                raise BundleError(f"output already exists: {relative}") from error
            output_descriptor = open_child_directory(current, leaf, create=False)
            os.fsync(current)
        finally:
            os.close(current)
    finally:
        os.close(root_descriptor)
    return repository_root.joinpath(*pure.parts), output_descriptor


def write_file_at(root_descriptor: int, relative: str, value: bytes) -> None:
    pure = validate_relative_path(relative, "bundle member")
    current = os.dup(root_descriptor)
    try:
        for part in pure.parts[:-1]:
            next_descriptor = open_child_directory(current, part, create=True)
            os.close(current)
            current = next_descriptor
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(pure.parts[-1], flags, 0o600, dir_fd=current)
        try:
            view = memoryview(value)
            while view:
                written = os.write(descriptor, view)
                require(written > 0, f"write made no progress: {relative}")
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.fsync(current)
    finally:
        os.close(current)


def create_bundle(
    repository_root: Path,
    source_release: str,
    evidence_paths: Mapping[str, str],
    output: str,
) -> Path:
    repository_root = repository_root.resolve(strict=True)
    require(repository_root.is_dir(), "repository root is not a directory")
    require(
        not RELEASE_INPUT_BLOCKERS,
        "release input refresh pending: " + "; ".join(RELEASE_INPUT_BLOCKERS),
    )
    source_root = resolve_repository_input(repository_root, source_release, "source release")
    require(source_root.is_dir(), "source release is not a directory")
    source = validate_source_release(source_root)

    verified: list[VerifiedEvidence] = []
    for spec in EVIDENCE_SPECS:
        repository_path = evidence_paths.get(spec.role, spec.default_path)
        root = resolve_repository_input(repository_root, repository_path, f"evidence {spec.role}")
        require(root.is_dir(), f"evidence {spec.role} is not a directory")
        verified.append(validate_evidence(spec, root, repository_path))
    by_role = {item.spec.role: item for item in verified}
    validate_cross_evidence(by_role)
    flash_root = by_role["rc5-dfu-flash-readback"].root
    require(
        read_regular_file(flash_root / "candidate.snapshot.bin") == source["candidate"],
        "DFU staged candidate is not byte-for-byte identical to the packaged RC5 image",
    )
    require(
        read_regular_file(flash_root / "candidate.readback.bin") == source["candidate"],
        "DFU readback is not byte-for-byte identical to the packaged RC5 image",
    )

    tooling_payloads: list[tuple[str, bytes]] = []
    for tooling_path in TOOLING_PATHS:
        resolved_tooling = resolve_repository_input(repository_root, tooling_path, f"qualification tooling {tooling_path}")
        require(resolved_tooling.is_file(), f"qualification tooling is not a file: {tooling_path}")
        tooling_payloads.append((tooling_path, read_regular_file(resolved_tooling, MAX_TEXT_BYTES)))

    output_path = resolve_output(repository_root, output)
    for input_root in [source_root, *(item.root for item in verified)]:
        require(not output_path.is_relative_to(input_root), "output must not be inside an authenticated input tree")

    manifest = {
        "bundle_format": BUNDLE_FORMAT,
        "qualification": {
            "status": QUALIFICATION_STATUS,
            "physical_runtime_evidence": "SCOPED_PASS_WITH_EXPLICIT_LIMITATIONS",
            "physical_fault_injection": "PENDING",
            "hardware_qualified": False,
            "fault_injection_waiver": None,
            "candidate_device_binding": "mixed-scope-see-evidence-bindings",
            "flash_and_linked_runtime_device_byte_binding": {
                "pass": True,
                "scope": "candidate image range plus rc5-usb-runtime and rc5-reset-retention only",
                "image_range_bytes": EXPECTED_CANDIDATE_SIZE,
                "bytes_beyond_image_range_verified": False,
                "historical_selftest_ab_byte_bound": False,
            },
            "usb_data_plane_trace_mapping_claimed": True,
            "spur_persistence": "NON_GATING_PENDING",
            "cold_boot_precondition": "sealed-operator-attestation-historical-version-bound",
        },
        "source_release": {
            "repository_relative_path": source_release,
            "release_id": EXPECTED_RELEASE_ID,
            "version": EXPECTED_VERSION,
            "release_commit": EXPECTED_RELEASE_COMMIT,
            "implementation_commit": EXPECTED_IMPLEMENTATION_COMMIT,
            "chibios_commit": EXPECTED_CHIBIOS_COMMIT,
            "sha256sums_sha256": EXPECTED_SOURCE_SEAL_SHA256,
            "manifest_sha256": EXPECTED_SOURCE_MANIFEST_SHA256,
            "simulation_qualification_sha256": EXPECTED_SOURCE_QUALIFICATION_SHA256,
            "simulation_qualification": "SIMULATION_PASS_HARDWARE_PENDING",
            "original_seal_mutated": False,
            "inventory_entries_verified": source["entry_count"],
        },
        "evidence_packaging": {
            "evidence_payloads_included": False,
            "bundle_self_contained": False,
            "included_material": "cryptographic-inventory-references-only",
            "audit_requires_named_repository_artifact_trees": True,
        },
        "qualification_tooling": {
            "payloads_included": True,
            "relationship": "audit snapshots; not a cryptographic attestation that each snapshot produced each historical record",
            "files": [
                {
                    "repository_relative_path": path,
                    "bundle_path": f"qualification-tooling/{path}",
                    "sha256": sha256_bytes(value),
                }
                for path, value in tooling_payloads
            ],
        },
        "firmware": {
            "candidate": {
                "path": f"firmware/{EXPECTED_CANDIDATE_NAME}",
                "hardware_target": "tinySA Ultra+ ZS407 / STM32F303",
                "version": EXPECTED_VERSION,
                "size_bytes": EXPECTED_CANDIDATE_SIZE,
                "sha256": EXPECTED_CANDIDATE_SHA256,
            },
            "official_rollback": {
                "path": f"firmware/{EXPECTED_ROLLBACK_NAME}",
                "hardware_target": "tinySA Ultra+ ZS407 / STM32F303",
                "version": EXPECTED_ROLLBACK_VERSION,
                "source_commit": EXPECTED_ROLLBACK_COMMIT,
                "size_bytes": EXPECTED_ROLLBACK_SIZE,
                "sha256": EXPECTED_ROLLBACK_SHA256,
            },
            "f072_binary_included": False,
        },
        "evidence": [
            {
                "role": item.spec.role,
                "repository_relative_path": item.repository_path,
                "inventory_copy": f"evidence-inventories/{item.spec.role}.SHA256SUMS",
                "sha256sums_sha256": item.spec.inventory_sha256,
                "inventory_entries_verified": len(item.inventory),
                "primary_file": item.spec.primary_file,
                "primary_sha256": item.spec.primary_sha256,
                "schema": item.spec.schema,
                "semantic_scope": semantic_scope(item.spec),
                "binding_scope": evidence_binding_scope(item.spec),
                "payload_included": False,
            }
            for item in verified
        ],
        "flash_policy": {
            "automated_flash": False,
            "owner": "Atom-Flasher",
            "bundle_authorization": "archive-only-no-current-write-authority",
            "dfu_entry": "standalone-flasher-guided-operator-confirmed",
            "flash_execution": "standalone-atom-flasher-only",
            "custom_artifact_admission": "tinysa-flasher-build-v2-manifest-required",
            "candidate_currently_admissible": False,
            "requires_known_good_rollback": True,
        },
    }
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")

    members: dict[str, bytes] = {
        f"firmware/{EXPECTED_CANDIDATE_NAME}": source["candidate"],
        f"firmware/{EXPECTED_ROLLBACK_NAME}": source["rollback"],
        "source-seal/SHA256SUMS": source["seal_bytes"],
        "source-seal/manifest.txt": source["manifest_bytes"],
        "source-seal/qualification.txt": source["qualification_bytes"],
        "manifest.json": manifest_bytes,
        "qualification-report.md": render_report(verified),
        "INSTALLATION.txt": render_installation_boundary(),
    }
    for item in verified:
        members[f"evidence-inventories/{item.spec.role}.SHA256SUMS"] = item.inventory_bytes
    for path, value in tooling_payloads:
        members[f"qualification-tooling/{path}"] = value
    sums = "".join(f"{sha256_bytes(members[name])}  ./{name}\n" for name in sorted(members))
    members["SHA256SUMS"] = sums.encode("utf-8")

    output_path, output_descriptor = reserve_output_directory(repository_root, output)
    try:
        write_file_at(output_descriptor, "INCOMPLETE", b"Bundle publication did not complete. Do not flash.\n")
        for name in sorted(members):
            write_file_at(output_descriptor, name, members[name])
        os.unlink("INCOMPLETE", dir_fd=output_descriptor)
        os.fsync(output_descriptor)
    finally:
        os.close(output_descriptor)

    return output_path


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="repository containing the sealed artifacts (default: script parent repository)",
    )
    parser.add_argument(
        "--source-release",
        default=DEFAULT_SOURCE_RELEASE,
        help="repository-relative path to the exact sealed RC5 source package",
    )
    parser.add_argument(
        "--evidence",
        action="append",
        default=[],
        metavar="ROLE=PATH",
        help="override one known evidence role with another repository-relative location",
    )
    parser.add_argument("--output", required=True, help="new repository-relative bundle directory")
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        overrides = evidence_overrides(args.evidence)
        output = create_bundle(args.repository_root, args.source_release, overrides, args.output)
    except BundleError as error:
        print(f"error: {error}", file=os.sys.stderr)
        return 2
    print(f"bundle={output}")
    print(f"status={QUALIFICATION_STATUS}")
    print("hardware_qualified=false")
    print("automated_flash=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
