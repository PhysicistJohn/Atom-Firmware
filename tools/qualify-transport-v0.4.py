#!/usr/bin/env python3
"""Qualify the one-shot ZS407 v0.4 binary transport without flashing.

This tool contains no DFU, reset, calibration, save, generator or firmware
write operation. Physical modes make ``output off`` the first shell command.
"""

from __future__ import annotations

import argparse
import binascii
from dataclasses import dataclass
import random
import re
import struct
import sys
import time
from typing import Any, Iterable


MAGIC = 0x5A53
MAGIC_BYTES = struct.pack("<H", MAGIC)
PROTOCOL_VERSION = 2
MINIMUM_VERSION = 1
MAXIMUM_PAYLOAD = 1024
FRAME_OVERHEAD = 14
PROMPT = b"ch> "
HANDOFF_TOKEN = "QUAL-407"

COMMAND_PING = 0
COMMAND_CAPABILITIES = 1
COMMAND_CLOCK_SNAPSHOT = 4
COMMAND_ACQUISITION_STATUS = 5
COMMAND_ZERO_SPAN_CAPTURE = 7

STATUS_UNSUPPORTED = 5
STATUS_NOT_QUALIFIED = 6
RESPONSE_FLAG = 0x01
ERROR_FLAG = 0x02

PROFILE_TRANSPORT_QUALIFICATION = 3
CAP_BINARY_TRANSPORT_QUALIFICATION = 1 << 19
SAFETY_BINARY_TRANSPORT_LOCKED = 1 << 4
SAFETY_PASSIVE_EXECUTION_LOCKED = 1 << 6
SAFETY_TRANSPORT_QUALIFICATION_ONLY = 1 << 9


class QualificationError(RuntimeError):
    """A fail-closed qualification error."""


@dataclass(frozen=True)
class Frame:
    version: int
    flags: int
    request_id: int
    command: int
    payload: bytes


def encode_frame(frame: Frame) -> bytes:
    if not MINIMUM_VERSION <= frame.version <= PROTOCOL_VERSION:
        raise ValueError("unsupported frame version")
    if not 0 <= frame.flags <= 0xFF:
        raise ValueError("flags outside u8")
    if not 0 <= frame.request_id <= 0xFFFF:
        raise ValueError("request ID outside u16")
    if not 0 <= frame.command <= 0xFFFF:
        raise ValueError("command outside u16")
    if len(frame.payload) > MAXIMUM_PAYLOAD:
        raise ValueError("payload exceeds protocol maximum")
    header = struct.pack(
        "<HBBHHH", MAGIC, frame.version, frame.flags,
        frame.request_id, frame.command, len(frame.payload)
    )
    body = header + frame.payload
    return body + struct.pack("<I", binascii.crc32(body) & 0xFFFFFFFF)


class FrameDecoder:
    def __init__(self) -> None:
        self.buffer = bytearray()
        self.accepted = 0
        self.rejected = 0
        self.discarded = 0

    def feed(self, data: bytes) -> list[Frame]:
        self.buffer.extend(data)
        output: list[Frame] = []
        while True:
            index = self.buffer.find(MAGIC_BYTES)
            if index < 0:
                retain = 1 if self.buffer[-1:] == MAGIC_BYTES[:1] else 0
                self.discarded += len(self.buffer) - retain
                if retain:
                    self.buffer[:] = self.buffer[-1:]
                else:
                    self.buffer.clear()
                break
            if index:
                self.discarded += index
                del self.buffer[:index]
            if len(self.buffer) < 10:
                break
            version = self.buffer[2]
            payload_length = struct.unpack_from("<H", self.buffer, 8)[0]
            if not MINIMUM_VERSION <= version <= PROTOCOL_VERSION or \
                    payload_length > MAXIMUM_PAYLOAD:
                self.rejected += 1
                self.discarded += 1
                del self.buffer[0]
                continue
            total = FRAME_OVERHEAD + payload_length
            if len(self.buffer) < total:
                break
            candidate = bytes(self.buffer[:total])
            expected = struct.unpack_from("<I", candidate, total - 4)[0]
            actual = binascii.crc32(candidate[:-4]) & 0xFFFFFFFF
            if expected != actual:
                self.rejected += 1
                self.discarded += 1
                del self.buffer[0]
                continue
            _, version, flags, request_id, command, payload_length = \
                struct.unpack_from("<HBBHHH", candidate)
            output.append(Frame(
                version, flags, request_id, command,
                candidate[10:10 + payload_length]
            ))
            self.accepted += 1
            del self.buffer[:total]
        return output


