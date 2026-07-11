# Reverse-engineering workflow

The official release is unusually friendly to analysis: the download directory
publishes an unstripped ELF with symbols and DWARF beside the raw binary. Use
that ELF before attempting blind decompilation of the `.bin`.

## Acquire and inspect

```bash
tools/inspect-official-release.sh
```

The command verifies pinned artifact hashes and writes ignored reports under:

```text
.artifacts/reports/v1.4-224-gc979386/
  readelf.txt
  dwarf-info.txt
  disassembly-with-source.txt
  symbols.txt
  strings.txt
```

The important baseline facts are:

```text
ELF class       ELF32 little-endian ARM EABI5, hard-float
entry point     0x080001a1 (Thumb entry; Reset_Handler at 0x080001a0)
vector base     0x08000000
initial MSP     0x20000200
application     0x08000000 through 0x0802d567 in the binary image
SRAM            0x20000000 through 0x20009fff
CCM RAM         0x10000000 through 0x10001fff
system ROM      STM32 bootloader base declared as 0x1fffd800
```

## Ghidra

Preferred import:

1. Import the official `.elf`, not the `.bin`.
2. Accept the ELF memory map and ARM little-endian Cortex/Thumb analysis.
3. Enable DWARF and demangler analyzers. The project is C, but DWARF provides
   source file, type, line, global, and function information.
4. Retain the original image as a read-only program and create a separate
   analysis project for annotations.

If a future release provides only `.bin`, import it as raw ARM little-endian
Cortex-M/Thumb at base `0x08000000`. The word at offset 0 is the initial stack
pointer and the word at offset 4 is the Thumb reset vector. Define the SRAM and
CCM blocks above, then seed functions from the vector table.

## What decompilation is useful for here

Because matching source and full debug data exist, decompilation is not a way
to recover missing code. Its useful roles are:

- prove that the distributed binary corresponds to the published source;
- inspect compiler output around timing-sensitive RF and interrupt code;
- compare future binaries whose source commits or build flags are ambiguous;
- locate dormant features, protocol commands, and calibration paths;
- understand data layout and persisted-configuration compatibility;
- audit hard-fault, USB, storage, and bounds-handling behavior.

Start from a source symbol, examine its mixed source/disassembly, and annotate
hardware register effects. Avoid renaming based on guesses when DWARF already
provides an authoritative name.

## Binary comparison strategy

For every upstream release:

1. Record URL, retrieval date, size, and SHA-256 for all formats.
2. Record source and submodule commit IDs.
3. Extract compiler producer strings and compilation directories from DWARF.
4. Rebuild with pinned tools and compare `.bin` first.
5. If bytes differ, compare symbol addresses and section layouts before looking
   at instruction diffs. Library ordering and build-time strings can change
   relocations without changing application source.
6. Treat any unexplained difference in RF, calibration, startup, interrupt, or
   persistence code as a flash blocker.

The current release passes the strongest version of this process: its `.bin`
is byte-for-byte reproducible.

## Artifact policy

Downloaded firmware, toolchains, disassemblies, and analysis databases are
ignored under `.artifacts/`. The repository stores small manifests, hashes,
scripts, and conclusions. This keeps personal analysis reproducible without
silently redistributing third-party binaries or multi-gigabyte toolchains.
