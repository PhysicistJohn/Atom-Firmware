# ZS407 enhancement and risk register

This is the working inventory of credible firmware, analyzer, UI, DSP and
generator improvements for the tinySA Ultra+ ZS407. It records opportunity and
risk separately so novelty does not outrank measurement integrity.

The register is based on:

- the byte-exact official GNU build and the non-flashing LLVM/GNU experiment;
- source-derived MCU pin, shared-bus and RF-path behavior;
- the STM32F303, Si4468, MAX2871, PE4302 and ST7796S documentation;
- the architecture, performance and embedded-UI investigations in this fork.

It is a candidate backlog, not a promise that every item belongs in a release.
Hardware-dependent work remains gated by the stock baseline, DFU recovery and
physical regression process in [HARDWARE_BRINGUP.md](HARDWARE_BRINGUP.md).

## Rating system

Risk is the combined engineering and instrument-validity risk of a first
prototype:

| Rating | Meaning |
| --- | --- |
| Low | Host-testable or localized; unlikely to change RF behavior. |
| Medium | Changes embedded timing, memory or behavior; hardware regression is required. |
| High | Changes RF tuning, clocks, switching or measurement semantics; can create spurs, false readings, lock failures or unintended output. |
| Very high | Exceeds a documented device limit or creates broad, hard-to-contain failure modes. |
| Blocked | The existing ZS407 lacks the required signal path or connection. |

Priority indicates ordering, not desirability:

| Priority | Meaning |
| --- | --- |
| P0 | Establish truth, safety or a prerequisite first. |
| P1 | First low-risk implementation tranche. |
| P2 | Implement after baseline and targeted hardware characterization. |
| P3 | Stretch work after the analyzer is qualified. |
| Research | Preserve as an experiment; do not schedule as product behavior yet. |
| Avoid | Poor value/risk tradeoff on the current hardware. |

## Build, architecture and macOS development

| Enhancement | Expected benefit | Risk | Principal risk or limit | Priority |
| --- | --- | --- | --- | --- |
| Preserve the byte-exact GNU macOS build | Permanent known-good baseline | Low | Keep source, submodule, tools and libraries pinned | P0, done |
| Hybrid LLVM/GNU build | Modern diagnostics and smaller selected modules | Medium | ABI, FPU context and unqualified hardware behavior | P0, build proven only |
| Per-module `-Oz`/`-O2` profiles | Save flash while accelerating measured kernels | Medium | Compiler transformations in timing-sensitive code | P1 |
| Isolated `-Ofast` DSP kernels | Faster qualified CMSIS-DSP operations | Medium-High | Fast-math changes rounding, NaN and associativity behavior | P2 |
| Modern CMSIS compiler support | Correct Clang and hard-float integration | Medium | Old ChibiOS/CMSIS assumptions | P1 |
| Split the hard-fault assembly veneer from the C reporter | Correct Clang compatibility and better diagnostics | Low-Medium | Exception stack and MSP/PSP handling | P1 |
| Split direct `.c` inclusion into translation units | Cleaner compiler boundaries and testing | Medium | Hidden static/global coupling | P1 |
| Portable analyzer core compiled natively on macOS | Fast tests for planning, calibration, metrics and DSP | Low | Preserve exact embedded numeric behavior | P0 |
| ASan, UBSan, fuzzing and property tests | Find overflows, parser bugs and invalid states | Low | Host/device type and ABI differences | P0 |
| Recorded-trace replay | Reproduce real behavior without hardware for every run | Low | Fixtures must retain RBW, path, detector and timing metadata | P0 |
| Python/NumPy/CMSIS-DSP design path | Rapid algorithms with a double-precision oracle | Low | Quantization must be explicitly tested | P1 |
| Generated C/TypeScript protocol codecs | Prevent Atomizer/firmware protocol drift | Low | Schema migration and versioning | P1 |
| WASM build of the portable core | Reuse exact algorithms in Atomizer and simulators | Low-Medium | Fixed-point and 64-bit behavior at the JS boundary | P2 |
| Isolated Rust `no_std` modules | Memory-safe parsers or sequence components | Medium | C ABI, panic behavior and flash growth | P3 |
| Whole-firmware Rust rewrite | Little near-term analyzer benefit | High | Large RF-behavior regression surface | Avoid |
| LLD/LTO/full LLVM link | Possible size and cross-module gains | High | Startup, ChibiOS assembly, newlib and exception ABI | P3 |
| Upgrade or replace ChibiOS | Long-term maintainability | High | Does not reduce analog settling and can disturb timing | P3 |
| Remove heap use from real-time paths | Deterministic memory and timing | Low-Medium | Existing implicit buffer reuse | P1 |

