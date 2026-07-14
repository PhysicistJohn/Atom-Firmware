#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$ROOT/tools/lib.sh"

ARTIFACTS=${TINYSA_ARTIFACTS_DIR:-"$ROOT/.artifacts"}
VERSION=1.16.1
BASE_URL="https://github.com/renode/renode/releases/download/v$VERSION"
TOOL_ROOT="$ARTIFACTS/toolchains/renode-$VERSION"
RUNTIME="$TOOL_ROOT/runtime"

execution_runtime() {
  if [ "$os" != Darwin ]; then
    printf '%s\n' "$RUNTIME"
    return
  fi

  # On current macOS releases a downloaded self-contained .NET app can remain
  # parked in dyld before main() when launched from the artifact cache, even
  # after its checksum and embedded ad-hoc signature have been validated.
  # A locally signed launcher in the per-user temporary directory avoids that
  # policy edge while all Renode data directories remain pinned symlinks.
  staged="${TMPDIR:-/tmp}/tinysa-renode-$VERSION-$(id -u)"
  mkdir -p "$staged"
  mkdir -p "$staged/dotnet-bundle"
  mkdir -p "$staged/home"
  cp "$RUNTIME/renode" "$staged/renode"
  cp "$RUNTIME/.renode-root" "$staged/.renode-root"
  for directory in platforms tools licenses plugins tests scripts; do
    ln -sfn "$RUNTIME/$directory" "$staged/$directory"
  done
  xattr -cr "$staged/renode"
  codesign --force --sign - "$staged/renode" >/dev/null 2>&1
  printf '%s\n' "$staged"
}

os=$(uname -s)
arch=$(uname -m)

case "$os:$arch" in
  Darwin:arm64)
    archive="renode-$VERSION-dotnet.osx-arm64-portable.dmg"
    expected='99b8ae5897b8926ef179868d39a504fe5296555dc9c9b973718ddf3ab09175d9'
    ;;
  Linux:x86_64)
    archive="renode-$VERSION.linux-portable-dotnet.tar.gz"
    expected='00e113cdbd0f5354cf2f64bbe3f5a070d8958409542fca66e45ac97d982938c0'
    ;;
  Linux:aarch64|Linux:arm64)
    archive="renode-$VERSION.linux-arm64-portable-dotnet.tar.gz"
    expected='fff3a098c96ed0a4ffbdff3f028c9c5fde432db09587c7bd7c99406180f90007'
    ;;
  *)
    die "Renode $VERSION bootstrap does not support $os/$arch"
    ;;
esac

if [ -x "$RUNTIME/renode" ]; then
  EXECUTION_RUNTIME=$(execution_runtime)
  actual_version=$(DOTNET_BUNDLE_EXTRACT_BASE_DIR="$EXECUTION_RUNTIME/dotnet-bundle" \
    $EXECUTION_RUNTIME/renode --version | sed -n '1s/^Renode v\([^ ]*\).*/\1/p')
  [ "$actual_version" = "$VERSION.16858" ] || \
    die "unexpected cached Renode version $actual_version"
  printf '%s\n' "$EXECUTION_RUNTIME"
  exit 0
fi

archive_path="$TOOL_ROOT/$archive"
mkdir -p "$TOOL_ROOT"
download_once "$BASE_URL/$archive" "$archive_path"
verify_sha256 "$archive_path" "$expected"

temporary="$TOOL_ROOT/runtime.part"
rm -rf "$temporary"
mkdir -p "$temporary"

case "$os" in
  Darwin)
    mountpoint="$TOOL_ROOT/mount"
    rm -rf "$mountpoint"
    mkdir -p "$mountpoint"
    device=''
    cleanup_mount() {
      if [ -n "$device" ]; then
        hdiutil detach "$device" >/dev/null 2>&1 || true
      fi
      rm -rf "$mountpoint"
    }
    trap cleanup_mount EXIT HUP INT TERM
    attach_output=$(hdiutil attach -nobrowse -readonly -mountpoint "$mountpoint" "$archive_path")
    device=$(printf '%s\n' "$attach_output" | awk '/^\/dev\/disk/{print $1; exit}')
    [ -x "$mountpoint/Renode.app/Contents/MacOS/renode" ] || \
      die 'mounted Renode image does not contain the expected runtime'
    ditto "$mountpoint/Renode.app/Contents/MacOS" "$temporary"
    cleanup_mount
    trap - EXIT HUP INT TERM
    ;;
  Linux)
    tar -xzf "$archive_path" -C "$temporary" --strip-components=1
    ;;
esac

[ -x "$temporary/renode" ] || die 'extracted Renode runtime is incomplete'
mv "$temporary" "$RUNTIME"

EXECUTION_RUNTIME=$(execution_runtime)
actual_version=$(DOTNET_BUNDLE_EXTRACT_BASE_DIR="$EXECUTION_RUNTIME/dotnet-bundle" \
  $EXECUTION_RUNTIME/renode --version | sed -n '1s/^Renode v\([^ ]*\).*/\1/p')
[ "$actual_version" = "$VERSION.16858" ] || \
  die "unexpected Renode version $actual_version"

printf '%s\n' "$EXECUTION_RUNTIME"
