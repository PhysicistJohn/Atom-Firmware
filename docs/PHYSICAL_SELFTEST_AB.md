# Physical official-versus-candidate self-test capture

`tools/capture-physical-selftests.py` records the physical counterpart of the
fourteen-case Renode visual gate. It has no flashing or DFU support. Run it
once with the official `c979386` image and once with the exact RC5 image, with a
human-controlled Atom-Flasher installation and cold boot between runs. The
record below predates the standalone boundary and is archival: the legacy RC5
raw image is not currently manifest-admissible, so do not repeat the pair until
it has a reviewed manifest migration or is rebuilt as a manifested target.

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

The serial package is already cached in the hardware-test environment. To keep
the workflow independent of Xcode's bundled Python, use the standalone local
Python 3.12 interpreter with the cached pyserial site-packages:

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

This warm run remains explicitly **non-qualifying evidence**. It was superseded
by cold official and RC5 all-fourteen captures whose inventories are
`28b7ed7bc5f4214da8cbba7fc21340ef4b534437b3f66c7598f673ef0d0d2890`
and `1cebd9368c0f7ccc2198fcbe1bbb59fb61a467c65f21045256695cfe8fa1a14c`.
The cold-boot-attested v3 A/B report under
`.artifacts/hardware-selftest/official-c979-vs-rc5-20260714-v3/` is eligible
and passes all fourteen cases; its report and inventory hashes are
`2f58569f30981c0076696680f256bd0788f587d2be0a22738167aff9993460ce`
and `6f420450e023f98fc423ad62d5a9e256c541044f28c128be9358a84826022321`.
These historical captures authenticate exact reported firmware versions, not
a DFU read-back of every captured image. Official TINYSA4 has no compiled DFU
shell argument or DFU menu, so automation must not claim it can make that
transition.

## 2026-07-14 exact DFU readback and post-readback RC5 follow-up

The packaged 193,980-byte RC5 image with SHA-256
`1e3f45a9744b18985622d5abf6c2445524a4ad53a831316766c37de80ac96685`
was subsequently downloaded through DFU alt 0 and read back byte-for-byte over
the same 193,980-byte range. The live device exposes exactly
`@Internal Flash  /0x08000000/128*0002Kg` and
`@Option Bytes  /0x1FFFF800/01*016 e`; the double spaces are significant and
the flash tool rejects the earlier normalized or 1 MiB assumptions. The flash
inventory and run hashes are
`b96880fb1c5a5ce3eaac93e34bc24a994aa3ed41e358346f06b1f57b10573301`
and
`0657dd6f5e541eeeb7900c5ee42aa89ddb6f5d0efa4a1eb2e7552607d9d86565`.
No option-byte write was attempted.

Fresh records linked to that exact readback passed normal USB enumeration,
six distinct complete 307,200-byte frame transfers, `data 2`/`trace 1`
mapping, resumed acquisition, one real reset/re-enumeration, and persisted
configuration integrity. Their inventory hashes are
`508e94e28c768a6281801d2123769cff4076ea75332452dc56ba1aa6a2b005ee`
for USB and
`dd88b441a17c147b5ed4d64c19b933aa23448d24a62bb1b055fc8d64d07b6490`
for reset retention.

After an operator-attested power-off interval of at least five seconds, the
fresh post-readback all-fourteen capture under
`.artifacts/hardware-selftest/rc5-readback-final-20260714/` passed every case
on its first stable framebuffer pair and preserved all thirteen persisted
configuration observations. Its inventory and `run.json` hashes are
`488cd1f908bc7aff655b5ef43e325ed542bd9cdc66c0d0ca5e2eba2a84aca156`
and
`72a472e23a79a4f01fe6c0467c13f6eac220e7307889b6ae2e14c44d12a4d6dd`.
The post-readback cold-boot attestation is
[`release-manifests/v0.4-rc5-readback-cold-boot-attestation.json`](../release-manifests/v0.4-rc5-readback-cold-boot-attestation.json).
That capture is bound to its exact version, USB identity, checksum inventory,
and operator-attested chronology. The self-test runner and v4 comparator did
not validate the flash inventory/run hashes, so the all-fourteen capture and
v4 A/B are not described as exact-byte-bound.

The fresh official-versus-post-readback comparison is deliberately preserved as a
failed report under
`.artifacts/hardware-selftest/official-c979-vs-rc5-readback-20260714-v4/`.
Its inventory and `report.json` hashes are
`e90dffaff79fc2990d6834790a510f517ea4a39c022b22c9a72b696fa6fe3022`
and
`a93187eb1304f16eadb61fe6f9d16e80a3b2e92902c04183d695248d6e3b4ae8`.
The report remains qualification-eligible with `qualification_pass=false` and
no diagnostic exclusion. Thirteen cases passed every gate. Case 2 alone
exceeded the predeclared suppression threshold in its first cold sweep: its
top-five peak median was -48.91 dBm versus -53.41 dBm for official, where the
limit is official plus 2.0 dB. No threshold was changed and the report was not
regenerated to erase that observation.

Three targeted repeats then isolated that result:

| Observation | Boot context | Top-five median | Q95 | Peak bin | Declared threshold |
| --- | --- | ---: | ---: | ---: | --- |
| Official `c979386` | cold | -53.41 dBm | -64.13 dBm | 287 | reference |
| Post-readback RC5 all-14 | first cold | -48.91 dBm | -64.79 dBm | 288 | fail |
| Post-readback RC5 repeat 2 | warm | -52.81 dBm | -63.95 dBm | 287 | pass |
| Post-readback RC5 repeat 3 | warm | -60.31 dBm | -65.15 dBm | 287 | pass |
| Post-readback RC5 repeat 4 | second cold | -52.81 dBm | -63.77 dBm | 287 | pass |

