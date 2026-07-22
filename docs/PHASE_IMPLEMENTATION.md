# Cumulative implementation and image plan

This document records the completed historical Phase 0–6 workflow. Every phase
was developed on a local/private branch created from the completed tip of the
preceding phase. No phase was rebased onto upstream and no image was flashed as
part of this plan.

## Branch chain

| Phase | Branch | Cumulative scope |
| ---: | --- | --- |
| Baseline | `physicistjohn/bootstrap-zs407` | Byte-exact archaeology, hardware/reference documentation and LLVM feasibility work. |
| 0 | `physicistjohn/phase-0-build-safety` | Build gates, feature profiles, documented timing profile, diagnostics and artifact provenance. |
| 1 | `physicistjohn/phase-1-host-core` | Portable host-tested core, generated contracts, replay fixtures and numerical oracles. |
| 2 | `physicistjohn/phase-2-deterministic-firmware` | RF-plan preparation, state ownership, SPI scheduling, compact trace representation and deterministic embedded services. |
| 3 | `physicistjohn/phase-3-dsp-ui` | Qualified DSP/measurements, progressive trace presentation and the Atomic embedded UI architecture. |
| 4 | `physicistjohn/phase-4-rf-experiments` | Independently gated FRR, RSSI timing, RX hopping, MAX2871 and adaptive-acquisition experiments. |
| 5 | `physicistjohn/phase-5-waveform-generator` | DAC AWG, waveform event compiler/runtime and Si4468 FIFO/direct modulation experiments. |
| 6 | `physicistjohn/phase-6-final-integration` | Cumulative integration, capability audit, hardware-v2 contracts and the final no-flash image matrix. |

Creating a later branch is an exit action of the preceding phase. This makes the
ancestry itself an audit trail: phase 5 necessarily contains phases 0 through 4.

## Image contract

`tools/build-phase-image.sh N` builds phase `N` only on its expected branch. It:

1. requires a clean committed worktree and the pinned ChibiOS submodule;
2. bootstraps the pinned Arm GNU 11.3.Rel1 compiler;
3. supplies an explicit phase build profile and reproducible timestamp;
4. performs two clean builds and requires byte-identical binaries;
5. verifies the 240 KiB application limit and ZS407 identity string;
6. records binary, ELF and HEX hashes plus GNU size output;
7. stores the image set below `.artifacts/phase-images/phase-N/<commit>/`.

The generated directory is deliberately ignored by Git. The exact phase-tip
commit is tagged after a successful build, and the final handoff records all
artifact hashes. Images remain explicitly hardware-unqualified until the
physical baseline and recovery gates are complete.

## Phase exit gates

Every phase must satisfy all applicable gates before the next branch is made:

- native host tests and generated-file consistency checks pass;
- a clean GNU firmware build completes twice with identical binary hashes;
- the ELF links without unresolved symbols;
- application flash stays at or below 245,760 bytes;
- static RAM, stack reports and largest-symbol changes are reviewed;
- the image contains the expected ZS407 and phase build identity;
- experimental RF/output behavior is off by default unless its phase explicitly
  owns a no-flash research image;
- the phase tip and annotated image tag were pushed only to the historical private
  `PhysicistJohn/TinySA_Firmware` origin.

Build success establishes compile/link and reproducibility confidence. It does
not establish RF accuracy, safe generator spectra or flash qualification.

## Enhancement disposition

The final phase audits every row in
[ENHANCEMENT_RISK_REGISTER.md](ENHANCEMENT_RISK_REGISTER.md) into one of these
states:

- `implemented` -- present in the cumulative image and covered by tests;
- `experimental` -- compiles behind a separate gate and awaits hardware data;
- `host-only` -- intentionally lives in the Mac/Atomizer toolchain;
- `specified` -- interface and acceptance criteria exist for later work;
- `blocked-hardware` -- impossible on the current sampled/control paths;
- `avoided` -- intentionally rejected because risk exceeds value.

"All the way through" means every candidate receives a disposition and every
implementable phase produces an image. It does not mean enabling an unverified
RF optimization or claiming I/Q/AWG behavior the ZS407 cannot physically
provide.

## Phase notes

- [Phase 0: reproducible build and electrical timing safety](phases/PHASE_0.md)
- [Phase 1: portable host core and generated contracts](phases/PHASE_1.md)
- [Phase 2: deterministic services and CCM frequency cache](phases/PHASE_2.md)
- [Phase 3: fixed-point DSP and Atomic UI model](phases/PHASE_3.md)
- [Phase 4: independently gated RF experiments](phases/PHASE_4.md)
- [Phase 5: waveform generator foundations](phases/PHASE_5.md)
- [Phase 6: final integration and hardware-v2 boundary](phases/PHASE_6.md)
