#!/usr/bin/env python3
"""Run the bounded physical checks for unpublished tinySA fixes 4 through 7.

This program never flashes firmware, enters DFU, saves configuration, resets
the unit, changes a correction table, or enables an RF output. It requires an
exact expected firmware identity and writes a command transcript after every
completed exchange.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import re
import sys
import time

try:
    import serial
except ModuleNotFoundError:
    serial = None


PROMPT = b"ch> "
MAX_COMMAND_BYTES = 47


def visible(data: bytes) -> str:
    rendered: list[str] = []
    for value in data:
        if value in (9, 10, 13) or 32 <= value < 127:
            rendered.append(chr(value))
        else:
            rendered.append(f"\\x{value:02x}")
    return "".join(rendered)


class QualificationSession:
    def __init__(self, port_name: str, package: int, expected: str,
                 transcript_path: Path) -> None:
        self.package = package
        self.expected = expected
        self.transcript_path = transcript_path
        self.entries: list[tuple[str, bytes]] = []
        self.result = "INCOMPLETE"
        self.started = datetime.now(timezone.utc).isoformat()
        if serial is None:
            raise RuntimeError(
                "pyserial 3.5 is required; use the hardware-test virtual "
                "environment documented in docs/UPSTREAM_HARDWARE_BATCH.md"
            )
        self.port = serial.Serial()
        self.port.port = port_name
        self.port.baudrate = 115200
        self.port.timeout = 0.05
        self.port.write_timeout = 1.0
        self.port.rts = False
        self.port.dtr = False
        self.port.exclusive = True

    def persist(self) -> None:
        lines = [
            f"# tinySA upstream package {self.package} hardware transcript",
            "",
            f"- Started UTC: `{self.started}`",
            f"- Expected version: `{self.expected}`",
            f"- Result: **{self.result}**",
            "",
        ]
        for command, response in self.entries:
            lines.extend((f"## `{command or '<connect>'}`", "", "```text",
                          visible(response).rstrip(), "```", ""))
        self.transcript_path.parent.mkdir(parents=True, exist_ok=True)
        self.transcript_path.write_text("\n".join(lines), encoding="utf-8")

    def read_until_prompt(self, timeout: float) -> bytes:
        deadline = time.monotonic() + timeout
        response = bytearray()
        while time.monotonic() < deadline:
            chunk = self.port.read(max(self.port.in_waiting, 1))
            if chunk:
                response.extend(chunk)
                if response.endswith(PROMPT):
                    return bytes(response)
            else:
                time.sleep(0.01)
        raise TimeoutError(
            f"prompt not received within {timeout:.1f}s: {response!r}"
        )

    def connect(self) -> None:
        self.port.open()
        time.sleep(0.25)
        self.port.write(b"\r")
        self.port.flush()
        response = self.read_until_prompt(5.0)
        self.entries.append(("", response))
        self.persist()

    def command(self, command: str, timeout: float = 20.0) -> bytes:
        encoded = command.encode("ascii")
        if len(encoded) > MAX_COMMAND_BYTES:
            raise ValueError(
                f"command is {len(encoded)} bytes; firmware accepts at most "
                f"{MAX_COMMAND_BYTES}"
            )
        self.port.write(encoded + b"\r")
        self.port.flush()
        response = self.read_until_prompt(timeout)
        self.entries.append((command, response))
        self.persist()
        print(f"=== {command} ===")
        print(visible(response), end="" if response.endswith(b"\n") else "\n")
        return response

    def close(self) -> None:
        if self.port.is_open:
            self.port.close()
        self.persist()


def require(response: bytes, expected: bytes, command: str) -> None:
    if expected not in response:
        raise AssertionError(
            f"{command!r} did not contain {expected!r}: {response!r}"
        )


def numeric_lines(response: bytes) -> list[int]:
    values: list[int] = []
    for line in response.replace(b"\r", b"").split(b"\n"):
        if re.fullmatch(rb"[0-9]+", line):
            values.append(int(line))
    return values


def correction_lines(response: bytes) -> list[bytes]:
    return [line for line in response.replace(b"\r", b"").split(b"\n")
            if line.startswith(b"correction low ")]


def palette_lines(response: bytes) -> list[bytes]:
    return [line.strip() for line in response.replace(b"\r", b"").split(b"\n")
            if re.fullmatch(rb"\s*[0-9]+:\s+0x[0-9a-fA-F]+", line)]


def query_legacy_points(session: QualificationSession) -> int:
    response = session.command("s")
    match = re.search(rb"s=(-?[0-9]+)", response)
    if match is None:
        raise AssertionError(f"legacy point query was not recognized: {response!r}")
    return int(match.group(1))


def qualify_package_4(session: QualificationSession) -> None:
    original_points = query_legacy_points(session)
    try:
        session.command("s 2")
        if query_legacy_points(session) != 2:
            raise AssertionError("legacy point count did not accept boundary 2")
        for value in ("1", "0", "-1", "2147483648"):
            response = session.command(f"s {value}")
            require(response, b"sweep point count is invalid", f"s {value}")
        if query_legacy_points(session) != 2:
            raise AssertionError("invalid legacy counts changed the active value")

        valid_scan = session.command("scan 1000000 1001000 2", timeout=30.0)
        if b"exceeds range" in valid_scan:
            raise AssertionError("two-point scan was rejected")
        for value in ("1", "0", "-1", "451"):
            command = f"scan 1000000 1001000 {value}"
            require(session.command(command), b"sweep points exceeds range", command)

        for value in ("0", "-1", "4294967296"):
            command = f"scanraw 1000000 1001000 {value}"
            require(session.command(command), b"scan point count is invalid", command)
        response = session.command("scanraw 1000000 1001000 1", timeout=30.0)
        start = response.find(b"{")
        end = response.rfind(b"}")
        frame = response[start:end + 1]
        if start < 0 or end < start or frame[0:2] != b"{x" or len(frame) != 5:
            raise AssertionError(f"one-point scanraw frame is malformed: {response!r}")
    finally:
        if original_points >= 2 and session.port.is_open:
            try:
                session.command(f"s {original_points}")
            except Exception:
                # Preserve the primary failure. This value is RAM-only and the
                # required power cycle discards it if transport was lost.
                pass


def qualify_package_5(session: QualificationSession) -> None:
    before = correction_lines(session.command("correction low"))
    if len(before) != 20:
        raise AssertionError(f"expected 20 low correction rows, found {len(before)}")
    commands = (
        "correction",
        "correction invalid",
        "correction invalid reset",
        "correction off reset",
        "correction low -1 1000000 0",
        "correction low 20 1000000 0",
    )
    for command in commands:
        require(session.command(command), b"correction ", command)
    after = correction_lines(session.command("correction low"))
    if after != before:
        raise AssertionError("invalid correction commands changed the low table")


def qualify_package_6(session: QualificationSession) -> None:
    before = palette_lines(session.command("color"))
    if len(before) != 32:
        raise AssertionError(f"expected 32 palette rows, found {len(before)}")

    trace_commands = (
        "trace 1 copy 0",
        "trace 1 copy 5",
        "trace 1 subtract 0",
        "trace 1 subtract 5",
        "trace 1 value -1 0",
        "trace 1 value 65535 0",
    )
    for command in trace_commands:
        require(session.command(command), b"trace {", command)

    marker_commands = (
        # TINYSA4 exposes eight markers; user-facing marker 9 is the first
        # out-of-range value. (The smaller TINYSA3 exposes four.)
        "marker 1 delta 9",
        "marker 1 trace 0",
        "marker 1 trace 5",
    )
    for command in marker_commands:
        require(session.command(command), b"marker [n]", command)

    session.command("color -1 ff00ff")
    session.command("color 32 ff00ff")
    after = palette_lines(session.command("color"))
    if after != before:
        raise AssertionError("invalid palette indices changed the palette")

    session.command("menu -1")
    session.command("menu 9999")


def qualify_package_7(session: QualificationSession) -> None:
    before = numeric_lines(session.command("frequencies", timeout=30.0))
    if len(before) < 2:
        raise AssertionError("could not capture the current frequency grid")
    start = before[0]
    stop = before[-1]

    long_argument = "12345678901234567890123456789012345678901"
    command = f"text {long_argument}"
    if len(command.encode("ascii")) != 46:
        raise AssertionError("maximum-line test vector changed unexpectedly")
    try:
        session.command("menu 3 3")
        session.command(command)
        session.command("version")
    finally:
        if session.port.is_open:
            try:
                # A clamped CENTER value can shrink the active span. Restore
                # both endpoints so the complete grid is reconstructed.
                session.command("menu 3 1")
                session.command(f"text {start}")
                session.command("menu 3 2")
                session.command(f"text {stop}")
            except Exception:
                # Preserve the primary failure. These settings are RAM-only
                # and the required power cycle discards them if transport was
                # lost.
                pass
    after = numeric_lines(session.command("frequencies", timeout=30.0))
    if after != before:
        raise AssertionError("frequency grid was not restored after keypad test")


QUALIFIERS = {
    4: qualify_package_4,
    5: qualify_package_5,
    6: qualify_package_6,
    7: qualify_package_7,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True)
    parser.add_argument("--package", required=True, type=int, choices=QUALIFIERS)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--transcript", required=True, type=Path)
    parser.add_argument(
        "--confirm",
        required=True,
        choices=("TARGETED-RAM-ONLY-TEST",),
        help="acknowledge that bounded RAM-only shell tests will run",
    )
    args = parser.parse_args()

    session = QualificationSession(
        args.port, args.package, args.expected_version, args.transcript
    )
    try:
        session.connect()
        session.command("output off")
        session.command("mode input")
        version = session.command("version")
        require(version, args.expected_version.encode("ascii"), "version")
        session.command("info")
        session.command("vbat")
        QUALIFIERS[args.package](session)
        session.command("output off")
        final_version = session.command("version")
        require(final_version, args.expected_version.encode("ascii"), "version")
        session.result = "PASS"
        session.persist()
        print(f"package {args.package}: PASS")
        print(f"transcript: {args.transcript}")
        return 0
    except Exception as error:
        session.result = f"FAIL: {error}"
        session.persist()
        print(f"package {args.package}: FAIL: {error}", file=sys.stderr)
        return 1
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
