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
| tinySA | ChibiOS 21.11.5 application port | RC5 is reproducibly built and its complete exact-image simulator seal passes; hardware qualification remains pending |
| tinySA | Current zero-span time grid | New focused application correctness fix; inherited exact simulator evidence is complete, but publish only after the exact RC5 hardware run |
| tinySA | Deterministic warm-reset backup checksum | New focused application bug fix; retain separately from the RTOS port and publish only after exact hardware reset testing |
| tinySA | Stack-safe MSP/PSP hard-fault entry | New focused application fix; simulator-qualified, but hold for forced-fault and recovery testing on hardware |
| tinySA | Sweep/display timing recovery and explicit single-precision constants | Keep in the ChibiOS port because these changes preserve baseline timing under the new RTOS build |
| ChibiOS | STM32F0 TIM14 GPT ISR | New upstream bug; seek maintainer guidance or use the ChibiOS SourceForge support path, then prepare one vendor-neutral change for the requested integration branch and let the maintainer select any stable backport |
| ChibiOS | USB PMA reuse across `SET_CONFIGURATION` | Confirmed USBv1 defect on 21.11.5 and confirmed analogous USBv2 pattern on current `master`; prepare a separate USB change that reviews and corrects both maintained PMA drivers, with repeated-configuration and reset regressions |
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

The isolated port retains the original application-port lineage through RC4,
then adds a focused RC5 correction:

- base port commit
  `751b62257e9d04fc29a3debc9c74c490628069ee`;
- official ChibiOS tag `ver21.11.5` at
  `f4bbadf964fc746aef8bbcf34135c7d8fabb8eae`;
- local TIM14 compatibility commit
  `2b8f425d26a61a7887916f7052b401f9e767a949`;
- self-test timing, trace-preservation, and current zero-span-grid implementation
  `f7b0d5c6a6894655108cd6e8626d56ff25ad76ee`;
- rejected RC4 package commit
  `f5f912c1bdc95b785dcbde85495aa5153fe0721a`;
- RC5 USB PMA implementation commit
  `d4c7ec8c2a6df9887bb0ab306346ebbf47688eef`;
- local ChibiOS USBv1 correction
  `b3f82b396de7cf2a9e85bc8f1575fbd58e9428d9`; and
- audited RC5 release-tooling commit
  `6fdf6f307ecb0cef2e3af478b0fc7b80a1fd13e2`.

The base port is a coupled RTOS migration, not an appropriate addition to any
of the seven published safety PRs. The TIM14 and USB allocator changes are
independent ChibiOS defects and are packaged separately for that vendor.

Current reproducible-build evidence with Arm GNU 11.3.Rel1 is:

| Target | Bytes | Flash use | SHA-256 |
| --- | ---: | ---: | --- |
| F303 RC5 | 193,980 | 78.93% of 240 KiB | `1e3f45a9744b18985622d5abf6c2445524a4ad53a831316766c37de80ac96685` |
| F072 compatibility | 115,236 | 97.01% of 116 KiB | `7e00dc013a81fd85e5a86911e7a1ac5781cb17d177bd0560689bc5041e36ea0f` |

Two clean builds reproduced BIN/ELF/HEX/MAP/LIST/DMP for both targets with
zero compiler warnings and zero undefined symbols. The F303 ELF SHA-256 is
`d742ba7dc33a71db83a2bb2ffa8b0cb67977977555c507d1e663aebc6051fa56`;
the simulator symbol-profile SHA-256 is
`44c1c0b0d2efca014babe49efc2c7832f162675e06b6832bf52c6b9cfa3876e8`.
The F072 image has only 3,548 bytes of flash headroom.

RC4's earlier all-fourteen twin evidence remains useful for the unchanged
application behavior, including shaped, non-flat traces and the exact-or-better
time-grid classification. It is not RC5 release evidence. RC4 was rejected
after its exact binary flashed and cold-booted on the ZS407 but failed physical
USB configuration: macOS identified `0483:5740`, remained at
`UsbEnumerationState=2`, created no `IOUSBHostInterface` child and no
`/dev/cu.usbmodem*`, and did the same after a physical cable unplug/replug.

