## Problem

The shell accepts a 47-byte line, while the F303 keypad buffer is 28 bytes.
`text` copied its argument byte-by-byte until NUL without checking the
destination size, so a legal remote command could overwrite adjacent UI state.

## Change

Move keypad-buffer ownership into the UI module and copy through the firmware's
existing size-aware `plot_printf` helper. The destination is always terminated
and valid short input is unchanged.

## Verification

- Arm GNU 11.3.Rel1 F072 and F303 builds pass.
- Both target images reproduce byte-for-byte on a second clean build.
- GCC `-fanalyzer` reports no analyzer diagnostic.
- The exact F303 image boots in the ZS407 Renode model with unchanged RF-device
  initialization counts.
- The exact F303 image was flashed to a physical tinySA Ultra+ ZS407 (hardware
  V0.5.4, MAX2871), and its embedded version was verified before testing.
- A legal 46-byte `text` command exercised the maximum shell-line boundary; the
  device remained responsive and reported the exact version afterward.
- The test restored both captured sweep endpoints, verified the complete
  450-point grid, and the built-in CAL-to-RF self-test passed afterward.

The hardware test opens the ordinary center-frequency keypad, sends a 46-byte
command line, proves subsequent UI/shell operation, and restores both captured
sweep endpoints without saving configuration.
