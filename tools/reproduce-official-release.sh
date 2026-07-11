#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$ROOT/tools/lib.sh"
. "$ROOT/release-manifests/v1.4-224-gc979386.env"

git -C "$ROOT" merge-base --is-ancestor "$SOURCE_COMMIT" HEAD || \
  die "the official source commit $SOURCE_COMMIT is not in this branch"
[ "$(git -C "$ROOT/ChibiOS" rev-parse HEAD)" = "$CHIBIOS_COMMIT" ] || \
  die "ChibiOS is not pinned to $CHIBIOS_COMMIT"

official_directory=$($ROOT/tools/fetch-official-release.sh)
$ROOT/tools/build-zs407.sh --exact

official="$official_directory/$RELEASE_BINARY_STEM.bin"
built="$ROOT/build/tinySA4.bin"
cmp -s "$official" "$built" || die 'hash matched the manifest but byte comparison failed'

printf 'Reproduced %s byte-for-byte from source.\n' "$RELEASE_BINARY_STEM.bin"
