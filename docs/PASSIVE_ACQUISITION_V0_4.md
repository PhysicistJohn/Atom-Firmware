# Passive acquisition candidate v0.4

This profile turns the v0.3 DSP and protocol foundations into a bounded,
device-side passive-acquisition pipeline. It is built from the exact
hardware-qualified v0.3 source checkpoint `43eb0f1`, but v0.4 itself is not
hardware-qualified and must not be flashed until the physical gate at the end
of this document is run.

Build the profile with:

```sh
make TARGET=F303 PHASE=6 RELEASE_PROFILE=passive-v0.4
```

The build contains no automatic flash step. RF output, AWG execution, binary
USB ownership, passive streaming, adaptive rescan execution and zero-span
capture execution all remain locked.

## What is implemented

| Capability | Implementation | Unqualified-image behavior |
|---|---|---|
| Device time | 64-bit extension of the 10 kHz ChibiOS tick, including wrap and regression detection | Records every completed input sweep |
| Sweep identity | 32-bit trace/sequence number plus completed, published, dropped and invalid counters | Records completion; publication counters remain zero |
| Passive stream | Completed trace encoded in a single acquire/release slot and drained only by the USB worker | Start returns `NOT_QUALIFIED` |
| Compact trace | ZigZag delta plus ULEB128 selected only when smaller, otherwise raw dB×32 plus validity bitmap | Codec and fallback are linked and self-tested |
| Adaptive scan | Strongest-first peak selection, bounded top-N retention, overlap merging, rational frequency mapping and truncation flags | Plan-only; never changes analyzer settings |
| Trigger capture | Rising threshold with hysteresis, optional pre-trigger ring, 256/512/1,024 samples, timing and discontinuity statistics | Arm returns `NOT_QUALIFIED` |
| Envelope FFT | Mean removal, Hann window, normalized Q1.15 radix-2 FFT, peak-bin and magnitude summary | Runs in self-test; live capture remains locked |
| Host contract | Schema 3 C, Swift, JavaScript and TypeScript payloads for clock, acquisition, adaptive windows and capture results | Available to host software now |

## Data path and backpressure

The acquisition hook runs only after the legacy sweep function returns a
completed input trace. It does not run in an ISR and does not change `perform`,
RF tuning, settling, detector post-processing, calibration or display timing.

```text
legacy RF sweep and detector processing
    -> completed trace is stable
    -> extend device tick and ledger sequence/duration
    -> optional dB×32 conversion and delta/raw encode
    -> one acquire/release frame slot
    -> higher-priority ChibiOS USB worker
    -> CDC output queue / USB ISR
```

The producer never waits for USB. If the slot is still owned by the consumer,
the entire next trace is dropped and the drop counter increments. Partial
frames are never exposed. This deliberately favors acquisition cadence and
honest loss accounting over hidden blocking.

The full frame is 1,038 bytes in the worst case. It is not reserved in BSS.
Only after both private qualification latches pass does the runtime lease the
first 1,038 bytes of the linker-defined unused-RAM region. ChibiOS heap and
memcore are compile-time disabled, and the lock audit proves that no allocator
or qualification setter is linked. The current image therefore retains more
than 4 KiB of unused ordinary SRAM and leases none of it at runtime.

## Timestamp semantics

`timestamp_us` is the estimated start of the completed sweep:

```text
extended completion tick - firmware-measured sweep duration
```

It is a monotonic, boot-relative device timestamp, not UTC and not a disciplined
multi-unit clock. The wire clock snapshot returns the device clock ID, current
raw tick, tick rate, flags and a 64-bit microsecond estimate. A host can perform
repeated request/response exchanges and fit offset and drift for approximate
multi-unit alignment. This does not create phase coherence, I/Q coherence or a
shared sampling clock; those require external timing hardware or hardware v2.

The base tick is 100 microseconds. Sweep start is therefore quantized to that
resolution, while duration comes from the existing firmware measurement.
Sequence and drop counters are authoritative when reconstructing a time series.

## Compact trace wire format

The existing 56-byte trace header is unchanged. Flag bit 2 identifies a compact
tail. In compact mode `validity_bytes` is zero and the tail contains exactly
`point_count` ZigZag-delta/ULEB128 values. The `-32768` invalid sentinel is
encoded as an ordinary value. In raw mode the original signed 16-bit samples
and validity bitmap remain unchanged.

The encoder first tries compact form directly inside the final frame buffer.
It then shrinks the reserved frame, recomputes CRC over the exact length and
commits it. If compact data is not smaller or does not fit, the encoder
deterministically overwrites the payload with raw form. A representative
450-point trace is 511 bytes including metadata versus 1,013 bytes raw on the
current Mac benchmark, a 49.6% payload reduction. Alternating full-scale input
is explicitly tested as an expansion case and takes the raw fallback.

## Adaptive refinement

The planner accepts a completed dB×32 trace, a rational frequency axis, a noise
estimate, minimum prominence, window radius and desired refined point count.
It finds local maxima, retains the strongest bounded set, merges overlapping
windows and reports source indices, exact start/stop frequencies, peak index,
priority and truncation/merge flags.