def require(condition: bool, message: str) -> None:
    if not condition:
        raise QualificationError(message)


def status_payload(frame: Frame, expected: int, detail: int = 0) -> None:
    require(frame.flags == RESPONSE_FLAG | ERROR_FLAG,
            f"status response flags 0x{frame.flags:02x}")
    require(len(frame.payload) == 4, "status response length is not four")
    status, reserved, actual_detail = struct.unpack("<BBH", frame.payload)
    require(status == expected, f"status {status} != {expected}")
    require(reserved == 0, "status reserved byte is nonzero")
    require(actual_detail == detail,
            f"status detail {actual_detail} != {detail}")


def test_decoder() -> None:
    decoder = FrameDecoder()
    frames = [
        Frame(2, 0, 1, COMMAND_PING, b""),
        Frame(2, 0xA5, 407, 0x1234, bytes(range(251))),
        Frame(1, 0, 0xFFFF, COMMAND_PING, bytes([0x53, 0x5A]) * 100),
    ]
    encoded = b"".join(encode_frame(frame) for frame in frames)
    decoded: list[Frame] = []
    for offset in range(0, len(encoded), 7):
        decoded.extend(decoder.feed(encoded[offset:offset + 7]))
    require(decoded == frames, "fragmented decoder round trip failed")

    damaged = bytearray(encode_frame(frames[1]))
    damaged[-1] ^= 0x80
    stream = b"noise\x53" + bytes(damaged) + b"\x00\xff" + encode_frame(frames[0])
    recovered = FrameDecoder().feed(stream)
    require(recovered == [frames[0]], "decoder did not recover after bad CRC")

    rng = random.Random(407)
    decoder = FrameDecoder()
    expected: list[Frame] = []
    stream_bytes = bytearray()
    for request_id in range(10000):
        payload = rng.randbytes(rng.randrange(0, 129))
        frame = Frame(2, rng.randrange(0, 256), request_id & 0xFFFF,
                      rng.randrange(0, 0x10000), payload)
        candidate = bytearray(encode_frame(frame))
        if request_id % 11 == 0:
            candidate[rng.randrange(2, len(candidate))] ^= 1 << rng.randrange(8)
        else:
            expected.append(frame)
        stream_bytes.extend(rng.randbytes(request_id % 3))
        stream_bytes.extend(candidate)
    actual: list[Frame] = []
    for offset in range(0, len(stream_bytes), 113):
        actual.extend(decoder.feed(bytes(stream_bytes[offset:offset + 113])))
    require(actual == expected, "10,000-frame decoder mutation test failed")


def decode_capabilities(payload: bytes) -> dict[str, int]:
    require(len(payload) == 24, "capabilities payload length")
    values = struct.unpack("<BBBBIIHHHHHH", payload)
    names = (
        "schema", "protocol", "phase", "profile", "features", "safety",
        "maximum_payload", "maximum_trace", "maximum_sweep", "maximum_fft",
        "waveform_samples", "waveform_event_bytes",
    )
    return dict(zip(names, values))


def decode_clock(payload: bytes) -> dict[str, int]:
    require(len(payload) == 24, "clock payload length")
    names = ("clock_id", "flags", "timestamp_us", "tick_hz", "raw_tick")
    return dict(zip(names, struct.unpack("<IIQII", payload)))


def decode_acquisition(payload: bytes) -> dict[str, int]:
    require(len(payload) == 40, "acquisition payload length")
    names = (
        "stream_id", "next_sequence", "complete", "published", "dropped",
        "invalid", "last_start_us", "duration_us", "points", "state", "flags",
    )
    return dict(zip(names, struct.unpack("<IIIIIIQIHBB", payload)))


def self_test() -> None:
    test_decoder()
    capabilities = decode_capabilities(struct.pack(
        "<BBBBIIHHHHHH", 3, 2, 6, 3,
        CAP_BINARY_TRANSPORT_QUALIFICATION,
        SAFETY_TRANSPORT_QUALIFICATION_ONLY,
        1024, 4096, 450, 1024, 256, 16,
    ))
    require(capabilities["profile"] == 3, "capabilities decode")
    clock = decode_clock(struct.pack("<IIQII", 0x5A533430, 3, 1234567, 10000, 9))
    require(clock["timestamp_us"] == 1234567, "clock decode")
    acquisition = decode_acquisition(struct.pack(
        "<IIIIIIQIHBB", 1, 2, 2, 0, 0, 0, 100, 735000, 450, 0, 0
    ))
    require(acquisition["points"] == 450, "acquisition decode")
    print("transport qualifier offline self-test: 10000 frames passed")


