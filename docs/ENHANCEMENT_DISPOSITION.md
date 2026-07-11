# Final enhancement dispositions

This is the Phase 6 closure record for every candidate in
[ENHANCEMENT_RISK_REGISTER.md](ENHANCEMENT_RISK_REGISTER.md). A disposition
describes the state of the cumulative no-flash image and its host tools; it is
not a claim of hardware qualification.

- `implemented`: present in the cumulative source/image and covered by a
  relevant automated check.
- `experimental`: implemented behind a refusal/read-only/dry-run boundary and
  awaiting hardware evidence.
- `host-only`: intentionally belongs in the Mac companion or build tools.
- `specified`: architecture and acceptance boundary exist, but execution is not
  in the Phase 6 image.
- `blocked-hardware`: the current ZS407 signal path or wiring cannot support it.
- `avoided`: explicitly rejected for this firmware because risk exceeds value.

`tools/audit-enhancement-dispositions.py` compares this document with the risk
register by exact name, ID, order, allowed state and total row count. Adding or
renaming a candidate without closing its disposition fails the host suite.

## Build, architecture and macOS development

| ID | Enhancement | Disposition | Evidence and boundary |
| --- | --- | --- | --- |
| E001 | Preserve the byte-exact GNU macOS build | implemented | Pinned source, ChibiOS and Arm GNU reproduce the 185,704-byte official binary exactly. |
| E002 | Hybrid LLVM/GNU build | experimental | Every cumulative phase links with selected Clang objects; all images remain no-flash. |
| E003 | Per-module `-Oz`/`-O2` profiles | specified | Optimization matrix exists; named production profiles need cycle and hardware evidence. |
| E004 | Isolated `-Ofast` DSP kernels | specified | Allowed only for bounded kernels after numerical and cycle acceptance tests. |
| E005 | Modern CMSIS compiler support | specified | Current hybrid uses a documented parser workaround while RTOS and FPU context remain GNU-owned. |
| E006 | Split the hard-fault assembly veneer from the C reporter | implemented | Phase 1 has an MSP/PSP-aware assembly veneer and ordinary non-returning C reporter. |
| E007 | Split direct `.c` inclusion into translation units | specified | Portable modules are split; the legacy main translation unit still includes RF source directly. |
| E008 | Portable analyzer core compiled natively on macOS | implemented | Allocation-free C11 core runs under Apple Clang and cross-compiles freestanding for Cortex-M4. |
| E009 | ASan, UBSan, fuzzing and property tests | implemented | UBSan and property/fuzz suites run; ASan always links and is opt-in where the Apple runtime is stable. |
| E010 | Recorded-trace replay | specified | Protocol fixture replay exists; calibrated trace fixtures require captures from the physical unit. |
| E011 | Python/NumPy/CMSIS-DSP design path | specified | Python generators and C numerical oracles exist; NumPy/CMSIS comparisons are future algorithm gates. |
| E012 | Generated C/TypeScript protocol codecs | implemented | One JSON contract deterministically generates C, TypeScript and Swift projections. |
| E013 | WASM build of the portable core | specified | Stable C ABI exists; 64-bit boundary tests and an Atomizer consumer are still required. |
| E014 | Isolated Rust `no_std` modules | specified | Reserved for a parser or sequencer only after C ABI and flash-cost proof. |
| E015 | Whole-firmware Rust rewrite | avoided | A big-bang rewrite has no near-term analyzer benefit and too much RF regression surface. |
| E016 | LLD/LTO/full LLVM link | avoided | Startup, RTOS, exception and RF timing remain on the proven GNU boundary for this hardware. |
| E017 | Upgrade or replace ChibiOS | avoided | Deferred beyond ZS407 modernization because it adds timing risk without reducing analog settling. |
| E018 | Remove heap use from real-time paths | specified | New core paths allocate nothing; legacy heap and shared-buffer use still require instrumentation. |

## Timing correctness and reliability

