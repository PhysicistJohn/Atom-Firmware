#!/usr/bin/env python3
"""Host-only tests for the bounded upstream hardware qualification script."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "qualify_upstream_tinysa", ROOT / "tools/qualify-upstream-tinysa.py"
)
assert SPEC is not None and SPEC.loader is not None
QUALIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(QUALIFY)


class FakePort:
    is_open = True


class FakeSession:
    def __init__(self, package: int) -> None:
        self.package = package
        self.commands: list[str] = []
        self.port = FakePort()
        self.legacy_points = 101
        self.frequencies = [100_000_000 + index * 1_000 for index in range(450)]
        self.palette = [f" {index:2d}: 0x{index:06x}" for index in range(32)]
        self.corrections = [
            f"correction low {index} {index * 1000000} {index / 10:.1f}"
            for index in range(20)
        ]
        self.pending_frequency: str | None = None

    def rebuild_frequencies(self, start: int, stop: int) -> None:
        count = len(self.frequencies) - 1
        span = stop - start
        step, remainder = divmod(span, count)
        self.frequencies = [
            start + step * index + (count // 2 + remainder * index) // count
            for index in range(count + 1)
        ]

    @staticmethod
    def response(command: str, body: str = "") -> bytes:
        return f"{command}\r\n{body}ch> ".encode("ascii")

    def command(self, command: str, timeout: float = 20.0) -> bytes:
        del timeout
        self.commands.append(command)
        if command == "s":
            return self.response(command, f"s={self.legacy_points}\r\n")
        if command.startswith("s "):
            value = int(command.split()[1])
            if 2 <= value <= 2_147_483_647:
                self.legacy_points = value
                return self.response(command)
            return self.response(command, "sweep point count is invalid\r\n")
        if command.startswith("scanraw"):
            value = int(command.split()[3])
            if value <= 0 or value > 0xFFFFFFFF:
                return self.response(command, "scan point count is invalid\r\n")
            if value == 1:
                return command.encode("ascii") + b"\r\n{x\x00\x00}ch> "
        if command.startswith("scan "):
            value = int(command.split()[3])
            if value < 2 or value > 450:
                return self.response(command, "sweep points exceeds range 450\r\n")
            return self.response(command)
        if command == "correction low":
            return self.response(command, "\r\n".join(self.corrections) + "\r\n")
        if command.startswith("correction"):
            return self.response(command, "correction low|lna 0-19 frequency(Hz) value(dB)\r\n")
        if command == "color":
            return self.response(command, "\r\n".join(self.palette) + "\r\n")
        if command.startswith("trace "):
            return self.response(command, "trace {dBm|RAW}\r\n")
        if command.startswith("marker "):
            fields = command.split()
            if (len(fields) == 4 and fields[2] == "delta"
                    and 1 <= int(fields[3]) <= 8):
                return self.response(command)
            return self.response(command, "marker [n] [on|off] [n|off|on]\r\n")
        if command == "frequencies":
            body = "\r\n".join(str(value) for value in self.frequencies) + "\r\n"
            return self.response(command, body)
        if command in ("menu 3 1", "menu 3 2", "menu 3 3"):
            self.pending_frequency = {
                "menu 3 1": "start",
                "menu 3 2": "stop",
                "menu 3 3": "center",
            }[command]
            return self.response(command)
        if command.startswith("text ") and self.pending_frequency is not None:
            value = int(command.split(" ", 1)[1][:13])
            start, stop = self.frequencies[0], self.frequencies[-1]
            if self.pending_frequency == "start":
                start = value
                if start > stop:
                    stop = start
            elif self.pending_frequency == "stop":
                stop = value
                if start > stop:
                    start = stop
            else:
                # Model the real edge case conservatively: an extreme CENTER
                # value can clamp at the limit and collapse the span.
                start = stop = value
            self.rebuild_frequencies(start, stop)
            self.pending_frequency = None
            return self.response(command)
        return self.response(command)


class QualificationLogicTests(unittest.TestCase):
    def assert_safe_commands(self, session: FakeSession) -> None:
        forbidden = ("save", "reset", "clearconfig", "correction low reset",
                     "sd_delete", "output on")
        for command in session.commands:
            self.assertNotIn(command, forbidden)

    def test_package_4(self) -> None:
        session = FakeSession(4)
        QUALIFY.qualify_package_4(session)
        self.assertEqual(session.legacy_points, 101)
        self.assertIn("scanraw 1000000 1001000 1", session.commands)
        self.assert_safe_commands(session)

    def test_package_5(self) -> None:
        session = FakeSession(5)
        QUALIFY.qualify_package_5(session)
        self.assertEqual(len(QUALIFY.correction_lines(
            session.command("correction low"))), 20)
        self.assert_safe_commands(session)

    def test_package_6(self) -> None:
        session = FakeSession(6)
        QUALIFY.qualify_package_6(session)
        self.assertIn("marker 1 delta 9", session.commands)
        self.assertNotIn("marker 1 delta 5", session.commands)
        self.assertIn("menu -1", session.commands)
        self.assert_safe_commands(session)

    def test_package_7(self) -> None:
        session = FakeSession(7)
        original_frequencies = list(session.frequencies)
        QUALIFY.qualify_package_7(session)
        self.assertEqual(session.frequencies, original_frequencies)
        long_commands = [command for command in session.commands
                         if command.startswith("text 123456")]
        self.assertEqual(len(long_commands), 1)
        self.assertEqual(len(long_commands[0].encode("ascii")), 46)
        self.assertIn("menu 3 1", session.commands)
        self.assertIn(f"text {original_frequencies[0]}", session.commands)
        self.assertIn("menu 3 2", session.commands)
        self.assertIn(f"text {original_frequencies[-1]}", session.commands)
        self.assert_safe_commands(session)


if __name__ == "__main__":
    unittest.main()
