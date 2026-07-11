# Phase 2: deterministic embedded services and CCM frequency cache

Branch: `physicistjohn/phase-2-deterministic-firmware`

Phase 2 links the portable core into the Cortex-M4 image and uses it for one
measured-risk optimization: caching the normal sweep grid in CPU-only CCM RAM.

## Implemented

- corrected the streaming rational/DDA accumulator to match the stock
  round-to-nearest grid at every point, exhaustively checked for 2..511 points;
- a 3,600-byte, 8-byte-aligned frequency cache in the previously unused 8 KiB
  CCM region for 450-point ZS407 sweeps;
- cached `getFrequency()` for normal sweeps, preserving the existing dynamic
  calculation for multiband sweeps and out-of-range compatibility calls;
- explicit RF-state dirty masks and settle classes for receiver, synthesizer,
  attenuator, RBW, path and generator state;
- a deterministic RF/control/display/storage scheduler model in which RF owns
  the highest priority;
- min/max/mean cycle profiling primitives with a 64-bit total;
- `modern selftest`, a hardware-free on-device exercise of the linked DDA,
  state, scheduler and profiler code;
- `modern caps`, an immutable source-derived capability profile that selects a
  restricted result for unknown hardware instead of assuming ZS407 limits;
- `modern plan START STOP POINTS`, a bounded read-only view of the exact
  frequency grid;
- removal of the zero-filled phantom fifth hardware-version entry in phase
  images;
- per-image section and stack-usage reports, including explicit CCM bytes.
- a complete opt-in Clang `-Oz`/GNU hybrid link with the portable core compiled
  as ARM Clang objects (187,836-byte draft image, no-flash).

The bus scheduler is an executable, tested ownership contract in this phase;
it does not yet interpose on legacy SPI calls. Doing that before display-DMA
and RF timing captures would add concurrency risk without evidence.

## Expected performance effect

Normal-grid construction performs the division once per sweep configuration.
Subsequent random marker, correction, rendering and measurement lookups become
one CCM load instead of 64-bit multiply/add/divide. Acquisition still performs
RF programming and analog settling, so this should improve CPU headroom and
jitter rather than promise a proportional sweep-rate increase.

CCM is safe for this cache because no peripheral DMA consumes frequencies. The
ordinary 40 KiB SRAM and both display DMA buffers are unchanged.

## Hardware gates still open

- compare every cached point with shell `frequencies` output on stock firmware;
- profile cycle distributions and complete-sweep timing with cache on/off;
- verify normal, multiband, zero-span and generator sweep grids;
- instrument display-DMA completion before the scheduler owns real SPI1 work.
