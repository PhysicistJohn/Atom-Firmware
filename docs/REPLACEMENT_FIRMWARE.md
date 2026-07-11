# Replacement firmware architecture

The goal is not a cosmetic fork of the existing firmware. It is a modern,
measurably better instrument stack that preserves the ZS407's calibrated RF
behavior and recovery path while replacing accidental coupling with explicit,
testable subsystems.

## Product definition

The replacement should feel like one coherent instrument in three forms:

1. **On-device firmware** for deterministic acquisition, essential analysis,
   immediate controls and a polished 480×320 interface.
2. **PhysicistJohn desktop companion** for long traces, heavy analysis,
   automation and the richer Atomizer visual system.
3. **A future hardware profile** for real sampled-I/Q bandwidth if the ZS407
   board proves unable to expose a suitable sample stream.

These are complementary, not competing. The handheld must remain useful alone;
the host must not pretend that USB trace streaming turns RSSI into I/Q; and a
future board must use the same measurement/protocol contracts where possible.

## Non-negotiable invariants

- Stock calibration data is never silently reinterpreted or overwritten.
- RF output never becomes active as a side effect of boot, reconnect or screen
  navigation.
- DFU/recovery remains available and is tested before feature firmware.
- Existing shell behavior remains available until a versioned replacement API
  has equivalent coverage.
- Every RF or timing change has a stock-versus-candidate measurement record.
- A faster screen cannot starve sweep timing, and a faster sweep cannot make
  displayed or exported values less truthful.
- Builds identify source, compiler, configuration, binary hash and calibration
  schema.

## Target architecture

```text
                         +-----------------------+
                         | UI / interaction      |
                         | tiles, touch, jog     |
                         +-----------+-----------+
                                     |
                         immutable instrument snapshot
                                     |
+------------------+     +-----------v-----------+     +-------------------+
| USB protocol     +---->| instrument service    |<----+ storage/config    |
| shell + binary v2|     | commands + state      |     | schema + journal  |
+------------------+     +-----+-----------+------+     +-------------------+
                             request       result
                                  |         |
                         +--------v---------v-----+
                         | measurement engine     |
                         | sweep + zero span      |
                         +------+-----------+-----+
                                |           |
                       +--------v--+     +--v----------------+
                       | RF plan   |     | DSP/derived values|
                       | and HAL   |     | uncertainty/meta  |
                       +-----------+     +-------------------+
```

### 1. Platform layer

Owns clocks, interrupts, DMA, GPIO, SPI/I2C, ADC/DAC, USB, flash and time. It
must expose bounded operations rather than peripheral globals. Clock profiles
are explicit because changing 48 MHz behavior can move RF spurs.

Initial interfaces should include:

```c
typedef struct {
  uint32_t (*now_ticks)(void);
  void (*delay_ticks)(uint32_t ticks);
} clock_port_t;

typedef struct {
  bool (*write)(const uint8_t *tx, size_t length);
  bool (*transfer)(const uint8_t *tx, uint8_t *rx, size_t length);
} spi_port_t;
```

The actual API should carry timeouts and typed error results. The point is to
make ownership visible, not to add virtual-function machinery to every byte.

### 2. Hardware capability profile

Replace scattered `hwid`, `hw_if` and `max2871` branches with one immutable
profile built from measured identity:

```c
typedef struct {
  uint16_t hardware_id;
  uint32_t first_if_hz;
  uint64_t normal_input_max_hz;
  uint64_t fundamental_lo_max_hz;
  bool has_max2871;
  bool has_plus_if;
  bool has_audio_codec;
  bool has_raw_demod_gpio;
} hardware_caps_t;
```

Unknown identity must select a restricted diagnostic profile, never the most
aggressive frequency table.

### 3. RF planner and driver

Split pure frequency planning from register I/O:

- requested frequency/RBW/mode -> path, LO targets, receiver target, harmonic,
  correction domain and required settle class;
- plan -> deterministic register transaction list;
- transaction result -> acquisition metadata and faults.

That separation allows exhaustive host tests at every range boundary without
pretending to simulate RF. It also makes caching and batch programming safe:
the planner can prove which registers changed before the driver skips writes.

The first implementation should reproduce stock decisions exactly. Only then
should it introduce measured optimizations such as precomputed MAX2871 register
words, same-band hopping, receiver-offset compensation or pipelined display
work during analog settle windows.

### 4. Measurement engine

Owns sweep lifecycle and produces a complete result object:

```c
typedef struct {
  uint64_t start_hz;
  uint64_t stop_hz;
  uint32_t actual_rbw_hz_x10;
  uint32_t elapsed_us;
  uint16_t point_count;
  int16_t power_db_x32[MAX_POINTS];
  uint32_t flags;
} sweep_result_t;
```

