## Problem

`chprintf.c::etoa()` normalizes values with `while (num > 10)` and then emits
the integer mantissa as one character.  An exact normalized mantissa of 10 is
therefore emitted as ASCII `':'`, not a decimal digit.  For example, the
official `c979386` firmware renders `-100.0` as `-:.000000e+01` from the
`data` shell command.

This is a formatter defect, not lost USB data.  During a physical warm-start
diagnostic on a ZS407, self-test case 3 returned all 450 rows for both `data 0`
and `data 2`.  Both responses contained the same malformed token at point 238,
and the independently formatted mapped traces reported `-100.00` at that
point.

## Change

Continue upper normalization while `num >= 10`.  The one-line change makes
the mantissa range match the single leading digit that follows, so `-100.0`
becomes `-1.000000e+02`.

No shell command, measurement value, storage format, RF path, or RTOS behavior
changes.

## Verification

- The standalone reproducer demonstrates the `':'` output with the original
  condition and passes with the proposed condition.
- Positive and negative exact powers `1`, `10`, `100`, and `1000` render with
  the expected mantissa and exponent.
- The immediately adjacent `nextafterf()` values on both sides of every tested
  positive and negative power remain valid numeric scientific notation and
  round-trip within the formatter's six-digit precision.
- The mailbox patch applies cleanly to upstream
  `c97938697b6c7485e7cab50bca9af76996b7d671`.

The physical observation used the untouched official firmware.  The local
v0.4 RC5 image remains byte-for-byte sealed with SHA-256
`1e3f45a9744b18985622d5abf6c2445524a4ad53a831316766c37de80ac96685`;
this formatter fix is not included in it and no RC5 physical pass is claimed
by this handoff.

## Suggested maintainer tests

Keep a host unit test for `%e` that covers:

- positive and negative exact powers across the supported exponent range;
- `nextafterf(power, 0)` and `nextafterf(power, +INFINITY)`, with sign mirrored;
- zero and ordinary non-power values; and
- the existing explicit/default precision forms.

