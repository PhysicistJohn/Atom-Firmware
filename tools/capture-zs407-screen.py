#!/usr/bin/env python3
"""Capture or decode the ZS407 LCD's RGB565 panel-order byte stream."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time
from typing import Any


WIDTH = 480
HEIGHT = 320
PIXEL_BYTES = WIDTH * HEIGHT * 2
PROMPT = b"ch> "
CAPTURE_ECHO = b"capture\r\n"


def read_until(port: Any, marker: bytes, timeout: float) -> bytes:
    deadline = time.monotonic() + timeout
    response = bytearray()
    while marker not in response:
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"marker {marker!r} not received ({len(response)} bytes read)"
            )
        chunk = port.read(max(port.in_waiting, 1))
        if chunk:
            response.extend(chunk)
    return bytes(response)


def read_exact(port: Any, size: int, timeout: float) -> bytes:
    deadline = time.monotonic() + timeout
    response = bytearray()
    while len(response) < size:
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"framebuffer incomplete: {len(response)} of {size} bytes"
            )
        chunk = port.read(min(max(port.in_waiting, 1), size - len(response)))
        if chunk:
            response.extend(chunk)
    return bytes(response)


def capture_frame(port_name: str) -> bytes:
    try:
        import serial
    except ImportError as error:
        raise RuntimeError(
            "capture requires pyserial; decoding an existing frame does not"
        ) from error

    device = serial.Serial()
    device.port = port_name
    device.baudrate = 115200
    device.timeout = 0.05
    device.write_timeout = 1.0
    device.rts = False
    device.dtr = False
    device.exclusive = True

    try:
        device.open()
        time.sleep(0.25)
        device.write(b"\r")
        device.flush()
        read_until(device, PROMPT, 5.0)

        device.write(b"capture\r")
        device.flush()
        prefix = read_until(device, CAPTURE_ECHO, 5.0)
        trailing = prefix.split(CAPTURE_ECHO, 1)[1]
        if len(trailing) > PIXEL_BYTES:
            raise RuntimeError(
                "capture response contained more than one framebuffer"
            )
        frame = trailing + read_exact(
            device, PIXEL_BYTES - len(trailing), 20.0
        )
        prompt = read_exact(device, len(PROMPT), 5.0)
        if prompt != PROMPT:
            raise RuntimeError(
                "framebuffer was not followed by the exact shell prompt: "
                f"{prompt!r}"
            )
        return frame
    finally:
        if device.is_open:
            device.close()


def rgb565be_to_ppm(frame: bytes) -> bytes:
    """Return PPM bytes from canonical RGB565 high-byte-first panel bytes."""
    if len(frame) != PIXEL_BYTES:
        raise ValueError(
            f"expected {PIXEL_BYTES} framebuffer bytes, got {len(frame)}"
        )

    rgb = bytearray(WIDTH * HEIGHT * 3)
    target = 0
    for offset in range(0, len(frame), 2):
        pixel = (frame[offset] << 8) | frame[offset + 1]
        red = (pixel >> 11) & 0x1F
        green = (pixel >> 5) & 0x3F
        blue = pixel & 0x1F
        rgb[target] = (red << 3) | (red >> 2)
        rgb[target + 1] = (green << 2) | (green >> 4)
        rgb[target + 2] = (blue << 3) | (blue >> 2)
        target += 3
    return f"P6\n{WIDTH} {HEIGHT}\n255\n".encode("ascii") + rgb


def output_path(base: Path, extension: str) -> Path:
    """Append an extension without truncating version-like suffixes."""
    return Path(f"{base}{extension}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Capture or decode the ZS407's 480x320 RGB565 high-byte-first "
            "LCD stream"
        )
    )
    commands = parser.add_subparsers(dest="command", required=True)
    capture = commands.add_parser("capture", help="read one physical LCD frame")
    capture.add_argument("port")
    capture.add_argument("output", type=Path, help="output base path")
    decode = commands.add_parser("decode", help="decode an existing raw frame")
    decode.add_argument("input", type=Path)
    decode.add_argument("output", type=Path, help="output base path")
    args = parser.parse_args()

    try:
        if args.command == "capture":
            frame = capture_frame(args.port)
            raw_path = output_path(args.output, ".rgb565be")
            raw_path.write_bytes(frame)
            print(f"captured {len(frame)} bytes to {raw_path}")
        else:
            frame = args.input.read_bytes()

        ppm_path = output_path(args.output, ".ppm")
        ppm_path.write_bytes(rgb565be_to_ppm(frame))
        print(f"wrote {ppm_path}")
        return 0
    except (OSError, RuntimeError, TimeoutError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
