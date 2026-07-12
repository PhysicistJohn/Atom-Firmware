#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$ROOT/tools/lib.sh"

expected_branch=physicistjohn/hardware-v0.3-fft1024
branch=$(git -C "$ROOT" branch --show-current)
[ "$branch" = "$expected_branch" ] || \
  die "hardware trial must be built on $expected_branch (current: $branch)"
[ -z "$(git -C "$ROOT" status --porcelain)" ] || \
  die 'hardware trial requires a clean committed worktree'
git -C "$ROOT" submodule status ChibiOS | grep -q '^ ' || \
  die 'initialize ChibiOS with: git submodule update --init --recursive'

ARTIFACTS=${TINYSA_ARTIFACTS_DIR:-"$ROOT/.artifacts"}
toolchain_bin=$(TINYSA_ARTIFACTS_DIR="$ARTIFACTS" \
  "$ROOT/tools/bootstrap-toolchain.sh")
export PATH="$toolchain_bin:$PATH"
export LC_ALL=C

commit=$(git -C "$ROOT" rev-parse HEAD)
short_commit=$(printf '%s' "$commit" | cut -c1-7)
source_date_epoch=$(git -C "$ROOT" show -s --format=%ct HEAD)
version="tinySA4_hw-v0.3-fft1024-g$short_commit"
artifact_dir="$ARTIFACTS/hardware-trials/v0.3/$commit"
first_binary="$artifact_dir/first.bin"

rm -rf "$artifact_dir"
mkdir -p "$artifact_dir"

TINYSA_ARTIFACTS_DIR="$ARTIFACTS" "$ROOT/tools/test-host-core.sh" \
  > "$artifact_dir/host-tests.txt"

build_f072() {
  make -C "$ROOT" TARGET=F072 clean >/dev/null
  SOURCE_DATE_EPOCH="$source_date_epoch" \
    make -C "$ROOT" TARGET=F072 \
      VERSION='tinySA_f072-hw-v0.3-regression' -j"$(host_jobs)"
}

build_f072 > "$artifact_dir/f072-build.txt" 2>&1
f072_binary="$ROOT/build/tinySA.bin"
f072_elf="$ROOT/build/tinySA.elf"
[ -f "$f072_binary" ] && [ -f "$f072_elf" ] || \
  die 'F072 regression did not produce BIN and ELF'
[ -z "$(arm-none-eabi-nm -u "$f072_elf")" ] || \
  die 'F072 regression ELF has unresolved symbols'
f072_first_hash=$(sha256_file "$f072_binary")
build_f072 >> "$artifact_dir/f072-build.txt" 2>&1
f072_hash=$(sha256_file "$f072_binary")
[ "$f072_first_hash" = "$f072_hash" ] || \
  die "clean F072 builds differ ($f072_first_hash != $f072_hash)"
f072_size=$(wc -c < "$f072_binary" | tr -d ' ')

build_f303() {
  make -C "$ROOT" TARGET=F303 clean >/dev/null
  SOURCE_DATE_EPOCH="$source_date_epoch" \
    make -C "$ROOT" TARGET=F303 PHASE=6 RELEASE_PROFILE=protocol-v2 \
      VERSION="$version" -j"$(host_jobs)"
}

build_f303
binary="$ROOT/build/tinySA4.bin"
elf="$ROOT/build/tinySA4.elf"
hex="$ROOT/build/tinySA4.hex"
[ -f "$binary" ] && [ -f "$elf" ] && [ -f "$hex" ] || \
  die 'F303 hardware trial did not produce BIN, ELF and HEX'
size=$(wc -c < "$binary" | tr -d ' ')
[ "$size" -le 245760 ] || die 'hardware trial exceeds application flash'
[ -z "$(arm-none-eabi-nm -u "$elf")" ] || die 'F303 ELF has unresolved symbols'
strings "$binary" | grep -Fq "$version" || die 'version string is absent'
strings "$binary" | grep -Fq '+ ZS407' || die 'ZS407 identity is absent'
strings "$binary" | grep -Fq 'fft_bench points=' || \
  die '1024-point hardware benchmark is absent'
cp "$binary" "$first_binary"
first_hash=$(sha256_file "$first_binary")

build_f303
second_hash=$(sha256_file "$binary")
[ "$first_hash" = "$second_hash" ] || \
  die "clean F303 builds differ ($first_hash != $second_hash)"

"$ROOT/tools/audit-output-lock.py" "$elf" \
  > "$artifact_dir/output-gate-audit.txt"
"$ROOT/tools/audit-protocol-v2-locks.py" "$elf" \
  > "$artifact_dir/protocol-v2-lock-audit.txt"

stem=tinySA4_hw-v0.3-fft1024
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
bss_bytes=$(awk '$1 == ".bss" { print $2 }' "$artifact_dir/sections.txt")
heap_bytes=$(awk '$1 == ".heap" { print $2 }' "$artifact_dir/sections.txt")
ccm_bytes=$(awk '$1 == ".ccmram" { print $2 }' "$artifact_dir/sections.txt")
[ "$heap_bytes" -ge 4096 ] || die "remaining heap is below 4 KiB ($heap_bytes)"
[ "$ccm_bytes" -eq 7696 ] || die "unexpected CCM use ($ccm_bytes)"

rollback="$ARTIFACTS/upstream/v1.4-224-gc979386/tinySA4_v1.4-224-gc979386.bin"
[ -f "$rollback" ] || die 'official rollback BIN is missing'
verify_sha256 "$rollback" \
  3c9847ff4d7b80561df2f2f1030a112703a083409ffb2ee11361b2413b7c1e41

size_report=$(arm-none-eabi-size "$artifact_dir/$stem.elf")
{
  printf 'trial=v0.3-fft1024\n'
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
  printf 'f072_binary_size=%s\n' "$f072_size"
  printf 'f072_binary_sha256=%s\n' "$f072_hash"
  printf 'bss_bytes=%s\n' "$bss_bytes"
  printf 'heap_bytes=%s\n' "$heap_bytes"
  printf 'ccm_bytes=%s\n' "$ccm_bytes"
  printf 'maximum_fft_points=1024\n'
  printf 'reproducible_clean_builds=true\n'
  printf 'host_tests=passed\n'
  printf 'f072_regression=passed\n'
  printf 'output_lock_audit=passed\n'
  printf 'protocol_v2_lock_audit=passed\n'
  printf 'official_rollback_verified=true\n'
  printf 'hardware_qualified=false\n'
  printf 'automated_flash=false\n'
  printf '\n%s\n' "$size_report"
} > "$artifact_dir/manifest.txt"

printf 'Hardware trial v0.3 image complete (NOT YET HARDWARE QUALIFIED)\n'
printf 'Commit:  %s\n' "$commit"
printf 'Version: %s\n' "$version"
printf 'Size:    %s bytes\n' "$size"
printf 'Heap:    %s bytes\n' "$heap_bytes"
printf 'CCM:     %s / 8192 bytes\n' "$ccm_bytes"
printf 'SHA-256: %s\n' "$binary_hash"
printf 'Files:   %s\n' "$artifact_dir"
