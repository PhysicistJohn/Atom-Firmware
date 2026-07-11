# ZS407 RF experiment gates

These gates separate compile-ready experiments from analyzer-qualified fast
paths. Phase 4 never sends `RX_HOP`, rewrites RSSI properties, selects manual
MAX2871 VCO values or changes acquisition automatically.

| Experiment | Phase 4 state | Required evidence before opt-in execution | Integration gate |
| --- | --- | --- | --- |
| Si4468 FRR RSSI | Current mapping/value readback only | For every RBW: paired `GET_MODEM_STATUS` and FRR samples over level, frequency, temperature and no-signal; timestamp freshness after tune | Bounded error versus stock, no stale-value tail, equal/better repeatability and a rollback flag |
| `MODEM_FAST_RSSI_DELAY` | Property readback only | Sweep candidate delay values after small/large same-band and cross-band jumps; compare amplitude settling and elapsed cycles | Smallest delay meeting stock amplitude tolerance at every RBW/path, never a global guessed constant |
| RSSI averaging controls | Property inventory only | Measure detector variance, attack/decay and calibration shift for each averaging mode | Explicit detector metadata plus new per-mode calibration |
| Si4468 `RX_HOP` | Register/VCO dry-run only | Confirm part/ROM/patch; capture full tune versus hop commands; compare actual frequency, RSSI, VCO failures and state at band edges | Per-band enable table; immediate fallback to full calibration on any state/freshness fault |
| Si4468 `TX_HOP` | Specified, no execution | Conducted-load spectra for every hop size/dwell; phase/transient capture | Generator-only arm gate, bounded bands and explicit noncoherent semantics |
| MAX2871 manual VCO | Integer/fraction/divider dry-run only | Prove MUX/LD routing, build a per-device VCO table over temperature and capture lock/spurs | Device-specific table with CRC, lock timeout and automatic-calibration fallback |
| MAX2871 lock/fast-lock/CSR | Existing register state documented; no new writes | Inspect loop-filter/SW topology and capture lock time, phase noise and spurs | Independent feature flags; no shortening from timing alone without valid LD evidence |
| Adaptive acquisition | Refinement-window dry-run only | Replay transient, narrow, drifting and dense traces; compare detection probability and total time | Display/export marks coarse/refined/interpolated bins; full sweep remains one-command fallback |
| 72 MHz MCU | Refused | Full clock tree, USB, timers, flash waits, SPI divisors, temperature and RF spur survey | Separate image only; no coupling to RF fast-path qualification |

## Initial hardware sequence

1. Run `modern radio`, `modern caps`, `modern rfdiag status` and
   `modern rfdiag probe`; archive the transcript.
2. Capture the shared SPI bus while the stock RSSI path reads a fixed source.
3. Build a host fixture from mapping, property, command, RSSI and timestamp
   records; do not change properties yet.
4. Add one independently gated FRR comparison command that records both paths
   without feeding FRR into the displayed trace.
5. Qualify freshness and error at every RBW before an opt-in sweep consumes it.
6. Approach hopping only after the comparison harness is stable.

Any timeout, unexpected radio state, out-of-range VCO count, missing lock
evidence or amplitude residual immediately selects the stock full-tune/read
path. Faster but untrustworthy is a failed experiment.
