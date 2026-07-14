# Self-test visual evidence finalization

`tools/finalize-selftest-visual-evidence.py` turns two completed Renode
self-test capture directories into the self-contained evidence tree expected
by the ChibiOS release sealer. It does not run Renode, build firmware, or touch
hardware.

The reference and candidate captures are supplied separately. This permits a
fresh release-candidate capture to be paired with either:

- the pinned pre-ChibiOS `lab-v0.2.0-protocol` behavioral baseline; or
- the already captured official `v1.4-224-gc979386` baseline.

Reusing the official reference is safe only when its BIN, ELF, symbol profile,
scenario bindings, and all copied capture files pass the finalizer's hash and
completeness checks. A candidate capture cannot be substituted from another
build: its `run.resc` BIN, ELF, and symbol-profile targets are hashed and must
match the explicitly supplied candidate hashes.

## Before finalizing

Run `tools/test-selftest-visual-regression.sh` for the exact candidate. Review
both generated contact sheets at full resolution, including the reference,
candidate, and difference panels for all 14 cases. Confirm that shaped traces,
markers, labels, status content, and the intended cases 12/13 time-grid changes
are visible. Do not attest based only on 14 PASS markers or on flat LCD lines.

The finalizer requires an explicit review result, reviewer, and attestation.
It will not synthesize or silently claim human review. A `FAIL` review stops
finalization.

## Official c979 baseline

The following is the command shape; candidate paths and all three candidate
hashes must come from the exact release package being qualified.

```sh
python3 tools/finalize-selftest-visual-evidence.py \
  --mode official-c979 \
  --twin-root ../TinySA_Twin \
  --reference-capture PATH/official-c979/reference \
  --candidate-capture PATH/fresh-rc5/candidate \
  --reference-bin .artifacts/upstream/v1.4-224-gc979386/tinySA4_v1.4-224-gc979386.bin \
  --reference-elf .artifacts/upstream/v1.4-224-gc979386/tinySA4_v1.4-224-gc979386.elf \
  --reference-symbols PATH/v1.4-224-gc979386.symbols \
  --candidate-bin PACKAGE/tinySA4_RELEASE.bin \
  --candidate-elf PACKAGE/tinySA4_RELEASE.elf \
  --candidate-symbols PACKAGE/RELEASE.symbols \
  --candidate-bin-sha256 EXPECTED_BIN_SHA256 \
  --candidate-elf-sha256 EXPECTED_ELF_SHA256 \
  --candidate-symbols-sha256 EXPECTED_SYMBOL_SHA256 \
  --candidate-release RELEASE \
  --output EVIDENCE/official-c979-selftest-visual \
  --human-review PASS \
  --human-reviewer 'REVIEWER' \
  --human-review-attestation 'WHAT WAS REVIEWED AND WHY IT PASSED'
```

Official-c979 mode requires the historical comparator to reproduce its
conservative rejection. This result is retained under
`comparison-original-rejected/`. The current comparator must then prove the
reviewed `mathematically-better-time-grid` result under `comparison/`.

## Lab baseline

Use the same command with `--mode lab`, the pinned lab BIN/ELF, and
`../TinySA_Twin/digital-twin/renode/symbols/v0.2.0-protocol-v2.symbols`. The
output normally becomes `EVIDENCE/selftest-visual`. The historical comparator is still
retained in the compatibility-named `comparison-original-rejected/` directory;
for the direct lab baseline that older classifier may itself pass.

The lab reference wrapper may omit an explicit `$symbols` assignment because
the recorded Twin commit's main `digital-twin/renode/zs407.resc` supplies the pinned
default. This is the only admitted implicit symbol binding. The finalizer then
requires all of the following: `--reference-symbols` resolves to that exact
Twin file and pinned hash, `run.resc` includes the exact recorded main
`zs407.resc` followed only by the exact tracked self-test visual body, the main
scenario retains its exact `$symbols ?=` default, and `run.log` confirms the loaded
`v0.2.0-protocol-v2.symbols` profile. Candidate and official-c979 wrappers
must always bind `$symbols` explicitly.

## Fail-closed checks

Finalization rejects evidence when any of these conditions is observed:

- a reference or candidate BIN, ELF, or symbol-profile hash differs;
- `run.resc` points at an artifact with a different hash;
- reference and candidate captures omit or disagree on the exact external
  Twin commit, Renode tree, tools tree, bootstrap blob, or executed Renode
  runtime identity;
- an implicit symbol binding is used anywhere except the securely proven lab
  reference default, or the loaded-profile log marker is missing;
- any of the 14 PNG, 307,200-byte RGB565, or 7,200-byte trace captures is
  missing, extra, empty, malformed, or incomplete;
- a framebuffer is blank or a measured trace plane is zero/unpopulated;
- a structurally shaped reference case is flattened in either capture;
- PASS, READY, VISUALLY_SETTLED, STATUS, screen-save, or trace-save markers are
  not exactly 14/14, or the run lacks a clean Renode quit;
- trace matrices are not byte-identical, raw/actual planes differ, or a
  critical per-case comparator gate fails;
- the current classifier or its adversarial blank/flat/missing-evidence suite
  fails; or
- explicit contact-sheet review is absent or not PASS.

The installed tree is assembled in a sibling staging directory and replaces
the requested output only after every check succeeds. `SUMMARY.txt`,
`PROVENANCE.txt`, `SUPPLEMENTAL_ANALYSIS.txt`, and `HUMAN_REVIEW.txt` are
generated from the reports, artifact hashes, capture logs, and explicit review
arguments. `SHA256SUMS` is a sorted, exhaustive inventory using `./`-prefixed
paths and intentionally excludes itself.

The output remains simulation evidence. It always records
`hardware_qualified=false`; physical qualification is a separate gate.
