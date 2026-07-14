# PR draft: stm32: restore standalone TIM14 GPT ISR

## What this changes

This adds the missing generic `STM32_TIM14_HANDLER` implementation to the
STM32 TIMv1 GPT low-level driver. It is active only when
`STM32_GPT_USE_TIM14` is enabled and `STM32_TIM14_SUPPRESS_ISR` is not defined.

The handler follows the existing ChibiOS IRQ shape and dispatches `GPTD14`
through `gpt_lld_serve_interrupt()`.

## Why

STM32F0 devices can expose TIM14 through a standalone vector and already
provide the platform handler/number definitions. The current fallback is an
unconditional compile-time error, so a valid STM32F072 GPTD14 configuration
cannot build.

## Scope

- One file: `os/hal/ports/STM32/LLD/TIMv1/hal_gpt_lld.c`.
- No tinySA-specific code or comments.
- No change to shared-vector targets or suppressed application-provided ISRs.
- Independent from the USB packet-memory fix.

## Verification to record on the rebased PR

- [ ] Unpatched STM32F072 reproducer reaches the documented `#error`.
- [ ] Patched reproducer builds with GPTD14 linked and referenced.
- [ ] Relevant current ChibiOS demo/test build passes.
- [ ] Current ChibiOS style checker passes the changed file.
- [ ] tinySA F072 and F303 integration builds remain warning-free.
- [ ] Hardware callback timing is reported only if F072 hardware is tested.

## Backport

The prepared patch applies to the 21.11.5 code and dry-runs on the audited
`master`, `main`, and `stable-21.11.x` tips. Current/default integration is
`master`; the repository PR template's unconditional `main` instruction is
stale. Please land the correction on the branch requested by the maintainers
and select any stable backport according to project policy.
