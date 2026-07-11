# Phase 3: fixed-point DSP, derived measurements and Atomic UI model

Branch: `physicistjohn/phase-3-dsp-ui`

Phase 3 adds analyzer math and presentation primitives while keeping every
result explicit about the data the ZS407 actually samples.

## Implemented

- Q1.15 radix-2 complex FFT kernels for 256 and 512 points with deterministic
  per-stage scaling and saturating narrowing;
- impulse, Nyquist and off-axis tone vectors that caught and corrected a real
  twiddle-stage indexing defect before the embedded image was cut;
- dB×32 conversion with the `-32768` invalid sentinel reserved;
- linear-milliwatt integrated power corrected by bin width / ENBW;
- configurable occupied-power bandwidth (99% in the shell command);
- robust 20th-percentile noise estimate, peak detection and qualified
  parabolic peak interpolation;
- explicit validity flags for gaps, power, OBW, noise and interpolation;
- immutable UI snapshot metadata, a 150-bit dirty map for the existing 15×10
  tile geometry, clipped rectangle invalidation and deterministic tile order;
- per-column min/max trace envelopes that preserve narrow peaks and skip
  invalid samples;
- `modern metrics`, which converts the completed live frequency trace and
  reports peak, noise floor, integrated power and 99% OBW without altering it;
- `modern dsp-selftest`, which runs embedded FFT and UI-model smoke vectors;
- `modern palette atomic|restore|status`, a reversible runtime preview of the
  sibling Atomizer/Atomic semantic palette. It never saves automatically;
- 7,456 CCM bytes reserved for the frequency cache, two fixed-point trace
  workspaces and 512-point complex FFT scratch, leaving ordinary DMA SRAM
  unchanged.
- a complete Phase 3 Clang `-Oz`/GNU hybrid link at 194,252 bytes (no-flash).

The Atomic preview changes the existing renderer's semantic colors immediately
but does not yet replace screen layout. Its mint/cyan/violet/amber/red tokens
are therefore testable on the physical panel before larger UI geometry work.
`restore` returns the exact palette captured when the preview was enabled.

## Measurement semantics

`modern metrics` accepts only a frequency sweep with at least two points. It
uses `actual_rbw_x10` as ENBW pending measured RBW kernels and reports flags
with every result. Hardware qualification must replace that approximation with
measured ENBW per RBW/path before treating integrated values as calibrated.

The FFT is not exposed as an RF spectrum mode in this phase. It is suitable for
uniform zero-span envelope samples after sample timestamps prove a stable
interval. It cannot recover phase, I/Q, negative frequency or instantaneous RF
bandwidth from the Si4468 RSSI detector.

## Hardware gates still open

- compare integrated power/OBW against a traceable source and measured ENBW;
- timestamp zero-span RSSI and qualify 256/512-point envelope FFT axes;
- capture Atomic palette screenshots and inspect the physical panel;
- measure CCM FFT cycles and check RF spurs while DSP runs;
- connect immutable snapshots/min-max envelopes to the production renderer
  only after display-DMA ownership is instrumented.
