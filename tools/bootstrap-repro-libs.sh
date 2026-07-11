#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$ROOT/tools/lib.sh"
. "$ROOT/release-manifests/v1.4-224-gc979386.env"

ARTIFACTS=${TINYSA_ARTIFACTS_DIR:-"$ROOT/.artifacts"}
BASE_URL='https://developer.arm.com/-/media/Files/downloads/gnu/11.3.rel1/binrel'
archive_path="$ARTIFACTS/toolchains/$WINDOWS_TOOLCHAIN_ARCHIVE"
package=${WINDOWS_TOOLCHAIN_ARCHIVE%.zip}
destination="$ARTIFACTS/toolchains/windows-target-libs"
package_root="$destination/$package"
gcc_lib="$package_root/lib/gcc/arm-none-eabi/11.3.1/thumb/v7e-m+fp/hard"
target_lib="$package_root/arm-none-eabi/lib/thumb/v7e-m+fp/hard"

if [ ! -f "$gcc_lib/libgcc.a" ] || [ ! -f "$target_lib/libm.a" ]; then
  command -v unzip >/dev/null 2>&1 || die 'unzip is required for the exact-reproduction libraries'
  download_once "$BASE_URL/$WINDOWS_TOOLCHAIN_ARCHIVE" "$archive_path"
  verify_sha256 "$archive_path" "$WINDOWS_TOOLCHAIN_SHA256"
  printf 'Extracting Cortex-M4 target libraries from %s\n' "$WINDOWS_TOOLCHAIN_ARCHIVE" >&2
  rm -rf "$package_root"
  unzip -q "$archive_path" \
    "$package/arm-none-eabi/lib/thumb/v7e-m+fp/hard/*" \
    "$package/lib/gcc/arm-none-eabi/11.3.1/thumb/v7e-m+fp/hard/*" \
    -d "$destination"
fi

[ -f "$gcc_lib/libc_nano.a" ] || die 'Windows libc_nano.a was not extracted'
[ -f "$target_lib/libm.a" ] || die 'Windows libm.a was not extracted'
printf '%s\n%s\n' "$gcc_lib" "$target_lib"
