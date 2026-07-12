# Performance and DSP plan

This document turns “LLVM, bit tricks, wider FFTs and faster response” into
specific experiments with budgets and validity rules. The first principle is
to optimize the bottleneck actually measured, not the loop that looks oldest.

## Baseline budgets

### Acquisition

The current sweep-time estimator uses:

```text
normal bare sweep ~= points × (step_delay_us + 127 us)
repeat overhead   ~= points × (repeat - 1) × 111 us
spur removal      ~= 2 × bare sweep
```

At 450 points, the fixed 127 µs term alone is 57.15 ms. Actual time also
includes frequency-dependent MAX2871/receiver programming and analog settling;
the code can multiply short settle delays by two or three in ZS407 paths. The
official specification conservatively claims more than 1,000 points/s with the
largest RBWs, or under roughly 450 ms for 450 points.

Fast zero-span has a configured 1.8 ms minimum estimate, but that is not proof
of 250 ksample/s independent measurements. The Si4468 RSSI update rate,
receiver bandwidth, SPI loop, trigger path and actual elapsed timestamp must be
measured together before assigning a sample rate or FFT frequency axis.

### Display

```text
frame pixels              480 × 320 = 153,600
RGB565 bytes              307,200
expected LCD SPI           24,000,000 bit/s
full-frame wire floor      102.4 ms
absolute full-frame rate   9.77 frame/s
one 32×32 tile             2,048 bytes = 682.7 µs wire time
full screen                15 × 10 = 150 tiles
```

Command overhead and rendering make real values slower. The correct target is
not “60 fps”; it is sub-frame dirty updates, immediate control feedback and no
visible blanking.

### CPU and memory

- Cortex-M4F, currently 48 MHz rather than the 72 MHz device maximum.
- 240 KiB application flash; exact stock binary uses 185,704 bytes.
- 40 KiB ordinary SRAM is fully assigned by the linker, with a 7,328-byte
  remainder represented as heap.
- 8 KiB CCM SRAM is unused, CPU-only and inaccessible to DMA.
- Four 450-element float measurement traces consume 7,200 bytes.
- The two LCD tile buffers together consume 4,096 bytes and are also reused by
  some storage/experimental code.

Clocking at 72 MHz is not an initial optimization. The source deliberately
shifts HSI trim around 48 MHz to move digital spurs; a clock change requires a
full RF spur survey plus timer, USB, ADC and SPI requalification.

## FFT: what can actually be widened

There are three distinct operations that are easy to conflate.

### 1. FFT of zero-span RSSI versus time

This can estimate periodic envelope or modulation content. It has a meaningful
time sample interval only after the RSSI loop is timestamped and shown to be
uniform. It cannot recover carrier phase, I/Q, modulation sign, negative
frequencies or signals outside the tuned receiver channel.

For `N` uniformly spaced samples at measured rate `Fs`:

```text
bin spacing       Fs / N
Nyquist limit     Fs / 2
record duration   N / Fs
```

Increasing `N` narrows bins and lengthens observation time; it does **not**
increase the receiver's instantaneous RF bandwidth.

### 2. Transform across a swept frequency trace

The x-axis is already RF frequency. A transform may help with RBW-kernel
deconvolution, correlation or feature detection, but its output is not a wider
RF spectrum. Sweep samples must first be uniformly spaced and expressed in the
appropriate linear domain.

### 3. FFT of real IF or I/Q samples

This is the familiar wideband spectrum-analyzer mode, but the shipped data path
does not supply these samples to the MCU. It becomes possible only if physical
inspection finds a sufficiently wide and safely loadable IF/test path, or in a
future hardware revision.

## Existing FFT archaeology

The source already contains:

- an always-defined radix-2 floating-point complex `FFT()` in `sa_core.c`;
- disabled `__FFT_VBW__` filtering fixed at 256 points;
- disabled `__FFT_DECONV__` code using four 256-float arrays;
- a disabled, older Q15 `fix_fft()` implementation with a 1,024-entry sine
  basis;
- disabled MCU ADC acquisition and FFT test code.

The float experiments alias their arrays onto the 4,096-byte LCD/SPI buffer:

```text
real[256] + imag[256]                  2,048 bytes
real + imag + real2 + imag2            4,096 bytes
```

That explains the hard-coded length and also means display DMA cannot safely
own the same buffer concurrently. The code is valuable design history, but it
lacks production memory ownership, numerical tests and measurement semantics.

## Practical FFT memory envelopes

The following are scratch-only lower-order estimates; instance tables can live
in flash, while windows, magnitudes and overlap state add memory.

| N | Q15 complex in-place (`4N`) | CMSIS Q15 real, separate input/output (`6N+4`) | float complex real+imag (`8N`) |
| ---: | ---: | ---: | ---: |
| 256 | 1,024 B | 1,540 B | 2,048 B |
| 512 | 2,048 B | 3,076 B | 4,096 B |
| 1,024 | 4,096 B | 6,148 B | 8,192 B |
| 2,048 | 8,192 B | 12,292 B | 16,384 B |
| 4,096 | 16,384 B | 24,580 B | 32,768 B |

