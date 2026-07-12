#!/usr/bin/env python3
"""Audit Protocol v2 transport ownership and hardware-off boundaries."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import shutil
import subprocess
import sys


class AuditError(RuntimeError):
    pass


def run(command: list[str]) -> str:
    try:
        return subprocess.run(command, check=True, text=True,
                              stdout=subprocess.PIPE).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        raise AuditError(f"command failed: {' '.join(command)}") from error


def private_byte(symbols: str, name: str) -> str:
    rows = [line for line in symbols.splitlines() if line.endswith(f" {name}")]
    if len(rows) != 1:
        raise AuditError(f"expected exactly one {name} symbol")
    fields = rows[0].split()
    if len(fields) != 4 or fields[1] != "00000001" or fields[2] != "b":
        raise AuditError(f"{name} must be a private 1-byte BSS symbol")
    return fields[0]


def private_bss(symbols: str, name: str, size: int) -> str:
    rows = [line.split() for line in symbols.splitlines()
            if line.endswith(f" {name}")]
    if len(rows) != 1 or len(rows[0]) != 4:
        raise AuditError(f"expected exactly one {name} symbol")
    address, width, kind, _ = rows[0]
    if int(width, 16) != size or kind != "b":
        raise AuditError(f"{name} must be a private {size}-byte BSS symbol")
    return address


def disassemble(objdump: str, elf: Path, name: str) -> str:
    output = run([objdump, "-d", f"--disassemble={name}", str(elf)])
    if f"<{name}>:" not in output:
        raise AuditError(f"required function is not linked: {name}")
    return output


def audit(elf: Path) -> str:
    objdump = shutil.which("arm-none-eabi-objdump")
    nm = shutil.which("arm-none-eabi-nm")
    if objdump is None or nm is None:
        raise AuditError("Arm objdump and nm must be on PATH")

    symbols = run([nm, "-S", "--defined-only", str(elf)])
    qualified_address = private_byte(symbols, "transport_hardware_qualified")
    ownership_address = private_byte(symbols, "shell_ownership_released")
    lifecycle_address = private_bss(symbols, "transport_lifecycle", 32)
    forbidden_names = (
        "transport_set_qualified", "transport_qualify",
        "release_shell_ownership", "transport_unlock",
    )
    if any(name in symbols for name in forbidden_names):
        raise AuditError("transport image exposes an unlock entry point")

    hardware_gate = disassemble(
        objdump, elf, "transport_admission_enabled")
    if qualified_address not in hardware_gate or "ldrb" not in hardware_gate:
        raise AuditError("hardware helper does not read the private lock byte")

    start = disassemble(objdump, elf, "zs407_usb_transport_start")
    if "transport_admission_enabled" not in start or \
            "zs407_transport_lifecycle_request" not in start:
        raise AuditError("transport request lacks qualification/lifecycle gates")
    if lifecycle_address not in start or "#6" not in start:
        raise AuditError("transport request lacks lifecycle address/refusal")
    if "chThdCreateStatic" in start:
        raise AuditError("sweep-thread request creates the binary worker")

    complete = disassemble(
        objdump, elf, "zs407_usb_transport_complete_handoff")
    begin = complete.find("<zs407_transport_lifecycle_begin>")
    create = complete.find("<chThdCreateStatic>")
    if begin < 0 or create < 0 or begin > create:
        raise AuditError("worker creation is not dominated by lifecycle begin")
    if "transport_admission_enabled" not in complete or \
            ownership_address not in complete:
        raise AuditError("completion lacks qualification/ownership gates")

    image_strings = run([shutil.which("strings") or "strings", str(elf)])
    if "qualification profile absent" not in image_strings or \
            "QUAL-407" in image_strings or \
            "armed: binary ownership begins" in image_strings:
        raise AuditError("locked image exposes qualification-profile admission")

    worker = disassemble(objdump, elf, "transport_worker")
    required_worker_calls = (
        "ibqGetFullBufferTimeout", "zs407_stream_parser_feed",
        "ibqReleaseEmptyBuffer", "zs407_transport_lifecycle_binary_active",
        "zs407_transport_lifecycle_disconnect",
    )
    if any(name not in worker for name in required_worker_calls):
        raise AuditError("worker is not a ChibiOS-buffer-to-parser thread")
    if "FromISR" in worker:
        raise AuditError("worker unexpectedly uses ISR-only APIs")

    bounded_write = disassemble(objdump, elf, "bounded_usb_write")
    if "obqWriteTimeout" not in bounded_write or "streamWrite" in bounded_write:
        raise AuditError("transport output is not timeout-bounded")

    receive_isr = run([
        objdump, "-d", "--disassemble=sduDataReceived", str(elf)
    ])
    if "zs407_stream_parser" in receive_isr or "zs407_crc32" in receive_isr:
        raise AuditError("USB receive ISR performs protocol or CRC work")

    full_disassembly = run([objdump, "-d", str(elf)])
    crc_calls = [line for line in full_disassembly.splitlines()
                 if re.search(r"\bbl\b.*<zs407_crc32_stm32_try>", line)]
    if len(crc_calls) != 1:
        raise AuditError("hardware CRC must only be reachable from its selftest")

    return (
        "protocol_v2_lock_audit=passed\n"
        "transport_qualification_symbol=private-bss-byte\n"
        "shell_ownership_symbol=private-bss-byte\n"
        "unlock_entry_points=absent\n"
        "request_worker_creation=absent\n"
        "worker_creation_dominated=locked-lifecycle\n"
        "binary_tx=bounded-output-queue-timeout\n"
        "usb_isr_protocol_work=absent\n"
        "hardware_crc_reachable_from=selftest-only\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("elf", type=Path)
    args = parser.parse_args()
    try:
        if not args.elf.is_file():
            raise AuditError(f"ELF not found: {args.elf}")
        print(audit(args.elf), end="")
        return 0
    except AuditError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
