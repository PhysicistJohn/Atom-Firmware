#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$ROOT/tools/lib.sh"

[ -d "$ROOT/ChibiOS/.git" ] || [ -f "$ROOT/ChibiOS/.git" ] || \
  die 'initialize ChibiOS with: git submodule update --init --recursive'
expected_chibios=$(git -C "$ROOT" ls-files --stage ChibiOS | \
  awk '$1 == "160000" { print $2 }')
[ "${#expected_chibios}" -eq 40 ] || die 'ChibiOS gitlink is missing or invalid'
actual_chibios=$(git -C "$ROOT/ChibiOS" rev-parse HEAD)
[ "$actual_chibios" = "$expected_chibios" ] || \
  die "ChibiOS HEAD differs from the recorded gitlink ($actual_chibios != $expected_chibios)"
[ -z "$(git -C "$ROOT/ChibiOS" status --porcelain)" ] || \
  die 'ChibiOS worktree must be clean for the firmware build gate'

toolchain_bin=$($ROOT/tools/bootstrap-toolchain.sh)
PATH="$toolchain_bin:$PATH"
export PATH
export LC_ALL=C
source_date_epoch=$(git -C "$ROOT" show -s --format=%ct HEAD)
jobs=${JOBS:-$(host_jobs)}

build_and_verify() {
  target=$1
  phase=$2
  release_profile=$3
  project=$4
  maximum_bytes=$5
  version=$6
  require_zs407=$7

  set -- "TARGET=$target" "RELEASE_PROFILE=$release_profile" \
    'RELEASE_HARD_FAULT_VENEER=no' "VERSION=$version"
  if [ -n "$phase" ]; then
    set -- "$@" "PHASE=$phase"
  fi

  env -i HOME="$HOME" PATH="$PATH" LC_ALL=C TMPDIR="${TMPDIR:-/tmp}" \
    make -C "$ROOT" "$@" clean >/dev/null 2>&1
  env -i HOME="$HOME" PATH="$PATH" LC_ALL=C TMPDIR="${TMPDIR:-/tmp}" \
    SOURCE_DATE_EPOCH="$source_date_epoch" \
    make -C "$ROOT" "$@" -j"$jobs"

  binary="$ROOT/build/$project.bin"
  elf="$ROOT/build/$project.elf"
  ihex="$ROOT/build/$project.hex"
  for artifact in "$binary" "$elf" "$ihex"; do
    [ -s "$artifact" ] || die "build did not produce a non-empty $artifact"
  done
  size=$(wc -c < "$binary" | tr -d ' ')
  [ "$size" -le "$maximum_bytes" ] || \
    die "$project contains $size bytes; limit is $maximum_bytes"
  arm-none-eabi-strings "$binary" | grep -Fq "$version" || \
    die "$project does not contain the requested version $version"
  if [ "$require_zs407" = true ]; then
    arm-none-eabi-strings "$binary" | grep -Fq '+ ZS407' || \
      die "$project does not contain the ZS407 hardware identity"
  fi
  [ -z "$(arm-none-eabi-nm -u "$elf")" ] || \
    die "$project ELF contains unresolved symbols"

  if [ "$target" = F303 ] && [ "$phase" = 6 ]; then
    "$ROOT/tools/audit-output-lock.py" "$elf"
  fi
  if [ "$release_profile" = protocol-v2 ]; then
    "$ROOT/tools/audit-protocol-v2-locks.py" "$elf"
  fi

  printf '%s: passed bytes=%s sha256=%s\n' \
    "$version" "$size" "$(sha256_file "$binary")"
}

printf 'Arm toolchain: %s\n' "$(arm-none-eabi-gcc --version | sed -n '1p')"
printf 'ChibiOS gitlink: %s\n' "$expected_chibios"
build_and_verify F072 '' '' tinySA 118784 tinySA_f072-ci false
build_and_verify F303 6 '' tinySA4 245760 tinySA4_phase6-ci true
build_and_verify F303 6 protocol-v2 tinySA4 245760 \
  tinySA4_protocol-v2-ci true
printf 'Firmware compile/link/lock gates: passed\n'
