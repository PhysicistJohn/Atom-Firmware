#!/usr/bin/env python3
"""Flash one admitted ZS407/F303 image through STM32 ROM DFU and seal evidence.

This tool never enters DFU mode.  It requires an already-enumerated, exactly
identified ROM DFU device and writes alternate 0 (Internal Flash) once.  It
never selects alternate 1 (Option Bytes), never retries a download, and does
an exact same-device DfuSe upload/read-back before requesting leave.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
from typing import Any, Iterable

from serial.tools import list_ports


SCHEMA = "tinysa-physical-dfu-flash-evidence-v2"
CONFIRMATION = "FLASH-ZS407-F303-ALT0"
DFU_VID = 0x0483
DFU_PID = 0xDF11
NORMAL_VID = 0x0483
NORMAL_PID = 0x5740
FLASH_ADDRESS = "0x08000000"
ADMITTED_CANDIDATE_SHA256 = (
    "1e3f45a9744b18985622d5abf6c2445524a4ad53a831316766c37de80ac96685"
)
ADMITTED_CANDIDATE_BYTES = 193_980
ADMITTED_VERSION_MARKER = b"tinySA4_v0.4-chibios21-rc5"
ADMITTED_HARDWARE_MARKER = b"+ ZS407"
ADMITTED_DFU_UTIL_SHA256 = (
    "d650bcf7a3f1ad42eff139924c93aacdde53d0c61629bae5aa85c8e793f5d669"
)
ADMITTED_DFU_UTIL_BYTES = 227_304
ADMITTED_DFU_UTIL_VERSION = "dfu-util 0.11"
ADMITTED_DFU_SERIAL = "2066365B2036"
ADMITTED_NORMAL_SERIAL = "706"
ADMITTED_ALT0_NAME = "@Internal Flash  /0x08000000/128*0002Kg"
ADMITTED_ALT1_NAME = "@Option Bytes  /0x1FFFF800/01*016 e"
DFU_LINE = re.compile(r"^Found DFU: \[([0-9A-Fa-f]{4}):([0-9A-Fa-f]{4})\](.*)$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_regular_snapshot(path: Path, label: str, maximum_bytes: int) -> bytes:
    """Read one regular file descriptor without following a symlink."""
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        status = os.fstat(descriptor)
        if not stat.S_ISREG(status.st_mode):
            raise ValueError(f"{label} is not a regular file: {path}")
        with os.fdopen(descriptor, "rb", closefd=False) as source:
            payload = source.read()
    finally:
        os.close(descriptor)
    if not payload or len(payload) > maximum_bytes:
        raise ValueError(f"{label} size must be within 1..{maximum_bytes} bytes")
    return payload


def validate_candidate_snapshot(payload: bytes, expected_sha256: str) -> None:
    actual_sha256 = hashlib.sha256(payload).hexdigest()
    if expected_sha256 != ADMITTED_CANDIDATE_SHA256:
        raise ValueError("requested candidate SHA-256 is not the sealed RC5 release")
    if actual_sha256 != ADMITTED_CANDIDATE_SHA256:
        raise ValueError(
            f"candidate hash mismatch: expected {ADMITTED_CANDIDATE_SHA256}, "
            f"got {actual_sha256}"
        )
    if len(payload) != ADMITTED_CANDIDATE_BYTES:
        raise ValueError(
            f"candidate size mismatch: expected {ADMITTED_CANDIDATE_BYTES}, got {len(payload)}"
        )
    initial_sp = int.from_bytes(payload[0:4], "little")
    reset_vector = int.from_bytes(payload[4:8], "little")
    reset_address = reset_vector & ~1
    if (
        not 0x20000000 <= initial_sp < 0x20080000
        or initial_sp % 8 != 0
        or reset_vector & 1 != 1
        or not 0x08000000 <= reset_address < 0x08000000 + len(payload)
    ):
        raise ValueError("candidate does not contain a valid STM32F303 vector prefix")
    for marker in (ADMITTED_VERSION_MARKER, ADMITTED_HARDWARE_MARKER):
        if marker not in payload:
            raise ValueError(f"candidate is missing admitted marker {marker!r}")


def parse_quoted(tail: str, field: str) -> str | None:
    match = re.search(rf'(?:^|, )?{re.escape(field)}="([^"]*)"', tail)
    return match.group(1) if match else None


def parse_integer(tail: str, field: str) -> int | None:
    match = re.search(rf"(?:^|, )?{re.escape(field)}=([0-9]+)(?:,|$)", tail)
    return int(match.group(1)) if match else None


def parse_dfu_listing(payload: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in payload.splitlines():
        match = DFU_LINE.match(line.strip())
        if not match:
            continue
        tail = match.group(3)
        record = {
            "vid": int(match.group(1), 16),
            "pid": int(match.group(2), 16),
            "path": parse_quoted(tail, "path"),
            "cfg": parse_integer(tail, "cfg"),
            "intf": parse_integer(tail, "intf"),
            "alt": parse_integer(tail, "alt"),
            "name": parse_quoted(tail, "name"),
            "serial": parse_quoted(tail, "serial"),
            "line": line.strip(),
        }
        if any(
            record[field] is None
            for field in ("path", "cfg", "intf", "alt", "name", "serial")
        ):
            raise ValueError(f"malformed dfu-util device line: {line!r}")
        records.append(record)
    return records


def admit_dfu_device(
    records: list[dict[str, Any]], expected_location: str, expected_serial: str,
) -> dict[str, Any]:
    if not records:
        raise ValueError("dfu-util found no DFU interfaces")
    devices = {
        (record["vid"], record["pid"], record["path"], record["serial"])
        for record in records
    }
    if devices != {(DFU_VID, DFU_PID, expected_location, expected_serial)}:
        raise ValueError(f"DFU device identity is not the one admitted target: {devices}")
    by_alt = {record["alt"]: record for record in records}
    if len(by_alt) != len(records) or set(by_alt) != {0, 1}:
        raise ValueError(f"expected exactly DFU alternates 0 and 1; got {sorted(by_alt)}")
    if by_alt[0]["name"] != ADMITTED_ALT0_NAME:
        raise ValueError(f"DFU alternate 0 is not Internal Flash: {by_alt[0]['name']!r}")
    if by_alt[1]["name"] != ADMITTED_ALT1_NAME:
        raise ValueError(f"DFU alternate 1 is not Option Bytes: {by_alt[1]['name']!r}")
    if any(record["cfg"] != 1 or record["intf"] != 0 for record in records):
        raise ValueError("expected DFU configuration 1 and interface 0 for both alternates")
    return {
        "vid": DFU_VID,
        "pid": DFU_PID,
        "path": expected_location,
        "serial": expected_serial,
        "alternates": [by_alt[0], by_alt[1]],
        "selected_alt": 0,
        "rejected_alt": 1,
    }


def run_process(arguments: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        arguments,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        check=False,
    )


def wait_for_normal_identity(
    serial_number: str, location: str, timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        matches = [
            port for port in list_ports.comports()
            if port.vid == NORMAL_VID and port.pid == NORMAL_PID
            and port.serial_number == serial_number and port.location == location
        ]
        if len(matches) == 1:
            port = matches[0]
            return {
                "device": port.device,
                "vid": port.vid,
                "pid": port.pid,
                "serial_number": port.serial_number,
                "location": port.location,
            }
        if len(matches) > 1:
            raise RuntimeError("multiple identical normal-mode USB interfaces appeared")
        if time.monotonic() >= deadline:
            raise TimeoutError("expected normal-mode USB identity did not enumerate")
        time.sleep(0.1)


def write_inventory(output: Path) -> None:
    paths = sorted(
        path for path in output.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS"
    )
    (output / "SHA256SUMS").write_text(
        "".join(
            f"{sha256_file(path)}  {path.relative_to(output).as_posix()}\n"
            for path in paths
        ),
        encoding="utf-8",
    )


def validate_args(args: argparse.Namespace) -> tuple[bytes, bytes]:
    if args.output.exists():
        raise ValueError(f"output path already exists: {args.output}")
    if args.confirm != CONFIRMATION:
        raise ValueError(f"--confirm must be exactly {CONFIRMATION}")
    if not re.fullmatch(r"[0-9a-f]{64}", args.expected_candidate_sha256):
        raise ValueError("--expected-candidate-sha256 must be 64 lowercase hex digits")
    candidate_snapshot = read_regular_snapshot(
        args.candidate_bin, "candidate", 1024 * 1024
    )
    validate_candidate_snapshot(candidate_snapshot, args.expected_candidate_sha256)
    dfu_util_snapshot = read_regular_snapshot(args.dfu_util, "dfu-util", 4 * 1024 * 1024)
    actual_tool_hash = hashlib.sha256(dfu_util_snapshot).hexdigest()
    if (
        len(dfu_util_snapshot) != ADMITTED_DFU_UTIL_BYTES
        or actual_tool_hash != ADMITTED_DFU_UTIL_SHA256
    ):
        raise ValueError(
            "dfu-util executable does not match the admitted arm64 0.11 build: "
            f"bytes={len(dfu_util_snapshot)} sha256={actual_tool_hash}"
        )
    if not args.expected_dfu_location or not args.expected_dfu_serial:
        raise ValueError("exact DFU location and serial are required")
    if not args.expected_normal_location or not args.expected_normal_serial:
        raise ValueError("exact normal-mode location and serial are required")
    if args.expected_normal_location != args.expected_dfu_location:
        raise ValueError("DFU and normal-mode USB locations must match")
    if args.expected_dfu_serial != ADMITTED_DFU_SERIAL:
        raise ValueError("DFU serial is not the admitted physical ZS407 unit")
    if args.expected_normal_serial != ADMITTED_NORMAL_SERIAL:
        raise ValueError("normal-mode serial is not the admitted RC5 USB identity")
    if not math.isfinite(args.timeout) or not 5.0 <= args.timeout <= 300.0:
        raise ValueError("--timeout must be finite and within 5..300 seconds")
    return candidate_snapshot, dfu_util_snapshot


def flash(args: argparse.Namespace) -> int:
    candidate_snapshot, dfu_util_snapshot = validate_args(args)
    output = args.output
    output.mkdir(parents=True)
    staged_candidate = output / "candidate.snapshot.bin"
    staged_candidate.write_bytes(candidate_snapshot)
    if sha256_file(staged_candidate) != args.expected_candidate_sha256:
        raise RuntimeError("staged candidate snapshot hash changed before DFU admission")
    staged_dfu_util = output / "dfu-util.snapshot"
    staged_dfu_util.write_bytes(dfu_util_snapshot)
    staged_dfu_util.chmod(0o500)
    if sha256_file(staged_dfu_util) != ADMITTED_DFU_UTIL_SHA256:
        raise RuntimeError("staged dfu-util snapshot hash changed before DFU admission")
    metadata: dict[str, Any] = {
        "schema": SCHEMA,
        "started_utc": utc_now(),
        "finished_utc": None,
        "result": "INCOMPLETE",
        "target": "tinySA Ultra+ ZS407 / STM32F303",
        "candidate": {
            "path": str(args.candidate_bin.resolve()),
            "bytes": len(candidate_snapshot),
            "sha256": args.expected_candidate_sha256,
            "staged_path": staged_candidate.name,
            "staged_sha256": args.expected_candidate_sha256,
        },
        "dfu_tool": {
            "path": str(args.dfu_util.resolve()),
            "sha256": ADMITTED_DFU_UTIL_SHA256,
            "bytes": len(dfu_util_snapshot),
            "expected_version": ADMITTED_DFU_UTIL_VERSION,
            "staged_path": staged_dfu_util.name,
        },
        "preflight": None,
        "download": {"attempt_count": 0, "selected_alt": 0},
        "readback": {"attempt_count": 0, "selected_alt": 0},
        "normal_mode": None,
        "limitations": [
            "DFU read-back proves the admitted flash byte range, not bytes beyond the RC5 image.",
            "Post-flash exact firmware version is authenticated by a separate serial evidence run."
        ],
    }
    result = "FAIL"
    try:
        version = run_process([str(staged_dfu_util), "--version"], args.timeout)
        (output / "dfu-util-version.stdout.txt").write_text(version.stdout, encoding="utf-8")
        (output / "dfu-util-version.stderr.txt").write_text(version.stderr, encoding="utf-8")
        version_lines = (version.stdout + version.stderr).splitlines()
        if (
            version.returncode != 0
            or not version_lines
            or version_lines[0].strip() != ADMITTED_DFU_UTIL_VERSION
        ):
            raise RuntimeError("dfu-util version probe failed")
        if sha256_file(staged_dfu_util) != ADMITTED_DFU_UTIL_SHA256:
            raise RuntimeError("staged dfu-util changed after version authentication")
        listing = run_process([str(staged_dfu_util), "-l"], args.timeout)
        (output / "dfu-util-list.stdout.txt").write_text(listing.stdout, encoding="utf-8")
        (output / "dfu-util-list.stderr.txt").write_text(listing.stderr, encoding="utf-8")
        if listing.returncode != 0:
            raise RuntimeError(f"dfu-util listing failed with exit {listing.returncode}")
        admitted = admit_dfu_device(
            parse_dfu_listing(listing.stdout + listing.stderr),
            args.expected_dfu_location,
            args.expected_dfu_serial,
        )
        metadata["preflight"] = {"pass": True, **admitted}
        print(
            "ZS407_DFU_PREFLIGHT=PASS "
            f"path={args.expected_dfu_location} serial={args.expected_dfu_serial}",
            flush=True,
        )

        if sha256_file(staged_dfu_util) != ADMITTED_DFU_UTIL_SHA256:
            raise RuntimeError("staged dfu-util changed before download")
        if sha256_file(staged_candidate) != ADMITTED_CANDIDATE_SHA256:
            raise RuntimeError("staged candidate changed before download")
        command = [
            str(staged_dfu_util), "-d", "0483:df11",
            "-p", args.expected_dfu_location,
            "-S", args.expected_dfu_serial,
            "-c", "1", "-i", "0", "-a", "0",
            "-s", FLASH_ADDRESS, "-D", str(staged_candidate.resolve()),
        ]
        metadata["download"].update({
            "attempt_count": 1,
            "started_utc": utc_now(),
            "argv": command,
        })
        downloaded = run_process(command, args.timeout)
        (output / "dfu-util-download.stdout.txt").write_text(
            downloaded.stdout, encoding="utf-8"
        )
        (output / "dfu-util-download.stderr.txt").write_text(
            downloaded.stderr, encoding="utf-8"
        )
        combined = downloaded.stdout + downloaded.stderr
        transfer_markers = (
            "Download done.",
            "File downloaded successfully",
        )
        if downloaded.returncode != 0 or not all(marker in combined for marker in transfer_markers):
            raise RuntimeError(
                f"one-shot dfu-util download was not successful (exit {downloaded.returncode})"
            )
        metadata["download"].update({
            "finished_utc": utc_now(),
            "exit_code": downloaded.returncode,
            "success_markers": list(transfer_markers),
            "pass": True,
            "retry_performed": False,
        })
        print(
            "ZS407_DFU_DOWNLOAD=PASS "
            f"bytes={len(candidate_snapshot)} sha256={ADMITTED_CANDIDATE_SHA256}",
            flush=True,
        )

        if sha256_file(staged_dfu_util) != ADMITTED_DFU_UTIL_SHA256:
            raise RuntimeError("staged dfu-util changed before read-back")
        readback_path = output / "candidate.readback.bin"
        readback_command = [
            str(staged_dfu_util), "-d", "0483:df11",
            "-p", args.expected_dfu_location,
            "-S", args.expected_dfu_serial,
            "-c", "1", "-i", "0", "-a", "0",
            "-s", f"{FLASH_ADDRESS}:{len(candidate_snapshot)}:leave",
            "-U", str(readback_path.resolve()),
        ]
        metadata["readback"].update({
            "attempt_count": 1,
            "started_utc": utc_now(),
            "argv": readback_command,
            "leave_requested_after_upload": True,
        })
        uploaded = run_process(readback_command, args.timeout)
        (output / "dfu-util-readback.stdout.txt").write_text(
            uploaded.stdout, encoding="utf-8"
        )
        (output / "dfu-util-readback.stderr.txt").write_text(
            uploaded.stderr, encoding="utf-8"
        )
        if (
            uploaded.returncode != 0
            or "Upload done." not in (uploaded.stdout + uploaded.stderr)
            or not readback_path.is_file()
        ):
            raise RuntimeError(
                f"one-shot DFU read-back failed (exit {uploaded.returncode})"
            )
        readback = read_regular_snapshot(readback_path, "DFU read-back", 1024 * 1024)
        readback_sha256 = hashlib.sha256(readback).hexdigest()
        if readback != candidate_snapshot:
            raise RuntimeError(
                "DFU read-back does not exactly match the admitted candidate: "
                f"bytes={len(readback)} sha256={readback_sha256}"
            )
        metadata["readback"].update({
            "finished_utc": utc_now(),
            "exit_code": uploaded.returncode,
            "bytes": len(readback),
            "sha256": readback_sha256,
            "exact_byte_match": True,
            "pass": True,
            "retry_performed": False,
        })
        print(
            "ZS407_DFU_READBACK=PASS "
            f"bytes={len(readback)} sha256={readback_sha256}",
            flush=True,
        )
        normal = wait_for_normal_identity(
            args.expected_normal_serial,
            args.expected_normal_location,
            args.timeout,
        )
        metadata["normal_mode"] = {"pass": True, **normal}
        metadata["device_byte_binding"] = {
            "scope": (
                "one-shot admitted DFU transfer, exact same-path flash read-back, "
                "and same-path normal re-enumeration"
            ),
            "candidate_sha256": args.expected_candidate_sha256,
            "readback_sha256": readback_sha256,
            "readback_performed": True,
            "exact_byte_match": True,
        }
        if sha256_file(staged_dfu_util) != ADMITTED_DFU_UTIL_SHA256:
            raise RuntimeError("staged dfu-util changed during the flash workflow")
        result = "PASS"
        return 0
    except Exception as error:
        metadata["error"] = f"{type(error).__name__}: {error}"
        print(f"error: {error}", file=sys.stderr)
        return 1
    finally:
        metadata["result"] = result
        metadata["finished_utc"] = utc_now()
        (output / "run.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        write_inventory(output)


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="one-shot admitted ZS407/F303 DFU flash with sealed evidence"
    )
    parser.add_argument("--dfu-util", required=True, type=Path)
    parser.add_argument("--candidate-bin", required=True, type=Path)
    parser.add_argument("--expected-candidate-sha256", required=True)
    parser.add_argument("--expected-dfu-location", required=True)
    parser.add_argument("--expected-dfu-serial", required=True)
    parser.add_argument("--expected-normal-location", required=True)
    parser.add_argument("--expected-normal-serial", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--confirm", required=True)
    return parser.parse_args(argv)


def main() -> int:
    try:
        return flash(parse_args())
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
