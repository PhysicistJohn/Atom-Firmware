#!/usr/bin/env python3
"""Prove the v0.4 passive acquisition image remains fail-closed."""

from __future__ import annotations

import argparse
from pathlib import Path
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


def symbol_rows(symbols: str, name: str) -> list[list[str]]:
    return [line.split() for line in symbols.splitlines()
            if line.endswith(f" {name}")]


def require_private_bss(symbols: str, name: str, size: int) -> str:
    rows = symbol_rows(symbols, name)
    if len(rows) != 1 or len(rows[0]) != 4:
        raise AuditError(f"expected exactly one private symbol: {name}")
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
    all_symbols = run([nm, "-a", str(elf)])

    latch_names = (
        "passive_hardware_qualified",
        "passive_stream_qualified",
        "passive_capture_qualified",
    )
    latch_addresses = {
        name: require_private_bss(symbols, name, 1) for name in latch_names
    }
    require_private_bss(symbols, "stream_frame_storage", 4)

    forbidden = (
        "passive_set_qualified", "passive_qualify", "passive_unlock",
        "passive_enable_qualification", "passive_release_lock",
    )
    if any(name in symbols for name in forbidden):
        raise AuditError("passive image exposes a qualification entry point")

    start = disassemble(objdump, elf, "zs407_passive_runtime_start_stream")
    for name in ("passive_hardware_qualified", "passive_stream_qualified"):
        if latch_addresses[name] not in start:
            raise AuditError(f"stream start does not reference {name}")
    if "#6" not in start:
        raise AuditError("stream gate does not return NOT_QUALIFIED")
    heap_addresses = {}
    for name in ("__heap_base__", "__heap_end__"):
        rows = [line.split() for line in all_symbols.splitlines()
                if line.endswith(f" {name}")]
        if len(rows) != 1:
            raise AuditError(f"missing linker boundary: {name}")
        heap_addresses[name] = rows[0][0]
    if any(address not in start for address in heap_addresses.values()):
        raise AuditError("stream frame lease is not bounded by linker heap")
    first_heap = min(position for address in heap_addresses.values()
                     if (position := start.find(address)) >= 0)
    first_gate = min(position for address in (
        latch_addresses["passive_hardware_qualified"],
        latch_addresses["passive_stream_qualified"],
    ) if (position := start.find(address)) >= 0)
    if first_heap < first_gate:
        raise AuditError("stream memory lease precedes qualification reads")

    capture = disassemble(objdump, elf, "zs407_passive_runtime_arm_capture")
    for name in ("passive_hardware_qualified", "passive_capture_qualified"):
        if latch_addresses[name] not in capture:
            raise AuditError(f"capture arm does not reference {name}")
    if "#6" not in capture or "zs407_zero_span_capture_arm" not in capture:
        raise AuditError("capture qualification gate or implementation missing")

    sweep = disassemble(
        objdump, elf, "zs407_passive_runtime_on_sweep_complete")
    required_sweep_calls = (
        "zs407_monotonic_clock_update",
        "zs407_acquisition_record_complete",
        "encode_trace_frame",
    )
    if any(name not in sweep for name in required_sweep_calls):
        raise AuditError("completed-sweep timestamp/ledger/stream path is incomplete")

    worker = disassemble(objdump, elf, "transport_worker")
    if "drain_passive_frame" not in worker:
        raise AuditError("transport worker does not schedule passive TX drain")
    drain = disassemble(objdump, elf, "drain_passive_frame")
    required_worker_calls = (
        "zs407_passive_runtime_take_frame",
        "zs407_passive_runtime_release_frame",
    )
    if any(name not in drain for name in required_worker_calls):
        raise AuditError("transport worker does not own the passive TX drain")
    if "blx" not in drain:
        raise AuditError("passive TX drain does not call the stream vtable")
    if "FromISR" in worker or "FromISR" in drain:
        raise AuditError("passive transport unexpectedly performs ISR work")

    undefined = run([nm, "-u", str(elf)])
    if undefined.strip():
        raise AuditError("ELF contains unresolved symbols")
    if any(symbol_rows(symbols, name) for name in
           ("malloc", "free", "chHeapAlloc", "chHeapFree")):
        raise AuditError("passive image unexpectedly links a heap allocator")

    return (
        "passive_lock_audit=passed\n"
        "qualification_latches=private-bss-bytes\n"
        "qualification_setters=absent\n"
        "stream_memory_lease=post-gate-linker-heap\n"
        "completed_sweep_timestamp_path=linked\n"
        "transport_drain=worker-only\n"
        "dynamic_allocator=absent\n"
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
    except (AuditError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
