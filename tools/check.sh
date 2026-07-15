#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$ROOT/tools/lib.sh"

usage() {
  printf 'Usage: %s [--boundary] [--host] [--firmware]\n' "$0"
  printf 'With no selection, run every deterministic check that needs no device.\n'
}

run_boundary=false
run_host=false
run_firmware=false
if [ "$#" -eq 0 ]; then
  run_boundary=true
  run_host=true
  run_firmware=true
fi
while [ "$#" -gt 0 ]; do
  case "$1" in
    --boundary) run_boundary=true ;;
    --host) run_host=true ;;
    --firmware) run_firmware=true ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; die "unknown check selection: $1" ;;
  esac
  shift
done

python=${PYTHON:-python3}
command -v "$python" >/dev/null 2>&1 || die "Python interpreter not found: $python"

if [ "$run_boundary" = true ]; then
  for test_file in \
    test-flasher-build-manifest.py \
    test-firmware-update-boundary.py \
    test-physical-dfu-flash-evidence.py \
    test-physical-qualification-bundle.py \
    test-physical-reset-retention.py \
    test-physical-selftest-capture.py \
    test-physical-selftest-negative.py \
    test-physical-selftest-spur-persistence.py \
    test-physical-usb-runtime.py \
    test-selftest-visual-comparator.py
  do
    "$python" "$ROOT/tools/$test_file"
  done
fi

if [ "$run_host" = true ]; then
  command -v node >/dev/null 2>&1 || \
    die 'Node is required for the generated JavaScript contract check'
  [ -x "$ROOT/node_modules/.bin/tsc" ] || \
    die 'TypeScript is not installed; run npm ci from the repository root'
  PATH="$ROOT/node_modules/.bin:$PATH"
  export PATH
  if [ "${ZS407_REQUIRE_PROJECTION_TOOLCHAINS:-0}" = 1 ]; then
    expected_node="v$(sed -n '1p' "$ROOT/.node-version")"
    actual_node=$(node --version)
    [ "$actual_node" = "$expected_node" ] || \
      die "Node version mismatch (expected $expected_node, got $actual_node)"
    [ "$(npm --version)" = 10.9.8 ] || \
      die "npm version mismatch (expected 10.9.8, got $(npm --version))"
  fi
  ZS407_RUN_ASAN=${ZS407_RUN_ASAN:-1}
  export ZS407_RUN_ASAN
  "$ROOT/tools/test-host-core.sh"
fi

if [ "$run_firmware" = true ]; then
  "$ROOT/tools/check-firmware-build.sh"
fi

printf 'Deterministic no-device checks: passed\n'
