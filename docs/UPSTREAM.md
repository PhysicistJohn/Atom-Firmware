# Upstream contribution queue

All personal development remains on the private PhysicistJohn repository.
Upstream candidates are isolated from the replacement-firmware roadmap and
carry the PhysicistJohn noreply identity.

Nothing in this queue has been published, discussed upstream, or flashed to
hardware. The upstream remote is fetch-only (`pushurl = no_push`); the only
writable remote is the private PhysicistJohn repository.

## tinySA firmware

Seven minimal patches are fully packaged under
[`upstream-patches/tinysa/`](../upstream-patches/tinysa/README.md). They target
upstream `c97938697b6c7485e7cab50bca9af76996b7d671` and pinned ChibiOS
`ade76dea89cd093650552328e881252a06486094`.

| Candidate | Independent branch | Commit | Verification | Remaining gate |
| --- | --- | --- | --- | --- |
| Reject unknown `TARGET` values | `upstream/fix-target-validation` | `46dc0d8` | Default/F072/F303 builds; invalid target fails | None |
| Keep CI on pinned ChibiOS | `upstream/fix-pinned-submodule-ci` | `08caa12` | YAML parse and gitlink checkout | None |
| Derive hardware table length | `upstream/fix-hardware-version-table` | `2a3a2df` | F072/F303 build; ELF has four records | ZS407 version page/command |
| Reject invalid scan counts | `upstream/fix-scanraw-points` | `1d518af` | F072/F303 build; static audit | USB boundary transcript |
| Bound correction table access | `upstream/fix-correction-bounds` | `6cba8a9` | F072/F303 build; static audit | USB mutation/boundary transcript |
| Bound shell-controlled indices | `upstream/fix-shell-index-bounds` | `5a029f9` | F072/F303 build; static audit | USB command transcript |
| Bound remote keypad text | `upstream/fix-shell-text-bounds` | `89e5d11` | F072/F303 build; static/string audit | Maximum-line USB test |

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

The managed suites total 976 passes and 17 existing skips with zero failures.
Eighteen STM32 Robot scenarios pass, the native RETTOBASE matrix covers
M0/M0+/M1/M4/M23/M33, and the exact ZS407 boot/jog/touch/RF integration passes.

Renode's contribution guide asks for an issue and issue-numbered branch before
a PR. Rebase first, then open separate NVIC and GPIO issues under
PhysicistJohn. Do not send them until the publication gate is lifted.

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
