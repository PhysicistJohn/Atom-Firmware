#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$ROOT/tools/lib.sh"
. "$ROOT/tools/twin-client-lib.sh"

TINYSA_ARTIFACTS_DIR=${TINYSA_ARTIFACTS_DIR:-"$ROOT/.artifacts"}
export TINYSA_ARTIFACTS_DIR

usage() {
  cat >&2 <<EOF
Usage: $0 --bin FILE --elf FILE --symbols FILE --twin-root DIR --output DIR
          [--runtime DIR] [--toolchain-bin DIR] [--warm-only]
          [--minimum-sweep-stack-free BYTES]
          [--minimum-msp-stack-free BYTES]

Qualify one exact ZS407 candidate in Renode. The run verifies RTC-backed
save -> system reset -> restore behavior. Unless --warm-only is supplied, it
then runs all 14 self-tests, stresses continuous remote redraw over USB CDC,
captures the firmware's "threads" stack watermark, and scans the CRT-filled
MSP interrupt stack.
The exact ELF must expose a 1024-byte MSP region and 6488-byte heap.

The command does not build or flash firmware. DIR receives the generated
scenario, raw/normalized logs, decoded threads output, and report.txt.
EOF
  exit 2
}

binary=
elf=
symbols=
twin_root=
output=
runtime=
toolchain_bin=
warm_only=false
minimum_sweep_stack_free=64
minimum_msp_stack_free=64
expected_msp_size=1024
expected_heap_size=6488

while [ "$#" -gt 0 ]; do
  case "$1" in
    --bin)
      [ "$#" -ge 2 ] || usage
      binary=$2
      shift 2
      ;;
    --elf)
      [ "$#" -ge 2 ] || usage
      elf=$2
      shift 2
      ;;
    --symbols)
      [ "$#" -ge 2 ] || usage
      symbols=$2
      shift 2
      ;;
    --twin-root)
      [ "$#" -ge 2 ] || usage
      twin_root=$2
      shift 2
      ;;
    --output)
      [ "$#" -ge 2 ] || usage
      output=$2
      shift 2
      ;;
    --runtime)
      [ "$#" -ge 2 ] || usage
      runtime=$2
      shift 2
      ;;
    --toolchain-bin)
      [ "$#" -ge 2 ] || usage
      toolchain_bin=$2
      shift 2
      ;;
    --warm-only)
      warm_only=true
      shift
      ;;
    --minimum-sweep-stack-free)
      [ "$#" -ge 2 ] || usage
      minimum_sweep_stack_free=$2
      shift 2
      ;;
    --minimum-msp-stack-free)
      [ "$#" -ge 2 ] || usage
      minimum_msp_stack_free=$2
      shift 2
      ;;
    -h|--help)
      usage
      ;;
    *)
      usage
      ;;
  esac
done

[ -n "$binary" ] && [ -n "$elf" ] && [ -n "$symbols" ] && \
  [ -n "$twin_root" ] && [ -n "$output" ] || usage
[ -f "$binary" ] || die "candidate binary not found: $binary"
[ -f "$elf" ] || die "candidate ELF not found: $elf"
[ -f "$symbols" ] || die "candidate symbol profile not found: $symbols"
[ -d "$twin_root" ] || die "twin root not found: $twin_root"

binary=$(CDPATH= cd -- "$(dirname -- "$binary")" && pwd)/$(basename "$binary")
elf=$(CDPATH= cd -- "$(dirname -- "$elf")" && pwd)/$(basename "$elf")
symbols=$(CDPATH= cd -- "$(dirname -- "$symbols")" && pwd)/$(basename "$symbols")
twin_root=$(CDPATH= cd -- "$twin_root" && pwd)
capture_twin_identity "$twin_root"
twin_root=$TWIN_ROOT
mkdir -p "$output"
output=$(CDPATH= cd -- "$output" && pwd)

