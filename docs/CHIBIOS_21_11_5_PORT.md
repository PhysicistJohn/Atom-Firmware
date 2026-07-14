ChibiOS 21.11.5 port
====================

Status
------

Both legacy firmware targets have been ported from the historical ChibiOS
snapshot to the official `ver21.11.5` (Agropoli) release at
`f4bbadf964fc746aef8bbcf34135c7d8fabb8eae`.

RC4 is rejected. Its exact 193,948-byte F303 image, SHA-256
`17fa401eac68e514c99fdb55ed0c106601107b4c973876aa28d18993aee22fae`,
flashed and cold-booted on the ZS407, but failed physical USB configuration.
macOS identified the raw `0483:5740` device and descriptors, then remained at
`UsbEnumerationState=2`; it created neither an `IOUSBHostInterface` child nor a
`/dev/cu.usbmodem*` device. A physical USB unplug/replug reproduced the same
failure. RC4 must not be used as a candidate again.

RC5 keeps the TIM14 compatibility fix and adds one USBv1 packet-memory fix.
The ChibiOS gitlink is
`b3f82b396de7cf2a9e85bc8f1575fbd58e9428d9`, directly above:

- `2b8f425d26a61a7887916f7052b401f9e767a949`, which restores the
  standalone STM32F0 TIM14 GPT interrupt service required by the F072
  `GPTD14` delay timer; and
- `b3f82b396de7cf2a9e85bc8f1575fbd58e9428d9`, which preserves endpoint
  zero's packet-memory reservation when the USB core disables and rebuilds
  nonzero endpoints.

The complete RC5 simulation seal and physical qualification are not complete.
The exact-image USB regression passes in the twin, while the remaining RC5
simulator matrix is running. No RC5 hardware pass is claimed here.

Why RC4 failed
--------------

On bus reset, the USBv1 low-level driver allocates EP0 IN and OUT at PMA
addresses `0x0040` and `0x0080`. The first configuration then allocates the
CDC endpoints after them: EP1 IN/OUT at `0x00c0`/`0x0100` and EP2 IN at
`0x0140`.

The default USB core intentionally tears down and rebuilds a configuration for
every valid `SET_CONFIGURATION`, including when a host selects the current
configuration again. During that teardown, `usb_lld_disable_endpoints()`
leaves EP0 active but resets `pmnext` to the beginning of packet memory. The
next configuration therefore assigns EP1 IN/OUT to EP0's still-live
`0x0040`/`0x0080` buffers and EP2 IN to `0x00c0`.

This is a deterministic allocator overlap, not a transport-speed or shell
problem. Defining `USB_SET_CONFIGURATION_OLD_BEHAVIOR` would only hide the
same-value `1 -> 1` reproducer; a standards-valid `1 -> 0 -> 1` sequence still
uses the faulty teardown path. It would also discard the endpoint reset
behavior introduced by ChibiOS commit `8097785b8` for bugs 938 and 939.

RC5 replaces the allocator reset in `usb_lld_disable_endpoints()` with a reset
that immediately reserves the configured EP0 IN and OUT maximum sizes. The
full bus-reset path still performs a true allocator reset before EP0 is
initialized. The change is confined to
`os/hal/ports/STM32/LLD/USBv1/hal_usb_lld.c`.

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
- Preserve the legacy hard-FPU build's `-fsingle-precision-constant` behavior.
- Gate expensive system-timer reads in the fast sweep path and retain only the
  three measured LCD hot paths at `O3,no-strict-aliasing`.
- Initialize the complete RTC backup structure before checksumming it.
- Replace naked C fault handling with an assembly-only MSP/PSP selector and
  r4-r11 save, followed by a normal C diagnostic on a 1 KiB main stack.
- Preserve factory-self-test scratch traces and restore pre-existing trace
  state on exit.
- Calculate zero-span grid geometry from the sweep that just completed, with
  64-bit arithmetic through the final division.
- Preserve EP0 PMA ownership while configuration endpoints are rebuilt.

Reproduce the RC5 build
-----------------------

Use the repository-pinned Arm GNU 11.3.Rel1 toolchain. The release builder
performs two clean builds of each target, compares BIN/ELF/HEX/MAP/LIST/DMP,
audits the hard-fault veneer and software-double call count, and generates the
exact simulator symbol profile:

```bash
git switch codex/chibios-latest-rc5
git submodule update --init --recursive
tools/build-chibios-release-candidate.sh v0.4-chibios21.11.5-rc5
```

