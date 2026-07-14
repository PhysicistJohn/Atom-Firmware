# Issue draft: STM32F0 TIM14 GPT ISR is missing

## Summary

Enabling `STM32_GPT_USE_TIM14` on an STM32F0 target fails in
`os/hal/ports/STM32/LLD/TIMv1/hal_gpt_lld.c` with:

```text
#error "TIM14 ISR not defined by platform"
```

STM32F0 platform headers already define the standalone
`STM32_TIM14_HANDLER` and `STM32_TIM14_NUMBER`, and the GPT driver provides
`GPTD14`. The generic low-level driver is missing the ISR that joins them.

## Affected code checked locally

- `ver21.11.5`, commit
  `f4bbadf964fc746aef8bbcf34135c7d8fabb8eae`.
- The public branch tips recorded in the repository's 2026-07-14 read-only
  audit also contained the same failure. Recheck current `main` before filing.

Commit `00091c7aab1e5b327ca291d40a31b82b9767635c` removed the generic TIM14
handler in 2019 while adding TIM10/TIM13 support. That was appropriate for
shared-vector platforms, but left the STM32F0 standalone-vector case without a
provider.

## Minimal reproduction

1. Select an STM32F072 platform that defines a standalone TIM14 vector.
2. Set `HAL_USE_GPT=TRUE` and `STM32_GPT_USE_TIM14=TRUE`.
3. Reference/start `GPTD14` so the driver is linked.
4. Build the application.

The unpatched build stops at the `#error` above.

## Proposed correction

Under the existing `STM32_GPT_USE_TIM14` and
`!STM32_TIM14_SUPPRESS_ISR` guards:

- require `STM32_TIM14_HANDLER`;
- define `OSAL_IRQ_HANDLER(STM32_TIM14_HANDLER)`;
- call `gpt_lld_serve_interrupt(&GPTD14)` between `OSAL_IRQ_PROLOGUE()` and
  `OSAL_IRQ_EPILOGUE()`.

This restores the same generic standalone-vector shape used before the 2019
change without changing shared-vector platforms.

## Local integration evidence

The one-file correction is local commit
`2b8f425d26a61a7887916f7052b401f9e767a949`. With it, the tinySA ChibiOS
21.11.5 port reproducibly builds both STM32F072 and STM32F303 targets with Arm
GNU 11.3.Rel1, zero compiler warnings, and zero undefined symbols. The F072
artifact is build evidence only; no F072 hardware result is claimed.

## Requested disposition

Please accept a vendor-neutral fix on `main` and select a
`stable-21.11.x` backport if appropriate. This issue is independent of the USB
PMA allocator report.
