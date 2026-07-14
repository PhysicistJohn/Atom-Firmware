#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$ROOT/tools/lib.sh"

release_id=${1:-v0.4-chibios21.11.5-rc2}
[ "$release_id" = v0.4-chibios21.11.5-rc2 ] || \
  die "unsupported ChibiOS candidate: $release_id"

[ -z "$(git -C "$ROOT" status --porcelain)" ] || \
  die 'candidate images require a clean committed worktree'

commit=$(git -C "$ROOT" rev-parse HEAD)
chibios_commit=$(git -C "$ROOT/ChibiOS" rev-parse HEAD)
[ "$chibios_commit" = 2b8f425d26a61a7887916f7052b401f9e767a949 ] || \
  die "unexpected ChibiOS commit $chibios_commit"

toolchain_bin=$($ROOT/tools/bootstrap-toolchain.sh)
export PATH="$toolchain_bin:$PATH"
export LC_ALL=C

source_date_epoch=$(git -C "$ROOT" show -s --format=%ct HEAD)
version='tinySA4_v0.4-chibios21-rc2'
artifact_dir="$ROOT/.artifacts/chibios-releases/$release_id/$commit"
stem="tinySA4_${release_id}"
first_binary="$artifact_dir/first.bin"

mkdir -p "$artifact_dir"
rm -f "$artifact_dir"/*

build_once() {
  make -C "$ROOT" TARGET=F303 clean >/dev/null
  SOURCE_DATE_EPOCH="$source_date_epoch" \
    make -C "$ROOT" TARGET=F303 VERSION="$version" \
      -j"$(host_jobs)"
}

build_once
binary="$ROOT/build/tinySA4.bin"
elf="$ROOT/build/tinySA4.elf"
[ -f "$binary" ] && [ -f "$elf" ] || \
  die 'F303 build did not produce BIN and ELF'
[ -z "$(arm-none-eabi-nm -u "$elf")" ] || \
  die 'candidate ELF has unresolved symbols'
double_helper_calls=$(arm-none-eabi-objdump -d "$elf" | \
  grep -Ec 'bl[[:space:]].*<__aeabi_d' || true)
[ "$double_helper_calls" -le 32 ] || \
  die "candidate regressed to software double arithmetic ($double_helper_calls helper calls)"
size=$(wc -c < "$binary" | tr -d ' ')
[ "$size" -le 245760 ] || \
  die "candidate exceeds the 240 KiB application region ($size bytes)"
strings "$binary" | grep -Fq "$version" || \
  die 'candidate does not contain its requested version identity'
strings "$binary" | grep -Fq '+ ZS407' || \
  die 'candidate does not contain the ZS407 identity'
cp "$binary" "$first_binary"
first_hash=$(sha256_file "$first_binary")

build_once
second_hash=$(sha256_file "$binary")
[ "$first_hash" = "$second_hash" ] || \
  die "clean candidate builds differ ($first_hash != $second_hash)"

for extension in bin elf hex map list dmp; do
  source_file="$ROOT/build/tinySA4.$extension"
  if [ -f "$source_file" ]; then
    cp "$source_file" "$artifact_dir/$stem.$extension"
  fi
done
rm -f "$first_binary"

arm-none-eabi-size -A "$artifact_dir/$stem.elf" \
  > "$artifact_dir/sections.txt"
arm-none-eabi-size "$artifact_dir/$stem.elf" \
  > "$artifact_dir/size.txt"

binary_hash=$(sha256_file "$artifact_dir/$stem.bin")
elf_hash=$(sha256_file "$artifact_dir/$stem.elf")
hex_hash=$(sha256_file "$artifact_dir/$stem.hex")

{
  printf 'release_id=%s\n' "$release_id"
  printf 'version=%s\n' "$version"
  printf 'commit=%s\n' "$commit"
  printf 'implementation_commit=%s\n' \
    'acf16b5fc044484c06ab13042843669680733e71'
  printf 'chibios_upstream_commit=%s\n' \
    'f4bbadf964fc746aef8bbcf34135c7d8fabb8eae'
  printf 'chibios_commit=%s\n' "$chibios_commit"
  printf 'source_date_epoch=%s\n' "$source_date_epoch"
  printf 'compiler=%s\n' "$(arm-none-eabi-gcc --version | sed -n '1p')"
  printf 'double_helper_calls=%s\n' "$double_helper_calls"
  printf 'binary_size=%s\n' "$size"
  printf 'binary_sha256=%s\n' "$binary_hash"
  printf 'elf_sha256=%s\n' "$elf_hash"
  printf 'hex_sha256=%s\n' "$hex_hash"
  printf 'reproducible_clean_builds=true\n'
  printf 'hardware_qualified=false\n'
  printf 'simulation_qualification=pending\n'
  printf 'automated_flash=false\n'
} > "$artifact_dir/manifest.txt"

cat > "$artifact_dir/FLASHING.txt" <<EOF
Candidate: $release_id
Hardware: tinySA Ultra+ ZS407 / STM32F303 only
Binary: $stem.bin
SHA-256: $binary_hash

This package is not hardware-qualified until qualification.txt says PASS.
Keep the known-good rollback binary available before flashing.

With the unit already in ROM DFU mode, the explicit flash command is:
  dfu-util -d 0483:df11 -a 0 -s 0x08000000:leave -D $stem.bin

Do not use this image on the F072 target.
EOF

printf 'candidate_build=passed\n'
printf 'artifact_dir=%s\n' "$artifact_dir"
printf 'binary=%s/%s.bin\n' "$artifact_dir" "$stem"
printf 'binary_size=%s\n' "$size"
printf 'binary_sha256=%s\n' "$binary_hash"