The implementation is
`d4c7ec8c2a6df9887bb0ab306346ebbf47688eef`; the audited release-tooling
commit is `6fdf6f307ecb0cef2e3af478b0fc7b80a1fd13e2`. Two clean builds of both
targets produced byte-identical artifacts with zero compiler warnings and zero
undefined symbols:

| Target | Binary | Size | Flash | SHA-256 |
| --- | --- | ---: | ---: | --- |
| F303 RC5 | `tinySA4_v0.4-chibios21.11.5-rc5.bin` | 193,980 B | 78.93% of 240 KiB | `1e3f45a9744b18985622d5abf6c2445524a4ad53a831316766c37de80ac96685` |
| F072 compatibility | `F072_COMPAT_tinySA_v0.4-chibios21.11.5-rc5.bin` | 115,236 B | 97.01% of 116 KiB | `7e00dc013a81fd85e5a86911e7a1ac5781cb17d177bd0560689bc5041e36ea0f` |

The F303 ELF SHA-256 is
`d742ba7dc33a71db83a2bb2ffa8b0cb67977977555c507d1e663aebc6051fa56`;
the symbol-profile SHA-256 is
`44c1c0b0d2efca014babe49efc2c7832f162675e06b6832bf52c6b9cfa3876e8`.
The F072 image has 3,548 bytes of application flash headroom and remains a
release constraint.

The package is under
`.artifacts/chibios-releases/v0.4-chibios21.11.5-rc5/6fdf6f307ecb0cef2e3af478b0fc7b80a1fd13e2/`.
At this point it deliberately carries `SIM_PENDING`,
`simulation_qualification=SIM_PENDING`, and `hardware_qualified=false`.

Digital-twin USB regression
---------------------------

The current USB scenario checks the firmware-owned endpoint registers and PMA
descriptors, not just a synthetic CDC response. It covers:

1. the first `SET_CONFIGURATION(1)`;
2. same-value reconfiguration `1 -> 1`;
3. explicit unconfiguration and selection `1 -> 0 -> 1`;
4. CDC setup, fragmented shell traffic, suspend/wakeup, and EP0 STALL; and
5. a final bus reset and clean re-enumeration.

`AssertActiveBufferAddressesDistinct` scans every active TX/RX buffer address
and rejects any duplicate. The exact RC4 ELF now fails on the second
configuration because EP0 TX and EP1 TX both own `0x0040`. The exact RC5 ELF
passes. The complete scenario requires exactly five
`ZS407_TWIN_USB_PMA=PASS` markers and three
`ZS407_TWIN_USB_ENDPOINTS=PASS data=disabled` markers, including the final
reset/re-enumeration state.

The ChibiOS USBv2 low-level driver in 21.11.5 contains the analogous pattern:
it leaves EP0 active, calls the same kind of `usb_pm_reset()` from
`usb_lld_disable_endpoints()`, and allocates later endpoint buffers from that
reset cursor. RC5 does not consume USBv2, so no USBv2 code is included in the
firmware hotpatch. The vendor handoff recommends the corresponding fix and a
driver-level regression on current `main` before publication.

Qualification boundary
----------------------

RC5 is reproducibly built and its focused exact-image USB regression passes.
The full simulator matrix is still in progress, so the package remains
`SIM_PENDING`. Physical RC5 testing has not yet been completed and the
manifest must remain `hardware_qualified=false`.

Before release, the exact packaged F303 binary still needs:

1. the complete hash-bound simulator seal: both all-14 screenshot/trace A/B
   suites, non-flat RF checks, runtime/reset, fault, UI, and complete USB gates;
2. cold boot, normal boot, DFU entry, recovery, and rollback on the ZS407;
3. physical CDC enumeration, same-value and zero-toggle configuration where
   the host exposes them, suspend/resume, unplug/replug, shell traffic, and
   sustained screen transfer;
4. all fourteen physical self-tests with CAL connected, with each settled
   screenshot and trace compared to official `c979386` for exact or
   demonstrably better, non-flat behavior;
5. the disconnected-CAL failure/recovery control, RF checks, controls/touch,
   acquisition, and warm/cold/power-cycle retention; and
6. forced PSP/MSP fault diagnostics and recovery, if an authorized physical
   fault-injection path is available.

The F072 compatibility artifact is build evidence only. It separately needs
TIM14 timing and complete-image qualification on F072 hardware.

The exact official-release reproduction documented in
[Baseline and provenance](BASELINE.md) remains unchanged; this port is a new
candidate and is not expected to reproduce the historical binary byte for
byte.
