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
- Physical ZS407 transcript: **pending the prepared four-image batch**.

The physical test uses only invalid indices, compares the palette before and
after, and confirms the shell remains responsive.