The real design should avoid copying the point array between layers. Metadata
must say whether spur removal, harmonic mixing, interpolation, saturation,
averaging or early abort affected a sweep.

Use explicit states instead of `goto`-connected implicit modes:

```text
IDLE -> PLAN -> CONFIGURE -> SETTLE -> SAMPLE -> POSTPROCESS -> PUBLISH
                      ^                         |
                      +--------- next point ---+
```

Zero-span is a separate acquisition mode because its x-axis is time and its
valid DSP operations differ from a frequency sweep.

### 5. DSP and derived measurements

The canonical stored level should be fixed point (`dB × 32` or a documented
successor). Convert to float only at API or algorithms that genuinely benefit.
Power integration must occur in the linear power domain, with RBW and bin-width
metadata included.

The current firmware already attempts or exposes harmonic/IMD, OIP3, phase
noise, SNR, pass-band, width, AM/FM, THD, channel-power and noise-figure modes.
The replacement should test and regularize these before adding:

- 99%/configurable occupied bandwidth;
- adjacent-channel and alternate-channel power ratios;
- robust noise floor using median/quantiles and outlier rejection;
- peak list with prominence, width and persistence across sweeps;
- carrier-to-noise, SINAD-like envelope metrics where the data supports them;
- spectral-mask pass/fail with worst-margin location;
- harmonic table with uncertainty and harmonic-mixing warnings;
- band power over arbitrary gates rather than fixed thirds;
- sweep-to-sweep mean, variance, min/max and persistence;
- detector-aware peak, average, quasi-peak and time-domain statistics.

Every result needs a validity contract. For example, an ACPR number based on
insufficient sweep span or RBW should be `not_valid`, not a plausible float.

### 6. Presentation model and renderer

The UI consumes a published snapshot; it does not reach into live RF globals.
Use the existing 32×32 dirty-tile/DMA concept, then replace the visual language
and screen model. See [EMBEDDED_UI.md](EMBEDDED_UI.md).

The UI should be progressively updated:

- update the current trace segment as points arrive when that does not perturb
  acquisition timing;
- commit expensive labels, marker callouts and metrics once per sweep;
- render only invalidated tiles;
- coalesce repeated value changes from touch/jog input;
- reserve explicit visual states for commanded, settling, measuring, stale,
  clipped, uncalibrated and output-on.

### 7. Protocol layer

Keep the text shell for compatibility and diagnostics. Add a framed binary API
with:

- protocol and schema versions;
- request ID, command ID, payload length and CRC;
- capability discovery;
- typed errors rather than free-form strings;
- sweep metadata plus fixed-point samples;
- optional streamed chunks for more than 450 logical points;
- explicit generator arm/configure/enable operations;
- read-only session mode by default.

The desktop app can negotiate v2 and fall back to the stock shell. Recorded
frames become regression fixtures.

### 8. Storage and crash evidence

Persist settings as a versioned, checksummed record with two-phase commit. Keep
factory calibration in its existing protected region until a proven migration
tool exists. Add a compact crash record containing reset cause, firmware ID,
fault registers, stacked PC/LR and last instrument state; do not attempt a rich
LCD workflow from a naked fault context.

## LLVM strategy

LLVM is valuable here for diagnostics, sanitizer-backed host tests, modern
warnings, optimization experiments and future LTO—but compiler choice alone
does not make the RF path faster.

The first non-flashing hybrid experiment now builds successfully:

```text
selected app/drivers Apple clang 17.0.0, ARM hard-float Cortex-M4 target
RF core/main          Arm GNU 11.3.1
ChibiOS/HAL/startup   Arm GNU 11.3.1
assembler/linker/libc Arm GNU 11.3.1
result                217,044-byte binary (88.32% of app flash)
```

Run it with:

```bash
experiments/llvm/build-hybrid.sh
```

It is deliberately marked **do not flash**. At the current shared `-Og`
setting it is 31,340 bytes larger than the exact 185,704-byte official binary.
That is a measurement, not a verdict: GCC-specific `#pragma optimize("Os")`
directives are ignored by Clang, the old build rules mix compiler/link flags,
and this is not yet a tuned size build.

A controlled optimization matrix confirms that interpretation:

| Clang-object policy | Complete image | Flash use | GNU-baseline delta |
| --- | ---: | ---: | ---: |
| inherited `-Og` | 217,044 B | 88.32% | +31,340 B |
| `-O2` | 244,236 B | 99.38% | +58,532 B |
| `-Os` | 196,832 B | 80.09% | +11,128 B |
| `-Oz` | **184,136 B** | **74.93%** | **−1,568 B** |

