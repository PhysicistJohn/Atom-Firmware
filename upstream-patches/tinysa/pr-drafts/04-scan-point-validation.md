## Problem

The `scan` path builds a frequency table using `points - 1`, but it accepted a
one-point request. The legacy `s` command also accepted zero, one, negative and
out-of-range values. `scanraw` divides by its requested point count and accepted
non-positive values before converting them to its unsigned loop bound.

## Change

Reject invalid counts before conversion or division:

- `scan`: 2 through the firmware's normal `POINTS_COUNT` limit;
- legacy `s`: 2 through `INT32_MAX`;
- `scanraw`: positive parsed values that fit its `uint32_t` loop counter.

The different `scanraw` lower bound is intentional: it divides by `points`, not
`points - 1`, and its documented raw interface supports arbitrary positive
counts.

## Verification

- Arm GNU 11.3.Rel1 F072 and F303 builds pass.
- Both target images reproduce byte-for-byte on a second clean build.
- GCC `-fanalyzer` reports no analyzer diagnostic.
- The exact F303 image boots in the ZS407 Renode model with unchanged RF-device
  initialization counts.
- Physical ZS407 transcript: **pending the prepared four-image batch**.

No valid scan format, RF setting, storage layout or persistent configuration is
changed.