def read_until(port: Any, marker: bytes, timeout: float) -> bytes:
    deadline = time.monotonic() + timeout
    data = bytearray()
    while marker not in data:
        if time.monotonic() >= deadline:
            raise QualificationError(
                f"timeout waiting for {marker!r} after {len(data)} bytes"
            )
        chunk = port.read(max(port.in_waiting, 1))
        if chunk:
            data.extend(chunk)
    return bytes(data)


class ShellSession:
    def __init__(self, port_name: str) -> None:
        try:
            import serial
        except ImportError as error:
            raise QualificationError(
                "physical qualification requires pyserial 3.5"
            ) from error
        self.port = serial.Serial()
        self.port.port = port_name
        self.port.baudrate = 115200
        self.port.timeout = 0.05
        self.port.write_timeout = 2.0
        self.port.rts = False
        self.port.dtr = False
        self.port.exclusive = True

    def __enter__(self) -> "ShellSession":
        self.port.open()
        time.sleep(0.25)
        self.port.reset_input_buffer()
        self.port.write(b"\r")
        self.port.flush()
        read_until(self.port, PROMPT, 10.0)
        return self

    def __exit__(self, *_: object) -> None:
        if self.port.is_open:
            self.port.close()

    def command(self, command: str, timeout: float = 30.0) -> str:
        self.port.write(command.encode("ascii") + b"\r")
        self.port.flush()
        response = read_until(self.port, PROMPT, timeout)
        return response[:-len(PROMPT)].decode("utf-8", "replace")


def fields_from_line(text: str, prefix: str) -> dict[str, int]:
    line = next((line for line in text.splitlines()
                 if line.startswith(prefix)), None)
    require(line is not None, f"missing {prefix!r} line")
    fields: dict[str, int] = {}
    for name, value in re.findall(r"([a-z_]+)=([0-9]+)", line):
        fields[name] = int(value)
    return fields


def require_version(text: str, expected: str) -> None:
    require(expected in text, f"running version does not contain {expected!r}")


def shell_preflight(session: ShellSession, expected_version: str) -> dict[str, int]:
    session.command("output off")
    require_version(session.command("version"), expected_version)
    selftest = session.command("modern transport selftest")
    require("transport_selftest=00000000 PASS" in selftest,
            "embedded transport self-test failed")
    status_text = session.command("modern transport status")
    status = fields_from_line(status_text, "transport compiled=")
    expected = {
        "compiled": 1, "running": 0, "qual_build": 1, "admitted": 1,
        "qualified": 0,
        "shell_released": 0, "worker": 0, "state": 1, "one_shot": 0,
        "attempts": 0, "handoffs": 0, "starts": 0, "recoveries": 0,
        "failures": 0,
    }
    for name, value in expected.items():
        require(status.get(name) == value,
                f"preflight transport {name}={status.get(name)} != {value}")
    passive = session.command("modern passive status")
    require("qualified=0 stream_qualified=0 capture_qualified=0" in passive,
            "passive execution latch is not closed")
    require("published=0 dropped=0 invalid=0" in passive,
            "locked passive counters are not clean")
    return status


class BinarySession:
    def __init__(self, port: Any) -> None:
        self.port = port
        self.decoder = FrameDecoder()
        self.pending: dict[int, Frame] = {}

    def write(self, data: bytes, chunks: Iterable[int] | None = None) -> None:
        if chunks is None:
            self.port.write(data)
            self.port.flush()
            return
        offset = 0
        for size in chunks:
            if offset >= len(data):
                break
            self.port.write(data[offset:offset + size])
            self.port.flush()
            offset += size
        if offset < len(data):
            self.port.write(data[offset:])
            self.port.flush()

    def receive(self, request_ids: set[int], timeout: float = 5.0) -> list[Frame]:
        deadline = time.monotonic() + timeout
        found: dict[int, Frame] = {}
        for request_id in list(request_ids):
            frame = self.pending.pop(request_id, None)
            if frame is not None:
                found[request_id] = frame
        while request_ids - set(found):
            if time.monotonic() >= deadline:
                missing = sorted(request_ids - set(found))
                raise QualificationError(f"binary response timeout: {missing}")
            chunk = self.port.read(max(self.port.in_waiting, 1))
            if not chunk:
                continue
            for frame in self.decoder.feed(chunk):
                if frame.request_id in request_ids:
                    require(frame.request_id not in found,
                            f"duplicate response {frame.request_id}")
                    found[frame.request_id] = frame
                else:
                    self.pending[frame.request_id] = frame
        return [found[request_id] for request_id in sorted(request_ids)]

    def exchange(self, frame: Frame,
                 chunks: Iterable[int] | None = None) -> Frame:
        self.write(encode_frame(frame), chunks)
        return self.receive({frame.request_id})[0]