for path in "$binary" "$elf" "$symbols" "$twin_root" "$output" "$toolchain_bin"; do
  case "$path" in
    *[[:space:]]*) die 'candidate, twin, and output paths must not contain whitespace' ;;
  esac
done
case "$minimum_sweep_stack_free:$minimum_msp_stack_free" in
  *[!0-9:]*|:*|*:) die 'stack minimums must be non-negative integer byte counts' ;;
esac

# The symbol profile is the ABI contract between this exact ELF and the twin.
# Derive the setting locations instead of pinning one build's SRAM placement.
setting_address=$(awk -F= '$1 == "setting" { print $2 }' "$symbols")
[ "$(printf '%s\n' "$setting_address" | wc -l | tr -d ' ')" -eq 1 ] || \
  die 'candidate symbol profile must contain exactly one setting address'
printf '%s\n' "$setting_address" | grep -Eq '^0x[0-9A-Fa-f]+$' || \
  die "invalid setting address in candidate symbol profile: $setting_address"
setting_base=$((setting_address))
setting_frequency0=$(printf '0x%08X' $((setting_base + 568)))
setting_frequency1=$(printf '0x%08X' $((setting_base + 576)))
setting_mode=$(printf '0x%08X' $((setting_base + 408)))
setting_attenuation_x2=$(printf '0x%08X' $((setting_base + 460)))

if [ -z "$toolchain_bin" ]; then
  toolchain_bin=$($ROOT/tools/bootstrap-toolchain.sh)
fi
[ -x "$toolchain_bin/arm-none-eabi-nm" ] || \
  die "Arm GNU nm not found: $toolchain_bin/arm-none-eabi-nm"

twin_script="$twin_root/digital-twin/renode/zs407.resc"
twin_model="$twin_root/digital-twin/renode/models/ZS407TwinStatus.cs"
[ -f "$twin_script" ] || die "twin loader not found: $twin_script"
[ -f "$twin_model" ] || die "twin status model not found: $twin_model"
grep -Fq 'LoadSymbolProfile' "$twin_model" || \
  die 'twin does not support candidate symbol profiles'
grep -Fq 'RunSelfTestCase' "$twin_model" || \
  die 'twin does not support firmware self-test control'

if [ -z "$runtime" ]; then
  [ -x "$twin_root/tools/bootstrap-renode.sh" ] || \
    die 'twin root does not provide tools/bootstrap-renode.sh'
  runtime=$("$twin_root/tools/bootstrap-renode.sh")
  runtime_source=twin-bootstrap
else
  runtime_source=caller-supplied
fi
[ -x "$runtime/renode" ] || die "Renode runtime is incomplete: $runtime"
runtime=$(CDPATH= cd -- "$runtime" && pwd)
capture_twin_runtime_identity "$runtime" "$runtime_source"

scenario="$output/runtime-state.resc"
raw_log="$output/runtime-state.raw.log"
log="$output/runtime-state.log"
threads="$output/threads.txt"
report="$output/report.txt"
nm_symbols="$output/candidate.nm.txt"
rm -f "$scenario" "$raw_log" "$log" "$threads" "$report" "$nm_symbols"
"$toolchain_bin/arm-none-eabi-nm" -n "$elf" > "$nm_symbols"

elf_symbol() {
  symbol=$1
  count=$(awk -v symbol="$symbol" '$NF == symbol { count++ } END { print count + 0 }' "$nm_symbols")
  [ "$count" -eq 1 ] || die "ELF must contain exactly one $symbol symbol (found $count)"
  value=$(awk -v symbol="$symbol" '$NF == symbol { print $1 }' "$nm_symbols")
  printf '0x%s\n' "$value"
}

