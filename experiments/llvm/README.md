# LLVM hybrid build experiment

This is a **compile/link feasibility spike**, not a hardware-qualified firmware
variant. It proves that selected tinySA application modules can be compiled for
the Cortex-M4F with Apple Clang 17 and linked into the existing GNU/ChibiOS
image.

It does not flash, invoke DFU or communicate with a device.

## Run

```bash
experiments/llvm/build-hybrid.sh

CLANG_OPT=-Oz LLVM_BUILD_DIR=build-llvm-oz \
  experiments/llvm/build-hybrid.sh

CLANG_OPT=-Os LLVM_BUILD_DIR=build-llvm-os \
  experiments/llvm/build-hybrid.sh

CLANG_OPT=-O2 LLVM_BUILD_DIR=build-llvm-o2 \
  experiments/llvm/build-hybrid.sh

CLANG_MAIN=1 LLVM_PHASE=1 CLANG_OPT=-Oz \
  LLVM_BUILD_DIR=build-llvm-phase1 \
  LLVM_VERSION=tinySA4_llvm-p1-gdraft01 \
  experiments/llvm/build-hybrid.sh
```

Output is isolated under the requested `build-llvm*` directory. The normal
`build/` directory is not removed. The script downloads/reuses the pinned Arm GNU 11.3.Rel1 toolchain via
the normal bootstrap helper and uses `/usr/bin/clang` by default. Override with
`CLANG=/path/to/clang` if needed. `CLANG_OPT` changes only the admitted Clang
objects; GNU-owned objects retain the baseline flags.

`CLANG_MAIN=1` is deliberately opt-in. It requires `LLVM_PHASE=1` or later so
the unity RF translation unit uses the assembly-only hard-fault veneer. The
RTOS, HAL, startup, assembler, linker and C runtime remain GNU-owned.

The build identifies itself as `tinySA4_llvm-000-gc979386` and exports
`SOURCE_DATE_EPOCH`, defaulting to the pinned source commit time (`1778053464`).
This keeps the recorded matrix independent of later documentation commits. A
clean repeat produced the same `-Og` hash. Callers can override
`LLVM_VERSION`/`SOURCE_DATE_EPOCH` for another source baseline.

## Proven result

On Apple Clang 17.0.0 (`clang-1700.4.4.1`) and Arm GNU 11.3.Rel1:

| Clang objects | Binary | App flash | Delta from exact GNU | SHA-256 |
| --- | ---: | ---: | ---: | --- |
| inherited `-Og` | 217,044 B | 88.32% | +31,340 B | `61964684e36e5f73b141e0604f21c873defc8c02be42a51a7a0def326a2794eb` |
| `-O2` | 244,236 B | 99.38% | +58,532 B | `72d0a5d9dce5618ddbcef71fa2708d54406fb647b473566b55592e1abed53497` |
| `-Os` | 196,832 B | 80.09% | +11,128 B | `27f79b87288696a18f9159d32699715c146ecbf00493427fa03573ec9c7ae900` |
| `-Oz` | **184,136 B** | **74.93%** | **−1,568 B** | `f97f08f9b22b67adc4595518aad4d61fb1f20ae990d0ed67a4395d5da217237e` |
| exact GNU release | 185,704 B | 75.56% | baseline | `3c9847ff4d7b80561df2f2f1030a112703a083409ffb2ee11361b2413b7c1e41` |

All LLVM rows are compile/link results with **no hardware testing; do not
flash them**. The `-Oz` result is especially promising: selected Clang objects
produce a complete image 1,568 bytes smaller than the exact GNU release. It is
not evidence of equivalent behavior or speed. Conversely, broad `-O2` nearly
fills flash and leaves only 1,524 bytes, so performance optimization must be
module/function-specific.

The Phase 1 opt-in also compiles `main.c` plus its directly included
`sa_core.c` and `sa_cmd.c` with Clang `-Oz`. It links successfully at 186,372
bytes (75.83%, SHA-256
`04ca605d98b10e85ab821af219c5a69300174a49d594d4c460690403ff816481`).
That closes the known compiler parsing seam; it remains a no-flash codegen
experiment and is not directly size-comparable to the official image because
it contains the cumulative Phase 1 diagnostics and fault handler.

The default `-Og` growth is localized by unlinked object flash estimates:

