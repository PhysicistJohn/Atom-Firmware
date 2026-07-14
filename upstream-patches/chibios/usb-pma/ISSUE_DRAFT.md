# Issue draft: STM32 USB PMA allocator can reuse active EP0 buffers

## Summary

The STM32 USBv1 low-level driver resets its packet-memory allocation cursor
when disabling configuration endpoints, even though endpoint zero remains
active. A subsequent configuration can therefore allocate nonzero endpoint
buffers over EP0's live TX/RX buffers.

This is proven on ChibiOS `ver21.11.5` at
`f4bbadf964fc746aef8bbcf34135c7d8fabb8eae`. The USBv2 driver in the same
release contains the analogous allocator-reset pattern and should be checked
on current `main` as part of the fix.

## Reproduction

Use a USB device with EP0 IN/OUT plus at least one nonzero endpoint. After bus
reset, address, and the first configuration, send either:

```text
SET_CONFIGURATION(1)
SET_CONFIGURATION(1)
```

or:

```text
SET_CONFIGURATION(1)
SET_CONFIGURATION(0)
SET_CONFIGURATION(1)
```

On the F303 CDC device used to isolate the problem, the healthy initial PMA
layout is:

```text
EP0 TX 0x0040   EP0 RX 0x0080
EP1 TX 0x00c0   EP1 RX 0x0100
EP2 TX 0x0140
```

After the endpoint-disable/rebuild path in the unpatched driver:

```text
EP0 TX 0x0040   EP0 RX 0x0080
EP1 TX 0x0040   EP1 RX 0x0080
EP2 TX 0x00c0
```

The first duplicate is enough to corrupt EP0/nonzero-endpoint traffic. A full
reproducer and exact SETUP bytes are in `REPRODUCER.md`.

## Cause

`usbDisableEndpointsI()` clears logical endpoints 1..N and calls
`usb_lld_disable_endpoints()`. The low-level driver's contract says it disables
all active endpoints *except endpoint zero*. USBv1 nevertheless calls
`usb_pm_reset()`, which sets `usbp->pmnext` to the PMA descriptor-table
boundary. The configured callback then initializes endpoints 1..N from that
cursor while EP0 still owns the first buffers.

The USB core's same-value rebuild is intentional. Commit `8097785b8` changed
`SET_CONFIGURATION` handling for bugs 938 and 939 so endpoint state and data
toggles are reset even when the selected configuration does not change.
Defining `USB_SET_CONFIGURATION_OLD_BEHAVIOR` only hides the `1 -> 1` case; it
does not correct `1 -> 0 -> 1` and gives up the intended endpoint-reset
behavior.

## Proposed correction

When disabling endpoints 1..N:

1. reset the PMA allocation cursor;
2. reserve EP0 IN and OUT maximum sizes from `usbp->epc[0]`; and
3. allocate rebuilt nonzero endpoints after those reservations.

Keep the bus-reset path unchanged so a real USB reset still starts from an
empty allocator before EP0 is initialized.

The prepared USBv1 patch changes only
`os/hal/ports/STM32/LLD/USBv1/hal_usb_lld.c`. Please apply the corresponding
ownership rule to USBv2 if current `main` still has the same pattern.

## Evidence boundary

The exact unpatched RC4 ELF fails deterministically on the second
configuration with EP0 TX and EP1 TX both at `0x0040`. The patched RC5 ELF
passes same-value `1 -> 1`, explicit `1 -> 0 -> 1`, CDC setup/traffic,
suspend/wakeup, EP0 STALL, and final bus-reset re-enumeration. The gate asserts
five distinct-PMA states and three data-endpoint-disabled states.

The RC4 physical device also failed CDC configuration: macOS saw its
`0483:5740` device descriptor but created no interface or serial device, both
before and after unplug/replug. That observation is consistent with the proven
overlap, but no host packet trace was captured that identifies the exact
repeated request, so the physical causal chain should not be overstated.

No physical RC5 pass is claimed in this issue draft.
