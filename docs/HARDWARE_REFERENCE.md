# tinySA Ultra+ ZS407 hardware reference

This is the working hardware reference for the **tinySA Ultra+ ZS407**. It is
deliberately confidence-graded: source code can reveal the hardware contract,
but it cannot prove which markings or substitutions are present in one Amazon
unit. The physical inventory remains gated on non-destructive inspection.

## Evidence vocabulary

| Label | Meaning |
| --- | --- |
| **Confirmed in build** | Required by the pinned F303 firmware or linker. |
| **Official product statement** | Described by tinySA or a component vendor. |
| **Strong inference** | Multiple independent source paths agree, but the board has not been inspected. |
| **Open** | Must be checked on the PhysicistJohn unit. |

The unit is user-identified as `tinySA Ultra+ ZS407`. Its rear label, runtime
identity, PCB revision, and component markings have not yet been captured.

## Architectural conclusion

The ZS407 is a **swept heterodyne spectrum analyzer**, not a wideband sampled-I/Q
analyzer. Its normal acquisition result is a tuned-channel power reading. The
firmware changes LO and receiver settings for a frequency point, waits for the
RF path to settle, and reads one byte of RSSI from the Si4468-class receiver.

```text
                                      +--------------------------+
                                      | MAX2871-class swept LO   |
                                      +------------+-------------+
                                                   |
RF SMA -> LNA or step attenuator -> path switch -> mixer
                                                   |
                                      high-IF filter / routing
                                                   |
                                      +------------v-------------+
                                      | Si4468 receiver          |
                                      | low IF + RBW + detector  |
                                      +------------+-------------+
                                                   |
                                            8-bit RSSI over SPI
                                                   |
                                      +------------v-------------+
                                      | STM32F303CC              |
                                      | sweep, math, UI, USB     |
                                      +------+-----------+-------+
                                             |           |
                                      ST7796S LCD      microSD/USB
```

