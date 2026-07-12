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
- The exact F303 image was flashed to a physical tinySA Ultra+ ZS407 (hardware
  V0.5.4, MAX2871), and its embedded version was verified before testing.
- Hardware checks captured all 20 low correction rows, exercised missing,
  unknown, special-token, negative and index-20 mutation forms, and proved all
  20 rows were byte-for-byte unchanged afterward.
- The complete built-in CAL-to-RF self-test passed after the candidate run.

The physical procedure only reads the valid correction table and proves invalid
commands leave it unchanged; it never resets or writes calibration data.
