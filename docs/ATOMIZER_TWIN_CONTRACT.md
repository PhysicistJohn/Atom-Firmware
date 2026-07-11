# Atomizer executable-twin bridge contract

Version: `1`. Owner: `TinySA_Firmware`.

The bridge is a trusted child process using newline-delimited JSON over stdio. It boots the pinned `lab-v0.2.0-protocol` image in Renode, proves the executable boot signature, and returns only firmware-executed analyzer data, retained LCD bytes, modeled touch evidence, or generator state.

## Assumptions

- Atomizer starts this exact sibling checkout and checks the ready declaration before exposing a candidate.
- Request frequencies are integer hertz; levels are finite dBm; every request names contract version `1`.
- The pinned ELF’s SRAM/CCM addresses are part of this release contract and remain protected by the existing ELF/BIN hashes.

## Guarantees

- `acquire_sweep` rewrites the pinned firmware’s setting and frequency-cache state, lets its real sweep thread execute against modeled RF peripherals, and exports trace 0 only after `completed` is asserted.
- `capture_screen` exports the retained ST7796S framebuffer as exact 480×320 RGB565 little-endian bytes.
- Generator/touch operations modify executable firmware state and advance virtual time before success.
- Invalid input, hash/bootstrap failure, Renode failure, incomplete sweep, malformed evidence, or unsupported method fails explicitly. There is no synthetic replacement.

## Boundary

Renode does not model USB transactions. Therefore the bridge identifies itself as `renode-monitor-v1`, never `usb-cdc-acm`. Atomizer may adapt this domain contract to its internal command scheduler, but must preserve `execution=firmware-digital-twin`, `usbIdentityVerified=false`, and the bridge evidence label.

SignalLab is a separate producer of versioned stimulus intent. A future stimulus sink must be added here and composed explicitly; the bridge does not scrape or silently import SignalLab state.