msp_base_address=$(elf_symbol __main_stack_base__)
msp_end_address=$(elf_symbol __main_stack_end__)
msp_declared_size=$(elf_symbol __main_stack_size__)
heap_base_address=$(elf_symbol __heap_base__)
heap_end_address=$(elf_symbol __heap_end__)
msp_base=$((msp_base_address))
msp_end=$((msp_end_address))
msp_size=$((msp_end - msp_base))
heap_base=$((heap_base_address))
heap_end=$((heap_end_address))
heap_size=$((heap_end - heap_base))
[ "$msp_end" -gt "$msp_base" ] || die 'ELF main stack boundaries are reversed or empty'
[ "$heap_end" -gt "$heap_base" ] || die 'ELF heap boundaries are reversed or empty'
[ "$msp_size" -eq "$expected_msp_size" ] || \
  die "ELF main stack is $msp_size bytes, expected exactly $expected_msp_size"
[ "$((msp_declared_size))" -eq "$expected_msp_size" ] || \
  die "ELF __main_stack_size__ is $((msp_declared_size)) bytes, expected exactly $expected_msp_size"
[ "$heap_size" -eq "$expected_heap_size" ] || \
  die "ELF heap is $heap_size bytes, expected exactly $expected_heap_size"

{
  write_twin_scenario_provenance
  printf '$bin=@%s\n' "$binary"
  printf '$elf=@%s\n' "$elf"
  printf '$symbols=@%s\n' "$symbols"
  printf 'include @%s\n' "$twin_script"
  cat <<EOF

# Start with an explicitly invalid/empty state image.
sysbus WriteDoubleWord 0x40002850 0
sysbus WriteDoubleWord 0x40002854 0
sysbus WriteDoubleWord 0x40002858 0
sysbus WriteDoubleWord 0x4000285C 0
sysbus WriteDoubleWord 0x40002860 0
sysbus WriteDoubleWord 0x40002864 0
emulation RunFor "1.5"
twinStatus AssertBooted

# Use values with recognizable word patterns. Thread1 must serialize them to
# the STM32 RTC backup registers before the reset.
twinStatus ConfigureAnalyzer 123456789 987654321 123 1234 18 0 10000 3 1 1 2 0 -73.5
emulation RunFor "3.0"
python "b=monitor.Machine.SystemBus; print 'ZS407_QUAL_WARM_PRE_SETTING_FREQ0=0x%016X' % (b.ReadDoubleWord($setting_frequency0) | (b.ReadDoubleWord($setting_frequency0 + 4) << 32))"
python "b=monitor.Machine.SystemBus; print 'ZS407_QUAL_WARM_PRE_SETTING_FREQ1=0x%016X' % (b.ReadDoubleWord($setting_frequency1) | (b.ReadDoubleWord($setting_frequency1 + 4) << 32))"
python "print 'ZS407_QUAL_WARM_PRE_SETTING_MODE=0x%02X' % monitor.Machine.SystemBus.ReadByte($setting_mode)"
python "print 'ZS407_QUAL_WARM_PRE_SETTING_ATTENUATION_X2=0x%04X' % monitor.Machine.SystemBus.ReadWord($setting_attenuation_x2)"
python "print 'ZS407_QUAL_WARM_PRE_BACKUP_FREQ0_LOW=0x%08X' % monitor.Machine.SystemBus.ReadDoubleWord(0x40002850)"
python "print 'ZS407_QUAL_WARM_PRE_BACKUP_FREQ0_HIGH=0x%08X' % monitor.Machine.SystemBus.ReadDoubleWord(0x40002854)"
python "print 'ZS407_QUAL_WARM_PRE_BACKUP_FREQ1_LOW=0x%08X' % monitor.Machine.SystemBus.ReadDoubleWord(0x40002858)"
python "print 'ZS407_QUAL_WARM_PRE_BACKUP_FREQ1_HIGH=0x%08X' % monitor.Machine.SystemBus.ReadDoubleWord(0x4000285C)"
python "print 'ZS407_QUAL_WARM_PRE_BACKUP_TAIL0=0x%08X' % monitor.Machine.SystemBus.ReadDoubleWord(0x40002860)"
python "print 'ZS407_QUAL_WARM_PRE_BACKUP_TAIL1=0x%08X' % monitor.Machine.SystemBus.ReadDoubleWord(0x40002864)"

# System-bus reset resets CPU/peripherals and clears modeled SRAM, while the
# RTC model intentionally retains backup registers like a warm STM32 reset.
sysbus Reset
emulation RunFor "1.5"
twinStatus AssertBooted
python "b=monitor.Machine.SystemBus; print 'ZS407_QUAL_WARM_POST_SETTING_FREQ0=0x%016X' % (b.ReadDoubleWord($setting_frequency0) | (b.ReadDoubleWord($setting_frequency0 + 4) << 32))"
python "b=monitor.Machine.SystemBus; print 'ZS407_QUAL_WARM_POST_SETTING_FREQ1=0x%016X' % (b.ReadDoubleWord($setting_frequency1) | (b.ReadDoubleWord($setting_frequency1 + 4) << 32))"
python "print 'ZS407_QUAL_WARM_POST_SETTING_MODE=0x%02X' % monitor.Machine.SystemBus.ReadByte($setting_mode)"
python "print 'ZS407_QUAL_WARM_POST_SETTING_ATTENUATION_X2=0x%04X' % monitor.Machine.SystemBus.ReadWord($setting_attenuation_x2)"
python "print 'ZS407_QUAL_WARM_POST_BACKUP_FREQ0_LOW=0x%08X' % monitor.Machine.SystemBus.ReadDoubleWord(0x40002850)"
python "print 'ZS407_QUAL_WARM_POST_BACKUP_FREQ1_LOW=0x%08X' % monitor.Machine.SystemBus.ReadDoubleWord(0x40002858)"
python "print 'ZS407_QUAL_WARM_POST_BACKUP_TAIL0=0x%08X' % monitor.Machine.SystemBus.ReadDoubleWord(0x40002860)"
python "print 'ZS407_QUAL_WARM_POST_BACKUP_TAIL1=0x%08X' % monitor.Machine.SystemBus.ReadDoubleWord(0x40002864)"
EOF

  if [ "$warm_only" = false ]; then
    cat <<'EOF'

# Exercise every built-in self-test before measuring the sweep thread's
# watermark. These are firmware executions with the calibrated RF loopback.
twinStatus SetCalibrationLoopback 1 -35.3
EOF
    case_number=1
    while [ "$case_number" -le 14 ]; do
      printf 'twinStatus RunSelfTestCase %s\n' "$case_number"
      # The modeled tests currently complete in about 1.8 seconds, but the
      # assertion must see the firmware's completion transition, not merely a
      # still-running status. Leave more than 2x that measured budget.
      printf 'emulation RunFor "4.0"\n'
      printf 'twinStatus AssertSelfTestCase %s 1\n' "$case_number"
      case_number=$((case_number + 1))
    done

    cat <<'EOF'

# Enumerate CDC ACM and ask the firmware itself for ChibiOS fill-pattern
# watermarks. IN data is retained in the log and decoded by the runner.
usb HostReset
emulation RunFor "0.05"
usb HostSetup "0005010000000000"
emulation RunFor "0.02"
usb HostIn 0
emulation RunFor "0.02"
usb HostSetup "0009010000000000"
emulation RunFor "0.02"
usb HostIn 0
emulation RunFor "0.05"
usb AssertDevice 1 1
usb HostSetup "2120000000000700"
emulation RunFor "0.02"
usb HostOut 0 "00c20100000008"
emulation RunFor "0.02"
usb HostIn 0
emulation RunFor "0.02"
usb HostSetup "2122030000000000"
emulation RunFor "0.02"
usb HostIn 0
emulation RunFor "1.20"
usb ClearCapture
python "print 'ZS407_QUAL_REDRAW_CAPTURE_BEGIN'"
usb HostOut 1 "72656672657368206f6e0d"
emulation RunFor "0.10"
EOF
    poll=1
    while [ "$poll" -le 128 ]; do
      printf 'usb HostSof 1\n'
      printf 'emulation RunFor "0.005"\n'
      printf 'usb HostPollIn 1\n'
      printf 'emulation RunFor "0.005"\n'
      poll=$((poll + 1))
    done
    cat <<'EOF'
usb HostOut 1 "72656672657368206f66660d"
EOF
    poll=1
    while [ "$poll" -le 384 ]; do
      printf 'usb HostSof 1\n'
      printf 'emulation RunFor "0.005"\n'
      printf 'usb HostPollIn 1\n'
      printf 'emulation RunFor "0.005"\n'
      poll=$((poll + 1))
    done
    cat <<'EOF'
python "print 'ZS407_QUAL_REDRAW_CAPTURE_END'"

# Measure the stack only after the remote-redraw stream is stopped and drained.
usb ClearCapture
python "print 'ZS407_QUAL_STACK_CAPTURE_BEGIN'"
usb HostOut 1 "746872656164730d"
emulation RunFor "0.40"
EOF
    poll=1
    while [ "$poll" -le 24 ]; do
      printf 'usb HostSof 1\n'
      printf 'emulation RunFor "0.02"\n'
      printf 'usb HostPollIn 1\n'
      printf 'emulation RunFor "0.02"\n'
      poll=$((poll + 1))
    done
    cat <<'EOF'
python "print 'ZS407_QUAL_STACK_CAPTURE_END'"

# crt0 fills the ELF-derived MSP/interrupt stack with 0x55.
# The untouched prefix is the interrupt-stack high-water safety margin.
EOF
    scan_address=$msp_base
    while [ "$scan_address" -lt "$msp_end" ]; do
      printf "python \"print 'ZS407_QUAL_MSP_WORD address=0x%08X value=0x%%08X' %% monitor.Machine.SystemBus.ReadDoubleWord(0x%08X)\"\n" \
        "$scan_address" "$scan_address"
      scan_address=$((scan_address + 4))
    done
  fi
  printf 'quit\n'
} > "$scenario"

