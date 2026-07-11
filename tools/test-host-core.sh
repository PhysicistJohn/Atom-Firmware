#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$ROOT/tools/lib.sh"

export LC_ALL=C
host_cc=${CC:-clang}
command -v "$host_cc" >/dev/null 2>&1 || die "host compiler not found: $host_cc"

"$ROOT/tools/generate-contracts.py" --check

build_dir="$ROOT/.artifacts/host-tests"
rm -rf "$build_dir"
mkdir -p "$build_dir/arm"

common_flags='-std=c11 -Wall -Wextra -Werror -Wpedantic -Wshadow -Wconversion'
sanitizer_flags='-fsanitize=undefined -fno-omit-frame-pointer'

# shellcheck disable=SC2086
"$host_cc" $common_flags $sanitizer_flags -O2 -I"$ROOT" \
  "$ROOT/modern/core/zs407_core.c" \
  "$ROOT/modern/core/zs407_protocol.c" \
  "$ROOT/tests/host/test_core.c" \
  -o "$build_dir/test_core"

"$build_dir/test_core" "$ROOT/tests/fixtures/protocol_v1_capabilities.hex"

# Apple Clang's ASan runtime can deadlock during dyld initialization on some
# newer macOS/toolchain combinations. Always prove the ASan-instrumented binary
# links; run it only when explicitly requested on a known-good host.
# shellcheck disable=SC2086
"$host_cc" $common_flags -fsanitize=address -fno-omit-frame-pointer -O1 \
  -I"$ROOT" "$ROOT/modern/core/zs407_core.c" \
  "$ROOT/modern/core/zs407_protocol.c" "$ROOT/tests/host/test_core.c" \
  -o "$build_dir/test_core_asan"
asan_status=linked-not-run
if [ "${ZS407_RUN_ASAN:-0}" = 1 ]; then
  "$build_dir/test_core_asan" \
    "$ROOT/tests/fixtures/protocol_v1_capabilities.hex"
  asan_status=passed
fi

gnu_bin=$($ROOT/tools/bootstrap-toolchain.sh)
for source in zs407_core zs407_protocol; do
  "$gnu_bin/arm-none-eabi-gcc" $common_flags -ffreestanding -fno-builtin \
    -mcpu=cortex-m4 -mthumb -I"$ROOT" \
    -c "$ROOT/modern/core/$source.c" -o "$build_dir/arm/$source.o"
done

if command -v swiftc >/dev/null 2>&1; then
  swiftc -typecheck "$ROOT/modern/generated/ZS407Contract.swift"
  swift_status=passed
else
  swift_status=not-installed
fi

printf 'Host compiler: %s\n' "$("$host_cc" --version | sed -n '1p')"
printf 'Native UBSan tests: passed\n'
printf 'Native ASan binary: %s\n' "$asan_status"
printf 'Cortex-M4 freestanding compile: passed\n'
printf 'Swift contract typecheck: %s\n' "$swift_status"
