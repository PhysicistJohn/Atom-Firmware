#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$ROOT/tools/lib.sh"

exact=false
clean=true
jobs=${JOBS:-$(host_jobs)}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --exact) exact=true ;;
    --no-clean) clean=false ;;
    --jobs)
      [ "$#" -ge 2 ] || die '--jobs requires a number'
      jobs=$2
      shift
      ;;
    -h|--help)
      printf 'Usage: %s [--exact] [--no-clean] [--jobs N]\n' "$0"
      exit 0
      ;;
    *) die "unknown argument $1" ;;
  esac
  shift
done

toolchain_bin=$($ROOT/tools/bootstrap-toolchain.sh)
export PATH="$toolchain_bin:$PATH"
export LC_ALL=C

git -C "$ROOT" submodule status ChibiOS | grep -q '^ ' || die 'initialize ChibiOS with: git submodule update --init --recursive'

if [ "$clean" = true ]; then
  make -C "$ROOT" TARGET=F303 clean >/dev/null
fi

if [ "$exact" = true ]; then
  . "$ROOT/release-manifests/v1.4-224-gc979386.env"
  library_paths=$($ROOT/tools/bootstrap-repro-libs.sh)
  gcc_lib=$(printf '%s\n' "$library_paths" | sed -n '1p')
  target_lib=$(printf '%s\n' "$library_paths" | sed -n '2p')
  export SOURCE_DATE_EPOCH
  make -C "$ROOT" TARGET=F303 VERSION="$RELEASE_BINARY_STEM" \
    ULIBDIR="$gcc_lib $target_lib" -j"$jobs"
else
  make -C "$ROOT" TARGET=F303 -j"$jobs"
fi

binary="$ROOT/build/tinySA4.bin"
[ -f "$binary" ] || die 'build did not produce build/tinySA4.bin'
[ "$(wc -c < "$binary" | tr -d ' ')" -le 245760 ] || die 'firmware exceeds the 240 KiB application flash region'
strings "$binary" | grep -Fq '+ ZS407' || die 'firmware does not contain the ZS407 hardware identity'

actual=$(sha256_file "$binary")
printf 'Built %s bytes\nSHA-256 %s\n' "$(wc -c < "$binary" | tr -d ' ')" "$actual"

if [ "$exact" = true ]; then
  [ "$actual" = "$BIN_SHA256" ] || die "exact build differs from official release $RELEASE_ID"
  printf 'Exact official binary reproduced.\n'
fi