console_fifo="$output/runtime-state.console.$$"
mkfifo "$console_fifo"
exec 3<>"$console_fifo"
rm -f "$console_fifo"

set +e
HOME="$runtime/home" DOTNET_BUNDLE_EXTRACT_BASE_DIR="$runtime/dotnet-bundle" \
  "$runtime/renode" --config "$runtime/config" --disable-xwt --console --plain \
  "$scenario" <&3 >"$raw_log" 2>&1 &
renode_pid=$!
elapsed=0
timed_out=false
while kill -0 "$renode_pid" 2>/dev/null; do
  if [ "$elapsed" -ge 3600 ]; then
    timed_out=true
    kill "$renode_pid" 2>/dev/null || true
    break
  fi
  sleep 1
  elapsed=$((elapsed + 1))
done
wait "$renode_pid"
status=$?
set -e
exec 3>&-
tr -d '\r' < "$raw_log" > "$log"

[ "$timed_out" = false ] || {
  sed -n '1,260p' "$log" >&2
  die 'runtime-state scenario timed out'
}
[ "$status" -eq 0 ] || {
  sed -n '1,260p' "$log" >&2
  die "Renode exited with status $status"
}
if grep -Eq 'Errors during compilation|There was an error executing command|No such command or device:|ZS407 twin .* assertion failed' "$log"; then
  sed -n '1,320p' "$log" >&2
  die 'runtime-state scenario reported an error'
