# Upstream return checkpoint

Recorded on 2026-07-14 before separating the executable digital twin into the
adjacent `TinySA_Twin` repository. No public push, issue, pull request, or
comment was made while recording this checkpoint.

## Resume state

- Firmware worktree: `physicistjohn/digital-twin-renode` at `c16ced5` when the
  upstream-readiness audit completed; the branch was clean and 44 commits
  ahead of its tracked fork branch.
- Full `make host-test`: pass, including 100,000 protocol mutation cases.
- GitHub publication is operationally blocked: the configured credential
  helper points to missing `/opt/homebrew/bin/gh`, and an authenticated
  `git push --dry-run` found no usable Keychain credential.
- The primary checkout's `upstream` remote is intentionally fetch-only. Use a
  fresh publication clone or branch and push only to the PhysicistJohn fork.

## Publication order

1. Restore GitHub authentication without putting a token in repository files,
   shell history, documentation, or chat.
2. Publish only the independent tinySA exact-power scientific-format fix:
   create a fresh branch from upstream `c979386`, apply
   `upstream-patches/tinysa/scientific-format/0001-chprintf-normalize-exact-powers.patch`,
   rerun the strict reproducer and F072/F303 builds, perform an authenticated
   dry-run push, then request an explicit final go-ahead before the public push
   and PR.
3. Leave tinySA PRs #156 through #162 and Renode PRs #217 and #218 unchanged
   while they remain open and cleanly mergeable with no maintainer request.
4. Ask ChibiOS maintainers to confirm the intake path and `master` target.
   Submit the vendor-neutral TIM14 fix independently after confirmation.
5. File the USB PMA defect report separately. Do not open a current-master USB
   PR until parallel USBv1 and USBv2 fixes and regressions are implemented.
6. Do not publish the ChibiOS 21.11.5 tinySA application port until the exact
   sealed RC5 binary completes cold physical qualification, both ChibiOS fixes
   are publicly consumable, the application port is recreated with noreply
   authorship on a clean upstream branch, and both targets are rebuilt and
   requalified.

## Remaining physical gate

The device is on untouched official firmware
`tinySA4_v1.4-224-gc979386`, in normal mode with CAL output off and its original
0--900 MHz runtime sweep restored. The next hardware sequence is:

1. Switch fully off for at least five seconds, switch on normally, and capture
   a new cold official all-14 baseline.
2. Enter TINYSA4 DFU manually, flash sealed RC5 BIN SHA-256
   `1e3f45a9744b18985622d5abf6c2445524a4ad53a831316766c37de80ac96685`,
   and verify warm USB enumeration.
3. Perform another true cold boot, capture all fourteen RC5 self-tests, and
   compare screenshots, all four traces, SFDR, sweep timing, and persisted
   configuration against the official baseline.
4. Complete unplug/replug, controls, touch, acquisition, warm/cold retention,
   and forced PSP/MSP fault recovery before setting `hardware_qualified=true`.

## Work explicitly held

- ChibiOS USBv1-only patch as a current-master PR;
- Renode Architectural HardFault priority until it has a separate issue,
  vendor-neutral patch, and managed NVIC tests;
- local DMA peer-address heuristic and project-local ST7796S changes;
- zero-span grid, backup checksum, hard-fault veneer, and selective spur
  firmware changes until their named physical gates pass.

The detailed vendor status and evidence remain in
[Vendor upstream delivery queue](VENDOR_UPSTREAM_QUEUE.md).