The failure is deterministic. USBv1's endpoint-disable path leaves EP0 active
but resets the packet-memory cursor to `0x0040`. The next configuration assigns
EP1 TX to EP0 TX's live `0x0040` buffer, EP1 RX to EP0 RX's `0x0080`, and EP2
TX to the old EP1 region. RC5 resets the cursor and then reserves EP0's IN/OUT
maximum sizes before allowing nonzero endpoints to be initialized.

The exact RC4 ELF now fails the focused twin regression on repeated
`SET_CONFIGURATION(1)`. The exact RC5 ELF passes same-value `1 -> 1`, explicit
`1 -> 0 -> 1`, CDC setup and traffic, suspend/wakeup, STALL, and final bus-reset
re-enumeration. The scenario requires five PMA-distinctness markers and three
data-endpoint-disabled markers. The complete hash-bound RC5 simulator matrix
and both all-14 visual/trace comparisons pass. The package is sealed
`SIMULATION_PASS_HARDWARE_PENDING` and remains `hardware_qualified=false`; no
RC5 physical pass is claimed.

Publication dependencies, in order:

1. Retain the completed RC5 hash-bound twin evidence: symbol profile, paired
   all-14 visual/trace captures, UI/RF, USB/reset, runtime-state, and fault
   scenarios.
2. Qualify the exact packaged F303 binary on the physical device, including
   recovery/DFU, cold boot, complete self-test with paired screenshot review,
   USB traffic, controls, touch, acquisition, RF behavior, warm/cold/power-cycle
   retention, and forced PSP/MSP fault recovery. Preserve the exact binary hash
   in evidence.
3. Make both focused ChibiOS fixes publicly fetchable. Ask the maintainers
   which integration branch and reporting path to use; the current/default
   branch is `master`, while the retained PR template still says `main` and
   GitHub issue creation is restricted. Let maintainers select stable
   backports. A parent repository must never point at the current local-only
   `2b8f425d` / `b3f82b396` lineage.
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

### New tinySA findings from port qualification

Keep the following three fixes independent of the RTOS-port review. They are
application defects present in the legacy code, not ChibiOS defects.

**Current zero-span time grid.** The legacy grid is calculated before the
completed CW sweep replaces `actual_sweep_time_us`, so the displayed time-axis
columns can describe the previous measurement. RC5 calculates the exact
`(offset,width,span)` tuple from the completed sweep, uses 64-bit arithmetic
until the final division, and redraws only if that tuple changed. In paired
cases 12 and 13, expected and observed columns match exactly while the baseline
columns are stale; every framebuffer delta is explained by relocated grid
intersections or bounded time text, and the four trace planes remain
byte-identical. The separate official `c979386` A/B run confirms the same
formula-current result with zero unexplained pixels and byte-identical trace
matrices. Prepare this as a focused application PR after the exact RC5
binary passes the physical self-test and display checks. Do not bundle the
simulator classifier or test-specific activity thresholds.

**Deterministic backup checksum.** `Thread1` copied a stack-local `backup_t`
into RTC backup storage after checksumming all bytes except the checksum byte,
but the packed structure's reserved byte was never initialized. Optimized
builds could therefore persist a checksum over indeterminate data and reject
otherwise valid analyzer settings after reset. RC5 zero-initializes the entire
structure before assigning fields. The earlier digital-twin qualification
preserved the configured 123,456,789..987,654,321 Hz range and 9 dB attenuation
across an MCU reset, including a deterministic reserved byte. Prepare this as a
tiny one-line
correctness PR only after the exact image also passes physical warm/cold reset
and power-cycle tests.

**Hard-fault entry.** The legacy handler marks ordinary C containing locals,
calls, and an infinite loop as `naked`, reads PSP unconditionally, and does not
reliably preserve r4-r11. RC5 uses an assembly-only EXC_RETURN MSP/PSP selector,
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

This is the authoritative Git repository used for the freshness audit. Do not
send the fix to the older `ChibiOS/ChibiOS` community mirror. At audit time:

- current/default integration branch `master`: `f825669c`;
- retained `main` branch: `fbbfad31a4b800f3be826afc5ad19266d15f7610`;
- maintenance branch `stable-21.11.x`:
  `eb9a832bc52f22d9bae012c3b33cbb3f8aad9d5b`;
- release tag consumed by this port: `ver21.11.5` / `f4bbadf964...`.

