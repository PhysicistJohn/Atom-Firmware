#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$ROOT/tools/lib.sh"
. "$ROOT/release-manifests/v1.4-224-gc979386.env"

ARTIFACTS=${TINYSA_ARTIFACTS_DIR:-"$ROOT/.artifacts"}
destination="$ARTIFACTS/upstream/$RELEASE_ID"
mkdir -p "$destination"

fetch_and_verify() {
  _fetch_name=$1
  _fetch_expected=$2
  _fetch_path="$destination/$_fetch_name"
  download_once "$OFFICIAL_BASE_URL/$_fetch_name" "$_fetch_path"
  verify_sha256 "$_fetch_path" "$_fetch_expected"
}

fetch_and_verify "$RELEASE_BINARY_STEM.bin" "$BIN_SHA256"
fetch_and_verify "$RELEASE_BINARY_STEM.dfu" "$DFU_SHA256"
fetch_and_verify "$RELEASE_BINARY_STEM.elf" "$ELF_SHA256"
fetch_and_verify "$RELEASE_BINARY_STEM.hex" "$HEX_SHA256"
fetch_and_verify 'changelog.txt' "$CHANGELOG_SHA256"

printf '%s\n' "$destination"
