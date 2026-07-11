# Renode upstream-ready fixes

This directory contains three PhysicistJohn-authored fixes prepared against
`renode/renode-infrastructure` commit
`1c3c1c1f9f1a1c4c7b7302bca3a37b9aa361c7a2` (current master when audited on
2026-07-11). The matching `renode/renode` checkout was
`4a4f575ec92f830fb9c26a857374e4a05e097162`.

No issue, pull request, public branch, or comment has been created. Publication
and hardware flashing remain explicitly gated.

## Patch queue

| Patch | Failure fixed | Upstream shape | Confidence |
| --- | --- | --- | --- |
| `0001` NVIC RETTOBASE | ICSR bit 11 was a tag that always read zero | Independent NVIC PR after opening the requested issue | High |
| `0002` STM32 IDR/ODR | Output-latch writes changed input pin state | First commit of one STM32 GPIO PR | High |
| `0003` STM32 BSRR priority | Simultaneous set/reset incorrectly let reset win | Second commit of the GPIO PR; depends on `0002` as packaged | Very high |

Apply the complete audited series from the stated Infrastructure base:

```bash
git am /path/to/upstream-patches/renode/000*.patch
```

The mailbox series was reapplied from a clean detached base and its resulting
tree was byte-for-byte identical to local audited commit
`4eb372083b9a94b337a7f4f6413b2bb841cb1da9`.

## 0001: implement ICSR.RETTOBASE

Current master defines ICSR bit 11 with `.WithTaggedFlag("RETTOBASE", 11)`, so
software always reads zero. Arm defines RETTOBASE on Armv7-M and Armv8-M as set
when no exception is active or the executing exception is the only active
exception. Armv6-M does not implement the bit and must read it as zero.

The patch:

- returns `activeIRQs.Count <= 1` on supported cores;
- keeps the bit zero for Cortex-M0, M0+, and M1;
- avoids `ArchitectureVersion` as the sole capability check because Renode
  intentionally reports Armv7 compatibility for its M0 family;
- supplies managed regression cases for zero, one, and two active exceptions.

The model-name guard is deliberately narrow and is the main review point. A
future Armv6-M CPU model would need to join the exclusion list; a first-class
architecture capability in Renode would be cleaner if maintainers prefer a
larger framework change. The current patch matches every Cortex-M model that
Renode exposes today.

Observed ZS407 consequence: ChibiOS checks RETTOBASE in the Cortex-M interrupt
epilogue before rescheduling. With the permanent zero, an ADC/DMA interrupt
made the application thread ready but returned to idle. Correct RETTOBASE
semantics let the unmodified binary complete startup.

The native reproduction is
[`reproductions/ret-to-base.resc`](reproductions/ret-to-base.resc). Its audited
readbacks were:

```text
Cortex-M0 / M0+ / M1 idle:  0x00000000
Cortex-M4 idle:             0x00000800
Cortex-M23 idle:            0x00000800
Cortex-M33 idle:            0x00000800
Cortex-M4 one active:       0x00000810
Cortex-M4 two active:       0x00000011
M4 after nested completes:  0x00011810
M4 after all complete:      0x00011800
```

The low bits and pending fields in the final values are expected NVIC state;
bit 11 is the value under test.

## 0002: separate STM32 IDR and ODR

The generic `STM32_GPIOPort` currently uses inherited electrical `State` for
both IDR and ODR. An ODR, BSRR, or BRR write can therefore change what IDR
reports even when the pin is configured as input, alternate function, or
analog.

The patch adds a 16-bit logical output latch and makes:

- ODR read/write the latch;
- BSRR and BRR update the latch;
- only output-mode pins drive the latch onto `State` and their GPIO
  connections;
- switching a pin into output mode drive its already-latched value;
- reset clear both electrical state and the output latch.

Regression coverage exercises input/ODR independence, input/AF/analog
non-driving behavior, a later switch to output mode, BSRR, BRR, and reset.

Observed ZS407 consequence: firmware initializes PA1-PA3 ODR high while those
active-high jog contacts remain inputs with pull-downs. The shared state made
all three contacts appear pressed during startup.

This patch does not attempt to model tri-state impedance, analog-mode IDR
special cases, or a complete STM32 pad/pull electrical network. Those are
separate modeling features, not requirements for correcting the latch.

## 0003: make BSRR set win

For STM32 BSRR, setting both the set and reset bit for one pin must leave that
pin set. The model registered the set callback before reset, so callback order
made reset win. The patch registers reset first and set second, matching the
documented priority and Renode's older STM32F1 model. Its regression writes
both halves for one pin and verifies ODR is set.

As packaged, `0003` follows `0002` because it uses the new output-latch
helper and extends the same test class. It should normally be the second commit
in the same GPIO PR. If maintainers want the tiny priority fix first, it can be
rebased mechanically onto current master without the latch change.

## Verification matrix

All checks below ran on macOS Arm64 with .NET 8 against the patched full Renode
checkout:

| Check | Result |
| --- | --- |
| `dotnet format --verify-no-changes` on all four touched C# files | Pass |
| Infrastructure Peripherals tests | 98 passed, 5 skipped, 0 failed |
| Renode integration tests | 273 passed, 6 skipped, 0 failed |
| Core unit tests | 605 passed, 6 skipped, 0 failed |
| STM32F072B Robot platform tests | 6 passed |
| STM32F4 Discovery Robot platform tests | 12 passed |
| Native M0/M0+/M1/M4/M23/M33 RETTOBASE reproduction | Pass |
| Exact immutable ZS407 image: boot, jog, touch, normal UI, 450 MHz RF tone | Pass |
| Normal full native Renode build | Pass |

The only `--werror` failure was a pre-existing unreachable-code warning in
the no-GUI `BitmapImageExtensions` build; none came from these patches.

The repository's exact-image integration check is:

```bash
tools/test-digital-twin.sh --full
```

The project-local GPIO compatibility model now also implements set-wins BSRR
semantics, and the same full ZS407 scenario passes after that alignment.

## Publication sequence

Renode's [contribution guide](https://github.com/renode/renode/blob/master/CONTRIBUTING.md)
requests an issue before implementation and a branch carrying the issue
number. The clean publication path is therefore:

1. Re-fetch and rebase onto current `renode-infrastructure` master.
2. Open one concise `renode/renode` issue for RETTOBASE and one for STM32 GPIO
   semantics, unless maintainers ask for a single issue.
3. Sign the CLA if GitHub reports it missing.
4. Submit the NVIC patch as one PR.
5. Submit the two GPIO commits as a separate PR.
6. Repeat the targeted, full managed, Robot, and ZS407 matrices.
7. Keep discussion and commits under the PhysicistJohn identity.

The technical recommendation is to upstream all three. The remaining gate is
process/hardware confirmation, not a known correctness defect in the patches.

Primary register references used in the audit are Arm's
[Cortex-M4 Devices Generic User Guide](https://documentation-service.arm.com/static/5f2ac76d60a93e65927bbdc5)
and ST's
[STM32F303 reference manual RM0316](https://www.st.com/resource/en/reference_manual/DM00043574.pdf).