| ID | Enhancement | Disposition | Evidence and boundary |
| --- | --- | --- | --- |
| E019 | Logic-analyzer timing inventory | specified | Capture points and acceptance matrix exist; measurements need the unit and passive probes. |
| E020 | DWT cycle-counter instrumentation | implemented | Scheduler, RF probe and modern diagnostics expose DWT cycle measurements. |
| E021 | GPIO or DAC timing pulses | specified | Probe design is documented but not enabled because digital edges may contaminate RF results. |
| E022 | Standards-compliant flash wait state | implemented | Every phase image uses one wait state at the 48 MHz HCLK profile. |
| E023 | Standards-compliant Si4468 SPI profile | implemented | Phase images cap the Si4468 bus at 6 MHz pending measured margin. |
| E024 | Standards-compliant MAX2871 SPI profile | implemented | Phase images cap MAX2871 SPI at 12 MHz pending measured margin. |
| E025 | Qualified aggressive clock profile | specified | Stock-fast clocks remain available only in byte-exact compatibility builds, not a qualified phase profile. |
| E026 | Boot-time Si4468 part, ROM and patch inventory | specified | A read-only shell query reports all fields; automatic boot policy awaits actual unit inventory. |
| E027 | Hardware capability structure | implemented | Source-derived, restricted-by-default capabilities cover ZS407 identity and range/path features. |
| E028 | Firmware image CRC and build identity | specified | Reproducible version, commit and external hashes exist; self-CRC needs a post-link signed-image format. |
| E029 | Persisted-configuration schema and CRC | specified | Migration must wrap legacy settings without ever erasing calibration implicitly. |
| E030 | Watchdog and structured fault record | specified | Hard-fault reporting exists; watchdog policy and persistent fault journal need hardware timing tests. |
| E031 | Output-state interlock | specified | The new DAC backend fails closed, but a single interlock does not yet own every legacy RF output path. |
| E032 | Independent experimental feature flags | implemented | Phase, RF-lab and waveform gates isolate cumulative code and leave execution disabled by default. |
| E033 | Automated hardware-in-loop regression | specified | Test matrix and evidence format exist; fixture, reference instruments and captured baselines are pending. |

## Sweep and analyzer performance

| ID | Enhancement | Disposition | Evidence and boundary |
| --- | --- | --- | --- |
| E034 | Precompile the complete RF plan | specified | Exact frequency planning is portable; full per-point register transactions are not integrated. |
| E035 | Rational/DDA frequency accumulator | implemented | Exhaustive 2 through 511 point comparison matches legacy nearest rounding. |
| E036 | Cache complete synthesizer and receiver state | specified | Dirty masks and settle classes are tested models; legacy drivers do not skip writes yet. |
| E037 | Cursor-based correction interpolation | implemented | Allocation-free monotonic correction cursor has boundary and interpolation tests. |
| E038 | Move invariant formatting and conversion out of the point loop | specified | Replacement architecture assigns this ownership; legacy loop refactor awaits timing captures. |
| E039 | RF-priority SPI1 scheduler | specified | Deterministic scheduler model exists; live SPI1 arbitration is hardware-sensitive and not installed. |
| E040 | Bounded display DMA chunks during acquisition | specified | UI model supports dirty work units; LCD DMA chunk policy needs bus captures. |
| E041 | Buffer SD logging between sweeps | specified | Ownership and loss policy are documented; no new logging executor is active. |
| E042 | Si4468 FRR RSSI reads | experimental | Read-only FRR mapping/value probe is linked; the acquisition fast path is forced off. |
| E043 | Configure `MODEM_FAST_RSSI_DELAY` | experimental | Current property is read and timed; no property write is allowed. |
| E044 | Si4468 RSSI averaging controls | specified | Requires per-RBW noise, timing and calibration measurements before any property change. |
| E045 | Manual Si4468 `RX_HOP` | experimental | Source-equivalent dry-run words and VCO estimate compile; radio execution is disabled. |
| E046 | Manual Si4468 `TX_HOP` | experimental | Shared hop planner exists; TX execution and transient qualification do not. |
| E047 | Si4468 automatic 64-channel hopping | avoided | Packet-oriented behavior does not map cleanly to honest bin acquisition on this analyzer. |
| E048 | Extend small-step frequency-offset tuning | specified | Range, stale-state and linearity gates are documented but need captures. |
| E049 | MAX2871 manual VCO lookup | experimental | Divider/register planning is live as dry-run output; VCO calibration/readback is unqualified. |
| E050 | MAX2871 lock-detect-driven settling | specified | Depends on confirming MUX/LD board routing and lock validity. |
| E051 | Qualify the MAX2871 fast-lock topology | specified | Requires physical loop-filter/SW inspection and settling measurements. |
| E052 | Qualify cycle-slip reduction | specified | Charge-pump, phase-noise and lock-time effects require a spectrum analyzer campaign. |
| E053 | Schedule CPU work during analog settling | specified | Only safe after GPIO/cycle correlation proves digital work does not create RF spurs. |
| E054 | Selective spur verification | specified | Selection and validity rules exist; live acquisition integration needs repeatable signals. |
| E055 | Coarse-first progressive survey | specified | Progressive UI semantics exist; no unmeasured point is currently synthesized into a live trace. |
| E056 | Focused rescans around peaks | experimental | Host-tested window selection and live dry-run reporting exist; rescans are not executed. |
| E057 | Dynamic attenuation pre-ranging | specified | Needs overload observability and discontinuity calibration before changing the live path. |
| E058 | Multi-pass range stitching | specified | Requires time-aligned captures and cross-range calibration. |
| E059 | Timestamped uniform zero-span capture | specified | Uniformity and independent RSSI update timing must first be measured. |
| E060 | Long segmented sweeps streamed to Mac | specified | Protocol framing exists; flow control and sweep-coherence behavior are pending. |
| E061 | 1,024-point on-device single-trace mode | specified | Point planner supports it conceptually; RAM, UI and proportional retune cost remain open. |
| E062 | 72 MHz MCU profile | specified | Legal for the MCU but coupled to USB, flash, timers, SPI and RF-spur behavior. |
| E063 | Overclock beyond 72 MHz | avoided | It exceeds the device rating with no defensible analyzer benefit. |

