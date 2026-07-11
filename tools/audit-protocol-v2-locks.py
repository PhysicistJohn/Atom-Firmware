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


def audit(elf: Path) -> str:
    objdump = shutil.which("arm-none-eabi-objdump")
    nm = shutil.which("arm-none-eabi-nm")
    if objdump is None or nm is None:
        raise AuditError("Arm objdump and nm must be on PATH")

    symbols = run([nm, "-S", "--defined-only", str(elf)])
    qualified_address = private_byte(symbols, "transport_hardware_qualified")
    ownership_address = private_byte(symbols, "shell_ownership_released")
    forbidden_names = (
        "transport_set_qualified", "transport_qualify",
        "release_shell_ownership", "transport_unlock",
    )
    if any(name in symbols for name in forbidden_names):
        raise AuditError("transport image exposes an unlock entry point")

    start = run([
        objdump, "-d", "--disassemble=zs407_usb_transport_start", str(elf)
    ])
    if "chThdCreateStatic" not in start:
        raise AuditError("transport worker creation path was not linked")
    call_offset = start.index("chThdCreateStatic")
    prefix = start[:call_offset]
    if prefix.count("ldrb") < 3 or prefix.count("cbz") < 2:
        raise AuditError("qualification and ownership byte gates do not dominate start")
    if qualified_address not in start or ownership_address not in start:
        raise AuditError("start does not reference both private lock bytes")
    if len(re.findall(r"movs\s+r\d+,\s*#6\b", start)) < 2:
        raise AuditError("both lock failures must return NOT_QUALIFIED (6)")

    worker = run([
        objdump, "-d", "--disassemble=transport_worker", str(elf)
    ])
    required_worker_calls = (
        "ibqGetFullBufferTimeout", "zs407_stream_parser_feed",
        "ibqReleaseEmptyBuffer",
    )
    if any(name not in worker for name in required_worker_calls):
        raise AuditError("worker is not a ChibiOS-buffer-to-parser thread")
    if "FromISR" in worker:
        raise AuditError("worker unexpectedly uses ISR-only APIs")

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
        "worker_creation_dominated=true\n"
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
