# Phase 0: reproducible build and electrical timing safety

Branch: `physicistjohn/phase-0-build-safety`

Phase 0 creates an opt-in modernization profile without disturbing the
archaeological build. A normal `TARGET=F303` build retains the source behavior
needed to reproduce the official ZS407 image. Supplying `PHASE=0` enables the
cumulative phase profile.

## Implemented

- one flash wait state at 48 MHz, as required by the STM32F303CC data sheet;
- a 6 MHz Si4468 SPI clock, below its 10 MHz command-interface maximum;
- a 12 MHz MAX2871 SPI clock, below its 20 MHz maximum;
- a 12 MHz ST7796S display SPI clock, below the documented write-cycle limit;
- the already-compliant 6 MHz PE4302 interface is unchanged;
- an explicit phase/feature header so later experiments remain independently
  gated;
- a read-only `modern` shell command reporting the compiled profile, flash
  configuration, DWT cycle-counter state and SPI budgets;
- an explicit `modern radio` query for Si4468 part, ROM and patch identity;
- a two-clean-build image tool with branch, identity, flash-size, unresolved
  symbol and reproducibility gates.

`modern radio` takes the sweep mutex because its two read commands use the same
SPI1 bus as acquisition and display. It does not change radio properties.

## Verified without hardware

- The compatibility profile reproduces the official 185,704-byte binary
  byte-for-byte (SHA-256
  `3c9847ff4d7b80561df2f2f1030a112703a083409ffb2ee11361b2413b7c1e41`).
- The phase profile compiles, links and has no unresolved ELF symbols.
- The final phase-tip image is built twice from clean state and must be
  byte-identical before Phase 1 is created.

## Hardware gates still open

- confirm that the slower shared-bus clocks do not expose an upstream timeout;
- capture `modern` and `modern radio` output from the exact ZS407;
- compare stock and Phase 0 sweep timing, amplitude, spur response and UI
  latency;
- prove DFU recovery before flashing any modernization image.

Build confidence and hardware qualification are deliberately separate. The
Phase 0 image is a no-flash artifact until those gates are complete.