## Memory and embedded DSP

| ID | Enhancement | Disposition | Evidence and boundary |
| --- | --- | --- | --- |
| E064 | Store traces as signed dB x32 `int16_t` | experimental | Metrics use a fixed-point trace scratch; legacy display/measurement storage remains floating point. |
| E065 | Compact fixed-point correction tables | specified | Quantization/error budgets must be proven against saved calibration tables. |
| E066 | Allocate DSP scratch in the 8 KiB CCM | implemented | 7,456 bytes hold frequency, trace, sort and 512-point FFT scratch; DMA SRAM is untouched. |
| E067 | Place selected hot code in CCM | specified | Only after cycle evidence justifies displacing scarce DSP data. |
| E068 | Explicit buffer ownership | specified | New modules have explicit scratch contracts; the whole legacy image still aliases large buffers. |
| E069 | Q15 windows, FIRs and FFTs | experimental | Saturating 256/512-point Q15 FFT is tested; live windows/FIR acquisition are pending. |
| E070 | Q31/scaled integer linear power | implemented | Derived power uses bounded fixed/scaled integer accumulation with host oracles. |
| E071 | Cortex-M4 `SMLAD` kernels | specified | Portable reference kernels come first; packed-instruction versions need alignment and cycle proof. |
| E072 | `SSAT`/`USAT` narrowing | specified | Defined C saturation is present; instruction-specific lowering is not yet a required ABI. |
| E073 | `CLZ` plus LUT logarithm | specified | Current log conversion is qualified for correctness, not replaced by an approximation. |
| E074 | Fixed-size CMSIS-DSP linkage | specified | Custom fixed-size FFT avoids table bloat; modern CMSIS integration remains a later option. |
| E075 | 512-point zero-span FFT | experimental | Transform passes impulse, cardinal and off-bin tests; uniform zero-span samples are not yet available. |
| E076 | 1,024-point zero-span FFT | specified | Current CCM budget and capture path do not support it without a new ownership profile. |
| E077 | Swept-trace FFT/correlation | specified | Allowed only with labeling that it analyzes an already swept sequence, not RF I/Q. |
| E078 | RBW-kernel deconvolution | host-only | Kept off-device where regularization, diagnostics and original-data comparison are practical. |
| E079 | Goertzel detector | specified | Efficient after a uniform timestamped envelope stream is proven. |
| E080 | Autocorrelation/period estimator | specified | Same uniform-sampling and aliasing gates as envelope FFT work. |

