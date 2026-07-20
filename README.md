<p align="center"><img src="docs/brand/logo.jpg" alt="AtomOS Firmware" width="520"></p>

AtomOS Firmware
==========================================================

AtomOS Firmware is PhysicistJohn's research fork of the official
[erikkaashoek/tinySA](https://github.com/erikkaashoek/tinySA) firmware for the
**tinySA Ultra+ ZS407**. The first goal is to preserve, understand, and
reproduce the official firmware. The second is to improve it without
sacrificing RF behavior, calibration, recovery, or protocol compatibility.

On top of the upstream source, this fork adds:

- byte-for-byte reproduction of the official ZS407 release binary on macOS,
  matching the original Windows ChibiStudio build environment;
- an LLVM/Clang cross-build experiment for the Cortex-M4 target;
- a Renode digital-twin workflow that executes real firmware without hardware,
  through the sibling
  [Atom-TinySA-Twin](https://github.com/PhysicistJohn/Atom-TinySA-Twin) repo;
- a portable, host-testable instrument core with generated C, Swift,
  TypeScript, and JavaScript contract projections (see
  [modern/README.md](modern/README.md));
- bug fixes and a ChibiOS 21.11.5 port queued for upstream (see
  [docs/UPSTREAM.md](docs/UPSTREAM.md) and `upstream-patches/`).

This is not an official tinySA repository, release channel, or support source.
The official project remains <https://github.com/erikkaashoek/tinySA>.

Baseline status
---------------

The official `tinySA4_v1.4-224-gc979386.bin` has been reproduced
**byte-for-byte** from source commit
`c97938697b6c7485e7cab50bca9af76996b7d671` and ChibiOS submodule commit
`ade76dea89cd093650552328e881252a06486094`.

```text
size:    185704 bytes
SHA-256: 3c9847ff4d7b80561df2f2f1030a112703a083409ffb2ee11361b2413b7c1e41
```

The proof is intentionally tied to the historical ChibiOS commit above. Run it
from a disposable checkout whose `ChibiOS` worktree is at that commit; the
script fails closed when the active development submodule uses a newer port:

```bash
git submodule update --init --recursive
git -C ChibiOS checkout ade76dea89cd093650552328e881252a06486094
tools/reproduce-official-release.sh
```

Do not move the ChibiOS checkout in an active development worktree merely to
run the historical proof. See [the baseline record](docs/BASELINE.md) for the
exact source, submodule, library and timestamp inputs.

The first run downloads pinned Arm GNU 11.3.Rel1 toolchain artifacts. Exact
reproduction uses the Windows package's target libraries because the official
ELF shows that the release was built in a Windows ChibiStudio environment.
All downloaded firmware and toolchains live under ignored `.artifacts/`.

For an ordinary development build:

```bash
tools/build-zs407.sh
```

Development checks
------------------

The supported local gate requires Python 3, Node 22.23.1 with npm 10.9.8, and
the recorded ChibiOS submodule. On macOS, Xcode also supplies the independent
Clang and Swift projection checks. Install the single lockfile-pinned host
dependency and run every deterministic check with:

```bash
git submodule update --init --recursive
npm ci
tools/check.sh
```

The first run downloads Arm GNU 11.3.Rel1 and verifies its pinned SHA-256. The
gate runs ownership/evidence regressions, C11 UBSan and ASan suites,
deterministic protocol mutation fuzzing, threaded SPSC stress, generated Swift,
JavaScript and TypeScript contract checks, two independent Cortex-M4 frontend
compiles, and clean F072, F303 Phase 6, and F303 Protocol v2 firmware
compile/link/lock audits. It never opens a device or installs firmware.

Use `--boundary`, `--host`, or `--firmware` to select a subset. CircleCI pins
the Python image, macOS/Xcode image, Node/npm, TypeScript, ChibiOS gitlink and
Arm compiler, and additionally proves that two clean custom-package builds are
byte-identical and acceptable to the standalone Flasher manifest writer.

Generated check scratch can be removed explicitly with
`tools/prune-check-artifacts.sh --confirm`. That command only removes `build/`
and `.artifacts/host-tests/`. Never delete `.artifacts/` wholesale: it also
contains firmware packages, releases, downloaded toolchains, and irreplaceable
hardware and qualification evidence.

Package a committed custom ZS407 build for the standalone
[Atom-Flasher](https://github.com/PhysicistJohn/Atom-Flasher):

```bash
version="tinySA4_lab-v0.3.0-g$(git rev-parse --short=7 HEAD)"
tools/package-flasher-build.sh "$version"
```

The packaging gate never flashes. It builds one fixed F303 Phase 6 profile
twice from a clean, sanitized environment and the committed tracked tree,
requires identical BIN hashes, checks the embedded
version and ZS407 identity, validates the STM32 vector table and 240 KiB write
limit, then emits a content-addressed BIN plus
`tinysa-flasher-build-v1.json` under `.artifacts/flasher-builds/`. In Flasher,
select that JSON manifest, not the BIN directly. The manifest records exact
source, ChibiOS, toolchain, image-digest, reproducibility, qualification, and
operator-only flash-policy evidence. It cannot label a build hardware-qualified
without an explicit immutable qualification-evidence file.

The complete ownership rule is documented in
[`docs/FIRMWARE_INSTALLATION_BOUNDARY.md`](docs/FIRMWARE_INSTALLATION_BOUNDARY.md).
Legacy release candidates and the RC5 physical-qualification bundle are build
or evidence archives, not alternate installation paths. The retired
`tools/flash-physical-dfu-evidence.py` name remains only as a fail-closed
compatibility tombstone for historical provenance.

Run the no-build packaging regression tests with:

```bash
python3 tools/test-flasher-build-manifest.py
```

Atomizer and Flasher integration
--------------------------------

The current cross-repository runtime authority is
[`contracts/trio-composition-v4.json`](contracts/trio-composition-v4.json).
Atomizer reaches this repository's executable Renode bridge
only through its `tinysa-zs407` driver, as the explicitly selected
`tinysa-firmware-twin` source kind. The twin never claims USB identity or
modeled USB transactions. SignalLab is Atomizer's factory-default high-level
measurement driver when no preference exists; its active measurement edge
bypasses this repository. The separate SignalLab stimulus-intent sink remains
`reserved-not-connected` here, and no source failure authorizes fallback to
the twin.

Firmware installation is not an Atomizer capability. The standalone sibling
[Atom-Flasher](https://github.com/PhysicistJohn/Atom-Flasher) (formerly
`TinySA_Flasher`) owns OEM and manifested custom-firmware artifact admission,
CDC/DFU preflight, irreversible writes, durable journals, and post-write
continuity verification. Atom-Flasher's active interface catalog v3 retains
active application contract v2 (`deviceContractVersion: 2`); interface catalog
v2 and legacy application contract v1 are frozen. A custom build selected
through its manifest remains distinct from OEM provenance and does not become
hardware-qualified merely because it builds or reports matching version text.
Atomizer may warning-admit a compatible unknown installed revision as
`custom-unqualified`, but that operational status is neither exact byte proof
nor permission to flash.

NeptuneSDR ([Atom-NeptuneSDR-Twin](https://github.com/PhysicistJohn/Atom-NeptuneSDR-Twin))
is a future Atomizer driver and contract-evolution target, not a capability
supplied by this firmware repository or the current twin.

Run the exact executable ZS407 digital twin from the adjacent
[Atom-TinySA-Twin](https://github.com/PhysicistJohn/Atom-TinySA-Twin) checkout
without hardware (these compatibility commands delegate there):

```bash
tools/test-digital-twin.sh --smoke
tools/test-digital-twin.sh --full
```

The twin verifies and executes the immutable private v0.2.0 BIN, renders its
real 480×320 framebuffer, accepts jog/touch input, initializes SD and RF parts,
and sweeps deterministic RF tones. It never flashes or transmits. Set
`TINYSA_TWIN_ROOT` when the twin is not the default `../Atom-TinySA-Twin`
sibling checkout.

For the first non-flashing LLVM/GNU hybrid experiment:

```bash
experiments/llvm/build-hybrid.sh
```

The hybrid image is a compiler feasibility result only and is explicitly
**not hardware-qualified**. It must not be flashed before the physical baseline
and recovery gate are complete.

None of these commands flashes a device. This firmware checkout intentionally
exposes no automated physical flash command in its maintained workflow; admit
the generated manifest through the standalone Atom-Flasher instead. The
original upstream README below is historical upstream guidance, not this
fork's current cross-repository safety contract.

Read first
----------

- [Baseline and provenance](docs/BASELINE.md)
- [ZS407 hardware reference and confidence map](docs/HARDWARE_REFERENCE.md)
- [Firmware architecture](docs/ARCHITECTURE.md)
- [Replacement firmware architecture](docs/REPLACEMENT_FIRMWARE.md)
- [Performance, fixed-point DSP and FFT plan](docs/PERFORMANCE_DSP.md)
- [Enhancement and risk register](docs/ENHANCEMENT_RISK_REGISTER.md)
- [Final disposition of all 140 enhancements](docs/ENHANCEMENT_DISPOSITION.md)
- [RF experiment qualification gates](docs/RF_EXPERIMENT_GATES.md)
- [Waveform and signal-generator architecture](docs/WAVEFORM_GENERATOR.md)
- [Coherent analyzer and true-RF-AWG hardware v2](docs/HARDWARE_V2.md)
- [Cumulative phase and image plan](docs/PHASE_IMPLEMENTATION.md)
- [Private phase-image release policy](docs/PRIVATE_RELEASES.md)
- [Portable firmware/Mac core and generated contracts](modern/README.md)
- [Exact ZS407 executable digital twin](docs/DIGITAL_TWIN.md)
- [Atomizer twin contract](docs/ATOMIZER_TWIN_CONTRACT.md)
- [ChibiOS 21.11.5 port and qualification boundary](docs/CHIBIOS_21_11_5_PORT.md)
- [Atomic 480×320 embedded UI](docs/EMBEDDED_UI.md)
- [LLVM hybrid build experiment](experiments/llvm/README.md)
- [Known issues and community research](docs/KNOWN_ISSUES.md)
- [Reverse-engineering workflow](docs/REVERSE_ENGINEERING.md)
- [Hardware bring-up and recovery gate](docs/HARDWARE_BRINGUP.md)
- [Modernization roadmap](ROADMAP.md)
- [Upstream contribution candidates](docs/UPSTREAM.md)
- [Personal-account and contribution policy](CONTRIBUTING.md)

Safety boundary
---------------

Do not flash a locally modified image merely because it compiles. Before the
first firmware change, record the shipped firmware and hardware versions, run
and save the stock self-test results, preserve configuration/calibration data,
and prove DFU detection and recovery. The official project also recommends a
self-test before every update.

Part of the AtomOS suite
------------------------

This repository is one of eight in the AtomOS suite, all under
[github.com/PhysicistJohn](https://github.com/PhysicistJohn):

- [Atom-Atomizer](https://github.com/PhysicistJohn/Atom-Atomizer): AI-native
  spectrum analyzer application
- [Atom-Classifier](https://github.com/PhysicistJohn/Atom-Classifier): Bayesian
  RF waveform classification
- [Atom-Firmware](https://github.com/PhysicistJohn/Atom-Firmware): this
  repository
- [Atom-Flasher](https://github.com/PhysicistJohn/Atom-Flasher): fail-closed
  firmware flasher
- [Atom-NeptuneSDR-Twin](https://github.com/PhysicistJohn/Atom-NeptuneSDR-Twin):
  Renode digital twin of an SDR
- [Atom-SignalLab](https://github.com/PhysicistJohn/Atom-SignalLab): 3GPP and
  reference signal generation
- [Atom-TinySA-Twin](https://github.com/PhysicistJohn/Atom-TinySA-Twin): Renode
  digital twin that boots real ZS407 firmware
- [Atom-Website](https://github.com/PhysicistJohn/Atom-Website): product site

License
-------

This fork inherits the upstream tinySA licensing. The upstream repository
ships no top-level LICENSE file; its source files carry GNU General Public
License version 3 (or later) headers, and this fork keeps those headers and
terms unchanged. tinySA is a trademark of its respective owner; see the
upstream note below.

Original upstream README
------------------------

tinySA - tiny Spectrum Analyzer
==========================================================

[![GitHub release](http://img.shields.io/github/release/erikkaashoek/tinySA.svg?style=flat)][release]
[![CircleCI](https://circleci.com/gh/erikkaashoek/tinySA.svg?style=shield)](https://circleci.com/gh/erikkaashoek/tinySA)

[release]: https://github.com/erikkaashoek/tinySA/releases

<div align="center">
<img src="/doc/tinySA.jpg" width="480px">
</div>

# About

tinySA is very tiny handheld Spectrum Analyzer (SA). It is
standalone with lcd display, portable device with battery. This
project aim to provide an useful instrument for the RF 
enthusiast.

This repository contains source of tinySA firmware.

# Support

General tinySA support questions should be posted here: https://groups.io/g/tinysa/messages

Use github issue list only for firmware bugs and preferrably cross post to: https://groups.io/g/tinysa/messages

## Prepare ARM Cross Tools

**UPDATE**: Recent gcc version works to build tinySA, no need old version.

### MacOSX

Install the cross-compilation tools. Firmware installation is handled only by
the standalone Atom-Flasher and is not a toolchain prerequisite here.

    $ brew tap px4/px4
    $ brew install gcc-arm-none-eabi-80

### Linux (ubuntu)

Download arm cross tools from [here](https://developer.arm.com/tools-and-software/open-source-software/developer-tools/gnu-toolchain/gnu-rm/downloads).

    $ wget https://developer.arm.com/-/media/Files/downloads/gnu-rm/8-2018q4/gcc-arm-none-eabi-8-2018-q4-major-linux.tar.bz2
    $ sudo tar xfj gcc-arm-none-eabi-8-2018-q4-major-linux.tar.bz2 -C /usr/local
    $ PATH=/usr/local/gcc-arm-none-eabi-8-2018-q4-major/bin:$PATH

## Fetch source code

Fetch source and submodule.

    $ git clone https://github.com/erikkaashoek/tinySA.git
    $ cd tinySA
    $ git submodule update --init --recursive

## Build

Just make in the directory.

    $ make

For tinySA Ultra use this command

    $ make TARGET="F303"

### Build firmware using docker

Using [this docker image](https://hub.docker.com/r/edy555/arm-embedded) and without installing arm toolchain, you can build the firmware.

    $ cd tinySA
    $ docker run -it --rm -v $(PWD):/work edy555/arm-embedded:8.2 make

## Install firmware

The direct upstream write commands are intentionally disabled in this fork.
Package a committed custom build with `tools/package-flasher-build.sh`, then
select the emitted JSON manifest in the standalone
[Atom-Flasher](https://github.com/PhysicistJohn/Atom-Flasher). The Flasher
alone owns device preflight, DFU admission, the physical write, recovery
journaling, and post-reboot identity verification.

## Companion Tools

There are several numbers of great companion PC tools from third-party.

* [Soon to come](https://github.com/erikkaashoek/tinySA-Win) by Erik
* [tinySASaver](https://github.com/erikkaashoek/tinySA-saver) by Erik

## Documentation

* [tinySA User Guide](https://tinySA.org/wiki/)

## Reference

* [Specification](https://tinysa.org/wiki/pmwiki.php?n=Main.Specification)
* [Technical info](https://tinysa.org/wiki/pmwiki.php?n=Main.TechnicalDescription)

## Note

tinySA is a trademark owned by its respective owner. Unauthorized use the the name tinySA not permitted

## Authorized Distributor

* [See the Wiki](https://tinysa.org/wiki/pmwiki.php?n=Main.Buying)

## Credit

* [@erikkaashoek](https://github.com/erikkaashoek)

### Contributors

* [@edy555](https://github.com/edy555)
* [@hugen79](https://github.com/hugen79)
* [@cho45](https://github.com/cho45)
* [@DiSlord](https://github.com/DiSlord/)
