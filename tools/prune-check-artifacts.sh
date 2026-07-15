#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$ROOT/tools/lib.sh"

if [ "$#" -ne 1 ] || [ "$1" != --confirm ]; then
  printf 'Usage: %s --confirm\n' "$0" >&2
  printf 'Deletes only build/ and .artifacts/host-tests/.\n' >&2
  exit 2
fi

for path in "$ROOT/build" "$ROOT/.artifacts/host-tests"; do
  [ ! -L "$path" ] || die "refusing to remove symbolic link: $path"
  if [ -e "$path" ]; then
    rm -rf -- "$path"
    printf 'Removed %s\n' "$path"
  fi
done

printf 'Preserved all firmware packages, releases, toolchains, and qualification evidence.\n'
