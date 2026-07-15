#!/usr/bin/env python3
"""Capture the fourteen physical tinySA4 self-test result screens.

This program deliberately contains no DFU or flashing support.  It starts one
positive-argument factory self-test case at a time, waits a conservative fixed
interval, proves that two full LCD readbacks are byte-identical, records the
read-only shell state, and acknowledges the retained result with the remote
touch controls.

The LCD ``capture`` command returns panel-order RGB565 (most-significant byte
first).  The authoritative panel bytes are retained, while ``case-XX.rgb565``
is byte-swapped to the little-endian format used by the Renode visual tools.
"""

from __future__ import annotations

import argparse
import binascii
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import struct
import sys
import time
from typing import Any, Callable, Iterable
import zlib


WIDTH = 480
HEIGHT = 320
PIXEL_BYTES = WIDTH * HEIGHT * 2
PROMPT = b"ch> "
CAPTURE_ECHO = b"capture\r\n"
DEFAULT_VID = 0x0483
DEFAULT_PID = 0x5740
EXPECTED_POINTS = 450
NONFLAT_CASES = frozenset((1, 2, 3, 4, 5, 6, 7, 8, 10, 11, 14))
CONFIRMATION = "CAL-RF-LOOPBACK-CONNECTED"
KNOWN_VARIANT_VERSIONS = {
    "official-c979": "tinySA4_v1.4-224-gc979386",
    "rc5": "tinySA4_v0.4-chibios21-rc5",
}
FLOAT_PATTERN = rb"[-+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][-+]?[0-9]+)?"
# The firmware's compact etoa() stops normalizing at a mantissa equal to 10,
# then emits that value as a single digit.  ASCII '0' + 10 is ':', so an
# exact power of ten can be rendered as (for example) -:.000000e+01 instead
# of -1.000000e+02.  Keep this workaround deliberately narrower than the
# general float grammar: cmd_data uses exactly six fractional digits and a
# signed two-digit exponent.
CHPRINTF_ETOA_POWER_OF_TEN_PATTERN = re.compile(
    rb"(?P<sign>-?):\.000000e(?P<exponent_sign>[+-])(?P<exponent>[0-9]{2})"
)
DATA_TRACE_NUMBERS = (4, 2, 1)
CORRECTION_TABLES = (
    "low", "lna", "ultra", "ultra_lna", "direct", "direct_lna",
    "harm", "harm_lna", "out", "out_direct", "out_adf", "out_ultra",
)


