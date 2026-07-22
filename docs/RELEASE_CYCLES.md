# Post-phase release cycles

The Phase 0–6 chain and the private laboratory releases described below are an
immutable historical archive. They predate the `Atom-Firmware` repository name
and v2 Flasher manifest; their old repository names remain exact provenance,
not current publishing instructions.

## Current hardware freeze

The actual enhanced v0.3 hardware checkpoint is source commit
`43eb0f193c8619cb7ca23726e3062973c65ae958`, embedded version
`tinySA4_hw-v0.3-fft1024-g43eb0f1`. It passed the cold self-test, modern
diagnostics and repeatable on-device 1,024-point FFT execution recorded in
[HARDWARE_BRINGUP.md](HARDWARE_BRINGUP.md). It is now frozen: getting FFT-1024
live was sufficient for this checkpoint, and no waveform or new RF-modulation
executor is scheduled for immediate deployment.

The table below is the original prospective theme map, not an as-built version
history. Its old v0.3/v0.5 allocation was superseded when FFT-1024 was selected
for the actual v0.3 hardware trial. Future version numbers and themes remain
provisional until work explicitly resumes; the deferred generator queue is in
[WAVEFORM_GENERATOR.md](WAVEFORM_GENERATOR.md).

## Original prospective theme map

| Release | Branch theme | Hardware behavior | Exit evidence |
|---|---|---|---|
| v0.2 | typed protocol, marshalling, async USB laboratory | binary worker and hardware CRC locked | cross-language vectors, fuzz, GNU/LLVM compile, binary lock audit |
| v0.3 | shared SPI bus arbiter and DWT observability | timing unchanged; record-only | bus ownership stress, logic traces, sweep equivalence |
| v0.4 | RF transaction pipeline, CTS/`nIRQ`, FRR and measured FIFO threshold | one opt-in path at a time | latency distributions, timeout/fallback tests, spectral comparison |
| v0.5 | wider FFT/measurement pipeline and Cortex-M4 DSP kernels | analyzer math changes behind A/B switch | vector error bounds, cycle/stack/RAM budgets, captured-signal corpus |
| v0.6 | atomic high-information display and host UI parity | presentation changes | screenshot/image regression and interaction timing |
| v0.7 | qualified waveform/RF generation experiments | output remains default-off | load, level, spur, thermal, watchdog and emergency-off qualification |
| v1.0 | selected hardware-qualified defaults | only proven paths on | complete ZS407 matrix and recovery image |

## Commit shape inside a release

Keep commits reviewable and bisectable in this order:

1. contract, fixtures and failing host tests;
2. portable implementation;
3. target adapter, initially unreachable or fail-closed;
4. binary/disassembly safety audit;
5. documentation and hardware procedure;
6. captured hardware evidence and only then the activation commit.

Generated files travel in the same commit as their schema/generator. Build
artifacts do not. The historical private prerelease attaches reproducible BIN/HEX/ELF,
manifest, sections, stack report, benchmark and lock audits.

## Branch and tag policy

The archived workflow used branches such as
`physicistjohn/release-v0.2-protocol-marshalling`, tags such as
`lab-v0.2.0-protocol`, and the private `PhysicistJohn/TinySA_Firmware` origin.
Do not repoint its release scripts at the current repository; the upstream
remote remains push-disabled.

A tag means the source and no-flash image are reproducible. It does not mean
hardware qualification. Release notes and manifests must say
`hardware_qualified=false` until physical tests are committed.

Upstreamable fixes are extracted as minimal patches without the personal
roadmap, private release tooling or PhysicistJohn branding, as described in
[`UPSTREAM.md`](UPSTREAM.md).
