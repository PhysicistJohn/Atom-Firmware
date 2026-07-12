# Remaining upstream firmware hardware batch

Status: hardware-independent qualification complete; physical device untouched
since the enhanced v0.3 qualification.

This runbook closes the physical gate for tinySA packages 4 through 7 in one
ordered session. Every candidate is an independent one-commit branch directly
on upstream `c97938697b6c7485e7cab50bca9af76996b7d671` with pinned ChibiOS
`ade76dea89cd093650552328e881252a06486094`; no candidate contains another
pending PR.

## Prepared candidates

| Package | Source commit | Embedded version | F303 bytes | F303 SHA-256 |
| --- | --- | --- | ---: | --- |
| 4 — scan counts | `1d518aff448b462cf52b39b95be90d9abfb22520` | `tinySA4_pr4-scan-g1d518af` | 185,832 | `ea11cdd5d06c00dc5d82c12a304fc32fd1b075baa210ea16c92c18373f303172` |
| 5 — correction bounds | `6cba8a9aafdc6273aeffb814f2131605dc22d267` | `tinySA4_pr5-correction-g6cba8a9` | 185,736 | `20b491939508a12f67d0affe844e1eada5ce9441a092dbf82c340258a133bc4a` |
| 6 — shell indices | `5a029f907a12e5e8f85e7dc57d311912b9efd36a` | `tinySA4_pr6-indices-g5a029f9` | 185,744 | `c3f5b827a5eb8577b247197d4f569e31a12cfbcd836ee449ad02c6c29ad57346` |
| 7 — keypad text | `89e5d11e83c48c6a9cb72c9474f3a556a4935a4b` | `tinySA4_pr7-text-g89e5d11` | 185,712 | `d899b3b155e2da0030d8edb1d64d647b23e82d9d9ce2c3e3c190c2b7cd81987c` |

The local images are under `.artifacts/upstream-staging/images/pr4` through
`pr7`. Each package passes F072 and F303 builds, a second byte-for-byte
reproducibility build, GCC `-fanalyzer`, source/diff checks, and exact-image
Renode boot with the expected Si4468, MAX2871 and PE4302 initialization counts.

## Safety boundary

- Flashing remains a separate, human-controlled operation; the qualification
  script has no DFU or flash code.
- The script verifies the exact embedded version before its package tests.
- Its first and last state command is `output off`.
- It never issues `save`, `saveconfig`, `reset`, `clearconfig`, correction
  update/reset, SD deletion, or an RF-enabling command.
- Package 5 compares the correction table before and after invalid commands but
  never changes a valid correction value.
- Package 7 temporarily changes center frequency in RAM and restores the exact
  original frequency grid. A power cycle also discards any unsaved state.

## Rapid physical sequence

Keep one short 50-ohm cable between CAL and RF only for the manual self-tests;
do not attach an antenna. Close Atomizer and every serial terminal before each
DFU transition.

For packages 4, 5, 6 and 7 in order:

1. Enter DFU physically and flash only that row's verified F303 image.
2. Boot normally and identify the returned `/dev/cu.usbmodem*` path.
3. Run the matching command below, substituting only the exact serial path.
4. Confirm the script reports `PASS` and preserves its Markdown transcript.
5. Cold-start and run the complete built-in CAL-to-RF self-test.
6. Power off before moving to the next candidate.

The prepared virtual environment already contains the pinned serial dependency.
To recreate it if needed:

```bash
python3 -m venv .artifacts/toolchains/tinysa-hardware-venv
.artifacts/toolchains/tinysa-hardware-venv/bin/python -m pip install -r tools/requirements-hardware-test.txt
```

```bash
.artifacts/toolchains/tinysa-hardware-venv/bin/python tools/qualify-upstream-tinysa.py --port /dev/cu.usbmodemXXXX --package 4 --expected-version tinySA4_pr4-scan-g1d518af --transcript .artifacts/upstream-staging/hardware/pr4.md --confirm TARGETED-RAM-ONLY-TEST
.artifacts/toolchains/tinysa-hardware-venv/bin/python tools/qualify-upstream-tinysa.py --port /dev/cu.usbmodemXXXX --package 5 --expected-version tinySA4_pr5-correction-g6cba8a9 --transcript .artifacts/upstream-staging/hardware/pr5.md --confirm TARGETED-RAM-ONLY-TEST
.artifacts/toolchains/tinysa-hardware-venv/bin/python tools/qualify-upstream-tinysa.py --port /dev/cu.usbmodemXXXX --package 6 --expected-version tinySA4_pr6-indices-g5a029f9 --transcript .artifacts/upstream-staging/hardware/pr6.md --confirm TARGETED-RAM-ONLY-TEST
.artifacts/toolchains/tinysa-hardware-venv/bin/python tools/qualify-upstream-tinysa.py --port /dev/cu.usbmodemXXXX --package 7 --expected-version tinySA4_pr7-text-g89e5d11 --transcript .artifacts/upstream-staging/hardware/pr7.md --confirm TARGETED-RAM-ONLY-TEST
```

Finally restore
`.artifacts/hardware-trials/v0.3/43eb0f193c8619cb7ca23726e3062973c65ae958/tinySA4_hw-v0.3-fft1024.bin`,
whose SHA-256 is
`6f284a24c4b4ab178da13af97e102e1a624618c9a67e8418b19bbc153e6f0174`.
Verify `tinySA4_hw-v0.3-fft1024-g43eb0f1`, repeat the cold self-test, then remove
the CAL-to-RF cable.

## Publication after the batch

Successful transcripts are summarized in the four prepared PR bodies. The
already staged public-fork branches are then pushed and opened one at a time:

| Package | Public branch | Proposed title |
| --- | --- | --- |
| 4 | `fix/scan-point-validation` | Validate scan point counts before division |
| 5 | `fix/correction-argument-bounds` | Validate correction table arguments |
| 6 | `fix/shell-index-bounds` | Validate shell-controlled array indices |
| 7 | `fix/keypad-text-bounds` | Bound remote keypad text input |

The publication clone is local at
`.artifacts/publish/tinysa-remaining-prs`. No remaining branch has been pushed
to the public fork and no new public PR has been opened.
