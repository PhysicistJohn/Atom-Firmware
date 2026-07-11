# Hardware v2: coherent analyzer and true RF AWG

Firmware can make the ZS407 faster, safer and much richer, but its swept RSSI
receiver cannot become an instantaneous coherent analyzer and its PLL/modem
outputs cannot become a true arbitrary RF waveform generator. This document is
the concrete replacement-hardware contract for those capabilities.

It is a feasibility architecture, not a finished schematic or promised
instrument specification. RF dynamic range, phase noise, isolation, thermal
behavior, battery life, layout, shielding and manufacturability require
simulation and measured prototypes.

## Recommended product tiers

| Tier | Architecture | Honest capability | Cost/complexity |
| --- | --- | --- | --- |
| V2A coherent handheld | 30 MHz–6 GHz direct-conversion I/Q transceiver, FPGA and real-time MCU | Up to 40 MHz instantaneous receive/transmit bandwidth, coherent measurements and true I/Q waveform playback | High but buildable from vendor reference designs |
| V2B microwave extender | V2A plus switched 6–12 GHz mixer/preselector and microwave LO | Swept/stitchable coherent analysis and translated AWG above 6 GHz | Very high RF/layout/calibration burden |
| V2C direct-RF instrument | Multi-GSPS RF ADC/DAC, JESD204 and large FPGA/SoC | Hundreds of MHz to GHz instantaneous bandwidth | Bench-instrument power, thermal and budget class; not the first handheld |

V2A is the recommended target. V2B should be a shielded daughtercard after the
baseband/RF platform works. V2C is a separate project, not feature creep.

## V2A reference architecture

```text
 RF IN
   |
 protection -> 0.5 dB DSA -> switchable LNA -> preselector/filter bank
   |                                                   |
 overload envelope detector                            |
   |                                                   v
   +-------------------------------------------> 2x2 coherent RF transceiver
                                                        | RX I/Q   ^ TX I/Q
                                                        v          |
                                               source-synchronous FPGA
                                          DDC/PFB/FFT, triggers, DMA, replay
                                                   |             |
                                           256 MiB sample RAM    hard mute
                                                   |             |
                                                   +------v------+
                                                          |
                                              real-time control/UI MCU
                                         protocol, calibration, display, files
                                              |        |         |
                                         USB3/2.5GbE  SD/eMMC  800x480 LCD

 common low-jitter reference -> RF transceiver, FPGA timebase, trigger/PPS
 RF OUT <- detector <- output DSA <- filters <- fail-safe switch <- TX path
```

### Coherent RF conversion

