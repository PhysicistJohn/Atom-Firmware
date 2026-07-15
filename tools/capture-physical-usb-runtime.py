#!/usr/bin/env python3
"""Capture non-mutating USB/runtime evidence from a physical tinySA4.

The command surface in this program is deliberately closed.  It can observe
identity, LCD frames, live sweep data, scheduler state, palette, and correction
tables; it cannot reset, touch, enter DFU, save, recall, or change configuration.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import importlib.util
import json
import math
from pathlib import Path
import re
import sys
import time
from types import ModuleType
from typing import Any, Iterable, Sequence


TOOL_PATH = Path(__file__).resolve()
SUPPORT_PATH = TOOL_PATH.with_name("capture-physical-selftests.py")


def _load_selftest_support() -> ModuleType:
    path = SUPPORT_PATH
    spec = importlib.util.spec_from_file_location("tinysa_physical_selftests", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load physical capture support from {path}")
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolves postponed annotations through sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CORE = _load_selftest_support()

DEFAULT_VID = CORE.DEFAULT_VID
DEFAULT_PID = CORE.DEFAULT_PID
PIXEL_BYTES = CORE.PIXEL_BYTES
EXPECTED_POINTS = CORE.EXPECTED_POINTS
PROMPT = CORE.PROMPT
CORRECTION_TABLES = CORE.CORRECTION_TABLES

READ_ONLY_COMMANDS = frozenset((
    "capture",
    "version",
    "frequencies",
    "trace",
    "trace 1 value",
    "data 2",
    "sweeptime",
    "status",
    "threads",
    "color",
    *(f"correction {table}" for table in CORRECTION_TABLES),
))
RUNTIME_COMMANDS = (
    "frequencies", "trace", "trace 1 value", "data 2",
    "sweeptime", "status", "threads",
)
CONFIG_COMMANDS = ("color", *(f"correction {table}" for table in CORRECTION_TABLES))
VERSION_FRAGMENTS = (b"ve", b"r", b"si", b"on\r")
FLASH_EVIDENCE_SCHEMA = "tinysa-physical-dfu-flash-evidence-v2"
USB_RUNTIME_SCHEMA = "tinysa-physical-usb-runtime-v2"
FLASH_EVIDENCE_MEMBERS = frozenset((
    "candidate.readback.bin",
    "candidate.snapshot.bin",
    "dfu-util-download.stderr.txt",
    "dfu-util-download.stdout.txt",
    "dfu-util-list.stderr.txt",
    "dfu-util-list.stdout.txt",
    "dfu-util-readback.stderr.txt",
    "dfu-util-readback.stdout.txt",
    "dfu-util-version.stderr.txt",
    "dfu-util-version.stdout.txt",
    "dfu-util.snapshot",
    "run.json",
))


def require_read_only_command(command: str) -> None:
    if command not in READ_ONLY_COMMANDS:
        raise ValueError(f"command is outside the closed read-only allowlist: {command!r}")


def require_exact_version(response: bytes, expected: str) -> None:
    lines = [line.strip() for line in response.replace(b"\r", b"").split(b"\n")]
    while lines and not lines[-1]:
        lines.pop()
    expected_bytes = expected.encode("ascii")
    reported = [line for line in lines if line.startswith(b"tinySA") and b"_v" in line]
    if not lines or lines[0] != b"version" or lines[-1] != PROMPT.strip():
        raise AssertionError(
            "version response has stale/prefixed data, a missing exact echo, or no exact prompt: "
            f"{CORE.visible(response)!r}"
        )
    if reported != [expected_bytes]:
        raise AssertionError(
            f"exact version mismatch: expected {expected!r}, reported "
            f"{[line.decode('ascii', 'backslashreplace') for line in reported]!r}"
        )


def _usb_dict(identity: Any) -> dict[str, Any]:
    return {
        "vid": int(identity.vid),
        "pid": int(identity.pid),
        "serial_number": identity.serial_number,
        "location": identity.location,
    }


def snapshot_usb_identity(locator: Any) -> dict[str, Any]:
    """Re-enumerate and return the identity at the resolved serial path."""
    device = locator.resolve()
    matches = [port for port in locator._ports() if port.device == device]
    if len(matches) != 1:
        raise AssertionError(
            f"resolved serial path {device!r} has {len(matches)} USB identities"
        )
    port = matches[0]
    if port.vid is None or port.pid is None:
        raise AssertionError(f"resolved serial path {device!r} has no USB VID/PID")
    return {
        "vid": int(port.vid),
        "pid": int(port.pid),
        "serial_number": port.serial_number,
        "location": port.location,
    }


def require_usb_identity(identity: dict[str, Any], args: argparse.Namespace) -> None:
    expected = {
        "vid": args.vid,
        "pid": args.pid,
        "serial_number": args.expected_usb_serial,
        "location": args.expected_usb_location,
    }
    if identity != expected:
        raise AssertionError(f"USB identity mismatch: expected {expected!r}, got {identity!r}")


class RuntimeEvidenceStore:
    def __init__(self, output: Path, arguments: dict[str, Any]) -> None:
        # A pre-existing empty directory is still stale/ambiguous evidence.
        if output.exists():
            raise RuntimeError(f"output path already exists; choose a fresh path: {output}")
        output.mkdir(parents=True)
        self.output = output
        self.log_path = output / "run.log"
        self.transcript_path = output / "run-transcript.md"
        self.transcript_entries: list[tuple[str, bytes]] = []
        self.metadata: dict[str, Any] = {
            "schema": USB_RUNTIME_SCHEMA,
            "started_utc": CORE.utc_now(),
            "finished_utc": None,
            "result": "INCOMPLETE",
            "arguments": arguments,
            "implementation": {
                "tool_sha256": CORE.sha256_file(TOOL_PATH),
                "capture_support_sha256": CORE.sha256_file(SUPPORT_PATH),
            },
            "candidate_binary": arguments["candidate_binary"],
            "authentication": None,
            "frames": [],
            "runtime_observations": {},
            "persisted_config_integrity": None,
            "final_identity": None,
            "port_history": [],
        }
        self.log_path.touch()
        self.transcript_path.write_text(
            "# tinySA4 physical USB/runtime transcript\n\n",
            encoding="utf-8",
        )
        self.persist_metadata()

    def event(self, message: str) -> None:
        line = f"{CORE.utc_now()} {message}"
        with self.log_path.open("a", encoding="utf-8") as target:
            target.write(line + "\n")
        print(line, flush=True)

    def add_transcript(self, heading: str, response: bytes) -> None:
        self.transcript_entries.append((heading, response))
        lines = [
            "# tinySA4 physical USB/runtime transcript", "",
            f"- Expected version: `{self.metadata['arguments']['expected_version']}`", "",
        ]
        for title, payload in self.transcript_entries:
            lines.extend((f"## `{title}`", "", "```text",
                          CORE.visible(payload).rstrip(), "```", ""))
        self.transcript_path.write_text("\n".join(lines), encoding="utf-8")

    def save_response(self, filename: str, heading: str, response: bytes) -> None:
        (self.output / filename).write_bytes(response)
        self.add_transcript(heading, response)

    def persist_metadata(self) -> None:
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
        self.persist_metadata()
        paths = sorted(
            path for path in self.output.rglob("*")
            if path.is_file() and path.name != "SHA256SUMS"
        )
        (self.output / "SHA256SUMS").write_text(
            "".join(
                f"{CORE.sha256_file(path)}  {path.relative_to(self.output)}\n"
                for path in paths
            ),
            encoding="utf-8",
        )


class ReadOnlyShellSession(CORE.ShellSession):
    def command(self, command: str, timeout: float = 30.0,
                retry_read_only: bool = False) -> bytes:
        require_read_only_command(command)
        return super().command(command, timeout=timeout, retry_read_only=retry_read_only)

    def command_fragmented(self, command: str, fragments: Sequence[bytes],
                           timeout: float = 30.0,
                           fragment_interval: float = 0.02) -> bytes:
        require_read_only_command(command)
        expected_wire = command.encode("ascii") + b"\r"
        if not fragments or any(not fragment for fragment in fragments):
            raise ValueError("fragment list must contain only non-empty byte strings")
        if b"".join(fragments) != expected_wire:
            raise ValueError("fragment sequence does not exactly encode the allowed command")
        if any(b"\r" in fragment for fragment in fragments[:-1]):
            raise ValueError("carriage return is permitted only in the final fragment")
        self.ensure_connected()
        for index, fragment in enumerate(fragments):
            self.port.write(fragment)
            self.port.flush()
            if fragment_interval and index + 1 < len(fragments):
                time.sleep(fragment_interval)
        return CORE.SCREEN_TOOL.read_until(self.port, PROMPT, timeout)

    def capture_frame(self) -> bytes:
        # The inherited implementation emits only the fixed literal "capture".
        require_read_only_command("capture")
        return super().capture_frame()


def capture_config(session: ReadOnlyShellSession, store: RuntimeEvidenceStore,
                   phase: str) -> dict[str, bytes]:
    responses: dict[str, bytes] = {}
    for command in CONFIG_COMMANDS:
        response = session.command(command, timeout=45.0, retry_read_only=True)
        responses[command] = response
        store.save_response(
            f"config-{phase}-{CORE.command_slug(command)}.txt",
            f"config {phase}: {command}", response,
        )
    return responses


def _require_response_payload(command: str, response: bytes) -> None:
    lines = [line.strip() for line in response.replace(b"\r", b"").split(b"\n")]
    payload = [line for line in lines if line and line not in (command.encode(), PROMPT.strip())]
    if not payload:
        raise AssertionError(f"{command!r} returned no observable payload")


def collect_runtime_observations(session: ReadOnlyShellSession,
                                 store: RuntimeEvidenceStore) -> dict[str, Any]:
    responses: dict[str, bytes] = {}
    for command in RUNTIME_COMMANDS:
        response = session.command(command, timeout=45.0, retry_read_only=True)
        responses[command] = response
        store.save_response(
            f"runtime-{CORE.command_slug(command)}.txt", command, response,
        )
        _require_response_payload(command, response)

    frequencies = CORE.parse_frequency_response(responses["frequencies"])
    trace = CORE.parse_trace_response(responses["trace 1 value"], 1)
    # cmd_data maps selector 2 to TRACE_ACTUAL; selector 0 is TRACE_TEMP.
    data = CORE.parse_data_response(responses["data 2"])
    if len(frequencies) != EXPECTED_POINTS:
        raise AssertionError(
            f"frequencies returned {len(frequencies)} points; expected {EXPECTED_POINTS}"
        )
    if len(trace) != EXPECTED_POINTS:
        raise AssertionError(
            f"trace 1 returned {len(trace)} points; expected {EXPECTED_POINTS}"
        )
    if len(data) != EXPECTED_POINTS:
        raise AssertionError(f"data 2 returned {len(data)} points; expected {EXPECTED_POINTS}")
    if not all(right > left for left, right in zip(frequencies, frequencies[1:])):
        raise AssertionError("frequency grid is not strictly increasing")
    metrics = CORE.trace_metrics(trace)
    trace_range = float(metrics["range"])
    if metrics["finite"] != EXPECTED_POINTS or not math.isfinite(trace_range):
        raise AssertionError("measured trace contains non-finite values")
    interior_range = max(trace[1:]) - min(trace[1:])
    ordered = sorted(trace)
    q05 = ordered[int(0.05 * (len(ordered) - 1))]
    q95 = ordered[int(0.95 * (len(ordered) - 1))]
    robust_range = q95 - q05
    if interior_range < 0.10 or robust_range < 0.25:
        raise AssertionError(f"measured trace is flat or invalid: range={trace_range!r} dB")
    data_trace_max_delta = max(abs(left - right) for left, right in zip(data, trace))
    if data_trace_max_delta > 0.011:
        raise AssertionError(
            "data 2 (TRACE_ACTUAL) and trace 1 disagree: maximum absolute delta "
            f"{data_trace_max_delta:.6f} dB"
        )
    status_lines = [
        line.strip() for line in responses["status"].replace(b"\r", b"").split(b"\n")
    ]
    if b"Resumed" not in status_lines:
        raise AssertionError(
            "runtime acquisition is not explicitly resumed: "
            f"{CORE.visible(responses['status'])!r}"
        )
    missing_threads = [
        name for name in ("main", "idle", "sweep", "shell")
        if re.search(rb"\b" + name.encode("ascii") + rb"\b", responses["threads"]) is None
    ]
    if missing_threads:
        raise AssertionError("threads response is missing: " + ", ".join(missing_threads))
    sweep_match = re.search(
        rb"(?:^|\s)([0-9]+(?:\.[0-9]+)?)\s*(ms|s)(?:\s|$)",
        responses["sweeptime"],
    )
    if sweep_match is None:
        raise AssertionError("sweeptime response contains no finite duration")
    sweep_value = float(sweep_match.group(1))
    sweep_seconds = sweep_value / 1000.0 if sweep_match.group(2) == b"ms" else sweep_value
    if not math.isfinite(sweep_seconds) or sweep_seconds <= 0.0:
        raise AssertionError(f"invalid sweep duration: {sweep_seconds!r}")
    return {
        "commands": list(RUNTIME_COMMANDS),
        "response_sha256": {
            command: CORE.sha256_bytes(response) for command, response in responses.items()
        },
        "frequency_points": len(frequencies),
        "frequency_start_hz": frequencies[0],
        "frequency_stop_hz": frequencies[-1],
        "trace_1_metrics": metrics,
        "trace_1_interior_range_db": interior_range,
        "trace_1_q05_dbm": q05,
        "trace_1_q95_dbm": q95,
        "trace_1_robust_range_db": robust_range,
        "data_trace_maximum_delta_db": data_trace_max_delta,
        "data_2_points": len(data),
        "acquisition_state": "Resumed",
        "sweep_seconds": sweep_seconds,
        "required_threads": ["main", "idle", "sweep", "shell"],
    }


def validate_flash_evidence(root: Path, args: argparse.Namespace) -> dict[str, Any]:
    if root.is_symlink():
        raise ValueError(f"flash evidence may not be a symlink: {root}")
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"flash evidence is not a regular directory: {root}")
    inventory = root / "SHA256SUMS"
    run_path = root / "run.json"
    if not inventory.is_file() or inventory.is_symlink() or not run_path.is_file():
        raise ValueError(f"flash evidence is incomplete: {root}")
    inventory_sha256 = CORE.sha256_file(inventory)
    run_json_sha256 = CORE.sha256_file(run_path)
    if inventory_sha256 != args.expected_flash_inventory_sha256:
        raise ValueError(
            "flash evidence inventory does not match the caller-pinned trust root: "
            f"expected {args.expected_flash_inventory_sha256}, got {inventory_sha256}"
        )
    if run_json_sha256 != args.expected_flash_run_sha256:
        raise ValueError(
            "flash evidence run.json does not match the caller-pinned trust root: "
            f"expected {args.expected_flash_run_sha256}, got {run_json_sha256}"
        )
    declared: dict[str, str] = {}
    for line in inventory.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match:
            raise ValueError(f"malformed flash evidence inventory line: {line!r}")
        relative = match.group(2)
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts or relative in declared:
            raise ValueError(f"unsafe flash evidence inventory path: {relative!r}")
        declared[relative] = match.group(1)
    actual = {
        path.relative_to(root).as_posix(): path
        for path in root.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS"
    }
    if set(actual) != set(declared):
        raise ValueError("flash evidence inventory does not exactly cover its files")
    if set(declared) != FLASH_EVIDENCE_MEMBERS:
        raise ValueError("flash evidence inventory has missing or unexpected members")
    for relative, path in actual.items():
        if path.is_symlink() or CORE.sha256_file(path) != declared[relative]:
            raise ValueError(f"flash evidence hash mismatch: {relative}")
    metadata = json.loads(run_path.read_text(encoding="utf-8"))
    if metadata.get("schema") != FLASH_EVIDENCE_SCHEMA or metadata.get("result") != "PASS":
        raise ValueError("flash evidence is not a completed PASS record")
    candidate = metadata.get("candidate")
    preflight = metadata.get("preflight")
    download = metadata.get("download")
    readback = metadata.get("readback")
    normal = metadata.get("normal_mode")
    binding = metadata.get("device_byte_binding")
    dfu_tool = metadata.get("dfu_tool")
    candidate_payload = args.candidate_bin.read_bytes()
    staged_payload = (root / "candidate.snapshot.bin").read_bytes()
    readback_payload = (root / "candidate.readback.bin").read_bytes()
    if staged_payload != candidate_payload or readback_payload != candidate_payload:
        raise ValueError(
            "flash evidence staged/readback bytes do not equal the admitted candidate"
        )
    if (
        not isinstance(candidate, dict)
        or candidate.get("sha256") != args.expected_candidate_sha256
        or candidate.get("staged_sha256") != args.expected_candidate_sha256
        or candidate.get("bytes") != len(candidate_payload)
        or candidate.get("staged_path") != "candidate.snapshot.bin"
    ):
        raise ValueError("flash evidence candidate hash does not match this run")
    if (
        not isinstance(dfu_tool, dict)
        or dfu_tool.get("staged_path") != "dfu-util.snapshot"
        or dfu_tool.get("sha256") != declared["dfu-util.snapshot"]
        or dfu_tool.get("bytes") != len((root / "dfu-util.snapshot").read_bytes())
        or dfu_tool.get("expected_version") != "dfu-util 0.11"
    ):
        raise ValueError("flash evidence does not authenticate the staged dfu-util")
    if (
        not isinstance(preflight, dict) or preflight.get("pass") is not True
        or preflight.get("vid") != 0x0483 or preflight.get("pid") != 0xDF11
        or preflight.get("path") != args.expected_usb_location
        or preflight.get("selected_alt") != 0 or preflight.get("rejected_alt") != 1
    ):
        raise ValueError("flash evidence lacks exact same-path alt-0 DFU admission")
    if (
        not isinstance(download, dict) or download.get("pass") is not True
        or download.get("attempt_count") != 1 or download.get("selected_alt") != 0
        or download.get("retry_performed") is not False
    ):
        raise ValueError("flash evidence lacks one-shot alternate-0 transfer success")
    candidate_bytes = args.candidate_bin.stat().st_size
    if (
        not isinstance(readback, dict) or readback.get("pass") is not True
        or readback.get("attempt_count") != 1 or readback.get("selected_alt") != 0
        or readback.get("retry_performed") is not False
        or readback.get("leave_requested_after_upload") is not True
        or readback.get("bytes") != candidate_bytes
        or readback.get("sha256") != args.expected_candidate_sha256
        or readback.get("exact_byte_match") is not True
    ):
        raise ValueError("flash evidence lacks exact same-device candidate read-back")
    if (
        not isinstance(binding, dict)
        or binding.get("candidate_sha256") != args.expected_candidate_sha256
        or binding.get("readback_sha256") != args.expected_candidate_sha256
        or binding.get("readback_performed") is not True
        or binding.get("exact_byte_match") is not True
    ):
        raise ValueError("flash evidence does not claim the verified byte binding")
    expected_normal = {
        "vid": args.vid,
        "pid": args.pid,
        "serial_number": args.expected_usb_serial,
        "location": args.expected_usb_location,
    }
    if not isinstance(normal, dict) or normal.get("pass") is not True:
        raise ValueError("flash evidence lacks normal-mode re-enumeration")
    mismatches = {
        field: {"expected": value, "observed": normal.get(field)}
        for field, value in expected_normal.items() if normal.get(field) != value
    }
    if mismatches:
        raise ValueError(f"flash evidence normal USB identity mismatch: {mismatches}")

    def transcript(stem: str) -> str:
        payload = b"".join(
            (root / f"{stem}.{stream}.txt").read_bytes()
            for stream in ("stdout", "stderr")
        )
        try:
            return payload.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError(f"flash evidence {stem} transcript is not UTF-8") from error

    version_lines = transcript("dfu-util-version").splitlines()
    if not version_lines or version_lines[0].strip() != "dfu-util 0.11":
        raise ValueError("flash evidence dfu-util version transcript mismatch")
    listing = transcript("dfu-util-list")
    listing_markers = (
        "Found DFU: [0483:df11]",
        "cfg=1, intf=0",
        f'path="{args.expected_usb_location}"',
        'alt=0, name="@Internal Flash  /0x08000000/128*0002Kg"',
        'alt=1, name="@Option Bytes  /0x1FFFF800/01*016 e"',
    )
    if any(marker not in listing for marker in listing_markers):
        raise ValueError("flash evidence DFU listing transcript is incomplete")
    if listing.count("Found DFU: [") != 2 or listing.count("cfg=1, intf=0") != 2:
        raise ValueError("flash evidence DFU listing has an unexpected device/interface count")
    download_text = transcript("dfu-util-download")
    if "Download done." not in download_text or "File downloaded successfully" not in download_text:
        raise ValueError("flash evidence download transcript lacks success markers")
    if "Upload done." not in transcript("dfu-util-readback"):
        raise ValueError("flash evidence readback transcript lacks success marker")
    return {
        "schema": metadata["schema"],
        "path": str(root),
        "inventory_sha256": inventory_sha256,
        "run_json_sha256": run_json_sha256,
        "candidate_sha256": candidate["sha256"],
        "dfu_location": preflight["path"],
        "dfu_serial": preflight.get("serial"),
        "selected_alt": 0,
        "normal_usb_identity": expected_normal,
        "readback_performed": True,
        "readback_sha256": readback["sha256"],
        "exact_byte_match": True,
    }


def validate_args(args: argparse.Namespace) -> None:
    if args.output.exists():
        raise RuntimeError(f"output path already exists; choose a fresh path: {args.output}")
    if not args.expected_version or not re.fullmatch(r"[ -~]+", args.expected_version):
        raise ValueError("--expected-version must be non-empty printable ASCII")
    if not args.expected_usb_serial:
        raise ValueError("--expected-usb-serial is required and may not be empty")
    if not args.expected_usb_location:
        raise ValueError("--expected-usb-location is required and may not be empty")
    if not re.fullmatch(r"[0-9a-f]{64}", args.expected_candidate_sha256):
        raise ValueError("--expected-candidate-sha256 must be 64 lowercase hex digits")
    if not re.fullmatch(r"[0-9a-f]{64}", args.expected_flash_inventory_sha256):
        raise ValueError("--expected-flash-inventory-sha256 must be 64 lowercase hex digits")
    if not re.fullmatch(r"[0-9a-f]{64}", args.expected_flash_run_sha256):
        raise ValueError("--expected-flash-run-sha256 must be 64 lowercase hex digits")
    if not args.candidate_bin.is_file():
        raise ValueError(f"--candidate-bin is not a regular file: {args.candidate_bin}")
    actual_candidate_sha256 = CORE.sha256_file(args.candidate_bin)
    if actual_candidate_sha256 != args.expected_candidate_sha256:
        raise ValueError(
            "candidate binary SHA-256 mismatch: expected "
            f"{args.expected_candidate_sha256}, got {actual_candidate_sha256}"
        )
    if not (0 <= args.vid <= 0xFFFF and 0 <= args.pid <= 0xFFFF):
        raise ValueError("--vid and --pid must be 16-bit USB identifiers")
    if not 2 <= args.frames <= 64:
        raise ValueError("--frames must be within 2..64 for live-display qualification")
    if not math.isfinite(args.frame_interval) or not 0.75 <= args.frame_interval <= 5.0:
        raise ValueError("--frame-interval must be within 0.75..5 seconds")
    if not math.isfinite(args.fragment_interval) or not 0 <= args.fragment_interval <= 1.0:
        raise ValueError("--fragment-interval must be within 0..1 second")
    if (
        not math.isfinite(args.reenumeration_timeout)
        or args.reenumeration_timeout <= 0.0
        or args.reenumeration_timeout > 300.0
    ):
        raise ValueError("--reenumeration-timeout must be finite and within (0, 300] seconds")
    validate_flash_evidence(args.flash_evidence, args)


def capture_run(args: argparse.Namespace) -> int:
    validate_args(args)
    candidate_path = args.candidate_bin.resolve()
    flash_evidence = validate_flash_evidence(args.flash_evidence, args)
    arguments = {
        "port": args.port,
        "vid": f"0x{args.vid:04x}",
        "pid": f"0x{args.pid:04x}",
        "expected_usb_serial": args.expected_usb_serial,
        "expected_usb_location": args.expected_usb_location,
        "expected_version": args.expected_version,
        "candidate_binary": {
            "path": str(candidate_path),
            "bytes": candidate_path.stat().st_size,
            "sha256": args.expected_candidate_sha256,
            "local_hash_match": True,
            "device_byte_binding": True,
            "binding_scope": (
                "One-shot admitted DFU transfer and exact same-path flash read-back "
                "bind the local candidate bytes; runtime exact-version authentication "
                "then binds this observation to the post-flash enumeration."
            ),
            "flash_evidence": flash_evidence,
        },
        "frames": args.frames,
        "frame_interval_seconds": args.frame_interval,
        "fragment_interval_seconds": args.fragment_interval,
    }
    store = RuntimeEvidenceStore(args.output, arguments)
    locator = CORE.PortLocator(
        args.port, args.vid, args.pid, args.expected_usb_serial,
        args.reenumeration_timeout, store.event,
    )
    session = ReadOnlyShellSession(locator, store)
    result = "FAIL"
    try:
        connect_response = session.connect()
        store.add_transcript("<connect>", connect_response)

        # Authenticate exact USB identity before issuing any named command.
        initial_identity = snapshot_usb_identity(locator)
        require_usb_identity(initial_identity, args)
        version = session.command_fragmented(
            "version", VERSION_FRAGMENTS,
            timeout=15.0, fragment_interval=args.fragment_interval,
        )
        store.save_response("device-version-fragmented.txt", "fragmented version", version)
        require_exact_version(version, args.expected_version)
        store.metadata["authentication"] = {
            "pass": True,
            "usb_identity": initial_identity,
            "version": args.expected_version,
            "version_response_sha256": CORE.sha256_bytes(version),
            "wire_fragment_hex": [fragment.hex() for fragment in VERSION_FRAGMENTS],
            "wire_reassembled_ascii": "version\\r",
        }
        store.persist_metadata()
        store.event(
            "ZS407_PHYSICAL_USB_AUTH=PASS "
            f"version={args.expected_version} serial={args.expected_usb_serial} "
            f"location={args.expected_usb_location}"
        )

        config_before = capture_config(session, store, "before")

        # Prove the normal acquisition path before sampling the live display.
        store.metadata["runtime_observations"] = collect_runtime_observations(session, store)
        store.persist_metadata()

        series_start = time.monotonic()
        for index in range(1, args.frames + 1):
            started_utc = CORE.utc_now()
            started = time.monotonic()
            frame = session.capture_frame()
            elapsed = time.monotonic() - started
            if len(frame) != PIXEL_BYTES:
                raise AssertionError(
                    f"frame {index} has {len(frame)} bytes; expected {PIXEL_BYTES}"
                )
            metrics = CORE.frame_metrics(frame)
            filename = f"frame-{index:02d}.rgb565be"
            (store.output / filename).write_bytes(frame)
            record = {
                "index": index,
                "started_utc": started_utc,
                "finished_utc": CORE.utc_now(),
                "elapsed_seconds": elapsed,
                "bytes": len(frame),
                "sha256": CORE.sha256_bytes(frame),
                **metrics,
            }
            store.metadata["frames"].append(record)
            store.persist_metadata()
            store.event(
                f"ZS407_PHYSICAL_USB_FRAME=PASS index={index}/{args.frames} "
                f"bytes={len(frame)} elapsed_seconds={elapsed:.6f} "
                f"sha256={record['sha256']}"
            )
            if index < args.frames:
                time.sleep(args.frame_interval)
        series_elapsed = time.monotonic() - series_start
        total_bytes = args.frames * PIXEL_BYTES
        distinct_frame_hashes = len({record["sha256"] for record in store.metadata["frames"]})
        if args.frames > 1 and distinct_frame_hashes < 2:
            raise AssertionError(
                "live display did not change across spaced captures; acquisition evidence "
                "is indistinguishable from a frozen screen"
            )
        store.metadata["frame_series"] = {
            "complete_frames": args.frames,
            "total_bytes": total_bytes,
            "elapsed_seconds": series_elapsed,
            "bytes_per_second": total_bytes / series_elapsed if series_elapsed else None,
            "frame_interval_seconds": args.frame_interval,
            "distinct_frame_hashes": distinct_frame_hashes,
        }

        config_after = capture_config(session, store, "after")
        mismatches = [
            command for command in CONFIG_COMMANDS
            if config_before[command] != config_after[command]
        ]
        store.metadata["persisted_config_integrity"] = {
            "pass": not mismatches,
            "commands": list(CONFIG_COMMANDS),
            "mismatches": mismatches,
            "before_sha256": {
                command: CORE.sha256_bytes(config_before[command]) for command in CONFIG_COMMANDS
            },
            "after_sha256": {
                command: CORE.sha256_bytes(config_after[command]) for command in CONFIG_COMMANDS
            },
        }
        store.persist_metadata()
        if mismatches:
            raise AssertionError(
                "palette/correction observations changed: " + ", ".join(mismatches)
            )

        final_version = session.command("version", timeout=15.0, retry_read_only=True)
        store.save_response("device-version-final.txt", "final version", final_version)
        require_exact_version(final_version, args.expected_version)
        final_identity = snapshot_usb_identity(locator)
        require_usb_identity(final_identity, args)
        if final_identity != initial_identity:
            raise AssertionError(
                f"USB identity changed during run: {initial_identity!r} -> {final_identity!r}"
            )
        store.metadata["final_identity"] = {
            "pass": True,
            "usb_identity": final_identity,
            "version": args.expected_version,
            "version_response_sha256": CORE.sha256_bytes(final_version),
        }
        store.persist_metadata()
        store.event(
            "ZS407_PHYSICAL_USB_RUNTIME=PASS "
            f"frames={args.frames} bytes={total_bytes} config_observations={len(CONFIG_COMMANDS)}"
        )
        result = "PASS"
        return 0
    except Exception as error:
        store.event(f"ZS407_PHYSICAL_USB_RUNTIME=FAIL error={error}")
        print(f"error: {error}", file=sys.stderr)
        return 1
    finally:
        session.close()
        store.finalize(result, locator)


def parse_int(value: str) -> int:
    return int(value, 0)


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="capture read-only physical tinySA4 USB/runtime evidence"
    )
    parser.add_argument("--port", default="auto")
    parser.add_argument("--vid", type=parse_int, default=DEFAULT_VID)
    parser.add_argument("--pid", type=parse_int, default=DEFAULT_PID)
    parser.add_argument("--expected-usb-serial", required=True)
    parser.add_argument("--expected-usb-location", required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--candidate-bin", required=True, type=Path)
    parser.add_argument("--expected-candidate-sha256", required=True)
    parser.add_argument("--flash-evidence", required=True, type=Path)
    parser.add_argument("--expected-flash-inventory-sha256", required=True)
    parser.add_argument("--expected-flash-run-sha256", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--frames", type=int, default=6)
    parser.add_argument("--frame-interval", type=float, default=1.0)
    parser.add_argument("--fragment-interval", type=float, default=0.02)
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
