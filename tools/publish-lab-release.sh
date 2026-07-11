#!/usr/bin/env bash
set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
repo=PhysicistJohn/TinySA_Firmware
origin=https://github.com/PhysicistJohn/TinySA_Firmware.git

usage() {
  printf 'Usage: %s [--dry-run] v0.2.0\n' "$0"
  printf 'Publish the committed no-flash laboratory image as a private prerelease.\n'
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
[[ $(value hardware_qualified) == false ]] || { printf 'error: qualification flag\n' >&2; exit 1; }
[[ $(value binary_transport_enabled) == false ]] || { printf 'error: transport flag\n' >&2; exit 1; }
[[ $(value automated_flash) == false ]] || { printf 'error: flash flag\n' >&2; exit 1; }

stem="tinySA4_${release}_protocol-v2"
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
