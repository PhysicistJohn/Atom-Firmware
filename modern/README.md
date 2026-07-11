# Portable ZS407 instrument core

This directory is the shared semantic boundary between embedded firmware and
the PhysicistJohn Mac companion. It contains no ChibiOS or STM32 dependency.

- `contracts/zs407_contract.json` is the protocol/capability source of truth.
- `generated/` contains deterministic C, Swift, TypeScript and runnable
  JavaScript projections.
- `core/` contains allocation-free C11 frequency, correction, protocol,
  RF-state, Q15 FFT, derived-measurement, dirty-tile UI and waveform/event
  primitives plus the Phase 0–6 release capability manifest.
- `embedded/` contains narrowly isolated STM32 adapters. The Phase 5 DAC/DMA
  adapter and post-phase binary USB worker are compiled and linked but locked
  before output/stream ownership changes.
- `waveforms/` documents the deterministic Mac-to-firmware waveform DSL and
  binary contract.

Run `tools/test-host-core.sh` on macOS to regenerate-check the contracts, build
with Apple Clang and UndefinedBehaviorSanitizer, link an AddressSanitizer image,
replay the golden frame, fuzz 10,000 encode/decode round trips, typecheck the
Swift projection and cross-compile every core source as freestanding Cortex-M4
code. Set `ZS407_RUN_ASAN=1` on a host with a known-good Apple ASan runtime;
some newer dyld/runtime combinations deadlock before `main`, so release builds
do not run that optional binary implicitly.

The `protocol-v2` post-phase profile adds typed payload codecs, incremental
framing/CRC, 4,096-point trace chunking, compact trace/waveform storage, an
SPSC interrupt-handoff primitive, and a compiled-but-locked ChibiOS USB worker.
See [`PROTOCOL_V2.md`](../docs/PROTOCOL_V2.md),
[`MCU_EXECUTION_MODEL.md`](../docs/MCU_EXECUTION_MODEL.md), and
[`RELEASE_CYCLES.md`](../docs/RELEASE_CYCLES.md).

This is source sharing, not source-to-source translation of the legacy
firmware. Instrument semantics are written once in portable C; native UI code
uses a generated Swift contract, and the same C is compiled for ARM only after
an embedded phase explicitly integrates it.
