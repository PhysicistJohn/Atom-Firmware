#!/usr/bin/env python3
"""Capture one controlled warm-reset retention cycle on a physical tinySA4.

The only state-changing wire command admitted here is one literal ``reset``.
There is no retry for it and no support for save, recall, DFU, touch,
calibration, or configuration writes.  Everything before and after that reset
is a read-only observation bound to one exact USB identity and candidate image.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
from pathlib import Path
import re
import sys
import time
from types import ModuleType
from typing import Any, Iterable


TOOL_PATH = Path(__file__).resolve()
SUPPORT_PATH = TOOL_PATH.with_name("capture-physical-selftests.py")
USB_SUPPORT_PATH = TOOL_PATH.with_name("capture-physical-usb-runtime.py")


def load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load support module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CORE = load_module("tinysa_reset_capture_support", SUPPORT_PATH)
USB = load_module("tinysa_reset_usb_support", USB_SUPPORT_PATH)

READ_ONLY_COMMANDS = frozenset((
    "version", "info", "sweep", "frequencies", "sweeptime", "status", "color",
    *(f"correction {table}" for table in CORE.CORRECTION_TABLES),
))
CONFIG_COMMANDS = ("color", *(f"correction {table}" for table in CORE.CORRECTION_TABLES))
RESET_WIRE = b"reset\r"
CONFIRMATION = "RESET-ZS407-F303-ONCE"


def require_read_only(command: str) -> None:
    if command not in READ_ONLY_COMMANDS:
        raise ValueError(f"command is outside the reset runner's read-only allowlist: {command!r}")


class ResetStore:
    def __init__(self, output: Path, arguments: dict[str, Any]) -> None:
        if output.exists():
            raise RuntimeError(f"output path already exists; choose a fresh path: {output}")
        output.mkdir(parents=True)
        self.output = output
        self.log_path = output / "run.log"
        self.transcript_path = output / "run-transcript.md"
        self.entries: list[tuple[str, bytes]] = []
        self.metadata: dict[str, Any] = {
            "schema": "tinysa-physical-reset-retention-v2",
            "started_utc": CORE.utc_now(),
            "finished_utc": None,
            "result": "INCOMPLETE",
            "arguments": arguments,
            "implementation": {
                "tool_sha256": CORE.sha256_file(TOOL_PATH),
                "capture_support_sha256": CORE.sha256_file(SUPPORT_PATH),
                "usb_support_sha256": CORE.sha256_file(USB_SUPPORT_PATH),
            },
            "candidate_binary": arguments["candidate_binary"],
            "before": None,
            "reset": {"sent_count": 0, "wire_hex": RESET_WIRE.hex()},
            "after": None,
            "retention": None,
            "port_history": [],
        }
        self.log_path.touch()
        self.transcript_path.write_text("# tinySA4 physical reset retention transcript\n\n")
        self.persist()

    def event(self, message: str) -> None:
        line = f"{CORE.utc_now()} {message}"
        with self.log_path.open("a", encoding="utf-8") as target:
            target.write(line + "\n")
        print(line, flush=True)

    def save_response(self, phase: str, command: str, response: bytes) -> None:
        filename = f"{phase}-{CORE.command_slug(command)}.txt"
        (self.output / filename).write_bytes(response)
        self.entries.append((f"{phase}: {command}", response))
        lines = ["# tinySA4 physical reset retention transcript", ""]
        for heading, payload in self.entries:
            lines.extend((f"## `{heading}`", "", "```text",
                          CORE.visible(payload).rstrip(), "```", ""))
        self.transcript_path.write_text("\n".join(lines), encoding="utf-8")

    def persist(self) -> None:
        temporary = self.output / "run.json.tmp"
        temporary.write_text(
            json.dumps(self.metadata, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.output / "run.json")

    def finalize(self, result: str, locator: Any) -> None:
        self.metadata["result"] = result
        self.metadata["finished_utc"] = CORE.utc_now()
        self.metadata["port_history"] = list(locator.history)
        self.persist()
        files = sorted(
            path for path in self.output.rglob("*")
            if path.is_file() and path.name != "SHA256SUMS"
        )
        (self.output / "SHA256SUMS").write_text(
            "".join(
                f"{CORE.sha256_file(path)}  {path.relative_to(self.output)}\n"
                for path in files
            ),
            encoding="utf-8",
        )


class ResetSession(CORE.ShellSession):
    def __init__(self, locator: Any, store: ResetStore) -> None:
        super().__init__(locator, store)
        self.reset_attempted = False
        self.reset_sent = False

    def command(self, command: str, timeout: float = 30.0,
                retry_read_only: bool = False) -> bytes:
        require_read_only(command)
        return super().command(command, timeout=timeout, retry_read_only=retry_read_only)

    def capture_frame(self) -> bytes:
        return super().capture_frame()

    def send_reset_once(self) -> dict[str, Any]:
        if self.reset_attempted:
            raise RuntimeError("reset was already sent; it may never be retried")
        self.reset_attempted = True
        self.ensure_connected()
        try:
            self.port.write(RESET_WIRE)
            self.port.flush()
            self.reset_sent = True
            try:
                response = CORE.SCREEN_TOOL.read_until(self.port, CORE.PROMPT, 1.0)
                disconnect_observed = False
                terminal_error = None
            except OSError as error:
                disconnect_observed = True
                terminal_error = f"{type(error).__name__}: {error}"
                response = f"transport ended after reset: {terminal_error}\n".encode(
                    "utf-8", "backslashreplace"
                )
            except (RuntimeError, TimeoutError) as error:
                disconnect_observed = False
                terminal_error = f"{type(error).__name__}: {error}"
                response = f"transport did not prove reset: {terminal_error}\n".encode(
                    "utf-8", "backslashreplace"
                )
        finally:
            self.close()
        return {
            "response": response,
            "wire_write_completed": self.reset_sent,
            "transport_disconnect_observed": disconnect_observed,
            "reset_banner_observed": b"Performing reset" in response,
            "prompt_observed": response.rstrip().endswith(CORE.PROMPT.rstrip()),
            "terminal_error": terminal_error,
        }


def parse_sweeptime(response: bytes) -> float:
    matches = re.findall(
        rb"(?:^|\s)([0-9]+(?:\.[0-9]+)?)\s*(ms|s)(?:\s|$)", response
    )
    if not matches:
        raise AssertionError("sweeptime response contains no duration")
    value, unit = matches[-1]
    seconds = float(value)
    if unit == b"ms":
        seconds /= 1000.0
    if not math.isfinite(seconds) or seconds <= 0.0:
        raise AssertionError(f"invalid sweep time: {seconds!r}")
    return seconds


def require_resumed(response: bytes) -> None:
    lines = [line.strip() for line in response.replace(b"\r", b"").split(b"\n")]
    if b"Resumed" not in lines:
        raise AssertionError(f"acquisition is not explicitly resumed: {CORE.visible(response)!r}")


def collect_snapshot(session: ResetSession, store: ResetStore, phase: str,
                     args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, bytes]]:
    responses: dict[str, bytes] = {}
    for command in (
        "version", "info", "sweep", "frequencies", "sweeptime", "status",
        *CONFIG_COMMANDS,
    ):
        response = session.command(command, timeout=45.0, retry_read_only=True)
        responses[command] = response
        store.save_response(phase, command, response)
    USB.require_exact_version(responses["version"], args.expected_version)
    frequencies = CORE.parse_frequency_response(responses["frequencies"])
    if len(frequencies) != CORE.EXPECTED_POINTS:
        raise AssertionError(
            f"{phase}: frequency grid has {len(frequencies)} points, expected {CORE.EXPECTED_POINTS}"
        )
    if not all(right > left for left, right in zip(frequencies, frequencies[1:])):
        raise AssertionError(f"{phase}: frequency grid is not strictly increasing")
    require_resumed(responses["status"])
    frame = session.capture_frame()
    frame_metrics = CORE.frame_metrics(frame)
    frame_path = store.output / f"{phase}-frame.rgb565be"
    frame_path.write_bytes(frame)
    identity = USB.snapshot_usb_identity(session.locator)
    USB.require_usb_identity(identity, args)
    return ({
        "usb_identity": identity,
        "version_sha256": CORE.sha256_bytes(responses["version"]),
        "info_sha256": CORE.sha256_bytes(responses["info"]),
        "frequency_points": len(frequencies),
        "frequency_start_hz": frequencies[0],
        "frequency_stop_hz": frequencies[-1],
        "frequency_sha256": CORE.sha256_bytes(responses["frequencies"]),
        "sweep_configuration_sha256": CORE.sha256_bytes(responses["sweep"]),
        "sweep_seconds": parse_sweeptime(responses["sweeptime"]),
        "status": "Resumed",
        "frame": {
            "bytes": len(frame),
            "sha256": CORE.sha256_bytes(frame),
            **frame_metrics,
        },
        "config_sha256": {
            command: CORE.sha256_bytes(responses[command]) for command in CONFIG_COMMANDS
        },
    }, responses)


def validate_args(args: argparse.Namespace) -> None:
    if args.confirm != CONFIRMATION:
        raise ValueError(
            f"--confirm must be exactly {CONFIRMATION}; this runner sends one reset"
        )
    if args.output.exists():
        raise RuntimeError(f"output path already exists; choose a fresh path: {args.output}")
    if not args.expected_usb_serial or not args.expected_usb_location:
        raise ValueError("exact USB serial and location are required")
    if not args.expected_version or not re.fullmatch(r"[ -~]+", args.expected_version):
        raise ValueError("--expected-version must be non-empty printable ASCII")
    if not re.fullmatch(r"[0-9a-f]{64}", args.expected_candidate_sha256):
        raise ValueError("--expected-candidate-sha256 must be 64 lowercase hex digits")
    if not re.fullmatch(r"[0-9a-f]{64}", args.expected_flash_inventory_sha256):
        raise ValueError("--expected-flash-inventory-sha256 must be 64 lowercase hex digits")
    if not re.fullmatch(r"[0-9a-f]{64}", args.expected_flash_run_sha256):
        raise ValueError("--expected-flash-run-sha256 must be 64 lowercase hex digits")
    if not args.candidate_bin.is_file():
        raise ValueError(f"--candidate-bin is not a regular file: {args.candidate_bin}")
    actual = CORE.sha256_file(args.candidate_bin)
    if actual != args.expected_candidate_sha256:
        raise ValueError(
            f"candidate binary SHA-256 mismatch: expected {args.expected_candidate_sha256}, got {actual}"
        )
    if not math.isfinite(args.reset_wait) or not 1.0 <= args.reset_wait <= 10.0:
        raise ValueError("--reset-wait must be within 1..10 seconds")
    if (
        not math.isfinite(args.reenumeration_timeout)
        or args.reenumeration_timeout <= 0.0
        or args.reenumeration_timeout > 300.0
    ):
        raise ValueError("--reenumeration-timeout must be finite and within (0, 300] seconds")
    USB.validate_flash_evidence(args.flash_evidence, args)


def capture_run(args: argparse.Namespace) -> int:
    validate_args(args)
    candidate = args.candidate_bin.resolve()
    flash_evidence = USB.validate_flash_evidence(args.flash_evidence, args)
    arguments = {
        "confirmation": args.confirm,
        "port": args.port,
        "vid": f"0x{args.vid:04x}",
        "pid": f"0x{args.pid:04x}",
        "expected_usb_serial": args.expected_usb_serial,
        "expected_usb_location": args.expected_usb_location,
        "expected_version": args.expected_version,
        "reset_wait_seconds": args.reset_wait,
        "candidate_binary": {
            "path": str(candidate),
            "bytes": candidate.stat().st_size,
            "sha256": args.expected_candidate_sha256,
            "local_hash_match": True,
            "device_byte_binding": True,
            "binding_scope": (
                "One-shot admitted DFU transfer and exact same-path flash read-back "
                "bind the local candidate bytes; exact-version authentication before "
                "and after reset binds this retention observation to the post-flash "
                "enumeration."
            ),
            "flash_evidence": flash_evidence,
        },
    }
    store = ResetStore(args.output, arguments)
    locator = CORE.PortLocator(
        args.port, args.vid, args.pid, args.expected_usb_serial,
        args.reenumeration_timeout, store.event,
    )
    session = ResetSession(locator, store)
    result = "FAIL"
    try:
        connect_response = session.connect()
        store.save_response("before", "connect", connect_response)
        before, before_responses = collect_snapshot(session, store, "before", args)
        store.metadata["before"] = before
        store.persist()

        store.event("ZS407_PHYSICAL_RESET=ATTEMPT count=1 wire=reset\\r")
        store.metadata["reset"].update({
            "attempted_count": 1,
            "attempted_utc": CORE.utc_now(),
        })
        store.persist()
        reset_delivery = session.send_reset_once()
        reset_response = reset_delivery.pop("response")
        store.metadata["reset"].update({
            "sent_count": 1 if session.reset_sent else 0,
            "transport_completed_utc": CORE.utc_now(),
            "response_sha256": CORE.sha256_bytes(reset_response),
            **reset_delivery,
        })
        store.save_response("reset", "reset", reset_response)
        store.persist()
        time.sleep(args.reset_wait)

        reconnect_response = session.connect()
        store.save_response("after", "connect", reconnect_response)
        after, after_responses = collect_snapshot(session, store, "after", args)
        store.metadata["after"] = after

        config_mismatches = [
            command for command in CONFIG_COMMANDS
            if before_responses[command] != after_responses[command]
        ]
        same_usb = before["usb_identity"] == after["usb_identity"]
        same_version = before_responses["version"] == after_responses["version"]
        same_info = before_responses["info"] == after_responses["info"]
        same_sweep_configuration = before_responses["sweep"] == after_responses["sweep"]
        same_grid = before_responses["frequencies"] == after_responses["frequencies"]
        sweep_delta = abs(float(after["sweep_seconds"]) - float(before["sweep_seconds"]))
        sweep_tolerance = float(before["sweep_seconds"]) * 0.10 + 0.010
        sweep_performance_retained = sweep_delta <= sweep_tolerance
        retention = {
            "pass": (
                same_usb and same_version and same_info and same_sweep_configuration
                and same_grid and sweep_performance_retained and not config_mismatches
                and session.reset_attempted and session.reset_sent
                and bool(reset_delivery["transport_disconnect_observed"])
            ),
            "same_usb_identity": same_usb,
            "same_version_response": same_version,
            "same_info_response": same_info,
            "same_sweep_configuration": same_sweep_configuration,
            "same_frequency_grid": same_grid,
            "sweep_time_delta_seconds": sweep_delta,
            "sweep_time_tolerance_seconds": sweep_tolerance,
            "sweep_performance_retained": sweep_performance_retained,
            "config_mismatches": config_mismatches,
            "reset_attempted_exactly_once": session.reset_attempted,
            "reset_wire_write_completed": session.reset_sent,
            "reset_transport_disconnect_observed": bool(
                reset_delivery["transport_disconnect_observed"]
            ),
        }
        store.metadata["retention"] = retention
        store.persist()
        if not retention["pass"]:
            raise AssertionError(f"warm-reset retention mismatch: {retention}")
        store.event(
            "ZS407_PHYSICAL_RESET_RETENTION=PASS reset_count=1 "
            f"sweep_delta_seconds={sweep_delta:.6f} config_observations={len(CONFIG_COMMANDS)}"
        )
        result = "PASS"
        return 0
    except Exception as error:
        store.event(f"ZS407_PHYSICAL_RESET_RETENTION=FAIL error={error}")
        print(f"error: {error}", file=sys.stderr)
        return 1
    finally:
        session.close()
        store.finalize(result, locator)


def parse_int(value: str) -> int:
    return int(value, 0)


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="capture one controlled physical tinySA4 warm-reset retention cycle"
    )
    parser.add_argument("--port", default="auto")
    parser.add_argument("--vid", type=parse_int, default=CORE.DEFAULT_VID)
    parser.add_argument("--pid", type=parse_int, default=CORE.DEFAULT_PID)
    parser.add_argument("--expected-usb-serial", required=True)
    parser.add_argument("--expected-usb-location", required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--candidate-bin", required=True, type=Path)
    parser.add_argument("--expected-candidate-sha256", required=True)
    parser.add_argument("--flash-evidence", required=True, type=Path)
    parser.add_argument("--expected-flash-inventory-sha256", required=True)
    parser.add_argument("--expected-flash-run-sha256", required=True)
    parser.add_argument("--confirm", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--reset-wait", type=float, default=2.0)
    parser.add_argument("--reenumeration-timeout", type=float, default=30.0)
    return parser.parse_args(argv)


def main() -> int:
    try:
        return capture_run(parse_args())
    except (RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