## Timing correctness and reliability

| Enhancement | Expected benefit | Risk | Principal risk or limit | Priority |
| --- | --- | --- | --- | --- |
| Logic-analyzer timing inventory | Establish actual SPI, CTS, settle and sweep timing | Low | Probe loading or injected digital noise | P0 |
| DWT cycle-counter instrumentation | Accurate CPU-region profiling | Low | Counter overflow and instrumentation overhead | P0 |
| GPIO or DAC timing pulses | Correlate firmware events with RF behavior | Medium | Edge activity can contaminate RF measurements | P0 |
| Standards-compliant flash wait state | Reliable voltage/temperature operation | Medium | May be slower than the stock zero-wait-state setting | P0 |
| Standards-compliant Si4468 SPI profile | Remove the nominal 12 MHz versus 10 MHz overclock | Medium | Slight transaction-time increase | P0 |
| Standards-compliant MAX2871 SPI profile | Remove the nominal 24 MHz versus 20 MHz overclock | Medium | Slight register-write increase | P0 |
| Qualified aggressive clock profile | Retain stock-like speed where margin is demonstrated | High | Unit, voltage, temperature and silicon variation | P3 |
| Boot-time Si4468 part, ROM and patch inventory | Select revision-correct behavior | Low | Robust command error handling | P0 |
| Hardware capability structure | Safely distinguish ZS407 and component variants | Low | Clones or substitutions may identify inconsistently | P1 |
| Firmware image CRC and build identity | Detect corrupt or mismatched images | Low | Boot and release integration | P1 |
| Persisted-configuration schema and CRC | Safe settings evolution | Low-Medium | Never erase calibration implicitly | P1 |
| Watchdog and structured fault record | Recover from deadlocks and retain evidence | Medium | Legitimate long calibration must service the watchdog | P1 |
| Output-state interlock | Prevent unintended RF after faults or mode changes | Medium | Safe defaults must preserve intended generator use | P1 |
| Independent experimental feature flags | Isolate FRR, hopping, LLVM and clock experiments | Low | Configuration complexity | P0 |
| Automated hardware-in-loop regression | Catch RF, sweep, UI and generator regressions | Low-Medium | Needs reference fixtures and instruments | P0-P1 |

## Sweep and analyzer performance

