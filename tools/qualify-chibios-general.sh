#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$ROOT/tools/lib.sh"

usage() {
  cat >&2 <<EOF
Usage: $0 --bin FILE --elf FILE --symbols FILE --twin-root DIR --output DIR
          [--runtime DIR]

Run the exact candidate through the executable ZS407 twin's existing full
UI/RF, 14-case self-test with disconnected-CAL recovery, and USB device
scenarios. The command does not build or flash firmware. DIR receives exact-
image scenario wrappers, raw and normalized logs, a warning inventory,
screenshots emitted by the existing scenarios, and report.txt.

A PASS is simulation evidence only. It is not hardware qualification.
EOF
  exit 2
}

binary=
elf=
symbols=
twin_root=
output=
runtime=

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
mkdir -p "$output"
output=$(CDPATH= cd -- "$output" && pwd)

for path in "$binary" "$elf" "$symbols" "$twin_root" "$output" "$runtime"; do
  case "$path" in
    *[[:space:]]*) die 'candidate, twin, runtime, and output paths must not contain whitespace' ;;
  esac
done

twin_loader=$twin_root/digital-twin/renode/zs407.resc
twin_model=$twin_root/digital-twin/renode/models/ZS407TwinStatus.cs
test_root=$twin_root/digital-twin/renode/tests
full_test=$test_root/full.resc
selftest_test=$test_root/selftest.resc
usb_test=$test_root/usb.resc

for required in "$twin_loader" "$twin_model" "$full_test" "$selftest_test" "$usb_test"; do
  [ -f "$required" ] || die "required twin file not found: $required"
done

# Refuse an older or reduced twin whose same-named scenarios do not exercise
# the release gates this qualifier promises to run.
grep -Fq 'LoadSymbolProfile $symbols' "$twin_loader" || \
  die 'twin loader does not load the exact candidate symbol profile'
grep -Fq 'twinStatus AssertNormalUi' "$full_test" || \
  die 'full scenario does not assert restoration of the normal UI'
grep -Fq 'twinStatus AssertToneObserved' "$full_test" || \
  die 'full scenario does not assert a frequency-selective RF tone'
grep -Fq 'twinStatus RunSelfTestCase 14' "$selftest_test" || \
  die 'self-test scenario does not run all 14 cases'
grep -Fq 'twinStatus SetCalibrationLoopback 0' "$selftest_test" || \
  die 'self-test scenario lacks the disconnected-CAL negative control'
grep -Fq 'twinStatus AssertSelfTestFailureDetected 3' "$selftest_test" || \
  die 'self-test scenario does not assert disconnected-CAL detection'
[ "$(grep -Fc 'twinStatus SetCalibrationLoopback 1' "$selftest_test")" -ge 2 ] || \
  die 'self-test scenario does not reconnect CAL after its negative control'
grep -Fq 'usb AssertCaptureContains "tinySA4"' "$usb_test" || \
  die 'USB scenario does not exercise the CDC version response'
grep -Fq 'usb AssertEndpointStalled 0' "$usb_test" || \
  die 'USB scenario does not assert EP0 STALL behavior'
grep -Fq 'usb AssertEvents 2 1 1' "$usb_test" || \
  die 'USB scenario does not assert reset recovery and re-enumeration'

if [ -z "$runtime" ]; then
  [ -x "$twin_root/tools/bootstrap-renode.sh" ] || \
    die 'twin root does not provide tools/bootstrap-renode.sh'
  runtime=$($twin_root/tools/bootstrap-renode.sh)
fi
[ -d "$runtime" ] || die "Renode runtime not found: $runtime"
runtime=$(CDPATH= cd -- "$runtime" && pwd)
[ -x "$runtime/renode" ] || die "Renode runtime is incomplete: $runtime"
case "$runtime" in
  *[[:space:]]*) die 'Renode runtime path must not contain whitespace' ;;
esac

scenario_dir=$output/scenarios
screen_dir=$output/.artifacts/digital-twin
inventory=$output/warning-inventory.txt
report=$output/report.txt
mkdir -p "$scenario_dir" "$screen_dir"
rm -f "$inventory" "$report" \
  "$screen_dir/full-tone-450mhz.png" "$screen_dir/selftest-complete.png"

