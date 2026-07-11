# Firmware architecture

This document describes the pinned `c979386` baseline. It separates facts
visible in source/ELF from assumptions that still require board inspection.

## Hardware-facing build target

The Ultra-family build is selected with `make TARGET=F303`. The target defines:

```text
CPU family       STM32F303xC / Cortex-M4
instruction set  Thumb, ARMv7E-M
floating point   hard ABI, FPv4-SP-D16
display          ST7796S path, 480 x 320 RGB565
receiver         Si4468 path
clock generator  Si5351 support
audio codec      TLV320AIC3204 support
filesystem       FatFs on microSD
USB              CDC ACM, VID 0483, PID 5740
RTOS             ChibiOS/RT API, kernel macro 4.0.0
```

For ZS407, runtime hardware ID 103 enables the MAX2871-specific branches and
the ZS407 correction/range tables. Component names here are derived from the
build and source. A teardown/photo inventory should confirm exact board
markings and substitutions before any electrical redesign.

The official RF description is a swept heterodyne analyzer: input switching
selects LNA or step attenuation and filtered/bypass paths; a swept LO and mixer
produce a high IF; the Si4468-class receive path converts to a low IF and
provides selectable RBW filters and power detection. Output mode reuses the RF
chain in the opposite direction. See
<https://tinysa.org/wiki/pmwiki.php?n=TinySA4.TechnicalDescription>.

## Memory map

```text
0x08000000 .. 0x0803bfff  240 KiB executable/constant/data-load image
0x0803c000 .. 0x0803ffff   16 KiB calibration storage region
0x20000000 .. 0x20009fff   40 KiB SRAM
0x10000000 .. 0x10001fff    8 KiB CCM RAM (not allocated today)
```

The exact baseline layout is:

| Section/group | Size |
| --- | ---: |
| vectors | 416 B |
| `.text` | 140,700 B |
| `.rodata` | 40,812 B |
| initialized `.data` | 3,764 B RAM / flash load |
| `.bss` | 28,200 B |
| exception stack | 512 B |
| process stack | 1,152 B |
| remaining linker heap | 7,328 B |

The linker calls RAM “100% used” because the heap deliberately consumes the
remainder. That is not proof that runtime heap usage is 100%, but it does mean
new static allocations cannot simply spill into ordinary SRAM. Stack high-water
measurement and intentional CCM placement are prerequisites for major growth.

## Execution model

There are two important execution contexts:

1. `main()` initializes clocks, GPIO, LCD, ADC/DAC, storage, USB, RF devices,
   persisted configuration, and runtime hardware identity. It then owns the
   USB shell connection loop.
2. `Thread1`, named `sweep`, owns scanning, self-test/calibration requests, UI
   processing, trace calculation, and most drawing.

Shell commands that touch instrument state are handed into the sweep thread
through shared command fields and a ChibiOS thread queue. This serialization is
important: moving command execution to a new task without understanding RF,
display, and SPI ownership could introduce subtle timing and race failures.

The system is largely static: fixed thread working areas, global configuration,
global trace/measurement arrays, and direct peripheral calls. There is no
dynamic driver registry or hardware abstraction boundary suitable for host
tests today.

## Source topology

The apparent file list understates translation-unit size because four C files
are included directly into other C files:

```text
main.c  -> sa_core.c -> core RF/sweep/calibration/measurement logic
main.c  -> sa_cmd.c  -> USB shell commands
plot.c  -> waterfall.c
ui.c    -> vna_browser.c
```

The largest application sources are approximately:

| File | Lines | Responsibility |
| --- | ---: | --- |
| `sa_core.c` | 8,699 | RF state, sweep, calibration, measurements |
| `ui.c` | 8,473 | menus, input, settings, screen workflows |
| `main.c` | 3,536 | boot, RTOS threads, shell, config and hardware identity |
| `si4468.c` | 2,736 | RF transceiver/PLL/device control |
| `plot.c` | 2,316 | traces, grid and rendering |
| `nanovna.h` | 1,942 | shared types, feature flags and global interfaces |
| `ili9341.c` | 1,771 | display/SPI implementation despite the legacy filename |
| `sa_cmd.c` | 1,420 | command protocol |

Unity inclusion permits hidden coupling through file-local declarations and
include order. Splitting these into normal translation units is desirable, but
it is a behavior-changing project until symbol visibility, stack, timing, and
binary size are measured.

## Modernization seams

The safest sequence is:

1. Freeze serial transcripts, self-test results, RF measurements, stack usage,
   binary size, and timing from the exact baseline.
2. Extract pure functions first: frequency planning, unit conversion,
   correction interpolation, trace math, and command parsing.
3. Add host-compiled tests around those functions without emulating hardware.
4. Introduce narrow interfaces for time, storage, display, RF register I/O,
   and persisted configuration.
5. Split unity translation units only after tests exercise their boundaries.
6. Change RTOS or MCU support last. An RTOS upgrade affects interrupt, timing,
   USB, HAL, and memory behavior simultaneously.

“Modern” is not automatically “better” in an RF instrument. The controlling
metrics are measurement accuracy, spur behavior, scan time, determinism,
recovery, memory headroom, and maintainability—not language or framework age.