| Enhancement | Expected benefit | Risk | Principal risk or limit | Priority |
| --- | --- | --- | --- | --- |
| Precompile the complete RF plan | Remove repeated decisions and divisions from the point loop | Low-Medium | Correct plan invalidation | P1 |
| Rational/DDA frequency accumulator | Replace repeated 64-bit division with add/carry | Medium | Exact rounding and band boundaries | P1 |
| Cache complete synthesizer and receiver state | Avoid redundant register writes | Medium | Missing a required retrigger or calibration | P1 |
| Cursor-based correction interpolation | Faster table lookup | Low | Segment-boundary correctness | P1 |
| Move invariant formatting and conversion out of the point loop | Reduce CPU work and jitter | Low | State invalidation | P1 |
| RF-priority SPI1 scheduler | Prevent display and SD activity delaying RF commands | Medium | DMA completion and safe mode transitions | P1 |
| Bounded display DMA chunks during acquisition | Reduce worst-case RF bus blocking | Medium | More command overhead and possible tearing | P1 |
| Buffer SD logging between sweeps | Prevent block I/O disrupting acquisition | Low-Medium | Data loss on sudden power removal | P1 |
| Si4468 FRR RSSI reads | Remove command/CTS response overhead | Medium-High | Fresh-sample and latch semantics vary by RBW | P1 experimental |
| Configure `MODEM_FAST_RSSI_DELAY` | Deterministic fresh RSSI after a hop | High | Too short gives invalid amplitude; too long loses speed | P1 experimental |
| Si4468 RSSI averaging controls | Lower random uncertainty | Medium-High | Changes detector timing and calibration | P2 |
| Manual Si4468 `RX_HOP` | Major receiver-retune reduction | High | VCO count, silicon patch and band-boundary correctness | P2 |
| Manual Si4468 `TX_HOP` | Faster generator hopping | High | Phase discontinuity and output transients | P3 |
| Si4468 automatic 64-channel hopping | Hardware-assisted surveys | High | Packet-oriented stop conditions do not naturally record every bin | Research |
| Extend small-step frequency-offset tuning | Faster narrow-span sweeps | Medium | Offset range, linearity and stale state | P1 |
| MAX2871 manual VCO lookup | Datasheet indicates about 200 us typical retune saving | High | Requires MUX/readback wiring and a per-device table | P2 |
| MAX2871 lock-detect-driven settling | Stop waiting as soon as valid lock is reached | High | LD wiring and validity after VCO selection | P2 |
| Qualify the MAX2871 fast-lock topology | Potentially shorter settling | High | Requires the physical SW/loop-filter network | P2 |
| Qualify cycle-slip reduction | Improve large frequency jumps | High | Charge-pump and phase-noise consequences | P2 |
| Schedule CPU work during analog settling | Hide planning and metric latency | Medium-High | Digital activity may create RF spurs | P2 |
| Selective spur verification | Avoid automatically doubling the entire sweep | Medium | Do not misclassify real narrow or intermittent signals | P1 |
| Coarse-first progressive survey | Much faster first useful result | Medium | Mark measured, aggregated and interpolated data honestly | P1 |
| Focused rescans around peaks | Better local resolution without a full slow sweep | Medium | Transients may disappear between passes | P2 |
| Dynamic attenuation pre-ranging | Avoid overload while preserving weak signals | High | Attenuator discontinuities and missed bursts | P2 |
| Multi-pass range stitching | Extend useful dynamic range | High | Time alignment and cross-range calibration | P3 |
| Timestamped uniform zero-span capture | Defensible modulation sample rate and FFT axis | Medium | RSSI updates may not be uniformly independent | P1 |
| Long segmented sweeps streamed to Mac | Essentially unlimited host-side point count | Medium | USB backpressure and sweep coherence | P1 |
| 1,024-point on-device single-trace mode | Higher stored resolution | Medium | Retune time scales approximately with points | P2 |
| 72 MHz MCU profile | Up to 50% more CPU clock, but much less total sweep gain | High | Flash waits, USB, timers, RF spurs and SPI divisors | P3 |
| Overclock beyond 72 MHz | No defensible analyzer benefit | Very high | MCU reliability and pervasive timing errors | Avoid |

## Memory and embedded DSP

