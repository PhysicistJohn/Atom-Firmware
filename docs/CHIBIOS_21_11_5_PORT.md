ChibiOS 21.11.5 port
====================

Status
------

This branch ports both legacy firmware targets from the historical ChibiOS
snapshot to the official `ver21.11.5` (Agropoli) release at upstream commit
`f4bbadf964fc746aef8bbcf34135c7d8fabb8eae`.

The submodule points to local compatibility commit
`2b8f425d26a61a7887916f7052b401f9e767a949`. It contains one focused change
on top of the official tag: restore the generic STM32F0 TIM14 GPT interrupt
service. The F072 firmware uses `GPTD14` as `DELAY_TIMER`; disabling it would
change firmware behavior rather than complete the port.

Port changes
------------

- Adopt the RT7/HAL9 configuration markers, OS library settings, build rules,
  Cortex-M port paths, and license include required by ChibiOS 21.11.5.
- Raise kernel-aware F303 interrupt priorities from 2 to 3 to respect the
  RT7 fast-interrupt reservation.
- Migrate board GPIO initialization, DMA allocation, ADC group definitions,
  PAL line events, USB serial hooks, endpoint configuration, PWM configuration,
  queue reset calls, time conversions, and thread-priority diagnostics.
- Update the project-local F303 ADC LLD while retaining its tinySA-specific
  behavior.
- Convert custom `BaseSequentialStream` VMTs to the current layout, including
  the required `instance_offset` field.
- Preserve the legacy hard-FPU build's `-fsingle-precision-constant` behavior
  explicitly. ChibiOS 21.11.x no longer adds it automatically; omitting it
  promotes unsuffixed sweep constants to software double precision and causes
  a measurable self-test sweep regression.
- Avoid reading and converting the system timer on seven of every eight fast
  sweep points where the progress bar cannot update.
- Compile only the LCD window, bitmap, and dirty-cell DMA handoff hot paths at
  `O3,no-strict-aliasing`. This restores held-screen throughput without
  exposing the RF/math firmware to whole-program optimization changes.
- Initialize the complete RTC backup structure before checksumming it so its
  reserved byte is deterministic across optimized warm resets.
- Replace the legacy naked-C hard-fault entry with an assembly-only MSP/PSP
  selector and r4-r11 save, then call the normal C diagnostic on a 1 KiB main
  stack. The core exception frame remains at the selected stack pointer for
  both basic and extended floating-point frames.
- Read the F303 free-running counter directly in the sweep hot path and reduce
  progress sampling adaptively, while leaving F072 on the kernel time API.
- Preserve the two factory self-test scratch traces directly instead of
  repeating equivalent acquisition work; restore any pre-existing trace state
  on exit.
- Recompute zero-span grid geometry from the sweep that just completed, retain
  the full 64-bit ratio until the final division, and redraw only when the exact
  grid tuple changes.

Reproduce the builds
--------------------

Use the repository-pinned Arm GNU 11.3.Rel1 toolchain. The release builder
performs two clean builds of each target, compares BIN/ELF/HEX/MAP/LIST/DMP,
audits the hard-fault veneer and software-double call count, and generates the
exact simulator symbol profile:

```bash
git switch physicistjohn/release-v0.4-chibios21.11.5-rc4
git submodule update --init --recursive
tools/build-chibios-release-candidate.sh v0.4-chibios21.11.5-rc4
```

These commands reproduce the package in this checkout. The release ref and
sealed artifact are currently local; an external handoff must publish the ref
or include both a source bundle and the package.

The exact package was built from implementation commit
`f7b0d5c6a6894655108cd6e8626d56ff25ad76ee` and audited builder commit
`f5f912c1bdc95b785dcbde85495aa5153fe0721a`. Two clean builds of both targets
produced byte-identical BIN/ELF/HEX/MAP/LIST/DMP artifacts with zero compiler
warnings and zero undefined symbols:

| Target | Binary | Size | Flash | SHA-256 |
| --- | --- | ---: | ---: | --- |
| F303 RC4 | `tinySA4_v0.4-chibios21.11.5-rc4.bin` | 193,948 B | 78.92% of 240 KiB | `17fa401eac68e514c99fdb55ed0c106601107b4c973876aa28d18993aee22fae` |
| F072 compatibility | `F072_COMPAT_tinySA_v0.4-chibios21.11.5-rc4.bin` | 115,188 B | 96.97% of 116 KiB | `01f4fb2ad5d7296a67bc987dd7276f4287192146cfdd4432421d11b87a3200d0` |

The F303 ELF SHA-256 is
`94ae40e40cd860bb5efb6e67a73f2e617e14e7f8e4979ed4e6cf5f40b79a69b2`;
the exact symbol-profile SHA-256 is
`7eebfeeef1885e2fcf31375ab66b0ef10d4ea6059e38267d27365b99efa9cf98`.
The release script also passed a hostile-environment build with poisoned output
directory, optimization, FPU, define, phase, version, and compiler variables
without changing the F303 hash. The F072 image has only 3,596 bytes of
application flash headroom, so further growth is a release constraint.

