#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$ROOT/tools/lib.sh"

export LC_ALL=C
host_cc=${CC:-clang}
command -v "$host_cc" >/dev/null 2>&1 || die "host compiler not found: $host_cc"

"$ROOT/tools/generate-contracts.py" --check
"$ROOT/tools/generate-waveform-tables.py" --check
"$ROOT/tools/compile-waveform.py" --self-test
"$ROOT/tools/audit-enhancement-dispositions.py"
"$ROOT/tools/audit-document-links.py"

build_dir="$ROOT/.artifacts/host-tests"
rm -rf "$build_dir"
mkdir -p "$build_dir/arm"

common_flags='-std=c11 -Wall -Wextra -Werror -Wpedantic -Wshadow -Wconversion'
sanitizer_flags='-fsanitize=undefined -fno-omit-frame-pointer'

# shellcheck disable=SC2086
"$host_cc" $common_flags $sanitizer_flags -O2 -I"$ROOT" \
  "$ROOT/modern/core/zs407_core.c" \
  "$ROOT/modern/core/zs407_capabilities.c" \
  "$ROOT/modern/core/zs407_fft.c" \
  "$ROOT/modern/core/zs407_measurements.c" \
  "$ROOT/modern/core/zs407_protocol.c" \
  "$ROOT/modern/core/zs407_rf_lab.c" \
  "$ROOT/modern/core/zs407_services.c" \
  "$ROOT/modern/core/zs407_ui_model.c" \
  "$ROOT/modern/core/zs407_waveform.c" \
  "$ROOT/tests/host/test_core.c" \
  -lm -o "$build_dir/test_core"

"$build_dir/test_core" "$ROOT/tests/fixtures/protocol_v1_capabilities.hex"

# Repeat the numerical suite with the Cortex-M single-precision policy.
# shellcheck disable=SC2086
"$host_cc" $common_flags $sanitizer_flags -DZS407_EMBEDDED_MATH=1 -O2 \
  -I"$ROOT" "$ROOT/modern/core/zs407_core.c" \
  "$ROOT/modern/core/zs407_capabilities.c" \
  "$ROOT/modern/core/zs407_fft.c" \
  "$ROOT/modern/core/zs407_measurements.c" \
  "$ROOT/modern/core/zs407_protocol.c" \
  "$ROOT/modern/core/zs407_rf_lab.c" \
  "$ROOT/modern/core/zs407_services.c" \
  "$ROOT/modern/core/zs407_ui_model.c" "$ROOT/tests/host/test_core.c" \
  "$ROOT/modern/core/zs407_waveform.c" \
  -lm -o "$build_dir/test_core_embedded_math"
"$build_dir/test_core_embedded_math" \
  "$ROOT/tests/fixtures/protocol_v1_capabilities.hex"

# Protocol-v2, fixed-buffer transport primitives and compact storage codecs.
# shellcheck disable=SC2086
"$host_cc" $common_flags $sanitizer_flags -O2 \
  -DZS407_RELEASE_PROTOCOL_V2=1 -I"$ROOT" \
  "$ROOT/modern/core/zs407_core.c" \
  "$ROOT/modern/core/zs407_capabilities.c" \
  "$ROOT/modern/core/zs407_protocol.c" \
  "$ROOT/modern/core/zs407_trace_codec.c" \
  "$ROOT/modern/core/zs407_waveform.c" \
  "$ROOT/modern/core/zs407_compact.c" \
  "$ROOT/modern/core/zs407_spsc.c" \
  "$ROOT/tests/host/test_protocol_v2.c" \
  -lm -o "$build_dir/test_protocol_v2"
"$build_dir/test_protocol_v2" "$ROOT/tests/fixtures"

# Passive acquisition primitives: wrap-safe clocks, non-blocking publication,
# adaptive refinement and triggered 256/1024-point zero-span FFT analysis.
# shellcheck disable=SC2086
"$host_cc" $common_flags $sanitizer_flags -O2 \
  -DZS407_RELEASE_PROTOCOL_V2=1 -DZS407_RELEASE_PASSIVE_V04=1 -I"$ROOT" \
  "$ROOT/modern/core/zs407_core.c" \
  "$ROOT/modern/core/zs407_fft.c" \
  "$ROOT/modern/core/zs407_waveform.c" \
  "$ROOT/modern/core/zs407_passive.c" \
  "$ROOT/tests/host/test_passive.c" -pthread -lm \
  -o "$build_dir/test_passive"
"$build_dir/test_passive"

# Exercise the release/acquire ring under true producer/consumer concurrency.
# shellcheck disable=SC2086
"$host_cc" $common_flags $sanitizer_flags -O2 -I"$ROOT" \
  "$ROOT/modern/core/zs407_core.c" \
  "$ROOT/modern/core/zs407_spsc.c" \
  "$ROOT/tests/host/test_spsc_threaded.c" -pthread \
  -o "$build_dir/test_spsc_threaded"
"$build_dir/test_spsc_threaded"

# Deterministic mutation fuzzing is always available. A libFuzzer entry point
# remains in the same source for hosts that ship the LLVM fuzzer runtime.
# shellcheck disable=SC2086
"$host_cc" $common_flags $sanitizer_flags -O2 \
  -DZS407_STANDALONE_FUZZ=1 -I"$ROOT" \
  "$ROOT/modern/core/zs407_core.c" \
  "$ROOT/modern/core/zs407_protocol.c" \
  "$ROOT/modern/core/zs407_trace_codec.c" \
  "$ROOT/modern/core/zs407_waveform.c" \
  "$ROOT/modern/core/zs407_compact.c" \
  "$ROOT/tests/host/fuzz_protocol_v2.c" -lm \
  -o "$build_dir/fuzz_protocol_v2"
