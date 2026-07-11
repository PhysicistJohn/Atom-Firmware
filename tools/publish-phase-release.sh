#!/usr/bin/env bash
set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
repo=PhysicistJohn/TinySA_Firmware
origin=https://github.com/PhysicistJohn/TinySA_Firmware.git

usage() {
  printf 'Usage: %s [--dry-run] PHASE\n' "$0"
  printf 'Publish an existing phase image as a private GitHub prerelease.\n'
}

dry_run=false
if [[ ${1:-} == --dry-run ]]; then
  dry_run=true
  shift
fi
[[ $# -eq 1 && $1 =~ ^[0-6]$ ]] || { usage >&2; exit 2; }
phase=$1

branches=(
  physicistjohn/phase-0-build-safety
  physicistjohn/phase-1-host-core
  physicistjohn/phase-2-deterministic-firmware
  physicistjohn/phase-3-dsp-ui
  physicistjohn/phase-4-rf-experiments
  physicistjohn/phase-5-waveform-generator
  physicistjohn/phase-6-final-integration
)
tags=(
  phase-0-build-safety
  phase-1-host-core
  phase-2-deterministic-firmware
  phase-3-dsp-ui
  phase-4-rf-experiments
  phase-5-waveform-generator
  phase-6-final-integration
)
branch=${branches[$phase]}
tag=${tags[$phase]}

[[ $(git -C "$ROOT" remote get-url origin) == "$origin" ]] || {
  printf 'error: origin URL mismatch\n' >&2
  exit 1
}
[[ $(git -C "$ROOT" remote get-url --push upstream) == no_push ]] || {
  printf 'error: upstream is not fetch-only\n' >&2
  exit 1
}
[[ $(gh api user --jq .login) == PhysicistJohn ]] || {
  printf 'error: GitHub login is not PhysicistJohn\n' >&2
  exit 1
}
[[ $(gh api "repos/$repo" --jq .private) == true ]] || {
  printf 'error: target repository is not private\n' >&2
  exit 1
}

"$ROOT/tools/audit-phase-chain.py" --through "$phase" --github

commit=$(git -C "$ROOT" rev-list -n1 "$tag")
[[ $(git -C "$ROOT" rev-parse "$branch") == "$commit" ]] || {
  printf 'error: tag is not the phase branch tip\n' >&2
  exit 1
}
[[ $(git -C "$ROOT" ls-remote origin "refs/heads/$branch" | awk '{print $1}') == "$commit" ]] || {
  printf 'error: remote phase branch is missing or stale\n' >&2
  exit 1
}
[[ $(git -C "$ROOT" ls-remote origin "refs/tags/$tag^{}" | awk '{print $1}') == "$commit" ]] || {
  printf 'error: remote annotated phase tag is missing or stale\n' >&2
  exit 1
}
artifact_dir="$ROOT/.artifacts/phase-images/phase-$phase/$commit"
manifest="$artifact_dir/manifest.txt"
[[ -f $manifest ]] || { printf 'error: missing phase manifest\n' >&2; exit 1; }

value() {
  sed -n "s/^$1=//p" "$manifest" | sed -n '1p'
}
size=$(value binary_size)
hash=$(value binary_sha256)
version=$(value version)
notes=$(printf '%s\n\n%s\n%s\n%s\n%s\n\n%s\n' \
  "Cumulative Phase $phase image for the tinySA Ultra+ ZS407 research fork." \
  "Version: $version" \
  "Commit: $commit" \
  "Binary size: $size bytes" \
  "SHA-256: $hash" \
  'WARNING: NOT HARDWARE QUALIFIED. DO NOT FLASH before the documented physical baseline, recovery, and RF/output gates are complete.')
title="Phase $phase — NO FLASH / hardware-unqualified"

assets=(
  "$artifact_dir/tinySA4_phase-$phase.bin"
  "$artifact_dir/tinySA4_phase-$phase.elf"
  "$artifact_dir/tinySA4_phase-$phase.hex"
  "$artifact_dir/manifest.txt"
  "$artifact_dir/sections.txt"
  "$artifact_dir/stack-usage.txt"
)
if [[ -f $artifact_dir/output-gate-audit.txt ]]; then
  assets+=("$artifact_dir/output-gate-audit.txt")
fi
if [[ $phase -eq 6 && -f $ROOT/.artifacts/final-audit/PHASE_MATRIX.md ]]; then
  assets+=("$ROOT/.artifacts/final-audit/PHASE_MATRIX.md")
fi
for asset in "${assets[@]}"; do
  [[ -f $asset ]] || { printf 'error: missing release asset %s\n' "$asset" >&2; exit 1; }
done

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
