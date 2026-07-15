#!/usr/bin/env python3
"""Capture the physical case-3 disconnected-CAL negative control and recovery.

This runner deliberately has no DFU, flashing, reset, save, clear, calibration,
or configuration-write support.  It is invoked once while the short CAL-to-RF
cable is physically disconnected and again after a human reconnects it.  The
recovery invocation authenticates and hash-binds the completed disconnected
evidence before it opens the serial device.

Both phases run only ``selftest 0 3``, wait a fixed interval, capture two exact
307,200-byte LCD readbacks, and acknowledge the retained result using the
normal touch/release sequence.  The negative phase proves the firmware's
durable red ``Test 3: Signal level Fail`` status line, and recovery proves the
corresponding green ``Test 3: Pass`` status line.  Read-only palette and all
twelve correction-table observations must remain byte-identical before and
after either phase.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import importlib.util
import json
import math
from pathlib import Path
import re
import sys
import time
from typing import Any, Iterable


TOOL_PATH = Path(__file__).resolve()
ROOT = TOOL_PATH.parents[1]
SUPPORT_PATH = TOOL_PATH.with_name("capture-physical-selftests.py")
FONT_PATH = ROOT / "Font5x7.c"


def load_support() -> Any:
    spec = importlib.util.spec_from_file_location(
        "physical_selftest_negative_capture_support", SUPPORT_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load physical capture support from {SUPPORT_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CAPTURE = load_support()

CASE_NUMBER = 3
ZERO_BASED_CASE = 2
SCHEMA = "tinysa-physical-selftest-negative-v1"
DISCONNECTED_TOKEN = "CAL-RF-LOOPBACK-DISCONNECTED"
RECOVERY_TOKEN = "CAL-RF-LOOPBACK-RECONNECTED"
BRIGHT_RED_PALETTE_INDEX = 20
BRIGHT_GREEN_PALETTE_INDEX = 21
FONT_START = 0x16
FONT_HEIGHT = 7


@dataclass(frozen=True)
class ScreenLiteral:
    text: str
    x: int
    y: int
    palette_index: int


@dataclass(frozen=True)
class PhaseSpec:
    name: str
    confirmation: str
    literals: tuple[ScreenLiteral, ...]


PHASES = {
    "disconnected": PhaseSpec(
        "disconnected",
        DISCONNECTED_TOKEN,
        (
            ScreenLiteral(
                "Test 3: Signal level Fail",
                55,
                76,
                BRIGHT_RED_PALETTE_INDEX,
            ),
        ),
    ),
    "recovery": PhaseSpec(
        "recovery",
        RECOVERY_TOKEN,
        (
            ScreenLiteral(
                "Test 3: Pass",
                55,
                76,
                BRIGHT_GREEN_PALETTE_INDEX,
            ),
        ),
    ),
}


READ_ONLY_COMMANDS = frozenset(
    (
        "version",
        "info",
        *CAPTURE.EVIDENCE_COMMANDS,
        "color",
        *(f"correction {table}" for table in CAPTURE.CORRECTION_TABLES),
    )
)
RAM_ONLY_ACTION_COMMANDS = frozenset(
    (f"selftest 0 {CASE_NUMBER}", "touch 200 150", "release")
)
ALLOWED_COMMANDS = READ_ONLY_COMMANDS | RAM_ONLY_ACTION_COMMANDS


class SafeShellSession(CAPTURE.ShellSession):
    """Enforce the complete shell-command allowlist before touching serial."""

    def command(
        self,
        command: str,
        timeout: float = 30.0,
        retry_read_only: bool = False,
    ) -> bytes:
        if command not in ALLOWED_COMMANDS:
            raise ValueError(
                f"command is outside the negative-control allowlist: {command!r}"
            )
        if retry_read_only and command not in READ_ONLY_COMMANDS and command != "release":
            raise ValueError(
                f"non-idempotent action cannot use read-only retry: {command!r}"
            )
        return super().command(command, timeout, retry_read_only)

    def capture_frame(self) -> bytes:
        """Use the separately framed, read-only binary ``capture`` transport."""
        return super().capture_frame()


# Kept as replaceable module bindings so the orchestration is hardware-free
# testable without importing or opening pyserial.
PORT_LOCATOR_CLASS = CAPTURE.PortLocator
SESSION_CLASS = SafeShellSession


class NegativeEvidenceStore(CAPTURE.EvidenceStore):
    def __init__(
        self,
        output: Path,
        variant: str,
        expected_version: str,
        phase: PhaseSpec,
        arguments: dict[str, Any],
        prior_binding: dict[str, Any] | None,
    ) -> None:
        super().__init__(output, variant, expected_version, [ZERO_BASED_CASE], arguments)
        self.metadata.update(
            {
                "schema": SCHEMA,
                "phase": phase.name,
                "confirmation": phase.confirmation,
                "selftest_argument": CASE_NUMBER,
                "zero_based_case": ZERO_BASED_CASE,
                "prior_disconnected_evidence": prior_binding,
                "command_policy": {
                    "read_only": sorted(READ_ONLY_COMMANDS),
                    "ram_only_actions": sorted(RAM_ONLY_ACTION_COMMANDS),
                    "read_only_capture_transport": {
                        "shell_sync": "single carriage return on connect",
                        "wire_command": "capture",
                        "expected_frame_bytes": CAPTURE.PIXEL_BYTES,
                        "expected_trailer": CAPTURE.PROMPT.decode("ascii"),
                    },
                    "forbidden_capabilities": [
                        "dfu",
                        "flash",
                        "save",
                        "reset",
                        "clear",
                        "calibration-write",
                        "correction-write",
                        "configuration-write",
                    ],
                },
                "implementation": {
                    "tool_sha256": CAPTURE.sha256_file(TOOL_PATH),
                    "capture_support_sha256": CAPTURE.sha256_file(SUPPORT_PATH),
                    "font_source_sha256": CAPTURE.sha256_file(FONT_PATH),
                },
            }
        )
        self.persist_metadata()


def normalized_lines(response: bytes) -> list[bytes]:
    return response.replace(b"\r", b"").split(b"\n")


def require_exact_version(response: bytes, expected: str) -> None:
    try:
        expected.encode("ascii")
    except UnicodeEncodeError as error:
        raise ValueError("--expected-version must be ASCII") from error
    CAPTURE.require_version(response, expected)


def parse_palette(response: bytes) -> dict[int, int]:
    """Return shell palette entries as exact RGB565 values."""
    palette: dict[int, int] = {}
    pattern = re.compile(rb"[ \t]*([0-9]+):[ \t]*0x([0-9A-Fa-f]{6})[ \t]*")
    for line in normalized_lines(response):
        match = pattern.fullmatch(line)
        if not match:
            continue
        index = int(match.group(1))
        rgb24 = int(match.group(2), 16)
        red = (rgb24 >> 16) & 0xFF
        green = (rgb24 >> 8) & 0xFF
        blue = rgb24 & 0xFF
        palette[index] = ((red >> 3) << 11) | ((green >> 2) << 5) | (blue >> 3)
    return palette


def load_font_rows(path: Path = FONT_PATH) -> dict[int, tuple[int, tuple[int, ...]]]:
    """Load the active 5x7 bitmap table used by the retained status overlay."""
    source = path.read_text(encoding="utf-8")
    marker = "// Char 0x16 width = 8"
    if marker not in source:
        raise ValueError(f"active font-table marker is missing from {path}")
    active = source.split(marker, 1)[1]
    tokens = re.findall(
        r"^[ \t]*0b([01]{8})(?:\|CW_([0-9]{2}))?,", active, re.MULTILINE
    )
    if not tokens or len(tokens) % FONT_HEIGHT:
        raise ValueError(
            f"active font table has {len(tokens)} rows; expected a multiple of {FONT_HEIGHT}"
        )
    glyphs: dict[int, tuple[int, tuple[int, ...]]] = {}
    for glyph_index in range(len(tokens) // FONT_HEIGHT):
        rows: list[int] = []
        for bits, width_macro in tokens[
            glyph_index * FONT_HEIGHT : (glyph_index + 1) * FONT_HEIGHT
        ]:
            value = int(bits, 2)
            if width_macro:
                width = int(width_macro)
                if width < 1 or width > 8:
                    raise ValueError(f"invalid font width macro CW_{width_macro}")
                value |= 8 - width
            rows.append(value)
        width = 8 - (rows[0] & 0x07)
        if width < 1 or width > 8:
            raise ValueError(f"invalid encoded font width {width}")
        glyphs[FONT_START + glyph_index] = (width, tuple(rows))
    return glyphs


def literal_pixels(
    literal: ScreenLiteral,
    glyphs: dict[int, tuple[int, tuple[int, ...]]],
) -> tuple[set[tuple[int, int]], set[tuple[int, int]]]:
    on: set[tuple[int, int]] = set()
    off: set[tuple[int, int]] = set()
    x = literal.x
    for character in literal.text:
        code = ord(character)
        if code not in glyphs:
            raise ValueError(f"font table does not contain {character!r} (0x{code:02x})")
        width, rows = glyphs[code]
        for row, bits in enumerate(rows):
            y = literal.y + row
            for column in range(width):
                coordinate = (x + column, y)
                if not (0 <= coordinate[0] < CAPTURE.WIDTH and 0 <= y < CAPTURE.HEIGHT):
                    raise ValueError(
                        f"literal {literal.text!r} extends outside the LCD at {coordinate}"
                    )
                if bits & (0x80 >> column):
                    on.add(coordinate)
                else:
                    off.add(coordinate)
        x += width
    off.difference_update(on)
    return on, off


def frame_pixel(frame: bytes, x: int, y: int) -> int:
    offset = 2 * (y * CAPTURE.WIDTH + x)
    return (frame[offset] << 8) | frame[offset + 1]


def inspect_literal(
    frame: bytes,
    literal: ScreenLiteral,
    palette: dict[int, int],
    glyphs: dict[int, tuple[int, tuple[int, ...]]],
) -> dict[str, Any]:
    if len(frame) != CAPTURE.PIXEL_BYTES:
        raise ValueError(
            f"frame has {len(frame)} bytes; expected {CAPTURE.PIXEL_BYTES}"
        )
    if literal.palette_index not in palette:
        raise AssertionError(
            f"color output has no palette index {literal.palette_index}"
        )
    expected = palette[literal.palette_index]
    on, off = literal_pixels(literal, glyphs)
    matched = sum(frame_pixel(frame, x, y) == expected for x, y in on)
    off_collisions = sum(frame_pixel(frame, x, y) == expected for x, y in off)
    passed = matched == len(on) and off_collisions == 0 and bool(on)
    return {
        "text": literal.text,
        "x": literal.x,
        "y": literal.y,
        "palette_index": literal.palette_index,
        "expected_rgb565": f"0x{expected:04x}",
        "ink_pixels": len(on),
        "matched_ink_pixels": matched,
        "ink_match_ratio": matched / len(on) if on else 0.0,
        "background_pixels": len(off),
        "foreground_collisions_in_background": off_collisions,
        "pass": passed,
    }


def inspect_phase_screen(
    frame: bytes,
    phase: PhaseSpec,
    color_response: bytes,
    glyphs: dict[int, tuple[int, tuple[int, ...]]] | None = None,
) -> dict[str, Any]:
    if not phase.literals:
        return {
            "method": "hash-bound-frame-for-manual-review",
            "literal_source": None,
            "literals": [],
            "literal_match": None,
            "pass": None,
            "manual_review_required": True,
            "gate": False,
            "qualification": "PROVISIONAL",
        }
    palette = parse_palette(color_response)
    if glyphs is None:
        glyphs = load_font_rows()
    records = [
        inspect_literal(frame, literal, palette, glyphs)
        for literal in phase.literals
    ]
    literal_match = all(record["pass"] for record in records)
    return {
        "method": "exact-font-mask-and-observed-palette-rgb565",
        "literal_source": (
            "sa_core.c cell_draw_test_info retained case-3 status overlay"
        ),
        "literals": records,
        "literal_match": literal_match,
        "pass": literal_match,
        "manual_review_required": not literal_match,
        "gate": True,
        "qualification": "PASS" if literal_match else "FAIL",
    }


def inspect_trace_condition(phase: PhaseSpec, evidence: dict[str, Any]) -> dict[str, Any]:
    metrics = evidence.get("trace_metrics")
    if not isinstance(metrics, list) or not metrics:
        raise AssertionError("case-3 shell evidence has no actual-trace metrics")
    maximum = float(metrics[0]["maximum"])
    if phase.name == "disconnected":
        passed = maximum < -60.0
        condition = "shell-rounded actual trace maximum < -60.00 dBm"
    else:
        passed = maximum >= -60.0
        condition = "shell-rounded actual trace maximum >= -60.00 dBm"
    result = {
        "condition": condition,
        "threshold_dbm": -60.0,
        "actual_trace_maximum_dbm": maximum,
        "shell_precision_db": 0.01,
        "rounding_caveat": (
            "The shell reports 0.01 dB precision while firmware evaluates its "
            "internal peak before formatting. The disconnected strict '< -60.00' "
            "gate conservatively rejects a displayed -60.00 boundary value."
        ),
        "pass": passed,
        "role": (
            "hard disconnected branch corroboration"
            if phase.name == "disconnected"
            else "automated recovery corroboration; final screen review remains required"
        ),
    }
    if not passed:
        raise AssertionError(
            f"{phase.name} case-3 trace does not satisfy {condition}: {maximum:.2f} dBm"
        )
    return result


def validate_checksum_inventory(root: Path) -> dict[str, Any]:
    inventory = root / "SHA256SUMS"
    if not inventory.is_file():
        raise ValueError(f"missing checksum inventory: {inventory}")
    declared: dict[str, str] = {}
    malformed: list[str] = []
    for line in inventory.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match:
            malformed.append(line)
            continue
        relative = match.group(2)
        relative_path = Path(relative)
        if (
            relative_path.is_absolute()
            or ".." in relative_path.parts
            or relative in declared
        ):
            malformed.append(line)
            continue
        declared[relative] = match.group(1)
    actual = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS"
    )
    missing = sorted(set(actual) - set(declared))
    extra = sorted(set(declared) - set(actual))
    mismatched = sorted(
        relative
        for relative in set(actual) & set(declared)
        if CAPTURE.sha256_file(root / relative) != declared[relative]
    )
    result = {
        "pass": not malformed and not missing and not extra and not mismatched,
        "sha256": CAPTURE.sha256_file(inventory),
        "entries": len(declared),
        "malformed": malformed,
        "missing": missing,
        "extra": extra,
        "mismatched": mismatched,
    }
    if not result["pass"]:
        raise ValueError(f"prior evidence checksum inventory is invalid: {result}")
    return result


def normalize_usb_identity(identity: Any, label: str) -> dict[str, Any]:
    if identity is None:
        raise ValueError(f"{label} USB identity is missing")
    if not isinstance(identity, dict):
        try:
            identity = asdict(identity)
        except (TypeError, ValueError) as error:
            raise ValueError(f"{label} USB identity is malformed: {identity!r}") from error
    vid = identity.get("vid")
    pid = identity.get("pid")
    serial_number = identity.get("serial_number")
    location = identity.get("location")
    if type(vid) is not int or type(pid) is not int:
        raise ValueError(f"{label} USB identity has invalid VID/PID: {identity!r}")
    for field, value in (("serial_number", serial_number), ("location", location)):
        if value is not None and (not isinstance(value, str) or not value):
            raise ValueError(
                f"{label} USB identity has invalid {field}: {value!r}"
            )
    if serial_number is None and location is None:
        raise ValueError(
            f"{label} USB identity has neither a stable serial number nor location"
        )
    return {
        "vid": vid,
        "pid": pid,
        "serial_number": serial_number,
        "location": location,
    }


def require_same_usb_identity(current: Any, prior: Any) -> dict[str, Any]:
    """Require exact VID/PID and every stable identifier recorded previously."""
    expected = normalize_usb_identity(prior, "prior disconnected")
    observed = normalize_usb_identity(current, "recovery")
    compared = ["vid", "pid"]
    mismatches: dict[str, dict[str, Any]] = {}
    for field in ("vid", "pid"):
        if observed[field] != expected[field]:
            mismatches[field] = {
                "expected": expected[field],
                "observed": observed[field],
            }
    for field in ("serial_number", "location"):
        if expected[field] is not None:
            compared.append(field)
            if observed[field] != expected[field]:
                mismatches[field] = {
                    "expected": expected[field],
                    "observed": observed[field],
                }
    result = {
        "pass": not mismatches,
        "semantics": (
            "VID/PID must match; each nonempty prior serial_number/location "
            "must also match exactly"
        ),
        "compared_fields": compared,
        "expected": expected,
        "observed": observed,
        "mismatches": mismatches,
    }
    if mismatches:
        raise AssertionError(f"recovery USB identity differs from prior run: {mismatches}")
    return result


def validate_prior_disconnected(
    root: Path, variant: str, expected_version: str
) -> dict[str, Any]:
    checksum = validate_checksum_inventory(root)
    metadata_path = root / "run.json"
    if not metadata_path.is_file():
        raise ValueError(f"prior evidence has no run.json: {root}")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    expected = {
        "schema": SCHEMA,
        "result": "PASS",
        "phase": "disconnected",
        "variant": variant,
        "expected_version": expected_version,
        "selftest_argument": CASE_NUMBER,
    }
    mismatches = {
        key: {"actual": metadata.get(key), "expected": value}
        for key, value in expected.items()
        if metadata.get(key) != value
    }
    integrity = metadata.get("persisted_config_integrity")
    if not isinstance(integrity, dict) or not integrity.get("pass"):
        mismatches["persisted_config_integrity"] = {
            "actual": integrity,
            "expected": {"pass": True},
        }
    trace = metadata.get("trace_condition")
    if not isinstance(trace, dict) or not trace.get("pass"):
        mismatches["trace_condition"] = {
            "actual": trace,
            "expected": {"pass": True},
        }
    screen = metadata.get("screen_condition")
    if not isinstance(screen, dict) or not screen.get("pass"):
        mismatches["screen_condition"] = {
            "actual": screen,
            "expected": {"pass": True},
        }
    try:
        usb_identity = normalize_usb_identity(
            metadata.get("usb_identity"), "prior disconnected"
        )
    except ValueError as identity_error:
        mismatches["usb_identity"] = {
            "actual": metadata.get("usb_identity"),
            "expected": "valid VID/PID and at least one stable serial/location",
            "error": str(identity_error),
        }
        usb_identity = None
    if mismatches:
        raise ValueError(f"prior disconnected evidence is incompatible: {mismatches}")
    assert usb_identity is not None
    return {
        "path": str(root.resolve()),
        "sha256sums_sha256": checksum["sha256"],
        "entries": checksum["entries"],
        "run_json_sha256": CAPTURE.sha256_file(metadata_path),
        "finished_utc": metadata.get("finished_utc"),
        "result": "PASS",
        "usb_identity": usb_identity,
    }


def paths_overlap(first: Path, second: Path) -> bool:
    first_resolved = first.resolve()
    second_resolved = second.resolve()
    return (
        first_resolved == second_resolved
        or first_resolved in second_resolved.parents
        or second_resolved in first_resolved.parents
    )


def require_finite_bound(name: str, value: float, minimum: float) -> None:
    if not math.isfinite(value) or value < minimum:
        raise ValueError(f"--{name} must be finite and at least {minimum:g}")


def validate_arguments(args: argparse.Namespace) -> tuple[PhaseSpec, dict[str, Any] | None]:
    phase = PHASES[args.phase]
    if args.confirm != phase.confirmation:
        raise ValueError(
            f"--confirm for phase {phase.name!r} must be exactly "
            f"{phase.confirmation}; physically verify the CAL-to-RF cable first"
        )
    require_finite_bound("case-wait", args.case_wait, 15.0)
    require_finite_bound("pair-interval", args.pair_interval, 0.5)
    require_finite_bound("settle-retry-wait", args.settle_retry_wait, 0.0)
    require_finite_bound("ack-hold", args.ack_hold, 0.0)
    require_finite_bound(
        "reenumeration-timeout", args.reenumeration_timeout, 0.001
    )
    if args.settle_attempts < 1:
        raise ValueError("--settle-attempts must be positive")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", args.variant):
        raise ValueError(
            "--variant may contain only letters, digits, dot, underscore and dash"
        )
    if not args.expected_version or "\n" in args.expected_version or "\r" in args.expected_version:
        raise ValueError("--expected-version must be one nonempty line")
    if phase.name == "disconnected":
        if args.prior_disconnected_evidence is not None:
            raise ValueError(
                "--prior-disconnected-evidence is valid only for the recovery phase"
            )
        return phase, None
    if args.prior_disconnected_evidence is None:
        raise ValueError(
            "recovery requires --prior-disconnected-evidence from the completed "
            "disconnected phase"
        )
    if paths_overlap(args.output, args.prior_disconnected_evidence):
        raise ValueError(
            "recovery output and prior disconnected evidence must not be equal, "
            "ancestors, or descendants of one another"
        )
    return phase, validate_prior_disconnected(
        args.prior_disconnected_evidence, args.variant, args.expected_version
    )


def write_frame_products(
    store: NegativeEvidenceStore, frame: bytes
) -> dict[str, Any]:
    (store.output / "case-03.rgb565be").write_bytes(frame)
    comparator_frame = CAPTURE.rgb565be_to_rgb565le(frame)
    (store.output / "case-03.rgb565").write_bytes(comparator_frame)
    png = CAPTURE.rgb565be_to_png(frame)
    (store.output / "case-03.png").write_bytes(png)
    return {
        "comparator_rgb565_sha256": CAPTURE.sha256_bytes(comparator_frame),
        "png_sha256": CAPTURE.sha256_bytes(png),
    }


def acknowledge_case_safely(
    session: SafeShellSession,
    store: NegativeEvidenceStore,
    hold_seconds: float,
) -> None:
    """Always release touch; never call an uncertain touch delivery a PASS."""
    touch_error: Exception | None = None
    release_error: Exception | None = None
    try:
        response = session.command("touch 200 150", timeout=10.0)
        store.add_transcript("case 03: touch 200 150", response)
    except Exception as error:
        touch_error = error
        store.event(
            f"touch_delivery_uncertain case={CASE_NUMBER} error={error}; "
            "will perform best-effort release and fail this phase"
        )
        session.close()
    finally:
        try:
            time.sleep(hold_seconds)
        finally:
            try:
                response = session.command(
                    "release", timeout=10.0, retry_read_only=True
                )
                store.add_transcript("case 03: release", response)
            except Exception as error:
                release_error = error
                store.event(
                    f"touch_release_failed case={CASE_NUMBER} error={error}"
                )
            finally:
                time.sleep(2.0)

    if touch_error is not None or release_error is not None:
        details = []
        if touch_error is not None:
            details.append(f"touch delivery uncertain: {touch_error}")
        if release_error is not None:
            details.append(f"release failed: {release_error}")
        raise RuntimeError("; ".join(details))
    store.event(f"ZS407_PHYSICAL_NEGATIVE_ACK=PASS case={CASE_NUMBER}")


def capture_run(args: argparse.Namespace) -> int:
    phase, prior_binding = validate_arguments(args)
    arguments = {
        "phase": phase.name,
        "port": args.port,
        "usb_serial": args.usb_serial,
        "vid": f"0x{args.vid:04x}",
        "pid": f"0x{args.pid:04x}",
        "case_wait_seconds": args.case_wait,
        "pair_interval_seconds": args.pair_interval,
        "settle_attempts": args.settle_attempts,
        "settle_retry_wait_seconds": args.settle_retry_wait,
        "ack_hold_seconds": args.ack_hold,
        "prior_disconnected_evidence": (
            str(args.prior_disconnected_evidence.resolve())
            if args.prior_disconnected_evidence is not None
            else None
        ),
    }
    store = NegativeEvidenceStore(
        args.output,
        args.variant,
        args.expected_version,
        phase,
        arguments,
        prior_binding,
    )
    locator = PORT_LOCATOR_CLASS(
        args.port,
        args.vid,
        args.pid,
        args.usb_serial,
        args.reenumeration_timeout,
        store.event,
    )
    session = SESSION_CLASS(locator, store)
    result = "FAIL"
    config_before: dict[str, bytes] | None = None
    errors: list[Exception] = []
    case_record: dict[str, Any] = {
        "zero_based_case": ZERO_BASED_CASE,
        "selftest_argument": CASE_NUMBER,
        "phase": phase.name,
        "started_utc": None,
        "finished_utc": None,
        "result": "INCOMPLETE",
    }
    store.metadata["cases"] = [case_record]
    store.persist_metadata()

    try:
        connect_response = session.connect()
        store.add_transcript("<connect>", connect_response)
        if prior_binding is not None:
            usb_binding = require_same_usb_identity(
                locator.identity, prior_binding["usb_identity"]
            )
            store.metadata["recovery_usb_identity_binding"] = usb_binding
            store.persist_metadata()
            store.event(
                "ZS407_PHYSICAL_NEGATIVE_USB_BINDING=PASS "
                "phase=recovery fields="
                + ",".join(usb_binding["compared_fields"])
            )
        version = session.command("version", retry_read_only=True)
        store.save_response(Path("device-version-before.txt"), "version before", version)
        require_exact_version(version, args.expected_version)
        info = session.command("info", retry_read_only=True)
        store.save_response(Path("device-info-before.txt"), "info before", info)
        config_before = CAPTURE.capture_persisted_config_evidence(
            session, store, "before"
        )
        store.event(
            "ZS407_PHYSICAL_NEGATIVE_IDENTITY=PASS "
            f"phase={phase.name} expected_version={args.expected_version}"
        )

        started = False
        uncertain_start = False
        case_record["started_utc"] = CAPTURE.utc_now()
        store.persist_metadata()
        try:
            store.event(
                "ZS407_PHYSICAL_NEGATIVE=START "
                f"phase={phase.name} case={CASE_NUMBER} "
                f"fixed_wait_seconds={args.case_wait:.1f}"
            )
            try:
                response = session.command(
                    f"selftest 0 {CASE_NUMBER}", timeout=10.0
                )
                started = True
                store.add_transcript(
                    f"{phase.name}: selftest 0 {CASE_NUMBER}", response
                )
            except (OSError, TimeoutError):
                uncertain_start = True
                raise
            time.sleep(args.case_wait)
            frame, display = CAPTURE.capture_stable_pair(
                session,
                store,
                CASE_NUMBER,
                args.settle_attempts,
                args.pair_interval,
                args.settle_retry_wait,
            )
            products = write_frame_products(store, frame)
            shell_evidence = CAPTURE.collect_case_evidence(
                session, store, CASE_NUMBER
            )
            screen_condition = inspect_phase_screen(
                frame, phase, config_before["color"]
            )
            store.metadata["screen_condition"] = screen_condition
            if not screen_condition.get("pass"):
                store.persist_metadata()
                raise AssertionError(
                    f"{phase.name} retained screen did not exactly match the "
                    "firmware's expected case-3 status literal"
                )
            trace_condition = inspect_trace_condition(phase, shell_evidence)
            store.metadata["trace_condition"] = trace_condition
            case_record.update(
                {
                    "display": display,
                    **products,
                    "shell_evidence": shell_evidence,
                    "screen_condition": screen_condition,
                    "trace_condition": trace_condition,
                    "result": "PASS",
                }
            )
            screen_state = (
                "MATCH" if screen_condition.get("literal_match") else "REVIEW_REQUIRED"
            )
            store.event(
                "ZS407_PHYSICAL_NEGATIVE_SCREEN=" + screen_state + " "
                f"phase={phase.name} case={CASE_NUMBER} "
                f"frame_sha256={display['sha256']}"
            )
        except Exception as error:
            errors.append(error)
            case_record["result"] = f"FAIL: {error}"
            store.event(
                "ZS407_PHYSICAL_NEGATIVE=FAIL "
                f"phase={phase.name} case={CASE_NUMBER} error={error}"
            )
        finally:
            if uncertain_start and not started:
                store.event(
                    "selftest_start_uncertain "
                    f"phase={phase.name}; waiting {args.case_wait:.1f}s "
                    "before recovery release"
                )
                time.sleep(args.case_wait)
                started = True
            if started:
                try:
                    acknowledge_case_safely(session, store, args.ack_hold)
                except Exception as ack_error:
                    errors.append(ack_error)
                    case_record["result"] = f"FAIL: acknowledgement: {ack_error}"
                    store.event(
                        "ZS407_PHYSICAL_NEGATIVE_ACK=FAIL "
                        f"phase={phase.name} error={ack_error}"
                    )
            case_record["finished_utc"] = CAPTURE.utc_now()
            store.persist_metadata()

        # Always attempt to authenticate the post-ack state and compare the
        # read-only persisted observations, even when a screen/trace gate failed.
        try:
            final_version = session.command("version", retry_read_only=True)
            store.save_response(
                Path("device-version-after.txt"), "version after", final_version
            )
            require_exact_version(final_version, args.expected_version)
            final_info = session.command("info", retry_read_only=True)
            store.save_response(Path("device-info-after.txt"), "info after", final_info)
            config_after = CAPTURE.capture_persisted_config_evidence(
                session, store, "after"
            )
            assert config_before is not None
            mismatches = sorted(
                command
                for command, response in config_before.items()
                if config_after.get(command) != response
            )
            store.metadata["persisted_config_integrity"] = {
                "pass": not mismatches,
                "commands": list(config_before),
                "mismatches": mismatches,
                "before_sha256": {
                    command: CAPTURE.sha256_bytes(response)
                    for command, response in config_before.items()
                },
                "after_sha256": {
                    command: CAPTURE.sha256_bytes(response)
                    for command, response in config_after.items()
                },
            }
            if mismatches:
                raise AssertionError(
                    "persisted calibration/palette observations changed: "
                    + ", ".join(mismatches)
                )
            store.event(
                "ZS407_PHYSICAL_NEGATIVE_PERSISTED_CONFIG=PASS "
                f"phase={phase.name} observations={len(config_before)}"
            )
        except Exception as state_error:
            errors.append(state_error)
            store.event(
                "ZS407_PHYSICAL_NEGATIVE_POST_STATE=FAIL "
                f"phase={phase.name} error={state_error}"
            )
        store.persist_metadata()

        if errors:
            raise RuntimeError("; ".join(str(error) for error in errors))
        result = "PASS"
        store.event(
            "ZS407_PHYSICAL_NEGATIVE_RUN=PASS "
            f"phase={phase.name} case={CASE_NUMBER} variant={args.variant}"
        )
        return 0
    except Exception as error:
        store.event(
            f"ZS407_PHYSICAL_NEGATIVE_RUN=FAIL phase={phase.name} error={error}"
        )
        print(f"error: {error}", file=sys.stderr)
        return 1
    finally:
        session.close()
        store.finalize(result, locator)


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "capture case-3 physical disconnected-CAL failure and reconnected "
            "recovery evidence; this tool never flashes or persists settings"
        )
    )
    parser.add_argument("--phase", choices=sorted(PHASES), required=True)
    parser.add_argument("--port", default="auto")
    parser.add_argument("--usb-serial")
    parser.add_argument("--vid", type=CAPTURE.parse_int, default=CAPTURE.DEFAULT_VID)
    parser.add_argument("--pid", type=CAPTURE.parse_int, default=CAPTURE.DEFAULT_PID)
    parser.add_argument("--variant", required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--prior-disconnected-evidence",
        type=Path,
        help="required for recovery; completed disconnected-phase directory",
    )
    parser.add_argument("--case-wait", type=float, default=30.0)
    parser.add_argument("--pair-interval", type=float, default=0.75)
    parser.add_argument("--settle-attempts", type=int, default=3)
    parser.add_argument("--settle-retry-wait", type=float, default=5.0)
    parser.add_argument("--ack-hold", type=float, default=1.5)
    parser.add_argument("--reenumeration-timeout", type=float, default=30.0)
    parser.add_argument(
        "--confirm",
        required=True,
        help=(
            f"must be {DISCONNECTED_TOKEN} for disconnected or "
            f"{RECOVERY_TOKEN} for recovery"
        ),
    )
    return parser.parse_args(argv)


def main() -> int:
    try:
        return capture_run(parse_args())
    except (RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