The [official Ultra technical description](https://tinysa.org/wiki/pmwiki.php?n=TinySA4.TechnicalDescription)
describes the generic chain as LNA/attenuator, optional 800 MHz low-pass path,
swept LO and mixer, a nominal 980 MHz high IF, then an RX that downconverts to
about 870 kHz, applies 200 Hz–800 kHz resolution filters, and detects power.
The current ZS407 source differs in one important detail: hardware IDs with
`hw_if == 1` use `DEFAULT_IF_PLUS`, **1.0701 GHz**, rather than the older
`DEFAULT_IF` of 977.4 MHz. This needs bench confirmation; it may describe the
ZS406/ZS407 filter revision or an intentional receiver over-range operating
point.

### What this means for DSP

- An FFT cannot synthesize instantaneous RF bandwidth that was never sampled.
- An FFT across zero-span RSSI samples can analyze **envelope/modulation versus
  time**, but has no RF phase or quadrature information.
- An FFT across an already swept trace can support convolution, deconvolution,
  resampling, or feature extraction; it is not a replacement for the sweep.
- True wideband RF FFT operation would require an accessible analog IF or
  digital I/Q/sample stream. Neither is exposed by the current firmware, and
  the public Si4468 interface documents demodulated data/FIFO and RSSI rather
  than host-accessible I/Q samples.

The [Si4468 data sheet](https://www.silabs.com/documents/public/data-sheets/Si4468-7.pdf)
does show an internal low-IF, delta-sigma ADC and DSP. It says the demodulated
signal is delivered through GPIO or the RX FIFO and specifies RSSI at 0.5 dB
resolution. That makes an undocumented/test-pad sample route worth
investigating, but it is not a firmware assumption we can safely make.

## Identity and runtime variants

One F303 image supports several Ultra-family boards. `get_hw_version_text()`
stabilizes ADC channel 0 and compares it with a table:

| ADC code | Source identity | `hwid` | `hw_if` | Runtime effect |
| ---: | --- | ---: | ---: | --- |
| 165–179 | V0.4.5.1 ZS405 | 1 | 0 | older IF/range path |
| 180–195 | V0.4.5.1.1 ZS405 | 2 | 0 | alternate LCD revision |
| 250–350 | V0.4.6 ZS406 | 3 | 1 | 900 MHz normal range, plus IF |
| 2200–2299 | **V0.5.4 ZS407** | **103** | **1** | MAX2871 and ZS407 tables |

For `hwid >= 100`, startup sets `max2871 = true`, loads the ZS407 correction
tables, selects a 900 MHz normal-mode ceiling, and derives the Ultra range from
a 6.3 GHz LO boundary plus first IF. The shell `version` command is expected to
include `V0.5.4` and `max2871`.

There is a documentation discrepancy worth preserving. The
[official specification](https://tinysa.org/wiki/pmwiki.php?n=TinySA4.Specification)
says V0.5.3 was the first ZS407, while the current source table reports V0.5.4.
The device response and PCB marking decide what this particular unit is.

## Component and subsystem inventory

| Subsystem | Working identification | Evidence and consequence | Confidence |
| --- | --- | --- | --- |
| MCU | STM32F303xC, expected STM32F303CC | F303 target, device header and 256 KiB/48 KiB memory model agree. Cortex-M4F with DSP instructions and FPv4-SP. | Confirmed in build; package marking open |
| Swept LO | MAX2871-class on ZS407 | Runtime ID 103 enables `max2871`; 6.3 GHz firmware LO boundary. ADI specifies 23.5 MHz–6.0 GHz nominal synthesis, fast-lock features and a four-wire serial interface. | Strong inference |
| IF receiver/detector | Si4468-class | `__SI4468__`; configurable 200 Hz–850 kHz firmware RBW tables; `GET_MODEM_STATUS` current RSSI read. | Strong inference |
| Reference/aux clock | Si5351-family support | `__SI5351__` and I2C driver are built. The Si5351 is an I2C programmable multi-output clock generator. Runtime availability is probed. | Strong inference; exact variant open |
| Input attenuator | PE4302-compatible 6-bit DSA | `__PE4302__`; official Ultra path says 0–31 dB. The PE4302 specification is 0.5 dB steps through 31.5 dB, DC–4 GHz. Firmware presents 1 dB user steps. | Strong inference; marking open |
| LNA | ZK10D, reported as U12 for ZS407 | The official tinySA FAQ distinguishes this from the ZS405/406 BGA2817. | Official product statement; marking open |
| Input RF switch | XA17-G4K, reported as U22 | Official tinySA FAQ; manufacturer describes a GaAs SPDT nominally covering 20 MHz–4 GHz. | Official product statement; marking open |
| Display | ST7796S-compatible, 480×320 RGB565 | `LCD_DRIVER_ST7796S`, dimensions and init sequence are compiled. | Confirmed in build; panel marking open |
| Input | Four-wire resistive touch and three-state jog/push control | ADC/GPIO paths and official specification agree. | Confirmed in build |
| Storage | microSD over shared SPI1, FatFs | SD support, browser, screenshot and firmware-dump paths are compiled. | Confirmed in build |
| USB | STM32 USB FS CDC ACM; DFU in ROM | Firmware VID/PID is 0483:5740 for the serial interface; ROM DFU recovery is used. | Confirmed in build; descriptors pending unit |
| UART | Optional TTL USART | PA9/PA10 alternate function and official specification. | Confirmed interface; header population open |
| Audio codec | TLV320AIC3204 support source | Driver and I2S code exist, but `__AUDIO__` is disabled and codec init is omitted in this build. TI specifies stereo ADC/DAC and up to 192 ksample/s. Physical population/routing is unknown. | Open |
| Audio/listen output | MCU DAC-based RSSI audio path | `__LISTEN__` is enabled and writes shaped RSSI to DAC channel 1. This is not an I/Q sample path. | Confirmed in build |

Primary component references:

- [STM32F303CC product page and data sheet](https://www.st.com/en/microcontrollers-microprocessors/stm32f303cc.html)
- [STM32F303 reference manual RM0316](https://www.st.com/resource/en/reference_manual/dm00043574.pdf)
- [MAX2871 data sheet](https://www.analog.com/media/en/technical-documentation/data-sheets/MAX2871.pdf)
- [Si4468/7 data sheet](https://www.silabs.com/documents/public/data-sheets/Si4468-7.pdf)
- [Si5351 data sheet](https://www.skyworksinc.com/-/media/Skyworks/SL/documents/public/data-sheets/Si5351-B.pdf)
- [PE4302 data sheet](https://www.psemi.com/wp-content/uploads/pdf/obs/pe4302ds.pdf)
- [TLV320AIC3204 product page](https://www.ti.com/product/TLV320AIC3204)
- [XA17-G4K manufacturer page](https://xinluda.com/en/RF-switch/20240718152.html)
- [tinySA FAQ with ZS407 service component identities](https://tinysa.org/wiki/pmwiki.php?n=Main.FAQ)

## Acquisition data path in source

The source-level path is unambiguous:

1. `perform()` selects the signal path and computes the LO/IF plan.
2. The MAX2871/ADF-compatible synthesizer and Si4468 receiver are retuned as
   needed.
3. Explicit microsecond delays account for PLL, offset and RSSI settling.
4. `Si446x_readRSSI()` issues `GET_MODEM_STATUS` and takes `CURR_RSSI`.
5. `Si446x_RSSI()` repeats/averages as configured.
6. Frequency correction, path loss, temperature, attenuation, LNA and unit
   transforms are applied.
7. Up to 450 points are placed into trace/measurement arrays and plotted.

The raw device sample is `uint8_t`; the intermediate fixed-point RSSI type is
`int16_t`. Device RSSI is shifted by four bits and the firmware's internal
power unit is 1/32 dB. The Si4468 vendor resolution is 0.5 dB, so the extra
fractional bits are for correction/averaging arithmetic, not additional raw
detector resolution.

Fast zero-span mode pre-fills the same 450-byte `age[]` array by repeatedly
reading RSSI. Trigger modes keep a circular RSSI history. No active code fills
an RF ADC, I/Q, or audio-codec sample buffer for spectrum processing.

There is a disabled `adc_buf_read()` experiment and disabled fixed/floating FFT
code. The STM32 ADC's active uses are board identity, battery/reference
measurement and touch. Treat the disabled ADC experiment as archaeology, not
evidence that RF is wired to an MCU ADC pin.

Key source anchors in the pinned tree:

- [feature flags and enabled hardware paths](../nanovna.h#L38)
- [ZS407 ADC identity table](../main.c#L2278)
- [ZS407/MAX2871 capability selection](../main.c#L3238)
- [per-frequency RF plan and acquisition](../sa_core.c#L3640)
- [Si4468 current-RSSI read](../si4468.c#L1861)
- [fast zero-span RSSI fill](../si4468.c#L2000)
- [display dimensions and tile-buffer contract](../nanovna.h#L1024)
- [dirty-cell renderer](../plot.c#L1069)
- [F303 clock configuration](../NANOVNA_STM32_F303/mcuconf.h#L42)
- [flash/SRAM/CCM linker declaration](../STM32F303xC.ld#L20)

## MCU, clocks and memory

The [STM32F303CC](https://www.st.com/en/microcontrollers-microprocessors/stm32f303cc.html)
supports a 72 MHz Cortex-M4F, DSP instructions, up to 40 KiB ordinary SRAM and
8 KiB CCM SRAM. This firmware does **not** use the maximum clock:

| Clock/domain | Current configuration |
| --- | ---: |
| HSI | 8 MHz internal RC |
| PLL input | HSI / 2 |
| PLL multiplier | ×12 |
| SYSCLK/HCLK | **48 MHz** |
| APB1 | 24 MHz |
| APB2 | 48 MHz |
| ADC12 | 24 MHz |
| GPT delay timer | 8 MHz (1/8 µs tick) |
| USB | 48 MHz |

The source can trim HSI to move the MCU clock around 48 MHz when a processor
clock harmonic would create an RF spur. A simple move to 72 MHz is therefore an
RF change, not merely a free 50% CPU upgrade.

### Linker map and headroom

```text
0x08000000 .. 0x0803bfff  240 KiB application image
0x0803c000 .. 0x0803ffff   16 KiB calibration storage
0x20000000 .. 0x20009fff   40 KiB ordinary SRAM
0x10000000 .. 0x10001fff    8 KiB CCM SRAM
```

The exact official binary is 185,704 bytes. Its ordinary SRAM allocation has
28,200 bytes of BSS, 3,764 bytes of initialized data, 1,664 bytes of fixed
stacks and a 7,328-byte remainder exposed as the linker heap.

The 8 KiB CCM region exists in the linker memory declaration but no sections
are assigned to it today. RM0316 states that CCM is CPU-only and **cannot be
accessed by DMA**. It is attractive for FFT scratch, scalar trace math, lookup
state or critical CPU code; it cannot hold an LCD/SD/ADC DMA buffer.

## Display pipeline

The panel contract is 480×320 at 16-bit RGB565. A full framebuffer would need
307,200 bytes, over six times all MCU RAM, so the firmware already uses the
right broad strategy:

- 32×32-pixel render cells;
- two 2,048-byte cell buffers inside one 4,096-byte SPI buffer;
- two dirty-cell maps;
- CPU rendering into one tile while DMA transmits the other;
- trace-coordinate caches so only intersecting cells are redrawn.

SPI1 is shared by LCD and microSD. The ST7796S path selects `SPI_BR_DIV2`; with
the current 48 MHz APB2 clock, the expected display serial clock is 24 MHz.
A full-screen RGB565 transfer therefore has a theoretical wire-time floor of
102.4 ms, before address commands and rendering. The absolute full-frame
ceiling is about 9.8 frames/s; responsive UI depends on dirty regions and
partial updates.

## Constraints that firmware cannot optimize away

1. **PLL/filter/RSSI settling dominates many sweeps.** Instruction scheduling
   does not remove analog settling time.
2. **The detector discards phase.** RSSI cannot recover I/Q later.
3. **The display is serial and has no usable full framebuffer.** Retained tiles
   are mandatory.
4. **Ordinary RAM is already tightly allocated.** New static buffers need
   reuse, CCM placement or a reduced feature footprint.
5. **The MCU clock is part of RF behavior.** Clock changes can move spurs and
   alter USB/timer/peripheral assumptions.
6. **The RF chain exceeds some individual component nominal ranges by mixing,
   bypass and harmonic techniques.** A component data-sheet ceiling is not the
   same thing as the instrument input ceiling.

## Physical confirmation checklist

No shield or enclosure should be opened until exterior characterization and
recovery are complete. When inspection is authorized, capture:

- front/rear labels, serial markings and PCB revision;
- shell `version`, `info`, `status` and USB descriptors;
- MCU top marking and package;
- MAX2871/compatible LO marking;
- Si4468/compatible RX marking;
- Si5351 variant and reference oscillator markings;
- U12 LNA and U22 input-switch markings;
- attenuator marking;
- display flex/controller identifiers;
- populated/unpopulated TLV320 codec and I2S/test pads;
- high-IF and receiver/test pads without probing them electrically yet;
- shield layout and both PCB faces at macro resolution.

Then use non-invasive measurements to settle the open questions:

1. Logic-analyze LCD SPI and confirm 24 MHz plus cell transfer timing.
2. Capture MAX2871 and Si4468 control transactions during a tiny sweep.
3. Measure actual point time versus RBW, step size and frequency region.
4. Observe whether the ZS407 first-IF programming is 1.0701 GHz in practice.
5. Identify any analog low-IF/audio/test node and its bandwidth/loading.
6. Determine whether any receiver GPIO exposes useful raw demodulated data.
7. Measure current draw, battery behavior and thermal drift at stock settings.

Until those checks are complete, references to exact populated components are
working hypotheses, and all LLVM-produced images remain **do-not-flash**.
