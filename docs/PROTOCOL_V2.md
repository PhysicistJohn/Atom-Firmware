# Protocol v2 and marshalling

Protocol v2 is the first post-phase release profile. It is selected explicitly:

```sh
make TARGET=F303 PHASE=6 RELEASE_PROFILE=protocol-v2
```

It does not alter any immutable Phase 0–6 commit or tag. The profile is a
no-flash laboratory image until the ZS407 hardware checks in this document are
complete.

## Wire frame

The frame remains deliberately small and byte-stream friendly. Version 2
decoders also accept version 1 frames.

| Offset | Bytes | Field |
|---:|---:|---|
| 0 | 2 | magic `0x5a53`, little-endian |
| 2 | 1 | protocol version, currently 2 |
| 3 | 1 | flags |
| 4 | 2 | request identifier |
| 6 | 2 | command |
| 8 | 2 | payload length, at most 1,024 |
| 10 | N | payload |
| 10+N | 4 | IEEE CRC-32 over header and payload |

All integer payload fields are explicitly little-endian. Code must not cast a
wire pointer to a C struct: Cortex-M4 unaligned accesses are slower, some
instructions always fault on misalignment, and the host languages do not share
C padding rules.

## Generated typed payloads

[`zs407_contract.json`](../modern/contracts/zs407_contract.json) is the source
of truth. [`generate-contracts.py`](../tools/generate-contracts.py) emits C,
Swift, TypeScript, runnable JavaScript and byte-for-byte golden fixtures.

| Payload | Fixed bytes | Variable tail |
|---|---:|---|
| capabilities | 24 | none |
| trace chunk | 56 | signed dB×32 samples, then validity bitmap |
| clock snapshot | 24 | none |
| acquisition status | 40 | none |
| adaptive window | 36 | none |
| capture summary | 60 | none |
| waveform upload | 16 | negotiated raw or compact events |
| status | 4 | none |

The generated C functions use field loads/stores rather than packed structs.
Swift uses fixed-width integers. TypeScript/JavaScript use `bigint` for 64-bit
frequency and timestamp fields, avoiding loss above JavaScript's exact integer
range.

Golden-vector tests prove that all three runnable implementations emit the
same bytes. The TypeScript source is also generated deterministically; its
runnable JavaScript twin is tested when `node` is installed, and `tsc` is used
when available.

## Trace chunking

One 4,096-point trace cannot fit in a 1,024-byte payload. A full chunk uses:

```text
56-byte metadata + 450 × 2-byte samples + ceil(450 / 8) validity bytes
= 1,013 bytes
```

Ten chunks carry the maximum trace: nine groups of 450 points and one group of
46. Each chunk includes trace ID, sequence, absolute start index, total points,
rational frequency step, RBW, ENBW, timestamp, RF path, detector and scale.
The validity bitmap is authoritative; unused high bits in its last byte must be
zero. Invalid samples retain the `-32768` sentinel for compatibility.

The protocol-v2 profile keeps raw `int16` streaming for fixed decode cost. The
additive passive-v0.4 profile first tries ZigZag delta values plus ULEB128
directly in the final frame. Trace flag bit 2 selects compact form and sets
`validity_bytes` to zero; the invalid sentinel remains lossless. Compact form
is committed only when smaller than the complete raw tail. A representative
smooth 450-point trace is about half the raw size; noisy or alternating data
can expand, so raw fallback is mandatory and tested.

Waveform programs use a separate compact representation: delta microseconds,
one opcode byte and a ZigZag/ULEB128 value. Decoding reconstructs the fixed
16-byte event ABI and runs the complete output-safe waveform validator before
the program can be accepted. Execution remains locked.

## Allocation-free frame paths

The core provides four paths:

- ordinary encode/decode for contiguous callers;
- reserve/fill/finalize so a payload is generated directly inside its frame;
- resize/finalize so a maximum reservation can be compacted in place;
- segment encode to avoid assembling a temporary payload;
- a scatter/gather sink that emits header, segments and trailer without a
  full-frame transmit buffer.

Decoded payload pointers borrow the input/parser buffer and expire when that
buffer is reused. No codec allocates memory.

