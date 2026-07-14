# ZS407 exact executable digital twin

The digital twin executes the immutable `lab-v0.2.0-protocol` firmware image,
unchanged, on a source-derived tinySA Ultra+ ZS407 platform in Renode. It is a
binary test bench for firmware development: the CPU runs the same Cortex-M4
instructions and the firmware reaches its real ChibiOS threads, LCD driver,
touch code, storage initialization and RF control paths.

No command in this workflow flashes hardware or emits RF.

## Reproducible inputs

| Input | Pinned identity |
| --- | --- |
| Firmware source | `d12bd826555eee51505542a55fd184ade5817d58` |
| Firmware BIN | 207,812 bytes; SHA-256 `a1dbaa03978a25b2a8b2a0e85f60029a6cc736481732eff68e93362724683dd7` |
| Firmware ELF | SHA-256 `3a8732fcaac5595e8ad21fe656ecb7e7300a12a760f453c3c1c296b733f72f43` |
| Private release | `lab-v0.2.0-protocol` in `PhysicistJohn/TinySA_Firmware` |
| Renode | 1.16.1.16858, build `d66b0c2a-202602160921` |
| macOS Arm64 package | SHA-256 `99b8ae5897b8926ef179868d39a504fe5296555dc9c9b973718ddf3ab09175d9` |

`tools/fetch-digital-twin-firmware.sh` verifies both firmware hashes. If the
ignored local artifacts are absent, it downloads them from the private release
only after confirming that `gh` is authenticated as `PhysicistJohn`.
`tools/bootstrap-renode.sh` performs the equivalent pinned download and hash
check for Renode on macOS Arm64, Linux x86-64 and Linux Arm64.

The executable bridge no longer assumes that every ELF shares the baseline's
absolute SRAM layout. `zs407.resc` loads a complete symbol profile alongside
the BIN and ELF, rejecting missing, duplicate, unknown or out-of-RAM entries
before the CPU runs. The checked-in baseline profile remains the default. The
ChibiOS 21.11.5 RC1 profile was generated from ELF SHA-256
`84afdfeb83018ef5769d8d89343f1f1501a40726079e0d584d0c12e9fe0e91e7`.

Generate another profile from an F303 ELF with the pinned toolchain's `nm`:

```bash
toolchain=$(tools/bootstrap-toolchain.sh)
tools/generate-twin-symbol-profile.py \
  --elf path/to/tinySA4.elf \
  --nm "$toolchain/arm-none-eabi-nm" \
  --chibios-current-thread-offset 12 \
  --output path/to/image.symbols
```

The current-thread offset is `offsetof(os_instance_t, rlist.current)` and must
be verified from that ELF's DWARF when ChibiOS changes. A candidate scenario
sets `$bin`, `$elf` and `$symbols` before including the standard test, keeping
the fixture and assertions identical to the immutable baseline.

## Run it

The short deterministic boot check takes about 30 seconds on the M3 Pro
development machine:

```bash
tools/test-digital-twin.sh --smoke
```

The full scenario adds jog input, resistive touch and a frequency-selective RF
scene:

```bash
tools/test-digital-twin.sh --full
```

The firmware's Stage-1 self-test qualification is intentionally slower. It
runs all 14 cases against the connected CAL/RF fixture, verifies a disconnected
cable is rejected, acknowledges the real failure screen through modeled touch,
and saves the final LCD image:

```bash
tools/test-digital-twin.sh --selftest
```

The USB qualification drives the STM32 device controller from a modeled host,
enumerates CDC ACM, sends a fragmented shell command, checks suspend/wakeup and
STALL behavior, then resets and re-enumerates the device:

```bash
tools/test-digital-twin.sh --usb
```

Generated logs and screenshots are under `.artifacts/digital-twin/`. Run an
interactive Renode monitor with:

```bash
tools/run-digital-twin.sh
```

At the monitor, boot and inspect the native framebuffer:

```text
emulation RunFor "1.5"
twinStatus AssertBooted
twinStatus Report
spi1.spiFabric.lcd SaveScreenshot $CWD/.artifacts/digital-twin/manual.png
```

## Proven full-system behavior

The clean-process smoke scenario has a stable boot signature:

```text
ZS407_TWIN_BOOT=PASS
spi=1031724
pixels=511280
nonblack=6121
si4468=167
max2871=7
pe4302=3
frame=0x81328339A8AFA2B3
```

These counters distinguish a real boot from merely setting the reset vector:

- ChibiOS schedules the application and sweep threads, then legitimately
  returns to the idle thread while timed work sleeps.
- The ST7796S receives more than three full screens of RGB565 writes and the
  framebuffer contains over 6,000 non-black pixels.
- The Si4468 completes 167 initialization commands and enters RX state `0x08`.
- The MAX2871 receives seven 32-bit register latches and initially decodes to
  3 GHz.
- The PE4302 receives three latches.
- The blank 32 MiB in-memory microSD participates on the real shared SPI bus.

The full deterministic test additionally reports:

