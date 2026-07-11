#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$ROOT/tools/lib.sh"

usage() {
  printf 'Usage: %s PHASE\n' "$0"
  printf 'Build PHASE 0..6 twice and archive a reproducible no-flash image.\n'
}

[ "$#" -eq 1 ] || { usage >&2; exit 2; }
phase=$1

case "$phase" in
  0) expected_branch=physicistjohn/phase-0-build-safety ;;
  1) expected_branch=physicistjohn/phase-1-host-core ;;
  2) expected_branch=physicistjohn/phase-2-deterministic-firmware ;;
  3) expected_branch=physicistjohn/phase-3-dsp-ui ;;
  4) expected_branch=physicistjohn/phase-4-rf-experiments ;;
  5) expected_branch=physicistjohn/phase-5-waveform-generator ;;
  6) expected_branch=physicistjohn/phase-6-final-integration ;;
  *) die 'PHASE must be an integer from 0 through 6' ;;
esac

branch=$(git -C "$ROOT" branch --show-current)
[ "$branch" = "$expected_branch" ] || \
  die "phase $phase must be built on $expected_branch (current: $branch)"

[ -z "$(git -C "$ROOT" status --porcelain)" ] || \
  die 'phase images require a clean committed worktree'

git -C "$ROOT" submodule status ChibiOS | grep -q '^ ' || \
  die 'initialize ChibiOS with: git submodule update --init --recursive'

toolchain_bin=$($ROOT/tools/bootstrap-toolchain.sh)
export PATH="$toolchain_bin:$PATH"
export LC_ALL=C

commit=$(git -C "$ROOT" rev-parse HEAD)
short_commit=$(printf '%s' "$commit" | cut -c1-7)
source_date_epoch=$(git -C "$ROOT" show -s --format=%ct HEAD)
version="tinySA4_v2.$phase-000-g$short_commit"
artifact_dir="$ROOT/.artifacts/phase-images/phase-$phase/$commit"
first_binary="$artifact_dir/first.bin"

rm -rf "$artifact_dir"
mkdir -p "$artifact_dir"

build_once() {
  make -C "$ROOT" TARGET=F303 clean >/dev/null
  SOURCE_DATE_EPOCH="$source_date_epoch" \
    make -C "$ROOT" TARGET=F303 PHASE="$phase" VERSION="$version" \
    -j"$(host_jobs)"
}

build_once

binary="$ROOT/build/tinySA4.bin"
elf="$ROOT/build/tinySA4.elf"
hex="$ROOT/build/tinySA4.hex"
[ -f "$binary" ] || die 'phase build did not produce build/tinySA4.bin'
[ -f "$elf" ] || die 'phase build did not produce build/tinySA4.elf'
[ -f "$hex" ] || die 'phase build did not produce build/tinySA4.hex'

size=$(wc -c < "$binary" | tr -d ' ')
[ "$size" -le 245760 ] || die 'firmware exceeds the 240 KiB application region'
strings "$binary" | grep -Fq '+ ZS407' || \
  die 'firmware does not contain the ZS407 hardware identity'
strings "$binary" | grep -Fq "$version" || \
  die 'firmware does not contain the requested phase version'
[ -z "$(arm-none-eabi-nm -u "$elf")" ] || die 'ELF contains unresolved symbols'

cp "$binary" "$first_binary"
first_hash=$(sha256_file "$first_binary")

build_once
second_hash=$(sha256_file "$binary")
[ "$first_hash" = "$second_hash" ] || \
  die "clean phase builds are not reproducible ($first_hash != $second_hash)"

for extension in bin elf hex map list dmp; do
  source_file="$ROOT/build/tinySA4.$extension"
  if [ -f "$source_file" ]; then
    cp "$source_file" "$artifact_dir/tinySA4_phase-$phase.$extension"
  fi
done
rm -f "$first_binary"

binary_hash=$(sha256_file "$artifact_dir/tinySA4_phase-$phase.bin")
elf_hash=$(sha256_file "$artifact_dir/tinySA4_phase-$phase.elf")
hex_hash=$(sha256_file "$artifact_dir/tinySA4_phase-$phase.hex")
size_report=$(arm-none-eabi-size "$artifact_dir/tinySA4_phase-$phase.elf")

{
  printf 'phase=%s\n' "$phase"
  printf 'branch=%s\n' "$branch"
  printf 'commit=%s\n' "$commit"
  printf 'chibios_commit=%s\n' "$(git -C "$ROOT/ChibiOS" rev-parse HEAD)"
  printf 'version=%s\n' "$version"
  printf 'source_date_epoch=%s\n' "$source_date_epoch"
  printf 'compiler=%s\n' "$(arm-none-eabi-gcc --version | sed -n '1p')"
  printf 'binary_size=%s\n' "$size"
  printf 'binary_sha256=%s\n' "$binary_hash"
  printf 'elf_sha256=%s\n' "$elf_hash"
  printf 'hex_sha256=%s\n' "$hex_hash"
  printf 'reproducible_clean_builds=true\n'
  printf 'hardware_qualified=false\n'
  printf '\n%s\n' "$size_report"
} > "$artifact_dir/manifest.txt"

printf 'Phase %s image complete (NOT HARDWARE QUALIFIED)\n' "$phase"
printf 'Branch:  %s\n' "$branch"
printf 'Commit:  %s\n' "$commit"
printf 'Version: %s\n' "$version"
printf 'Size:    %s bytes\n' "$size"
printf 'SHA-256: %s\n' "$binary_hash"
printf 'Files:   %s\n' "$artifact_dir"