Selected `-Oz` Clang modules already make a complete image smaller than the
exact release; broad `-O2` leaves only 1,524 bytes of flash. Neither is a
hardware result. The likely production policy is size optimization for UI and
control code, with `-O2` reserved for measured DSP/render kernels whose code
growth and RF timing are acceptable.

The spike exposed two real migration seams:

1. CMSIS 4.10 uses a GCC `"vfpcc"` inline-assembly clobber rejected by Clang.
   The hybrid keeps the GNU-built RTOS/FPU context code and uses a parser-only
   compatibility define for Clang application modules.
2. `hard_fault_handler_c()` is declared `naked` but contains ordinary C. Clang
   correctly rejects that. The RF-core translation unit stays on GCC until the
   fault entry is split into a minimal assembly veneer and a normal C reporter.

Compiling a driver in this experiment proves source compatibility only. It does
not qualify its generated timing or make that driver a production Clang
migration.

Compiler migration order:

1. Host-compile pure math/protocol modules with Clang and aggressive warnings.
2. Move fonts, trace math and renderer primitives to Clang firmware objects.
3. Replace per-file GCC pragmas with build-system optimization classes.
4. Modernize or narrowly patch CMSIS compiler support and test FPU context.
5. Fix the fault entry and split unity translation units.
6. Migrate hardware drivers one at a time with register/timing captures.
7. Evaluate LLD and LLVM LTO only after GNU-linked Clang objects are qualified.

Do not mix compiler migration with a ChibiOS upgrade. Each changes ABI,
interrupt, optimization and timing risk; independent steps make failures
diagnosable.

## Making response feel dramatically faster

The best gains are not all shorter total sweep time:

1. **Instrument the phase budget.** Count cycles and microseconds in planning,
   SPI programming, analog settle, RSSI read, postprocess and display.
2. **Avoid redundant device writes.** Cache complete hardware state and emit
   only changed register groups.
3. **Precompute the next plan.** Integer frequency math can overlap the current
   analog settle interval if bus ownership remains deterministic.
4. **Progressively present data.** A visible trace beginning immediately feels
   faster than a blank screen followed by a complete sweep.
5. **Use multi-resolution acquisition.** Survey coarsely, then refine detected
   regions; preserve the distinction between measured and interpolated bins.
6. **Decouple display cadence.** Do not redraw labels/menus for every point.
7. **Stream to the host concurrently in bounded chunks.** Never block the RF
   loop on an unready USB consumer.

The optimizer can improve planning, transforms and rendering. It cannot remove
PLL lock time, RBW filter response or the 24 MHz LCD wire time.

## More than 450 values without lying

`POINTS_COUNT == 450` is a storage/UI choice, not a law of RF physics. Options:

- retain 450 physical samples on-device but compute continuous marker
  interpolation and derived metrics;
- stream arbitrarily long sweeps to the host without retaining every point;
- acquire tiles/windows and merge them into a larger host trace;
- use a multiresolution trace: min/max envelope plus representative value per
  display column;
- reuse one trace buffer to offer a higher-point single-trace mode;
- move CPU-only scratch to CCM after stack/heap measurement.

The API and UI must distinguish physical measurements, aggregates and
interpolated display pixels.

## Future sampled-I/Q profile

If board inspection finds no viable sample tap, a true wideband replacement is
a hardware project. A future profile would add:

- quadrature downconversion or a direct-sampling RF/IF ADC;
- sample clock with characterized jitter;
- DMA-accessible sample RAM sized for at least two acquisition blocks;
- a newer MCU/SoC with materially more SRAM and DSP throughput;
- explicit anti-alias filtering and gain staging;
- calibration for amplitude, phase, I/Q imbalance and clock error;
- a transport capable of sustained sample or spectral streaming.

That profile can reuse the protocol, measurement types, UI semantics and host
analysis built for the ZS407. It should not force the first firmware milestone
to wait.

## Delivery sequence

| Milestone | Deliverable | Hardware gate |
| --- | --- | --- |
| R0 | exact stock reproduction and evidence | complete |
| R1 | stock unit characterization and rollback proof | required before flashing |
| R2 | host-tested RF planner, units and protocol parser | no modified flash needed |
| R3 | display-only Atomic UI prototype | rebuilt-stock qualification first |
| R4 | versioned protocol and richer metrics | RF regression suite |
| R5 | measured sweep/render optimizations | timing + RF captures |
| R6 | Clang RF-core candidate | full compiler/ABI/timing qualification |
| R7 | optional sample-tap experiment or hardware-v2 design | teardown authorization |

The success criterion is evidence: faster first trace, shorter qualified sweep,
lower UI latency, more valid metrics, better recovery, clearer state or easier
maintenance—with no unexplained RF regression.
