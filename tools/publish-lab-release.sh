#!/usr/bin/env bash
set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$ROOT/tools/lib.sh"
repo=PhysicistJohn/TinySA_Firmware
origin=https://github.com/PhysicistJohn/TinySA_Firmware.git

usage() {
  printf 'Usage: %s [--dry-run] v0.2.0\n' "$0"
  printf 'Historical only: publish the archived laboratory image to the retired private repository.\n'
}

dry_run=false
if [[ ${1:-} == --dry-run ]]; then
  dry_run=true
  shift
fi
[[ $# -eq 1 && $1 == v0.2.0 ]] || { usage >&2; exit 2; }
release=$1
branch=physicistjohn/release-v0.2-protocol-marshalling
tag=lab-v0.2.0-protocol

[[ $(git -C "$ROOT" remote get-url origin) == "$origin" ]] || {
  printf 'error: origin URL mismatch\n' >&2; exit 1;
}
[[ $(git -C "$ROOT" remote get-url --push upstream) == no_push ]] || {
  printf 'error: upstream is not fetch-only\n' >&2; exit 1;
}
[[ $(gh api user --jq .login) == PhysicistJohn ]] || {
  printf 'error: GitHub login is not PhysicistJohn\n' >&2; exit 1;
}
[[ $(gh api "repos/$repo" --jq .private) == true ]] || {
  printf 'error: target repository is not private\n' >&2; exit 1;
}

commit=$(git -C "$ROOT" rev-list -n1 "$tag")
[[ $(git -C "$ROOT" rev-parse "$branch") == "$commit" ]] || {
  printf 'error: tag is not the release branch tip\n' >&2; exit 1;
}
[[ $(git -C "$ROOT" ls-remote origin "refs/heads/$branch" | awk '{print $1}') == "$commit" ]] || {
  printf 'error: remote release branch is missing or stale\n' >&2; exit 1;
}
[[ $(git -C "$ROOT" ls-remote origin "refs/tags/$tag^{}" | awk '{print $1}') == "$commit" ]] || {
  printf 'error: remote annotated tag is missing or stale\n' >&2; exit 1;
}

artifact_dir="$ROOT/.artifacts/lab-releases/$release/$commit"
manifest="$artifact_dir/manifest.txt"
[[ -f $manifest ]] || { printf 'error: missing release manifest\n' >&2; exit 1; }
value() { sed -n "s/^$1=//p" "$manifest" | sed -n '1p'; }
[[ $(value commit) == "$commit" ]] || { printf 'error: manifest commit\n' >&2; exit 1; }
[[ $(value profile) == protocol-v2 ]] || { printf 'error: manifest profile\n' >&2; exit 1; }
[[ $(value reproducible_clean_builds) == true ]] || { printf 'error: reproducibility flag\n' >&2; exit 1; }
[[ $(value official_exact_reproduction) == passed ]] || { printf 'error: official regression\n' >&2; exit 1; }
[[ $(value f072_reproducible_clean_builds) == true ]] || { printf 'error: F072 reproducibility\n' >&2; exit 1; }
[[ $(value hardware_qualified) == false ]] || { printf 'error: qualification flag\n' >&2; exit 1; }
[[ $(value binary_transport_enabled) == false ]] || { printf 'error: transport flag\n' >&2; exit 1; }
[[ $(value automated_flash) == false ]] || { printf 'error: flash flag\n' >&2; exit 1; }

stem="tinySA4_${release}_protocol-v2"
[[ $(wc -c < "$artifact_dir/$stem.bin" | tr -d ' ') == $(value binary_size) ]] || {
  printf 'error: binary size does not match manifest\n' >&2; exit 1;
}
[[ $(sha256_file "$artifact_dir/$stem.bin") == $(value binary_sha256) ]] || {
  printf 'error: binary hash does not match manifest\n' >&2; exit 1;
}
[[ $(sha256_file "$artifact_dir/$stem.elf") == $(value elf_sha256) ]] || {
  printf 'error: ELF hash does not match manifest\n' >&2; exit 1;
}
[[ $(sha256_file "$artifact_dir/$stem.hex") == $(value hex_sha256) ]] || {
  printf 'error: HEX hash does not match manifest\n' >&2; exit 1;
}
[[ $(sha256_file "$artifact_dir/protocol-v2-benchmark.txt") == $(value benchmark_sha256) ]] || {
  printf 'error: benchmark hash does not match manifest\n' >&2; exit 1;
}
[[ $(sha256_file "$artifact_dir/official-reproduction.txt") == $(value official_report_sha256) ]] || {
  printf 'error: official report hash does not match manifest\n' >&2; exit 1;
}
[[ $(sha256_file "$artifact_dir/f072-build.txt") == $(value f072_report_sha256) ]] || {
  printf 'error: F072 report hash does not match manifest\n' >&2; exit 1;
}
grep -Fq 'output_lock=passed' "$artifact_dir/output-gate-audit.txt" || {
  printf 'error: output lock report failed\n' >&2; exit 1;
}
grep -Fq 'protocol_v2_lock_audit=passed' "$artifact_dir/protocol-v2-lock-audit.txt" || {
  printf 'error: transport lock report failed\n' >&2; exit 1;
}
grep -Fq 'Exact official binary reproduced.' "$artifact_dir/official-reproduction.txt" || {
  printf 'error: official reproduction report failed\n' >&2; exit 1;
}
grep -Fq 'f072_regression=passed' "$artifact_dir/f072-build.txt" || {
  printf 'error: F072 build report failed\n' >&2; exit 1;
}
assets=(
  "$artifact_dir/$stem.bin"
  "$artifact_dir/$stem.elf"
  "$artifact_dir/$stem.hex"
  "$artifact_dir/manifest.txt"
  "$artifact_dir/sections.txt"
  "$artifact_dir/stack-usage.txt"
  "$artifact_dir/host-tests.txt"
  "$artifact_dir/official-reproduction.txt"
  "$artifact_dir/f072-build.txt"
  "$artifact_dir/protocol-v2-benchmark.txt"
  "$artifact_dir/output-gate-audit.txt"
  "$artifact_dir/protocol-v2-lock-audit.txt"
)
for asset in "${assets[@]}"; do
  [[ -f $asset ]] || { printf 'error: missing asset %s\n' "$asset" >&2; exit 1; }
done

hash=$(value binary_sha256)
size=$(value binary_size)
heap=$(value heap_bytes)
version=$(value version)
notes=$(printf '%s\n\n%s\n%s\n%s\n%s\n%s\n\n%s\n' \
  'Protocol v2 and marshalling laboratory image for tinySA Ultra+ ZS407.' \
  "Version: $version" "Commit: $commit" "Binary size: $size bytes" \
  "Remaining heap: $heap bytes" "SHA-256: $hash" \
  'WARNING: NO FLASH / NOT HARDWARE QUALIFIED. Binary transport, hardware CRC default, RF experiments and waveform output remain locked.')
title='Lab v0.2.0 — Protocol v2 — NO FLASH / hardware-unqualified'

if [[ $dry_run == true ]]; then
  printf 'Private prerelease dry run passed: %s (%s), %s assets\n' \
    "$tag" "$hash" "${#assets[@]}"
  exit 0
fi

if gh release view "$tag" --repo "$repo" >/dev/null 2>&1; then
  gh release edit "$tag" --repo "$repo" --title "$title" \
    --notes "$notes" --prerelease
  gh release upload "$tag" --repo "$repo" --clobber "${assets[@]}"
else
  gh release create "$tag" --repo "$repo" --verify-tag --prerelease \
    --title "$title" --notes "$notes" "${assets[@]}"
fi

gh release view "$tag" --repo "$repo" \
  --json tagName,isPrerelease,url,assets \
  --jq '{tag:.tagName,prerelease:.isPrerelease,url:.url,assets:(.assets | length)}'
