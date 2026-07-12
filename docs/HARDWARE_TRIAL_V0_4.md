# ZS407 passive acquisition v0.4 Stage 1 hardware receipt

This receipt records the first physical execution of the locked passive
acquisition candidate. It qualifies normal boot, analyzer regression,
device-side diagnostics and fail-closed behavior. It does not qualify live
binary streaming, triggered capture or adaptive analyzer control.

## Artifact and device identity

| Fact | Observed value |
| --- | --- |
| Test date | 2026-07-12 (America/Los_Angeles) |
| Source commit | `c945d24e9c2c80e4a0e34380b58b4ec405316dc9` |
| Embedded version | `tinySA4_lab-v0.4-passive-gc945d24` |
| Binary size | 219,928 bytes |
| Binary SHA-256 | `3ec209448ede8031baeba99445f375725c939f925034c2df96aaa2063f846636` |
| Instrument | tinySA ULTRA+ ZS407 |
| Hardware readback | `V0.5.4 max2871` (`hwid=103`) |
| MCU/platform | STM32F303xC, ARMv7E-M Cortex-M4F |
| Radio readback | Si4468 rev 2, ROM 6, firmware 6.0.7 |
| Battery readback | 4,236 mV |

The candidate was rebuilt twice reproducibly before the trial. Host tests,
F072 regression, output-lock audits, protocol/passive lock audits and the
source-derived executable twin all passed. The verified official rollback
image remained available throughout.

## Safe flash transaction

The user ran the stock/baseline built-in self-test before entering DFU and
reported a pass. DFU enumeration found exactly one physical STM32 device,
serial `2066365B2036`, at path `2-1`, with alt 0 internal flash and alt 1 option
bytes. `dfu-util 0.11` selected only alt 0 and address `0x08000000`.

The ROM endpoint initially reported `dfuERROR` status 10, which `dfu-util`
cleared to `dfuIDLE`. Erase and download each reached 100%; the utility then
reported `Download done`, `File downloaded successfully`, submitted leave and
entered manifest. Option bytes were not selected or written. The raw BIN's
missing DFU suffix produced the expected warning and did not affect the
successful DfuSe address transfer.

After normal boot, the user reported that the complete built-in CAL-to-RF
self-test passed. The cable was then removed and the user explicitly reported
the RF path clear. No calibration, configuration, save, reset or generator
command was issued. `output off` was the first command in every serial session.

## Embedded diagnostics

The exact running identity matched the artifact. Runtime readback reported:

- phase 6, schema 3 and protocol 2;
- 48 MHz HCLK, one flash wait state and a running DWT cycle counter;
- 12 MHz LCD/MAX2871 SPI and 6 MHz Si4468/PE4302 SPI;
- 7,696 CCM bytes reserved and a 1,024-point maximum FFT;
- feature mask `0x0007FFFF` and safety mask `0x000001FF`; and
- binary transport, passive stream, zero-span capture, AWG output and RF fast
  paths compiled but locked.

Every fixture returned a zero failure mask:

| Command | Result |
| --- | --- |
| `modern selftest` | `deterministic_selftest=0x00000000 PASS` |
| `modern dsp-selftest` | `fft=0x00000000 ui=0x00000000 PASS` |
| `modern passive selftest` | `passive_selftest=00000000 PASS execution=locked` |
| `modern transport selftest` | `transport_selftest=00000000 PASS binary_transport=off` |
| `modern awg selftest` | `awg_selftest=0x00000000 PASS output=off` |
| `modern audit` | manifest, services, FFT, UI and AWG all zero; `PASS` |

The audit's AWG fixture prepared only its deterministic RAM state. Subsequent
status was `prepared=1 active=0 qualified=0`; no DAC or RF output started.

## Physical FFT timing

Five consecutive 1,024-point Q15 FFT fixtures produced the expected bin 512
and Q15 magnitude 16,000:

| Run | DWT cycles | Result |
| ---: | ---: | --- |
| 1 | 1,837,034 | PASS |
| 2 | 1,836,844 | PASS |
| 3 | 1,837,013 | PASS |
| 4 | 1,837,025 | PASS |
| 5 | 1,836,714 | PASS |

The mean is 1,836,926 cycles, or 38.269 ms at 48 MHz. The 320-cycle range is
6.67 microseconds. Compared with the v0.3 physical mean of 1,923,337.8 cycles,
this linked v0.4 image is 86,411.8 cycles (1.800 ms, 4.49%) faster on the same
deterministic transform. This is a code-placement/build result, not a claim
that every analyzer sweep now runs 4.49% faster.

