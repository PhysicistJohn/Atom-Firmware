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

Reproduce the builds
--------------------

Use the repository-pinned Arm GNU 11.3.Rel1 toolchain:

```bash
git submodule update --init --recursive
PATH="$(tools/bootstrap-toolchain.sh):$PATH" make TARGET=F303 -j8
make clean
PATH="$(tools/bootstrap-toolchain.sh):$PATH" make TARGET=F072 -j8
```

The final clean builds complete with zero compiler warnings and errors:

| Target | Binary | Size | Flash | SHA-256 |
| --- | --- | ---: | ---: | --- |
| F303 | `tinySA4.bin` | 193,060 B | 78.56% of 240 KiB | `6a442a53c71eb5e85880714863d80e13c47ebad1106187586e7724aebc3450b9` |
| F072 | `tinySA.bin` | 114,940 B | 96.76% of 116 KiB | `396922a90a643d247bbe4ef56cdc137f3ba4df439cfad31b15745af87330c07c` |

The F072 image has little remaining flash headroom. Treat further growth on
that target as a release constraint.

Qualification boundary
----------------------

These images are build- and host-test-qualified only. No hardware was flashed
or controlled while preparing this port. Before release, qualify at least:

1. Cold boot, normal boot, DFU entry, and recovery.
2. Complete self-test and calibration-preservation checks.
3. USB enumeration, shell traffic, suspend/resume, disconnect/reconnect, and
   sustained frame transfer.
4. Lever, push, touch, SD-card detect/power, and serial-mode PAL events.
5. ADC acquisition and sweep behavior across modes and ranges.
6. F072 TIM14 delay timing and F303 interrupt-load behavior.
7. RF output and measurement accuracy against the known-good firmware.

The exact official-release reproduction documented in
[Baseline and provenance](BASELINE.md) remains unchanged; this port is a new
candidate and is not expected to reproduce that historical binary byte for
byte.
