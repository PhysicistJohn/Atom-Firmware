# Upstream contribution queue

All personal development remains on the private PhysicistJohn repository.
Upstream candidates are isolated from the replacement-firmware roadmap and
carry the PhysicistJohn noreply identity.

Publication proceeds one explicitly approved contribution at a time. As of
2026-07-11, all seven tinySA packages are open as PRs
[#156](https://github.com/erikkaashoek/tinySA/pull/156),
[#157](https://github.com/erikkaashoek/tinySA/pull/157), and
[#158](https://github.com/erikkaashoek/tinySA/pull/158),
[#159](https://github.com/erikkaashoek/tinySA/pull/159),
[#160](https://github.com/erikkaashoek/tinySA/pull/160),
[#161](https://github.com/erikkaashoek/tinySA/pull/161), and
[#162](https://github.com/erikkaashoek/tinySA/pull/162). Renode PRs
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

That isolated port is now complete on `codex/chibios-latest` at `ed558b3`
(implementation commit `751b622`). Both F303 and F072 build with zero warnings
on pinned GNU 11.3.1, and the F303 candidate reproduces the qualified twin boot
signature and passes USB enumeration/CDC/reset qualification. Only one ChibiOS
delta proved necessary: local commit `2b8f425d` restores the generic STM32F0
TIM14 GPT ISR that F072 uses as `DELAY_TIMER`. Treat it as a focused upstream
fix or carried hotpatch; do not replace it by disabling TIM14. The F072 image
is already at 96.76% of its 116 KiB flash region, so further upstream growth is
a release constraint.

## Renode

Three emulator fixes are packaged under
[`upstream-patches/renode/`](../upstream-patches/renode/README.md) against
`renode-infrastructure`
`1c3c1c1f9f1a1c4c7b7302bca3a37b9aa361c7a2`.

| Candidate | Observable failure | Recommended PR |
| --- | --- | --- |
| NVIC `ICSR.RETTOBASE` | Armv7/Armv8 bit always read zero; ChibiOS could not reschedule from the ZS407 startup IRQ | One NVIC PR |
| Independent STM32 IDR/ODR | ODR initialization falsely asserted input-mode jog contacts | GPIO PR, commit 1 |
| STM32 BSRR set priority | Simultaneous set/reset incorrectly let reset win | GPIO PR, commit 2 |

The completed self-test has now exposed two additional candidates. A
full-duplex STM32 SPI transmit request must also clock the paired RX DMA
channel, and an ST7796S model must implement GRAM read commands `0x2E`/`0x3E`
with their dummy byte and cursor advance. These fixes unblock the immutable
firmware's LCD readback test. They are proven in the project-local twin but are
not yet in the three-patch mailbox above; each needs a minimal upstream model
change and focused managed regression before publication. The CAL/RF fixture,
USB host scenario and SRAM self-test driver remain repository-specific test
infrastructure, not Renode patches.

The managed suites total 976 passes and 17 existing skips with zero failures.
Eighteen STM32 Robot scenarios pass, the native RETTOBASE matrix covers
M0/M0+/M1/M4/M23/M33, and the exact ZS407 boot/jog/touch/RF integration passes.

Renode's contribution guide asks for an issue and issue-numbered branch before
a PR. Issues 941 and 942 were opened under PhysicistJohn after explicit
approval. The NVIC change is
[PR #217](https://github.com/renode/renode-infrastructure/pull/217). The
independent-IDR/ODR GPIO change and its tightly related BSRR set-priority
follow-up are the two commits in
[PR #218](https://github.com/renode/renode-infrastructure/pull/218). Both Renode
PRs are mergeable and their CLA checks pass; neither has maintainer feedback
yet.

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

## Deferred, not queued as “obvious”

### Hard-fault entry

`hard_fault_handler_c(uint32_t *sp)` is marked `naked` but contains ordinary
C, locals, calls, and an infinite loop. Clang correctly rejects this; GCC emits
stack-relative stores without a normal allocation prologue. A correct fix needs
an assembly-only MSP/PSP veneer and a normal C diagnostic routine.

This is a real correctness concern but not a few-line, low-risk change. It
requires forced thread/handler faults, stack canaries, debugger comparison, and
hardware validation before packaging.

### Reproducible release manifest

The image embeds `__DATE__` and `__TIME__`. A release manifest should record
source/submodule commits, toolchain package, epoch, flags, sizes, and hashes.
That is useful process work, but separate from the two-line pinned-submodule
fix.

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
