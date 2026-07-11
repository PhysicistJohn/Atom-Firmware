#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$ROOT/tools/lib.sh"

ARTIFACTS=${TINYSA_ARTIFACTS_DIR:-"$ROOT/.artifacts"}
BASE_URL='https://developer.arm.com/-/media/Files/downloads/gnu/11.3.rel1/binrel'
os=$(uname -s)
arch=$(uname -m)

case "$os:$arch" in
  Darwin:arm64|Darwin:x86_64)
    archive='arm-gnu-toolchain-11.3.rel1-darwin-x86_64-arm-none-eabi.tar.xz'
    expected='826353d45e7fbaa9b87c514e7c758a82f349cb7fc3fd949423687671539b29cf'
    if [ "$arch" = arm64 ] && ! /usr/bin/arch -x86_64 /usr/bin/true >/dev/null 2>&1; then
      die 'Arm GNU 11.3.Rel1 is Intel-only on macOS; install Rosetta 2 first'
    fi
    ;;
  Linux:x86_64)
    archive='arm-gnu-toolchain-11.3.rel1-x86_64-arm-none-eabi.tar.xz'
    expected='d420d87f68615d9163b99bbb62fe69e85132dc0a8cd69fca04e813597fe06121'
    ;;
  Linux:aarch64|Linux:arm64)
    archive='arm-gnu-toolchain-11.3.rel1-aarch64-arm-none-eabi.tar.xz'
    expected='6c713c11d018dcecc16161f822517484a13af151480bbb722badd732412eb55e'
    ;;
  *)
    die "unsupported build host $os/$arch"
    ;;
esac

archive_path="$ARTIFACTS/toolchains/$archive"
directory="$ARTIFACTS/toolchains/${archive%.tar.xz}"
compiler="$directory/bin/arm-none-eabi-gcc"

if [ ! -x "$compiler" ]; then
  download_once "$BASE_URL/$archive" "$archive_path"
  verify_sha256 "$archive_path" "$expected"
  printf 'Extracting %s\n' "$archive" >&2
  tar -xJf "$archive_path" -C "$ARTIFACTS/toolchains"
fi

version=$($compiler -dumpfullversion)
[ "$version" = '11.3.1' ] || die "unexpected compiler version $version"
printf '%s\n' "$directory/bin"