```text
ZS407_TWIN_JOG=PASS ui_mode=1
ZS407_TWIN_TOUCH=PASS pixel=200,150 raw=1723,2014
ZS407_TWIN_UI_NORMAL=PASS
ZS407_TWIN_RF_TONE=PASS samples=7323 range=108..200
```

The 450 MHz, −20 dBm scene produces a visible peak near the center of the real
analyzer display. It is not a painted test overlay: the firmware programs the
MAX2871 and Si4468 for each sweep point, reads the modeled RSSI response,
computes its trace and marker, changes its reference scale, and draws the
result through SPI/DMA.

## Modeled ZS407 hardware

| Block | Twin behavior | Evidence/source |
| --- | --- | --- |
| STM32F303xC Cortex-M4 | 48 MHz Cortex-M4, NVIC, SysTick, VTOR, bit bands, DWT | board configuration, linker map and ELF |
| Memories | 256 KiB flash, 40 KiB SRAM, 8 KiB CCM, system ROM window | linker script and STM32F303xC data |
| Factory words | deterministic UID, flash size and VREF calibration | STM32 factory register addresses used by firmware |
| RCC | enable/ready mirrors and system-clock switch status | F303 register use in ChibiOS HAL |
| DMA1/DMA2 | seven/five channels, widths, increments, circular mode, flags, IRQs and paired full-duplex peripheral requests | firmware DMA configuration and SPI readback traffic |
| ADC1 | ZS407 hardware-ID divider, battery and VREF channels | `NANOVNA_STM32_F303/adc.c` |
| ADC2/touch | four-wire X/Y measurement, watchdog, DMA and 20 Hz TIM1 trigger behavior | `ui.c`, `adc.c`, board pins |
| GPIO/EXTI | independent IDR/ODR state, modes, pulls, set-wins BSRR, BRR and grouped EXTI IRQs | board reset values, STM32 register semantics and ChibiOS EXT config |
| SPI1 | F303 data-size packing, FIFO/status and DMA traffic | HAL SPI configuration and LCD packed writes |
| Shared SPI wiring | simultaneous active-low selects/latches with broadcast MOSI | source GPIO macros and transaction code |
| ST7796S LCD | 480×320 RGB565 GRAM write/readback, windows, MADCTL, reset, D/C, display enable | LCD driver command stream and self-test readback |
| microSD | 32 MiB in-memory SPI-mode card with active-low card detect | board and FatFs wiring |
| Si4468 | command buffer, CTS/SDN, properties, states, RSSI/FRR, deterministic RF scene | `si4468.c` and Si4468 command protocol |
| MAX2871 | six 32-bit registers, frequency/output decode and LE behavior | synthesizer source and MAX2871 register format |
| PE4302 | six-bit, 0.5 dB attenuation code and LE behavior | attenuator source and PE4302 interface |
| USB FS device | F303 endpoint registers, PMA descriptors/data, IRQs, control and bulk transactions | ChibiOS STM32 USB LLD and USB 2.0 device requests |
| Jog control | active-high PA1/PA2/PA3 contacts through EXTI | `board.h` and `ui.c` |

The platform is in `digital-twin/renode/platforms/zs407.repl`; custom peripheral
models are deliberately small C# files under `digital-twin/renode/models/` so
each assumption can be audited against source or a datasheet.

## Interactive stimuli

The sweep loop can take about 623 ms, so hold a jog contact long enough for the
firmware to consume it:

```text
gpioPortA.jogPress Press
emulation RunFor "1.0"
twinStatus AssertMenuOpen
gpioPortA.jogPress Release
```

Inject a calibrated touch, inspect the coordinates consumed by the firmware,
then release it:

```text
adc2 SetTouchPixel 200 150
emulation RunFor "2.0"
twinStatus AssertTouchAccepted
adc2 ReleaseTouch
emulation RunFor "0.3"
```

Create a swept RF scene:

```text
spi1.spiFabric.receiver ClearFixedRssi
spi1.spiFabric.receiver ClearTones
spi1.spiFabric.receiver ResetRssiStatistics
spi1.spiFabric.receiver SetNoiseFloorDbm -110
spi1.spiFabric.receiver AddTone 450000000 -20 10000000
emulation RunFor "1.5"
twinStatus AssertToneObserved 150
```

For protocol and UI stress tests, force a raw Si4468 RSSI value:

```text
spi1.spiFabric.receiver SetFixedRssi 220
emulation RunFor "1.0"
spi1.spiFabric.receiver ClearFixedRssi
```

Remove and reinsert the card-detect contact with
`gpioPortB.sdCardPresent Release` and `Press`.

The CAL/RF cable is a controllable fixture. Connected mode routes the
firmware-selected 30/15 MHz references through the direct harmonic, tracking
filter, LPF/LNA and switch/attenuator paths used by Stage-1 self-test. The model
only supplies physical response; the immutable firmware still performs every
sweep and owns every pass/fail result:

