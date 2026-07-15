#!/usr/bin/env python3
"""Validate and package one reproducible ZS407 BIN for TinySA Flasher.

This helper never builds or flashes. The shell wrapper proves two clean builds
match, then invokes this tool to create a content-addressed BIN plus strict v1
manifest using create-once writes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import struct
from pathlib import Path

MAXIMUM_WRITE_BYTES = 245_760
MINIMUM_FIRMWARE_BYTES = 8_192
LOAD_ADDRESS = 0x0800_0000
SCHEMA_ID = "https://physicistjohn.github.io/tinysa-flasher/contracts/schemas/tinysa-firmware-build-manifest-v1.schema.json"
RESERVED_OEM_REVISIONS = {"c5dd31f", "c979386"}
VERSION_PATTERN = re.compile(r"^tinySA4_[A-Za-z0-9.+_-]{1,96}-g([a-f0-9]{7,40})$")
HEX_40_PATTERN = re.compile(r"^[a-f0-9]{40}$")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--chibios-commit", required=True)
    parser.add_argument("--source-date-epoch", required=True, type=int)
    parser.add_argument("--toolchain", required=True)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--simulation-passed", action="store_true")
    parser.add_argument("--hardware-qualified-evidence", type=Path)
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    source_commit = require_hex_40(arguments.source_commit, "source commit")
    chibios_commit = require_hex_40(arguments.chibios_commit, "ChibiOS commit")
    version_match = VERSION_PATTERN.fullmatch(arguments.version)
    if not version_match:
        fail("version must be a bounded tinySA4_* value ending in -g<7..40 lowercase hex>")
    revision = version_match.group(1)
    if not source_commit.startswith(revision):
        fail("embedded reported revision is not a prefix of the source commit")
    if revision in RESERVED_OEM_REVISIONS:
        fail("reserved OEM revisions cannot be packaged as a local custom build")
    if arguments.source_date_epoch <= 0:
        fail("source-date epoch must be positive")
    if not arguments.toolchain or len(arguments.toolchain) > 240 or any(character in arguments.toolchain for character in "\r\n"):
        fail("toolchain identity must be one bounded line")

    binary = read_regular_file(arguments.binary, MAXIMUM_WRITE_BYTES)
    if len(binary) < MINIMUM_FIRMWARE_BYTES:
        fail(f"firmware contains {len(binary)} bytes; minimum is {MINIMUM_FIRMWARE_BYTES}")
    version_bytes = arguments.version.encode("ascii")
    if version_bytes not in binary:
        fail("firmware does not contain the exact requested version")
    if b"+ ZS407" not in binary:
        fail("firmware does not contain the ZS407 identity")
    initial_stack_pointer, reset_handler = struct.unpack_from("<II", binary)
    validate_vectors(initial_stack_pointer, reset_handler, len(binary))
    digest = hashlib.sha256(binary).hexdigest()

    qualification_digest = None
    if arguments.hardware_qualified_evidence:
        qualification = read_regular_file(arguments.hardware_qualified_evidence, 64 * 1024 * 1024)
        qualification_digest = hashlib.sha256(qualification).hexdigest()
    manifest = {
        "$schema": SCHEMA_ID,
        "manifestVersion": 1,
        "artifact": {
            "filename": f"{arguments.version}.bin",
            "format": "raw-stm32-binary",
            "sizeBytes": len(binary),
            "sha256": digest,
            "loadAddress": "0x08000000",
            "maximumWriteBytes": MAXIMUM_WRITE_BYTES,
            "initialStackPointer": hexadecimal(initial_stack_pointer),
            "resetHandler": hexadecimal(reset_handler),
        },
        "firmware": {
            "product": "tinySA Ultra / Ultra+",
            "hardwareTarget": "ZS407",
            "mcu": "STM32F303",
            "version": arguments.version,
            "reportedRevision": revision,
            "sourceRepository": "PhysicistJohn/TinySA_Firmware",
            "sourceCommit": source_commit,
            "sourceTree": "tracked-clean",
            "chibiosCommit": chibios_commit,
        },
        "build": {
            "sourceDateEpoch": arguments.source_date_epoch,
            "toolchain": arguments.toolchain,
            "reproducibleCleanBuilds": True,
            "hardwareQualification": "qualified-on-zs407" if qualification_digest else "unqualified",
            "simulationQualification": "passed" if arguments.simulation_passed else "not-run",
            **({"qualificationEvidenceSha256": qualification_digest} if qualification_digest else {}),
        },
        "flashPolicy": {
            "physicalFlash": "operator-confirmed-only",
            "automatedFlash": False,
            "requiresKnownGoodRollback": True,
        },
    }
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=False) + "\n").encode("utf-8")
    output_directory = arguments.output_root / source_commit / digest
    output_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    install_create_once(output_directory / manifest["artifact"]["filename"], binary)
    install_create_once(output_directory / "tinysa-flasher-build-v1.json", manifest_bytes)
    if arguments.hardware_qualified_evidence:
        evidence_name = f"qualification-{qualification_digest}.evidence"
        install_create_once(output_directory / evidence_name, qualification)
    sync_directory(output_directory)
    print(f"manifest={output_directory / 'tinysa-flasher-build-v1.json'}")
    print(f"binary={output_directory / manifest['artifact']['filename']}")
    print(f"binary_size={len(binary)}")
    print(f"binary_sha256={digest}")
    return 0


def read_regular_file(path: Path, maximum_bytes: int) -> bytes:
    if path.is_symlink():
        fail(f"input must not be a symbolic link: {path}")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size <= 0 or before.st_size > maximum_bytes:
            fail(f"input is not a bounded regular file: {path}")
        if hasattr(os, "getuid") and before.st_uid != os.getuid():
            fail(f"input is not owned by the current user: {path}")
        if before.st_mode & 0o022:
            fail(f"input is writable by another user or group: {path}")
        with os.fdopen(os.dup(descriptor), "rb") as stream:
            value = stream.read(maximum_bytes + 1)
        after = os.fstat(descriptor)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns
        ) or len(value) != before.st_size:
            fail(f"input changed while it was read: {path}")
        return value
    finally:
        os.close(descriptor)


def validate_vectors(stack_pointer: int, reset_handler: int, size: int) -> None:
    stack_in_sram = 0x2000_0000 <= stack_pointer <= 0x2000_A000
    stack_in_ccm = 0x1000_0000 <= stack_pointer <= 0x1000_2000
    if stack_pointer & 0x3 or not (stack_in_sram or stack_in_ccm):
        fail(f"initial stack pointer {hexadecimal(stack_pointer)} is outside STM32F303 ZS407 RAM")
    reset_address = reset_handler & ~1
    if not reset_handler & 1 or not LOAD_ADDRESS + 8 <= reset_address < LOAD_ADDRESS + size:
        fail(f"reset handler {hexadecimal(reset_handler)} is not Thumb code inside the image")


def install_create_once(destination: Path, value: bytes) -> None:
    if destination.exists():
        if destination.is_symlink() or destination.read_bytes() != value:
            fail(f"create-once destination conflicts with existing data: {destination}")
        return
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.part")
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            remaining = memoryview(value)
            while remaining:
                written = os.write(descriptor, remaining)
                if written <= 0:
                    fail(f"create-once write made no progress: {temporary}")
                remaining = remaining[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        try:
            os.link(temporary, destination)
        except FileExistsError:
            if destination.is_symlink() or destination.read_bytes() != value:
                fail(f"create-once destination raced with conflicting data: {destination}")
        temporary.unlink()
    finally:
        temporary.unlink(missing_ok=True)


def sync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def require_hex_40(value: str, label: str) -> str:
    if not HEX_40_PATTERN.fullmatch(value):
        fail(f"{label} must be 40 lowercase hexadecimal characters")
    return value


def hexadecimal(value: int) -> str:
    return f"0x{value:08x}"


def fail(message: str) -> None:
    raise SystemExit(f"error: {message}")


if __name__ == "__main__":
    raise SystemExit(main())
