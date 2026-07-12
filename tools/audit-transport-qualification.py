#!/usr/bin/env python3
"""Audit the one-shot transport qualification image at the ELF boundary."""

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
        return subprocess.run(
            command, check=True, text=True, stdout=subprocess.PIPE
        ).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        raise AuditError(f"command failed: {' '.join(command)}") from error


def symbol_rows(symbols: str, name: str) -> list[list[str]]:
    return [line.split() for line in symbols.splitlines()
            if line.endswith(f" {name}")]


def private_bss(symbols: str, name: str, size: int) -> str:
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
        raise AuditError(f"required function is absent: {name}")
    return output


def ordered_calls(disassembly: str, names: tuple[str, ...]) -> None:
    position = -1
    for name in names:
        next_position = disassembly.find(f"<{name}>", position + 1)
        if next_position < 0:
            raise AuditError(f"missing ordered call {name}")
        if next_position <= position:
            raise AuditError(f"call order is not monotonic at {name}")
        position = next_position


def audit(elf: Path) -> str:
    objdump = shutil.which("arm-none-eabi-objdump")
    nm = shutil.which("arm-none-eabi-nm")
    strings = shutil.which("strings")
    if objdump is None or nm is None or strings is None:
        raise AuditError("Arm binutils and strings must be on PATH")

    symbols = run([nm, "-S", "--defined-only", str(elf)])
    undefined = run([nm, "-u", str(elf)])
    if undefined.strip():
        raise AuditError("qualification ELF contains unresolved symbols")

    lifecycle_address = private_bss(symbols, "transport_lifecycle", 32)
    ownership_address = private_bss(symbols, "shell_ownership_released", 1)
    private_bss(symbols, "transport_thread", 4)
    private_bss(symbols, "transport_frame_storage", 1038)
    private_bss(symbols, "transport_parser", 36)
    private_bss(symbols, "passive_hardware_qualified", 1)
    private_bss(symbols, "passive_stream_qualified", 1)
    private_bss(symbols, "passive_capture_qualified", 1)
    private_bss(symbols, "stream_frame_storage", 4)
    if symbol_rows(symbols, "transport_hardware_qualified"):
        raise AuditError("qualification profile unexpectedly links a mutable hardware latch")

    forbidden = (
        "transport_set_qualified", "transport_qualify",
        "transport_unlock", "passive_set_qualified", "passive_unlock",
        "awg_set_qualified", "automated_flash",
    )
    if any(name in symbols for name in forbidden):
        raise AuditError("generic qualification/unlock entry point is linked")

    image_strings = run([strings, str(elf)])
    required_strings = (
        "QUAL-407",
        "armed: binary ownership begins after this prompt",
        "unplug USB to recover shell",
        "qualification-only",
        "stream=locked",
        "capture=locked",
    )
    if any(value not in image_strings for value in required_strings):
        raise AuditError("qualification identity/safety strings are incomplete")

    request = disassemble(objdump, elf, "zs407_usb_transport_start")
    if "zs407_transport_lifecycle_request" not in request:
        raise AuditError("shell request does not enter the lifecycle")
    if "chThdCreateStatic" in request or "zs407_passive_runtime_start_stream" in request:
        raise AuditError("sweep-thread request starts a worker or passive stream")
    if lifecycle_address not in request or "#6" not in request:
        raise AuditError("request lacks lifecycle address or qualification refusal")

    complete = disassemble(
        objdump, elf, "zs407_usb_transport_complete_handoff")
    ordered_calls(complete, (
        "zs407_transport_lifecycle_begin",
        "zs407_stream_parser_init",
        "chThdCreateStatic",
        "zs407_transport_lifecycle_activate",
    ))
    if ownership_address not in complete:
        raise AuditError("handoff does not write the private ownership byte")
    if complete.count("zs407_transport_lifecycle_fail") < 2:
        raise AuditError("handoff failure paths are incomplete")
    if "zs407_passive_runtime_start_stream" in complete:
        raise AuditError("transport handoff starts passive streaming")

    shell = disassemble(objdump, elf, "myshellThread")
    ordered_calls(shell, (
        "zs407_usb_transport_handoff_requested",
        "zs407_usb_transport_complete_handoff",
    ))
    if "shell_printf" not in shell:
        raise AuditError("shell does not retain an explicit completion failure path")

    main = disassemble(objdump, elf, "main")
    guard_rows = [line for line in main.splitlines()
                  if "<zs407_usb_transport_shell_may_spawn>" in line]
    create_rows = [line for line in main.splitlines()
                   if "<chThdCreateStatic>" in line]
    if len(guard_rows) != 1 or len(create_rows) < 2:
        raise AuditError("main shell guard/thread creation calls are incomplete")
    guard_address = int(guard_rows[0].split(":", 1)[0].strip(), 16)
    shell_create_address = int(create_rows[-1].split(":", 1)[0].strip(), 16)
    guard_tail = main[main.find(guard_rows[0]):]
    branch_targets = [int(value, 16) for value in re.findall(
        r"\bb(?:\.n)?\s+([0-9a-f]+)\b", guard_tail)]
    if guard_address <= shell_create_address or not any(
            shell_create_address - 64 <= target <= shell_create_address
            for target in branch_targets):
        raise AuditError("main does not branch from the ownership guard to shell creation")

    worker = disassemble(objdump, elf, "transport_worker")
    required_worker = (
        "zs407_transport_lifecycle_binary_active",
        "usb_link_active",
        "ibqGetFullBufferTimeout",
        "zs407_stream_parser_feed",
        "ibqReleaseEmptyBuffer",
        "zs407_transport_lifecycle_disconnect",
        "zs407_transport_lifecycle_fail",
    )
    if any(name not in worker for name in required_worker):
        raise AuditError("worker lifecycle/parser/recovery path is incomplete")
    if "VNAShell_readLine" in worker or "streamRead" in worker:
        raise AuditError("binary worker shares the legacy shell reader")

    handler = disassemble(objdump, elf, "handle_frame")
    required_handler = (
        "send_response", "send_status", "zs407_release_manifest_for_phase",
        "zs407_passive_runtime_status",
    )
    if any(name not in handler for name in required_handler):
        raise AuditError("binary request/response dispatch is incomplete")
    forbidden_handler = (
        "zs407_passive_runtime_start_stream",
        "zs407_passive_runtime_arm_capture",
        "zs407_awg_start", "set_mode", "set_sweep_frequency",
    )
    if any(name in handler for name in forbidden_handler):
        raise AuditError("transport-only handler reaches an execution path")

    bounded_write = disassemble(objdump, elf, "bounded_usb_write")
    if "obqWriteTimeout" not in bounded_write:
        raise AuditError("binary TX is not bounded by an output-queue timeout")
    if "streamWrite" in bounded_write:
        raise AuditError("binary TX retained an infinite stream write")

    receive_isr = disassemble(objdump, elf, "sduDataReceived")
    if "zs407_stream_parser" in receive_isr or "zs407_crc32" in receive_isr:
        raise AuditError("USB receive ISR performs protocol/CRC work")

    return (
        "transport_qualification_audit=passed\n"
        "qualification_mode=compile-time-profile-only\n"
        "handoff=prompt-then-shell-exit\n"
        "usb_readers=single-owner-state-machine\n"
        "handoff_reentry=same-boot-refused\n"
        "disconnect_recovery=shell-reenabled\n"
        "binary_tx=bounded-output-queue-timeout\n"
        "passive_stream=locked\n"
        "zero_span_capture=locked\n"
        "rf_and_awg_execution=locked\n"
        "usb_isr_protocol_work=absent\n"
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