"$build_dir/fuzz_protocol_v2"

# Informational performance evidence; correctness is tested above.
# shellcheck disable=SC2086
"$host_cc" $common_flags -O3 -I"$ROOT" \
  "$ROOT/modern/core/zs407_core.c" \
  "$ROOT/modern/core/zs407_protocol.c" \
  "$ROOT/modern/core/zs407_waveform.c" \
  "$ROOT/modern/core/zs407_compact.c" \
  "$ROOT/tests/host/benchmark_protocol_v2.c" -lm \
  -o "$build_dir/benchmark_protocol_v2"
"$build_dir/benchmark_protocol_v2" \
  > "$build_dir/protocol-v2-benchmark.txt"
sed -n '/./p' "$build_dir/protocol-v2-benchmark.txt"

# Apple Clang's ASan runtime can deadlock during dyld initialization on some
# newer macOS/toolchain combinations. Always prove the ASan-instrumented binary
# links; run it only when explicitly requested on a known-good host.
# shellcheck disable=SC2086
"$host_cc" $common_flags -fsanitize=address -fno-omit-frame-pointer -O1 \
  -I"$ROOT" "$ROOT/modern/core/zs407_core.c" \
  "$ROOT/modern/core/zs407_capabilities.c" \
  "$ROOT/modern/core/zs407_fft.c" \
  "$ROOT/modern/core/zs407_measurements.c" \
  "$ROOT/modern/core/zs407_protocol.c" \
  "$ROOT/modern/core/zs407_rf_lab.c" \
  "$ROOT/modern/core/zs407_services.c" \
  "$ROOT/modern/core/zs407_ui_model.c" \
  "$ROOT/modern/core/zs407_waveform.c" "$ROOT/tests/host/test_core.c" \
  -lm -o "$build_dir/test_core_asan"
asan_status=linked-not-run
if [ "${ZS407_RUN_ASAN:-0}" = 1 ]; then
  "$build_dir/test_core_asan" \
    "$ROOT/tests/fixtures/protocol_v1_capabilities.hex"
  asan_status=passed
fi

gnu_bin=$($ROOT/tools/bootstrap-toolchain.sh)
for source in zs407_capabilities zs407_compact zs407_core zs407_fft \
              zs407_measurements zs407_protocol zs407_rf_lab zs407_services \
              zs407_spsc zs407_trace_codec zs407_ui_model zs407_waveform \
              zs407_passive; do
  "$gnu_bin/arm-none-eabi-gcc" $common_flags -ffreestanding -fno-builtin \
    -DZS407_EMBEDDED_MATH=1 -DZS407_RELEASE_PROTOCOL_V2=1 \
    -DZS407_RELEASE_PASSIVE_V04=1 \
    -mcpu=cortex-m4 -mthumb -I"$ROOT" \
    -c "$ROOT/modern/core/$source.c" -o "$build_dir/arm/$source.o"
done

# Cross-compile the new portable core through LLVM as a second independent
# frontend/code generator. Linking the whole legacy ChibiOS image stays GNU.
llvm_status=not-installed
if command -v clang >/dev/null 2>&1; then
  mkdir -p "$build_dir/arm-llvm"
  gnu_root=$(CDPATH= cd -- "$gnu_bin/.." && pwd)
  for source in zs407_compact zs407_core zs407_protocol zs407_spsc \
                zs407_trace_codec zs407_waveform zs407_fft zs407_passive; do
    clang $common_flags -target arm-none-eabi -mcpu=cortex-m4 -mthumb \
      -ffreestanding -fno-builtin -DZS407_EMBEDDED_MATH=1 \
      -DZS407_RELEASE_PROTOCOL_V2=1 -DZS407_RELEASE_PASSIVE_V04=1 \
      --sysroot="$gnu_root/arm-none-eabi" \
      -I"$ROOT" -c "$ROOT/modern/core/$source.c" \
      -o "$build_dir/arm-llvm/$source.o"
  done
  llvm_status=passed
fi

if command -v swiftc >/dev/null 2>&1; then
  swiftc "$ROOT/modern/generated/ZS407Contract.swift" \
    "$ROOT/tests/host/test_contract.swift" \
    -o "$build_dir/test_swift_contract"
  "$build_dir/test_swift_contract" "$ROOT/tests/fixtures"
  swift_status=passed
else
  swift_status=not-installed
fi

if command -v node >/dev/null 2>&1; then
  node "$ROOT/tests/host/test_contract.mjs" "$ROOT/tests/fixtures"
  javascript_status=passed
else
  javascript_status=not-installed
fi

if command -v tsc >/dev/null 2>&1; then
  tsc --noEmit --strict --target ES2020 --module ES2020 \
    "$ROOT/modern/generated/zs407-contract.ts"
  typescript_status=passed
else
  typescript_status=generated-not-installed
fi

printf 'Host compiler: %s\n' "$("$host_cc" --version | sed -n '1p')"
printf 'Native UBSan tests: passed\n'
printf 'Embedded single-precision policy tests: passed\n'
printf 'Protocol-v2 UBSan tests: passed\n'
printf 'Passive acquisition UBSan/threaded tests: passed\n'
printf 'Protocol mutation fuzz: passed\n'
printf 'SPSC threaded stress: passed\n'
printf 'Native ASan binary: %s\n' "$asan_status"
printf 'Cortex-M4 freestanding compile: passed\n'
printf 'Cortex-M4 LLVM compile: %s\n' "$llvm_status"
printf 'Swift contract typecheck: %s\n' "$swift_status"
printf 'JavaScript contract test: %s\n' "$javascript_status"
printf 'TypeScript contract: %s\n' "$typescript_status"
