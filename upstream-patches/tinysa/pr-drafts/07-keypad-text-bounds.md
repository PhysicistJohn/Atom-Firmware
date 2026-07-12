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
- Physical ZS407 maximum-line transcript: **pending the prepared four-image
  batch**.

The hardware test opens the ordinary center-frequency keypad, sends a 46-byte
command line, proves subsequent UI/shell operation, and restores the original
frequency grid without saving configuration.
