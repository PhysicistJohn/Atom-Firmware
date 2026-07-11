# ZS407 firmware modernization roadmap

The ordering principle is simple: preserve measurement behavior first, create
evidence second, improve structure third, and add ambitious features only when
regressions are observable.

## Phase 0 — reproducible archaeology

Status: substantially complete.

- [x] Clone official source with the pinned ChibiOS submodule.
- [x] Identify the ZS407 runtime hardware path.
- [x] Acquire and hash current official `.bin`, `.dfu`, `.elf`, and `.hex`.
- [x] Recover the official compiler and build timestamp from DWARF/binary data.
- [x] Reproduce the official `.bin` byte-for-byte.
- [x] Add deterministic acquisition, build, verification, and inspection tools.
- [x] Document source topology, memory constraints, licensing uncertainty, and
  upstream candidates.
- [x] Document the ZS407 swept-RSSI path, clock/memory/display budgets and
  confidence-graded component inventory.
- [x] Define replacement-firmware, embedded-UI and fixed-point DSP strategies.
- [x] Build a non-flashing Clang/GNU hybrid image and record migration blockers.
- [ ] Publish under PhysicistJohn after personal authentication is isolated.

Exit criterion: one command recreates the pinned official binary from source.

## Phase 1 — exact-device characterization

- [ ] Record the shipped firmware, hardware identity, labels, USB descriptors,
  configuration, and calibration state.
- [ ] Run and archive untouched self-test results.
- [ ] Capture serial command transcripts and binary-response fixtures.
- [ ] Measure representative normal, Ultra, LNA, attenuation, RBW, and generator
  behavior with safe RF fixtures.
- [ ] Enumerate DFU without writing and prove normal recovery.
- [ ] Flash the byte-identical locally rebuilt official image.
- [ ] Repeat all baseline tests and close any discrepancy.

Exit criterion: locally rebuilt stock firmware is indistinguishable from the
shipped/official image on the physical unit.

## Phase 2 — regression harness

- [ ] Add a host-side transcript runner for USB commands and responses.
- [x] Extract the first pure frequency-planning, correction, statistics and
  protocol functions into host-compilable units.
- [ ] Add golden tests for boundary frequencies, integer overflow, interpolation,
  marker math, persistence checksums, and malformed commands.
- [ ] Add firmware size, static RAM, stack-usage, warning, and symbol-delta gates.
- [ ] Add a hardware smoke-test command that is read-only by default.
- [ ] Define RF golden measurements with tolerances based on instrument accuracy,
  fixture uncertainty, and repeatability.

Exit criterion: a change cannot silently alter the protocol, core math, memory
budget, self-test, or selected RF results.

## Phase 3 — low-risk correctness work

- [ ] Fix and upstream the phantom hardware-version table entry.
- [ ] Validate `TARGET` values instead of treating every non-empty value as F303.
- [ ] Replace build timestamps with explicit reproducible build metadata.
- [ ] Harden shell argument parsing, ranges, timeouts, and error reporting.
- [ ] Make persisted configuration schema/version transitions explicit.
- [ ] Measure stack high-water marks and move suitable buffers to CCM deliberately.
- [ ] Close compiler warnings without hiding warnings globally.

Exit criterion: fixes are small, independently reviewable, build both supported
targets where relevant, and pass physical regression tests.

## Phase 4 — architectural modernization

- [ ] Define narrow interfaces for RF register I/O, display, storage, clock/time,
  USB transport, and persisted settings.
- [ ] Split direct `.c` inclusion into normal translation units incrementally.
- [ ] Reduce shared mutable globals and state ownership ambiguity.
- [ ] Separate measurement state, presentation state, and command transport.
- [x] Introduce a restricted-by-default capability structure keyed by measured
  hardware identity.
- [ ] Evaluate a current compiler before considering an RTOS/HAL upgrade.
- [x] Prove selected application objects compile with Clang 17 and link with
  GNU 11.3.1; keep the resulting image in do-not-flash status.
- [ ] Replace GCC optimization pragmas with named per-module build profiles.
- [x] Split hard-fault assembly entry from the normal C crash reporter.
- [ ] Modernize CMSIS compiler support and test hard-float context switching.
- [ ] Evaluate ChibiOS replacement/upgrade only with interrupt, USB, timing,
  memory, power, and RF evidence in place.

Exit criterion: core logic is host-testable and hardware drivers have explicit
boundaries, without degrading sweep timing or RF behavior.

## Phase 5 — genuinely better instrument behavior

The complete candidate inventory, source-derived constraints, risk ratings and
recommended implementation order live in
[`docs/ENHANCEMENT_RISK_REGISTER.md`](docs/ENHANCEMENT_RISK_REGISTER.md). This
phase lists the major directions; the register is the detailed working backlog.
The cumulative branch and image gates are defined in
[`docs/PHASE_IMPLEMENTATION.md`](docs/PHASE_IMPLEMENTATION.md).

Candidate directions, to be prioritized from measurements rather than novelty:

- a versioned, machine-readable USB protocol alongside the compatible shell;
- richer error/status telemetry and crash records;
- faster or more deterministic trace streaming;
- safer generator state and explicit output indication;
- the Atomic 480×320 dirty-tile UI described in `docs/EMBEDDED_UI.md`;
- progressive trace presentation and display/RF deadline scheduling;
- occupied bandwidth, ACPR, robust noise floor, peak persistence, spectral
  masks and arbitrary gated power with validity metadata;
- measured sweep optimizations: state caching, precomputed plans and adaptive
  coarse/refined acquisition;
- Q15 FIR/FFT kernels using Cortex-M4 packed DSP/saturation instructions where
  cycle counts demonstrate a benefit;
- improved saved-measurement metadata and configuration migration;
- optional zero-span envelope-spectrum and deconvolution experiments whose
  sample axis, kernel and uncertainty are stated;
- a signed/hash-verified personal release process with reproducible artifacts.

“Better” must be demonstrated in at least one measurable dimension—accuracy,
repeatability, scan speed, usability, recovery, diagnosability, safety, or
maintainability—without an unexplained loss elsewhere.

## Phase 6 — sampled-data decision

- [ ] Inspect board/test pads and public Si4468 GPIO modes for a safely
  accessible low-IF, demodulated-data or audio path.
- [ ] Measure any candidate path's bandwidth, sample clock, loading, noise and
  relationship to the selected RBW.
- [ ] If useful, prototype a reversible external capture before changing the
  PCB or production firmware.
- [ ] If no suitable sample path exists, specify hardware v2 with quadrature or
  direct IF sampling, DMA-visible RAM and a shared protocol/UI contract.

Exit criterion: “wideband FFT” has either a characterized physical sample path
and honest bandwidth, or an explicit future-hardware requirement. It is never
claimed from swept RSSI alone.

## Permanent non-goals

- Pretending modified firmware is an official tinySA release.
- Publishing from a corporate GitHub identity or corporate repository.
- Silent firmware updates or generator activation.
- Removing recovery paths to gain a small amount of flash.
- Replacing calibrated RF behavior on aesthetic grounds.
- A big-bang rewrite before the existing implementation is under test.
