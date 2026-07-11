# Atomic embedded UI for 480×320

The replacement display should be recognizably related to the **tinySA
Atomizer** desktop interface in the sibling `TinySA` repository, without
pretending a 48 MHz MCU and serial RGB565 panel can render browser CSS.

The visual source of truth inspected for this plan is:

- `TinySA/apps/desktop/src/renderer/styles.css`
- `TinySA/apps/desktop/src/renderer/components/SpectrumPlot.tsx`
- `TinySA/.artifacts/atomic-ui-live-sweep.png`
- `TinySA/.artifacts/atomic-ui-generator.png`

The transferable design language is not blur or gradients. It is hierarchy:
one dominant measurement plane, low-contrast structure, mint energy/state,
monospaced values, clear safety state and small amounts of violet/amber/red for
meaning.

## Embedded design tokens

Use semantic tokens so a palette change does not leak through measurement code.
The renderer can convert RGB888 constants once to the firmware's byte-ordered
RGB565 representation.

| Token | Desktop source | Embedded role |
| --- | --- | --- |
| `surface.canvas` | `#090b0c` | full-screen background |
| `surface.panel` | `#111516` | cards, menu rail, callouts |
| `surface.raised` | `#171c1c` | selected control or modal |
| `text.primary` | `#f2f3ee` | major value/title |
| `text.secondary` | `#c1c7c4` | labels and secondary readings |
| `text.muted` | `#858e8b` | units, inactive state |
| `line.grid` | approximately `#23302d` | plot grid and dividers |
| `energy.mint` | `#79f2c3` | live trace, active selection, safe ready |
| `energy.bright` | `#a1ffd8` | peak node/highlight |
| `signal.cyan` | `#6ee1e8` | secondary trace/reference |
| `signal.violet` | `#9b8cff` | third trace/analysis mode |
| `state.amber` | `#f4c66b` | caution, simulated/stale/uncalibrated |
| `state.red` | `#ff7e72` | RF output active, clipping, fault |

Do not spend cycles on per-pixel alpha. Precompute a few blended solid colors
for dim borders, fills and trace under-strokes.

## Default spectrum layout

```text
0       32                         382  480
+-------+----------------------------+----+  y=0
| mode  | 98.000 MHz   RBW 10 kHz    |bat |  24 px status
+-------+----------------------------+----+  y=24
| -20   |                                 |
|       |       measurement plane         |
| dBm   |          M1 ●                    |  208 px plot
|       |                                 |
| -120  |                                 |
+-------+---------------------------------+  y=232
| PEAK -60.0 | FLOOR -90.2 | OBW 182 kHz |  48 px metrics
+---------------------+-------------------+  y=280
| 88 MHz   LIVE 01    | 108 MHz   57 ms  |  40 px command/status
+---------------------+-------------------+  y=320
```

Dimensions are starting points, not frozen ABI. The important choices are:

- the plot remains dominant;
- current mode/output/battery state is always visible;
- three most relevant metrics are readable without opening a menu;
- frequency endpoints and acquisition state stay anchored;
- no permanent desktop-style navigation sidebar consumes 20% of the display.

When a menu is open, use a 96-pixel contextual rail on the right and reduce the
plot to 384 pixels wide. Six approximately 52-pixel-high targets fit the screen.
The current firmware's 80-pixel rail proves the interaction model; the redesign
adds clearer icons/state and larger touch targets.

## Screens

### Spectrum

- Mint primary trace with one dark-mint under-stroke to suggest glow.
- Low-contrast 8×4 or 10×5 grid selected from available plot area.
- Peak marker: bright ring/node, thin dashed or sparse stem and a compact solid
  callout containing marker ID, level and frequency.
- Detection/limit gates: dim amber vertical band or edge ticks, not translucent
  browser overlays.
- Metric strip is mode-aware: peak/floor/occupied bandwidth by default;
  channel power/ACPR in channel mode; carrier/deviation/SNR in modulation mode.
- “Measured”, “interpolated”, “stale”, “clipped” and “harmonic” states have
  visible glyphs or labels.

### Zero span

- Time axis and sample/record duration replace frequency endpoints.
- Trigger position is explicit.
- Optional envelope FFT is a second view with `ENVELOPE FFT` in its title; it
  must never be labeled as instantaneous RF spectrum.
- Detector mode and effective sampling interval are visible.

### Generator

The desktop generator screen's strongest idea is a dominant output state.
Preserve it:

```text
RF OUTPUT

             OFF

100.000000 MHz       -40 dBm

[ Configure ]        [ Hold to enable ]
```

- `OFF` uses muted mint/white; `ON` uses red plus a persistent border/status
  indicator everywhere.
- Configuration and enable are separate actions.
- Reconnect/boot state is always output off.
- Enabling requires a deliberate hold or two-step confirmation.
- The UI states that software is not a physical interlock.

### Measurement workspace

Expose derived results as a small result card over the same trace rather than a
new maze of menus. Examples:

- occupied bandwidth with left/right power cursors;
- ACPR with center/adjacent gates;
- harmonic table with current harmonic highlighted;
- mask result with worst violation marker;
- persistent-signal list ordered by power or frequency.

