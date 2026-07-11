# STM32F303 execution and I/O optimization model

This note records which desktop optimization instincts transfer to the ZS407
and which do not. The target is an STM32F303xC Cortex-M4F at 72 MHz with 40 KiB
ordinary SRAM, 8 KiB CCM and a 240 KiB application flash region.

## Memory and concurrency

| Resource | Useful property | Constraint |
|---|---|---|
| ordinary SRAM | CPU and DMA visible | shared by stacks, queues, display buffers and heap |
| CCM | low-contention CPU scratch | DMA cannot access it; only 736 bytes remain in Phase 6 |
| USB packet memory | dedicated endpoint storage | 512 bytes on F303xB/C; not a general DMA buffer |
| aligned 32-bit SRAM word | natural Cortex-M4 ownership/index unit | wire data still needs explicit byte loads |

Cortex-M4 exception entry stacks registers automatically and supports
tail-chaining, but an interrupt is not free. The floating-point context can
make it more expensive, and the USB interrupt already has priority 3. Handlers
therefore acknowledge/post the minimum state and wake a thread. Long CRCs,
parsers, rendering, formatting and RF state machines do not belong in an ISR.

The `DMB` instruction orders explicit memory accesses. The SPSC implementation
uses compiler acquire/release builtins so both GNU and LLVM select the required
barrier semantics. It does not emulate an x86 cache protocol: this M4 has no
data cache. ChibiOS locks remain appropriate for RTOS objects and shared
peripherals.

Unaligned accesses are slower and can fault for several instructions. Protocol
code never dereferences packed integer pointers. DMA buffers stay in ordinary
SRAM; CPU-only FFT/sweep scratch can use CCM.

Primary references:

- [ST PM0214 Cortex-M4 programming manual](https://www.st.com/resource/en/programming_manual/dm00046982-stm32-cortex-m4-mcus-and-mpus-programming-manual-stmicroelectronics.pdf)
- [STM32F303xB/C data sheet](https://www.st.com/resource/en/datasheet/stm32f303vc.pdf)
- [ST AN4832 migration tables, including F303 USB packet memory](https://www.st.com/resource/en/application_note/an4832-migrating-from-stm32f303-line-to-stm32l4-series-and-stm32l4-series-microcontrollers-stmicroelectronics.pdf)

## Current USB path

The board exposes one USB full-speed CDC ACM interface with 64-byte bulk
endpoint packets. ChibiOS allocates two 256-byte receive and two 256-byte
transmit buffers. Endpoint callbacks run in interrupt context and only move
queue ownership/start the next transaction. The legacy shell then calls
`streamRead(..., 1)` for every character.

Protocol v2 consumes complete ChibiOS buffers in a worker. Adding MCU DMA is
not an optimization here: this USB peripheral transfers through its dedicated
packet memory and interrupt machinery. The gains come from fewer RTOS calls,
fewer copies, incremental parsing and binary payloads.

## SPI1 and the hardware shift registers

SPI1 is shared by the LCD/SD path and the RF devices. LCD transmit uses DMA1
channel 3; LCD receive uses channel 2. Those are also the STM32F303 SPI1 TX/RX
DMA channels, so an RF DMA experiment must first introduce an owner-aware bus
arbiter. Starting a second transfer behind the display would corrupt both
devices.

The RF code already uses the STM32 SPI shift register in hardware mode:

- Si4468 commands are streamed as bytes through `SPI1->DR`;
- MAX2871 registers are four MSB-first bytes with a latch edge;
- PE4302 attenuation is sent as one byte and then latched.

The remaining `shiftOut` name does not imply that the active build bit-bangs
every transaction. The software loop is a fallback. More useful work is to
batch register bytes, reduce repeated mode/baud changes, and schedule bus
ownership around LCD DMA.

Device limits matter:

| Device | Interface fact | Current safe profile |
|---|---|---:|
| Si4468 | 4-wire SPI, maximum 10 MHz | 6 MHz |
| MAX2871 | 32-bit MSB-first register, 50 ns minimum clock period | 12 MHz |
| PE4302 | 6-bit shift register, maximum 10 MHz, latch timing requirements | 6 MHz |

References:

- [Si4468/7 data sheet](https://www.silabs.com/documents/public/data-sheets/Si4468-7.pdf)
- [Si4x6x programming guide AN633](https://www.silabs.com/documents/public/application-notes/AN633.pdf)
- [MAX2871 data sheet](https://www.analog.com/media/en/technical-documentation/data-sheets/MAX2871.pdf)
- [PE4302 data sheet](https://www.psemi.com/wp-content/uploads/pdf/obs/pe4302ds.pdf)

## Where interrupts and DMA help

| Path | Preferred mechanism | Reason |
|---|---|---|
| 1–16 byte RF command | polled FIFO/shift register under bus ownership | interrupt or DMA setup can cost more than the transfer |
| 32-bit MAX2871 write | prepacked bytes, short polled burst, explicit latch | deterministic edge timing; no response data |
| one PE4302 code | one hardware-SPI write and latch | already near the minimum operation count |
| Si4468 command completion | GPIO CTS or `nIRQ`, then thread/state-machine continuation | removes tight SPI polling and frees CPU during radio MCU work |
| Si4468 fast status/RSSI | fast-response-register read | avoids full command/CTS/response cycles |
| 32–64 byte Si4468 FIFO | measured FIFO or DMA burst after bus arbitration | setup can amortize; FIFO thresholds provide natural interrupts |
| LCD cells | existing double-buffered DMA | CPU renders the next cell while SPI shifts the current one |
| USB frames | existing ISR buffer queue plus worker | USB packet RAM is not ordinary SPI-style DMA |

Silicon Labs documents three ways to observe command completion: SPI CTS
polling, a GPIO CTS signal, or the `CHIP_READY` interrupt on `nIRQ`. It also
defines fast-response registers and FIFO almost-full/almost-empty interrupts.
Those are the correct async primitives for a later RF release.

## Cortex-M4 bit and DSP opportunities

Useful instructions/intrinsics include byte reversal for prepacked register
words, `CLZ` for normalization, signed saturation for Q15/dB pipelines, and
dual 16-bit multiply/accumulate for FFT/window kernels. Their value depends on
the generated code: every candidate needs an ARM disassembly and DWT cycle
comparison against portable C.

GPIO set/reset should use the STM32 atomic BSRR register rather than a
read-modify-write sequence. Bit-band aliases can provide atomic single-bit CPU
access in the supported regions, but they do not solve DMA ownership and are
not a substitute for a bus state machine. Protocol queues use aligned indices
instead of bit-band flags.

## RF optimization release gate

The next RF-bus release should be observational first:

1. add a single SPI1 owner/transaction descriptor used by display, storage and
   RF code;
2. record DWT cycles, byte counts, wait time and mode changes without changing
   radio output;
3. precompute the next Si4468/MAX2871 transaction during ADC/settle time;
4. compare polling, interrupt and DMA thresholds on hardware;
5. enable GPIO CTS/`nIRQ` only after logic-analyzer traces prove polarity,
   clearing and timeout behavior;
6. qualify FRR RSSI/status against the existing command path;
7. change one active path per release and retain an immediate fallback.

No v0.2 code changes RF bus timing or output. This separation prevents a USB
marshalling improvement from being confounded with spectral or settling
changes.