| Enhancement | Expected benefit | Risk | Principal risk or limit | Priority |
| --- | --- | --- | --- | --- |
| Store traces as signed dB x32 `int16_t` | Save about 3.6 KiB | Medium | Conversion boundaries and existing float consumers | P1 |
| Compact fixed-point correction tables | Further flash/SRAM savings | Medium | Calibration precision and interpolation error | P2 |
| Allocate DSP scratch in the 8 KiB CCM | Fast 512/1,024-point kernels | Medium | DMA cannot access CCM | P1 |
| Place selected hot code in CCM | Recover speed with compliant flash latency | Medium | Competes with DSP scratch space | P2 |
| Explicit buffer ownership | Eliminate LCD/DSP/SD aliasing hazards | Low-Medium | Current code intentionally reuses buffers | P1 |
| Q15 windows, FIRs and FFTs | Faster and smaller DSP | Medium | Scaling, saturation and noise-floor error | P1-P2 |
| Q31/scaled integer linear power | Accurate integration without float-heavy loops | Medium | Accumulator bounds and log conversion | P1 |
| Cortex-M4 `SMLAD` kernels | Faster FIR, window and dot products | Medium | Alignment and accumulator overflow | P2 |
| `SSAT`/`USAT` narrowing | Defined saturation instead of C overflow | Low | Must match intended detector behavior | P1 |
| `CLZ` plus LUT logarithm | Fast power-to-dB conversion | Medium | Full-range approximation error | P2 |
| Fixed-size CMSIS-DSP linkage | Optimized FFT without every table | Low-Medium | Only retain qualified transform sizes | P1 |
| 512-point zero-span FFT | Envelope and modulation analysis | Medium | This is not RF I/Q; sample timing must be proven | P2 |
| 1,024-point zero-span FFT | Better temporal-frequency resolution | Medium | Longer record and CCM pressure | P2 |
| Swept-trace FFT/correlation | Spur-pattern and feature detection | Medium | Never present it as instantaneous RF bandwidth | P3 |
| RBW-kernel deconvolution | Potentially sharpen repeatable swept features | High | Noise amplification and misleading resolution | Research |
| Goertzel detector | Efficient measurement of a few envelope tones | Low-Medium | Requires uniform temporal sampling | P2 |
| Autocorrelation/period estimator | Burst and periodic-envelope analysis | Medium | Aliasing and nonuniform sampling | P2 |

## Measurement quality and derived values

| Enhancement | Expected benefit | Risk | Principal risk or limit | Priority |
| --- | --- | --- | --- | --- |
| Linear-domain channel-power integration | Defensible channel power | Medium | Accurate ENBW and bin-width correction | P1 |
| Occupied bandwidth | Modern analyzer measurement | Medium | Detector and RBW semantics must be explicit | P1 |
| Adjacent/alternate-channel power | Useful transmitter evaluation | Medium | Sweep synchronization and integration windows | P2 |
| Spectral-mask testing | Automated pass/fail assessment | Medium | Calibration uncertainty and detector choice | P2 |
| Robust noise-floor histogram/quantiles | Stable low-cost noise estimate | Low-Medium | Exclude signals from the floor population | P1 |
| Peak prominence and width | Better signal discrimination | Low-Medium | RBW broadening and close signals | P1 |
| Parabolic marker interpolation | Sub-bin peak estimate | Low-Medium | Invalid for asymmetric or clipped peaks | P1 |
| Persistent peak tracking | Follow drifting and intermittent signals | Low | Association across changing spans and RBWs | P1 |
| Sweep min/max/variance | Reveal intermittent emissions | Low | Memory and reset semantics | P1 |
| Harmonic table with confidence flags | Rapid transmitter characterization | Medium | Internal products can imitate harmonics | P2 |
| Burst duration and duty cycle | Better zero-span measurements | Medium | RSSI detector attack and decay limits | P2 |
| Qualified VBW FIR/IIR filters | Predictable smoothing | Medium | Preserve narrow transient peaks appropriately | P1 |
| Median/outlier filtering | Reject isolated glitches | Medium | Can erase legitimate short events | P2 |
| Explicit detector semantics | Peak, average, quasi-peak and min/max behavior | Medium | Standards require exact time constants | P2 |
| Per-path/RBW/frequency calibration surfaces | Major amplitude-accuracy improvement | High | Large measurement campaign and interpolation design | P2 |
| Level-dependent calibration | Correct compression and nonlinearity | High | Requires a traceable source over wide dynamic range | P3 |
| Temperature-dependent calibration | Better stability | Medium-High | Radio sensor temperature is not every component temperature | P2 |
| Measured RBW impulse response and ENBW | More accurate integrated power | Medium | Requires an automated reference fixture | P1 |
| Overload/saturation detection | Prevent plausible-looking invalid readings | Medium | Need observable analog-chain indicators | P1 |
| Per-bin validity metadata | Honest display and host analysis | Low-Medium | Expands trace and protocol structures | P1 |
| Measurement uncertainty estimate | Distinguish display resolution from accuracy | Medium | Combine calibration, detector, RBW and range errors | P2 |
| Host-side heavy FFT/deconvolution/ML | Analyses impossible on the MCU | Low | Never infer information the device did not sample | P2 |

