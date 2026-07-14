# USBv2 requirement for current ChibiOS integration

This is a source-audit requirement for preparing a current integration-branch
patch, not a claim that USBv2 has runtime qualification from tinySA.

In ChibiOS 21.11.5, USBv2 has the same ownership pattern as the proven USBv1
defect. The 2026-07-14 read-only audit confirmed that both driver patterns
remain on current/default `master` at `f825669c`:

- `usb_lld_disable_endpoints()` documents that it preserves endpoint zero;
- it calls `usb_pm_reset(usbp)`, returning `pmnext` to 64;
- it clears only endpoint registers 1..N; and
- `usb_lld_init_endpoint()` allocates later TX/RX buffers from `pmnext`.

USBv2's allocator uses four-byte rounding rather than USBv1's two-byte
rounding, but that does not change the ownership error.

## Required upstream shape

After rebasing and confirming the current structures, a `master`-targeted USB
change must use the same semantic fix in USBv2 as in USBv1:

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

1. Fetch the maintainer-requested integration branch (current/default
   `master`) and confirm the audited PMA allocator and endpoint-disable
   contracts have not changed since `f825669c`.
2. Check isochronous/double-buffer descriptor semantics and every supported
   EP0 direction configuration.
3. Decide whether a common internal helper is appropriate or whether USBv1
   and USBv2 should retain parallel local helpers.
4. Add a USBv2-capable target or model test that executes `1 -> 1`,
   `1 -> 0 -> 1`, class traffic, and final bus reset.
5. Run current ChibiOS style, ARM build, and USB test matrices.

The tinySA RC5 binary consumes USBv1 only. Its passing executable-twin result
does not qualify USBv2 runtime behavior.

GitHub issue creation is restricted for the authoritative repository, and its
checked-in PR template still refers to stale `main`. Obtain maintainer guidance
on the intake path and target branch, or use the official ChibiOS SourceForge
project support path at <https://sourceforge.net/p/chibios/>. Nothing in this
handoff has been published.