### Settings and diagnostics

Separate ordinary acquisition settings from lab/diagnostic controls. Clock
trim, raw register commands, correction editing, DFU and calibration writes
belong behind a `LAB` label and confirmation. Runtime hardware profile, build
hash, reset cause and calibration schema should be easy to inspect.

## Input model

The display has resistive touch and a jog/push control. Design for both:

- minimum primary touch target: about 44×44 pixels; prefer 48×48;
- single tap selects, jog rotates through siblings, press activates;
- long press/hold is reserved for clearly labeled safety actions;
- drag is used for marker movement or a single slider, never required for core
  navigation;
- value editing offers coarse/fine decade focus rather than a tiny keyboard for
  every adjustment;
- selected/focused state uses both color and a border/shape.

Avoid hover assumptions from desktop. Every control must have a visible idle,
focused, active, disabled and fault state.

## Renderer architecture

Retain the existing 32×32 cell renderer and double-buffered LCD DMA. Replace
its immediate global-state coupling with a display list per tile or compact
snapshot-driven primitives.

Suggested frame phases:

1. Publish an immutable UI snapshot after state changes.
2. Diff semantic regions and mark intersecting tiles dirty.
3. Render one dirty tile into the idle half-buffer.
4. Start DMA for that tile.
5. Render the next tile while DMA owns the previous half-buffer.
6. Defer low-priority decoration if RF acquisition has a deadline.

Priority order:

```text
output/fault state > control feedback > live trace > marker > primary values
> metric strip > grid/decorative details
```

### Primitive set

Keep a small, fast vocabulary:

- clipped solid rectangle and 1-pixel divider;
- horizontal/vertical span;
- Bresenham/polyline segment clipped to one tile;
- 1-bit glyph/icon mask with foreground/background modes;
- rounded-corner mask for a few fixed radii;
- dotted/dashed line with deterministic phase;
- paired trace under-stroke and bright stroke;
- compact numeric formatting into caller-provided buffers.

Rounded cards can be four corner masks plus spans. Do not implement general
anti-aliased vector paths on the first firmware.

### Trace rendering

Precompute x/y coordinates once per published sweep. For each display column,
retain min and max when multiple physical samples map to one pixel; this shows
narrow peaks more truthfully than choosing one sample. When display pixels
outnumber samples, connect measured coordinates but do not invent data for
metrics.

The desktop gradient trace becomes:

1. a 3-pixel dark-mint/cyan clipped polyline;
2. a 1-pixel bright mint polyline over it;
3. optional violet only for a separate trace or analysis state, not a costly
   per-pixel gradient.

### Text

- Large values: compact fixed bitmap font, tabular digits.
- Units/status: 5×7 or 7×13 font in muted color.
- Limit dynamic font scaling; select from two proven sizes.
- Format frequency/level once per state change, not per tile.
- Never use `sprintf` in a render hot path where the existing bounded formatter
  suffices.

## Dirty-region policy

Examples:

| Change | Dirty region |
| --- | --- |
| one new trace segment | tiles intersecting old and new segments |
| marker move | old marker/callout tiles plus new marker/callout tiles |
| battery change | top-right status tiles only |
| metric value change | corresponding metric card only |
| menu focus change | old and new button tiles |
| menu open/close | right rail plus newly exposed plot tiles |
| generator output transition | entire status band and generator state card |

Avoid full-screen invalidation for a color-independent value change. Keep old
and current dirty maps, as the existing renderer does, so erased geometry is
repainted correctly.

## Animation policy

Animation is functional, sparse and deadline-aware:

- one- or two-frame focus transitions;
- acquisition sweep cursor only if it does not add RF interference or missed
  deadlines;
- live dot toggled at a low rate;
- no continuous orbital logo, blur, background gradients or full-screen fades;
- disable decoration automatically during long/precise sweeps if required.

The Atomic identity comes from proportion, color and clarity—not motion.

## Remote visual validation

The firmware already supports remote desktop/screen readback. Use it to create
golden screenshots for:

- empty/disconnected diagnostic state;
- normal spectrum with marker;
- menu open and focused by jog;
- limit violation/clipping;
- zero-span trigger;
- generator off/configured/on confirmation;
- unknown hardware and uncalibrated warnings;
- battery low and SD/USB activity;
- all four trace colors against grid and callouts.

Add image comparisons with tolerances for known dynamic fields, then perform a
physical review for viewing angle, brightness, touch alignment and real LCD
color. A screenshot cannot reveal SPI tearing, DMA stalls or readability in
daylight.

## First UI implementation slice

1. Extract semantic palette and bounded text formatting.
2. Add a snapshot structure without changing the stock screen.
3. Implement the top status band and three-card metric strip using dirty tiles.
4. Render the Atomic trace/marker treatment on the existing coordinate cache.
5. Add a generator output state screen while retaining stock command behavior.
6. Capture remote screenshots and timing counters.
7. Hardware-test display noise, touch, jog, battery and long sweeps before
   replacing the remaining menu surfaces.

The target is a display that looks intentional and modern while staying honest
about every measurement and every commanded RF state.