write_wrapper() {
  name=$1
  test_file=$2
  wrapper=$scenario_dir/$name.resc
  {
    printf '$bin=@%s\n' "$binary"
    printf '$elf=@%s\n' "$elf"
    printf '$symbols=@%s\n' "$symbols"
    printf 'include @%s\n' "$test_file"
  } > "$wrapper"
}

write_wrapper full "$full_test"
write_wrapper selftest "$selftest_test"
write_wrapper usb "$usb_test"

renode_pid=
cleanup() {
  if [ -n "$renode_pid" ] && kill -0 "$renode_pid" 2>/dev/null; then
    kill "$renode_pid" 2>/dev/null || true
    wait "$renode_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT
trap 'cleanup; exit 1' HUP INT TERM

run_scenario() {
  name=$1
  wrapper=$scenario_dir/$name.resc
  raw_log=$output/$name.raw.log
  log=$output/$name.log
  console_fifo=$output/$name.console.$$
  rm -f "$raw_log" "$log" "$console_fifo"
  mkfifo "$console_fifo"
  exec 3<>"$console_fifo"
  rm -f "$console_fifo"

  set +e
  (
    cd "$output"
    HOME="$runtime/home" DOTNET_BUNDLE_EXTRACT_BASE_DIR="$runtime/dotnet-bundle" \
      exec "$runtime/renode" --config "$runtime/config" \
        --disable-xwt --console --plain "$wrapper" <&3 >"$raw_log" 2>&1
  ) &
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
  renode_pid=
  set -e
  exec 3>&-
  tr -d '\r' < "$raw_log" > "$log"

  [ "$timed_out" = false ] || {
    sed -n '1,320p' "$log" >&2
    die "$name scenario timed out"
  }
  [ "$status" -eq 0 ] || {
    sed -n '1,320p' "$log" >&2
    die "$name scenario exited with status $status"
  }
  if grep -Eiq 'Errors during compilation|There was an error executing command|No such command or device:|unknown command| assertion failed|Unhandled exception|ZS407_TWIN_[A-Z0-9_]*=FAIL' "$log"; then
    sed -n '1,360p' "$log" >&2
    die "$name scenario reported an emulator command or assertion error"
  fi
  grep -Fq 'Renode is quitting' "$log" || {
    sed -n '1,320p' "$log" >&2
    die "$name scenario did not reach its explicit quit"
  }
}

run_scenario full
run_scenario selftest
run_scenario usb

[ -s "$screen_dir/full-tone-450mhz.png" ] || \
  die 'full UI/RF scenario did not retain its tone screenshot'
[ -s "$screen_dir/selftest-complete.png" ] || \
  die 'self-test scenario did not retain its completion screenshot'

python3 - \
  "$output/full.log" "$output/selftest.log" "$output/usb.log" \
  "$scenario_dir/full.resc" "$scenario_dir/selftest.resc" "$scenario_dir/usb.resc" \
  "$inventory" "$report" "$binary" "$elf" "$symbols" "$screen_dir" <<'PY'
import hashlib
import pathlib
import re
import sys

(
    full_log_path,
    selftest_log_path,
    usb_log_path,
    full_wrapper_path,
    selftest_wrapper_path,
    usb_wrapper_path,
    inventory_path,
    report_path,
    binary_path,
    elf_path,
    symbols_path,
    screen_dir,
) = sys.argv[1:]

log_paths = {
    "full": pathlib.Path(full_log_path),
    "selftest": pathlib.Path(selftest_log_path),
    "usb": pathlib.Path(usb_log_path),
}
logs = {
    name: path.read_text(errors="replace").splitlines()
    for name, path in log_paths.items()
}


def fail(message):
    raise SystemExit(f"general exact-image qualification failed: {message}")


def digest(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def exact_count(name, fragment, expected):
    count = sum(fragment in line for line in logs[name])
    if count != expected:
        fail(
            f"{name} has {count} occurrences of {fragment!r}; expected {expected}"
        )


def marker_index(name, fragment, occurrence=1):
    matches = [index for index, line in enumerate(logs[name]) if fragment in line]
    if len(matches) < occurrence:
        fail(f"{name} is missing occurrence {occurrence} of {fragment!r}")
    return matches[occurrence - 1]


def classify_warning(line):
    payload = line.split("[WARNING]", 1)[1].strip()
    if re.fullmatch(
        r"Translation cache size [0-9]+ is larger than maximum allowed [0-9]+\. "
        r"It will be clamped to maximum",
        payload,
    ):
        return "translation-cache-clamp"
    if re.fullmatch(r"cpu: Patching PC 0x[0-9A-Fa-f]+ for Thumb mode\.", payload):
        return "thumb-pc-normalization"
    if (
        payload.startswith("usart1: Unhandled write to offset 0x4.")
        and "Unhandled bits: [6]" in payload
        and "when writing value 0x40." in payload
        and payload.endswith("Tags: LBDIE (0x1).")
    ):
        return "usart-lbdie-gap"
    if (
        payload.startswith("usart1: Unhandled write to offset 0x8.")
        and "Unhandled bits: [0]" in payload
        and "when writing value 0x1." in payload
        and payload.endswith("Tags: EIE (0x1).")
    ):
        return "usart-eie-gap"
    if (
        payload.startswith("usart1: Unhandled write to offset 0x20.")
        and "Unhandled bits: [" in payload
        and "when writing value 0xFFFFFFFF." in payload
        and "Tags:" in payload
    ):
        tags_text = payload.split("Tags:", 1)[1]
        tags = set(re.findall(r"([A-Z][A-Z0-9]*) \(0x[0-9A-Fa-f]+\)", tags_text))
        allowed_tags = {
            "PECF",
            "FECF",
            "NCF",
            "ORECF",
            "IDLECF",
            "RESERVED",
            "CTSCF",
            "CMCF",
            "WUCF",
            "TCBGTCF",
            "LBDCF",
            "EOBCF",
        }
        if tags and tags <= allowed_tags and {"PECF", "ORECF", "IDLECF"} <= tags:
            return "usart-icr-gap"
    if (
        payload.startswith("timer1: Unhandled write to offset 0x4.")
        and "Unhandled bits: [5]" in payload
        and "when writing value 0x20." in payload
        and payload.endswith("Tags: MMS (0x2).")
    ):
        return "tim1-mms-bit5-gap"
    return None


warning_classes = (
    "translation-cache-clamp",
    "thumb-pc-normalization",
    "usart-lbdie-gap",
    "usart-eie-gap",
    "usart-icr-gap",
    "tim1-mms-bit5-gap",
)
warning_rows = []
unexpected_warnings = []
warning_counts = {
    name: {warning_class: 0 for warning_class in warning_classes}
    for name in logs
}
for name, lines in logs.items():
    for line in lines:
        if "[WARNING]" not in line:
            continue
        warning_class = classify_warning(line)
        if warning_class is None:
            unexpected_warnings.append((name, line))
            warning_rows.append((name, "UNEXPECTED", line))
        else:
            warning_counts[name][warning_class] += 1
            warning_rows.append((name, warning_class, line))

inventory_lines = [
    "schema=tinysa-chibios-general-warning-inventory-v1",
    "allowed_warning_classes=" + ",".join(warning_classes),
]
for name in ("full", "selftest", "usb"):
    scenario_total = sum(warning_counts[name].values())
    inventory_lines.append(f"{name}_warning_count={scenario_total}")
    for warning_class in warning_classes:
        inventory_lines.append(
            f"{name}_{warning_class}_count={warning_counts[name][warning_class]}"
        )
inventory_lines.extend(
    [
        f"allowed_warning_count={sum(sum(row.values()) for row in warning_counts.values())}",
        f"unexpected_warning_count={len(unexpected_warnings)}",
    ]
)
for sequence, (name, warning_class, line) in enumerate(warning_rows, start=1):
    inventory_lines.append(
        f"warning_{sequence:03d}={name}|{warning_class}|{line.strip()}"
    )
pathlib.Path(inventory_path).write_text("\n".join(inventory_lines) + "\n")
if unexpected_warnings:
    rendered = " | ".join(
        f"{name}: {line.strip()}" for name, line in unexpected_warnings[:4]
    )
    fail(f"unexpected Renode warning(s): {rendered}")

# Bind every completed process to this exact candidate and symbol profile.
binary_size = pathlib.Path(binary_path).stat().st_size
symbol_name = pathlib.Path(symbols_path).name
for name in ("full", "selftest", "usb"):
    exact_count(name, "Renode is quitting", 1)
    exact_count(name, f"ZS407_TWIN_SYMBOLS=LOADED profile={symbol_name} ", 1)
    load_pattern = re.compile(
        rf"Loading block of {binary_size} bytes length at 0x0?8000000"
    )
    load_count = sum(bool(load_pattern.search(line)) for line in logs[name])
    if load_count != 1:
        fail(
            f"{name} has {load_count} exact-size firmware load markers; expected 1"
        )
    exact_count(name, "ZS407_TWIN_BOOT=PASS", 1)

for wrapper_path in (full_wrapper_path, selftest_wrapper_path, usb_wrapper_path):
    wrapper = pathlib.Path(wrapper_path).read_text().splitlines()
    required_lines = {
        f"$bin=@{binary_path}",
        f"$elf=@{elf_path}",
        f"$symbols=@{symbols_path}",
    }
    if not required_lines <= set(wrapper):
        fail(f"{wrapper_path} does not bind all exact candidate inputs")

# Full UI and frequency-selective RF behavior.
for marker in (
    "ZS407_TWIN_JOG=PASS",
    "ZS407_TWIN_TOUCH=PASS",
    "ZS407_TWIN_UI_NORMAL=PASS",
    "ZS407_TWIN_RF_TONE=PASS",
    "ZS407_TWIN_STATUS ",
):
    exact_count("full", marker, 1)

# Every positive self-test must pass once. Case 3 then runs once more as the
# disconnected-CAL negative control and must recover only after acknowledgement.
for case in range(1, 15):
    exact_count("selftest", f"ZS407_TWIN_SELFTEST=PASS case={case} status=1", 1)
exact_count("selftest", "ZS407_TWIN_SELFTEST=START", 15)
exact_count("selftest", "ZS407_TWIN_SELFTEST=PASS", 15)
exact_count("selftest", "ZS407_TWIN_CAL_LOOPBACK=connected", 2)
exact_count("selftest", "ZS407_TWIN_CAL_LOOPBACK=disconnected", 1)
exact_count("selftest", "ZS407_TWIN_SELFTEST_FAILURE=PASS case=3 status=2", 1)
exact_count("selftest", "ZS407_TWIN_SELFTEST=PASS case=3 status=2", 1)
exact_count("selftest", "ZS407_TWIN_STATUS ", 1)

first_connected = marker_index("selftest", "ZS407_TWIN_CAL_LOOPBACK=connected", 1)
case_one_start = marker_index("selftest", "ZS407_TWIN_SELFTEST=START case=1")
case_fourteen_pass = marker_index(
    "selftest", "ZS407_TWIN_SELFTEST=PASS case=14 status=1"
)
disconnected = marker_index("selftest", "ZS407_TWIN_CAL_LOOPBACK=disconnected")
failure = marker_index(
    "selftest", "ZS407_TWIN_SELFTEST_FAILURE=PASS case=3 status=2"
)
negative_acknowledged = marker_index(
    "selftest", "ZS407_TWIN_SELFTEST=PASS case=3 status=2"
)
reconnected = marker_index("selftest", "ZS407_TWIN_CAL_LOOPBACK=connected", 2)
final_status = marker_index("selftest", "ZS407_TWIN_STATUS ")
if not (
    first_connected
    < case_one_start
    < case_fourteen_pass
    < disconnected
    < failure
    < negative_acknowledged
    < reconnected
    < final_status
):
    fail("disconnected-CAL detection, acknowledgement, and recovery are out of order")

# USB enumeration, CDC command traffic, EP0 STALL, and bus-reset recovery.
exact_count("usb", "ZS407_TWIN_USB_DESCRIPTOR=PASS", 2)
exact_count("usb", "ZS407_TWIN_USB_ENUM=PASS", 4)
exact_count("usb", "ZS407_TWIN_USB_CDC=PASS", 2)
exact_count("usb", "ZS407_TWIN_USB_CDC=PASS contains=tinySA4", 1)
exact_count("usb", "ZS407_TWIN_USB_CDC=PASS contains=ch> ", 1)
exact_count("usb", "ZS407_TWIN_USB_STALL=PASS ep=0", 1)
exact_count("usb", "ZS407_TWIN_USB=RESET count=", 2)
exact_count("usb", "ZS407_TWIN_USB_EVENTS=PASS reset=1 suspend=1 wakeup=1", 1)
exact_count("usb", "ZS407_TWIN_USB_EVENTS=PASS reset=2 suspend=1 wakeup=1", 1)
exact_count("usb", "ZS407_TWIN_STATUS ", 1)
stall = marker_index("usb", "ZS407_TWIN_USB_STALL=PASS ep=0")
second_reset = marker_index("usb", "ZS407_TWIN_USB=RESET count=2")
recovered = marker_index(
    "usb", "ZS407_TWIN_USB_EVENTS=PASS reset=2 suspend=1 wakeup=1"
)
if not stall < second_reset < recovered:
    fail("USB STALL, second bus reset, and recovery are out of order")

wrappers = {
    "full": pathlib.Path(full_wrapper_path),
    "selftest": pathlib.Path(selftest_wrapper_path),
    "usb": pathlib.Path(usb_wrapper_path),
}
total_warnings = sum(sum(row.values()) for row in warning_counts.values())
report_lines = [
    "schema=tinysa-chibios-general-exact-image-v1",
    "result=PASS",
    "environment=RENODE_DIGITAL_TWIN",
    "qualification_boundary=SIMULATION_ONLY",
    "hardware_qualified=NO",
    "hardware_flash_performed=NO",
    f"candidate_binary_bytes={binary_size}",
    f"candidate_binary_sha256={digest(binary_path)}",
    f"candidate_elf_sha256={digest(elf_path)}",
    f"candidate_symbols_sha256={digest(symbols_path)}",
    f"full_wrapper_sha256={digest(wrappers['full'])}",
    f"selftest_wrapper_sha256={digest(wrappers['selftest'])}",
    f"usb_wrapper_sha256={digest(wrappers['usb'])}",
    "full_ui_rf=PASS",
    "selftest_positive_cases=14",
    "selftest_all_cases=PASS",
    "selftest_disconnected_cal_detection=PASS",
    "selftest_disconnected_cal_recovery=PASS",
    "usb_enumeration=PASS",
    "usb_cdc=PASS",
    "usb_ep0_stall=PASS",
    "usb_reset_recovery=PASS",
    f"full_warning_count={sum(warning_counts['full'].values())}",
    f"selftest_warning_count={sum(warning_counts['selftest'].values())}",
    f"usb_warning_count={sum(warning_counts['usb'].values())}",
    f"known_model_warning_count={total_warnings}",
    "unexpected_model_warning_count=0",
    f"warning_inventory_sha256={digest(inventory_path)}",
    f"screens_dir={screen_dir}",
    "release_seal=NOT_EVALUATED",
]
pathlib.Path(report_path).write_text("\n".join(report_lines) + "\n")
PY

cat "$report"
printf 'full_scenario=%s\n' "$scenario_dir/full.resc"
printf 'selftest_scenario=%s\n' "$scenario_dir/selftest.resc"
printf 'usb_scenario=%s\n' "$scenario_dir/usb.resc"
printf 'full_log=%s\n' "$output/full.log"
printf 'selftest_log=%s\n' "$output/selftest.log"
printf 'usb_log=%s\n' "$output/usb.log"
printf 'warning_inventory=%s\n' "$inventory"
printf 'report=%s\n' "$report"
