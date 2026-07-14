# USBv2 recommendation for current ChibiOS `main`

This is a source-audit recommendation, not a patch claimed to apply to or pass
current `main`.

In ChibiOS 21.11.5, USBv2 has the same ownership pattern as the proven USBv1
defect:

- `usb_lld_disable_endpoints()` documents that it preserves endpoint zero;
- it calls `usb_pm_reset(usbp)`, returning `pmnext` to 64;
- it clears only endpoint registers 1..N; and
- `usb_lld_init_endpoint()` allocates later TX/RX buffers from `pmnext`.

USBv2's allocator uses four-byte rounding rather than USBv1's two-byte
rounding, but that does not change the ownership error.

## Proposed shape

After rebasing and confirming the current structures, use the same semantic
fix as USBv1:

```c
static void usb_pm_reset_after_ep0(USBDriver *usbp) {
  const USBEndpointConfig *epcp = usbp->epc[0];

  usb_pm_reset(usbp);
  if (epcp->in_state != NULL) {
    (void)usb_pm_alloc(usbp, epcp->in_maxsize);
  }
  if (epcp->out_state != NULL) {
    (void)usb_pm_alloc(usbp, epcp->out_maxsize);
  }
}
```

Call that helper only from the endpoint-disable path that keeps EP0 active.
Keep the true bus-reset path on `usb_pm_reset()` so it does not reserve stale
state before EP0 initialization.

## Required review before turning this into a patch

1. Fetch current authoritative `main` and confirm USBv2 still uses this PMA
   allocator and endpoint-disable contract.
2. Check isochronous/double-buffer descriptor semantics and every supported
   EP0 direction configuration.
3. Decide whether a common internal helper is appropriate or whether USBv1
   and USBv2 should retain parallel local helpers.
4. Add a USBv2-capable target or model test that executes `1 -> 1`,
   `1 -> 0 -> 1`, class traffic, and final bus reset.
5. Run current ChibiOS style, ARM build, and USB test matrices.

The tinySA RC5 binary consumes USBv1 only. Its passing executable-twin result
does not qualify USBv2 runtime behavior.
