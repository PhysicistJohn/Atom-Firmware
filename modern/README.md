# Portable ZS407 instrument core

This directory is the shared semantic boundary between embedded firmware and
the PhysicistJohn Mac companion. It contains no ChibiOS or STM32 dependency.

- `contracts/zs407_contract.json` is the protocol/capability source of truth.
- `generated/` contains deterministic C, Swift and TypeScript projections.
- `core/` contains allocation-free C11 frequency, correction, statistics and
  framed-protocol primitives.

Run `tools/test-host-core.sh` on macOS to regenerate-check the contracts, build
with Apple Clang and UndefinedBehaviorSanitizer, link an AddressSanitizer image,
replay the golden frame, fuzz 10,000 encode/decode round trips, typecheck the
Swift projection and cross-compile every core source as freestanding Cortex-M4
code. Set `ZS407_RUN_ASAN=1` on a host with a known-good Apple ASan runtime;
some newer dyld/runtime combinations deadlock before `main`, so release builds
do not run that optional binary implicitly.

This is source sharing, not source-to-source translation of the legacy
firmware. Instrument semantics are written once in portable C; native UI code
uses a generated Swift contract, and the same C is compiled for ARM only after
an embedded phase explicitly integrates it.
