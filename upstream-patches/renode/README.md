# Renode upstream-ready fixes

These independent patches target
[`renode/renode-infrastructure`](https://github.com/renode/renode-infrastructure)
master commit `1c3c1c1f9f1a1c4c7b7302bca3a37b9aa361c7a2`, observed on
2026-07-11. Each patch carries PhysicistJohn authorship and an NUnit regression.
Neither patch nor a public issue/PR has been pushed.

## 0001: NVIC ICSR.RETTOBASE

Current master uses `.WithTaggedFlag("RETTOBASE", 11)`, so reads always return
zero. ARM defines the bit as one when no exception is active or the executing
exception is the only active exception. The patch reports
`activeIRQs.Count <= 1` and tests the base-level state.

Observed consequence: ChibiOS Cortex-M `_port_irq_epilogue` uses RETTOBASE to
decide whether it can reschedule after an IRQ. With the permanent zero, an ADC
DMA interrupt made the main thread READY but control returned to the idle
thread. Supplying the correct value allowed the unmodified firmware to finish
startup and reach all UI/RF threads.

## 0002: independent STM32 IDR and ODR

Current `STM32_GPIOPort` uses the inherited `State` array for both IDR and ODR.
Writing the output latch therefore changes the reported electrical input even
when a pin is configured as an input. The patch adds an output-latch array,
drives it only in output mode, and tests input/output independence plus a later
switch to output mode.

Observed consequence: the ZS407 initializes the PA1–PA3 ODR bits high but keeps
the active-high jog contacts in input mode with pull-downs. The shared state
made left, press and right look asserted at startup.

## Apply independently

From a clean checkout at the base commit, either patch can be reviewed and
applied alone:

```bash
git am /path/to/0001-FIX-NVIC-Implement-ICSR-RETTOBASE.patch
```

or:

```bash
git am /path/to/0002-FIX-STM32_GPIOPort-Separate-IDR-and-ODR-state.patch
```

Both patches were applied to a complete Renode checkout at the stated base and
tested on macOS Arm64 with .NET 8:

```text
PeripheralsTests: 91 passed, 5 skipped, 0 failed
```

The skips are existing platform-dependent tests. Before publication, rebase
each patch onto the then-current master and repeat that suite. The exact ZS407
binary test in this repository is the integration regression:

```bash
tools/test-digital-twin.sh --full
```

The older STM32 timer UIF discrepancy is intentionally not packaged: current
master already sets `updateInterruptFlag` on an update event independently of
`updateInterruptEnable`.
