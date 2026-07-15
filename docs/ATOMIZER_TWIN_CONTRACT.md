# Atomizer executable-twin bridge contract

Version: `1`. Owner: `TinySA_Firmware`.

Trio composition: [`contracts/trio-composition-v4.json`](../contracts/trio-composition-v4.json).

Within composition v4, this repository remains the executable-twin
compatibility owner. Its bridge launchers remain contract version 1 and
delegate to the adjacent `TinySA_Twin` implementation; moving contractual
ownership requires a coordinated new trio-contract version.

The bridge is a trusted child process using newline-delimited JSON over stdio. It boots the pinned `lab-v0.2.0-protocol` image in Renode, proves the executable boot signature, and returns only firmware-executed analyzer data, retained LCD bytes, modeled touch evidence, or generator state.

## Assumptions

- Atomizer exposes one declared `tinysa-firmware-twin` candidate independently of physical serial enumeration. Connecting that candidate descriptor-launches this exact sibling bridge and checks the ready declaration before exposing an operational session.
- Request frequencies are integer hertz; levels are finite dBm; every request names contract version `1`.
- The pinned ELF’s SRAM/CCM addresses are part of this release contract and remain protected by the existing ELF/BIN hashes.
- The internal transport retains `execution=firmware-digital-twin`. Atomizer’s generic session projection uses `sourceKind=tinysa-firmware-twin`, `execution=firmware-executed-twin`, and `transport=renode-monitor-bridge`; it omits USB-identity evidence entirely and preserves `usbTransactionsModeled=false`.

## Guarantees

- `acquire_sweep` rewrites the pinned firmware’s setting and frequency-cache state, lets its real sweep thread execute against modeled RF peripherals, and exports trace 0 only after `completed` is asserted.
- `capture_screen` exports the retained ST7796S framebuffer as exact 480×320 RGB565 little-endian bytes.
- Generator/touch operations modify executable firmware state and advance virtual time before success.
- Atomizer qualifies the returned generator output as `firmware-executed-twin`, never as physical emission or calibrated RF measurement. Output-affecting dispatch first makes host state unknown; configuration, acquisition, and disconnect must establish output off or fault visibly.
- Invalid input, hash/bootstrap failure, Renode failure, incomplete sweep, malformed evidence, or unsupported method fails explicitly. There is no synthetic replacement.

## Boundary

Renode does not model USB transactions. Therefore the bridge identifies itself as `renode-monitor-v1`, never `usb-cdc-acm`. Only Atomizer's `tinysa-zs407` driver may adapt this domain contract to the internal TinySA service and command scheduler. Its internal transport retains `execution=firmware-digital-twin`; the generic instrument provenance reports `execution=firmware-executed-twin`, omits `usbIdentityVerified`, preserves `usbTransactionsModeled=false`, and retains the bridge evidence label.

SignalLab is now an active high-level measurement producer directly to Atomizer through the separate `signal-lab` driver. That edge does not pass through this repository and does not mutate executable firmware. SignalLab also owns a separately versioned future stimulus intent. A stimulus sink must be added here and composed explicitly; the bridge does not scrape or silently import SignalLab state.

## Assume/guarantee composition

Firmware assumes Atomizer launches one trusted child, sends NDJSON requests with unique bounded IDs and `contractVersion=1`, serializes state-changing operations, and accepts success only after the exact ready declaration.

Firmware guarantees one ready/fatal declaration, one response per admitted request, pinned release/source/binary/boot evidence, executable-origin sweep/LCD/touch/generator results, and explicit error envelopes. These guarantees discharge Atomizer’s twin assumptions only when the byte-identical trio manifest also matches.

The active SignalLab→Atomizer measurement edge does not activate the reserved SignalLab→Firmware edge. This bridge has no stimulus sink in version 1. Absence is a contract state, not an error-recovery cue. A sink must declare intent version, acknowledgement, lifecycle, virtual-time semantics, evidence, and teardown before a new trio version may activate it.

## Atomizer selection and fallback boundary

The twin is one explicit source kind owned by Atomizer's `tinysa-zs407` driver; the physical ZS407 is another. With no owner-only Atomizer preference, the factory default is the independent `signal-lab` driver. Atomizer may connect the twin only after an explicit selection or a persisted `tinysa-zs407`/`tinysa-firmware-twin` preference. Physical absence, SignalLab failure, preferred-source failure, or ambiguity never authorizes automatic twin admission. The twin likewise never falls through to SignalLab, physical USB, or a protocol test double after a ready/hash/boot/request failure.

NeptuneSDR is a future Atomizer driver/contract evolution, not a current Firmware capability. This bridge exposes firmware-executed TinySA operations and does not claim complex I/Q or SDR controls.

## Safety, liveness, and failure algebra

- Safety: the bridge never claims USB, never emits synthetic replacement evidence, never accepts out-of-range/non-finite values, and never reports sweep success before executable firmware asserts completion.
- Liveness: boot and each request have bounded timeouts; each admitted request settles once; shutdown or protocol poison stops and reaps the complete isolated bridge/Renode process group.
- Invalid input or version rejects before state mutation.
- Ready/hash/boot mismatch terminates admission.
- Renode exit, monitor error, incomplete sweep, malformed frame, or generator/touch failure returns explicit failure and is not retried.
- LCD export must contain exactly 307,200 RGB565LE bytes.
- Generator configuration must return output off; the cross-repository release smoke returns output off after its enable test.

Run `npm run check:firmware-twin` from the sibling `TinySA` repository for the composed executable release smoke.