| Object | GNU | Clang `-Og` | Delta |
| --- | ---: | ---: | ---: |
| `ui.o` | 45,746 B | 66,718 B | +20,972 B |
| `si4468.o` | 7,352 B | 13,518 B | +6,166 B |
| `plot.o` | 11,059 B | 15,279 B | +4,220 B |
| `ili9341.o` | 4,010 B | 7,070 B | +3,060 B |

Those files currently request GCC `optimize("Os")` while the inherited Clang
build remains at `-Og`; the matrix confirms that the mismatch, rather than an
intrinsic LLVM penalty, explains most of the first result.

## Compiler boundary

By default Clang compiles selected filesystem, USB configuration, board ADC,
plot, UI, LCD, RF peripheral, font, flash and RTC translation units. Arm GNU
11.3.1 compiles:

- startup and assembly;
- ChibiOS RTOS and HAL;
- `main.c`, which directly includes `sa_core.c` and `sa_cmd.c`;
- the context-switch/FPU implementation;
- every source not explicitly admitted by the wrapper.

Arm GNU also assembles, links, supplies newlib-nano/libgcc and converts the ELF
to `.bin`/`.hex`. `.comment` sections in `plot.o`, `ui.o` and `si4468.o` confirm
Clang provenance; `main.o` and `chsys.o` confirm GNU provenance.

With `CLANG_MAIN=1`, `main.o` (and therefore the included RF core and command
code) moves to Clang. `chsys.o` and all timing-critical RTOS/HAL objects remain
GNU provenance.

## Compatibility details

The inherited Makefile uses one GCC option string for compilation and linking.
`clang-cc.sh` removes only unsupported compile-time options such as
`--specs=nano.specs`, GNU assembler-listing flags and
`-fno-inline-small-functions`. The GNU linker still receives its original
newlib-nano specification.

The pinned ChibiOS contains CMSIS 4.10. Its GNU branch names an inline-assembly
clobber `vfpcc`, which Clang rejects. For Clang application modules only, the
wrapper defines `__SOFTFP__` as a **preprocessor/parser workaround** so those
unused CMSIS FPSCR inline functions are not emitted. The actual Clang target,
object attributes and ABI remain Cortex-M4 hard-float. ChibiOS and its FPU
context code stay GNU-built and do not use that workaround.

This is acceptable for a no-flash feasibility spike, not a final toolchain
architecture. A production Clang build needs a current compiler-aware CMSIS
layer or a narrowly reviewed compatibility patch plus FPU context tests.

Clang is forced to DWARF 4 because the pinned GNU 11 objdump cannot fully parse
Apple Clang's default newer DWARF forms.

## Migration findings

The first attempted Clang build of `main.c` found this real incompatibility:

```c
void hard_fault_handler_c(uint32_t *sp) __attribute__((naked));
```

The function contains ordinary C, local variables and LCD calls. Clang rejects
non-assembly statements in a naked function. Phase 1 now supplies the correct
structure behind its cumulative feature gate: a naked assembly veneer selects
MSP/PSP, saves R4-R11, and branches to an ordinary non-returning C reporter.
Both GNU and Clang compile/link it, and disassembly confirms the veneer. A
controlled fault test is still required before hardware qualification.

The experiment also surfaces warnings currently hidden or accepted by GCC,
including old-style field designators, self-assignment, declarations without
prototypes and optimizer pragmas with no Clang meaning. These should become
small correctness/cleanup changes, not one warning-suppression patch.

## Next experiments

1. Add host tests before changing arithmetic optimization.
2. Replace source pragmas with named per-module build optimization classes.
3. Use `-Oz` for UI/control and benchmark narrowly selected DSP/render kernels
   at `-O2` instead of applying `-O2` to every Clang object.
4. Record cycle, stack and object-symbol deltas automatically.
5. Hardware-test the completed hard-fault entry/report split.
6. Introduce modern CMSIS compiler support and explicitly test FPU context
   across preemption/interrupts.
7. Migrate one timing-sensitive driver only after logic-analyzer captures exist.
8. Consider LLD/LTO last, after the GNU-linked Clang object path is stable.

See [replacement architecture](../../docs/REPLACEMENT_FIRMWARE.md) and
[performance/DSP plan](../../docs/PERFORMANCE_DSP.md) for the broader design.
