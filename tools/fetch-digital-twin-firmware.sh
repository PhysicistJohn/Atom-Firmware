#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$ROOT/tools/lib.sh"

repo=PhysicistJohn/TinySA_Firmware
tag=lab-v0.2.0-protocol
commit=d12bd826555eee51505542a55fd184ade5817d58
stem=tinySA4_v0.2.0_protocol-v2
artifact_dir="$ROOT/.artifacts/lab-releases/v0.2.0/$commit"
binary="$artifact_dir/$stem.bin"
elf="$artifact_dir/$stem.elf"
manifest="$artifact_dir/manifest.txt"
binary_hash=a1dbaa03978a25b2a8b2a0e85f60029a6cc736481732eff68e93362724683dd7
elf_hash=3a8732fcaac5595e8ad21fe656ecb7e7300a12a760f453c3c1c296b733f72f43

verify() {
  [ -f "$binary" ] || return 1
  [ -f "$elf" ] || return 1
  [ "$(wc -c < "$binary" | tr -d ' ')" = 207812 ] || \
    die 'digital-twin firmware has the wrong size'
  verify_sha256 "$binary" "$binary_hash"
  verify_sha256 "$elf" "$elf_hash"
}

if ! verify; then
  command -v gh >/dev/null 2>&1 || \
    die "missing exact twin image; install gh and authenticate as PhysicistJohn"
  [ "$(gh api user --jq .login)" = PhysicistJohn ] || \
    die 'the private twin image can only be fetched with PhysicistJohn credentials'

  mkdir -p "$artifact_dir"
  temporary="$artifact_dir/download.part"
  rm -rf "$temporary"
  mkdir -p "$temporary"
  trap 'rm -rf "$temporary"' EXIT HUP INT TERM
  gh release download "$tag" --repo "$repo" --dir "$temporary" \
    --pattern "$stem.bin" --pattern "$stem.elf" --pattern manifest.txt
  mv "$temporary/$stem.bin" "$binary"
  mv "$temporary/$stem.elf" "$elf"
  mv "$temporary/manifest.txt" "$manifest"
  rm -rf "$temporary"
  trap - EXIT HUP INT TERM
  verify
fi

printf 'binary=%s\n' "$binary"
printf 'elf=%s\n' "$elf"
printf 'commit=%s\n' "$commit"
printf 'binary_sha256=%s\n' "$binary_hash"
printf 'elf_sha256=%s\n' "$elf_hash"