def exercise_binary(session: ShellSession, expected_version: str) -> None:
    shell_preflight(session, expected_version)
    handoff = session.command(
        f"modern transport handoff {HANDOFF_TOKEN}"
    )
    require("transport_handoff status=0 armed:" in handoff,
            "firmware did not arm the one-shot handoff")
    binary = BinarySession(session.port)

    payload = bytes((index * 37) & 0xFF for index in range(1024))
    response = binary.exchange(
        Frame(2, 0, 100, COMMAND_PING, payload),
        [1, 2, 3, 5, 8, 13, 21, 34],
    )
    require(response.flags == RESPONSE_FLAG and response.payload == payload,
            "maximum-size fragmented ping mismatch")

    capabilities_frame = binary.exchange(
        Frame(2, 0, 101, COMMAND_CAPABILITIES, b"")
    )
    capabilities = decode_capabilities(capabilities_frame.payload)
    require(capabilities_frame.flags == RESPONSE_FLAG,
            "capabilities response flags")
    require(capabilities["schema"] == 3 and capabilities["protocol"] == 2,
            "capabilities schema/protocol mismatch")
    require(capabilities["profile"] == PROFILE_TRANSPORT_QUALIFICATION,
            "capabilities profile is not transport qualification")
    require(capabilities["features"] & CAP_BINARY_TRANSPORT_QUALIFICATION,
            "qualification feature bit is absent")
    require(capabilities["safety"] & SAFETY_TRANSPORT_QUALIFICATION_ONLY,
            "qualification-only safety bit is absent")
    require(not capabilities["safety"] & SAFETY_BINARY_TRANSPORT_LOCKED,
            "binary-transport-locked safety bit is contradictory")
    require(capabilities["safety"] & SAFETY_PASSIVE_EXECUTION_LOCKED,
            "passive execution is not declared locked")

    clock_frame = binary.exchange(
        Frame(2, 0, 102, COMMAND_CLOCK_SNAPSHOT, b"")
    )
    clock = decode_clock(clock_frame.payload)
    require(clock["clock_id"] == 0x5A533430 and clock["flags"] == 3,
            "clock identity/flags mismatch")
    require(clock["tick_hz"] == 10000 and clock["timestamp_us"] > 0,
            "clock did not advance at 10 kHz")

    acquisition_frame = binary.exchange(
        Frame(2, 0, 103, COMMAND_ACQUISITION_STATUS, b"")
    )
    acquisition = decode_acquisition(acquisition_frame.payload)
    require(acquisition["complete"] > 0 and acquisition["points"] == 450,
            "binary acquisition status has no completed 450-point sweep")
    require(acquisition["state"] == 0 and
            acquisition["published"] == acquisition["dropped"] ==
            acquisition["invalid"] == 0,
            "passive stream changed state in transport-only image")

    capture = binary.exchange(
        Frame(2, 0, 104, COMMAND_ZERO_SPAN_CAPTURE, b"")
    )
    status_payload(capture, STATUS_NOT_QUALIFIED)

    unsupported = binary.exchange(Frame(2, 0, 105, 0x7FFE, b""))
    status_payload(unsupported, STATUS_UNSUPPORTED, 0x7FFE)

    corrupt = bytearray(encode_frame(Frame(2, 0, 106, COMMAND_PING, b"bad")))
    corrupt[-1] ^= 0x80
    recovery = Frame(2, 0, 107, COMMAND_PING, b"crc-recovery")
    binary.write(b"garbage\x53" + bytes(corrupt) + b"\xff" +
                 encode_frame(recovery))
    recovered = binary.receive({107})[0]
    require(recovered.payload == b"crc-recovery",
            "device parser did not recover after bad CRC")

    wrong_version = bytearray(encode_frame(
        Frame(2, 0, 108, COMMAND_PING, b"wrong-version")
    ))
    wrong_version[2] = 99
    struct.pack_into("<I", wrong_version, len(wrong_version) - 4,
                     binascii.crc32(wrong_version[:-4]) & 0xFFFFFFFF)
    after_version = Frame(2, 0, 109, COMMAND_PING, b"version-recovery")
    binary.write(bytes(wrong_version) + encode_frame(after_version))
    require(binary.receive({109})[0].payload == b"version-recovery",
            "device parser did not recover after unsupported version")

    first = Frame(2, 0, 110, COMMAND_PING, b"coalesced-a")
    second = Frame(2, 0, 111, COMMAND_PING, b"coalesced-b")
    binary.write(encode_frame(first) + encode_frame(second))
    pair = binary.receive({110, 111})
    require([frame.payload for frame in pair] == [b"coalesced-a", b"coalesced-b"],
            "coalesced request ordering mismatch")

    print("binary transport exercise: passed")
    print(f"device_clock_us={clock['timestamp_us']}")
    print(f"completed_sweeps={acquisition['complete']}")
    print("NEXT: physically unplug/reconnect USB, then run verify-recovery")