## Display and interaction

| Enhancement | Expected benefit | Risk | Principal risk or limit | Priority |
| --- | --- | --- | --- | --- |
| Immutable UI snapshots | Decouple RF state from rendering | Medium | Additional state ownership discipline | P1 |
| Retain double-buffered 32x32 dirty tiles | Efficient local redraws | Low | SPI ownership during DMA | P1 |
| Semantic dirty regions | Avoid unnecessary invalidation | Low-Medium | Correctly erase old geometry | P1 |
| RF-priority display scheduling | Prevent UI work slowing sweeps | Medium | Variable perceived frame rate | P1 |
| Progressive trace drawing | Results appear during acquisition | Medium | Do not imply unmeasured points | P1 |
| Min/max envelope per screen column | Preserve narrow peaks when downsampling | Low-Medium | Aggregate correctly across RBW/path changes | P1 |
| ST7796S vertical-scroll waterfall | Transmit one new row instead of shifting a region | Medium-High | Landscape orientation mapping requires testing | P2 |
| Ring-buffer waterfall data | Long history with bounded memory | Low-Medium | Timestamps and color-scale changes | P1 |
| Modern analyzer-style UI | Clearer status, measurements and generator state | Low-Medium | Flash budget and touch target size | P1 |
| Prepacked fonts and icons | Faster, consistent rendering | Low | Flash budget | P1 |
| Tabular large numeric font | Faster reading of frequency and level | Low | Asset size | P1 |
| Better jog/touch value editor | Faster operation without tiny keyboards | Low | Changed interaction habits | P1 |
| Sparse deadline-aware animation | Better feedback without constant redraw | Low-Medium | Avoid continuous bus and CPU load | P2 |
| Display-controller readback/detection | Adapt to panel variants | Medium | Reads are slower and share SPI1 | P2 |

## Signal generator and waveform work

