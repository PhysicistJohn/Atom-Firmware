# Upstream contribution candidates

Personal research belongs on the PhysicistJohn fork. Generally useful fixes
should be packaged as small branches based directly on `upstream/main`, with no
personal roadmap, artifact tooling, or branding mixed into the patch.

No contribution has been pushed. Publishing is locally blocked until a personal
GitHub authentication path is explicitly configured.

| Candidate | Local branch | Commit | Verification |
| --- | --- | --- | --- |
| Target validation | `upstream/fix-target-validation` | `97952e6` | Default F072 and explicit F303 builds pass; invalid targets fail |
| Hardware table length | `upstream/fix-hardware-version-table` | `131ec88` | F303 build passes with the existing warning count; physical version check pending |

## Candidate 1: hardware-version table count

Current source declares `MAX_VERSION_TEXT` as 5 but initializes only four rows.
The removed fifth row is zero-initialized, so an ADC identification reading of
zero matches it and returns a null text pointer. Known ZS407 readings match row
four before this, but unknown/failed identification should return `"Unknown"`
rather than a phantom record.

Proposed minimal patch:

- let the compiler infer the array length;
- iterate with `sizeof(array) / sizeof(array[0])` or the project's accepted
  array-count macro;
- add a testable helper that maps an ADC value without reading hardware;
- verify known ZS405, ZS406, ZS407, zero, and out-of-range values.

Hardware test: confirm the version screen and `version` command on the ZS407.

## Candidate 2: `TARGET` parsing

The Makefile currently behaves as:

```make
ifeq ($(TARGET),)
  TARGET = F072
else
  TARGET = F303
endif
```

Therefore any non-empty value—even a typo—silently selects F303. A minimal fix
would preserve the F072 default, accept only `F072` or `F303`, and fail clearly
for anything else. Both outputs should build in CI.

## Candidate 3: pinned submodule behavior in CI

The existing CircleCI configuration runs `git submodule update --remote`, which
can move ChibiOS away from the superproject's pinned commit. That defeats source
reproducibility and can introduce an unreviewed RTOS/HAL change. It also builds
the default F072 target rather than explicitly testing the Ultra F303 target.

Proposed patch:

- use `git submodule update --init --recursive` without `--remote`;
- build explicit F072 and F303 jobs;
- pin the compiler image/toolchain by digest or verified archive hash;
- report binary size and embedded version for each target.

## Candidate 4: reproducible release metadata

The image embeds `__DATE__` and `__TIME__`. GCC honors `SOURCE_DATE_EPOCH`, as
the exact reproduction proves, but the upstream release process does not record
the epoch or toolchain target-library package. A documented build manifest would
make future releases independently verifiable.

An upstream patch should avoid imposing this fork's large diagnostic download.
It can instead record source commit, submodule commit, compiler package, build
epoch, flags, size, and release hashes at publish time.

## Candidate 5: root licensing clarity

Application headers mostly state GPL-3.0-or-later, but there is no root license
file and the tree combines code under several notices. Ask the maintainer which
aggregate license statement and notice set is intended before proposing a
`LICENSE`, `COPYING`, or SPDX sweep.

## Packaging checklist

For every proposed upstream patch:

1. Create a branch from the exact current `upstream/main`.
2. Include one concern only.
3. Explain observable failure, not stylistic preference.
4. Build F072 and F303 where the change is shared.
5. Record firmware size and warning deltas.
6. Run the ZS407 self-test and relevant RF/USB checks for runtime changes.
7. Keep generated binaries out of the commit unless the maintainer requests one.
8. Use PhysicistJohn authorship and a PhysicistJohn-owned fork/PR.