fi

verify_twin_identity
verify_twin_runtime_identity "$runtime"
python3 - "$log" "$threads" "$report" "$binary" "$elf" "$symbols" \
  "$warm_only" "$minimum_sweep_stack_free" "$minimum_msp_stack_free" \
  "$msp_base_address" "$msp_end_address" "$msp_size" \
  "$heap_base_address" "$heap_end_address" "$heap_size" <<'PY'
import hashlib
import pathlib
import re
import sys

(
    log_path,
    threads_path,
    report_path,
    binary_path,
    elf_path,
    symbols_path,
    warm_only_text,
    minimum_sweep_text,
    minimum_msp_text,
    msp_base_text,
    msp_end_text,
    msp_size_text,
    heap_base_text,
    heap_end_text,
    heap_size_text,
) = sys.argv[1:]

lines = pathlib.Path(log_path).read_text(errors="replace").splitlines()
warm_only = warm_only_text == "true"
minimum_sweep = int(minimum_sweep_text)
minimum_msp = int(minimum_msp_text)
msp_base = int(msp_base_text, 0)
msp_end = int(msp_end_text, 0)
msp_size = int(msp_size_text)
heap_base = int(heap_base_text, 0)
heap_end = int(heap_end_text, 0)
heap_size = int(heap_size_text)


