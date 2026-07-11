#!/usr/bin/env python3
"""Compile a deterministic, output-safe ZS407 waveform event program."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
from pathlib import Path
import re
import struct
import sys
import zlib


MAGIC = b"ZSAW"
VERSION = 1
HEADER = struct.Struct("<4sBBHI")
EVENT = struct.Struct("<IBBHq")
MAX_EVENTS = 0xFFFF

OP_GATE = 0
OP_FREQUENCY_HZ = 1
OP_LEVEL_DBM_X10 = 2
OP_DAC_SAMPLE = 3
OP_WAIT_TRIGGER = 4
OP_END = 5

QUANTITY = re.compile(r"^([+-]?\d+(?:\.\d+)?)([A-Za-z]+)$")


class CompileError(ValueError):
    pass


@dataclass(frozen=True)
class WaveEvent:
    at_us: int
    opcode: int
    value: int

    def pack(self) -> bytes:
        return EVENT.pack(self.at_us, self.opcode, 0, 0, self.value)


def scaled_integer(token: str, scales: dict[str, Decimal], what: str) -> int:
    match = QUANTITY.fullmatch(token)
    if match is None or match.group(2) not in scales:
        units = ", ".join(scales)
        raise CompileError(f"invalid {what} {token!r}; expected units: {units}")
    try:
        value = Decimal(match.group(1)) * scales[match.group(2)]
    except InvalidOperation as error:
        raise CompileError(f"invalid {what} {token!r}") from error
    integral = value.to_integral_value()
    if value != integral:
        raise CompileError(f"{what} {token!r} is not exactly representable")
    return int(integral)


def parse_time(token: str) -> int:
    value = scaled_integer(
        token,
        {"us": Decimal(1), "ms": Decimal(1000), "s": Decimal(1000000)},
        "time",
    )
    if not 0 <= value <= 0xFFFFFFFF:
        raise CompileError("time is outside the uint32 microsecond range")
    return value


def parse_frequency(token: str) -> int:
    value = scaled_integer(
        token,
        {
            "Hz": Decimal(1),
            "kHz": Decimal(1000),
            "MHz": Decimal(1000000),
            "GHz": Decimal(1000000000),
        },
        "frequency",
    )
    if not 0 <= value <= 12_000_000_000:
        raise CompileError("frequency must be between 0 Hz and 12 GHz")
    return value


def parse_level(token: str) -> int:
    value = scaled_integer(token, {"dBm": Decimal(10)}, "level")
    if not -1200 <= value <= 100:
        raise CompileError("level must be between -120.0 dBm and +10.0 dBm")
    return value


def parse_source(source: str) -> list[WaveEvent]:
    events: list[WaveEvent] = []
    for line_number, raw_line in enumerate(source.splitlines(), 1):
        line = raw_line.partition("#")[0].strip()
        if not line:
            continue
        words = line.split()
        try:
            if len(words) < 3 or words[0] != "at":
                raise CompileError("expected: at TIME ACTION [VALUE]")
            at_us = parse_time(words[1])
            action = words[2]
            if action == "gate" and len(words) == 4:
                if words[3] not in ("off", "on"):
                    raise CompileError("gate value must be off or on")
                event = WaveEvent(at_us, OP_GATE, int(words[3] == "on"))
            elif action == "frequency" and len(words) == 4:
                event = WaveEvent(at_us, OP_FREQUENCY_HZ,
                                  parse_frequency(words[3]))
            elif action == "level" and len(words) == 4:
                event = WaveEvent(at_us, OP_LEVEL_DBM_X10,
                                  parse_level(words[3]))
            elif action == "dac" and len(words) == 4:
                sample = int(words[3], 10)
                if not 0 <= sample <= 4095:
                    raise CompileError("DAC sample must be between 0 and 4095")
                event = WaveEvent(at_us, OP_DAC_SAMPLE, sample)
            elif action == "wait-trigger" and len(words) == 3:
                event = WaveEvent(at_us, OP_WAIT_TRIGGER, 0)
            elif action == "end" and len(words) == 3:
                event = WaveEvent(at_us, OP_END, 0)
            else:
                raise CompileError(f"unknown or malformed action {action!r}")
        except (CompileError, ValueError) as error:
            raise CompileError(f"line {line_number}: {error}") from error
        events.append(event)
    validate(events)
    return events


def validate(events: list[WaveEvent]) -> None:
    if not 2 <= len(events) <= MAX_EVENTS:
        raise CompileError("program must contain between 2 and 65535 events")
    if events[0] != WaveEvent(0, OP_GATE, 0):
        raise CompileError("first event must be 'at 0us gate off'")
    gate_on = False
    previous_time = 0
    for index, event in enumerate(events):
        if event.at_us < previous_time:
            raise CompileError(f"event {index + 1} moves backward in time")
        previous_time = event.at_us
        if event.opcode == OP_GATE:
            gate_on = bool(event.value)
        elif event.opcode == OP_WAIT_TRIGGER and gate_on:
            raise CompileError("wait-trigger is forbidden while the gate is on")
        elif event.opcode == OP_END and (
            index != len(events) - 1 or gate_on or event.value != 0
        ):
            raise CompileError("end must be last and the gate must be off")
    if events[-1].opcode != OP_END or gate_on:
        raise CompileError("program must end with the gate off and an end event")


def compile_program(source: str) -> tuple[bytes, list[WaveEvent]]:
    events = parse_source(source)
    payload = b"".join(event.pack() for event in events)
    header = HEADER.pack(MAGIC, VERSION, EVENT.size, len(events),
                         zlib.crc32(payload))
    return header + payload, events


def inspect(program: bytes) -> str:
    if len(program) < HEADER.size:
        raise CompileError("program is shorter than the header")
    magic, version, event_size, count, expected_crc = HEADER.unpack_from(program)
    payload = program[HEADER.size:]
    if magic != MAGIC or version != VERSION or event_size != EVENT.size:
        raise CompileError("unsupported waveform header")
    if len(payload) != count * EVENT.size:
        raise CompileError("event count does not match program length")
    if zlib.crc32(payload) != expected_crc:
        raise CompileError("payload CRC mismatch")
    return (
        f"format=ZSAW/{version} events={count} bytes={len(program)} "
        f"payload_crc32={expected_crc:08x} sha256={hashlib.sha256(program).hexdigest()}"
    )


def self_test() -> None:
    safe = """\
