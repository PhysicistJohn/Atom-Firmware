# tinySA upstream bug-fix queue

These patches are intentionally conservative. They repair reproducibility,
bounds, and one divide-by-zero path in the existing firmware; they do not
introduce DSP, scheduling, UI, RF, or architectural changes.

The queue is based on upstream `tinySA` commit
`c97938697b6c7485e7cab50bca9af76996b7d671` with its pinned ChibiOS gitlink
`ade76dea89cd093650552328e881252a06486094`. All authorship is
`PhysicistJohn <54456354+PhysicistJohn@users.noreply.github.com>`.

Publication proceeded one explicitly approved patch at a time. As of
2026-07-11, all seven packages are public as tinySA PRs
[#157](https://github.com/erikkaashoek/tinySA/pull/157),
[#156](https://github.com/erikkaashoek/tinySA/pull/156), and
[#158](https://github.com/erikkaashoek/tinySA/pull/158),
[#159](https://github.com/erikkaashoek/tinySA/pull/159),
[#160](https://github.com/erikkaashoek/tinySA/pull/160),
[#161](https://github.com/erikkaashoek/tinySA/pull/161), and
[#162](https://github.com/erikkaashoek/tinySA/pull/162), respectively. Packages
3–7 were also flashed to the physical ZS407 and passed their targeted runtime
checks and complete built-in self-test gates.

## Queue

| # | Patch | Observable defect | Runtime risk |
| --- | --- | --- | --- |
| 1 | Reject unknown build targets | Every non-empty `TARGET`, including typos, silently selected F303 | None |
| 2 | Keep ChibiOS pinned in CI | `git submodule update --remote` ignored the reviewed gitlink | None |
| 3 | Derive hardware table length | A declared fifth zero-filled row could match ADC zero and return a null label | Very low |
| 4 | Reject invalid scan counts | One-point scan paths divide by `points - 1`; legacy/raw counts could wrap | Low |
| 5 | Validate correction arguments | Invalid table names and slots indexed outside correction arrays | Low |
| 6 | Validate shell-controlled indices | Trace, marker, palette, and remote-menu inputs could index outside arrays | Low |
| 7 | Bound remote keypad text | A 47-byte shell argument was copied without bounds into a 28-byte F303 UI buffer | Low |

The generated mailbox files form the exact combined series that was built and
tested. From a clean checkout at the stated base:

```bash
git am /path/to/upstream-patches/tinysa/000*.patch
```

A clean-room `git am` audit produced a tree identical to
`bece91ea29adc86ee2cd4804c6d8be407526f35e`, and both firmware targets then
built successfully.

## Branches and commits

Each concern also exists as a one-commit branch directly off
`upstream/main`, which is the preferred source for a narrowly scoped PR:

| Concern | Independent branch | Commit | Combined-series commit |
| --- | --- | --- | --- |
| Target validation | `upstream/fix-target-validation` | `46dc0d840d457b79e5b662ac04c887fb823e1fd6` | `45d123e79da420edb82e2ea1f37bc095289c13be` |
| Pinned CI submodule | `upstream/fix-pinned-submodule-ci` | `08caa12cf68ea3edbb8ca713adaef2dd922a0878` | `eb91a3d` |
| Hardware table length | `upstream/fix-hardware-version-table` | `2a3a2df14283a840f8e650c655296332eea8186a` | `ce09d72` |
| Scan point validation | `upstream/fix-scanraw-points` | `1d518aff448b462cf52b39b95be90d9abfb22520` | `a385084` |
| Correction bounds | `upstream/fix-correction-bounds` | `6cba8a9aafdc6273aeffb814f2131605dc22d267` | `a837907` |
| Shell index bounds | `upstream/fix-shell-index-bounds` | `5a029f907a12e5e8f85e7dc57d311912b9efd36a` | `5f1e432` |
| Keypad text bound | `upstream/fix-shell-text-bounds` | `89e5d11e83c48c6a9cb72c9474f3a556a4935a4b` | `bece91e` |

The tested integration branch is
`physicistjohn/upstream-firmware-fixes` at
`bece91ea29adc86ee2cd4804c6d8be407526f35e`.

## Why each change is defensible

### 1. Target validation

The old Makefile selected F072 only when `TARGET` was empty and F303 for
every non-empty value. The patch preserves the default, accepts exactly
`F072` and `F303`, and produces a clear make-time error for anything else.

Verified cases: unset target, explicit F072, explicit F303, and an invalid
target returning exit status 2.

### 2. Pinned submodule CI

A superproject gitlink identifies the reviewed ChibiOS revision.
`git submodule update --remote` can move away from that revision at CI time.
The patch replaces the init/update pair with the standard recursive command
that checks out the gitlink. The CircleCI YAML parses and a clean submodule
checkout remains at `ade76dea`.

This patch deliberately does not redesign the old CI image or add a target
matrix; those are useful follow-up work, not a two-line correctness fix.

### 3. Hardware-version table count

The array has four initialized rows but was explicitly sized for five. Static
zero initialization made the phantom row cover ADC value zero and contain a
null `hw_text`. Letting the compiler derive the element count makes the loop
cover exactly the records that exist.

The F303 ELF contains four table records after the change. A physical ZS407
reported `V0.5.4 max2871` with the exact candidate installed, and the complete
built-in CAL-to-RF self-test passed after a physical cold start. This exact
commit is published as PR #158.

### 4. Scan point validation

`cmd_scan` ultimately computes frequencies using `points - 1`, so zero and
one are invalid. The legacy `s` command reaches the same kind of sweep path
and now requires 2 through `INT32_MAX`. `scanraw` divides the interval by
`points`, not `points - 1`, and the
[official USB interface](https://tinysa.org/wiki/pmwiki.php?n=Main.USBInterface)
permits arbitrary point counts; it therefore rejects only non-positive values
and values that do not fit its `uint32_t` loop counter.

The different lower bound for `scanraw` is intentional.

### 5. Correction bounds

The [documented correction command](https://tinysa.org/wiki/pmwiki.php?n=Main.Correction)
previously used the result of table-name lookup and a user slot directly as two
array subscripts. The patch requires an argument, permits only actual
correction tables for mutations, and checks the slot against
`CORRECTION_POINTS` before either write. The existing F303 `off`/`on` commands
remain valid in their one-argument form.

### 6. Shell-controlled indices

The patch adds the missing checks immediately before these accesses:

- trace copy/subtract source or destination;
- trace sample index, including negative values;
- marker delta reference and marker trace;
- negative palette index;
- negative or overlong remote menu path.

It does not change valid command syntax or storage layout.

### 7. Remote keypad text

The shell accepts up to 47 input characters. F303's keypad buffer is 28 bytes
with long filenames enabled. The original loop copied until NUL with no size
check. The new UI helper uses the firmware's existing bounded formatter and
always terminates the destination before the existing numeric parser consumes
it.

## Build and analysis evidence

Arm GNU Toolchain 11.3.Rel1 was used for the audit, matching the compiler family
identified in the official image.

| Target | text | data | bss | Result |
| --- | ---: | ---: | ---: | --- |
| F072 / `tinySA` | 109,990 | 828 | 15,744 | Pass |
| F303 / `tinySA4` | 181,704 | 4,180 | 37,192 | Pass |

The F303 text increase is 188 bytes over the unpatched base. Data and BSS do not
grow.

A second F303 build enabled GCC `-fanalyzer`, format, array-bounds,
string-overflow, conversion, and shadow diagnostics. It completed with no
`-Wanalyzer-*` finding. The conversion/shadow warnings are pre-existing
firmware and ChibiOS debt; none was promoted into this minimal queue.

## Exact combined artifacts

The reproducible build used `SOURCE_DATE_EPOCH=1778074389`. Files remain local
under
`.artifacts/firmware-fix-queue/bece91ea29adc86ee2cd4804c6d8be407526f35e/`
and are not committed:

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `tinySA.bin` | 110,820 | `6c06ced7e57fa97ff3261441b57b5eeced322d98db29ab1c743603e6c142681b` |
| `tinySA.elf` | 913,936 | `b422e8e25aab26de3cabc523aa74eeab33c9d354ea4b6233921daed509832658` |
| `tinySA.hex` | 311,755 | `8dd6adfac0c1ae62479bd9043c4a505822aa2bee165e02773a180a1fc40758f5` |
| `tinySA4.bin` | 185,888 | `cef3181b0834b9d498ec7ebd7ae4a46514a1d54d0c673cfe9b15a8011516bafa` |
| `tinySA4.elf` | 1,266,352 | `5078f2b2a894841ec7a580db5a4ffc638991929cd23274c5d958aff5cd4a441d` |
| `tinySA4.hex` | 522,913 | `490817635e0f0a546a6f5b3f86bce47f8e40a1434783a5f358135cdee28fc033` |

## Digital-twin evidence and limit

The combined F303 image boots in the exact ZS407 twin and reaches the same
initial peripheral transaction counts as untouched upstream:

```text
stock:     spi=1031724 pixels=511280 si4468=167 max2871=7 pe4302=3
candidate: spi=1031724 pixels=511280 si4468=167 max2871=7 pe4302=3
```

The framebuffer hashes differ because the embedded version/build text differs.

The repository's longer jog/menu script targets the newer lab firmware. Both
untouched `c979386` and this candidate stop at the same menu assertion, so
that result is a harness/version incompatibility and is not counted as either a
candidate pass or regression. The current lab image still passes the complete
boot/jog/touch/UI/RF scenario.

## Completed hardware gates

Package 3 completed its physical version-identification and self-test gate.
Packages 4–7 pass independent dual-target reproducible builds, GCC
`-fanalyzer`, exact-source audits, exact-image Renode boot, targeted ZS407 USB
checks and the complete built-in self-test. Their four F303 images, hashes,
fail-closed test runner, physical order and completed results are in
[UPSTREAM_HARDWARE_BATCH.md](../../docs/UPSTREAM_HARDWARE_BATCH.md) and
[UPSTREAM_HARDWARE_RESULTS.md](../../docs/UPSTREAM_HARDWARE_RESULTS.md).

The completed physical batch deliberately avoided calibration mutation:

1. Verify valid `scan`, legacy `s`, and one-point `scanraw` operation.
2. Confirm zero/one/negative/overflow scan counts are rejected as specified.
3. Read the complete correction table, exercise missing/invalid tables and
   slots `-1`/first-invalid, then prove the table is byte-for-byte unchanged.
4. Exercise invalid trace/marker/color/menu indices, prove the palette remains
   unchanged, and confirm the shell remains responsive.
5. Send a 46-byte command line to `text`, confirm normal subsequent UI/USB
   operation, and restore both captured sweep endpoints without saving.
6. Cold-start and run the complete built-in self-test on every exact candidate.
7. Restore the qualified enhanced v0.3 image, repeat its self-test, and only
   then remove the CAL-to-RF cable.

## Suggested upstream grouping

Keep review surfaces small:

1. Target validation alone.
2. Pinned-submodule CI alone.
3. Hardware-table count alone after the physical version check.
4. Scan count validation alone after USB transcripts.
5. Correction bounds alone after USB transcripts.
6. Shell index bounds alone after USB transcripts.
7. Keypad text bound alone after USB transcripts.

The hard-fault veneer, compiler modernization, warning cleanup, DSP work,
interrupt/DMA redesign, and UI changes are intentionally excluded. They may be
valuable, but none belongs in this low-risk bug-fix queue.
