# Phase 6: final integration and hardware-v2 boundary

Branch: `physicistjohn/phase-6-final-integration`

Phase 6 closes the cumulative software program without inventing hardware
results. It produces a final no-flash image, a runtime safety/capability
manifest, a machine-complete disposition register and a concrete coherent
replacement-hardware architecture.

## Implemented

- a 20-byte release-capability ABI with monotonic Phase 0–6 feature bits,
  explicit safety bits and host self-tests;
- `modern audit`, which runs manifest, deterministic-service, FFT, UI and locked
  AWG self-tests and reports all execution gates;
- an exact-name/order/state audit covering all 140 enhancement candidates;
- a candidate-by-candidate closure table separating implemented,
  experimental, host-only, specified, hardware-blocked and avoided work;
- a hardware-v2 plan for coherent 40 MHz I/Q, true RF AWG, FPGA sample timing,
  large capture memory, independent buses and a 6–12 GHz translated extender;
- a phase-chain auditor that verifies branch/tag identity, cumulative ancestry,
  artifact hashes/sizes, reproducibility flags, output locks, personal Git
  identity, exact origin URL and private GitHub visibility;
- final documentation links and release packaging policy.

## Runtime audit contract

`modern audit` is read-only except for RAM scratch used by self-tests. Its AWG
self-test calls the same start path audited in the ELF and requires
`NOT_QUALIFIED`; no RF experiment executes. A healthy Phase 6 result reports:

```text
manifest ... phase=6 ... features=... safety=...
audit selftest manifest=00000000 services=00000000 fft=00000000 ui=00000000 awg=00000000 PASS
audit hardware_qualified=0 rf_execution=off awg_execution=locked automated_flash=absent
```

## Resource result

The draft GNU image uses 203,684 bytes of the 245,760-byte application region.
Ordinary BSS remains 28,820 bytes, linker heap 6,708 bytes and CCM 7,456/8,192
bytes. `cmd_modern` remains at 200 bytes static stack below its 450-byte shell
working area. The complete Clang `-Oz`/GNU hybrid draft links at 200,396 bytes.
The unaffected F072 target also links at 110,668 bytes in its 116 KiB
application region. Final ZS407 sizes and hashes come only from the clean
committed two-build manifest.

## Closure result

The disposition checker currently reports 140 rows: 24 implemented, 20
experimental, 3 host-only, 85 specified, 1 directly hardware-blocked candidate
and 7 avoided. “Specified” is intentionally the largest group: hardware
qualification, full legacy refactoring and new-board development cannot be
truthfully converted into implemented features by compiling more code.

The complete table is [ENHANCEMENT_DISPOSITION.md](../ENHANCEMENT_DISPOSITION.md).
The coherent successor design is [HARDWARE_V2.md](../HARDWARE_V2.md).

## Exit state

Phase 6 establishes source completeness, host correctness, compile/link
confidence, reproducible artifacts, ancestry and output-lock confidence. It
does not establish measurement accuracy, generator spectrum, analog bandwidth,
thermal behavior or flash safety on the user's ZS407. Every image remains
**NOT HARDWARE QUALIFIED**.
