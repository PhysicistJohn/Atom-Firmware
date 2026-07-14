# Vendor upstream delivery queue

This is the publication handoff for findings made while qualifying the ZS407
digital twin and porting the firmware to ChibiOS 21.11.5. It separates code
that is already public, code that is ready to prepare for a vendor, and local
test infrastructure that must not be sent upstream.

Status was checked against the public repositories on 2026-07-14. This audit
was read-only: it did not open an issue, publish a branch, comment, or push.

## Disposition at a glance

| Vendor | Item | Disposition |
| --- | --- | --- |
| tinySA | Seven focused safety/build fixes | Already open as PRs #156 through #162; do not duplicate |
| tinySA | ChibiOS 21.11.5 application port | Exact simulation is complete; hold until exact-image hardware qualification, then rebase, rebuild, requalify, and submit as a separate RTOS-port PR |
| tinySA | Current zero-span time grid | New focused application correctness fix; exact simulator evidence is complete, but publish only after the exact RC4 hardware run |
| tinySA | Deterministic warm-reset backup checksum | New focused application bug fix; retain separately from the RTOS port and publish only after exact hardware reset testing |
| tinySA | Stack-safe MSP/PSP hard-fault entry | New focused application fix; simulator-qualified, but hold for forced-fault and recovery testing on hardware |
| tinySA | Sweep/display timing recovery and explicit single-precision constants | Keep in the ChibiOS port because these changes preserve baseline timing under the new RTOS build |
| ChibiOS | STM32F0 TIM14 GPT ISR | New upstream bug; prepare one issue and a `main` PR, then let the maintainer select a `stable-21.11.x` backport |
| Renode | NVIC `RETTOBASE` | Already open as PR #217; do not duplicate |
| Renode | STM32 GPIO IDR/ODR and BSRR priority | Already open as the two commits in PR #218; do not duplicate |
| Renode | Architectural HardFault priority | New issue in `renode/renode`, followed by one issue-numbered infrastructure PR; keep separate from #217 |
| Renode | Local DMA peer-channel heuristic | **Not for upstream**; upstream Renode already models SPI RX DMA requests through GPIO request lines |
| Renode | STM32F3 SPI-v2/data packing and channel DMA | Possible future feature, after it is redesigned around Renode request lines and focused tests |
| Renode | ST7796S GRAM readback | Possible future *new peripheral model*; there is no upstream ST7796S file to patch |
| Renode | STM32F303 USB device/host fixture | Keep local until the controller is separated from the deterministic host fixture |
| Renode | Timer UIF semantics | No action; current upstream already has the correction |
| Any vendor | CAL/RF fixtures, SRAM self-test driver, USB host scenario | Repository-specific qualification infrastructure; do not upstream |

## 1. tinySA application maintainer

Authoritative repository: <https://github.com/erikkaashoek/tinySA>

The public `main` branch remained at
`c97938697b6c7485e7cab50bca9af76996b7d671` when this queue was checked.
GitHub still reports every existing contribution as open, and it has generated
a merge ref for each one against that current `main`. None has a public review
or maintainer comment. The repository exposes no status-check contexts for
these heads; that is different from a failing check.

### Already published queue

