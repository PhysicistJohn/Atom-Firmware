#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$ROOT/tools/lib.sh"
. "$ROOT/release-manifests/v1.4-224-gc979386.env"

ARTIFACTS=${TINYSA_ARTIFACTS_DIR:-"$ROOT/.artifacts"}
release_directory=$($ROOT/tools/fetch-official-release.sh)
toolchain_bin=$($ROOT/tools/bootstrap-toolchain.sh)
elf="$release_directory/$RELEASE_BINARY_STEM.elf"
binary="$release_directory/$RELEASE_BINARY_STEM.bin"
report="$ARTIFACTS/reports/$RELEASE_ID"
mkdir -p "$report"

"$toolchain_bin/arm-none-eabi-readelf" -a "$elf" > "$report/readelf.txt"
"$toolchain_bin/arm-none-eabi-readelf" --debug-dump=info "$elf" > "$report/dwarf-info.txt"
"$toolchain_bin/arm-none-eabi-objdump" -dS "$elf" > "$report/disassembly-with-source.txt"
"$toolchain_bin/arm-none-eabi-nm" -nS "$elf" > "$report/symbols.txt"
strings -a "$binary" > "$report/strings.txt"

printf 'ELF: %s\n' "$elf"
printf 'Entry point: '
"$toolchain_bin/arm-none-eabi-readelf" -h "$elf" | awk -F: '/Entry point address/ {gsub(/^[ \t]+/, "", $2); print $2}'
printf 'Reports: %s\n' "$report"
