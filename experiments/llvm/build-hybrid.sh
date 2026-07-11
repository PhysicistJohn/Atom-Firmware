#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
. "$ROOT/tools/lib.sh"

GNU_BIN=$($ROOT/tools/bootstrap-toolchain.sh)
export PATH="$GNU_BIN:$PATH"
export LC_ALL=C
build_dir=${LLVM_BUILD_DIR:-build-llvm}
LLVM_VERSION=${LLVM_VERSION:-tinySA4_llvm-000-gc979386}
SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH:-$(git -C "$ROOT" show -s --format=%ct c97938697b6c7485e7cab50bca9af76996b7d671)}
export SOURCE_DATE_EPOCH

case "$build_dir" in
  build-llvm|build-llvm-[a-z0-9_-]*) ;;
  *) die 'LLVM_BUILD_DIR must be build-llvm or start with build-llvm-' ;;
esac

git -C "$ROOT" submodule status ChibiOS | grep -q '^ ' || \
  die 'initialize ChibiOS with: git submodule update --init --recursive'

# The project's custom clean target is hard-coded to build/, even when
# BUILDDIR is overridden. Remove only this experiment's generated output.
rm -rf "$ROOT/$build_dir" "$ROOT/.dep"
make -C "$ROOT" \
  TARGET=F303 \
  BUILDDIR="$build_dir" \
  VERSION="$LLVM_VERSION" \
  CC="$ROOT/experiments/llvm/clang-cc.sh" \
  LD=arm-none-eabi-gcc \
  CP=arm-none-eabi-objcopy \
  AS='arm-none-eabi-gcc -x assembler-with-cpp' \
  AR=arm-none-eabi-ar \
  OD=arm-none-eabi-objdump \
  SZ=arm-none-eabi-size \
  HEX='arm-none-eabi-objcopy -O ihex' \
  BIN='arm-none-eabi-objcopy -O binary' \
  -j"$(host_jobs)"

binary="$ROOT/$build_dir/tinySA4.bin"
[ -f "$binary" ] || die "hybrid build did not produce $build_dir/tinySA4.bin"
[ "$(wc -c < "$binary" | tr -d ' ')" -le 245760 ] || \
  die 'hybrid firmware exceeds the 240 KiB application flash region'
strings "$binary" | grep -Fq '+ ZS407' || \
  die 'hybrid firmware does not contain the ZS407 hardware identity'

printf 'Built hybrid LLVM/GNU image in %s: %s bytes\n' "$build_dir" "$(wc -c < "$binary" | tr -d ' ')"
printf 'Clang optimization: %s\n' "${CLANG_OPT:-inherited -Og}"
printf 'Firmware version: %s\n' "$LLVM_VERSION"
printf 'SOURCE_DATE_EPOCH: %s\n' "$SOURCE_DATE_EPOCH"
printf 'SHA-256: %s\n' "$(sha256_file "$binary")"
printf 'This image is an experiment and is not hardware-qualified. Do not flash it.\n'
