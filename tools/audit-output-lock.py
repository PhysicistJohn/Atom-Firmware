#!/usr/bin/env python3
"""Prove the Phase 5 AWG binary fails closed before hardware setup."""

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


def instruction_rows(disassembly: str) -> list[tuple[int, str]]:
    rows: list[tuple[int, str]] = []
    pattern = re.compile(r"^\s*([0-9a-f]+):\s+(?:[0-9a-f]{2,8}\s+)+(.*)$")
    for line in disassembly.splitlines():
        match = pattern.match(line)
        if match:
            rows.append((int(match.group(1), 16), match.group(2).strip()))
    return rows


def audit(elf: Path) -> str:
    objdump = shutil.which("arm-none-eabi-objdump")
    nm = shutil.which("arm-none-eabi-nm")
    if objdump is None or nm is None:
        raise AuditError("Arm objdump and nm must be on PATH")

    symbols = run([nm, "-S", "--defined-only", str(elf)])
    matches = [line for line in symbols.splitlines()
               if line.endswith(" awg_hardware_qualified")]
    if len(matches) != 1:
        raise AuditError("expected exactly one AWG qualification symbol")
    fields = matches[0].split()
    if len(fields) != 4 or fields[1] != "00000001" or fields[2] != "b":
        raise AuditError("qualification latch must be a private 1-byte BSS symbol")
    allowed_qualification_symbols = {
        "awg_hardware_qualified", "transport_hardware_qualified",
        "passive_hardware_qualified", "passive_stream_qualified",
        "passive_capture_qualified",
    }
    for line in symbols.splitlines():
        if "qualif" not in line.lower():
            continue
        name = line.split()[-1]
        if name not in allowed_qualification_symbols:
            raise AuditError("unexpected qualification-related entry point")
        if name != "awg_hardware_qualified":
            latch_fields = line.split()
            if len(latch_fields) != 4 or \
                    latch_fields[1] != "00000001" or \
                    latch_fields[2] != "b":
                raise AuditError(f"{name} qualification latch is not private")

    disassembly = run([
        objdump, "-d", "--disassemble=zs407_awg_start", str(elf)
    ])
    rows = instruction_rows(disassembly)
    if not rows:
        raise AuditError("zs407_awg_start was not linked")

    gate_index = -1
    gate_target = -1
    for index, (_, instruction) in enumerate(rows):
        match = re.search(
            r"\b(?:beq(?:\.n)?|cbz)\s+(?:r\d+,\s*)?([0-9a-f]+)\b",
            instruction,
        )
        if match:
            gate_index = index
            gate_target = int(match.group(1), 16)
            break
    if gate_index < 2:
        raise AuditError("no early conditional qualification branch")

    before_gate = [instruction for _, instruction in rows[:gate_index]]
    if not any(instruction.startswith("ldrb") for instruction in before_gate):
        raise AuditError("qualification latch is not read as a byte")
    if any(re.match(r"(?:str|bl|blx)\b", instruction)
           for instruction in before_gate):
        raise AuditError("side effect occurs before qualification branch")

    hardware_call = next(
        (index for index, (_, instruction) in enumerate(rows)
         if "dmaStreamAllocate" in instruction),
        -1,
    )
    if hardware_call < 0 or gate_index >= hardware_call:
        raise AuditError("qualification branch does not dominate DMA allocation")

    target_index = next(
        (index for index, (address, _) in enumerate(rows)
         if address == gate_target),
        -1,
    )
    if target_index < 0:
        raise AuditError("qualification failure target is missing")
    failure_path = " ".join(
        instruction for _, instruction in rows[target_index:target_index + 4]
    )
    if not re.search(r"movs?\s+r0,\s*#6\b", failure_path) or \
            not re.search(r"bx\s+lr\b", failure_path):
        raise AuditError("failure branch does not return NOT_QUALIFIED (6)")

    return (
        "output_lock=passed\n"
        "qualification_symbol=private-bss-byte\n"
        "prebranch_side_effects=none\n"
        "failure_status=ZS407_CORE_NOT_QUALIFIED\n"
        "dma_allocation_dominated=true\n"
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