The four post-readback candidate observations have a median top-five result
of -52.81 dBm, 0.60 dB above official and inside the original 2.0 dB limit.
The second cold result also differs from official by only 0.60 dB. Q95 stays
within a 1.38 dB band while the narrow response amplitude varies, so the first
cold threshold excursion did not reproduce as a cold-start dependency.
Screenshots for official, the failed first-cold observation, and the second
cold repeat are all populated, retain the green `Test 2: Pass` result, and
show the same shaped narrow response near bin 287 rather than a blank or flat
substitution. This is repeatability evidence, not a physical-source or
long-term-stability attribution. The sealed measurements and the operator
power-cycle statement are recorded in
[`release-manifests/v0.4-rc5-case2-repeat-attestation.json`](../release-manifests/v0.4-rc5-case2-repeat-attestation.json).
That attestation's SHA-256 is
`225c8a39f0ffbcd2ae4e5afce52043a5faa695a73176a26f67cd7d243ed9ee71`.

A separate three-sweep persistence analysis is `DIAGNOSTIC_COMPLETE` with
`release_gate=false`. Cases 3 and 4 are stochastic/nonpersistent in both
firmware groups, and case 11 has no significant secondary peak in either.
Case 10 has ten persistent clusters, all ten shared; case 14 has eight
candidate clusters, all eight shared, plus one reference-only cluster. There
are zero candidate-only persistent clusters across all five eligible cases.
This establishes only short-run frequency recurrence: it neither attributes
harmonics or a physical source nor closes the A/B report's pending SFDR field.
The analyzer inventory and report hashes are
`b3aa84e71cc96ad8b2416bf3eab2c886304d36a869fa695c65b1d05c60c9377c`
and
`0c95fc39737db7992026a6d2dba6ba4da81474e2ec68286c20bb41d8ecea04b7`.

The earlier scoped physical handoff at
`.artifacts/physical-qualification/v0.4-chibios21.11.5-rc5/` independently
authenticates all 26 inventoried members; its `SHA256SUMS` seal is
`6bf2459d03627399da9c6b7f005eebd56dd01e637e8b46a4a69a7811afc06e2c`.
It predates the post-readback final all-fourteen capture, the fresh v4 A/B,
the case-2 repeats, and the spur-persistence report, and is intentionally not
mutated to imply otherwise. The production packager is now fail-closed so it
cannot regenerate that older fault-injection-only status while ignoring v4.
The existing bundle remains correctly labeled
`physical-runtime-pass_fault-injection-pending`, with
`hardware_qualified=false`; physical PSP-origin and nested-MSP forced-fault
testing is an unexecuted mandatory gate. Overall qualification also retains
the v4 case-2 failure: the three supplemental passes establish
non-reproduction but do not mutate or waive that sealed failed report.
The current machine-readable disposition is
[`release-manifests/v0.4-rc5-physical-qualification-status.json`](../release-manifests/v0.4-rc5-physical-qualification-status.json),
SHA-256
`2e3fd347053dcf9536611513882d535efc1f3f78d684f1119bef651bd9c0a11f`.

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

Historically, the exact RC5 binary was installed next. For any repeat, use only
standalone Atom-Flasher after the exact candidate has a reviewed manifest;
then perform a true power-off cold boot and run:

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
case. It then proves the exact green `Test N: Pass` firmware-font literal from
the observed palette, requires at least 400 active columns across the complete
450-column plot, checks frequency grids and all four shell trace planes, and
compares RF levels, robust shape and measured sweep time. Cases 12 and 13 must
render time-grid columns consistent with their own measured sweep time; exact
legacy self-comparison remains allowed. This report is labeled as physical
evidence and remains separate from the Renode release gate.

```sh
"$TINYSA_HW_PYTHON" tools/compare-physical-selftest-captures.py \
  --reference .artifacts/hardware-selftest/official-c979 \
  --candidate .artifacts/hardware-selftest/rc5 \
  --cold-boot-attestation release-manifests/v0.4-rc5-cold-boot-attestation.json \
  --output .artifacts/hardware-selftest/official-c979-vs-rc5-20260714-v3
```

The v3 output contains `report.json`, `report.md`, fourteen false-color diff
images, two official/RC5/diff contact sheets, the copied operator cold-boot
attestation, snapshots of all comparison implementations, and its own checksum
inventory.
The report records every threshold and failed check. Raw framebuffer content
similarity and raw pointwise trace RMSE remain diagnostics: independent RF
noise makes them unsuitable release gates. Structured cases instead compare a
nine-bin envelope after at most three bins of alignment and removal of the
reported median level offset. They require correlation at least `0.94` and
aligned RMSE at most `2.0 dB`; absolute peak and frequency checks remain
separate, so this does not hide gain or tuning regressions. Trace range uses
`Q99-Q01` rather than allowing one startup/noise bin to define both extrema.

Those physical thresholds were calibrated with the same-RC5 case-3 retained
capture and post-reconnect recovery repeat. The raw pair had `2.605 dB` RMSE;
the nine-bin aligned result had `1.034 dB` RMSE and `0.9949` correlation. That
repeat is diagnostic threshold calibration only, not official-versus-RC5
qualification evidence. Similarly, a single sweep's strongest out-of-lobe bin
is reported but never called a persistent spur or used as an SFDR release gate.
At least three independent sweeps with a frequency-persistence rule are needed
before the five eligible single-carrier cases can gain such a gate.

Run the hardware-free helper checks at any time:

```sh
"$TINYSA_HW_PYTHON" tools/test-physical-selftest-capture.py
"$TINYSA_HW_PYTHON" -m py_compile tools/capture-physical-selftests.py
"$TINYSA_HW_PYTHON" -m py_compile tools/compare-physical-selftest-captures.py
```
