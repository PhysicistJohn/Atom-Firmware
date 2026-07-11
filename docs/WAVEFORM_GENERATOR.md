# Waveform and signal-generator architecture

The ZS407 can gain useful waveform-generation behavior, but it has two very
different output classes. Keeping them separate prevents a low-frequency DAC
feature from being mistaken for a true arbitrary RF generator.

## Capability boundary

| Path | What can be arbitrary | What it cannot do | Phase 5 state |
| --- | --- | --- | --- |
| STM32 DAC1 on PA4 | A 12-bit low-frequency voltage sample stream | RF, coherent I/Q, calibrated 50-ohm level, or a second channel | Buffer/timer/DMA implementation linked but start permanently refused |
| Si4468 FIFO/modem | OOK, 2FSK, 2GFSK, 4FSK, 4GFSK and PRBS symbol streams | QAM, OFDM, arbitrary phase, arbitrary multitone, or host I/Q samples | Quantization/planning only; no radio writes |
| Existing PLL/generator paths | Frequency, dwell, gate and coarse level events | Phase-continuous sampled waveforms | Event format and compiler only; no executor |
| PE4302 | 0.5 dB attenuation steps | Smooth voltage envelope or fast calibrated AM | Quantization model only |

The answer to “can it do arbitrary waveform generation?” is therefore **yes
at low frequency through the MCU DAC, and structured modulation at RF**. A true
arbitrary RF waveform needs new I/Q or direct-RF hardware.

## Low-frequency DAC engine

`modern/embedded/zs407_awg.c` contains the full STM32F303 execution path:

```text
Q15 phase accumulator -> 256 x uint16 DAC buffer in ordinary SRAM
                                      |
                                 DMA2 channel 3
                                      |
                              DAC1 DHR12R1 / PA4
                                      ^
                                      |
                    TIM6 update/TRGO at planned sample rate
```

- Sine uses a generated 65-entry quarter-wave Q15 table.
- Triangle and square are integer phase functions; noise uses xorshift32.
- The requested sample clock is quantized into 16-bit TIM6 PSC/ARR fields and
  the actual rate is reported.
- The waveform phase increment is recalculated from that actual sample rate;
  the actual waveform frequency is reported in millihertz.
- Samples saturate to the DAC's 0..4095 range.
- The 512-byte circular buffer is deliberately in ordinary SRAM because the
  STM32F303 DMA controller cannot access CCM.
- DAC channel 2 bits are preserved because DAC2/PA5 controls LCD brightness.

The current source already writes listen-mode RSSI audio to `DAC->DHR12R1`.
The board header confusingly names PA4 `GPIO_SD_DAT2`, but configures it as
analog and no active source consumes that symbol as SD data. This is useful
source evidence, not proof of the connector bandwidth or load on one ZS407.

### Hard lock in the Phase 5 image

The backend contains a private `volatile` qualification latch with no setter.
`zs407_awg_start()` checks it before allocating DMA, changing pin mode,
enabling TIM6, or altering DAC1. Consequently:

- `modern awg SHAPE FREQ_HZ SAMPLE_HZ` renders and checks the buffer only;
- `modern awg selftest` verifies planning, rendering and the refusal path;
- `modern awg start` always returns `NOT_QUALIFIED`;
- no Phase 5 command can turn the latch on;
- `modern awg stop` is a no-op unless the backend is active.

The unreachable hardware path is still linked and compiled so register names,
DMA allocation calls and the ChibiOS ABI cannot silently rot.

### Qualification required before unlocking

1. Prove stock DFU recovery and preserve configuration/calibration.
2. Identify the PA4 destination by continuity and measure its DC load while
   the unit is off.
3. Capture the stock listen waveform, offset, amplitude and bandwidth.
4. Start with a midscale DC buffer through a current-limited/high-impedance
   measurement path; confirm DAC2 brightness is unchanged.
5. Verify TIM6 and DMA2 channel 3 are free in every enabled configuration.
6. Check underflow behavior, stop-to-zero behavior and ownership against listen
   mode, PWM mode, sweep processing, shell abort and hard fault.
7. Measure image rejection, sample images, distortion, load dependence and
   useful bandwidth before publishing any amplitude or frequency claim.

The 200 ksample/s software ceiling is a conservative planning limit, not a
promise of 100 kHz usable analog bandwidth. DAC settling, board filtering,
connector routing and reconstruction requirements will set the real ceiling.

## Portable waveform event format

The event ABI is a fixed 16-byte little-endian record:

| Field | Type | Meaning |
| --- | --- | --- |
| `at_us` | `uint32` | Absolute program time in microseconds |
| `opcode` | `uint8` | Gate, frequency, level, DAC sample, trigger wait or end |
| `flags` | `uint8` | Must be zero in version 1 |
| `reserved` | `uint16` | Must be zero |
| `value` | `int64` | Opcode-specific integer value |

The `ZSAW/1` file adds a 12-byte header containing magic, version, record size,
count and IEEE CRC-32 of the event payload. The C structure has a compile-time
16-byte size assertion. The Mac compiler uses an explicit little-endian pack
format and a deterministic golden fixture.

Both implementations reject a program unless its first event is gate-off at
time zero, times never move backward, trigger waits occur while gated off, and
the final event ends with output off. These invariants make malformed programs
fail closed; they do not make a requested RF emission legal or calibrated.

See [the DSL and example](../modern/waveforms/README.md).

## Structured RF plans

`modern rf-wave MODE BITRATE DEVIATION_HZ` validates and reports a 64-byte
Si4468 FIFO plan. It never writes a radio register and always prints `tx=off`.
The current planner supports:

- OOK and PRBS at one bit per symbol;
- 2FSK/2GFSK at one bit per symbol;
- 4FSK/4GFSK at two bits per symbol;
- 100 bit/s through 1 Mbit/s planning bounds;
- deviations through 500 kHz.

Those are software acceptance bounds, not a claim that every rate/deviation
combination is legal in every band or realizable through the ZS407 output path.
Before an executor exists, generated modem properties must be independently
checked against the exact Si4468 patch/configuration and measured into a
shielded 50-ohm load. Direct GPIO modulation remains unsuitable because the
source-derived GPIO assignments also own CTS and RF path switching.

## Honest non-capabilities

No firmware technique, LLVM optimization or larger FFT can recover hardware
that is absent. The current board has no host-accessible coherent I/Q receive
stream and no dual high-rate transmit DAC/IQ modulator. Therefore Phase 5 does
not claim arbitrary RF phase, QAM/OFDM, phase-coherent chirps, simultaneous
arbitrary multitone, or RF waveform playback.
