#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$ROOT/tools/lib.sh"

usage() {
  printf 'Usage: %s v0.2.0\n' "$0"
  printf 'Build the Protocol v2 ZS407 laboratory image twice; never flash.\n'
}

[ "$#" -eq 1 ] || { usage >&2; exit 2; }
release=$1
case "$release" in
  v0.2.0)
    profile=protocol-v2
    expected_branch=physicistjohn/release-v0.2-protocol-marshalling
    tag=lab-v0.2.0-protocol
    ;;
  *) die 'only v0.2.0 is defined by this release script' ;;
esac

branch=$(git -C "$ROOT" branch --show-current)
[ "$branch" = "$expected_branch" ] || \
  die "$release must be built on $expected_branch (current: $branch)"
[ -z "$(git -C "$ROOT" status --porcelain)" ] || \
  die 'laboratory images require a clean committed worktree'
git -C "$ROOT" submodule status ChibiOS | grep -q '^ ' || \
  die 'initialize ChibiOS with: git submodule update --init --recursive'

toolchain_bin=$($ROOT/tools/bootstrap-toolchain.sh)
export PATH="$toolchain_bin:$PATH"
export LC_ALL=C

commit=$(git -C "$ROOT" rev-parse HEAD)
short_commit=$(printf '%s' "$commit" | cut -c1-7)
source_date_epoch=$(git -C "$ROOT" show -s --format=%ct HEAD)
version="tinySA4_lab-${release}-g${short_commit}"
artifact_dir="$ROOT/.artifacts/lab-releases/$release/$commit"
first_binary="$artifact_dir/first.bin"

rm -rf "$artifact_dir"
mkdir -p "$artifact_dir"
"$ROOT/tools/test-host-core.sh" | tee "$artifact_dir/host-tests.txt"

build_once() {
  make -C "$ROOT" TARGET=F303 clean >/dev/null
  SOURCE_DATE_EPOCH="$source_date_epoch" \
    make -C "$ROOT" TARGET=F303 PHASE=6 RELEASE_PROFILE="$profile" \
      VERSION="$version" -j"$(host_jobs)"
}

build_once
binary="$ROOT/build/tinySA4.bin"
elf="$ROOT/build/tinySA4.elf"
hex="$ROOT/build/tinySA4.hex"
[ -f "$binary" ] || die 'release build did not produce build/tinySA4.bin'
[ -f "$elf" ] || die 'release build did not produce build/tinySA4.elf'
[ -f "$hex" ] || die 'release build did not produce build/tinySA4.hex'
size=$(wc -c < "$binary" | tr -d ' ')
[ "$size" -le 245760 ] || die 'firmware exceeds the 240 KiB application region'
strings "$binary" | grep -Fq '+ ZS407' || \
  die 'firmware does not contain the ZS407 identity'
strings "$binary" | grep -Fq "$version" || \
  die 'firmware does not contain the requested release version'
strings "$binary" | grep -Fq 'protocol_v2=1' || \
  die 'firmware does not contain the Protocol v2 diagnostics'
[ -z "$(arm-none-eabi-nm -u "$elf")" ] || die 'ELF has unresolved symbols'
cp "$binary" "$first_binary"
first_hash=$(sha256_file "$first_binary")

build_once
second_hash=$(sha256_file "$binary")
[ "$first_hash" = "$second_hash" ] || \
  die "clean release builds differ ($first_hash != $second_hash)"

"$ROOT/tools/audit-output-lock.py" "$elf" \
  > "$artifact_dir/output-gate-audit.txt"
"$ROOT/tools/audit-protocol-v2-locks.py" "$elf" \
  > "$artifact_dir/protocol-v2-lock-audit.txt"

stem="tinySA4_${release}_protocol-v2"
for extension in bin elf hex map list dmp; do
  source_file="$ROOT/build/tinySA4.$extension"
  if [ -f "$source_file" ]; then
    cp "$source_file" "$artifact_dir/$stem.$extension"
  fi
done
rm -f "$first_binary"
cp "$ROOT/.artifacts/host-tests/protocol-v2-benchmark.txt" \
  "$artifact_dir/protocol-v2-benchmark.txt"

arm-none-eabi-size -A "$artifact_dir/$stem.elf" \
  > "$artifact_dir/sections.txt"
find "$ROOT/build/obj" -name '*.su' -type f -exec sed -n '/./p' {} \; \
  | sort -k2,2nr > "$artifact_dir/stack-usage.txt"

binary_hash=$(sha256_file "$artifact_dir/$stem.bin")
elf_hash=$(sha256_file "$artifact_dir/$stem.elf")
hex_hash=$(sha256_file "$artifact_dir/$stem.hex")
benchmark_hash=$(sha256_file "$artifact_dir/protocol-v2-benchmark.txt")
bss_bytes=$(awk '$1 == ".bss" { print $2 }' "$artifact_dir/sections.txt")
heap_bytes=$(awk '$1 == ".heap" { print $2 }' "$artifact_dir/sections.txt")
ccm_bytes=$(awk '$1 == ".ccmram" { print $2 }' "$artifact_dir/sections.txt")
[ -n "$bss_bytes" ] && [ -n "$heap_bytes" ] && [ -n "$ccm_bytes" ] || \
  die 'section report is missing RAM accounting'
[ "$heap_bytes" -ge 4096 ] || die "remaining heap is below 4 KiB ($heap_bytes)"
[ "$ccm_bytes" -le 8192 ] || die "CCM overflow ($ccm_bytes)"

size_report=$(arm-none-eabi-size "$artifact_dir/$stem.elf")
{
  printf 'release=%s\n' "$release"
  printf 'release_tag=%s\n' "$tag"
  printf 'profile=%s\n' "$profile"
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
  printf 'benchmark_sha256=%s\n' "$benchmark_hash"
  printf 'bss_bytes=%s\n' "$bss_bytes"
  printf 'heap_bytes=%s\n' "$heap_bytes"
  printf 'ccm_bytes=%s\n' "$ccm_bytes"
  printf 'reproducible_clean_builds=true\n'
  printf 'host_tests=passed\n'
  printf 'output_lock_audit=passed\n'
  printf 'protocol_v2_lock_audit=passed\n'
  printf 'hardware_qualified=false\n'
  printf 'binary_transport_enabled=false\n'
  printf 'hardware_crc_default=false\n'
  printf 'rf_bus_timing_changed=false\n'
  printf 'automated_flash=false\n'
  printf '\n%s\n' "$size_report"
} > "$artifact_dir/manifest.txt"

printf '%s image complete (NO FLASH / NOT HARDWARE QUALIFIED)\n' "$release"
printf 'Branch:  %s\n' "$branch"
printf 'Commit:  %s\n' "$commit"
printf 'Version: %s\n' "$version"
printf 'Size:    %s bytes\n' "$size"
printf 'Heap:    %s bytes\n' "$heap_bytes"
printf 'SHA-256: %s\n' "$binary_hash"
printf 'Files:   %s\n' "$artifact_dir"