The shell command uses a 20th-percentile noise estimate, 6 dB prominence,
four-bin radius, four retained windows and 201 refined points:

```text
modern passive plan
```

It is intentionally a dry run. Automatically rewriting start/stop/RBW and
revisit cadence must be qualified against real intermittent signals and UI
interaction before an executor is added.

## Triggered zero-span FFT

The capture engine consumes calibrated RSSI trace points from completed
zero-span sweeps. It supports power-of-two lengths of 256, 512 and 1,024,
rising threshold detection, hysteresis and a bounded pre-trigger history. It
tracks first/last timestamps, minimum/maximum inferred sample delta and
cross-sweep timing discontinuities. A completed legacy sweep provides only its
start estimate and total duration, so timestamps inside each sweep are
explicitly flagged as interpolated; v0.4 does not claim per-point hardware
timestamping or intra-sweep jitter measurement. Before the FFT it:

1. reorders the pre-trigger ring into chronological order;
2. removes the mean;
3. normalizes without floating point;
4. applies a lookup-based Hann window; and
5. runs the 1,024-capable saturating Q1.15 FFT.

The capture shares the existing 4 KiB CCM DSP union: RSSI samples occupy the
real half and the imaginary half is the reorder/FFT workspace. Streaming and
capture are mutually exclusive, so no duplicate 1,024-sample buffer is added.

This is an FFT of detected RSSI versus time. It can reveal envelope repetition,
burst cadence and modulation-rate energy, but it is not a 1,024-bin
instantaneous RF spectrum and cannot recover phase, sign of frequency offset or
quadrature information.

At the normal 450 trace points, a 1,024-sample capture necessarily spans at
least three completed zero-span sweeps. Boundary gaps are included and counted;
they are not silently treated as contiguous samples.

## Commands in the candidate

```text
modern passive status   # clock, sequence/drop ledger, slot and capture state
modern passive clock    # same status with explicit clock line
modern passive selftest # frame, wrap, capture and FFT fixture; no RF mutation
modern passive plan     # strongest-first dry-run refinement of current trace
modern passive start    # deliberately returns NOT_QUALIFIED
modern passive capture  # deliberately returns NOT_QUALIFIED
```

Protocol commands 4–7 expose clock snapshot, acquisition status, adaptive-plan
namespace and zero-span capture summary. The locked transport responds to clock
and acquisition status once USB ownership is separately qualified; adaptive
execution remains unsupported and capture summary is returned only after a
qualified capture exists.

## Hardware-free evidence

The candidate is required to pass all of the following before packaging:

- native and embedded-math UBSan suites;
- 100,000 deterministic protocol/compact-trace mutations;
- 50,000 exact single-slot producer/consumer frames under real host threads;
- two million bytes through the existing SPSC stress test;
- clock wrap/regression, saturating ledger and raw-fallback edge cases;
- 256- and 1,024-point triggered FFT numerical fixtures, including pre-trigger
  wrap and injected timing discontinuity;
- schema 3 golden bytes in C, Swift and JavaScript plus generated TypeScript;
- GNU and LLVM freestanding Cortex-M4 compilation;
- exact clean-build reproducibility, unresolved-symbol and stack-usage checks;
- RF-output, binary-transport and passive-gate disassembly audits; and
- a source-derived Renode run that executes completed sweeps, advances the
  clock/ledger, observes a modeled 450 MHz tone, proves all passive latches and
  counters remain closed, and proves no stream buffer was leased.

Host performance numbers are informational because the Cortex-M4 cost differs.
The current Mac run measured roughly 1.1 microseconds to encode a smooth
450-point compact trace, 0.3 microseconds to plan refinement and 38 microseconds
for the complete 1,024-point preprocessing/FFT pipeline. The physical v0.3
Cortex-M4 FFT benchmark remains the relevant device budget: about 1.923 million
cycles, or 40 ms at 48 MHz, before the additional linear preprocessing pass.

## Physical qualification still required

Another agent currently owns the hardware, so none of these steps has been run
for v0.4. When it is available, test one gate at a time:

1. flash only the committed/reproducible v0.4 candidate and cold-start it;
2. run the full built-in self-test, `modern selftest`, `modern dsp-selftest`,
   `modern passive selftest`, `modern audit` and `modern fft-bench`;
3. leave streaming/capture locked and compare ordinary sweep time, UI response,
   battery reporting and RF self-test with v0.3;
4. in a separate qualification-only build, hand USB ownership to binary mode,
   validate reconnect/recovery, decode both compact and adversarial raw traces,
   saturate the host deliberately and verify exact drop accounting;
5. measure device/host timestamp offset and drift over at least 30 minutes;
6. qualify zero-span interval and jitter at several sweep times before arming a
   1,024-point capture; and
7. compare envelope FFT bins against a known pulsed source while checking that
   analyzer and self-test behavior remain unchanged after a cold restart.

Until those steps pass, the correct release statement is: **implemented,
cross-compiled and executable-twin verified; physical execution locked**.