The streaming parser accepts arbitrary USB-sized fragments, multiple frames in
one fragment and leading noise. It searches for magic, validates the header as
soon as ten bytes exist, updates CRC while payload bytes arrive, and retains an
overlapping plausible magic prefix when a false header is rejected.

## CRC backends

The portable backend replaces eight polynomial steps per byte with two
four-bit table steps. The table costs 64 bytes rather than the 1 KiB required
by a byte lookup table and supports incremental updates.

The STM32F303 backend is compiled but not selected automatically. RM0316 says
the F303 CRC block supports a programmable polynomial, initial value,
byte/half-word/word access, input reversal and output reversal. The backend
uses polynomial `0x04c11db7`, initial value `0xffffffff`, byte input reversal,
output reversal and final XOR `0xffffffff`; its hardware self-test must return
`0xcbf43926` for `123456789`. It claims the global peripheral under a very
short kernel critical section, computes with interrupts enabled, and releases
ownership afterward. Hardware comparison and concurrency tests are still
required before making it the default.

Primary references:

- [STM32F303 reference manual RM0316](https://www.st.com/resource/en/reference_manual/DM00043574.pdf)
- [ST AN4187: Using the CRC peripheral](https://www.st.com/resource/en/application_note/an4187-using-the-crc-peripheral-in-the-stm32-family-stmicroelectronics.pdf)

## USB execution boundary

The existing ChibiOS CDC driver already implements the right interrupt split:

```text
USB packet memory
    → USB ISR callback
    → ChibiOS 2 × 256-byte input buffer queue
    → dedicated protocol worker
    → incremental parser / typed command handler
    → ChibiOS output queue
    → USB ISR starts the next IN transaction
```

The ISR only posts/releases buffers and starts endpoint transactions. It does
not scan magic, calculate protocol CRCs, allocate memory or execute commands.
The worker acquires complete ChibiOS queue buffers and parses each buffer in
one batch, avoiding the legacy shell's one-byte `streamRead` loop.

The compiled adapter supports ping and capabilities; other commands return a
typed unsupported status. Two private, zero-initialized bytes must both become
true before its thread can be created:

1. transport hardware qualification;
2. explicit release of the single CDC stream by the shell.

There are no setters or unlock commands in this image. `modern transport
start` therefore returns `NOT_QUALIFIED`. The binary audit verifies that both
checks dominate `chThdCreateStatic`, that no unlock symbol exists, and that the
USB receive ISR has no protocol/CRC call.

## SPSC interrupt handoff

The portable single-producer/single-consumer byte ring is for future UART,
timer or custom ISR boundaries. It uses monotonically increasing aligned
32-bit indices and compiler atomic acquire/release operations, which GNU and
LLVM lower for Cortex-M4 without a desktop mutex. Producer and consumer never
write the same index. A threaded host stress test transfers and verifies 2 MiB
through an eight-bit wrapping data path.

The current USB adapter does not add this ring because ChibiOS already provides
the equivalent double-buffered ownership transfer. Adding another queue would
increase latency and consume scarce SRAM.

## Evidence and activation gates

[`test-host-core.sh`](../tools/test-host-core.sh) runs:

- native UBSan suites and 10,000 legacy frame round trips;
- typed v2 payload, stream parser, trace, compact codec and ring tests;
- 100,000 deterministic mutation-fuzz cases;
- a real two-thread SPSC stress test;
- C/Swift/JavaScript golden vectors;
- GNU and LLVM Cortex-M4 freestanding compilation;
- an informational old/new benchmark.

Before transport activation on a physical ZS407:

1. capture v1 shell behavior and USB enumeration before/after;
2. run hardware CRC golden vectors at lengths 0, 1, 2, 3, 4, 5, 63, 64,
   255, 256, 1,023 and 1,024;
3. test disconnect/reset during partial receive and blocked transmit;
4. sustain bidirectional randomized frames while sweeping and redrawing;
5. measure worker stack high-water and minimum heap;
6. implement an explicit shell-to-binary ownership handshake and recovery
   timeout;
7. rerun output-lock and RF spectral checks before enabling any mutating
   command.
