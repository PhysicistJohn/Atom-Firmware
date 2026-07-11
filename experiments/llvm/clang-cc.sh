#!/usr/bin/env bash
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
CLANG=${CLANG:-/usr/bin/clang}
CLANG_OPT=${CLANG_OPT:-}
GNU_BIN=$($ROOT/tools/bootstrap-toolchain.sh)
GNU_ROOT=$(CDPATH= cd -- "$GNU_BIN/.." && pwd)
SYSROOT="$GNU_ROOT/arm-none-eabi"
GCC_VERSION=$($GNU_BIN/arm-none-eabi-gcc -dumpfullversion)
GCC_INCLUDE="$GNU_ROOT/lib/gcc/arm-none-eabi/$GCC_VERSION/include"
GCC_INCLUDE_FIXED="$GNU_ROOT/lib/gcc/arm-none-eabi/$GCC_VERSION/include-fixed"

case "$CLANG_OPT" in
  ''|-O0|-O1|-O2|-O3|-Og|-Os|-Oz) ;;
  *)
    printf 'error: unsupported CLANG_OPT %s\n' "$CLANG_OPT" >&2
    exit 2
    ;;
esac

# Keep startup, RTOS/HAL, the monolithic RF core in main.c, and all assembly on
# the proven GNU toolchain. The pinned ChibiOS tree carries CMSIS 4.10 headers
# whose GCC-only FPSCR clobber syntax is rejected by Clang; more importantly,
# the context switcher and RF timing are hardware-critical. This wrapper is an
# application-module experiment, not an LLVM-only port.
use_clang=false
for argument in "$@"; do
  source_name=${argument##*/}
  case "$source_name" in
    main.c)
      if [ "${CLANG_MAIN:-0}" = 1 ]; then
        use_clang=true
      fi
      ;;
    ff.c|ffunicode.c|usbcfg.c|adc.c|plot.c|ui.c|ili9341.c|tlv320aic3204.c|si5351.c|numfont20x22.c|Font5x7.c|Font10x14.c|Font7x13b.c|flash.c|si4468.c|rtc.c|zs407_*.c)
      use_clang=true
      ;;
  esac
done

if [ "$use_clang" = false ]; then
  exec "$GNU_BIN/arm-none-eabi-gcc" "$@"
fi

# The inherited ChibiOS GCC rules mix compiler, assembler-listing, and linker
# flags. Strip only flags that Clang cannot consume; GNU ld still receives the
# original options because the build uses arm-none-eabi-gcc as LD.
filtered=()
for argument in "$@"; do
  case "$argument" in
    --specs=nano.specs|-fno-inline-small-functions|-mno-thumb-interwork|-fstack-usage|-fsingle-precision-constant)
      ;;
    -O0|-O1|-O2|-O3|-Og|-Os|-Oz)
      if [ -z "$CLANG_OPT" ]; then
        filtered+=("$argument")
      fi
      ;;
    -Wa,-alms=*|-Wa,-amhls=*)
      ;;
    *)
      filtered+=("$argument")
      ;;
  esac
done

if [ -n "$CLANG_OPT" ]; then
  filtered+=("$CLANG_OPT")
fi

# Parser-only workaround for CMSIS 4.10's unsupported "vfpcc" clobber. The
# target and object ABI remain hard-float; GNU-built ChibiOS owns FPU context.
exec "$CLANG" \
  --target=arm-none-eabi \
  --sysroot="$SYSROOT" \
  -D__SOFTFP__ \
  -gdwarf-4 \
  -Wno-macro-redefined \
  -Wno-unknown-pragmas \
  -isystem "$GCC_INCLUDE" \
  -isystem "$GCC_INCLUDE_FIXED" \
  "${filtered[@]}"