def fail(message):
    raise SystemExit(f"runtime-state qualification failed: {message}")


warning_lines = [line for line in lines if "[WARNING]" in line]
known_warning_fragments = (
    "Translation cache size ",
    "cpu: Patching PC ",
    "usart1: Unhandled write to offset ",
    "timer1: Unhandled write to offset ",
)
unexpected_warnings = [
    line
    for line in warning_lines
    if not any(fragment in line for fragment in known_warning_fragments)
]
if unexpected_warnings:
    fail("unexpected Renode warning(s): " + " | ".join(unexpected_warnings[:4]))

def tagged_value(marker):
    pattern = re.compile(rf"{re.escape(marker)}=(0x[0-9A-Fa-f]+)")
    matches = [match for line in lines if (match := pattern.fullmatch(line.strip()))]
    if len(matches) != 1:
        fail(f"expected one atomic {marker} value, found {len(matches)}")
    return int(matches[0].group(1), 16)


expected = {
    "ZS407_QUAL_WARM_PRE_SETTING_FREQ0": 123456789,
    "ZS407_QUAL_WARM_PRE_SETTING_FREQ1": 987654321,
    "ZS407_QUAL_WARM_PRE_SETTING_MODE": 0,
    "ZS407_QUAL_WARM_PRE_SETTING_ATTENUATION_X2": 18,
    "ZS407_QUAL_WARM_PRE_BACKUP_FREQ0_LOW": 123456789,
    "ZS407_QUAL_WARM_PRE_BACKUP_FREQ0_HIGH": 0,
    "ZS407_QUAL_WARM_PRE_BACKUP_FREQ1_LOW": 987654321,
    "ZS407_QUAL_WARM_PRE_BACKUP_FREQ1_HIGH": 0,
    "ZS407_QUAL_WARM_POST_SETTING_FREQ0": 123456789,
    "ZS407_QUAL_WARM_POST_SETTING_FREQ1": 987654321,
    "ZS407_QUAL_WARM_POST_SETTING_MODE": 0,
    "ZS407_QUAL_WARM_POST_SETTING_ATTENUATION_X2": 18,
    "ZS407_QUAL_WARM_POST_BACKUP_FREQ0_LOW": 123456789,
    "ZS407_QUAL_WARM_POST_BACKUP_FREQ1_LOW": 987654321,
}
for marker, wanted in expected.items():
    actual = tagged_value(marker)
    if actual != wanted:
        fail(f"{marker} is 0x{actual:X}, expected 0x{wanted:X}")