The reference transceiver is the
[Analog Devices ADRV9002](https://www.analog.com/en/products/adrv9002.html).
ADI currently marks it recommended for new designs and specifies two receive
and two transmit channels, 30 MHz–6 GHz tuning, 12 kHz–40 MHz signal bandwidth,
two integrated fractional-N synthesizers, fast hopping, and CMOS or LVDS
synchronous serial sample interfaces. It is expensive and layout-intensive,
but it replaces several speculative custom blocks with a supported coherent
signal chain and published reference designs.

Use the two channels deliberately:

- RX1 is the calibrated measurement path.
- RX2 can monitor a coupled generator sample, diversity input or reference
  channel for transfer-function/phase measurements.
- TX1 is the user RF output.
- TX2 can drive a calibration/reference path or differential experiment, but
  must not silently energize an external connector.

The transceiver's digital corrections help, but do not eliminate instrument
calibration. Front-end attenuator/LNA/filter gain, connector response, mixer
paths, image response, compression and temperature still need traceable
surfaces.

### Low-frequency path below 30 MHz

Do not fake coverage below the transceiver limit with extrapolated calibration.
Add a switched direct-sampling path with these minimum requirements:

- DC block bypass option where safe;
- at least 14 effective converter bits at low input frequencies;
- at least 80 MSPS for a 30 MHz alias-protected band;
- differential driver, programmable gain/attenuation and anti-alias filters;
- synchronous clocking into the same FPGA/timestamp domain;
- a matching dual-DAC or numerically controlled low-frequency generator path.

The [AD9253](https://www.analog.com/en/products/ad9253.html), a current
14-bit 80/105/125 MSPS converter family, is a capability reference rather than
a selected BOM part. One or two channels are sufficient; part choice should be
revisited against power, interface, availability and measured ENOB when the
schematic begins.

### Deterministic FPGA plane

An FPGA owns every sample deadline. The
[Lattice ECP5/ECP5-5G](https://www.latticesemi.com/products/fpgaandcpld/ecp5)
family is a plausible cost/power starting point because it combines embedded
RAM, DSP blocks and up-to-5-Gbit/s SERDES. Resource closure must be proven with
the exact transceiver interface, memory controller, PFB/FFT sizes and transport
before selecting a density.

The FPGA is responsible for:

- source-synchronous RX/TX framing and deterministic timestamps;
- numerically controlled oscillators, DDC/DUC, decimation/interpolation and
  channel filters;
- windowing and a polyphase filter bank for honest wideband spectra;
- fixed-size streaming FFT engines and block-floating scaling metadata;
- pretrigger/posttrigger ring buffers and loss counters;
- min/max/average/peak-hold reductions for the display;
- arbitrary I/Q playback with underrun-to-mute behavior;
- a hardware output-enable state machine independent of MCU software;
- CRC-protected descriptors between the sample plane and control plane.

The MCU never services a per-sample interrupt. It submits bounded descriptors
and consumes complete blocks.

### Control and UI processor

The recommended control processor class is the
[NXP i.MX RT1170](https://www.nxp.com/products/i.MX-RT1170): up to a 1 GHz
Cortex-M7, a 400 MHz Cortex-M4, and up to 2 MiB of on-chip SRAM, with external
SDRAM, SD/eMMC and serial-memory interfaces. M7 owns the UI, files, networking
and derived measurements; M4 owns deterministic control, interlocks and slow
peripherals. The FPGA still owns sample timing.

An [STM32H7R7/H7S7](https://www.st.com/en/microcontrollers-microprocessors/stm32h7r7-7s7.html)
at up to 600 MHz with 620 KiB SRAM, TFT-LCD support and external-memory
interfaces is a credible single-core alternative if staying close to the
current ecosystem matters more than the RT1170's memory and second core.

Neither choice should bit-bang RF data. Select after testing external-memory,
display, FPGA-control and recovery paths on evaluation boards.

### Memory and transport budget

At 61.44 MSPS, one complex channel represented as signed 16-bit I and Q is
245.76 MB/s; two channels are 491.52 MB/s. Therefore:

- 256 MiB stores about 1.09 seconds of one channel or 0.55 seconds of two,
  before descriptor/alignment overhead;
- USB 2.0 and 1 GbE cannot continuously carry both raw channels;
- full-rate capture needs local RAM plus triggered blocks, decimation, or a
  USB 3.x/2.5GbE-class transport;
- SD is for reduced traces and finite captures, not lossless continuous raw IQ;
- every stream reports dropped blocks rather than silently stretching time.

Use ECC/parity where practical for descriptors and calibration. Sample RAM can
be ordinary DDR/LPDDR with end-to-end block CRC and overwrite counters.

### FFT and analyzer performance targets

At a 61.44 MSPS complex sample rate:

| FFT size | Record time | Raw bin spacing | Primary use |
| ---: | ---: | ---: | --- |
| 4,096 | 66.7 us | 15 kHz | fast live spectrum and triggering |
| 65,536 | 1.067 ms | 937.5 Hz | detailed live analysis |
| 1,048,576 | 17.07 ms | 58.6 Hz | finite capture/offline fine resolution |

Displayed resolution is not simply bin spacing. Every result also carries
window, equivalent noise bandwidth, overlap, detector, averaging, gain/path,
calibration revision and validity. Wider spans are stitched from overlapped
coherent blocks; overlap regions quantify mismatch rather than hiding seams.

### True arbitrary waveform generation

V2A stores or streams signed I/Q samples and uses FPGA interpolation/DUC into
the transceiver. This enables QAM, OFDM, arbitrary multitone, shaped pulses,
phase-continuous chirps and calibrated modulation within the qualified sample
rate and analog bandwidth.

Required safety behavior is implemented in hardware:

1. RF output switch and PA enable default physically off at reset/brownout.
2. FPGA requires a CRC-valid descriptor, bounded frequency/level/rate and a
   short renewable enable lease.
3. Underrun, clock loss, PLL unlock, thermal fault or MCU heartbeat loss mutes
   before reconfiguration.
4. MCU UI always shows requested and measured output state; detector feedback
   can disagree and force mute.
5. Calibration and regulatory warnings never override the hard maximum-power
   table.
6. First tests use a shielded 50-ohm load, external attenuation and an
   independent analyzer—never an antenna.

## V2B 6–12 GHz extender

Above 6 GHz, add a switched fundamental-mixer path rather than claiming direct
transceiver coverage. The
[HMC773/HMC773LC3B](https://www.analog.com/en/products/hmc773.html) is a useful
architecture reference: a passive 6–26 GHz double-balanced mixer with DC–8 GHz
IF. The [ADF4371](https://www.analog.com/en/products/adf4371.html) is a reference
LO class with 62.5 MHz–32 GHz outputs and explicit hardware/software mute.

The actual extender needs:

- switched 6–8, 8–10 and 10–12 GHz preselectors/image filters;
- enough LO range to place the selected RF block inside a qualified ADRV9002
  band without ambiguous images;
- independent LO leakage, image, conversion-loss and compression calibration;
- lock detect and a hardware mute held through every retune;
- a directional sample or detector on the generated high-band output;
- shielding partitioned from the 30 MHz–6 GHz direct path.

An optional broadband detector such as the
[ADL6010](https://www.analog.com/en/products/adl6010.html)—specified over
0.5–43.5 GHz with 40 MHz envelope bandwidth—can provide overload protection,
triggering and output monitoring. It is not a coherent measurement channel and
cannot replace I/Q data.

V2B can translate arbitrary I/Q bandwidth through a mixer, but absolute phase
across retunes and bands requires common-reference design and calibration. It
must report when a result is stitched rather than instantaneous.

## Clock, trigger and calibration architecture

- One low-phase-noise 10 MHz TCXO/OCXO reference feeds a jitter cleaner/clock
  tree for transceiver, FPGA timebase, ADC/DAC and microwave LO.
- Accept and generate 10 MHz reference plus PPS/trigger with protection and
  selectable 50-ohm termination.
- A 64-bit FPGA sample counter is the canonical time; MCU time is presentation
  metadata only.
- Factory/user calibration lives in a separately versioned, CRC-protected and
  recoverable partition. Firmware updates never erase it implicitly.
- Include an internal coupled loopback, known noise/source path if affordable,
  temperature sensors near RF gain/LO blocks and detector telemetry.
- Calibration records component serial/board revision, reference instrument,
  uncertainty, temperature, path, bandwidth and software schema.

## Bus and PCB partitioning

The ZS407's shared SPI1 is a central performance limit. Hardware v2 separates:

| Domain | Required connection |
| --- | --- |
| RF control | Dedicated SPI buses or FPGA chip-select scheduler with bounded latency |
| Sample data | Source-synchronous parallel/LVDS directly between transceiver and FPGA |
| Sample memory | Dedicated wide DDR interface owned by FPGA |
| Display | LTDC/RGB or high-speed dedicated display bus, never shared with RF |
| Storage | SD/eMMC bus with DMA and bounded queues |
| Host stream | USB 3.x or at least 2.5GbE-class path from FPGA/bridge |
| Safety | Independent mute, detector, PLL-lock and fault GPIOs |

Use separate RF/digital power trees, sequenced rails, low-noise regulators for
references/PLLs, controlled-impedance stackup, via-fenced shields and explicit
return-current planning. Vendor evaluation-board layout is the starting point,
not permission to improvise a two-layer prototype.

## Software contract reused from this repository

The portable Phase 1–6 work survives the hardware change:

- generated protocol schema and strict frame parser;
- requested-versus-actual frequency/rate/level reporting;
- fixed-point measurement semantics and host numerical oracles;
- immutable UI snapshots and min/max display envelopes;
- deterministic waveform event compiler;
- capability/safety manifest and fail-closed feature negotiation;
- reproducible build/artifact provenance.

Add a sample-block descriptor with at least:

```text
magic, schema, stream_id, sequence, first_sample_timestamp
center_frequency_hz, sample_rate_hz, bandwidth_hz
path_id, gain_db32, reference_level_db32, temperature_mC
sample_format, channel_mask, sample_count, validity_flags
calibration_revision, payload_crc32, header_crc32
```

The host refuses unknown sample formats or missing validity fields. No UI layer
infers instantaneous bandwidth from a swept trace.

## Bring-up sequence and exit gates

1. **Digital prototype:** MCU, FPGA, external RAM, display and host streaming;
   PRBS memory tests and loss-accounted synthetic I/Q only.
2. **Transceiver evaluation:** vendor radio card plus FPGA reference HDL;
   receive and transmit digital loopbacks before custom RF layout.
3. **Low-band custom board:** protected direct path, one RX/TX connector and
   hardware mute; characterize into fixtures.
4. **Analyzer front end:** attenuator, LNA, filters, overload detector and
   calibration loopback with compression/noise/spur measurements.
5. **Generator:** shielded load only; verify mute at reset, underrun, fault,
   retune and cable disconnect before enabling arbitrary playback.
6. **Microwave extender:** separate board and calibration campaign after V2A
   meets all coherent specifications.
7. **Portable integration:** battery/thermal/display enclosure only after RF
   performance is stable on bench supplies.

No phase exits on “it displays a spectrum.” Required evidence includes clock
phase noise, amplitude/phase flatness, SFDR, noise figure, P1dB, image rejection,
LO leakage, output harmonics, transient spectrum, trigger latency/jitter,
sample-loss accounting, thermal drift, battery noise, recovery and fault mute.

## Decision

For this ZS407 repository, instantaneous wideband FFT and arbitrary RF I/Q are
`blocked-hardware`. The best current-board work remains deterministic swept-RSSI
acquisition, honest derived measurements, a better UI, structured Si4468
modulation and a low-frequency DAC AWG. Hardware v2 should start with a coherent
40 MHz transceiver plus FPGA—not with a faster MCU pretending RSSI is I/Q.
