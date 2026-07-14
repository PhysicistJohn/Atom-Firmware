# Physical official-versus-candidate self-test capture

`tools/capture-physical-selftests.py` records the physical counterpart of the
fourteen-case Renode visual gate. It has no flashing or DFU support. Run it
once with the official `c979386` image and once with the exact RC5 image, with a
human-controlled flash and cold boot between runs.

## Safety and setup

- Close serial terminals and Atomizer before starting. The runner exclusively
  opens one `0483:5740` USB CDC interface and follows the same USB serial number
  if macOS assigns a new `/dev/cu.usbmodem*` path.
- Connect only a short 50-ohm cable from CAL to RF. Do not connect an antenna.
- Start each run immediately after a cold boot, with no unsaved RAM-only setup
  that needs to survive the built-in factory self-test.
- The runner never flashes, resets, saves, clears, or writes calibration or
  configuration. The factory self-test itself restores the persisted device
  configuration when each retained result is acknowledged. Its normal
  RAM-only working sweep state is not promised to survive; a cold boot restores
  persisted settings. Read-only snapshots of all twelve correction tables and
  the color palette must be byte-identical before and after the run.
- The `--expected-version` check prevents collecting a baseline under the
  candidate label or vice versa. Use the complete version text observed from
  that exact image.

The serial package is already cached in the hardware-test environment. On this
workstation its original virtual-environment interpreter symlink is stale, so
use the user-local Python 3.12 executable with that environment's site-packages:

```sh
export TINYSA_HW_PYTHON=/Users/johnelliott/.local/bin/python3.12
export PYTHONPATH="$PWD/.artifacts/toolchains/tinysa-hardware-venv/lib/python3.12/site-packages"
"$TINYSA_HW_PYTHON" -c 'import serial; assert serial.VERSION == "3.5"'
```

On another checkout, recreate a normal virtual environment from
`tools/requirements-hardware-test.txt` and substitute its Python executable.

## Capture the A/B pair

After flashing and cold-booting the official image:

```sh
"$TINYSA_HW_PYTHON" \
  tools/capture-physical-selftests.py \
  --variant official-c979 \
  --expected-version tinySA4_v1.4-224-gc979386 \
  --output .artifacts/hardware-selftest/official-c979 \
  --port auto \
  --confirm CAL-RF-LOOPBACK-CONNECTED
```

Then flash the exact RC5 binary, perform a true power-off cold boot, and run:

```sh
"$TINYSA_HW_PYTHON" \
  tools/capture-physical-selftests.py \
  --variant rc5 \
  --expected-version tinySA4_v0.4-chibios21-rc5 \
  --output .artifacts/hardware-selftest/rc5 \
  --port auto \
  --confirm CAL-RF-LOOPBACK-CONNECTED
```

The release filename contains the full ChibiOS tag
(`tinySA4_v0.4-chibios21.11.5-rc5.bin`), while the firmware's intentionally
shorter shell identity is `tinySA4_v0.4-chibios21-rc5`. The runner checks the
shell identity, not the artifact filename.

The default case set is zero-based `0-13`. Each command actually sent to the
firmware is `selftest 0 N`, where positive argument `N=1..14` retains one real
result screen. The runner waits a fixed 30 seconds without polling the active
self-test, then reads the complete 307,200-byte LCD twice at least 0.75 seconds
apart. A late redraw gets up to two additional fixed-settlement attempts. No
case passes unless one pair is byte-identical and the screen is populated.

For each retained case the runner saves:

- both authoritative big-endian panel readbacks and their SHA-256 hashes;
- `case-XX.rgb565`, byte-swapped to the little-endian Renode comparator format;
- a deterministic truecolor `case-XX.png`;
- `frequencies`, trace configuration, all four `trace N value` planes, all
  three `data N` views, `sweeptime`, `status`, and `threads` responses;
- a 7,200-byte `case-XX-measured.f32le` matrix derived from the four shell trace
  planes (values have the shell's 0.01-unit precision, unlike direct SRAM twin
  dumps);
- structured metrics, complete transcript, port history, and `SHA256SUMS`.
- before/after correction-table and palette responses proving that the
  persisted calibration/config view did not change.

Cases whose factory response is expected to have vertical structure are also
rejected if the measured trace collapses below 0.10 dB range. Cases 9, 12, and
13 intentionally can be horizontal, so their quality must be judged against
the paired official capture rather than an invented non-flat requirement.

The output directory must be new and empty. If a transport or evidence check
fails, the runner attempts the normal touch/release cleanup, seals the partial
evidence, and stops. Re-run failed or remaining cases into a new directory with
`--cases`, for example `--cases 7-13`; do not mix files from separate boots
without recording that provenance.

## Compare the completed captures

The physical report adapter first authenticates both complete `SHA256SUMS`
inventories and rechecks the selected pair of identical readbacks for every
case. It then compares populated frames, frequency grids, all four shell trace
planes, peaks, structured-trace shape, and measured sweep time. Exact frame or
trace identity is reported when observed but is not assumed: bounded physical
noise is evaluated with explicit directional and similarity thresholds. This
report is labeled as physical evidence and remains separate from the Renode
release gate.

```sh
"$TINYSA_HW_PYTHON" tools/compare-physical-selftest-captures.py \
  --reference .artifacts/hardware-selftest/official-c979 \
  --candidate .artifacts/hardware-selftest/rc5 \
  --output .artifacts/hardware-selftest/official-c979-vs-rc5
```

The output contains `report.json`, `report.md`, fourteen false-color diff
images, two official/RC5/diff contact sheets, and its own checksum inventory.
The report records every threshold and failed check. In particular, cases with
known structured responses must retain peak position, at least 95% trace
correlation, and at most 2 dB pointwise RMSE; noise/suppression cases use
directional peak and range comparisons instead of pretending their samples
must align point for point.

Run the hardware-free helper checks at any time:

```sh
"$TINYSA_HW_PYTHON" tools/test-physical-selftest-capture.py
"$TINYSA_HW_PYTHON" -m py_compile tools/capture-physical-selftests.py
"$TINYSA_HW_PYTHON" -m py_compile tools/compare-physical-selftest-captures.py
```