## Live passive ledger and clock

Four status samples separated by three-second host intervals reported completed
sweep counts `236`, `239`, `242` and `245`. Every interval therefore added
three complete 450-point traces. The last measured sweep durations were 735.5,
735.3, 735.1 and 735.4 ms. Corresponding start timestamps were strictly
increasing, the 10 kHz raw clock mapped exactly to boot-relative microseconds,
and flags `0x00000003` meant relative plus monotonic time with no observed wrap
or regression.

All samples retained:

```text
published=0 dropped=0 invalid=0
slot committed=0 consumed=0 dropped=0
capture_state=0 capture_summary=0
```

Those zeros are the expected locked-image behavior: the completion hook and
ledger are live, while no stream buffer is leased and nothing is published.

### Short host-clock comparison

The remaining hardware window allowed a short read-only clock comparison. An
initial 179.891-second run collected 91 samples at two-second intervals. It
kept device time and the completion ledger monotonic, advanced 180 completed
sweeps and retained zero published, dropped or invalid traces. One request
waited 231 ms at a sweep boundary, so its 4,316.6 ppm regression was retained
as a latency-contaminated observation rather than the clock estimate.

A warmed follow-up collected 36 samples across 45.502 seconds. All request
round trips were between 4.719 and 8.061 ms, with a 5.043 ms median. Fits using
host request, midpoint and response timestamps produced respectively 4,213.2,
4,216.9 and 4,220.5 ppm. The midpoint estimate therefore places this unit's
free-running 10 kHz device clock about **4,217 ppm (0.422%) fast** relative to
the Mac monotonic clock during this short run. Device time advanced 45.6961
seconds while host response time advanced 45.502124 seconds. The ledger moved
from 1,603 to 1,638 completed sweeps with zero publication, drops or invalid
traces.

This result proves the clock is stable enough to fit over a short interval and
also proves that raw timestamps must not be treated as UTC or nominal-rate time.
Per-unit offset/drift fitting is mandatory for multi-instrument timestamp
alignment. The result does not provide sample- or RF-phase coherence and does
not replace the planned 30-minute, temperature-aware and multi-unit test.

`modern passive plan` completed against real 0–900 MHz sweep data with status
zero and `execution=locked`. It produced bounded windows around observed local
maxima without modifying start, stop, RBW or sweep cadence. `modern metrics`
also executed, but its uncalibrated open-input values—including the strong
0 Hz endpoint artifact—are diagnostic snapshots, not RF accuracy evidence.

Read-only radio checks returned the expected Si4468 identity and properties.
The FRR/property probe completed in 10,463 DWT cycles. Frequency DDA, Si4468
hop, MAX2871 and RF-wave planners all returned valid dry-run plans while their
execution paths stayed off.

## Fail-closed execution evidence

Every attempted execution boundary refused with no state transition:

| Command | Required result |
| --- | --- |
| `modern passive start` | status 6, hardware qualification required |
| `modern passive capture` | status 6, zero-span qualification required |
| `modern transport start` | status 6, qualification and shell handoff required |
| `modern awg start` | status 6, hardware qualification required |
| `modern rfdiag enable` | refused, RF fast paths require qualification |

Post-refusal status still reported acquisition state zero, transport not
running, shell ownership retained, zero accepted/rejected/transmitted frames,
zero stream-slot activity and all qualification latches false.

## Display evidence

A read-only capture returned exactly 307,200 RGB565 big-endian panel bytes with
SHA-256
`cbdc84bef201007844b50a9ed6a9338aa363b4b12ef26a2fc12acbd82456639f`.
It decoded to the expected 480 by 320 analyzer screen, grid, labels, marker and
trace without byte-order or geometry corruption. The display used the persisted
black/yellow palette; the earlier charcoal/mint Atomic preview was deliberately
RAM-only and therefore was not expected after reboot.

## Decision and remaining boundary

Stage 1 is **PASS** for this exact artifact: boot, built-in self-test, normal
sweep accounting, diagnostic DSP, dry-run planning, hardware readback, display
capture and every safety lock behaved correctly on the physical ZS407.

This receipt does not unlock code. Live binary transport/trace streaming,
30-minute multi-unit clock characterization, triggered zero-span capture and
adaptive execution require separate qualification-only images and fixtures.
Each must be introduced and recoverability-tested one boundary at a time before
its private release can claim physical qualification.