| Enhancement | Expected benefit | Risk | Principal risk or limit | Priority |
| --- | --- | --- | --- | --- |
| Deterministic waveform event sequencer | Unified frequency, level, gate and phase schedules | Medium | Deadlines and shared-SPI serialization | P1 |
| Mac waveform DSL/compiler | Convert requested waveforms into legal device events | Low | Quantization model must match firmware | P1 |
| USB/SD waveform upload | Long reusable sequences | Medium | Buffer underrun and protocol versioning | P1 |
| Triggered/repeated sequences | Test bursts and synchronized measurements | Medium | Trigger latency and jitter | P2 |
| Timer/DMA audio DAC AWG | True arbitrary low-frequency analog output | Medium | Headphone bandwidth, loading and reconstruction | P1 |
| Sine/square/triangle/noise audio modes | Useful bench source from the existing DAC | Low-Medium | DAC offset and output buffering | P1 |
| Si4468 FIFO OOK | Repeatable pulse and data RF patterns | Medium-High | Switching spectrum and RF-path bandwidth | P1 experimental |
| Si4468 FIFO 2FSK/2GFSK | Clean hardware-timed digital modulation | Medium-High | Generated configuration and path calibration | P2 |
| Si4468 FIFO 4FSK/4GFSK | Four-level symbol generation | High | Deviation mapping and path linearity | P2 |
| Si4468 PRBS modulation | BER and receiver stress testing | Medium-High | Not equivalent to true broadband noise | P2 |
| Packet/protocol generator | Telemetry, RTTY, pager and custom framing tests | Medium | Exact framing and controlled RF emissions | P2 |
| Direct OOK/2FSK through PB9/Si GPIO1 | Stream patterns without FIFO-length limits | High | Sacrifices hardware CTS and needs precise timer/pin control | P3 |
| Synchronous direct GFSK | Stream shaped modulation | High or blocked | Needs another usable TX clock connection | Research |
| Arbitrary PE4302 AM envelope | Uploaded amplitude patterns | Medium-High | 0.5 dB quantization, 25 kHz limit and switching transients | P2 |
| Si4468 PA-level/ramp envelopes | Potentially smoother local RF gating | High | PA nonlinearity and command latency | Research |
| Arbitrary FM deviation table | More than sine FM and CTCSS | Medium-High | Property-write latency and jitter | P2 |
| Native Si4468 modulation instead of SPI-stepped FM | Cleaner and faster modulation | High | New TX configuration and RF validation | P2 |
| Frequency-hop/dwell lists | Synthesizer stimulus and channel sequences | Medium-High | PLL settling and transient emissions | P2 |
| Stepped chirps | Radar/FMCW-like experiments | High | Not phase-continuous and may have strong step sidebands | P3 |
| MAX2871 manual fast hopping | Faster high-frequency sequences | High | VCO table, lock and spectral splatter | P3 |
| MAX2871 phase adjustment | Slow PSK and narrowband polar-IQ feasibility | High | Phase repeatability, attenuation synchronization and update transients | Research |
| Generator leveling calibration | Better frequency/level/path accuracy | High | Large campaign with a reference power instrument | P2 |
| Report the actual quantized waveform | Honest frequency, level, timing and phase limits | Low-Medium | Protocol and UI work | P1 |
| Emissions-limit warnings | Warn about excessive power, band or duty settings | Medium | Jurisdiction-specific rules change | P2 |

Generator experiments start into a shielded 50-ohm load with an independent
spectrum analyzer. No antenna is used until harmonics, spurs, transient output
and fault-state muting are characterized. Loopback to an analyzer input must
include enough attenuation to prevent damage or compression.

## Source-derived wiring constraints that affect enhancements

The source is a partial functional netlist. The active F303 build establishes
the following connections or roles strongly enough to drive the architecture:

| Net or control | Source-derived role | Consequence |
| --- | --- | --- |
| PB3/PB4/PB5 | Shared SPI1 clock/MISO/MOSI for LCD, SD, Si4468, MAX2871 and PE4302 | RF, display and storage transactions serialize. |
| PB6 | MAX2871/ADF latch enable | MAX writes share SPI1 but have an independent select. |
| PB7 | Si4468 shutdown | Radio reset is directly MCU-controlled. |
| PB8 | Si4468 chip select | Radio commands share SPI1. |
| PB9 | Si4468 GPIO1 configured as CTS | It is the best candidate for experimental direct TX data, but doing so removes pin CTS. |
| PA15 | PE4302 latch enable | Arbitrary AM shares SPI1 with frequency and display traffic. |
| PA8 | External LNA control | The current 500 ms transition makes it a configuration control, not a per-point actuator. |
| PB15 | Active-low Ultra/mixer-path control | It is a direct MCU path switch. |
| Si4468 GPIO0 | Divided calibration clock and pulse control | It is not a generally free direct-modulation pin. |
| Si4468 GPIO2 | Active-low high-path switch control | The old generated GPIO2 direct-OOK profile conflicts with runtime wiring. |
| Si4468 GPIO3 | RX/output-path switch control | It is not a free modulation pin. |
| Si4468 nIRQ | Active-low direct-path switch control | Interrupt functionality is traded for RF switching. |
| PA4/DAC1 | Audio/listen analog output | Enables a genuine low-frequency AWG, not an RF I/Q AWG. |
| PA5/DAC2 | LCD brightness | Not available as a second arbitrary output without losing brightness control. |

The remaining physical questions are narrow: exact switch IC destinations,
MAX2871 MUX/LD/SW connectivity, optional codec population/routing, and exposed
test pads. Visual inspection and continuity checks complete this functional
map; they do not replace it.

