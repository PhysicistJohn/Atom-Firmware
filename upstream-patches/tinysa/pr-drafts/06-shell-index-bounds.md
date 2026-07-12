## Problem

Several shell arguments reached array or menu traversal operations without a
complete lower/upper bound check. Negative trace samples and palette IDs,
invalid trace copy/subtract destinations, out-of-range marker references, and
negative/overlong remote-menu paths could address outside their valid objects.

## Change

Add checks immediately before the affected operations:

- trace copy/subtract destination and sample index;
- marker delta reference and marker trace;
- palette index;
- remote-menu traversal, including safe termination when a path runs past the
  available menu items.

Valid command syntax, one-based public trace/marker numbering, and menu layout
remain unchanged.

## Verification

- Arm GNU 11.3.Rel1 F072 and F303 builds pass.
- Both target images reproduce byte-for-byte on a second clean build.
- GCC `-fanalyzer` reports no analyzer diagnostic.
- The exact F303 image boots in the ZS407 Renode model with unchanged RF-device
  initialization counts.
- The exact F303 image was flashed to a physical tinySA Ultra+ ZS407 (hardware
  V0.5.4, MAX2871), and its embedded version was verified before testing.
- Hardware checks rejected invalid trace copy/subtract/sample indices, marker 9
  and invalid marker-trace indices, palette IDs -1 and 32, and remote-menu paths
  -1 and 9999. All 32 palette rows were unchanged afterward.
- The complete built-in CAL-to-RF self-test passed after the candidate run.

The physical test uses only invalid indices, compares the palette before and
after, and confirms the shell remains responsive.
