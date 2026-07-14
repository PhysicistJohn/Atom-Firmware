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

## 2026-07-14 warm staging diagnostic (non-qualifying)

The exact official rollback binary was staged first:

| Fact | Observed value |
| --- | --- |
| Rollback file | `ROLLBACK_OFFICIAL_tinySA4_v1.4-224-gc979386.bin` |
| Rollback SHA-256 | `3c9847ff4d7b80561df2f2f1030a112703a083409ffb2ee11361b2413b7c1e41` |
| Shell identity | `tinySA4_v1.4-224-gc979386` |
| Hardware identity | `tinySA ULTRA+ ZS407`; `HW Version:V0.5.4 max2871` |
| Warm USB enumeration | `0483:5740`, serial `400`, location `0-1`, `/dev/cu.usbmodem4001` |

The rollback file is the copy inside the exact RC5 package at
`.artifacts/worktrees/chibios-rc5/.artifacts/chibios-releases/`
`v0.4-chibios21.11.5-rc5/6fdf6f307ecb0cef2e3af478b0fc7b80a1fd13e2/`.

After DFU's manifest/leave warm reboot, the read-only diagnostic under
`.artifacts/hardware-selftest/official-c979-warm-diagnostic2-20260714/`
completed all fourteen cases. Every case passed on its first settlement
attempt with two identical 307,200-byte panel frames read 0.75 seconds apart.
The palette and all twelve correction-table responses were byte-identical
before and after the run. Its checksum inventory has SHA-256
`193fd7cde4c52ffe3a3db0a3fe4bab3cd0f7f26766f1d51634adf81a34f34f5d`;
`run.json` has SHA-256
`0c64beed218131af116ced9b7e68a1257dc90567fcbf58251e20523a8927a6e6`.

The validator was then intentionally run with that capture as both reference
and candidate. The resulting tool self-check under
`.artifacts/hardware-selftest/official-c979-warm-self-check2-20260714/`
passed all fourteen cases, all 285 source-inventory entries, persisted-config
integrity, exact frames and traces, and sweep-time parsing. Its `report.json`
has SHA-256
`dc975a06fe9631f43d19d19c694cf9b8c7cc8d09d38e95ceb0b08323a7067c8a`.
This proves the captured evidence passes the comparison tooling; because the
same capture occupies both sides, it is not an official-versus-RC5 result.

Human review of both contact sheets confirmed populated screens and genuine
RF response shapes rather than blank or substituted flat lines. Cases 12 and
13 retain their intentionally horizontal response portions. The contact-sheet
SHA-256 values are
`9d5e14dea93489dc7b8f03073c4d88d6a58cd920a4c29de3c36e521cba702356`
for cases 1-7 and
`f39d5798c3a48cb446a0e284bb23d9cf7ad9c1dfe56b45f5a810e562593f6898`
for cases 8-14.

Two capture-tool defects were exposed and fixed without changing either
firmware image. Untouched official case 3 emitted the legacy `etoa()` token
`-:.000000e+01` for `-100.00`; commit
`d7dad37801c10e37fe4704489b7cdafd19cce1c9` decodes only that narrowly defined
power-of-ten defect and cross-checks it against the independently formatted
trace. Commit `0fdab812c55cb1f5bd7cd0be21b37806547eeffb`
adds correct `ms` as well as `s` sweep-time parsing. The separate upstream
formatter correction is documented in
[Vendor upstream queue](VENDOR_UPSTREAM_QUEUE.md#new-tinysa-findings-from-port-qualification).

This run is explicitly **not qualifying evidence**: the unit had no true cold
boot after the official flash. The next physical action is to switch the unit
off for at least five seconds, switch it on, and capture a new cold official
baseline. After that completes, enter TINYSA4 DFU manually, flash the exact
RC5 binary, perform the same cold boot, and capture RC5. Official TINYSA4 has
no compiled DFU shell argument or DFU menu, so automation must not claim it
can make that transition.

## 2026-07-14 official IF-discrimination survey (non-qualifying)

The official firmware was also measured in three controlled receiver
configurations to distinguish coherent internal responses from random noise
maxima and real CAL-path products. Each row is the average of two fresh
450-point scans using the connected CAL-to-RF loopback:

- `base`: `spur off`, `avoid off`;
- `alternate`: `spur off`, `avoid on`;
- `dual`: `spur on`, `avoid off`, which measures both paths and retains the
  lower RSSI at each point.

| Scene | Base SFDR | Alternate SFDR | Dual SFDR | Interpretation |
| --- | ---: | ---: | ---: | --- |
| 30 MHz, 1 MHz span, LNA off (case-3-like) | 60.78 dB | 58.50 dB | 65.00 dB | Noise-limited secondary maxima moved between repeats; dual acquisition lowered the visible maximum by about 4 dB. |
| 30 MHz, 5 MHz span, LNA on (case-14-like) | 42.00 dB | 43.78 dB | 55.28 dB | Coherent responses repeated at the same bins for each single-IF path; dual acquisition suppressed the worst response by about 13 dB while the wanted carrier changed by 0.50 dB. |
| 30 MHz, 7 MHz span, 32 dB attenuation (case-11-like) | 31.03 dB | 31.75 dB | 33.50 dB | The strongest out-of-lobe bin moved by megahertz between repeats, identifying a noise maximum rather than a stable spur. |
| 915 MHz, 5 MHz span, 15 MHz CAL and LNA on (case-10-like) | 24.50 dB | 24.00 dB | 24.25 dB | The approximately -468.75 kHz companion remained repeatable under both IF choices; it is consistent with a real CAL/harmonic-path product, not a one-path image that the minimum detector can remove. |

The raw, hash-bound records are:

- `.artifacts/diagnostics/official-c979-spur-if-ab-run2-20260714/run.json`,
  SHA-256
  `8fb296862e8064a7a72c0afa2d81b56f65f89d967971685e4817a04fcb764e8b`;
- `.artifacts/diagnostics/official-c979-switch-spur-if-ab-20260714/run.json`,
  SHA-256
  `e08fec5b0dc3524ac093ef44d9789c863652f403349c4293f06ba46581f78aa8`;
- `.artifacts/diagnostics/official-c979-915m-spur-if-ab-20260714/run.json`,
  SHA-256
  `54e708b748b61485d9b971c7ca818dbbf1cbccd9cf1c76c26e6cc4b8b26be811`.

Every survey ended by disabling CAL output, warm-resetting untouched official
firmware, re-authenticating `tinySA4_v1.4-224-gc979386`, and verifying that
the initial resumed 0--900 MHz sweep and automatic 850 kHz RBW were restored.
These measurements characterize the official receiver only; they do not
qualify RC5 and do not justify making factory self-tests cosmetically cleaner.

The lowest-risk later-firmware improvement is selective dual-IF confirmation:
in normal low-input `AUTO`, perform the second acquisition only for frequencies
already classified `F_AT_SPUR` by `avoid_spur()`. Keep full two-pass behavior
for explicit `ON` and Ultra `AUTO_ON`, and exclude self-test, direct, tracking,
and zero-span paths until each has its own timing and RF qualification. This
uses the existing frequency/IF-aware tables rather than a peak heuristic, so a
real narrow signal that persists under both IF choices remains visible.

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