def load_screen_tool() -> Any:
    """Load the existing capture decoder without making it an import package."""
    path = Path(__file__).with_name("capture-zs407-screen.py")
    spec = importlib.util.spec_from_file_location("zs407_screen_capture", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load screen capture support from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SCREEN_TOOL = load_screen_tool()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def visible(payload: bytes) -> str:
    rendered: list[str] = []
    for value in payload:
        if value in (9, 10, 13) or 32 <= value < 127:
            rendered.append(chr(value))
        else:
            rendered.append(f"\\x{value:02x}")
    return "".join(rendered)


def rgb565be_to_rgb565le(frame: bytes) -> bytes:
    if len(frame) != PIXEL_BYTES:
        raise ValueError(f"frame has {len(frame)} bytes; expected {PIXEL_BYTES}")
    swapped = bytearray(len(frame))
    swapped[0::2] = frame[1::2]
    swapped[1::2] = frame[0::2]
    return bytes(swapped)


def png_chunk(kind: bytes, payload: bytes) -> bytes:
    body = kind + payload
    return struct.pack(">I", len(payload)) + body + struct.pack(">I", binascii.crc32(body) & 0xFFFFFFFF)


def rgb565be_to_png(frame: bytes) -> bytes:
    """Encode a panel-order frame as a deterministic truecolor PNG."""
    ppm = SCREEN_TOOL.rgb565be_to_ppm(frame)
    header = f"P6\n{WIDTH} {HEIGHT}\n255\n".encode("ascii")
    if not ppm.startswith(header):
        raise ValueError("screen decoder returned an unexpected PPM header")
    rgb = ppm[len(header):]
    stride = WIDTH * 3
    scanlines = b"".join(
        b"\x00" + rgb[offset:offset + stride]
        for offset in range(0, len(rgb), stride)
    )
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", WIDTH, HEIGHT, 8, 2, 0, 0, 0)
    return signature + png_chunk(b"IHDR", ihdr) + png_chunk(
        b"IDAT", zlib.compress(scanlines, 9)
    ) + png_chunk(b"IEND", b"")


def frame_metrics(frame: bytes) -> dict[str, int]:
    if len(frame) != PIXEL_BYTES:
        raise ValueError(f"frame has {len(frame)} bytes; expected {PIXEL_BYTES}")
    values = [
        (frame[offset] << 8) | frame[offset + 1]
        for offset in range(0, len(frame), 2)
    ]
    unique = len(set(values))
    nonblack = sum(value != 0 for value in values)
    if unique < 4 or nonblack < 1000:
        raise AssertionError(
            f"captured result is not a populated LCD frame: colors={unique} "
            f"nonblack_pixels={nonblack}"
        )
    return {"unique_rgb565_colors": unique, "nonblack_pixels": nonblack}


def parse_case_set(specification: str) -> list[int]:
    selected: set[int] = set()
    for item in specification.split(","):
        item = item.strip()
        if not item:
            raise ValueError("empty item in --cases")
        if "-" in item:
            fields = item.split("-", 1)
            if not all(field.isdigit() for field in fields):
                raise ValueError(f"invalid case range: {item}")
            start, end = (int(field) for field in fields)
            if start > end:
                raise ValueError(f"descending case range: {item}")
            selected.update(range(start, end + 1))
        else:
            if not item.isdigit():
                raise ValueError(f"invalid case index: {item}")
            selected.add(int(item))
    if not selected or min(selected) < 0 or max(selected) > 13:
        raise ValueError("self-test case indices must be within 0..13")
    return sorted(selected)


def parse_frequency_response(response: bytes) -> list[int]:
    values: list[int] = []
    for line in response.replace(b"\r", b"").split(b"\n"):
        if re.fullmatch(rb"[0-9]+", line):
            values.append(int(line))
    return values


def parse_trace_response(response: bytes, trace: int) -> list[float]:
    pattern = re.compile(
        rb"trace " + str(trace).encode("ascii")
        + rb" value ([0-9]+) (" + FLOAT_PATTERN + rb")"
    )
    indexed: dict[int, float] = {}
    for line in response.replace(b"\r", b"").split(b"\n"):
        match = pattern.fullmatch(line)
        if match:
            indexed[int(match.group(1))] = float(match.group(2))
    expected = list(range(len(indexed)))
    if sorted(indexed) != expected:
        raise AssertionError(
            f"trace {trace} indices are incomplete: found {len(indexed)} contiguous points"
        )
    return [indexed[index] for index in expected]


def parse_data_response(
    response: bytes,
    formatter_defects: list[dict[str, Any]] | None = None,
) -> list[float]:
    pattern = re.compile(FLOAT_PATTERN)
    values: list[float] = []
    for line in response.replace(b"\r", b"").split(b"\n"):
        if pattern.fullmatch(line):
            values.append(float(line))
            continue
        defect = CHPRINTF_ETOA_POWER_OF_TEN_PATTERN.fullmatch(line)
        if defect:
            exponent = int(defect.group("exponent"))
            if defect.group("exponent_sign") == b"-":
                exponent = -exponent
            decoded = 10.0 ** (exponent + 1)
            if defect.group("sign") == b"-":
                decoded = -decoded
            if not math.isfinite(decoded):
                raise AssertionError(
                    f"known chprintf etoa defect overflows: {line!r}"
                )
            point_index = len(values)
            values.append(decoded)
            if formatter_defects is not None:
                formatter_defects.append({
                    "kind": "chprintf-etoa-power-of-ten",
                    "point_index": point_index,
                    "raw_ascii": line.decode("ascii"),
                    "decoded_value": decoded,
                })
            continue
        if not line or line == PROMPT or re.fullmatch(rb"data [0-2]", line):
            continue
        raise AssertionError(f"data response contains malformed line: {line!r}")
    return values


def validate_data_formatter_defects(
    plane: int,
    defects: list[dict[str, Any]],
    traces: list[list[float]],
) -> list[dict[str, Any]]:
    """Cross-check a narrowly decoded cmd_data token against cmd_trace."""
    if plane < 0 or plane >= len(DATA_TRACE_NUMBERS):
        raise ValueError(f"invalid data plane: {plane}")
    trace_number = DATA_TRACE_NUMBERS[plane]
    trace_values = traces[trace_number - 1]
    validated: list[dict[str, Any]] = []
    for defect in defects:
        point_index = int(defect["point_index"])
        if point_index < 0 or point_index >= len(trace_values):
            raise AssertionError(
                f"data {plane} formatter defect point {point_index} has no "
                f"trace {trace_number} counterpart"
            )
        decoded = float(defect["decoded_value"])
        trace_value = trace_values[point_index]
        delta = abs(decoded - trace_value)
        if delta > 0.011:
            raise AssertionError(
                f"data {plane} formatter defect at point {point_index} decoded "
                f"as {decoded}, but trace {trace_number} reports {trace_value}"
            )
        record = dict(defect)
        record.update({
            "data_plane": plane,
            "mapped_trace": trace_number,
            "mapped_trace_value": trace_value,
            "absolute_delta": delta,
            "trace_cross_check": "PASS",
        })
        validated.append(record)
    return validated


def trace_metrics(values: list[float]) -> dict[str, float | int]:
    finite = [value for value in values if math.isfinite(value)]
    if not finite:
        return {"points": len(values), "finite": 0, "minimum": math.nan,
                "maximum": math.nan, "range": math.nan}
    minimum = min(finite)
    maximum = max(finite)
    return {
        "points": len(values),
        "finite": len(finite),
        "minimum": minimum,
        "maximum": maximum,
        "range": maximum - minimum,
    }


@dataclass
class UsbIdentity:
    vid: int
    pid: int
    serial_number: str | None
    location: str | None


class PortLocator:
    """Resolve one USB CDC device and follow its path after re-enumeration."""

    def __init__(self, requested: str, vid: int, pid: int,
                 usb_serial: str | None, timeout: float,
                 event: Callable[[str], None]) -> None:
        self.requested = requested
        self.vid = vid
        self.pid = pid
        self.usb_serial = usb_serial
        self.timeout = timeout
        self.event = event
        self.identity: UsbIdentity | None = None
        self.current: str | None = None
        self.history: list[str] = []

    @staticmethod
    def _ports() -> list[Any]:
        try:
            from serial.tools import list_ports
        except ModuleNotFoundError as error:
            raise RuntimeError(
                "pyserial 3.5 is required; install tools/requirements-hardware-test.txt"
            ) from error
        return list(list_ports.comports())

    def _matching_ports(self) -> list[Any]:
        ports = self._ports()
        if self.identity is None and self.requested != "auto":
            # An explicit path is strict: never fall back to a different
            # matching analyzer when the requested path is absent.  Return the
            # descriptor at that path (if any) so resolve() can fail with the
            # exact VID/PID/serial mismatch before opening it.
            return [port for port in ports if port.device == self.requested]
        usb = [port for port in ports if port.vid == self.vid and port.pid == self.pid]
        if self.usb_serial is not None:
            usb = [port for port in usb if port.serial_number == self.usb_serial]
        if self.identity is not None and self.identity.serial_number:
            return [
                port for port in usb
                if port.serial_number == self.identity.serial_number
            ]
        if self.identity is not None and self.identity.location:
            return [
                port for port in usb if port.location == self.identity.location
            ]
        return usb

    def resolve(self) -> str:
        deadline = time.monotonic() + self.timeout
        last_description = "no matching USB CDC port"
        while time.monotonic() < deadline:
            matches = self._matching_ports()
            if len(matches) == 1:
                port = matches[0]
                if port.vid != self.vid or port.pid != self.pid:
                    raise RuntimeError(
                        f"{port.device} is {port.vid!r}:{port.pid!r}, not "
                        f"{self.vid:04x}:{self.pid:04x}"
                    )
                if (
                    self.usb_serial is not None
                    and port.serial_number != self.usb_serial
                ):
                    raise RuntimeError(
                        f"{port.device} USB serial is {port.serial_number!r}, not "
                        f"the required {self.usb_serial!r}"
                    )
                if self.identity is None:
                    self.identity = UsbIdentity(
                        int(port.vid), int(port.pid), port.serial_number,
                        port.location,
                    )
                if port.device != self.current:
                    previous = self.current
                    self.current = port.device
                    self.history.append(port.device)
                    self.event(
                        f"serial_port={port.device} previous={previous or 'none'} "
                        f"usb_serial={port.serial_number or 'unknown'}"
                    )
                return port.device
            if len(matches) > 1:
                last_description = "multiple matches: " + ", ".join(
                    port.device for port in matches
                )
            time.sleep(0.25)
        raise TimeoutError(
            f"USB CDC port did not resolve within {self.timeout:.1f}s: "
            f"{last_description}"
        )


class EvidenceStore:
    def __init__(self, output: Path, variant: str, expected_version: str,
                 cases: list[int], arguments: dict[str, Any]) -> None:
        if output.exists() and any(output.iterdir()):
            raise RuntimeError(
                f"output directory is not empty: {output}; use a new evidence directory"
            )
        output.mkdir(parents=True, exist_ok=True)
        self.output = output
        self.log_path = output / "run.log"
        self.transcript_path = output / "run-transcript.md"
        self.transcript_entries: list[tuple[str, bytes]] = []
        self.metadata: dict[str, Any] = {
            "schema": "tinysa-physical-selftest-capture-v1",
            "started_utc": utc_now(),
            "finished_utc": None,
            "result": "INCOMPLETE",
            "variant": variant,
            "expected_version": expected_version,
            "zero_based_cases": cases,
            "arguments": arguments,
            "port_history": [],
            "usb_identity": None,
            "cases": [],
        }
        self.persist_metadata()

    def event(self, message: str) -> None:
        line = f"{utc_now()} {message}"
        with self.log_path.open("a", encoding="utf-8") as target:
            target.write(line + "\n")
        print(line, flush=True)

    def add_transcript(self, heading: str, response: bytes) -> None:
        self.transcript_entries.append((heading, response))
        lines = [
            "# tinySA4 physical self-test shell transcript",
            "",
            f"- Variant: `{self.metadata['variant']}`",
            f"- Expected version: `{self.metadata['expected_version']}`",
            "",
        ]
        for title, payload in self.transcript_entries:
            lines.extend((f"## `{title}`", "", "```text",
                          visible(payload).rstrip(), "```", ""))
        self.transcript_path.write_text("\n".join(lines), encoding="utf-8")

    def save_response(self, relative: Path, heading: str, response: bytes) -> None:
        path = self.output / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response)
        self.add_transcript(heading, response)

    def persist_metadata(self) -> None:
        temporary = self.output / "run.json.tmp"
        temporary.write_text(
            json.dumps(self.metadata, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.output / "run.json")

    def finalize(self, result: str, locator: PortLocator) -> None:
        self.metadata["result"] = result
        self.metadata["finished_utc"] = utc_now()
        self.metadata["port_history"] = locator.history
        self.metadata["usb_identity"] = (
            asdict(locator.identity) if locator.identity is not None else None
        )
        self.persist_metadata()
        paths = sorted(
            path for path in self.output.rglob("*")
            if path.is_file() and path.name != "SHA256SUMS"
        )
        sums = "".join(
            f"{sha256_file(path)}  {path.relative_to(self.output)}\n"
            for path in paths
        )
        (self.output / "SHA256SUMS").write_text(sums, encoding="utf-8")


class ShellSession:
    def __init__(self, locator: PortLocator, store: EvidenceStore) -> None:
        self.locator = locator
        self.store = store
        self.port: Any = None

    def close(self) -> None:
        if self.port is not None and self.port.is_open:
            self.port.close()

    def connect(self) -> bytes:
        self.close()
        try:
            import serial
        except ModuleNotFoundError as error:
            raise RuntimeError(
                "pyserial 3.5 is required; install tools/requirements-hardware-test.txt"
            ) from error
        name = self.locator.resolve()
        device = serial.Serial()
        device.port = name
        device.baudrate = 115200
        device.timeout = 0.05
        device.write_timeout = 1.0
        device.rts = False
        device.dtr = False
        device.exclusive = True
        device.open()
        self.port = device
        time.sleep(0.25)
        device.reset_input_buffer()
        device.write(b"\r")
        device.flush()
        response = SCREEN_TOOL.read_until(device, PROMPT, 5.0)
        self.store.event(f"shell_connected port={name}")
        return response

    def ensure_connected(self) -> None:
        if self.port is None or not self.port.is_open:
            response = self.connect()
            self.store.add_transcript("<reconnect>", response)

    def command(self, command: str, timeout: float = 30.0,
                retry_read_only: bool = False) -> bytes:
        attempts = 2 if retry_read_only else 1
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                self.ensure_connected()
                encoded = command.encode("ascii")
                if len(encoded) > 47:
                    raise ValueError(f"shell command is too long: {command}")
                self.port.write(encoded + b"\r")
                self.port.flush()
                return SCREEN_TOOL.read_until(self.port, PROMPT, timeout)
            except (OSError, TimeoutError) as error:
                last_error = error
                self.store.event(
                    f"shell_transport_error command={command!r} attempt={attempt}/{attempts} "
                    f"error={error}"
                )
                self.close()
                if attempt < attempts:
                    self.store.event(f"shell_read_only_retry command={command!r}")
        assert last_error is not None
        raise last_error

    def capture_frame(self) -> bytes:
        last_error: Exception | None = None
        for attempt in range(1, 3):
            try:
                self.ensure_connected()
                self.port.write(b"capture\r")
                self.port.flush()
                prefix = SCREEN_TOOL.read_until(self.port, CAPTURE_ECHO, 5.0)
                trailing = prefix.split(CAPTURE_ECHO, 1)[1]
                if len(trailing) > PIXEL_BYTES:
                    raise RuntimeError("capture response contains excess prefix data")
                frame = trailing + SCREEN_TOOL.read_exact(
                    self.port, PIXEL_BYTES - len(trailing), 30.0
                )
                prompt = SCREEN_TOOL.read_exact(self.port, len(PROMPT), 5.0)
                if prompt != PROMPT:
                    raise RuntimeError(
                        f"framebuffer was not followed by exact prompt: {prompt!r}"
                    )
                return frame
            except (OSError, RuntimeError, TimeoutError) as error:
                last_error = error
                self.store.event(
                    f"screen_transport_error attempt={attempt}/2 error={error}"
                )
                self.close()
        assert last_error is not None
        raise last_error


def capture_stable_pair(session: ShellSession, store: EvidenceStore,
                        case_number: int, attempts: int,
                        pair_interval: float, retry_wait: float) -> tuple[bytes, dict[str, Any]]:
    for attempt in range(1, attempts + 1):
        first = session.capture_frame()
        time.sleep(pair_interval)
        second = session.capture_frame()
        first_path = store.output / f"case-{case_number:02d}-settle-{attempt:02d}-a.rgb565be"
        second_path = store.output / f"case-{case_number:02d}-settle-{attempt:02d}-b.rgb565be"
        first_path.write_bytes(first)
        second_path.write_bytes(second)
        first_hash = sha256_bytes(first)
        second_hash = sha256_bytes(second)
        store.event(
            f"ZS407_PHYSICAL_SELFTEST_FRAME_PAIR case={case_number} "
            f"attempt={attempt} bytes={len(first)} sha_a={first_hash} "
            f"sha_b={second_hash} identical={str(first == second).lower()}"
        )
        if first == second:
            metrics: dict[str, Any] = frame_metrics(first)
            metrics.update({
                "bytes": len(first),
                "sha256": first_hash,
                "settle_attempt": attempt,
                "pair_interval_seconds": pair_interval,
            })
            return first, metrics
        if attempt < attempts:
            time.sleep(retry_wait)
    raise AssertionError(
        f"self-test case {case_number} never produced two identical full frames"
    )


EVIDENCE_COMMANDS = (
    "frequencies",
    "trace",
    "trace 1 value",
    "trace 2 value",
    "trace 3 value",
    "trace 4 value",
    "data 0",
    "data 1",
    "data 2",
    "sweeptime",
    "status",
    "threads",
)


def command_slug(command: str) -> str:
    return command.replace(" ", "-")


def capture_persisted_config_evidence(session: ShellSession, store: EvidenceStore,
                                      phase: str) -> dict[str, bytes]:
    """Observe calibration/palette config without invoking any save or recall."""
    responses: dict[str, bytes] = {}
    commands = ("color", *(f"correction {table}" for table in CORRECTION_TABLES))
    for command in commands:
        response = session.command(command, timeout=45.0, retry_read_only=True)
        responses[command] = response
        store.save_response(
            Path("persisted-config") / f"{phase}-{command_slug(command)}.txt",
            f"persisted config {phase}: {command}", response,
        )
    return responses


def collect_case_evidence(session: ShellSession, store: EvidenceStore,
                          case_number: int) -> dict[str, Any]:
    responses: dict[str, bytes] = {}
    shell_dir = Path(f"case-{case_number:02d}-shell")
    for command in EVIDENCE_COMMANDS:
        response = session.command(command, timeout=45.0, retry_read_only=True)
        responses[command] = response
        store.save_response(
            shell_dir / f"{command_slug(command)}.txt",
            f"case {case_number:02d}: {command}", response,
        )

    frequencies = parse_frequency_response(responses["frequencies"])
    if len(frequencies) != EXPECTED_POINTS:
        raise AssertionError(
            f"case {case_number}: frequencies returned {len(frequencies)} points; "
            f"expected {EXPECTED_POINTS}"
        )

    traces = [
        parse_trace_response(responses[f"trace {trace} value"], trace)
        for trace in range(1, 5)
    ]
    data_formatter_defects: list[dict[str, Any]] = []
    data_planes: list[list[float]] = []
    for plane in range(3):
        plane_defects: list[dict[str, Any]] = []
        data_planes.append(parse_data_response(
            responses[f"data {plane}"], plane_defects
        ))
        data_formatter_defects.extend(validate_data_formatter_defects(
            plane, plane_defects, traces
        ))
    for label, values in [
        *[(f"trace {index + 1}", values) for index, values in enumerate(traces)],
        *[(f"data {index}", values) for index, values in enumerate(data_planes)],
    ]:
        if len(values) != len(frequencies):
            raise AssertionError(
                f"case {case_number}: {label} returned {len(values)} values; "
                f"frequency grid has {len(frequencies)}"
            )

    metrics = [trace_metrics(values) for values in traces]
    actual_range = float(metrics[0]["range"])
    if case_number in NONFLAT_CASES and actual_range < 0.10:
        raise AssertionError(
            f"case {case_number}: measured trace collapsed to {actual_range:.3f} dB range"
        )
    packed = struct.pack(
        f"<{len(traces) * len(frequencies)}f",
        *(value for trace in traces for value in trace),
    )
    trace_path = store.output / f"case-{case_number:02d}-measured.f32le"
    trace_path.write_bytes(packed)
    for defect in data_formatter_defects:
        store.event(
            "ZS407_PHYSICAL_SHELL_FORMATTER_DEFECT=OBSERVED "
            f"case={case_number} kind={defect['kind']} "
            f"data_plane={defect['data_plane']} point={defect['point_index']} "
            f"raw={defect['raw_ascii']} decoded={defect['decoded_value']} "
            f"mapped_trace={defect['mapped_trace']} "
            f"trace_cross_check={defect['trace_cross_check']}"
        )
    return {
        "frequency_points": len(frequencies),
        "frequency_start_hz": frequencies[0],
        "frequency_stop_hz": frequencies[-1],
        "trace_metrics": metrics,
        "trace_dump_format": "float32 little-endian, shell-rounded to 0.01",
        "trace_dump_bytes": len(packed),
        "trace_dump_sha256": sha256_bytes(packed),
        "data_points": [len(values) for values in data_planes],
        "known_shell_formatter_defects": data_formatter_defects,
    }


def acknowledge_case(session: ShellSession, store: EvidenceStore,
                     case_number: int, hold_seconds: float) -> None:
    """Release a retained result; a lost touch response is not replayed."""
    try:
        response = session.command("touch 200 150", timeout=10.0)
        store.add_transcript(f"case {case_number:02d}: touch 200 150", response)
    except (OSError, TimeoutError) as error:
        store.event(
            f"touch_response_uncertain case={case_number} error={error}; "
            "will reconnect and issue release"
        )
        session.close()
    time.sleep(hold_seconds)
    response = session.command("release", timeout=10.0, retry_read_only=True)
    store.add_transcript(f"case {case_number:02d}: release", response)
    time.sleep(2.0)
    store.event(f"ZS407_PHYSICAL_SELFTEST_ACK=PASS case={case_number}")


def require_variant_version(variant: str, expected: str) -> None:
    """Bind reserved evidence-label families to their exact firmware identity."""
    for prefix, required in KNOWN_VARIANT_VERSIONS.items():
        if variant == prefix or variant.startswith(prefix + "-"):
            if expected != required:
                raise ValueError(
                    f"variant {variant!r} requires exact version {required!r}; "
                    f"got {expected!r}"
                )
            return


def require_version(response: bytes, expected: str) -> None:
    """Require one clean, exact firmware identity response."""
    lines = [line.strip() for line in response.replace(b"\r", b"").split(b"\n")]
    while lines and not lines[-1]:
        lines.pop()
    expected_bytes = expected.encode("ascii")
    reported = [line for line in lines if line.startswith(b"tinySA") and b"_v" in line]
    if not lines or lines[0] != b"version" or lines[-1] != PROMPT.strip():
        raise AssertionError(
            "version response has stale/prefixed data, a missing exact echo, or "
            f"no exact prompt: {visible(response)!r}"
        )
    if reported != [expected_bytes]:
        raise AssertionError(
            f"exact version mismatch: expected {expected!r}, reported "
            f"{[line.decode('ascii', 'backslashreplace') for line in reported]!r}"
        )


def capture_run(args: argparse.Namespace) -> int:
    cases = parse_case_set(args.cases)
    if args.confirm != CONFIRMATION:
        raise ValueError(
            f"--confirm must be exactly {CONFIRMATION}; the short 50-ohm "
            "CAL-to-RF cable must be connected"
        )
    if not math.isfinite(args.case_wait) or not 15.0 <= args.case_wait <= 300.0:
        raise ValueError("--case-wait must be finite and within 15..300 seconds")
    if not math.isfinite(args.pair_interval) or not 0.5 <= args.pair_interval <= 10.0:
        raise ValueError("--pair-interval must be finite and within 0.5..10 seconds")
    if not 1 <= args.settle_attempts <= 10:
        raise ValueError("--settle-attempts must be within 1..10")
    if (
        not math.isfinite(args.settle_retry_wait)
        or not 0.5 <= args.settle_retry_wait <= 60.0
    ):
        raise ValueError("--settle-retry-wait must be finite and within 0.5..60 seconds")
    if not math.isfinite(args.ack_hold) or not 0.1 <= args.ack_hold <= 10.0:
        raise ValueError("--ack-hold must be finite and within 0.1..10 seconds")
    if (
        not math.isfinite(args.reenumeration_timeout)
        or args.reenumeration_timeout <= 0.0
        or args.reenumeration_timeout > 300.0
    ):
        raise ValueError("--reenumeration-timeout must be finite and within (0, 300] seconds")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", args.variant):
        raise ValueError("--variant may contain only letters, digits, dot, underscore and dash")
    require_variant_version(args.variant, args.expected_version)

    arguments = {
        "port": args.port,
        "usb_serial": args.usb_serial,
        "vid": f"0x{args.vid:04x}",
        "pid": f"0x{args.pid:04x}",
        "case_wait_seconds": args.case_wait,
        "pair_interval_seconds": args.pair_interval,
        "settle_attempts": args.settle_attempts,
        "settle_retry_wait_seconds": args.settle_retry_wait,
        "ack_hold_seconds": args.ack_hold,
    }
    store = EvidenceStore(args.output, args.variant, args.expected_version,
                          cases, arguments)
    locator = PortLocator(args.port, args.vid, args.pid, args.usb_serial,
                          args.reenumeration_timeout, store.event)
    session = ShellSession(locator, store)
    result = "FAIL"
    try:
        connect_response = session.connect()
        store.add_transcript("<connect>", connect_response)
        version = session.command("version", retry_read_only=True)
        store.save_response(Path("device-version-before.txt"), "version before", version)
        require_version(version, args.expected_version)
        info = session.command("info", retry_read_only=True)
        store.save_response(Path("device-info-before.txt"), "info before", info)
        config_before = capture_persisted_config_evidence(
            session, store, "before"
        )
        store.event(
            f"ZS407_PHYSICAL_IDENTITY=PASS expected_version={args.expected_version}"
        )

        for zero_based in cases:
            case_number = zero_based + 1
            case_record: dict[str, Any] = {
                "zero_based_case": zero_based,
                "selftest_argument": case_number,
                "started_utc": utc_now(),
                "finished_utc": None,
                "result": "INCOMPLETE",
            }
            store.metadata["cases"].append(case_record)
            store.persist_metadata()
            started = False
            uncertain_start = False
            primary_error: Exception | None = None
            try:
                store.event(
                    f"ZS407_PHYSICAL_SELFTEST=START case={case_number} "
                    f"zero_based={zero_based} fixed_wait_seconds={args.case_wait:.1f}"
                )
                try:
                    response = session.command(f"selftest 0 {case_number}", timeout=10.0)
                    started = True
                    store.add_transcript(
                        f"case {case_number:02d}: selftest 0 {case_number}", response
                    )
                except (OSError, TimeoutError):
                    uncertain_start = True
                    raise
                time.sleep(args.case_wait)
                frame, display = capture_stable_pair(
                    session, store, case_number, args.settle_attempts,
                    args.pair_interval, args.settle_retry_wait,
                )
                (store.output / f"case-{case_number:02d}.rgb565be").write_bytes(frame)
                comparator_frame = rgb565be_to_rgb565le(frame)
                (store.output / f"case-{case_number:02d}.rgb565").write_bytes(
                    comparator_frame
                )
                png = rgb565be_to_png(frame)
                (store.output / f"case-{case_number:02d}.png").write_bytes(png)
                evidence = collect_case_evidence(session, store, case_number)
                case_record.update({
                    "display": display,
                    "comparator_rgb565_sha256": sha256_bytes(comparator_frame),
                    "png_sha256": sha256_bytes(png),
                    "shell_evidence": evidence,
                    "result": "PASS",
                })
                store.event(
                    f"ZS407_PHYSICAL_SELFTEST=PASS case={case_number} "
                    f"frame_sha256={display['sha256']} "
                    f"trace_range_db={evidence['trace_metrics'][0]['range']:.3f}"
                )
            except Exception as error:
                primary_error = error
                case_record["result"] = f"FAIL: {error}"
                store.event(f"ZS407_PHYSICAL_SELFTEST=FAIL case={case_number} error={error}")
            finally:
                if uncertain_start and not started:
                    # The command could have reached firmware even if its prompt was
                    # lost.  Give it the same full interval before a harmless release.
                    store.event(
                        f"selftest_start_uncertain case={case_number}; "
                        f"waiting {args.case_wait:.1f}s before recovery release"
                    )
                    time.sleep(args.case_wait)
                    started = True
                if started:
                    try:
                        acknowledge_case(session, store, case_number, args.ack_hold)
                    except Exception as ack_error:
                        store.event(
                            f"ZS407_PHYSICAL_SELFTEST_ACK=FAIL case={case_number} "
                            f"error={ack_error}"
                        )
                        if primary_error is None:
                            primary_error = ack_error
                            case_record["result"] = f"FAIL: acknowledgement: {ack_error}"
                case_record["finished_utc"] = utc_now()
                store.persist_metadata()
            if primary_error is not None:
                raise primary_error

        final_version = session.command("version", retry_read_only=True)
        store.save_response(Path("device-version-after.txt"), "version after", final_version)
        require_version(final_version, args.expected_version)
        final_info = session.command("info", retry_read_only=True)
        store.save_response(Path("device-info-after.txt"), "info after", final_info)
        config_after = capture_persisted_config_evidence(
            session, store, "after"
        )
        config_mismatches = [
            command for command in config_before
            if config_before[command] != config_after[command]
        ]
        store.metadata["persisted_config_integrity"] = {
            "pass": not config_mismatches,
            "commands": list(config_before),
            "mismatches": config_mismatches,
            "before_sha256": {
                command: sha256_bytes(response)
                for command, response in config_before.items()
            },
            "after_sha256": {
                command: sha256_bytes(response)
                for command, response in config_after.items()
            },
        }
        store.persist_metadata()
        if config_mismatches:
            raise AssertionError(
                "persisted calibration/palette observations changed: "
                + ", ".join(config_mismatches)
            )
        store.event(
            "ZS407_PHYSICAL_PERSISTED_CONFIG=PASS "
            f"observations={len(config_before)}"
        )
        result = "PASS"
        store.event(
            f"ZS407_PHYSICAL_SELFTEST_RUN=PASS cases={len(cases)} variant={args.variant}"
        )
        return 0
    except Exception as error:
        store.event(f"ZS407_PHYSICAL_SELFTEST_RUN=FAIL error={error}")
        print(f"error: {error}", file=sys.stderr)
        return 1
    finally:
        session.close()
        store.finalize(result, locator)


def parse_int(value: str) -> int:
    return int(value, 0)


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "capture settled physical tinySA4 self-test screens and read-only "
            "trace evidence; this tool never flashes firmware"
        )
    )
    parser.add_argument("--port", default="auto",
                        help="serial device path or 'auto' (default: auto)")
    parser.add_argument("--usb-serial", help="optional USB serial-number filter")
    parser.add_argument("--vid", type=parse_int, default=DEFAULT_VID)
    parser.add_argument("--pid", type=parse_int, default=DEFAULT_PID)
    parser.add_argument("--variant", required=True,
                        help="evidence label, such as official-c979 or rc5")
    parser.add_argument("--expected-version", required=True,
                        help="exact clean firmware identity required from the version command")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--cases", default="0-13",
                        help="zero-based case set (default: 0-13)")
    parser.add_argument("--case-wait", type=float, default=30.0,
                        help="fixed wait after starting each case (default: 30s)")
    parser.add_argument("--pair-interval", type=float, default=0.75,
                        help="delay between full frame readbacks (default: 0.75s)")
    parser.add_argument("--settle-attempts", type=int, default=3)
    parser.add_argument("--settle-retry-wait", type=float, default=5.0)
    parser.add_argument("--ack-hold", type=float, default=1.5)
    parser.add_argument("--reenumeration-timeout", type=float, default=30.0)
    parser.add_argument("--confirm", required=True,
                        help=f"must be exactly {CONFIRMATION}")
    return parser.parse_args(argv)


def main() -> int:
    try:
        return capture_run(parse_args())
    except (RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