## Measurement quality and derived values

| ID | Enhancement | Disposition | Evidence and boundary |
| --- | --- | --- | --- |
| E081 | Linear-domain channel-power integration | implemented | Fixed-point summary converts dB bins to linear power and applies bin/ENBW correction. |
| E082 | Occupied bandwidth | implemented | Configurable power quantile returns occupied start/stop bins with validity flags. |
| E083 | Adjacent/alternate-channel power | specified | Needs window definitions, detector semantics and synchronized sweep data. |
| E084 | Spectral-mask testing | specified | Mask schema and uncertainty policy belong after calibrated per-bin validity. |
| E085 | Robust noise-floor histogram/quantiles | implemented | Allocation-free quantile estimator is tested and used by live metrics/refinement dry runs. |
| E086 | Peak prominence and width | experimental | Prominence drives refinement windows; calibrated width semantics remain pending. |
| E087 | Parabolic marker interpolation | implemented | Saturating Q15 sub-bin interpolation covers flat, boundary and asymmetric cases. |
| E088 | Persistent peak tracking | specified | Association and reset rules are not yet part of measurement state. |
| E089 | Sweep min/max/variance | specified | Needs bounded storage and explicit reset/time-window semantics. |
| E090 | Harmonic table with confidence flags | specified | Must distinguish internal conversion products using path-aware validation. |
| E091 | Burst duration and duty cycle | specified | Requires uniform zero-span timestamps and measured RSSI attack/decay. |
| E092 | Qualified VBW FIR/IIR filters | specified | Coefficients, transient preservation and detector semantics need separate acceptance tests. |
| E093 | Median/outlier filtering | specified | Disabled until short legitimate signals can be distinguished from glitches. |
| E094 | Explicit detector semantics | specified | Existing detector modes need a versioned metadata mapping and standards caveats. |
| E095 | Per-path/RBW/frequency calibration surfaces | specified | Architecture exists; coefficients require a traceable automated calibration campaign. |
| E096 | Level-dependent calibration | specified | Requires reference sweeps through compression and noise over all paths. |
| E097 | Temperature-dependent calibration | specified | Requires multiple physical sensors or a validated relationship to component temperature. |
| E098 | Measured RBW impulse response and ENBW | specified | Integrated-power accuracy remains conditional on hardware measurements. |
| E099 | Overload/saturation detection | specified | No trusted analog-chain overload indicator has yet been characterized. |
| E100 | Per-bin validity metadata | specified | Summary flags exist; a compact protocol/display representation for each bin is pending. |
| E101 | Measurement uncertainty estimate | specified | Needs calibration, repeatability, fixture and detector error components from hardware. |
| E102 | Host-side heavy FFT/deconvolution/ML | host-only | Intentionally uses the Mac while preserving the sampled-information limits of swept RSSI. |

## Display and interaction

| ID | Enhancement | Disposition | Evidence and boundary |
| --- | --- | --- | --- |
| E103 | Immutable UI snapshots | implemented | Portable snapshot object separates measurement values from renderer mutation. |
| E104 | Retain double-buffered 32x32 dirty tiles | implemented | Existing efficient tile/DMA design is preserved and modeled rather than replaced by a framebuffer. |
| E105 | Semantic dirty regions | implemented | Portable dirty model maps semantic changes to bounded tile sets with host tests. |
| E106 | RF-priority display scheduling | specified | Requires live SPI arbiter and acquisition latency captures. |
| E107 | Progressive trace drawing | experimental | Snapshot validity/count semantics exist; live renderer integration awaits hardware timing. |
| E108 | Min/max envelope per screen column | implemented | Host-tested envelope preserves narrow extrema during downsampling. |
| E109 | ST7796S vertical-scroll waterfall | specified | Landscape address mapping and controller variant must be read back on hardware. |
| E110 | Ring-buffer waterfall data | specified | Needs timestamp, RBW/path and color-scale metadata plus a memory profile. |
| E111 | Modern analyzer-style UI | experimental | Atomic palette and state model compile; a complete replacement screen is not enabled. |
| E112 | Prepacked fonts and icons | specified | Assets must fit the remaining flash budget and support the final layout. |
| E113 | Tabular large numeric font | specified | Design exists in the Atomic UI plan; embedded asset and renderer are pending. |
| E114 | Better jog/touch value editor | specified | Interaction contract needs testing on the resistive panel and lever. |
| E115 | Sparse deadline-aware animation | specified | Only after RF/display deadlines are measured and scheduled. |
| E116 | Display-controller readback/detection | specified | Read transactions are hardware-dependent and share the RF SPI bus. |

