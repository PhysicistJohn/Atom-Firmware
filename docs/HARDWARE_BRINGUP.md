# Physical ZS407 bring-up and flash gate

The source build is solved. The next milestone is to characterize the exact
unit before changing any byte that runs on it.

## 1. Preserve the shipped state

Record, without changing settings:

- front and rear labels, especially `ZS407` and any board/hardware revision;
- packaging/vendor details and authenticity indications;
- firmware version screen and the USB `version` response;
- `info`, `status`, and `help` output;
- USB VID/PID, serial number behavior, and macOS device path;
- battery state and installed microSD details;
- current configuration, correction tables, and any device-specific calibration
  data that the firmware exposes safely;
- screenshots and photos of all self-test results.

The exact runtime hardware line is especially important. Current source expects
the public ZS407 path to identify as `V0.5.4 + ZS407` with hardware ID 103.
Do not force that identity if the unit reports something else; investigate it.

## 2. Run the untouched baseline

The official update guide explicitly recommends running self-test before a
firmware update so pre-existing RF damage is not mistaken for an update
regression:
<https://tinysa.org/wiki/pmwiki.php?n=Main.UpdatingTheFirmware>.

At minimum, preserve:

- complete self-test result set;
- low-input response to the internal calibration source;
- LNA on/off delta;
- attenuation steps at 0, 2, 4, 8, 16, and 31 dB where safe;
- representative noise floor and marker readings;
- one repeatable sweep in normal mode;
- one repeatable sweep near the normal/Ultra transition;
- one conservative Ultra-mode sweep using a known or shielded setup;
- generator output checks only into suitable 50-ohm test equipment/attenuation.

Respect the official RF limits. The wiki lists a maximum of +/-5 V DC and a
maximum input of +6 dBm at 0 dB internal attenuation for Ultra-class hardware;
software cannot protect a damaged front end.

## 3. Prove DFU discovery without writing

For Ultra hardware, the official recovery entry is:

1. power off;
2. hold the jog control down;
3. power on while holding it;
4. expect a black display;
5. connect USB and enumerate the STM32 DFU device.

On macOS/Linux, discovery can be checked without a download:

```bash
dfu-util -l
```

Do not run `dfu-util -D`, STM32CubeProgrammer download, or `make flash` during
this discovery step. Record the DFU descriptor and confirm that normal reboot
returns to the shipped firmware.

## 4. First write qualification

The safest first write is the exact reproduced official baseline—not a feature
change. The candidate must have this SHA-256:

```text
3c9847ff4d7b80561df2f2f1030a112703a083409ffb2ee11361b2413b7c1e41
```

Before that write:

- verify the candidate hash immediately before programming;
- have the official `.bin` and `.dfu` cached and verified;
- have a charged battery and stable USB connection;
- know the jog-button recovery procedure;
- save the pre-flash self-test and configuration evidence;
- disconnect RF sources and loads unless the procedure requires them.

Afterward, repeat the entire untouched baseline and compare results. Only when
the rebuilt official image behaves identically do locally modified images enter
the test queue.

## 5. Modified-firmware gate

Every modified image must carry:

- source commit and clean/dirty status;
- compiler/toolchain identity;
- binary SHA-256 and size;
- flash/RAM/stack deltas from baseline;
- exact feature or fix under test;
- rollback image and recovery steps;
- serial smoke-test result;
- self-test result;
- RF regression measurements appropriate to the changed subsystem.

Changes to frequency planning, correction data, synthesizer setup, timing,
attenuator/LNA control, persistence layout, or interrupt/RTOS code require a
larger matrix than display-only changes.

## 6. Executed package-3 qualification (2026-07-11)

The physical unit enumerated as `0483:5740`, identified as
`tinySA ULTRA+ ZS407`, and reported `HW Version:V0.5.4 max2871`. Battery voltage
was 4.25–4.27 V throughout the procedure.

Before any locally modified image was written:

- the installed `tinySA4_v1.4-217-gc5dd31f` firmware passed the complete
  built-in CAL-to-RF self-test;
- Atomizer wrote the exact official `tinySA4_v1.4-224-gc979386` baseline,
  SHA-256
  `3c9847ff4d7b80561df2f2f1030a112703a083409ffb2ee11361b2413b7c1e41`;
- the official image re-enumerated and its source revision, model, hardware
  revision, toolchain and battery telemetry were read back successfully; and
- a physical power-off/power-on was required before its post-update self-test
  behaved normally. DFU's manifest/leave reboot and successful USB
  re-enumeration did not replace this cold-start gate.

The first modified image was hardware-table package 3, source commit
`2a3a2df14283a840f8e650c655296332eea8186a`. Its 185696-byte binary had SHA-256
`611c33bb11b0f453a8c915c34c7f842edf078b01a92443e7d97a7e31ec421ae3`.
Preflight found one physical STM32 DFU device and one internal-flash alternate.
`dfu-util 0.11` completed the erase, download and manifest/leave operation.

Warm-boot readback reported firmware `hardware_table_audit`, model
`tinySA ULTRA+ ZS407`, and the intended `V0.5.4 max2871` table match. After a
second physical cold start, the complete built-in self-test passed with a short
50-ohm cable between CAL and RF. The user performed and directly attested the
manual cable, cold-start and self-test steps; automation issued only read-only
`version`, `info`, and `vbat` commands.

Package 3 therefore passed source/build provenance, rollback preparation, DFU
admission, physical programming, runtime hardware identification and full
self-test qualification. This evidence supports upstream review of the small
table-length fix; it does not generalize to later RF, persistence or timing
patches.

## Commands excluded from initial automation

Until backup and recovery are demonstrated, do not automate configuration
clears, calibration writes, correction-table writes, reset-to-DFU, firmware
download, SD deletion, or generator enable. A convenient command is not the
same thing as a safe command.
