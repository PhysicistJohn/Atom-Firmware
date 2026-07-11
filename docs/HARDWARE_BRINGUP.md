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

## Commands excluded from initial automation

Until backup and recovery are demonstrated, do not automate configuration
clears, calibration writes, correction-table writes, reset-to-DFU, firmware
download, SD deletion, or generator enable. A convenient command is not the
same thing as a safe command.