def verify_recovery(session: ShellSession, expected_version: str) -> None:
    session.command("output off")
    require_version(session.command("version"), expected_version)
    status_text = session.command("modern transport status")
    status = fields_from_line(status_text, "transport compiled=")
    expected = {
        "running": 0, "qual_build": 1, "admitted": 1, "qualified": 0,
        "shell_released": 0, "worker": 0, "state": 5, "one_shot": 1,
        "attempts": 1, "handoffs": 1, "starts": 1, "recoveries": 1,
        "failures": 0,
    }
    for name, value in expected.items():
        require(status.get(name) == value,
                f"recovery transport {name}={status.get(name)} != {value}")
    require(status.get("accepted", 0) >= 10,
            "too few accepted binary requests")
    require(status.get("rejected", 0) >= 2,
            "malformed frames were not rejected")
    require(status.get("discarded", 0) > 0,
            "garbage bytes were not accounted")
    require(status.get("tx") == status.get("accepted"),
            "response count does not match accepted requests")
    require(status.get("errors") == 0, "transport reported an I/O error")

    refused = session.command(
        f"modern transport handoff {HANDOFF_TOKEN}"
    )
    require("transport_handoff status=6 refused:" in refused,
            "same-boot second handoff was not refused")
    after = fields_from_line(
        session.command("modern transport status"), "transport compiled="
    )
    require(after.get("state") == 5 and after.get("attempts") == 2 and
            after.get("handoffs") == 1 and after.get("starts") == 1,
            "refused handoff changed the one-shot lifecycle")
    require("transport_selftest=00000000 PASS" in
            session.command("modern transport selftest"),
            "post-recovery embedded transport self-test failed")
    passive = session.command("modern passive status")
    require("qualified=0 stream_qualified=0 capture_qualified=0" in passive,
            "passive locks changed after transport recovery")
    print("USB disconnect/shell recovery: passed")
    print("same-boot second handoff refusal: passed")


def physical(command: str, port: str, expected_version: str,
             confirmation: str | None) -> None:
    if command == "exercise" and confirmation != HANDOFF_TOKEN:
        raise QualificationError(
            f"exercise requires --confirm {HANDOFF_TOKEN}"
        )
    with ShellSession(port) as session:
        if command == "preflight":
            shell_preflight(session, expected_version)
            print("transport qualification preflight: passed")
        elif command == "exercise":
            exercise_binary(session, expected_version)
        elif command == "verify-recovery":
            verify_recovery(session, expected_version)
        else:
            raise QualificationError(f"unsupported physical mode {command}")


def main() -> int:
    parser = argparse.ArgumentParser()
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("self-test")
    for name in ("preflight", "exercise", "verify-recovery"):
        command = subcommands.add_parser(name)
        command.add_argument("port")
        command.add_argument("--expected-version", required=True)
        if name == "exercise":
            command.add_argument("--confirm")
    args = parser.parse_args()
    try:
        if args.command == "self-test":
            self_test()
        else:
            physical(args.command, args.port, args.expected_version,
                     getattr(args, "confirm", None))
        return 0
    except (OSError, QualificationError, TimeoutError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
