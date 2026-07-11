# Phase 5: waveform generator foundations

Branch: `physicistjohn/phase-5-waveform-generator`

Phase 5 answers the arbitrary-waveform question with executable software while
keeping every physical output disabled pending the hardware session.

## Implemented

- deterministic generated Q15 sine data and integer sine, triangle, square and
  noise renderers;
- a tested 16-bit timer planner that reports the actual sample clock;
- a 12-bit saturating DAC renderer that reports actual waveform frequency;
- the full TIM6 TRGO -> DAC1/PA4 <- DMA2 channel 3 circular backend;
- a private, unsettable hardware-qualification latch checked before the first
  peripheral mutation;
- a 512-byte DMA buffer in ordinary SRAM, leaving the 7,456-byte CCM DSP layout
  unchanged;
- an output-off self-test and shell status/prepare/refusal commands;
- a fixed 16-byte gate/frequency/level/DAC/trigger/end event ABI with fail-closed
  validation;
- a deterministic macOS waveform DSL compiler and checked source fixture;
- Si4468 OOK/FSK/GFSK/4FSK/4GFSK/PRBS FIFO planning with no register writes;
- PE4302 0.5 dB attenuation quantization;
- host UBSan, embedded-float, ASan-link, freestanding Cortex-M4 and Swift checks.

## Embedded commands

```text
modern awg status
modern awg selftest
modern awg sine 1000 48000
modern awg start
modern rf-wave 2gfsk 100000 25000
```

Prepare and self-test only alter RAM. `start` always refuses with hardware
qualification required. Every RF waveform command is a dry run and prints
`tx=off`.

## Resource result

The latest draft GNU link is 202,692 bytes in the 245,760-byte application region.
Ordinary BSS is 28,820 bytes and the linker heap remains 6,708 bytes after the
DMA buffer. CCM remains 7,456/8,192 bytes. `cmd_modern` static stack use is 200
bytes, below the 450-byte shell working area. A complete Clang `-Oz`/GNU hybrid
link is 199,508 bytes. The final reproducible image and hash are recorded by the
phase image manifest after commit.

## Exit state

This phase proves source, host behavior, cross-compilation and full linking. It
does not prove PA4 loading, analog bandwidth, RF modulation quality or safe
emissions. Those remain physical qualification gates in
[WAVEFORM_GENERATOR.md](../WAVEFORM_GENERATOR.md).
