# PR draft: stm32: preserve EP0 PMA across reconfiguration

## What this changes

When the STM32 PMA USB low-level driver disables configuration endpoints, reset
the allocator and immediately reserve the still-active EP0 IN/OUT buffers.
Reinitialized endpoints 1..N then receive non-overlapping PMA addresses.

The full bus-reset path remains unchanged: it resets the allocator completely
and initializes EP0 from a clean state.

## Why

The endpoint-disable API explicitly preserves endpoint zero. Resetting the PMA
cursor without reserving EP0 violates that ownership rule. A repeated
`SET_CONFIGURATION` can assign EP1's buffers to the same addresses still used
by EP0.

The default USB core rebuild on same-value configuration is intentional and
must not be disabled as a workaround. The `1 -> 0 -> 1` path proves that such
a workaround would also be incomplete.

## Proposed upstream scope

- Keep this PR independent from the STM32F0 TIM14 correction.
- Apply the exact USBv1 ownership fix.
- Audit and, if still applicable on rebased `main`, apply the analogous fix to
  USBv2 in the same USB-focused PR or a maintainer-requested follow-up.
- Add regression coverage for `1 -> 1`, `1 -> 0 -> 1`, and final bus reset.

The attached mailbox patch is intentionally based on `ver21.11.5` and changes
USBv1 only. `USBV2_MAIN_RECOMMENDATION.md` describes the analogous source
pattern without pretending to be a rebased or tested current-`main` patch.

## Verification to record on the rebased PR

- [ ] Unpatched PMA descriptors overlap after repeated configuration.
- [ ] First configuration has no active buffer-address duplicates.
- [ ] Same-value `SET_CONFIGURATION(1)` preserves unique active buffers.
- [ ] `1 -> 0` disables every data endpoint and preserves EP0 buffers.
- [ ] `1 -> 0 -> 1` rebuilds unique data buffers.
- [ ] CDC or the selected USB class still transfers data after both sequences.
- [ ] Suspend/wakeup and unsupported-request EP0 STALL still work.
- [ ] A final bus reset disables data endpoints, resets EP0 correctly, and
  re-enumerates with unique buffers.
- [ ] Relevant USBv1 and USBv2 target builds and current style checks pass.

## Stable backport

The exact USBv1 patch applies to the 21.11.5 source used by the reproducer.
Please land on `main` first and let maintainers select any stable backport.
