# Phase 4: independently gated RF experiments

Branch: `physicistjohn/phase-4-rf-experiments`

Phase 4 turns the disabled fast-path source fragments and data-sheet ideas into
testable plans and probes. It deliberately does not enable them.

## Implemented

- source-equivalent Si4468 band/integer/fraction planning and a normalized,
  explicitly unqualified VCO-count estimate for `RX_HOP`/`TX_HOP` research;
- MAX2871 output-divider, integer, fraction, modulus and register 0/1 dry-run
  planning for the ZS407's scaled 30 MHz reference;
- boundary, exact-frequency, unsupported-band and overflow host tests;
- prominence/radius refinement-window selection with merging and bounded
  output for adaptive coarse/refined sweeps;
- `modern rfdiag status`, which proves FRR, hopping, manual VCO and adaptive
  execution are all off;
- `modern rfdiag probe`, which only reads the active FRR A-D mappings/values,
  `MODEM_RSSI_CONTROL`, `MODEM_RSSI_COMP` and
  `MODEM_FAST_RSSI_DELAY`, with DWT elapsed cycles;
- `modern rfdiag enable`, which intentionally refuses to enable RF fast paths;
- `modern hop-plan FREQ` and `modern max-plan FREQ`, which print transaction
  inputs/words without sending them;
- `modern refine PROMINENCE_DB RADIUS`, which identifies candidate rescan
  windows on the completed live trace but performs no new acquisition;
- the explicit qualification matrix in
  [RF_EXPERIMENT_GATES.md](../RF_EXPERIMENT_GATES.md).
- a complete Phase 4 Clang `-Oz`/GNU hybrid link at 197,532 bytes (no-flash).

The existing source's disabled hopping expression multiplies by the
`FREQ_MULTIPLIER` scale inside its VCO estimate and is labelled unreliable.
The portable planner removes that unit mismatch, but the resulting value is
still marked `vco_qualified=0` because only actual calibration/readback can
establish the correct count.

## Hardware gates still open

Every RF experiment remains open. The phase is valuable because the upcoming
hardware session can collect exact mappings, properties, cycles and dry-run
words from the same image while the measurement path stays stock. See the gate
matrix for the required paired evidence and rollback rules.
