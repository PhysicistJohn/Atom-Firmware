# Self-test visual regression

`tools/test-selftest-visual-regression.sh` qualifies a relocatable firmware
candidate against the pinned v0.2.0 executable twin. It drives both images
through the same fourteen built-in self-test cases and the same deterministic
CAL-to-RF fixture profile.

The runner launches each case with the firmware's positive, interactive test
argument. It requires `PASS`, `test_wait`, `SWEEP_SELFTEST`, the requested
positive argument and the matching RF fixture while the result is retained.
It also requires the fixture-appropriate `in_selftest` state: asserted for
active cases and intentionally cleared by firmware for silent cases 1, 2 and 5
so spurs remain visible. The runner captures that result screen, acknowledges
it with the modeled touch panel and requires clean restoration before launching
the next case. This is important: the negative/no-wait test argument restores
normal sweeping before a caller can capture the tested trace.

The gate does not accept a firmware `PASS` status by itself. While each result
screen is retained it captures:

- a 480x320 PNG for direct visual review;
- the exact 307,200-byte RGB565 LCD framebuffer;
- firmware peak level, peak position, 15 dB width and modeled RF statistics;
- expanded measured-trace range/statistics when supplied by the symbol profile.

The comparator first tests for exact framebuffer identity. If a candidate is
not pixel-identical, it requires behavioral equivalence: a populated display,
primary-trace coverage comparable to the reference, sufficient vertical trace
structure, high content similarity, trace-column overlap and bounded trace
shape error. Numeric peak and width checks are directional where appropriate:
lower is better for suppression/noise cases, while signal cases must remain
close to the reference. A blank frame or a reference-shaped trace collapsed to
a flat line therefore fails even when the firmware's internal self-test status
is `PASS`.

Run the gate with the release candidate and its SRAM symbol profile:

```sh
tools/test-selftest-visual-regression.sh \
  --candidate-bin /absolute/path/to/tinySA4-candidate.bin \
  --candidate-elf /absolute/path/to/tinySA4-candidate.elf \
  --candidate-symbols /absolute/path/to/candidate-symbols.resc
```

Results are written below `.artifacts/digital-twin/selftest-visual/`:

- `reference/` and `candidate/` contain the fourteen PNG/raw-frame pairs and
  Renode logs;
- `comparison/report.json` is the machine-readable gate result;
- `comparison/report.md` is a compact evidence table;
- `comparison/index.html` places original, candidate and false-color diff
  images side by side for every test.
- `comparison/contact-cases-01-07.png` and `contact-cases-08-14.png` provide
  compact triplet sheets for review.
- `SHA256SUMS` authenticates every captured frame and comparison artifact.

The raw-frame comparison is intentionally independent of the PNG encoder. In a
false-color diff, reference-only pixels are red, candidate-only pixels are cyan
and identical pixels are dim gray.
