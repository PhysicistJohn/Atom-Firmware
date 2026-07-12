## Problem

`correction` used the table-name lookup result and user-provided slot directly
as array indices. A missing or unknown table name, a special `off`/`on` token in
a mutation form, or a negative/overlong slot could access outside the
correction arrays.

## Change

Require an argument before lookup, restrict mutation/reset forms to the actual
correction tables, and validate the slot against `CORRECTION_POINTS` before
either array write. The existing F303 one-argument `off` and `on` forms remain
unchanged.

## Verification

- Arm GNU 11.3.Rel1 F072 and F303 builds pass.
- Both target images reproduce byte-for-byte on a second clean build.
- GCC `-fanalyzer` reports no analyzer diagnostic.
- The exact F303 image boots in the ZS407 Renode model with unchanged RF-device
  initialization counts.
- Physical ZS407 transcript: **pending the prepared four-image batch**.

The physical procedure only reads the valid correction table and proves invalid
commands leave it unchanged; it never resets or writes calibration data.