The checked-in pull-request template still says that changes must land on
`main` first, but that guidance conflicts with the repository's current
default `master` branch and must be treated as stale. GitHub issue creation is
restricted for this repository. Before publishing, ask the maintainers which
branch and intake path they want; if GitHub is not the requested reporting
path, use the [official ChibiOS SourceForge project](https://sourceforge.net/p/chibios/)
support path. Do not infer a workflow from the stale template. Stable
backports remain maintainer-selected.

### STM32F0 TIM14 GPT ISR defect

When an STM32F0 application enables `STM32_GPT_USE_TIM14`, current `master`,
retained `main`, `stable-21.11.x`, and `ver21.11.5` reach:

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
first of two focused ChibiOS deltas required by RC5. Its vendor-neutral patch
dry-runs cleanly against current/default `master` at `f825669c`, retained
`main` at `fbbfad31`, and `stable-21.11.x` at `eb9a832b`. No matching public
change was found in the authoritative repository when checked; restricted
GitHub issue creation means that absence is not permission to create an issue.

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

1. Start from the maintainer-requested integration branch (currently/default
   `master`) and configure an STM32F072 build with
   `HAL_USE_GPT=TRUE` and `STM32_GPT_USE_TIM14=TRUE`.
2. Show the unpatched compile stopping at the exact `#error` above.
3. Apply the one-file handler restoration and build the same target cleanly.
4. Run the current ChibiOS style checker on the changed C file.
5. Build a relevant Cortex-M0 target, preferably
   `RT-STM32F072RB-NUCLEO64`, with GPTD14 linked and referenced so the handler
   cannot be discarded.
6. Include the already completed tinySA F072 and F303 zero-warning builds as
   external integration evidence. If F072 hardware is available, verify a
   GPTD14 periodic callback and its configured priority; do not claim that
   evidence until it exists.

Recommended publication order:

1. Ask the ChibiOS maintainers for the intended report channel and integration
   branch. GitHub issue creation is restricted; use the official SourceForge
   project support path if that is the available or requested intake route.
2. Create a fresh branch from the branch the maintainer names (the current
   default is `master`) and submit the one-file, vendor-neutral fix. Complete
   the current style and ARM build gates; do not rely on the stale `main` text
   in the repository PR template.
3. After the integration change merges, let the maintainer select or request
   the `stable-21.11.x` backport for the future 21.11.6 release. Do not open a
   stable change first.
4. Once a public commit is available, update the tinySA port gitlink and repeat
   its build/qualification gates.

Keep the TIM14 defect independent from the USB allocator defect below. The
multi-file tinySA application adaptation belongs to tinySA, and the historical
fork's mixed `ade76dea8` changes do not belong in either ChibiOS PR.

### USB PMA reuse after endpoint disable

The ChibiOS USB core handles every valid `SET_CONFIGURATION`, including a
request that selects the active configuration again. Commit `8097785b8` made
that rebuild intentional to reset endpoint state for bugs 938 and 939. The
low-level driver's endpoint-disable contract explicitly preserves endpoint
zero.

USBv1 violates the corresponding packet-memory ownership rule. On the F303,
bus reset allocates EP0 TX at `0x0040` and EP0 RX at `0x0080`. The first CDC
configuration allocates EP1 TX/RX at `0x00c0`/`0x0100` and EP2 TX at `0x0140`.
`usb_lld_disable_endpoints()` then leaves EP0 active but calls
`usb_pm_reset()`, returning the cursor to `0x0040`. Rebuilding the configuration
overlaps EP1 TX with EP0 TX and EP1 RX with EP0 RX.

This was hidden by the old one-configuration simulator scenario. It is now
reproduced by the exact RC4 ELF and is consistent with RC4's physical USB
rejection: the device descriptor was visible, but macOS never created the CDC
interface. The packet-memory overlap itself is proven deterministically; the
physical host trace did not expose which repeated request triggered it, so do
not claim a packet-by-packet macOS causal trace.

Local ChibiOS commit
`b3f82b396de7cf2a9e85bc8f1575fbd58e9428d9` adds a reset helper that reserves
the still-configured EP0 IN and OUT maximum sizes before allocating nonzero
endpoints. It changes only
`os/hal/ports/STM32/LLD/USBv1/hal_usb_lld.c`, is directly based on the retained
TIM14 commit, and increases the F303/F072 images by 32/48 bytes respectively.
Do not publish it verbatim because it carries a workstation-local author
identity. The vendor-neutral USBv1 mailbox patch dry-runs against audited
`master` at `f825669c`, retained `main` at `fbbfad31`, and
`stable-21.11.x` at `eb9a832b`.

The exact regression sequence is:

1. bus reset, address, and first `SET_CONFIGURATION(1)`;
2. `SET_CONFIGURATION(1)` again;
3. `SET_CONFIGURATION(0)`, verify data endpoints disabled, then
   `SET_CONFIGURATION(1)`;
4. CDC class setup and fragmented shell traffic;
5. suspend/wakeup and unsupported-request EP0 STALL; and
6. final bus reset, verify data endpoints disabled, then address/configure
   and recheck PMA uniqueness.

The RC4 ELF fails step 2 with EP0 TX and EP1 TX both at `0x0040`. The RC5 ELF
passes and produces exactly five PMA-distinctness markers and three
data-endpoint-disabled markers through the final reset. Defining
`USB_SET_CONFIGURATION_OLD_BEHAVIOR` is not a fix: it only skips same-value
reconfiguration and still leaves `1 -> 0 -> 1` vulnerable.

The USBv2 driver shipped in 21.11.5 has the analogous structure: its disable
function leaves EP0 active, resets `pmnext` to the descriptor-table boundary,
and later endpoints allocate from that cursor. The read-only freshness audit
confirmed that both USBv1 and USBv2 retain this ownership defect on current
`master`. tinySA RC5 does not use USBv2, so its runtime evidence qualifies only
USBv1. A `master`-targeted USB change must nevertheless review and correct both
drivers, add driver-level repeated-configuration/reset coverage, and document
any driver-specific differences. The exact stable mailbox patch remains a
USBv1-only reproducer/fix for 21.11.5. Do not combine the USB work with the
TIM14 change.

The local handoff in
[`upstream-patches/chibios/`](../upstream-patches/chibios/README.md) contains a
21.11.5 USBv1 patch, separate issue/PR drafts, the exact reproducer, and a
USBv2 integration-branch recommendation. It is preparation only: this local
update did not open an issue, publish a branch, push, or claim a current public
status.

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
| 1 | [issue #941](https://github.com/renode/renode/issues/941) / [PR #217](https://github.com/renode/renode-infrastructure/pull/217) | `297ee9f670291d6c5daf89ab612a14bc146bdaf5` | Open; GitHub reports clean mergeability; generated merge ref is based on `66feec8`, not current `master`; patch dry-runs on current `master`; CLA success; only CLA bot comment, no review |
| 2 | [issue #942](https://github.com/renode/renode/issues/942) / [PR #218](https://github.com/renode/renode-infrastructure/pull/218) | `d7337a1a3fc7bbabfe436aa4f1dd0501034af456`, then `12d2d3f66714c276de36865ccbd063d7eaed3790` | Open; GitHub reports clean mergeability; generated merge ref is based on `66feec8`, not current `master`; patches dry-run on current `master`; CLA success; no comments or review |

PR #217 implements NVIC `ICSR.RETTOBASE`. PR #218 first separates STM32 GPIO
IDR from ODR and then makes simultaneous BSRR set/reset resolve to set. The
latest generated merge refs fetched for both PRs use `66feec8` as their first
parent, not current infrastructure `master` at `7068985`; they therefore are
not current-master merge proofs. GitHub still reports both PRs cleanly
mergeable, and the PR patch or patch series dry-runs against current `master`,
so no content conflict is presently observed. Do not create duplicates or add
unrelated model changes to either PR. Wait for review and rebase only if
GitHub reports a conflict or a maintainer requests it.

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

1. Keep RC4 rejected, finish the exact RC5 simulation seal, and complete RC5
   physical qualification before calling any v0.4 image hardware-qualified.
2. Leave tinySA PRs #156-#162 and Renode PRs #217/#218 alone pending review.
3. When explicitly authorized, ask ChibiOS maintainers for the intake path and
   integration branch (or use their SourceForge support path), then submit
   separate TIM14 and USB PMA changes; let maintainers choose stable backports.
4. When explicitly authorized, publish the separate Renode HardFault-priority
   issue and issue-numbered infrastructure PR.
5. After both required ChibiOS fixes are public (and stable backports are
   selected), update and requalify the tinySA ChibiOS port, then submit the
   single RTOS-port PR.
6. After the exact RC5 hardware self-test, offer the current zero-span-grid fix
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
