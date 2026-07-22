#!/usr/bin/env python3
"""Compare the production Q15 FFT with Atom-DSP's language-neutral vector."""

import json
from pathlib import Path
import subprocess
import sys


def fail(message):
    raise SystemExit("Atom-DSP conformance: %s" % message)


def main():
    if len(sys.argv) != 3:
        fail("usage: check-atom-dsp-conformance.py VECTOR RUNNER")
    vector_path = Path(sys.argv[1])
    runner_path = Path(sys.argv[2])
    if not vector_path.is_file():
        fail("missing vector file: %s" % vector_path)

    document = json.loads(vector_path.read_text(encoding="utf-8"))
    if document.get("schemaVersion") != "dsp-conformance-v1":
        fail("unsupported vector schema")
    vector = document.get("q15Fft")
    if not isinstance(vector, dict) or vector.get("size") != 256:
        fail("expected a 256-point q15Fft vector")
    vector_input = vector.get("input")
    if not isinstance(vector_input, dict) or vector_input.get("kind") != "impulse":
        fail("expected an impulse q15Fft input")

    result = subprocess.run(
        [
            str(runner_path),
            str(vector_input.get("realAmplitude")),
            str(vector_input.get("index")),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    actual = []
    for line_number, line in enumerate(result.stdout.splitlines(), start=1):
        fields = line.split()
        if len(fields) != 2:
            fail("malformed runner output at line %d" % line_number)
        actual.append((int(fields[0]), int(fields[1])))

    expected = list(zip(vector.get("expectedReal", []), vector.get("expectedImaginary", [])))
    if actual != expected:
        for index, (actual_value, expected_value) in enumerate(zip(actual, expected)):
            if actual_value != expected_value:
                fail(
                    "Q15 FFT mismatch at bin %d: got %r, expected %r"
                    % (index, actual_value, expected_value)
                )
        fail("Q15 FFT output length mismatch")
    print("Atom-DSP Q15 FFT conformance: passed")


if __name__ == "__main__":
    main()
