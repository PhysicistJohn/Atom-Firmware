# Phase 1: portable host core and generated contracts

Branch: `physicistjohn/phase-1-host-core`

Phase 1 establishes a tested seam between the ZS407 firmware and a modern Mac
application without trying to emulate RF hardware.

## Implemented

- allocation-free C11 frequency DDA, fixed-point saturation, correction-table
  cursor, quantile and parabolic-marker primitives;
- a bounded little-endian protocol frame with version, request ID, command,
  payload length and CRC-32;
- one JSON source of truth projected deterministically into C, Swift and
  TypeScript;
- a golden protocol fixture and 10,000 deterministic encode/decode round trips;
- Apple Clang UBSan tests, an ASan-linked opt-in image, Swift typechecking and
  Cortex-M4 freestanding cross-compilation;
- a correct assembly-only hard-fault entry veneer for phase images, choosing
  MSP or PSP from `EXC_RETURN`, preserving R4-R11, then entering ordinary C;
- a successful opt-in Clang `-Oz` compile of `main.c`, `sa_core.c` and
  `sa_cmd.c` inside a complete GNU-linked 186,372-byte hybrid image;
- strict `TARGET=F072|F303` validation rather than silently mapping typos to an
  F303 build.

The binary protocol is a contract and tested codec in this phase; it is not yet
connected to USB. The legacy shell remains the only live transport.

## Hardware gates still open

- capture real shell transcripts and USB descriptors as fixtures;
- confirm the phase fault reporter with a controlled debug-only fault after
  recovery is proven;
- establish RF golden measurements and tolerances.

The generated Swift file can be imported by the future Mac companion today;
no firmware behavior needs to be guessed or manually duplicated.
