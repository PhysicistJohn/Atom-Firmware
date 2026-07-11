# Known issues and research priorities

Snapshot date: 2026-07-10. These are reports and open questions from the
official GitHub project, official changelog, wiki, and support channels. An open
issue is not automatically a confirmed defect in the ZS407 or current release.

## Build provenance is a functional input

Two reports make compiler provenance a first-class RF concern:

- [Issue #70](https://github.com/erikkaashoek/tinySA/issues/70) reports a Basic
  image built with GCC 12.2 that booted but produced bad RF behavior and failed
  tests. Discussion points to hard-coded timing and optimizer-sensitive code.
- [Issue #152](https://github.com/erikkaashoek/tinySA/issues/152) reports noise
  and self-test failure from a GitHub-built image. A 2026 comment says releases
  since v1.4216 use Arm GNU 11.3.Rel1.

This fork goes beyond “same compiler version”: it reproduces the current
official binary byte-for-byte using GCC 11.3.1, the Windows package's target
libraries, and the release build epoch. That result is ready to be shared on
issue #152 after PhysicistJohn-only authentication is available.

Implication: compiler upgrades are hardware experiments. A successful link and
smaller image do not qualify a toolchain.

## ZS407 RF behavior has continued to evolve

Recent official changelog entries include ZS407-specific work:

- v1.4195: reduced ZS407 spurs;
- v1.4197: reduced internally generated 10 MHz-related spurs on ZS407;
- v1.4-198: possible reduction of approximately 4.278 GHz spurs on some ZS407
  hardware;
- v1.4215: improved ZS407 output-level accuracy near -78 dBm;
- v1.4216: compiler change with an explicit warning about undiscovered bugs.

These entries show why the RF baseline needs fixtures around known transition
and spur frequencies. A structural refactor can regress behavior even when its
high-level math is unchanged.

## Reliability and transport

- [Issue #87](https://github.com/erikkaashoek/tinySA/issues/87) reports USB
  serial becoming unresponsive after repeated `scan` commands while the local UI
  remains alive. Long-duration command/sweep arbitration is a Phase 1 test.
- [Issue #85](https://github.com/erikkaashoek/tinySA/issues/85) reports identical
  USB serial numbers; [PR #112](https://github.com/erikkaashoek/tinySA/pull/112)
  proposes unique serials. Device identity must not rely on serial number alone.
- The v1.4216 changelog says a redraw after `wait` could cause stack overflow and
  records a compiler switch. Stack high-water telemetry belongs in the firmware
  before command-path expansion.

Required tests:

- thousands of prompt-delimited commands;
- repeated `scan`, `scanraw`, capture, pause/resume, and abort sequences;
- USB unplug/replug during each response type;
- simultaneous screen refresh and measurement acquisition where supported;
- thread stack high-water marks before and after each test.

## Measurement correctness

- [Issue #118](https://github.com/erikkaashoek/tinySA/issues/118) argues that the
  quasi-peak implementation smooths across frequency rather than applying the
  required time-domain detector behavior per bin. Treat quasi-peak results as a
  research item until the implementation is checked against the intended CISPR
  model and test waveforms.
- [Issue #101](https://github.com/erikkaashoek/tinySA/issues/101) reports an
  unexpected measurement step.
- Several historical calibration and self-test issues remain open. Some may be
  support cases or damaged hardware, so they need reproduction criteria rather
  than bulk code changes.

Measurement changes require known sources, attenuation, repeat runs, uncertainty
budgets, and golden raw traces—not screenshots alone.

## Persistence and storage

- [Issue #141](https://github.com/erikkaashoek/tinySA/issues/141) reports that
  loading a saved CSV corrupts/restores incorrect sweep frequencies and that a
  normalize/average preset becomes inconsistent after recall.
- [Issue #97](https://github.com/erikkaashoek/tinySA/issues/97) reports missing
  RBW restoration for multiband settings.
- [Issue #75](https://github.com/erikkaashoek/tinySA/issues/75) reports SD
  read/write trouble; v1.4217 later improved compatibility with some 32 GB cards.
- [Issues #90](https://github.com/erikkaashoek/tinySA/issues/90),
  [#99](https://github.com/erikkaashoek/tinySA/issues/99), and
  [#100](https://github.com/erikkaashoek/tinySA/issues/100) cover filename and
  file-browser limitations.

The first host tests should target parsers, format round trips, schema versions,
frequency/RBW restoration, long names, malformed files, and power loss during
writes. These are high-value tests that do not require RF emulation.

## Protocol and feature opportunities

- [Issue #155](https://github.com/erikkaashoek/tinySA/issues/155) requests ACPR
  display and machine-readable access to computed measurements over USB.
- [Issue #132](https://github.com/erikkaashoek/tinySA/issues/132) requests a
  compact two-byte `scanraw` representation.
- [Issue #153](https://github.com/erikkaashoek/tinySA/issues/153) requests more
  signal-generator sweep parameters.
- [Issue #147](https://github.com/erikkaashoek/tinySA/issues/147) discusses a
  cross-platform controller, reinforcing the value of a stable firmware-side
  capability and data protocol.

A versioned structured protocol should be additive. Existing shell commands and
prompt behavior are compatibility surface area for current tools.

## Triage order for this fork

1. Reproduce current stock behavior on the physical ZS407.
2. Stress USB serial and record raw failure transcripts.
3. Build persistence/CSV round-trip tests on the host.
4. Validate quasi-peak semantics and ZS407 spur/transition fixtures.
5. Add read-only machine-readable measurement/status access.
6. Consider ACPR and other new measurements only after raw values, units,
   averaging, and uncertainty have explicit contracts.