tail_words = {
    "pre": (
        tagged_value("ZS407_QUAL_WARM_PRE_BACKUP_TAIL0"),
        tagged_value("ZS407_QUAL_WARM_PRE_BACKUP_TAIL1"),
    ),
    "post": (
        tagged_value("ZS407_QUAL_WARM_POST_BACKUP_TAIL0"),
        tagged_value("ZS407_QUAL_WARM_POST_BACKUP_TAIL1"),
    ),
}
for phase, (tail0, tail1) in tail_words.items():
    attenuation = tail0 & 0xFF
    mode = (tail0 >> 24) & 0xFF
    reserved = (tail1 >> 16) & 0xFF
    if attenuation != 19:
        fail(f"{phase} backup attenuation is 0x{attenuation:X}, expected 0x13")
    if mode != 0:
        fail(f"{phase} backup mode is 0x{mode:X}, expected 0")
    if reserved != 0:
        fail(f"{phase} backup reserved byte is 0x{reserved:X}, expected 0")

boot_passes = sum("ZS407_TWIN_BOOT=PASS" in line for line in lines)
if boot_passes != 2:
    fail(f"expected two successful boots, found {boot_passes}")

thread_text = ""
sweep_free = None
msp_free = None
selftest_passes = 0
redraw_packets = 0
redraw_bytes = 0
if not warm_only:
    selftest_passes = sum("ZS407_TWIN_SELFTEST=PASS" in line for line in lines)
    if selftest_passes != 14:
        fail(f"expected 14 self-test passes, found {selftest_passes}")

    redraw_begin = next(
        (i for i, line in enumerate(lines) if "ZS407_QUAL_REDRAW_CAPTURE_BEGIN" in line), None
    )
    redraw_end = next(
        (i for i, line in enumerate(lines) if "ZS407_QUAL_REDRAW_CAPTURE_END" in line), None
    )
    if redraw_begin is None or redraw_end is None or redraw_end <= redraw_begin:
        fail("USB remote-redraw capture markers are missing or reversed")
    redraw_payload = bytearray()
    for line in lines[redraw_begin + 1 : redraw_end]:
        match = re.search(r"ZS407_TWIN_USB=IN ep=1 .* data=([0-9A-Fa-f]*)", line)
        if match:
            packet = bytes.fromhex(match.group(1))
            if packet:
                redraw_packets += 1
                redraw_bytes += len(packet)
                redraw_payload.extend(packet)
    if redraw_packets < 32 or redraw_bytes < 2048:
        fail(
            f"remote redraw produced only {redraw_packets} USB packets/{redraw_bytes} bytes"
        )
    if b"bulk\r\n" not in redraw_payload and b"fill\r\n" not in redraw_payload:
        fail("remote redraw USB stream contains neither a bulk nor fill region header")

    begin = next((i for i, line in enumerate(lines) if "ZS407_QUAL_STACK_CAPTURE_BEGIN" in line), None)
    end = next((i for i, line in enumerate(lines) if "ZS407_QUAL_STACK_CAPTURE_END" in line), None)
    if begin is None or end is None or end <= begin:
        fail("USB stack capture markers are missing or reversed")
    payload = bytearray()
    for line in lines[begin + 1 : end]:
        match = re.search(r"ZS407_TWIN_USB=IN ep=1 .* data=([0-9A-Fa-f]*)", line)
        if match:
            payload.extend(bytes.fromhex(match.group(1)))
    thread_text = payload.decode("ascii", errors="replace")
    pathlib.Path(threads_path).write_text(thread_text)
    sweep_rows = [line for line in thread_text.splitlines() if line.rstrip().endswith("sweep")]
    if len(sweep_rows) != 1:
        fail(f"expected one sweep thread row, found {len(sweep_rows)}")
    fields = sweep_rows[0].split("|")
    if len(fields) < 8 or not re.fullmatch(r"[0-9A-Fa-f]{8}", fields[2].strip()):
        fail(f"malformed sweep thread row: {sweep_rows[0]!r}")
    sweep_free = int(fields[2].strip(), 16)
    if sweep_free < minimum_sweep:
        fail(f"sweep thread free margin {sweep_free} < {minimum_sweep} bytes")

    word_pattern = re.compile(
        r"ZS407_QUAL_MSP_WORD address=(0x[0-9A-Fa-f]{8}) value=(0x[0-9A-Fa-f]{8})"
    )
    words = []
    addresses = []
    for line in lines:
        match = word_pattern.fullmatch(line.strip())
        if match:
            addresses.append(int(match.group(1), 16))
            words.append(int(match.group(2), 16))
    expected_words = msp_size // 4
    if len(words) != expected_words:
        fail(f"MSP scan returned {len(words)} words, expected {expected_words}")
    expected_addresses = list(range(msp_base, msp_end, 4))
    if addresses != expected_addresses:
        fail("MSP scan addresses are incomplete, duplicated, or out of order")
    untouched = 0
    for value in words:
        if value != 0x55555555:
            break
        untouched += 1
    msp_free = untouched * 4
    if msp_free < minimum_msp:
        fail(f"MSP free margin {msp_free} < {minimum_msp} bytes")
