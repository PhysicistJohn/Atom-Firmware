# ChibiOS upstream handoff

This directory packages two independent ChibiOS findings from the tinySA
21.11.5 port. It is a local publication handoff, not evidence that an issue,
branch, or pull request has been published.

| Finding | Proven base | Local integration commit | Upstream shape |
| --- | --- | --- | --- |
| STM32F0 TIM14 GPT ISR missing | `ver21.11.5` / `f4bbadf964fc746aef8bbcf34135c7d8fabb8eae` | `2b8f425d26a61a7887916f7052b401f9e767a949` | One issue and one vendor-neutral `main` PR; maintainer-selected stable backport |
| USB PMA allocator reuses active EP0 buffers | USBv1 proven on the same tag; USBv2 has the analogous source pattern | `b3f82b396de7cf2a9e85bc8f1575fbd58e9428d9` | Separate issue/PR; exact USBv1 stable patch plus a current-`main` USBv1/USBv2 review |

The local ChibiOS chain is exactly:

```text
f4bbadf964  ver21.11.5
  |
2b8f425d26  TIM14 compatibility fix
  |
b3f82b396d  USBv1 EP0 PMA preservation
```

Do not publish those two local commits verbatim. They use a workstation-local
author identity, and the TIM14 commit contains a tinySA-specific source
comment. The mailbox patches here use the intended public identity and neutral
wording.

## Contents

- [`tim14/ISSUE_DRAFT.md`](tim14/ISSUE_DRAFT.md) and
  [`tim14/PR_DRAFT.md`](tim14/PR_DRAFT.md): separate vendor text for the
  missing TIM14 ISR.
- [`tim14/0001-stm32-restore-TIM14-GPT-ISR.patch`](tim14/0001-stm32-restore-TIM14-GPT-ISR.patch):
  one-file patch prepared from `ver21.11.5`.
- [`usb-pma/ISSUE_DRAFT.md`](usb-pma/ISSUE_DRAFT.md) and
  [`usb-pma/PR_DRAFT.md`](usb-pma/PR_DRAFT.md): separate vendor text for the
  PMA ownership defect.
- [`usb-pma/0001-usbv1-preserve-EP0-PMA-on-reconfigure.patch`](usb-pma/0001-usbv1-preserve-EP0-PMA-on-reconfigure.patch):
  exact one-file USBv1 patch for the 21.11.5 stable code.
- [`usb-pma/REPRODUCER.md`](usb-pma/REPRODUCER.md): host sequence, expected
  descriptors, and pass/fail checks.
- [`usb-pma/USBV2_MAIN_RECOMMENDATION.md`](usb-pma/USBV2_MAIN_RECOMMENDATION.md):
  analogous USBv2 review and proposed shape for current `main`; it is not an
  already-validated `main` patch.

## Local evidence boundary

The exact RC4 firmware image physically exposed the USB failure after a clean
flash and cold boot. macOS saw VID:PID `0483:5740` and device descriptors but
remained at `UsbEnumerationState=2`; it created neither an
`IOUSBHostInterface` child nor `/dev/cu.usbmodem*`. Unplug/replug reproduced
the same result.

The executable twin proves the allocator defect independently. RC4 fails on a
second `SET_CONFIGURATION(1)` because EP0 TX and EP1 TX both use `0x0040`.
RC5 passes same-value `1 -> 1`, explicit `1 -> 0 -> 1`, CDC traffic,
suspend/wakeup, STALL, and a final bus reset/re-enumeration. The full scenario
requires five PMA-distinctness markers and three data-endpoint-disabled
markers.

RC5 is reproducibly built but was still `SIM_PENDING` and
`hardware_qualified=false` when this handoff was prepared. Do not convert the
focused twin result into a physical RC5 claim.

## Clean-room patch audit

Both mailbox files were applied independently with `git am` to detached clean
worktrees at `f4bbadf964`. The resulting audit commits were:

- TIM14: `5821b87b8`;
- USBv1 PMA: `39070195e`.

The USBv1 result is byte-for-byte identical to the corresponding file at local
integration commit `b3f82b396`. The TIM14 result differs from local integration
commit `2b8f425d` only by removing its tinySA-specific two-line source comment.
ChibiOS 21.11.5's `tools/style/stylecheck.pl` produced no output for either
patched file.

Patch SHA-256 values:

```text
5bb4bb8fe00db6b9b238b1501095935dc9f3ec0e84f534c3524b2c6eef14e5a7  tim14/0001-stm32-restore-TIM14-GPT-ISR.patch
f3ed4e777be9093c15e320b75a34c299d39682dc6a70c9a721c874c7fc56cd60  usb-pma/0001-usbv1-preserve-EP0-PMA-on-reconfigure.patch
```

## Before publication

1. Fetch current `chibios-upstream/chibios` and rebase each finding separately
   onto the maintainer's requested branch.
2. Recheck whether current `main` still contains both USB PMA driver patterns.
3. Run the current repository style tool and relevant ARM build/test matrix.
4. Keep TIM14 and USB PMA as separate issues and PRs.
5. Let maintainers choose stable backports after a `main` fix.
6. Use `PhysicistJohn <54456354+PhysicistJohn@users.noreply.github.com>`.
7. Publish only with explicit approval; this package performs no network or
   repository-host mutation.