## Capabilities blocked by existing hardware

| Desired enhancement | Why blocked | Required hardware | Status |
| --- | --- | --- | --- |
| Instantaneous wideband RF FFT | MCU receives RSSI rather than sampled IF/IQ | Accessible IF plus ADC, or SDR transceiver | Blocked |
| True broadband arbitrary RF waveform | No high-rate RF DAC or IQ modulator | Dual DAC plus IQ modulator, or direct-RF DAC | Blocked |
| Broadband/high-order QAM or OFDM | No continuous independently controlled complex-sample path | Coherent IQ transmitter | Blocked |
| Clean simultaneous arbitrary multitone | Current sources are PLL/modem based | RF DAC or IQ modulator | Blocked |
| Phase-coherent arbitrary chirp | PLL register stepping is not a continuous sample stream | DDS, FPGA or IQ transmitter | Blocked |
| Receive phase/vector measurements | RSSI detection discards phase | Coherent I/Q receiver | Blocked |
| Wideband demodulation | No sampled baseband/IF buffer reaches the MCU | DMA-accessible ADC or SDR IC | Blocked |
| Uninterrupted display DMA and RF SPI | All relevant devices share SPI1 | Separate display and RF buses | Hardware v2 |
| MAX manual VCO when MUX is unconnected | Register 6 cannot be read back | Route MUX/LD to MCU or a test pad | Hardware-dependent |
| Synchronous Si direct mode without a clock connection | Other Si GPIOs control RF switches | Dedicated TX-data and clock nets | Hardware-dependent |

The blocked boundary is broadband, coherent and general-purpose I/Q—not the
mathematics of quadrature modulation. Any complex envelope can be expressed as
amplitude and phase. The stock attenuation and synthesizer controls may be able
to approximate a low-symbol-rate polar signal, but that remains deferred
research until phase repeatability, command timing, synchronization, EVM and
spectral emissions are measured. See
[WAVEFORM_GENERATOR.md](WAVEFORM_GENERATOR.md) for the bounded experiment and
the distinction from a hardware-v2 I/Q transmitter.

## Recommended implementation order

1. Establish truth and safety: timing instrumentation, silicon inventory,
   compliant clocks, recovery, fault records and hardware-in-loop fixtures.
2. Take the low-risk speed wins: portable Mac core, precompiled plans, state
   caching, fixed-point traces, CCM ownership, SPI arbitration and progressive
   UI updates.
3. Characterize FRR RSSI independently for every RBW before integrating it into
   normal sweeps.
4. Attempt manual Si4468 RX hopping, then MAX2871 manual-VCO/lock experiments,
   behind independent feature flags.
5. Add measurement quality: ENBW, linear power integration, validity metadata,
   overload reporting and calibration surfaces.
6. Add generator capabilities in the order DAC AWG, Si4468 FIFO OOK, FIFO
   FSK/GFSK, then the general event sequencer.
7. Keep direct GPIO modulation, MAX phase/polar-IQ control, 72 MHz, LTO and RTOS
   changes as stretch work after the analyzer baseline is qualified.
8. Treat I/Q acquisition and true RF AWG as hardware-v2 requirements.

The best value/risk combination is not a raw CPU-clock increase. It is faster
RF commands, precompiled plans, honest adaptive scanning, reclaimed fixed-point
memory, RF-priority bus scheduling and host-assisted analysis. The best
generator path is Si4468 FIFO modulation plus a deterministic sequencer; a true
RF AWG requires new hardware.

## Related evidence

- [Hardware reference and confidence map](HARDWARE_REFERENCE.md)
- [Performance and fixed-point DSP plan](PERFORMANCE_DSP.md)
- [Replacement-firmware architecture](REPLACEMENT_FIRMWARE.md)
- [Embedded UI design](EMBEDDED_UI.md)
- [LLVM/GNU hybrid experiment](../experiments/llvm/README.md)
- [Modernization roadmap](../ROADMAP.md)