else:
    pathlib.Path(threads_path).write_text("warm-only run: no stack capture\n")


def digest(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


report_lines = [
    "schema=tinysa-chibios-runtime-state-v1",
    "result=PASS",
    "environment=RENODE_DIGITAL_TWIN",
    "hardware_qualified=NO",
    "release_seal=NOT_EVALUATED",
    f"known_model_warning_count={len(warning_lines)}",
    "unexpected_model_warning_count=0",
    f"candidate_binary_bytes={pathlib.Path(binary_path).stat().st_size}",
    f"candidate_binary_sha256={digest(binary_path)}",
    f"candidate_elf_sha256={digest(elf_path)}",
    f"candidate_symbols_sha256={digest(symbols_path)}",
    f"msp_base=0x{msp_base:08X}",
    f"msp_end=0x{msp_end:08X}",
    f"msp_size_bytes={msp_size}",
    f"heap_base=0x{heap_base:08X}",
    f"heap_end=0x{heap_end:08X}",
    f"heap_size_bytes={heap_size}",
    "memory_layout=PASS",
    "warm_reset_rtc_retention=PASS",
    "warm_reset_frequency_restore=PASS",
    "warm_reset_mode_restore=PASS",
    "warm_reset_attenuation_restore=PASS",
    "warm_reset_reserved_byte_zero=PASS",
    f"boot_passes={boot_passes}",
    f"selftest_passes={selftest_passes}",
]
if not warm_only:
    report_lines.extend(
        [
            f"sweep_stack_free_bytes={sweep_free}",
            f"sweep_stack_minimum_bytes={minimum_sweep}",
            f"msp_stack_free_bytes={msp_free}",
            f"msp_stack_minimum_bytes={minimum_msp}",
            f"remote_redraw_usb_packets={redraw_packets}",
            f"remote_redraw_usb_bytes={redraw_bytes}",
            "remote_redraw_usb_stress=PASS",
            "stack_watermark=PASS",
        ]
    )
else:
    report_lines.append("stack_watermark=NOT_RUN")
pathlib.Path(report_path).write_text("\n".join(report_lines) + "\n")
PY

{
  printf 'twin_source_commit=%s\n' "$TWIN_SOURCE_COMMIT"
  printf 'twin_renode_tree=%s\n' "$TWIN_RENODE_TREE"
  printf 'twin_tools_tree=%s\n' "$TWIN_TOOLS_TREE"
  printf 'twin_bootstrap_blob=%s\n' "$TWIN_BOOTSTRAP_BLOB"
  printf 'renode_runtime_source=%s\n' "$TWIN_RUNTIME_SOURCE"
  printf 'renode_runtime_sha256=%s\n' "$TWIN_RUNTIME_SHA256"
  printf 'renode_runtime_path=%s\n' "$runtime"
} >> "$report"

cat "$report"
printf 'scenario=%s\n' "$scenario"
printf 'log=%s\n' "$log"
printf 'threads=%s\n' "$threads"
printf 'report=%s\n' "$report"
