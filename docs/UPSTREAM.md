# Upstream contribution queue

The exact pause/resume state for the next publication session is recorded in
[Upstream return checkpoint](UPSTREAM_RETURN_CHECKPOINT.md).

> **ChibiOS port published as a draft on 2026-07-15.** The clean public-only
> tinySA application stack is [PR #166](https://github.com/erikkaashoek/tinySA/pull/166)
> at `5e0299009f29`; the independent stable ChibiOS backports are draft
> [PR #86](https://github.com/chibios-upstream/chibios/pull/86) and
> [PR #87](https://github.com/chibios-upstream/chibios/pull/87). The temporary
> public ChibiOS integration pin is `db35f6df1370` on
> `PhysicistJohn/chibios:codex/integration-tinysa-21.11.5`. The reproducible
> public F303 BIN is 192,940 bytes with SHA-256
> `13f72e9ee9a80af170438958fc26029c516f6106c87aed9a45eea335a9a59fc9`.
> General, runtime-state, and PSP/MSP fault twin qualifiers pass with zero
> unexpected warnings; their report SHA-256 values are `d0556431e247`,
> `c27620424a44`, and `73a7fa6fe114`, respectively. Keep #166 draft until its
> ChibiOS pin is canonical and the remaining true cold-power-cycle gate is
> attached to the physical record below.

The exact clean public F303 binary was physically staged on 2026-07-15. A
one-shot alt-0 DFU download was followed by an exact 192,940-byte same-device
readback; it matched SHA-256 `13f72e9ee9a80af170438958fc26029c516f6106c87aed9a45eea335a9a59fc9`
and re-enumerated as the admitted normal USB device. The live shell reports
`tinySA4_v1.4-231-g5e02990`, `tinySA ULTRA+ ZS407`, kernel `7.0.6`, and the
STM32F303 Cortex-M4F platform.

Two complete physical all-14 runs passed, with paired 307,200-byte LCD
readbacks, all four trace planes, scheduler/runtime observations, and all
thirteen calibration/palette observations preserved. The second run's sealed
inventory is `a38149926b84`; its official-`c979386` A/B report has no failed
case and inventory SHA-256 `47ded667d49f`. Case 2 repeats proved that its
single high first sweep was transient; the standalone A/B uses a later complete
run whose lower, quieter result still contains a 70-pixel/18.58 dB robust
trace. The physical comparator now accounts for millisecond shell rounding in
zero-span grid geometry and uses absolute non-flat floors for suppression
tests; 43 focused comparator/capture tests pass. This evidence remains
diagnostic-only until a true power-off cold boot is operator-attested. The
public PR must also remain draft until the ChibiOS pin is canonical.

All personal development remains on the private PhysicistJohn repository.
Upstream candidates are isolated from the replacement-firmware roadmap and
carry the PhysicistJohn noreply identity.

Publication proceeds one explicitly approved contribution at a time. Status
was rechecked after publication on 2026-07-15: the original seven tinySA
packages remain open as PRs
[#156](https://github.com/erikkaashoek/tinySA/pull/156),
[#157](https://github.com/erikkaashoek/tinySA/pull/157), and
[#158](https://github.com/erikkaashoek/tinySA/pull/158),
[#159](https://github.com/erikkaashoek/tinySA/pull/159),
[#160](https://github.com/erikkaashoek/tinySA/pull/160),
[#161](https://github.com/erikkaashoek/tinySA/pull/161), and
[#162](https://github.com/erikkaashoek/tinySA/pull/162). The formatter,
zero-span-grid, and backup-checksum fixes are now open as tinySA PRs
[#163](https://github.com/erikkaashoek/tinySA/pull/163),
[#164](https://github.com/erikkaashoek/tinySA/pull/164), and
[#165](https://github.com/erikkaashoek/tinySA/pull/165). The ChibiOS TIM14
and USB PMA fixes are open as
[#84](https://github.com/chibios-upstream/chibios/pull/84) and
[#85](https://github.com/chibios-upstream/chibios/pull/85). Renode PRs
[#217](https://github.com/renode/renode-infrastructure/pull/217) and
[#218](https://github.com/renode/renode-infrastructure/pull/218) are open.
Packages 4 through 7 completed the physical batch documented in
[UPSTREAM_HARDWARE_RESULTS.md](UPSTREAM_HARDWARE_RESULTS.md). The primary
worktree's upstream remote remains fetch-only (`pushurl = no_push`); the
separate publication clone writes only to the PhysicistJohn public fork.

## tinySA firmware

Seven minimal patches are fully packaged under
[`upstream-patches/tinysa/`](../upstream-patches/tinysa/README.md). They target
upstream `c97938697b6c7485e7cab50bca9af76996b7d671` and pinned ChibiOS
`ade76dea89cd093650552328e881252a06486094`.

| Candidate | Independent branch | Commit | Verification | Status |
| --- | --- | --- | --- | --- |
| Reject unknown `TARGET` values | `upstream/fix-target-validation` | `46dc0d8` | Default/F072/F303 builds; invalid target fails | [PR #157](https://github.com/erikkaashoek/tinySA/pull/157) open |
| Keep CI on pinned ChibiOS | `upstream/fix-pinned-submodule-ci` | `08caa12` | YAML parse and gitlink checkout | [PR #156](https://github.com/erikkaashoek/tinySA/pull/156) open |
| Derive hardware table length | `upstream/fix-hardware-version-table` | `2a3a2df` | F072/F303 build; exact candidate flashed to ZS407; correct `V0.5.4 max2871` readback; cold-start full self-test passed | [PR #158](https://github.com/erikkaashoek/tinySA/pull/158) open |
| Reject invalid scan counts | `upstream/fix-scanraw-points` | `1d518af` | Dual reproducible build, GCC analyzer, exact-image twin, targeted ZS407 USB test and built-in self-test pass | [PR #159](https://github.com/erikkaashoek/tinySA/pull/159) open |
| Bound correction table access | `upstream/fix-correction-bounds` | `6cba8a9` | Dual reproducible build, GCC analyzer, exact-image twin, unchanged-table ZS407 test and built-in self-test pass | [PR #160](https://github.com/erikkaashoek/tinySA/pull/160) open |
| Bound shell-controlled indices | `upstream/fix-shell-index-bounds` | `5a029f9` | Dual reproducible build, GCC analyzer, exact-image twin, targeted ZS407 index test and built-in self-test pass | [PR #161](https://github.com/erikkaashoek/tinySA/pull/161) open |
| Bound remote keypad text | `upstream/fix-shell-text-bounds` | `89e5d11` | Dual reproducible build, GCC analyzer, exact-image twin, maximum-line ZS407 test and built-in self-test pass | [PR #162](https://github.com/erikkaashoek/tinySA/pull/162) open |
| Normalize exact scientific powers | `fix/scientific-format-exact-powers` | `ca5df0b` | Strict boundary reproducer; F072/F303 builds; official-hardware defect observation | [PR #163](https://github.com/erikkaashoek/tinySA/pull/163) open |
| Refresh zero-span grid from completed sweep | `fix/current-zero-span-grid` | `1a15e6e` | F072/F303 builds; formula-exact physical cases 12/13 with byte-identical trace planes | [PR #164](https://github.com/erikkaashoek/tinySA/pull/164) open |
| Initialize complete backup checksum image | `fix/deterministic-backup-checksum` | `ead2a0a` | F072/F303 builds; physical warm-reset sentinel retention | [PR #165](https://github.com/erikkaashoek/tinySA/pull/165) open; cold power-cycle sentinel unmeasured |

The tested aggregate is
`physicistjohn/upstream-firmware-fixes` at
`bece91ea29adc86ee2cd4804c6d8be407526f35e`. A clean mailbox reapplication
produces the same source tree, GCC 11.3.Rel1 builds both targets, GCC
`-fanalyzer` reports no analyzer diagnostic, and the F303 image boots in the
exact ZS407 twin with the same initial peripheral transaction counts as
untouched upstream.

The full patch rationale, artifact hashes, exact sizes, A/B twin result, and
physical test script are in the queue README. Keep these as separate PRs; they
are easier to review and revert individually.

### ChibiOS consumption audit

The current firmware pin is the tinySA fork commit
`ade76dea89cd093650552328e881252a06486094`. The upgrade candidate is the
official ChibiOS stable tag `ver21.11.5`, commit
`f4bbadf964fc746aef8bbcf34135c7d8fabb8eae`, evaluated in an isolated
worktree before changing the release line.

Do not replay fork commit `ade76dea8` (`DiSlord improvements`) wholesale: it
mixes CMSIS, build rules, HAL queues, serial, USB, ADC and USART changes that
must be justified independently against the newer tree. Likewise, the old
`67fdcd8ed` linker change from 16-byte to 4-byte `.text` subalignment is
superseded by `ver21.11.5`'s `ALIGN_WITH_INPUT` linker rules. Preserve only a
small fork delta when the dual-target build, executable twin or hardware
qualification proves it is still required.

RC4 is rejected by physical evidence. Its exact 193,948-byte F303 image
(`17fa401eac68e514c99fdb55ed0c106601107b4c973876aa28d18993aee22fae`)
flashed and cold-booted, but macOS stopped at `UsbEnumerationState=2`, created
no `IOUSBHostInterface` child and no `/dev/cu.usbmodem*`, and repeated the
failure after a cable unplug/replug. The old simulator scenario had selected
configuration 1 only once, so it did not expose the allocator defect.

The replacement RC5 build is implementation commit `d4c7ec8c2a6d` with
audited release-tooling commit `6fdf6f307ecb`. Two clean builds reproduce all
six retained outputs with zero warnings and zero undefined symbols on pinned
Arm GNU 11.3.Rel1. The 193,980-byte F303 image has SHA-256
`1e3f45a9744b18985622d5abf6c2445524a4ad53a831316766c37de80ac96685`;
the 115,236-byte F072 compatibility image has SHA-256
`7e00dc013a81fd85e5a86911e7a1ac5781cb17d177bd0560689bc5041e36ea0f`
and only 3,548 bytes free in its 116 KiB flash region.

RC5 carries exactly two focused ChibiOS commits on `ver21.11.5`. Local commit
`2b8f425d` restores the generic STM32F0 TIM14 GPT ISR that F072 uses as
`DELAY_TIMER`; do not replace it by disabling TIM14. Local commit `b3f82b396`
fixes USBv1 endpoint packet-memory reuse when
`usb_lld_disable_endpoints()` leaves EP0 active but resets the allocation cursor
to the PMA base. The exact RC4 ELF now fails the repeated-configuration twin
gate with EP0 TX and EP1 TX both at `0x0040`; the RC5 ELF passes same-value
`1 -> 1`, explicit `1 -> 0 -> 1`, CDC, suspend/wakeup, STALL, and final bus-reset
re-enumeration. The complete gate requires five PMA-distinctness markers and
three data-endpoint-disabled markers.

The exact RC5 package has a scoped physical-runtime pass: exact-range DFU
download/readback, USB/reset behavior, cold boot, and all fourteen physical
self-tests passed. The overall manifest remains `hardware_qualified=false`
because the fresh v4 A/B preserves one first-cold case-2 threshold failure
despite three passing repeats, and physical PSP/MSP forced-fault injection was
not performed. The F072 artifact remains build evidence only.

The TIM14 correction was recreated on current/default `master` with the public
noreply identity as commit `14da3ecdf0e2` and is open as ChibiOS
[PR #84](https://github.com/chibios-upstream/chibios/pull/84). The unpatched
F072 demo reaches the exact missing-ISR error; the patched demo, POSIX
simulator, and style checks pass.

The USB correction was recreated independently as commit `f295e2908b8f` and
is open as ChibiOS [PR #85](https://github.com/chibios-upstream/chibios/pull/85).
It applies the same EP0-ownership rule to both current USBv1 and USBv2 drivers.
Current-master F303/USBv1 and G0B1/USBv2 CDC builds, the POSIX simulator, and
both style checks pass. RC5 supplies executable and physical runtime evidence
for USBv1 only; the PR explicitly does not claim USBv2 runtime hardware.

## Renode

Three emulator fixes are packaged under
[`upstream-patches/renode/`](../upstream-patches/renode/README.md) against
`renode-infrastructure`
`1c3c1c1f9f1a1c4c7b7302bca3a37b9aa361c7a2`; the fourth row is the newly
qualified finding still awaiting a fresh issue/branch package.

| Candidate | Observable failure | Recommended PR |
| --- | --- | --- |
| NVIC `ICSR.RETTOBASE` | Armv7/Armv8 bit always read zero; ChibiOS could not reschedule from the ZS407 startup IRQ | One NVIC PR |
| Independent STM32 IDR/ODR | ODR initialization falsely asserted input-mode jog contacts | GPIO PR, commit 1 |
| STM32 BSRR set priority | Simultaneous set/reset incorrectly let reset win | GPIO PR, commit 2 |
| Architectural HardFault priority | A configurable priority-zero IRQ cannot be preempted because HardFault is also modeled as numeric priority zero | New issue and separate NVIC PR |

The completed self-test also exposed gaps in the project-local STM32F3 SPI/DMA
and ST7796S models, but those local fixes are not ready-made upstream patches.
In particular, the DMA address-matching heuristic must not be submitted:
upstream Renode already emits explicit SPI RX DMA request GPIOs. A future
contribution would instead add STM32F3 SPI-v2 data packing and connect its
normal request lines to a generalized channel-DMA model, with focused managed
tests. Renode has no upstream ST7796S peripheral, so its GRAM readback support
would have to be proposed as a complete new display model rather than a small
readback patch. The CAL/RF fixture, USB host scenario and SRAM self-test driver
remain repository-specific test infrastructure. See
[`VENDOR_UPSTREAM_QUEUE.md`](VENDOR_UPSTREAM_QUEUE.md) for the exact vendor
dispositions and ordering.

The managed suites total 976 passes and 17 existing skips with zero failures.
Eighteen STM32 Robot scenarios pass, the native RETTOBASE matrix covers
M0/M0+/M1/M4/M23/M33, and the exact ZS407 boot/jog/touch/RF integration passes.

Renode's contribution guide asks for an issue and issue-numbered branch before
a PR. Issues 941 and 942 were opened under PhysicistJohn after explicit
approval. The NVIC change is
[PR #217](https://github.com/renode/renode-infrastructure/pull/217). The
independent-IDR/ODR GPIO change and its tightly related BSRR set-priority
follow-up are the two commits in
[PR #218](https://github.com/renode/renode-infrastructure/pull/218). GitHub
reports both Renode PRs cleanly mergeable and their CLA checks pass; neither
has maintainer feedback yet. Their generated merge refs are based on
`66feec8`, not current infrastructure `master` at `7068985`, so those refs are
not current-master proofs. The PR patch series do dry-run against current
`master`, with no content conflict observed. Do not add the HardFault-priority
correction to PR #217: open a new
`renode/renode` issue and issue-numbered infrastructure PR, with focused tests
for configurable priority zero, NMI, `PRIGROUP`, Arm-version coverage, and
interrupt masks.

## Exact-build finding for tinySA issue 152

The official source and submodule are sufficient to reproduce the release:

- tinySA source `c979386`;
- ChibiOS `ade76de`;
- Arm GNU 11.3.Rel1 target libraries;
- `SOURCE_DATE_EPOCH=1778074389`.

With the matching Windows target libraries, the official binary reproduces at
SHA-256
`3c9847ff4d7b80561df2f2f1030a112703a083409ffb2ee11361b2413b7c1e41`.
The macOS package preserves application symbol layout but orders some Newlib
routines differently.

If the maintainer welcomes a response, contribute a concise reproducibility
comment or small manifest—not the personal research history.

## Candidate findings still held from publication

### Current zero-span time grid

The legacy grid can remain based on the previous CW sweep because it is
calculated before `actual_sweep_time_us` is updated. RC5 calculates and applies
the exact grid tuple from the completed sweep, with 64-bit arithmetic through
the final division and no redraw when the tuple is unchanged. Paired cases 12
and 13 prove formula-exact columns, zero unexplained framebuffer pixels, and
byte-identical trace memory against the pinned pre-ChibiOS
`lab-v0.2.0-protocol` behavioral baseline (commit `d12bd826`; BIN SHA-256
`a1dbaa03978a25b2a8b2a0e85f60029a6cc736481732eff68e93362724683dd7`).
The supplemental official `c979386` comparison independently reproduces the
same conclusion: cases 1..11 and 14 pass strictly, all fourteen trace matrices
are byte-identical, and cases 12/13 contain only formula-current grid and
bounded time-text changes with zero unexplained pixels. Keep this as a focused
tinySA application PR after the exact RC5 hardware self-test; do not include
the local simulator classifier.

### Hard-fault entry

`hard_fault_handler_c(uint32_t *sp)` is marked `naked` but contains ordinary C,
locals, calls, and an infinite loop. Clang correctly rejects this; GCC emits
stack-relative stores without a normal allocation prologue. RC5 uses an
assembly-only EXC_RETURN MSP/PSP selector, saves r4-r11, and tail-branches to a
normal C diagnostic routine on a 1 KiB main stack.

Simulator fault injection rejected one incorrect intermediate design: an
extended floating-point exception still places the core R0..xPSR frame at the
selected stack pointer, so adding 72 bytes made the reported PC zero. The
corrected entry must still pass forced thread/handler faults, stack canaries,
LCD reporting, reset and DFU recovery on physical hardware before it becomes a
separate tinySA PR.

### Deterministic warm-reset checksum

The RTC backup checksum included a reserved byte from an uninitialized
stack-local `backup_t`. RC5 initializes the complete structure before assigning
fields, and the digital twin preserves the configured range and attenuation
across an MCU reset. Keep this one-line application fix independent of the
ChibiOS port, but do not publish it until the exact image passes warm reset,
cold reset and power-cycle checks on hardware.

### Reproducible release manifest

RC5 closes this process gap: although the image embeds `__DATE__` and `__TIME__`,
the builder fixes `SOURCE_DATE_EPOCH`, and the sealed manifest records source
and submodule commits, toolchain, epoch, flags, sizes, hashes, and qualification
state. Offer any equivalent upstream process change separately from PR #156.

### Licensing clarity

Application files mostly state GPL-3.0-or-later, while the repository combines
several notices and has no root aggregate license file. Ask the maintainer what
statement they intend before proposing `LICENSE`, `COPYING`, or an SPDX
sweep.

### Larger firmware work

LLVM support, warning cleanup, async/interrupt redesign, DMA, RF/DSP
optimization, display replacement, and waveform generation belong to this
repository's staged replacement-firmware program. They are not upstream
bug-fix candidates in the present queue.

## Publication checklist

For each future contribution:

1. Fetch and rebase onto the then-current upstream branch.
2. Keep one observable defect per branch/PR.
3. Re-run the applicable full build/test matrix.
4. Capture the required ZS407 USB or UI evidence for runtime changes.
5. Exclude generated binaries unless the maintainer explicitly requests them.
6. Use `PhysicistJohn <54456354+PhysicistJohn@users.noreply.github.com>`.
7. Push only to the PhysicistJohn fork, never with the Keysight identity.
8. Wait for explicit approval before creating any public issue, PR, or comment.