The CMSIS Q15 figure follows the documented legacy real-FFT requirement: `N`
Q15 input samples and `2N+2` Q15 output samples because it also writes the
conjugate half. Newer APIs/versions and custom packed transforms may differ.
See the [CMSIS-DSP real FFT documentation](https://arm-software.github.io/CMSIS-DSP/latest/group__RealFFT.html).

Consequences:

- A tested 1,024-point Q15 real FFT can fit in 8 KiB CCM with roughly 2 KiB left
  for window/magnitude state.
- A 1,024-point float complex buffer exactly consumes CCM and leaves no margin.
- A 2,048-point Q15 complex in-place buffer fits exactly but is operationally
  unrealistic without additional scratch.
- DMA input/output must remain in ordinary SRAM and be copied or processed in
  blocks because DMA cannot access CCM.

Start at 256 or 512 points. Widen only when measured resolution and use cases
justify memory and record-time cost.

## DSP representation

### Keep detector data fixed point

The detector begins as an 8-bit RSSI code and current intermediate precision is
1/32 dB in `int16_t`. Preserve that exact representation for correction and
display paths while building reference conversions in double precision on the
host.

Suggested domains:

| Quantity | Embedded representation | Notes |
| --- | --- | --- |
| corrected level | signed dB × 32 (`q_db32`) | compatible with current math |
| linear amplitude | Q1.15 where normalized | FFT/window/FIR input |
| relative linear power | Q1.31 or scaled `uint32_t` | band integration |
| accumulated power | signed/unsigned 64-bit | avoid overflow across bins |
| frequency | `uint64_t` Hz | existing high ranges require it |
| normalized screen coordinate | Q16.16 or integer rational | avoid float in per-pixel loops |

Do not convert dB values directly to Q15 and sum them for channel power. Convert
to linear power, integrate with actual bin width/RBW correction, then convert
the result back to dB.

### Numerical acceptance tests

Every fixed-point kernel needs host-generated vectors covering:

- zero, full scale and one-LSB inputs;
- alternating extrema and worst-case accumulator growth;
- impulses at every alignment;
- single tones both on and between bins;
- two-tone dynamic-range cases;
- DC offset and ramps;
- saturation and rounding boundaries;
- forward/inverse scale factors;
- window coherent gain and equivalent noise bandwidth;
- comparison with double-precision reference and explicit tolerance.

## Useful Cortex-M4 bit/DSP techniques

Use intrinsics when the instruction matters; do not rely on either compiler to
discover every packed operation from clever C.

### Packed Q15 dual multiply-accumulate

`SMLAD` performs two signed 16×16 multiplies and accumulates into 32 bits. It is
well suited to pairs of Q15 FIR/window samples, dot products and two-bin power
work. Align loads and define saturation/accumulator bounds first.

Conceptually:

```c
int32_t acc = 0;
for (size_t i = 0; i < count; i += 2) {
  acc = __SMLAD(packed_samples[i / 2], packed_coeffs[i / 2], acc);
}
```

### Saturation instead of overflow branches

Use `SSAT`/`USAT` for well-defined narrowing. C signed overflow is undefined;
“it wraps on GCC” is not a portable DSP contract.

### Leading-zero count for logarithms and normalization

`CLZ` cheaply finds the exponent of a positive fixed-point value. Combine it
with a small mantissa lookup/polynomial for log2, dB conversion and block
floating normalization. Validate error in dB over the full detector range.

### Reciprocal multiply for repeated division

For a constant or slowly changing positive divisor, compute a scaled reciprocal
once and replace repeated divisions with a wide multiply and shift. Use exact
integer division for configuration boundaries where one-hertz correctness is
more important than cycles.

### Word-wide pixels

The renderer already clears eight RGB565 pixels per loop using 32-bit stores.
Extend this carefully for:

- paired-pixel fills and horizontal spans;
- prepacked grid/trace colors;
- clipped line masks per tile;
- glyph row expansion from bit masks.

The bus, not the clear loop, dominates a full screen. Optimize word stores when
profiling shows CPU rendering delays DMA, not simply because they are elegant.

### Branchless clipping only where predictable

Packed min/max, saturating arithmetic and lookup tables can reduce hot-loop
branches. On a Cortex-M4 without a data cache or sophisticated predictor,
simple predictable branches can still be cheaper and clearer. Measure both
generated instructions and cycle counts.

## Faster sweeps: priority order

### P0 — add observability

Record min/mean/max for:

- frequency-plan computation;
- MAX2871 transaction time;
- Si4468 transaction time;
- requested settle delay and actual elapsed delay;
- RSSI read/repeat time;
- per-point correction math;
- sweep postprocessing;
- dirty-tile render CPU time;
- LCD DMA wait time;
- USB write blocking time.

Use the Cortex-M DWT cycle counter for CPU regions and a spare GPIO/DAC trace
only when it is proven not to contaminate RF. Store a small ring of timing
counters rather than printing inside the acquisition loop.

### P1 — eliminate redundant work

- Cache the last complete synthesizer and receiver configuration.
- Precompute constant divider/modulus choices for monotonic sweep runs.
- Replace repeated frequency-table searches with a cursor when frequency is
  monotonic.
- Calculate correction-table segment slopes once per region.
- Move invariant unit/display conversions out of the point loop.
- Update marker/metric state once per completed or intentionally partial sweep.

### P2 — schedule around unavoidable settling

Use analog settle windows to prepare the next pure plan, advance display state
or enqueue a bounded USB chunk. Never touch a shared RF SPI bus during a settle
interval unless measurement proves the digital activity is harmless.

### P3 — adaptive acquisition

A coarse survey followed by focused windows can deliver useful information
earlier. The trace data model must mark:

- physically measured bins;
- min/max aggregates;
- interpolated display points;
- different RBW/attenuation/path regions;
- acquisition timestamp or sweep generation.

Do not draw a smooth 2,048-bin line and imply 2,048 RF measurements when only
450 were taken.

## Better VBW and postprocessing

FFT filtering is usually not the best VBW implementation. A short symmetric
FIR, cascaded one-pole IIR or sweep-to-sweep exponential average uses less RAM,
has predictable latency and can be updated as points arrive. Choose based on
desired detector behavior:

- frequency-axis smoothing for trace readability;
- time-axis averaging at the same RF bin for noise reduction;
- peak/max/quasi-peak detector dynamics;
- median/outlier suppression for impulsive artifacts.

These are different operations and need different labels. Preserve peaks by
offering min/max envelope or peak-hold alongside any smoothed trace.

Deconvolution is an offline/experimental measurement until the RBW impulse
response is measured for every relevant filter/path and regularization prevents
noise explosion. A larger FFT does not fix a wrong kernel.

## Derived measurements: cheap wins

Most valuable metrics are `O(N)` over 450 points and far cheaper than one PLL
settle sequence:

- robust peak list;
- integrated power inside one or more gates;
- occupied bandwidth by cumulative power;
- ACPR/alternate-channel ratio;
- spectral mask margin;
- noise-floor median/percentiles;
- trace delta/variance across sweeps;
- time occupancy above threshold;
- marker interpolation with a local parabolic/log-domain fit.

Compute shared primitives once: linearized bin power, prefix sums, peak list and
noise estimate. Many metrics then become constant-time range queries rather
than independent scans.

## LLVM optimization matrix

The current firmware uses global `-Og`, no LTO and GCC per-file/per-region
`optimize("Os")` pragmas. One region explicitly says `Os` causes a problem.
Treat that as evidence of undefined behavior or timing coupling until proven
otherwise.

Build and compare at least:

| Variant | Purpose |
| --- | --- |
| GCC 11.3 `-Og` exact baseline | binary/provenance anchor |
| GCC 11.3 `-Os` by safe module | size and obvious timing regressions |
| Clang 17 `-Og` hybrid | compatibility and warnings; now builds |
| Clang `-Oz` by pure module | flash recovery |
| Clang `-O2` by DSP/render module | performance candidate |
| Clang/GNU link with section GC | controlled migration |
| LLVM LTO later | only after ABI/ISR/hardware tests |

The initial whole-admitted-module measurements are already informative:

```text
exact GNU image       185,704 B
Clang hybrid -Oz      184,136 B
Clang hybrid -Os      196,832 B
Clang hybrid -Og      217,044 B
Clang hybrid -O2      244,236 B
```

`-Oz` recovers all of the initial Clang size growth and beats the exact GNU
image by 1,568 bytes. Applying `-O2` broadly consumes 99.38% of application
flash. The next matrix must therefore be per module: size-first UI/control plus
targeted speed builds only for cycle-proven kernels.

For each variant record binary/section/symbol sizes, stack usage, generated
assembly of critical functions, host vector results, point timing, sweep timing,
RF output/spurs and display behavior. “LLVM is faster” is not a result until a
qualified image demonstrates it.

## Initial performance targets

These are experiment targets, not promises:

| Area | First measurable target |
| --- | --- |
| control feedback | dirty-region response visible within 50 ms when RF-safe |
| first trace evidence | first measured segment shown before sweep completion |
| completed-sweep UI | labels/metrics committed within one 32×32 tile-frame budget after acquisition |
| pure metric suite | all common O(N) metrics under 2 ms at 48 MHz |
| Q15 FFT | measure the 1,024-point transform in CPU cycles on the F303; establish a safe target from the first physical benchmark |
| display | no full-screen clear during normal sweep/menu interaction |
| flash | recover at least 15 KiB before adding a production DSP library |
| RAM | preserve measured stack margin and at least 1 KiB emergency headroom per active context |

The physical baseline will replace estimates with real budgets before any
optimization image is flashed.
