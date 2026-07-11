# ZS407 baseline and provenance

Status: source and binary baseline established on 2026-07-10; physical-device
qualification still pending.

## Exact target

The target is the tinySA Ultra+ ZS407, not the Basic, ZS405, or ZS406. The
official model table identifies the rear label as the way to distinguish ZS406
from ZS407. The current firmware uses one `F303`/`tinySA4` image for the Ultra
family and detects the hardware at runtime.

At startup, `get_hw_version_text()` reads an ADC identification value. The
current table maps ADC values 2200 through 2299 to:

```text
hardware text: V0.5.4 + ZS407
hwid:         103
hw_if:        1
```

`main()` then treats `hwid >= 100` as the MAX2871-based hardware path, loads
the `v5_2_*` correction tables, enables the Ultra+ IF behavior, and derives the
upper boundary from 6.3 GHz plus the configured first IF. There is no separate
`ZS407` compiler define.

Official references:

- Model comparison: <https://tinysa.org/wiki/pmwiki.php?n=TinySA4.Comparison>
- Ultra/Ultra+ specification: <https://tinysa.org/wiki/pmwiki.php?n=TinySA4.Specification>
- Technical description: <https://tinysa.org/wiki/pmwiki.php?n=TinySA4.TechnicalDescription>

## Pinned software provenance

| Item | Pinned value |
| --- | --- |
| Official source | <https://github.com/erikkaashoek/tinySA> |
| Source commit | `c97938697b6c7485e7cab50bca9af76996b7d671` |
| Source description | `v1.4-224-gc979386` |
| Source commit date | 2026-05-06 |
| ChibiOS submodule | `ade76dea89cd093650552328e881252a06486094` |
| ChibiOS fork | <https://github.com/edy555/ChibiOS> |
| ChibiOS commit date | 2022-07-11 |
| Kernel version macro | `4.0.0` |
| FatFs | `R0.14b` |
| Official release | `tinySA4_v1.4-224-gc979386` |
| Compiler | Arm GNU Toolchain 11.3.Rel1, GCC 11.3.1 20220712 |
| Firmware target | STM32F303xC, Cortex-M4, hard-float Thumb |

The source is still active—the pinned head is from May 2026. What is old is
primarily the architecture: an old ChibiOS generation, large unity-compiled C
translation units, extensive global state, Make-based build discovery, and no
current automated ZS407 validation pipeline.

## Official artifacts

The official update page points Ultra users to
<http://dfu.tinydevices.org/tinySA4/DFU/>. The directory offered `.bin`, `.dfu`,
`.elf`, and `.hex` files for the pinned release. Locally recorded hashes are:

| Artifact | SHA-256 |
| --- | --- |
| `.bin` | `3c9847ff4d7b80561df2f2f1030a112703a083409ffb2ee11361b2413b7c1e41` |
| `.dfu` | `0fdf3233b4e117f793466413bf6f614e55fd3483b7d34d45a636bc116a63a8e2` |
| `.elf` | `d74099496ba074f41f91358cbc1ff3f92ea388c0b7b60221da59cb61f64c397d` |
| `.hex` | `827049301dd9c21a0162fe0ac7727fba0308a6f5268b81b5fac8e8ee7764ee55` |

The release server is HTTP-only and publishes no detached signature or
authoritative checksum. These hashes are therefore a reproducible local pin,
not proof against compromise of the distribution server. The source commit in
the filename and embedded version string does match the Git checkout.

## Reproduction result

The official `.elf` is unstripped and includes DWARF. It reports the compiler,
all important source paths, and a Windows compilation directory
(`C:\\work\\VNA\\tinySA`). Reproduction proceeded in three controlled steps:

1. Arm GNU 11.3.Rel1 for macOS produced the same version strings, symbol layout,
   flash size, and 185,704-byte binary. Its target libraries were ordered
   differently from the official image.
2. Linking with target libraries extracted from Arm's Windows 11.3.Rel1 package
   made every symbol address and all but ten bytes identical.
3. The ten bytes were the build banner's `__DATE__` and `__TIME__`. Setting
   `SOURCE_DATE_EPOCH=1778074389` recreated `May  6 2026 - 13:33:09` and made
   the binary byte-for-byte identical.

Run the full proof with:

```bash
tools/reproduce-official-release.sh
```

The release manifest is
[`release-manifests/v1.4-224-gc979386.env`](../release-manifests/v1.4-224-gc979386.env).

The Windows toolchain archive's checksum sidecars are known to have been wrong
or unavailable. This fork pins the SHA-256 of the archive retrieved over HTTPS
and documents the matching MD5 independently reported on Arm's own support
forum: <https://community.arm.com/support-forums/f/compilers-and-libraries-forum/53343/arm-gnu-toolchain-11-3-rel1-windows-arm-none-eabi-md5-is-incorrect>.

## Build observations

- Flash application region: 240 KiB at `0x08000000`.
- Calibration region: 16 KiB at `0x0803c000`.
- Reproduced application image: 185,704 bytes, 75.56% of application flash.
- SRAM region: 40 KiB at `0x20000000`, fully assigned by the linker among
  stacks, data, BSS, and a 7,328-byte heap remainder.
- CCM RAM: 8 KiB at `0x10000000`, currently unused by the linker layout.
- Build warnings: only old ChibiOS/CMSIS fallthrough and stack-pointer-clobber
  warnings plus a duplicate `clean` target warning; no application warning was
  emitted under the existing flags.

An open upstream issue reports noise and self-test failure with a separately
compiled image. Exact reproduction removes most build uncertainty, but it does
not replace physical self-test and RF regression testing:
<https://github.com/erikkaashoek/tinySA/issues/152>.

## Licensing status

Most application files declare GPL version 3 or later. ChibiOS-derived files
carry Apache-2.0 headers, FatFs carries its own permissive notice, and some
radio configuration headers come from Silicon Labs. The upstream repository
does not contain a root `LICENSE` or `COPYING` file at this commit.

Do not assign a new aggregate license casually. Before distributing modified
binaries, complete a file-level license inventory and include all required
notices and corresponding source. Clarifying the missing root license with the
upstream maintainer is tracked as an upstream candidate.
