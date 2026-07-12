# ZS407 v0.4 transport-only qualification

This is the next reversible laboratory image after the physically qualified
v0.4 Stage 1 checkpoint. It enables only an explicit, one-shot transition from
the legacy USB shell to Protocol v2. Passive trace publication, zero-span
capture, adaptive execution, AWG output and RF fast paths remain locked.

The image is **not hardware-qualified** until the physical procedure below is
completed. Its purpose is to qualify USB ownership and binary request/response
behavior without combining those risks with live streaming.

The status line deliberately distinguishes `admitted=1` from `qualified=0`.
The compile-time trial profile admits this single path so it can be tested; only
a recorded physical pass can change the release-level qualification claim.

## Why a handoff is required

The ChibiOS serial-USB input queue can have only one consumer. Starting a binary
worker while the legacy shell is blocked in its reader would race two threads
for the same USB buffers. The qualification profile therefore uses this exact
sequence:

```text
shell receives exact handoff command
    -> sweep thread records HANDOFF_REQUESTED
    -> sweep thread queues final ASCII result and prompt
    -> shell thread wakes, claims STARTING, and creates worker
    -> lifecycle becomes BINARY_ACTIVE; shell stream is nulled and exits
```

The request path never creates a worker. Worker creation occurs only from the
shell thread after the final prompt has been queued. The main thread consults
the lifecycle before every shell-thread creation, so it cannot respawn a shell
while binary ownership is active.

## One-shot lifecycle

| State | USB owner | Meaning |
| --- | --- | --- |
| `SHELL_READY` | shell | Qualification profile booted; no request made |
| `HANDOFF_REQUESTED` | shell | Exact command accepted; final prompt pending |
| `STARTING` | shell thread | Parser and static worker are being admitted |
| `BINARY_ACTIVE` | binary worker | Shell has exited; Protocol v2 owns input |
| `SHELL_RECOVERED` | shell after reconnect | USB link was physically disconnected |
| `FAILED` | shell | Admission failed before or during worker start |

Only `SHELL_READY` can accept a handoff. The accepted transition permanently
sets a RAM-only one-shot bit. Disconnecting and reconnecting USB restores the
shell, but another handoff in the same boot is refused. A physical restart
clears RAM and starts a new lifecycle. There is no persistent unlock, hidden
setter, automated start or firmware update path.

Binary output uses the ChibiOS output-buffer queue with a 250 ms bound per
frame segment. A host that stops reading can cause an explicit transport error,
but cannot block the worker forever. USB receive interrupts only fill buffers;
all parsing, CRC and response work remains in the worker thread.

## Qualification wire surface

The host may exercise only existing schema-3 Protocol-v2 operations:

- ping, including the maximum 1,024-byte payload;
- capabilities, which must report profile 3, the transport-qualification
  feature and qualification-only safety bits;
- boot-relative clock snapshot;
- locked acquisition status; and
- the expected error responses for unavailable capture and unsupported
  commands.

No binary command starts a sweep, stream, capture, generator or adaptive
executor. The image continues ordinary analyzer sweeps and records their clock
and ledger status, but `published`, `dropped` and stream-slot counters remain
zero because passive publication is locked.

## Offline evidence

The build must pass:

- the complete host/UBSan, embedded-math, Swift, JavaScript and generated
  TypeScript contract suites;
- 100,000 protocol mutations and one million lifecycle mutations;
- a 32-thread request race with exactly one accepted handoff;
- GNU and LLVM freestanding Cortex-M4 compilation;
- a source audit proving the physical driver has no process execution, file
  mutation, DFU, flash, persistence, calibration or generator command;
- ELF audits proving prompt-then-exit ordering, one USB reader, bounded output,
  disconnect recovery and all passive/output locks;
- two byte-identical clean F303 builds plus two F072 regression builds; and
- a source-derived Renode boot that executes real sweeps while observing
  `SHELL_READY`, no worker, one-shot unused and every passive latch closed.

The host driver has an offline self-test and three intentionally separate
physical modes:

```sh
tools/qualify-transport-v0.4.py self-test

tools/qualify-transport-v0.4.py preflight /dev/cu.usbmodemXXXX \
  --expected-version tinySA4_lab-v0.4-transport-qual-gCOMMIT

tools/qualify-transport-v0.4.py exercise /dev/cu.usbmodemXXXX \
  --expected-version tinySA4_lab-v0.4-transport-qual-gCOMMIT \
  --confirm QUAL-407

# Physically unplug and reconnect USB; do not enter DFU.
tools/qualify-transport-v0.4.py verify-recovery /dev/cu.usbmodemXXXX \
  --expected-version tinySA4_lab-v0.4-transport-qual-gCOMMIT
```

The exercise fragments a maximum ping, validates capabilities/clock/ledger,
checks fail-closed capture and unsupported responses, injects bad CRC, garbage
and an unsupported version, proves parser resynchronization, and coalesces two
requests. Recovery then requires retained rejection/discard counters, one
disconnect recovery, no I/O errors and refusal of a second same-boot handoff.

## Physical qualification order

1. Verify the exact candidate hash and both the Stage 1 and official rollback
   images.
2. Run the complete built-in CAL-to-RF self-test on the currently installed
   checkpoint.
3. Remove every RF cable, enter DFU physically and flash only the committed
   transport-qualification BIN.
4. Cold-start, run the complete built-in self-test again, remove the CAL cable
   and leave the unit in input mode.
5. Run `preflight`, then `exercise`. Do not use another serial application.
6. Physically unplug and reconnect USB without entering DFU; run
   `verify-recovery`.
7. Cold-start once more and repeat the built-in self-test and normal analyzer
   smoke check.
8. Any identity, self-test, handoff, binary, reconnect or lock failure ends the
   trial and restores the verified Stage 1 or official image.

The earlier short comparison measured this unit's device clock about 4,217 ppm
fast relative to the Mac. Once binary clock requests are physically admitted,
a later unattended 30-minute run will fit request/midpoint/response time and
temperature without shell-command scheduling. That is timestamp calibration,
not RF phase coherence.

## Exit boundary

Passing this image qualifies binary USB request/response ownership and recovery
only. The next branch may enable passive trace publication and deliberately
saturate the host to validate compact/raw decoding and exact drop accounting.
Capture and adaptive retuning remain later, separate images.
