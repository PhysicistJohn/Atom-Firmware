# USB PMA reconfiguration reproducer

This reproducer checks buffer ownership in the USB controller. Merely receiving
a descriptor or shell prompt is insufficient because overlapped PMA can remain
latent until a particular endpoint transfer.

## Device requirements

- ChibiOS USBv1 on an STM32 PMA USB peripheral.
- EP0 configured for IN and OUT.
- One configuration that initializes at least one nonzero endpoint.
- A way to inspect the endpoint buffer-descriptor addresses after control
  requests. A debugger, a test-only command, or a peripheral model is enough.

The tinySA CDC fixture uses EP1 IN/OUT and EP2 IN with 64-byte maximum packets.

## Control-transfer sequence

The hexadecimal strings below are the eight-byte USB SETUP packets in wire
field order.

1. Bus reset.
2. Get the device descriptor: `8006000100001200`.
3. Set address 1: `0005010000000000`.
4. Get the configuration descriptor: `8006000200004300`.
5. Select configuration 1: `0009010000000000`.
6. Record all active TX/RX PMA buffer addresses and assert uniqueness.
7. Select configuration 1 again: `0009010000000000`.
8. Record addresses and assert uniqueness again.
9. Unconfigure: `0009000000000000`.
10. Assert endpoints 1..N are disabled; record EP0 addresses and assert
    uniqueness.
11. Select configuration 1: `0009010000000000`.
12. Record addresses and assert uniqueness.
13. Complete the device's class setup and transfer data through its nonzero
    endpoints.
14. Exercise suspend/wakeup and an unsupported EP0 request/STALL.
15. Bus reset; assert endpoints 1..N are disabled.
16. Address/configure again, record addresses, and assert uniqueness.

For CDC ACM, the class setup packets used by the exact reproducer are:

```text
SET_LINE_CODING setup: 2120000000000700
SET_LINE_CODING data:  00c20100000008
SET_CONTROL_LINE_STATE: 2122030000000000
```

## Address assertion

For every active endpoint descriptor, collect each present TX and RX buffer
address. Fail if any two active directions have the same PMA address. The
assertion must include EP0; checking only data endpoints cannot detect this
defect.

With the tinySA endpoint sizes, expected addresses are:

```text
EP0.TX=0x0040 EP0.RX=0x0080
EP1.TX=0x00c0 EP1.RX=0x0100 EP2.TX=0x0140
```

The unpatched 21.11.5 USBv1 driver instead reports after step 7:

```text
EP0.TX=0x0040 EP0.RX=0x0080
EP1.TX=0x0040 EP1.RX=0x0080 EP2.TX=0x00c0
```

## Repository exact-image check

The executable-twin scenario is
`../TinySA_Twin/digital-twin/renode/tests/usb.resc`; its firmware release gate is
`tools/qualify-chibios-general.sh`. A passing complete run has exactly:

```text
ZS407_TWIN_USB_PMA=PASS                         5 occurrences
ZS407_TWIN_USB_ENDPOINTS=PASS data=disabled    3 occurrences
```

It also requires descriptor, address/configuration, CDC, STALL,
suspend/wakeup, two bus resets, and final re-enumeration markers. The exact RC4
ELF fails the second PMA assertion; the exact RC5 ELF passes.
