# Upstream firmware hardware qualification results

Qualification completed on 2026-07-11 PDT / 2026-07-12 UTC using a physical
tinySA Ultra+ ZS407 reporting hardware V0.5.4, MAX2871 and an STM32F303
Cortex-M4F. RF output was disabled before every scripted exchange. A short
50-ohm cable connected CAL to RF only for the manual built-in self-tests.

## Result matrix

| Package | Exact embedded version | Targeted USB test | Built-in self-test |
| --- | --- | --- | --- |
| 4 — scan counts | `tinySA4_pr4-scan-g1d518af` | PASS | PASS |
| 5 — correction bounds | `tinySA4_pr5-correction-g6cba8a9` | PASS | PASS |
| 6 — shell indices | `tinySA4_pr6-indices-g5a029f9` | PASS | PASS |
| 7 — keypad text | `tinySA4_pr7-text-g89e5d11` | PASS | PASS |
| Restored enhanced firmware | `tinySA4_hw-v0.3-fft1024-g43eb0f1` | Identity and health PASS | PASS |

Every flash used DFU alternate 0 (internal flash) only. `dfu-util` reported
`File downloaded successfully` and completed the manifest/leave transition for
all five images. Option bytes were never selected.

## Package evidence

### Package 4 — scan counts

- Verified the exact candidate identity before issuing test commands.
- Accepted legacy point count 2, valid 2-point `scan`, and valid 1-point
  `scanraw` with the expected five-byte `{x..}` frame.
- Rejected legacy counts 1, 0, -1 and 2147483648.
- Rejected `scan` counts 1, 0, -1 and 451.
- Rejected `scanraw` counts 0, -1 and 4294967296.
- Restored the original legacy point count of 101 and confirmed liveness.

### Package 5 — correction bounds

- Captured all 20 `correction low` rows before testing.
- Exercised missing and unknown table forms, invalid reset forms, slot -1 and
  slot 20.
- Captured all 20 rows again and proved they were byte-for-byte unchanged.
- Never issued a valid correction mutation, correction reset or save command.

### Package 6 — shell indices

- Rejected trace copy/subtract indices 0 and 5 and sample indices -1 and 65535.
- Rejected marker delta reference 9 and marker-trace indices 0 and 5.
- Safely ignored palette indices -1 and 32; all 32 palette entries were
  identical before and after.
- Safely returned from menu paths -1 and 9999 and confirmed final liveness.

### Package 7 — keypad text

- Opened the ordinary CENTER keypad path and submitted a legal 46-byte shell
  line, longer than the keypad destination buffer.
- Confirmed the exact firmware version immediately afterward.
- Restored captured START and STOP endpoints in a `finally` block and compared
  every frequency-grid value before and after.
- Explicitly reconstructed the pre-test 0–900 MHz sweep and verified all 450
  generated frequencies against the firmware's integer interpolation formula.

The machine-generated Markdown transcripts remain under
`.artifacts/upstream-staging/hardware/` as `pr4.md` through `pr7.md`,
`pr7-grid-recovery.md`, and `enhanced-v0.3-restore.md`.

## Hardware findings from the live run

1. The ZS407/TINYSA4 build has eight markers (`MARKER_COUNT == 8`). A first
   private harness vector inherited the smaller model's four-marker assumption
   and incorrectly used marker 5 as an invalid value. Marker 5 was accepted as
   designed. The corrected boundary is user-facing marker 9, and the host fake
   now models all eight valid markers.
2. Setting an extreme CENTER frequency can clamp the center and shrink the
   existing span in `set_sweep_frequency(ST_CENTER, ...)`. Restoring only the
   prior center is therefore insufficient. The corrected harness restores both
   START and STOP in a `finally` block, and its host fake deliberately collapses
   the span to prove recovery.
3. The restart method used during the run retained the temporary zero-span
   sweep. The process now avoids relying on restart semantics: it explicitly
   restores endpoints and verifies the full grid before declaring success.
4. The STM32 ROM DFU endpoint repeatedly began in `dfuERROR` status 10 after a
   firmware transition. `dfu-util` cleared that status to `dfuIDLE`, erased and
   downloaded the complete image, and reported successful manifest/leave each
   time. No retry or second flash was needed.

These findings changed only the private qualification tooling and runbook. The
four proposed upstream firmware commits remained byte-for-byte unchanged from
the images tested on hardware.

## Final restoration

The exact enhanced image at source commit
`43eb0f193c8619cb7ca23726e3062973c65ae958` was restored from the previously
qualified binary:

- size: 208,484 bytes;
- SHA-256: `6f284a24c4b4ab178da13af97e102e1a624618c9a67e8418b19bbc153e6f0174`;
- embedded version: `tinySA4_hw-v0.3-fft1024-g43eb0f1`;
- final battery reading: 4222 mV;
- final built-in self-test: PASS.