at 0us gate off
at 0us frequency 100MHz
at 0us level -30.0dBm
at 1ms gate on
at 11ms gate off
at 11ms end
"""
    first, events = compile_program(safe)
    second, _ = compile_program(safe)
    assert first == second
    assert len(first) == HEADER.size + 6 * EVENT.size
    assert hashlib.sha256(first).hexdigest() == (
        "e975e3b504b49fd4accb5d96f325ce7ec27d7190ccf19b3a8cf2e02052e8ad61"
    )
    assert events[1].pack() == EVENT.pack(0, OP_FREQUENCY_HZ, 0, 0,
                                          100_000_000)
    assert inspect(first).startswith("format=ZSAW/1 events=6 bytes=108 ")
    try:
        compile_program("at 0us gate on\nat 1ms end\n")
    except CompileError:
        pass
    else:
        raise AssertionError("unsafe initial gate was accepted")
    try:
        compile_program("at 0us gate off\nat 1ms gate on\nat 2ms end\n")
    except CompileError:
        pass
    else:
        raise AssertionError("active gate at end was accepted")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", nargs="?", type=Path)
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument("--inspect", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
            print("waveform compiler self-test: passed")
            return 0
        if args.input is None:
            parser.error("INPUT is required unless --self-test is used")
        if args.inspect:
            print(inspect(args.input.read_bytes()))
            return 0
        if args.output is None:
            parser.error("--output is required when compiling")
        program, _ = compile_program(args.input.read_text(encoding="utf-8"))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(program)
        print(inspect(program))
        return 0
    except (CompileError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