The simulation-sealed package is under
`.artifacts/chibios-releases/v0.4-chibios21.11.5-rc4/f5f912c1bdc95b785dcbde85495aa5153fe0721a/`.
Its 220-entry `SHA256SUMS` inventory has SHA-256
`bc221054ff0a80954f59dce844f19328d6e3d01321bbffa843ae564d25844360`.
The package carries `HARDWARE_PENDING`, not a hardware-release approval.

Digital-twin qualification
--------------------------

The exact RC4 package passed boot and peripheral initialization, jog input,
touch, return to normal UI, and a frequency-selective 450 MHz RF scene. The
modeled tone produced 7,333 RSSI samples spanning 108..200 and a complete,
visibly non-flat 445.9 MHz / -28.3 dBm screen.

The same BIN passed USB device/configuration descriptors, address and
configuration, CDC ACM setup, fragmented shell traffic, suspend/wakeup,
unsupported-request STALL, bus reset, and re-enumeration. A disconnected-CAL
negative control made case 3 fail with firmware status 2 and cause
`Signal level`, retained the real interactive failure screen, accepted touch
acknowledgement, restored normal sweep state, and reconnected the fixture.

The authoritative paired visual gate ran all fourteen cases on the pinned
pre-ChibiOS `lab-v0.2.0-protocol` baseline (`d12bd826`, BIN SHA-256
`a1dbaa03978a25b2a8b2a0e85f60029a6cc736481732eff68e93362724683dd7`)
and the exact RC4 image. This direct ancestor is the port's behavioral A/B
reference; it is not the separate official `c979386` rollback image. Both runs
produced fourteen firmware passes, settled result screens, status records,
307,200-byte raw LCD frames, and 7,200-byte four-plane trace captures, with zero
model errors. Cases 1..11 and 14 pass the strict legacy comparator. Cases 12
and 13 pass the separate `mathematically-better-time-grid` classifier: RC4's
expected and observed columns match exactly, the lab-baseline grid is stale,
and all changed
pixels are relocated grid intersections or bounded time text. All fourteen
trace matrices are byte-identical baseline-to-RC4. The suite visibly retains
the narrow peaks, broad filter responses, and the 104.03 dB-span case-14 gain
trace; flat status-only evidence is explicitly rejected.

Runtime-state qualification retained the configured RTC state across warm
reset, completed all fourteen tests again, left 624 bytes of sweep stack and
912 bytes of MSP, and transferred a 131-packet/8,300-byte remote redraw over
USB. Both the extended-FPU PSP and nested-handler MSP HardFault paths preserved
their core frames and r4-r11 diagnostics; the fatal screens were captured from
the authoritative raw framebuffer with 584 and 552 bytes of MSP remaining.

Every exact scenario exited zero with zero unexpected simulator warnings. Known
warnings were limited to the pinned Renode model's documented translation-cache
clamp, Thumb-entry normalization, USART LBDIE/EIE/ICR gaps, and TIM1 MMS bit 5.
The nested-MSP test assigned the outer configurable IRQ priority `0x80` because
the pinned model represents HardFault as numeric priority zero; that distinct
Renode defect is retained in the vendor queue.

Qualification boundary
----------------------

This image is build-, host-, and simulator-qualified with
`simulation_qualification=SIMULATION_PASS_HARDWARE_PENDING`. Its manifest must
remain `hardware_qualified=false`; no hardware was flashed or controlled while
preparing this package. Before setting `hardware_qualified=true` or field
launch, qualify at least:

1. Cold boot, normal boot, DFU entry, and recovery.
2. Complete self-test and calibration-preservation checks; capture every result
   screen and compare it with the sealed lab-baseline/candidate evidence for
   exact or demonstrably better behavior, including real non-flat traces.
3. USB enumeration, shell traffic, suspend/resume, disconnect/reconnect, and
   sustained frame transfer.
4. Lever, push, touch, SD-card detect/power, and serial-mode PAL events.
5. ADC acquisition and sweep behavior across modes and ranges.
6. Warm reset, cold reset, and power-cycle RTC/settings retention.
7. Forced extended-FPU PSP and nested-MSP faults, diagnostic-screen review,
   reset, DFU recovery, and rollback.
8. F303 interrupt-load behavior and RF output/measurement accuracy against the
   known-good firmware.

The F072 compatibility artifact is build evidence only. Before any F072
release, separately qualify TIM14 timing and the complete F072 image on F072
hardware.

The exact official-release reproduction documented in
[Baseline and provenance](BASELINE.md) remains unchanged; this port is a new
candidate and is not expected to reproduce that historical binary byte for
byte.
