# ZS407 enhanced hardware trial v0.3

This is the first deliberately flashable private image from the modernization
program. It is a reversible laboratory trial, not an official tinySA release.

## Included

- the exact upstream `c979386` analyzer behavior and ZS407 hardware tables;
- the complete seven-item small build/bounds-fix queue;
- the Phase 0–6 deterministic services, CCM frequency cache, fixed-point
  measurements, dry-run RF planners and reversible Atomic palette preview;
- the v0.2 typed protocol, compact codecs and SPSC/USB worker, with binary
  transport still locked;
- a saturating Q1.15 radix-2 FFT extended from 512 to 1,024 points;
- an embedded 1,024-point correctness vector and `modern fft-bench`, which
  executes and times the transform with the Cortex-M4 DWT cycle counter; and
- locked AWG/RF experiment entry points. No new RF output path can start.

Metrics scratch and complex FFT scratch cannot be live simultaneously, so they
share one explicit union. Together with the frequency cache this consumes
7,696 of the F303's 8,192 CCM bytes and leaves ordinary DMA SRAM unchanged.

## What the FFT means

The transform is a real on-device 1,024-point DSP capability. It is not yet a
1,024-bin instantaneous RF spectrum. The ZS407 exposes swept RSSI rather than
wideband I/Q samples. A useful live envelope FFT still requires a measured,
uniform zero-span sample interval and calibrated frequency-axis semantics.

`modern fft-bench` therefore operates only on a deterministic RAM vector. It
proves correctness and establishes the cycle budget on the physical MCU
without changing RF, calibration, configuration or persistent storage.

## Conservative first-flash behavior

This first trial retains the phase program's conservative SPI timing and one
flash wait state. The CPU/DSP and frequency-cache work can be measured safely,
but the LCD and RF-control buses are not accelerated beyond their conservative
profile. A later hardware-qualified performance profile can restore the
already-proven OEM bus rates selectively and compare response time and spurs.

The Atomic palette remains an explicit, RAM-only preview:

```text
modern palette atomic
modern palette restore
```

It is never saved automatically and a reboot restores the persisted palette.

## Physical qualification order

1. Cache and hash the official `c979386` BIN and DFU rollback images.
2. Verify one physical DFU device and one internal-flash alternate.
3. Write the exact committed v0.3 binary with every RF cable removed.
4. Read back only `version`, `info` and `vbat` after DFU leave.
5. Perform a physical cold power cycle.
6. Run the complete built-in CAL-to-RF self-test, then remove the cable.
7. Run `modern`, `modern selftest`, `modern dsp-selftest`, `modern audit` and
   `modern fft-bench` over USB.
8. Exercise the Atomic palette only after the analyzer and DSP gates pass.

Any boot, identity, self-test or DSP failure ends the trial and returns the
unit to the cached official image before further development.
