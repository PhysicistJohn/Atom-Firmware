# Atomizer executable-twin bridge contract

Version: `1`. Owner: `TinySA_Firmware`.

Trio composition: [`contracts/trio-composition-v1.json`](../contracts/trio-composition-v1.json).

The bridge is a trusted child process using newline-delimited JSON over stdio. It boots the pinned `lab-v0.2.0-protocol` image in Renode, proves the executable boot signature, and returns only firmware-executed analyzer data, retained LCD bytes, modeled touch evidence, or generator state.

## Assumptions

- Atomizer starts this exact sibling checkout and checks the ready declaration before exposing a candidate.
- Request frequencies are integer hertz; levels are finite dBm; every request names contract version `1`.
- The pinned ELF’s SRAM/CCM addresses are part of this release contract and remain protected by the existing ELF/BIN hashes.
- Atomizer preserves `execution=firmware-digital-twin`, `transport=renode-monitor-bridge`, `usbIdentityVerified=false`, and `usbTransactionsModeled=false` through every projection.

## Guarantees

- `acquire_sweep` rewrites the pinned firmware’s setting and frequency-cache state, lets its real sweep thread execute against modeled RF peripherals, and exports trace 0 only after `completed` is asserted.
- `capture_screen` exports the retained ST7796S framebuffer as exact 480×320 RGB565 little-endian bytes.
- Generator/touch operations modify executable firmware state and advance virtual time before success.
- Invalid input, hash/bootstrap failure, Renode failure, incomplete sweep, malformed evidence, or unsupported method fails explicitly. There is no synthetic replacement.

## Boundary

Renode does not model USB transactions. Therefore the bridge identifies itself as `renode-monitor-v1`, never `usb-cdc-acm`. Atomizer may adapt this domain contract to its internal command scheduler, but must preserve `execution=firmware-digital-twin`, `usbIdentityVerified=false`, and the bridge evidence label.

SignalLab is a separate producer of versioned stimulus intent. A future stimulus sink must be added here and composed explicitly; the bridge does not scrape or silently import SignalLab state.

## Assume/guarantee composition

Firmware assumes Atomizer launches one trusted child, sends NDJSON requests with unique bounded IDs and `contractVersion=1`, serializes state-changing operations, and accepts success only after the exact ready declaration.

Firmware guarantees one ready/fatal declaration, one response per admitted request, pinned release/source/binary/boot evidence, executable-origin sweep/LCD/touch/generator results, and explicit error envelopes. These guarantees discharge Atomizer’s twin assumptions only when the byte-identical trio manifest also matches.

The reserved SignalLab→Firmware edge has no sink in version 1. Absence is a contract state, not an error-recovery cue. A sink must declare intent version, acknowledgement, lifecycle, virtual-time semantics, evidence, and teardown before a new trio version may activate it.

## Safety, liveness, and failure algebra

- Safety: the bridge never claims USB, never emits synthetic replacement evidence, never accepts out-of-range/non-finite values, and never reports sweep success before executable firmware asserts completion.
- Liveness: boot and each request have bounded timeouts; each admitted request settles once; shutdown terminates the child and Renode.
- Invalid input or version rejects before state mutation.
- Ready/hash/boot mismatch terminates admission.
- Renode exit, monitor error, incomplete sweep, malformed frame, or generator/touch failure returns explicit failure and is not retried.
- LCD export must contain exactly 307,200 RGB565LE bytes.
- Generator configuration must return output off; the cross-repository release smoke returns output off after its enable test.

Run `npm run check:firmware-twin` from the sibling `TinySA` repository for the composed executable release smoke.
