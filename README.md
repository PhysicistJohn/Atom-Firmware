PhysicistJohn tinySA Ultra+ ZS407 firmware lab
==========================================================

This is the personal research fork for PhysicistJohn's **tinySA Ultra+ ZS407**.
The first goal is to preserve, understand, and reproduce the official firmware.
The second is to improve it without sacrificing RF behavior, calibration,
recovery, or protocol compatibility.

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

Reproduce it locally:

```bash
git submodule update --init --recursive
tools/reproduce-official-release.sh
```

The first run downloads pinned Arm GNU 11.3.Rel1 toolchain artifacts. Exact
reproduction uses the Windows package's target libraries because the official
ELF shows that the release was built in a Windows ChibiStudio environment.
All downloaded firmware and toolchains live under ignored `.artifacts/`.

For an ordinary development build:

```bash
tools/build-zs407.sh
```

Neither command flashes a device. There is intentionally no automated flash
command in this fork yet.

Read first
----------

- [Baseline and provenance](docs/BASELINE.md)
- [Firmware architecture](docs/ARCHITECTURE.md)
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

Install cross tools and firmware updating tool.

    $ brew tap px4/px4
    $ brew install gcc-arm-none-eabi-80
    $ brew install dfu-util

### Linux (ubuntu)

Download arm cross tools from [here](https://developer.arm.com/tools-and-software/open-source-software/developer-tools/gnu-toolchain/gnu-rm/downloads).

    $ wget https://developer.arm.com/-/media/Files/downloads/gnu-rm/8-2018q4/gcc-arm-none-eabi-8-2018-q4-major-linux.tar.bz2
    $ sudo tar xfj gcc-arm-none-eabi-8-2018-q4-major-linux.tar.bz2 -C /usr/local
    $ PATH=/usr/local/gcc-arm-none-eabi-8-2018-q4-major/bin:$PATH
    $ sudo apt install -y dfu-util

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

## Flash firmware

First, make device enter DFU mode by one of following methods.

* Jumper BOOT0 pin at powering device
* Select menu Config->DFU (needs recent firmware)

Then, flash firmware using dfu-util via USB.

    $ dfu-util -d 0483:df11 -a 0 -s 0x08000000:leave -D build/ch.bin

Or simply use make.

    $ make flash

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