| Order | PR | Public head | Local preparation commit | Purpose |
| ---: | --- | --- | --- | --- |
| 1 | [#156](https://github.com/erikkaashoek/tinySA/pull/156) | `1836ad672c9f6b7ca3a36f2b88c89b3ee903c85e` | `08caa12` | Keep CI on the pinned ChibiOS gitlink |
| 2 | [#157](https://github.com/erikkaashoek/tinySA/pull/157) | `52d7b0809182ccc875d0afc2bfaa4ccfb4ce8e32` | `46dc0d8` | Reject unknown firmware targets |
| 3 | [#158](https://github.com/erikkaashoek/tinySA/pull/158) | `2a3a2df14283a840f8e650c655296332eea8186a` | same | Derive the hardware-version table length |
| 4 | [#159](https://github.com/erikkaashoek/tinySA/pull/159) | `1d518aff448b462cf52b39b95be90d9abfb22520` | same | Reject invalid scan point counts |
| 5 | [#160](https://github.com/erikkaashoek/tinySA/pull/160) | `6cba8a9aafdc6273aeffb814f2131605dc22d267` | same | Validate correction-table arguments |
| 6 | [#161](https://github.com/erikkaashoek/tinySA/pull/161) | `5a029f907a12e5e8f85e7dc57d311912b9efd36a` | same | Validate shell-controlled array indices |
| 7 | [#162](https://github.com/erikkaashoek/tinySA/pull/162) | `89e5d11e83c48c6a9cb72c9474f3a556a4935a4b` | same | Bound remote keypad text |

Keep these as independent PRs. The public commits for #156 and #157 were
recreated during publication, which is why their public hashes differ from
the local preparation branches. The code intent and verification recorded in
`docs/UPSTREAM.md` and `upstream-patches/tinysa/README.md` remain the source of
truth.

Recommended action is to wait for maintainer feedback rather than add another
small PR to the existing review queue. If `main` advances, refresh only the PR
that becomes conflicted or is explicitly requested by the maintainer.

### ChibiOS 21.11.5 application port

The isolated port and selected RC4 release lineage are represented by:

- base port commit
  `751b62257e9d04fc29a3debc9c74c490628069ee`;
- initial boot/USB qualification documentation commit `ed558b3`;
- official ChibiOS tag `ver21.11.5` at
  `f4bbadf964fc746aef8bbcf34135c7d8fabb8eae`;
- local ChibiOS compatibility commit
  `2b8f425d26a61a7887916f7052b401f9e767a949` on top of that tag;
- timing/display recovery commit `67948e1`;
- deterministic-state and release-diagnostic commit `80161c7`;
- corrected extended-FPU core-frame commit `eae9983`;
- rejected RC3 gate commit
  `134ccdeaf710f5266bb8b1e447e0c915385566ea`;
- self-test timing, trace-preservation, and current zero-span-grid implementation
  `f7b0d5c6a6894655108cd6e8626d56ff25ad76ee`;
- exact audited RC4 package commit
  `f5f912c1bdc95b785dcbde85495aa5153fe0721a`.

The base port commit changes 21 files (449 insertions and 203 deletions); the
later commits add qualification-driven timing, state, diagnostic, and display
corrections. It is a coupled RTOS migration, not an appropriate addition to any
of the seven safety PRs.

Current build evidence with Arm GNU 11.3.Rel1 is:

| Target | Bytes | Flash use | SHA-256 |
| --- | ---: | ---: | --- |
| F303 RC4 | 193,948 | 78.92% of 240 KiB | `17fa401eac68e514c99fdb55ed0c106601107b4c973876aa28d18993aee22fae` |
| F072 compatibility | 115,188 | 96.97% of 116 KiB | `01f4fb2ad5d7296a67bc987dd7276f4287192146cfdd4432421d11b87a3200d0` |

The builder produced two byte-identical clean builds of all six retained
artifacts (BIN/ELF/HEX/MAP/LIST/DMP) for both targets, with zero compiler
warnings and zero undefined symbols. A hostile-environment rebuild reproduced
the same F303 hash after poisoning the caller's output-directory, optimization,
FPU, define, phase, version, and compiler variables. The exact F303 image passed
boot, jog, touch, a visibly non-flat 445.9 MHz RF tone, all fourteen positive
self-tests, disconnected-CAL failure/recovery, and the complete USB
enumeration/CDC/STALL/reset matrix.

The authoritative paired visual run captured the direct pre-ChibiOS
`lab-v0.2.0-protocol` ancestor (`d12bd826`, BIN SHA-256
`a1dbaa03978a25b2a8b2a0e85f60029a6cc736481732eff68e93362724683dd7`)
and RC4 result screen plus all four 450-point trace planes for every case. This
is the port's behavioral baseline, not the official `c979386` rollback image.
Cases 1..11 and 14 passed the strict visual comparator. Cases 12 and 13 passed
the additive `mathematically-better-time-grid` classifier: RC4's observed grid
columns exactly match its completed sweep time, the lab baseline is demonstrably
stale, and every changed pixel is an expected grid intersection or bounded time
label. All fourteen 7,200-byte trace matrices are byte-identical between the
baseline and RC4, including the non-flat filter and gain responses. Physical
qualification is still required. The F072 image has only 3,596 bytes of flash
headroom and remains a release constraint.

The simulation-sealed package contains a 220-entry `SHA256SUMS` inventory with
SHA-256
`bc221054ff0a80954f59dce844f19328d6e3d01321bbffa843ae564d25844360`.
Its manifest remains `hardware_qualified=false`, and `HARDWARE_PENDING` names
the physical screenshot, RF, USB, reset, forced-fault, and recovery gates.

Publication dependencies, in order:

1. Retain the completed hash-bound twin evidence: symbol profile, paired
   all-14 visual/trace captures, UI/RF, USB/reset, runtime-state, and fault
   scenarios.
2. Qualify the exact packaged F303 binary on the physical device, including
   recovery/DFU, cold boot, complete self-test with paired screenshot review,
   USB traffic, controls, touch, acquisition, RF behavior, warm/cold/power-cycle
   retention, and forced PSP/MSP fault recovery. Preserve the exact binary hash
   in evidence.
3. Make the TIM14 ChibiOS fix publicly fetchable. Prefer the authoritative
   ChibiOS `main` fix and its selected stable backport. A parent repository
   must never point at the current local-only `2b8f425d` gitlink.
4. In the port PR, change `.gitmodules` from the historical
   `edy555/ChibiOS` fork to the authoritative
   `chibios-upstream/chibios` repository and remove the obsolete
   `branch = I2SFULLDUPLEX` hint. The port no longer consumes that fork delta.
5. Rebase the port after the seven focused PRs, because the migration touches
   `Makefile`, `main.c`, `sa_core.c`, and `ui.c`, which can overlap their
   changes.
6. Rebuild both targets and rerun the exact candidate gates after the rebase.
7. Recreate the public commit with the PhysicistJohn noreply identity. The
   local port commits contain a workstation-local author email and must not be
   published verbatim.

The recommended submission is one clearly labeled RTOS-port PR containing the
submodule URL/gitlink transition and the coupled application API migration.
Put detailed build and hardware evidence in the PR description, but do not add
generated BIN/ELF/MAP files unless the maintainer requests release artifacts.

Do not send the broad fork commit `ade76dea8` ("DiSlord improvements") or the
old `67fdcd8ed` linker alignment change. The former combines unrelated
CMSIS/HAL/USB/serial changes; the latter is superseded by 21.11.5's
`ALIGN_WITH_INPUT` rules. Do not mix the digital-twin fixtures into the
application port.

### New tinySA findings from RC4 qualification

Keep the following three fixes independent of the RTOS-port review. They are
application defects present in the legacy code, not ChibiOS defects.

**Current zero-span time grid.** The legacy grid is calculated before the
completed CW sweep replaces `actual_sweep_time_us`, so the displayed time-axis
columns can describe the previous measurement. RC4 calculates the exact
`(offset,width,span)` tuple from the completed sweep, uses 64-bit arithmetic
until the final division, and redraws only if that tuple changed. In paired
cases 12 and 13, expected and observed columns match exactly while the baseline
columns are stale; every framebuffer delta is explained by relocated grid
intersections or bounded time text, and the four trace planes remain
byte-identical. Prepare this as a focused application PR after the same RC4
binary passes the physical self-test and display checks. Do not bundle the
simulator classifier or test-specific activity thresholds.

**Deterministic backup checksum.** `Thread1` copied a stack-local `backup_t`
into RTC backup storage after checksumming all bytes except the checksum byte,
but the packed structure's reserved byte was never initialized. Optimized
builds could therefore persist a checksum over indeterminate data and reject
otherwise valid analyzer settings after reset. RC4 zero-initializes the entire
structure before assigning fields. The digital twin preserved the configured
123,456,789..987,654,321 Hz range and 9 dB attenuation across an MCU reset,
including a deterministic reserved byte. Prepare this as a tiny one-line
correctness PR only after the exact image also passes physical warm/cold reset
and power-cycle tests.

**Hard-fault entry.** The legacy handler marks ordinary C containing locals,
calls, and an infinite loop as `naked`, reads PSP unconditionally, and does not
reliably preserve r4-r11. RC4 uses an assembly-only EXC_RETURN MSP/PSP selector,
saves r4-r11 on the 1 KiB main stack, then tail-branches to a normal noreturn C
diagnostic. A forced PSP fault with active FPU state proved that the Cortex-M4
core frame is already at the selected stack pointer; an attempted 72-byte
adjustment was rejected because it reported PC as zero. Submit the final
minimal veneer as its own PR only after both PSP/thread and MSP/handler faults,
LCD diagnostics, stack canaries, reset, and DFU recovery pass on hardware.

The explicit `-fsingle-precision-constant` policy, fast-sweep timer-read
gating, factory-self-test scratch preservation, and three narrowly selected
display hot paths belong in the ChibiOS port. Together they restore paired
self-test timing, trace planes, and display throughput under the newer
kernel/compiler rules; splitting them out would leave the port with a known
performance regression. Do not propose whole-firmware `-O3`, strict-aliasing
changes, or the simulator's activity thresholds upstream.

## 2. ChibiOS

Authoritative repository: <https://github.com/chibios-upstream/chibios>

This is a newly designated authoritative Git repository. Do not send the fix
to the older `ChibiOS/ChibiOS` community mirror. At audit time:

- contribution target `main`: `fbbfad31a4b800f3be826afc5ad19266d15f7610`;
- maintenance branch `stable-21.11.x`:
  `eb9a832bc52f22d9bae012c3b33cbb3f8aad9d5b`;
- release tag consumed by this port: `ver21.11.5` / `f4bbadf964...`.

The repository's pull-request template requires all changes to land on `main`
first. A stable branch receives only a maintainer-selected backport of a commit
already merged on `main`.

### STM32F0 TIM14 GPT ISR defect

When an STM32F0 application enables `STM32_GPT_USE_TIM14`, current `main`,
`stable-21.11.x`, and `ver21.11.5` reach:

```text
#error "TIM14 ISR not defined by platform"
```

in `os/hal/ports/STM32/LLD/TIMv1/hal_gpt_lld.c`. STM32F0 declares the
standalone `STM32_TIM14_HANDLER`/`STM32_TIM14_NUMBER`, so the driver otherwise
has everything it needs. Commit
`00091c7aab1e5b327ca291d40a31b82b9767635c` removed the generic TIM14 handler
in 2019 while adding TIM10/TIM13 support; the F0 standalone-vector case was
left without a provider.

Local commit `2b8f425d26a61a7887916f7052b401f9e767a949` restores the handler and is the
only ChibiOS delta required by the tinySA dual-target port. Its patch applies
cleanly to authoritative `main` at `fbbfad31` and `stable-21.11.x` at
`eb9a832b`. No matching issue or PR existed in the authoritative repository
when checked.

Do not publish `2b8f425d` verbatim: it carries a workstation-local author
email and a tinySA-specific source comment. Prepare a fresh, vendor-neutral
commit that restores the pre-`00091c7aa` handler shape:

- validate `STM32_TIM14_HANDLER`;
- define `OSAL_IRQ_HANDLER(STM32_TIM14_HANDLER)`;
- call `gpt_lld_serve_interrupt(&GPTD14)` between the normal OSAL IRQ prologue
  and epilogue;
- retain the existing `STM32_GPT_USE_TIM14` and
  `STM32_TIM14_SUPPRESS_ISR` guards.

Minimal reproducer and evidence for the issue/PR:

1. Start from authoritative `main` and configure an STM32F072 build with
   `HAL_USE_GPT=TRUE` and `STM32_GPT_USE_TIM14=TRUE`.
2. Show the unpatched compile stopping at the exact `#error` above.
3. Apply the one-file handler restoration and build the same target cleanly.
4. Run `tools/style/stylecheck.py` on the changed C file.
5. Build a relevant Cortex-M0 target, preferably
   `RT-STM32F072RB-NUCLEO64`, with GPTD14 linked and referenced so the handler
   cannot be discarded.
6. Include the already completed tinySA F072 and F303 zero-warning builds as
   external integration evidence. If F072 hardware is available, verify a
   GPTD14 periodic callback and its configured priority; do not claim that
   evidence until it exists.

Recommended publication order:

1. Open one concise issue in `chibios-upstream/chibios` with the compiler
   reproduction, affected branches, STM32F0 vector definitions, and regression
   commit.
2. Create a fresh branch from `main` and submit the one-file, vendor-neutral
   fix, linked to the issue. Complete the PR template's style and ARM build
   gates.
3. After the main PR merges, let the maintainer select or request the
   `stable-21.11.x` backport for the future 21.11.6 release. Do not open the
   stable PR first.
4. Once a public commit is available, update the tinySA port gitlink and repeat
   its build/qualification gates.

Only this TIM14 defect belongs in the ChibiOS queue. The multi-file tinySA
application adaptation belongs to tinySA, and the historical fork's mixed
`ade76dea8` changes do not belong in either ChibiOS PR.

## 3. Renode

Model fixes target <https://github.com/renode/renode-infrastructure>, while
the contribution workflow tracks their issues in
<https://github.com/renode/renode>. It requires an issue and an
issue-numbered infrastructure branch before a PR. Current infrastructure
`master` was `7068985cd454911e4137bbffcce177fd7b488950` when status was
checked.

### Already published queue

| Order | Issue / PR | Public commits | Live status |
| ---: | --- | --- | --- |
| 1 | [issue #941](https://github.com/renode/renode/issues/941) / [PR #217](https://github.com/renode/renode-infrastructure/pull/217) | `297ee9f670291d6c5daf89ab612a14bc146bdaf5` | Open; current-master merge ref exists; CLA success; only CLA bot comment, no review |
| 2 | [issue #942](https://github.com/renode/renode/issues/942) / [PR #218](https://github.com/renode/renode-infrastructure/pull/218) | `d7337a1a3fc7bbabfe436aa4f1dd0501034af456`, then `12d2d3f66714c276de36865ccbd063d7eaed3790` | Open; current-master merge ref exists; CLA success; no comments or review |

PR #217 implements NVIC `ICSR.RETTOBASE`. PR #218 first separates STM32 GPIO
IDR from ODR and then makes simultaneous BSRR set/reset resolve to set. The
latest generated merge refs have current `master` as their first parent, so
there is no observed merge conflict. Do not create duplicates or add unrelated
model changes to either PR. Wait for review and rebase only if GitHub later
reports a conflict or a maintainer requests it.

### Architectural HardFault priority: new issue and PR

The RC4 nested-handler qualifier exposed a distinct NVIC modeling defect.
Cortex-M assigns HardFault a fixed architectural priority above every
configurable interrupt, but the current model represents it with numeric
priority zero. A configurable IRQ also left at priority zero therefore cannot
be preempted by HardFault. The local qualification scenario must assign the
outer IRQ priority `0x80` to exercise the correct nested MSP path.

This is not part of `RETTOBASE` PR #217. Open a new issue in
`renode/renode`, then prepare one issue-numbered `renode-infrastructure` PR
that gives HardFault its fixed priority. Focused tests should prove:

- HardFault preempts a configurable priority-zero IRQ;
- NMI still preempts HardFault;
- `PRIGROUP` does not make a configurable interrupt outrank HardFault;
- behavior is correct across the supported Cortex-M/Arm versions;
- `PRIMASK`, `BASEPRI`, and `FAULTMASK` retain their architectural effects.

The RC4 PSP and nested-MSP scenarios are integration evidence, not a substitute
for managed NVIC unit tests. No matching public issue or PR existed when this
queue was checked.

### DMA peer-channel heuristic: not for upstream

Commit `4dcedad` added `ServicePendingPeripheralToMemory()` to the
project-local `STM32F303Dma`. When a memory-to-peripheral channel writes a
peripheral address, it scans all enabled peripheral-to-memory channels with
the same address and services them. That unblocked LCD readback in this twin,
but it is not the right Renode abstraction and must **not** be submitted as a
DMA fix.

Upstream Renode's `STM32SPI.HandleDataWrite()` already enqueues the returned
SPI byte and calls `DMAReceive.Blink()` for each transmitted byte when RX DMA
is enabled. Upstream DMA models consume explicit peripheral request GPIOs.
The local heuristic compensates for the custom `STM32F303Spi` lacking those
request outputs; it can also spuriously service any unrelated channel that
happens to name the same peripheral address.

A future upstream contribution, if desired, should instead be an STM32F3
SPI-v2/channel-DMA feature:

- add STM32F3 to a suitable generic SPI model or introduce a reviewed SPI-v2
  variant;
- model DS=8 access-width packing, where one 16-bit DR write emits two byte
  frames least-significant byte first;
- expose `DMAReceive` and `DMASend` request lines;
- connect them to a generalized F0/F3 channel-DMA model using normal Renode
  GPIO requests, not address matching.

Open a separate design issue before implementing it. Focused tests must cover
16-bit data packing, one RX request per transmitted byte, simultaneous N-byte
TX/RX completion, disabled RX DMA, distinct peripherals, circular mode, and
transfer-complete flags/IRQs. This work is independent of PRs #217/#218 and
should wait until those reviews are no longer being crowded.

### ST7796S: propose a new peripheral, not a readback patch

Renode infrastructure currently has no ST7796S peripheral. Therefore the
51-line `0x2E`/`0x3E` readback addition in `4dcedad` has no upstream file to
patch. It is a delta against the project-local model originally introduced in
`51c9530` and subsequently extended in `915860c`.

If Renode maintainers want the device, open a new issue first and offer the
complete, vendor-neutral ST7796S SPI display model. Separate it from
`ZS407SpiFabric`, CAL/RF behavior, framebuffer screenshots, and tinySA SRAM
control. A focused model/test PR should cover:

- reset, display on/off, address-window setup, and RGB565 memory writes;
- memory-read `0x2E` and read-continue `0x3E`;
- the required initial dummy byte;
- sequential byte order, cursor advance/wrap, and window bounds;
- the supported MADCTL orientation behavior;
- chip-select/end-of-transaction state reset.

The complete tinySA self-test case 12 is useful integration evidence, but it
does not replace managed unit tests for the new model.

### Deferred Renode work

The project-local STM32F303 USB class combines an F303 PMA device controller
with a deterministic host fixture. Renode infrastructure has no corresponding
STM32 USB model, so this could become useful upstream work only after the
controller is separated from the host scenario and integrated with Renode's
USB abstractions. Do not submit the current combined class.

Do not submit another timer UIF patch: current Renode master already sets UIF
independently of UIE. USART warning boundaries, the CAL/RF fixture profiles,
the SRAM self-test symbol driver, and the scripted USB host sequence remain
project-local qualification infrastructure.

## Recommended cross-vendor order

1. Keep the simulation-sealed RC4 hash fixed and complete its physical
   qualification before calling it hardware-qualified.
2. Leave tinySA PRs #156-#162 and Renode PRs #217/#218 alone pending review.
3. Publish the ChibiOS TIM14 issue and `main` PR when explicitly authorized.
4. When explicitly authorized, publish the separate Renode HardFault-priority
   issue and issue-numbered infrastructure PR.
5. After the TIM14 fix is public (and a stable backport is selected), update and
   requalify the tinySA ChibiOS port, then submit the single RTOS-port PR.
6. After the exact RC4 hardware self-test, offer the current zero-span-grid fix
   as its own tinySA correctness PR.
7. After exact hardware reset testing, offer the deterministic backup checksum
   as a separate tinySA fix if the maintainer wants another focused PR.
8. Hold the hard-fault veneer until forced PSP/MSP faults, LCD reporting, stack
   canaries, reboot and DFU recovery all pass on the physical ZS407; then offer
   it as a separate tinySA safety PR.
9. Only after the existing Renode review queue has moved, ask maintainers about
   the ST7796S new model and the broader STM32F3 SPI-v2/channel-DMA design as
   separate issues.

This ordering keeps each vendor's review boundary clear and prevents local
qualification shortcuts from becoming public emulator behavior.