```text
twinStatus SetCalibrationLoopback 1 -35.3
twinStatus RunSelfTestCase 8
emulation RunFor "5.0"
twinStatus AssertSelfTestCase 8 1
```

Disconnected mode drops the input to the modeled noise floor and exercises the
firmware's real cable-failure screen.

## What “exact” means

The twin is exact at the executable-input boundary: it runs the pinned release
BIN, uses its matching ELF only for symbols/assertion addresses, preserves the
source-derived wiring, and makes deterministic stimuli repeatable. It is also
register- or command-behavioral for every modeled device listed above.

It is not a transistor-, cycle-, or electromagnetic twin. In particular:

- RF response is a deterministic mixer/attenuator/RSSI abstraction, not a
  SPICE or field model. Phase noise, images, nonlinear compression, filter
  tolerances and calibration-unit variation still require hardware.
- USB is register- and transaction-behavioral, not an electrical PHY or an OS
  passthrough. It verifies firmware descriptors, endpoint/PMA ownership, CDC
  queues, shell traffic, suspend/wakeup, STALL and bus-reset recovery; analog
  signaling and host-controller timing still require hardware.
- The TLV320 audio path and physical speaker are not modeled.
- Flash configuration pages and the SD image are in-memory unless a future
  persistence scenario explicitly backs them with files.
- Wall-clock performance is slower than hardware because every LCD SPI byte is
  retained and audited. Virtual timing, not host time, controls the firmware.
- A passing twin test does not qualify RF behavior, recovery, calibration or a
  modified image for flashing.

## Expected Renode warnings

Renode 1.16.1 currently reports a small, stable warning set while the firmware
configures register bits that its generic STM32 peripherals do not implement:

- USART `LBDIE`, `EIE` and interrupt-clear bits;
- extended EXTI pending-register offsets;
- TIM1 master-mode-selection bit 5;
- macOS translation-cache clamping and the Cortex-M Thumb-entry normalization.

These are documented fidelity boundaries, not ignored test results. Scenario
assertions, compilation errors, unknown monitor commands/devices and missing
result markers fail `tools/test-digital-twin.sh` even when Renode itself exits
with status zero.

Those boundaries are intentional test labels, not hidden uncertainty. Hardware
bring-up remains the release gate in `docs/HARDWARE_BRINGUP.md`.

All-14 release screenshots and trace matrices are assembled and hash-bound
with the fail-closed workflow in
[`SELFTEST_VISUAL_EVIDENCE.md`](SELFTEST_VISUAL_EVIDENCE.md).

## Renode defects exposed by the twin

Six emulator discrepancies were isolated during boot, register audit and the
complete firmware self-test:

1. Renode 1.16.1 and current `renode-infrastructure` master tag
   `ICSR.RETTOBASE` instead of calculating it. ChibiOS reads that bit in
   `_port_irq_epilogue`; a permanent zero leaves a woken higher-priority thread
   READY while the idle thread continues. The local compatibility peripheral
   supplies the architected value.
2. The generic STM32 GPIO model backs IDR and ODR with one state array. The
   ZS407 board writes high reset values to ODR while PA1–PA3 remain pull-down
   inputs, making all jog contacts appear pressed. The F303 twin keeps input,
   output and external state separate.
3. The STM32 BSRR callbacks apply set before reset, so writing both halves for
   one pin incorrectly leaves it reset. STM32 specifies set priority. The local
   F303 model and the upstream patch now apply reset first and set last.
4. Renode 1.16.1 only sets STM32 timer UIF when UIE is enabled. UIF is a status
   flag; UIE gates only its interrupt. Current Renode master already contains
   the correct unconditional UIF behavior, so this is a local 1.16.1 backport,
   not a new upstream request.
5. A full-duplex STM32 SPI transfer clocks receive data for every transmitted
   unit. The local F303 DMA model infers the matching peripheral-to-memory
   channel when the transmit channel writes the shared data register. That
   address-matching heuristic unblocks LCD readback in this executable fixture,
   but it is not an upstream design: Renode's generic STM32 SPI model already
   emits explicit RX DMA request GPIOs. Any upstream F303 work must connect
   proper SPI-v2 request lines to a generalized channel-DMA model.
6. ST7796S memory-read commands `0x2E` and `0x3E` return a dummy byte followed
   by sequential RGB565 GRAM data and advance the active window cursor. The
   local display model implements that behavior so the firmware can validate
   and restore GRAM. Renode has no upstream ST7796S peripheral, so a vendor
   contribution would be a complete new model rather than a readback patch.

The RETTOBASE fix is public in Renode PR #217; the two GPIO fixes are public in
PR #218. The local DMA heuristic is explicitly not for upstream. STM32F3
SPI-v2/channel-DMA support and a complete ST7796S model are possible future
proposals only after redesign and focused Renode regressions. Timer UIF needs
no new upstream patch. The complete queue is in
[`VENDOR_UPSTREAM_QUEUE.md`](VENDOR_UPSTREAM_QUEUE.md).
