#!/usr/bin/env python3
"""Offline end-to-end simulation of the physical transport qualifier."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import struct
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "qualify-transport-v0.4.py"
SPEC = importlib.util.spec_from_file_location("zs407_transport_qualifier", TOOL)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("unable to load transport qualifier")
qualifier = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = qualifier
SPEC.loader.exec_module(qualifier)

EXPECTED_VERSION = "tinySA4_lab-v0.4-transport-qual-gtest"


class FakeBinaryPort:
    def __init__(self) -> None:
        self.decoder = qualifier.FrameDecoder()
        self.output = bytearray()

    @property
    def in_waiting(self) -> int:
        return len(self.output)

    def write(self, data: bytes) -> int:
        for frame in self.decoder.feed(data):
            self.output.extend(qualifier.encode_frame(self.handle(frame)))
        return len(data)

    def flush(self) -> None:
        return

    def read(self, size: int) -> bytes:
        count = min(size, len(self.output))
        result = bytes(self.output[:count])
        del self.output[:count]
        return result

    @staticmethod
    def status(request: Any, status: int, detail: int = 0) -> Any:
        return qualifier.Frame(
            2, qualifier.RESPONSE_FLAG | qualifier.ERROR_FLAG,
            request.request_id, request.command,
            struct.pack("<BBH", status, 0, detail),
        )

    def handle(self, request: Any) -> Any:
        if request.command == qualifier.COMMAND_PING:
            return qualifier.Frame(
                2, qualifier.RESPONSE_FLAG, request.request_id,
                request.command, request.payload,
            )
        if request.command == qualifier.COMMAND_CAPABILITIES and \
                not request.payload:
            payload = struct.pack(
                "<BBBBIIHHHHHH", 3, 2, 6, 3,
                qualifier.CAP_BINARY_TRANSPORT_QUALIFICATION,
                qualifier.SAFETY_TRANSPORT_QUALIFICATION_ONLY |
                qualifier.SAFETY_PASSIVE_EXECUTION_LOCKED,
                1024, 4096, 450, 1024, 256, 16,
            )
            return qualifier.Frame(
                2, qualifier.RESPONSE_FLAG, request.request_id,
                request.command, payload,
            )
        if request.command == qualifier.COMMAND_CLOCK_SNAPSHOT and \
                not request.payload:
            return qualifier.Frame(
                2, qualifier.RESPONSE_FLAG, request.request_id,
                request.command,
                struct.pack("<IIQII", 0x5A533430, 3, 407000000, 10000, 4070000),
            )
        if request.command == qualifier.COMMAND_ACQUISITION_STATUS and \
                not request.payload:
            return qualifier.Frame(
                2, qualifier.RESPONSE_FLAG, request.request_id,
                request.command,
                struct.pack(
                    "<IIIIIIQIHBB", 0x04070001, 407, 407, 0, 0, 0,
                    406000000, 735000, 450, 0, 0,
                ),
            )
        if request.command == qualifier.COMMAND_ZERO_SPAN_CAPTURE:
            return self.status(request, qualifier.STATUS_NOT_QUALIFIED)
        return self.status(
            request, qualifier.STATUS_UNSUPPORTED, request.command
        )


class FakeShellSession:
    def __init__(self, recovered: bool = False) -> None:
        self.port = FakeBinaryPort()
        self.recovered = recovered
        self.attempts = 1 if recovered else 0
        self.commands: list[str] = []

    def command(self, command: str, timeout: float = 30.0) -> str:
        del timeout
        self.commands.append(command)
        if command == "output off":
            return "output off\r\n"
        if command == "version":
            return f"version\r\n{EXPECTED_VERSION}\r\n"
        if command == "modern transport selftest":
            return "transport_selftest=00000000 PASS binary_transport=qualification-only\r\n"
        if command == "modern passive status":
            return (
                "passive initialized=1 qualified=0 stream_qualified=0 "
                "capture_qualified=0 state=0 stream=04070001 next=407 "
                "complete=407 published=0 dropped=0 invalid=0\r\n"
            )
        if command == "modern transport status":
            if self.recovered:
                return (
                    "transport compiled=1 running=0 qual_build=1 admitted=1 "
                    "qualified=0 "
                    "shell_released=0 worker=0 state=5 one_shot=1 "
                    f"attempts={self.attempts} handoffs=1 starts=1 recoveries=1 "
                    "failures=0 accepted=10 rejected=2 discarded=23 tx=10 errors=0\r\n"
                )
            return (
                "transport compiled=1 running=0 qual_build=1 admitted=1 "
                "qualified=0 "
                "shell_released=0 worker=0 state=1 one_shot=0 attempts=0 "
                "handoffs=0 starts=0 recoveries=0 failures=0 accepted=0 "
                "rejected=0 discarded=0 tx=0 errors=0\r\n"
            )
        if command == f"modern transport handoff {qualifier.HANDOFF_TOKEN}":
            if self.recovered:
                self.attempts += 1
                return "transport_handoff status=6 refused: one-shot handoff unavailable\r\n"
            return (
                "transport_handoff status=0 armed: binary ownership begins "
                "after this prompt; unplug USB to recover shell\r\n"
            )
        raise AssertionError(f"unexpected shell command: {command}")


def main() -> int:
    qualifier.self_test()
    exercise = FakeShellSession()
    qualifier.exercise_binary(exercise, EXPECTED_VERSION)
    if exercise.commands[0] != "output off":
        raise AssertionError("exercise did not begin output-off")
    recovered = FakeShellSession(recovered=True)
    qualifier.verify_recovery(recovered, EXPECTED_VERSION)
    if recovered.commands[0] != "output off":
        raise AssertionError("recovery did not begin output-off")
    print("transport qualifier simulated physical workflow: passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