## Signal generator and waveform work

| ID | Enhancement | Disposition | Evidence and boundary |
| --- | --- | --- | --- |
| E117 | Deterministic waveform event sequencer | specified | Fixed event ABI and fail-closed validator exist; no embedded event executor is linked. |
| E118 | Mac waveform DSL/compiler | host-only | Deterministic compiler, CRC format, unsafe-program rejection and golden hash are tested. |
| E119 | USB/SD waveform upload | specified | Versioned file format exists; transport, storage and execution ownership do not. |
| E120 | Triggered/repeated sequences | specified | Trigger-wait event is validated only while gated off; runtime timing is not implemented. |
| E121 | Timer/DMA audio DAC AWG | experimental | Full TIM6, DMA2/3 and DAC1 backend links, but binary audit proves start always refuses. |
| E122 | Sine/square/triangle/noise audio modes | experimental | Q15 renderers and actual-frequency reporting are tested; physical PA4 output is locked. |
| E123 | Si4468 FIFO OOK | experimental | Bounds and symbol plan exist; no radio properties, FIFO bytes or TX state are changed. |
| E124 | Si4468 FIFO 2FSK/2GFSK | experimental | Dry-run quantization exists; modem configuration and spectrum remain unqualified. |
| E125 | Si4468 FIFO 4FSK/4GFSK | experimental | Two-bit symbol-rate planning exists; deviation mapping and RF execution are disabled. |
| E126 | Si4468 PRBS modulation | experimental | Planner recognizes PRBS; it is explicitly not represented as true broadband noise. |
| E127 | Packet/protocol generator | specified | Framing belongs above a qualified FIFO modem executor. |
| E128 | Direct OOK/2FSK through PB9/Si GPIO1 | avoided | It sacrifices CTS and conflicts with source-derived control wiring for little benefit over FIFO mode. |
| E129 | Synchronous direct GFSK | blocked-hardware | No dedicated synchronous TX clock/data pair is routed without stealing RF-control GPIOs. |
| E130 | Arbitrary PE4302 AM envelope | specified | 0.5 dB quantizer is tested; shared-SPI timing, 25 kHz limit and transients block execution. |
| E131 | Si4468 PA-level/ramp envelopes | specified | Property latency, nonlinearity and path calibration require hardware experiments. |
| E132 | Arbitrary FM deviation table | specified | Event model can carry intent; property-write timing cannot provide qualified arbitrary FM yet. |
| E133 | Native Si4468 modulation instead of SPI-stepped FM | specified | Preferred RF architecture after exact modem profile and output-path characterization. |
| E134 | Frequency-hop/dwell lists | specified | Event ABI expresses schedules; settling, gating and transient limits need an executor and captures. |
| E135 | Stepped chirps | specified | Possible only as honestly labeled non-phase-continuous PLL steps. |
| E136 | MAX2871 manual fast hopping | experimental | Register planner exists; VCO table, lock detect and transient control are disabled. |
| E137 | MAX2871 phase adjustment | avoided | Repeatability and update splatter make it a poor substitute for coherent I/Q generation. |
| E138 | Generator leveling calibration | specified | Requires a traceable power instrument, shielded load and automated frequency/level campaign. |
| E139 | Report the actual quantized waveform | implemented | DAC timer/frequency, FIFO symbol rate and PE4302 attenuation report requested versus actual values. |
| E140 | Emissions-limit warnings | specified | Needs region/profile input and cannot replace operator responsibility or measured spectral safety. |

## Hardware-blocked capabilities beyond the candidate rows

The current board also cannot provide instantaneous wideband RF FFT, coherent
receive phase, QAM/OFDM, phase-continuous arbitrary RF chirps or simultaneous
arbitrary RF multitone. Those are not deferred firmware tasks; they are inputs
to [HARDWARE_V2.md](HARDWARE_V2.md).
