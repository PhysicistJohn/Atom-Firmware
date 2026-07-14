#!/usr/bin/env python3
"""Generate the absolute-SRAM profile consumed by ZS407TwinStatus."""

from __future__ import annotations

import argparse
import hashlib
import pathlib
import subprocess
import sys


PROFILE_SYMBOLS = (
    ("last_touch_x", "last_touch_x"),
    ("last_touch_y", "last_touch_y"),
    ("ui_mode", "ui_mode"),
    ("setting", "setting"),
    ("sweep_mode", "sweep_mode"),
    ("in_selftest", "in_selftest"),
    ("selftest_status", "test_status"),
    ("selftest_fail_cause", "test_fail_cause"),
    ("selftest_wait", "test_wait"),
    ("peak_frequency", "peakFreq"),
    ("peak_level", "peakLevel"),
    ("peak_index", "peakIndex"),
    ("shell_function", "shell_function"),
    ("shell_line", "shell_line"),
    ("shell_nargs", "shell_nargs"),
    ("shell_stream", "shell_stream"),
    ("measured", "measured"),
    ("actual_rbw_x10", "actual_rbw_x10"),
    ("dirty", "dirty"),
    ("scan_dirty", "scandirty"),
    ("completed", "completed"),
    ("sweep_counter", "sweep_counter"),
    ("avoid_setting", "avoid_setting"),
    ("frequency_start", "frequencyStart"),
    ("frequency_stop", "frequencyStop"),
    ("frequency_count", "_f_count"),
    ("frequency_delta", "_f_delta"),
    ("frequency_error", "_f_error"),
    ("frequency_start_internal", "_f_start"),
)


def parse_int(value: str) -> int:
    return int(value, 0)


def read_symbols(nm: pathlib.Path, elf: pathlib.Path) -> dict[str, int]:
    result = subprocess.run(
        [str(nm), "-n", "-S", str(elf)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    symbols: dict[str, int] = {}
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) < 4:
            continue
        try:
            address = int(fields[0], 16)
            int(fields[1], 16)
        except ValueError:
            continue
        symbols[fields[3]] = address
    return symbols


def require(symbols: dict[str, int], name: str) -> int:
    try:
        return symbols[name]
    except KeyError as error:
        raise SystemExit(f"required ELF symbol is missing: {name}") from error


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--elf", required=True, type=pathlib.Path)
    parser.add_argument("--nm", required=True, type=pathlib.Path)
    parser.add_argument("--output", type=pathlib.Path)
    parser.add_argument("--profile-name", default="generated")
    parser.add_argument(
        "--chibios-current-thread-offset",
        type=parse_int,
        required=True,
        help="offsetof(os_instance_t, rlist.current), derived from ELF DWARF",
    )
    parser.add_argument(
        "--frequency-cache-address",
        type=parse_int,
        default=0x10000000,
        help="bridge scratch address when the ELF has no _f_cache symbol",
    )
    args = parser.parse_args()

    symbols = read_symbols(args.nm, args.elf)
    values = [
        ("chibios_current_thread", require(symbols, "ch0") + args.chibios_current_thread_offset)
    ]
    values.extend((profile_key, require(symbols, elf_symbol)) for profile_key, elf_symbol in PROFILE_SYMBOLS)
    values.append(("frequency_cache", symbols.get("_f_cache", args.frequency_cache_address)))

    digest = hashlib.sha256(args.elf.read_bytes()).hexdigest()
    lines = [
        f"# Generated from {args.elf.name} for {args.profile_name}.",
        f"# ELF SHA-256: {digest}",
        "# chibios_current_thread uses ch0 + the supplied DWARF-derived offset.",
    ]
    lines.extend(f"{key}=0x{value:08X}" for key, value in values)
    encoded = "\n".join(lines) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="ascii")
    else:
        sys.stdout.write(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
