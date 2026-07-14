#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$ROOT/tools/lib.sh"

usage() {
  cat >&2 <<EOF
Usage: $0 --bin FILE --elf FILE --symbols FILE --twin-root DIR --output DIR
          [--runtime DIR] [--toolchain-bin DIR]
          [--minimum-msp-stack-free BYTES]

Exercise the exact candidate's HardFault veneer in two destructive Renode
scenarios: an extended-FPU frame stacked on PSP, and a nested HardFault from
an enabled external IRQ's default handler stacked on MSP. Both scenarios verify the core frame pointer,
EXC_RETURN, r0-r12/LR/PC/xPSR, the veneer copy of r4-r11, a complete ELF-
derived MSP canary scan, and a non-flat fatal-screen capture.

The exact ELF must expose a 1024-byte MSP region and 6488-byte heap. This is a
simulation qualification; it does not claim that hardware was exercised.
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
case "$minimum_msp_stack_free" in
  ''|*[!0-9]*) die 'MSP stack minimum must be a non-negative integer byte count' ;;
esac

binary=$(CDPATH= cd -- "$(dirname -- "$binary")" && pwd)/$(basename "$binary")
elf=$(CDPATH= cd -- "$(dirname -- "$elf")" && pwd)/$(basename "$elf")
symbols=$(CDPATH= cd -- "$(dirname -- "$symbols")" && pwd)/$(basename "$symbols")
twin_root=$(CDPATH= cd -- "$twin_root" && pwd)
mkdir -p "$output"
output=$(CDPATH= cd -- "$output" && pwd)
for path in "$binary" "$elf" "$symbols" "$twin_root" "$output" "$toolchain_bin"; do
  case "$path" in
    *[[:space:]]*) die 'candidate, twin, and output paths must not contain whitespace' ;;
  esac
done

if [ -z "$toolchain_bin" ]; then
  toolchain_bin=$($ROOT/tools/bootstrap-toolchain.sh)
fi
nm=$toolchain_bin/arm-none-eabi-nm
objdump=$toolchain_bin/arm-none-eabi-objdump
[ -x "$nm" ] || die "Arm GNU nm not found: $nm"
[ -x "$objdump" ] || die "Arm GNU objdump not found: $objdump"

twin_script=$twin_root/digital-twin/renode/zs407.resc
twin_model=$twin_root/digital-twin/renode/models/ZS407TwinStatus.cs
[ -f "$twin_script" ] || die "twin loader not found: $twin_script"
[ -f "$twin_model" ] || die "twin status model not found: $twin_model"
grep -Fq 'SaveScreenRaw' "$twin_model" || die 'twin does not support raw screen capture'

if [ -z "$runtime" ]; then
  [ -x "$twin_root/tools/bootstrap-renode.sh" ] || \
    die 'twin root does not provide tools/bootstrap-renode.sh'
  runtime=$($twin_root/tools/bootstrap-renode.sh)
fi
[ -x "$runtime/renode" ] || die "Renode runtime is incomplete: $runtime"

nm_symbols=$output/candidate.nm.txt
veneer_disassembly=$output/hardfault-veneer.disassembly.txt
report=$output/report.txt
rm -f "$nm_symbols" "$veneer_disassembly" "$report"
"$nm" -n "$elf" > "$nm_symbols"

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
handler_address=$(elf_symbol HardFault_Handler)
c_handler_address=$(elf_symbol hard_fault_handler_c)
vector_irq_address=$(elf_symbol Vector8C)
unhandled_address=$(elf_symbol _unhandled_exception)

msp_base=$((msp_base_address))
msp_end=$((msp_end_address))
msp_size=$((msp_end - msp_base))
heap_base=$((heap_base_address))
heap_end=$((heap_end_address))
heap_size=$((heap_end - heap_base))
handler=$((handler_address))
c_handler=$((c_handler_address))

[ "$msp_size" -eq "$expected_msp_size" ] || \
  die "ELF main stack is $msp_size bytes, expected exactly $expected_msp_size"
[ "$((msp_declared_size))" -eq "$expected_msp_size" ] || \
  die "ELF __main_stack_size__ is $((msp_declared_size)) bytes, expected exactly $expected_msp_size"
[ "$heap_size" -eq "$expected_heap_size" ] || \
  die "ELF heap is $heap_size bytes, expected exactly $expected_heap_size"
[ "$c_handler" -gt "$handler" ] && [ $((c_handler - handler)) -le 64 ] || \
  die 'HardFault veneer is missing or unexpectedly large'

"$objdump" -d --start-address="$handler_address" --stop-address="$c_handler_address" \
  "$elf" > "$veneer_disassembly"
grep -Eq 'tst\.w[[:space:]]+lr, #4' "$veneer_disassembly" || \
  die 'HardFault veneer does not select the exception stack from EXC_RETURN'
grep -Eq 'mrseq[[:space:]]+r0, MSP' "$veneer_disassembly" || \
  die 'HardFault veneer does not read MSP into r0'
grep -Eq 'mrsne[[:space:]]+r0, PSP' "$veneer_disassembly" || \
  die 'HardFault veneer does not read PSP into r0'
grep -Eq 'sub[[:space:]]+sp, #32' "$veneer_disassembly" || \
  die 'HardFault veneer does not reserve exactly 32 bytes for r4-r11'
grep -Eq 'mov[[:space:]]+r1, sp' "$veneer_disassembly" || \
  die 'HardFault veneer does not pass the r4-r11 save area in r1'
if grep -Eq 'add(s|\.w)?[[:space:]]+r0,.*#72' "$veneer_disassembly"; then
  die 'HardFault veneer incorrectly skips 72 bytes for an extended FP frame'
fi

capture_dir=$output/screens
mkdir -p "$capture_dir"
rm -f "$capture_dir/fault-psp.png" "$capture_dir/fault-psp.rgb565" \
  "$capture_dir/fault-msp.png" "$capture_dir/fault-msp.rgb565"

write_scenario() {
  kind=$1
  scenario=$2
  {
    printf '$bin=@%s\n' "$binary"
    printf '$elf=@%s\n' "$elf"
    printf '$symbols=@%s\n' "$symbols"
    printf '$captureDir = @%s\n' "$capture_dir"
    printf 'include @%s\n' "$twin_script"
    printf 'cpu AddHook %s "c=self.GetRegisterUlong(\x27r0\x27); s=self.GetRegisterUlong(\x27r1\x27); b=self.Bus; print \x27ZS407_FAULT_ENTRY kind=%s core=0x%%08X callee=0x%%08X exc_return=0x%%08X stacked_r0=0x%%08X stacked_r1=0x%%08X stacked_r2=0x%%08X stacked_r3=0x%%08X stacked_r12=0x%%08X stacked_lr=0x%%08X stacked_pc=0x%%08X stacked_psr=0x%%08X save4=0x%%08X save5=0x%%08X save6=0x%%08X save7=0x%%08X save8=0x%%08X save9=0x%%08X save10=0x%%08X save11=0x%%08X\x27 %% (c, s, self.LR.RawValue, b.ReadDoubleWord(c), b.ReadDoubleWord(c+4), b.ReadDoubleWord(c+8), b.ReadDoubleWord(c+12), b.ReadDoubleWord(c+16), b.ReadDoubleWord(c+20), b.ReadDoubleWord(c+24), b.ReadDoubleWord(c+28), b.ReadDoubleWord(s), b.ReadDoubleWord(s+4), b.ReadDoubleWord(s+8), b.ReadDoubleWord(s+12), b.ReadDoubleWord(s+16), b.ReadDoubleWord(s+20), b.ReadDoubleWord(s+24), b.ReadDoubleWord(s+28))"\n' \
      "$c_handler_address" "$kind"
    cat <<EOF
emulation RunFor "1.5"
twinStatus AssertBooted
EOF
    if [ "$kind" = psp ]; then
      cat <<'EOF'
python "c=monitor.Machine.SystemBus.GetCPUs()[0]; print 'ZS407_FAULT_PRE kind=psp control=0x%X active_sp=0x%08X other_sp=0x%08X fpccr=0x%08X irq=%d' % (c.Control.RawValue, c.SP.RawValue, c.OtherSP.RawValue, c.FPCCR.RawValue, c.IRQ)"
EOF
    else
      cat <<'EOF'
# Exception 35 is external IRQ19, whose Vector8C is the default handler in
# this exact ELF. Explicitly give IRQ19 a lower priority and enable it before
# pending it. Renode represents HardFault with numeric priority 0 (instead of
# the architectural fixed -1), so the outer IRQ must not retain priority 0 if
# this scenario is to exercise architectural HardFault preemption.
sysbus WriteDoubleWord 0xE000E410 0x80000000
sysbus WriteDoubleWord 0xE000E100 0x00080000
nvic SetPendingIRQ 35
emulation RunFor "0.02"
python "c=monitor.Machine.SystemBus.GetCPUs()[0]; print 'ZS407_FAULT_PRE kind=msp control=0x%X active_sp=0x%08X other_sp=0x%08X fpccr=0x%08X irq=%d pc=0x%08X' % (c.Control.RawValue, c.SP.RawValue, c.OtherSP.RawValue, c.FPCCR.RawValue, c.IRQ, c.PC.RawValue)"
EOF
    fi
    cat <<'EOF'
sysbus WriteWord 0x20009000 0xBF00
sysbus WriteWord 0x20009002 0xE7FE
cpu PC 0x20009000
cpu SetRegisterUlong "r0" 0x10101010
cpu SetRegisterUlong "r1" 0x11111111
cpu SetRegisterUlong "r2" 0x22222222
cpu SetRegisterUlong "r3" 0x33333333
cpu SetRegisterUlong "r4" 0x44444444
cpu SetRegisterUlong "r5" 0x55555555
cpu SetRegisterUlong "r6" 0x66666666
cpu SetRegisterUlong "r7" 0x77777777
cpu SetRegisterUlong "r8" 0x88888888
cpu SetRegisterUlong "r9" 0x99999999
cpu SetRegisterUlong "r10" 0xAAAAAAAA
cpu SetRegisterUlong "r11" 0xBBBBBBBB
cpu SetRegisterUlong "r12" 0x12121212
cpu LR 0xEEEEEEEE
EOF
    if [ "$kind" = psp ]; then
      printf 'cpu SetRegisterUlong "s0" 0x3F800000\n'
    fi
    printf 'nvic SetPendingIRQ 3\n'
    cat <<EOF
emulation RunFor "0.5"
python "c=monitor.Machine.SystemBus.GetCPUs()[0]; print 'ZS407_FAULT_POST kind=$kind control=0x%X active_sp=0x%08X other_sp=0x%08X pc=0x%08X irq=%d fpccr=0x%08X' % (c.Control.RawValue, c.SP.RawValue, c.OtherSP.RawValue, c.PC.RawValue, c.IRQ, c.FPCCR.RawValue)"
spi1.spiFabric.lcd SaveScreenshot \$captureDir/fault-$kind.png
twinStatus SaveScreenRaw \$captureDir/fault-$kind.rgb565
EOF
    scan_address=$msp_base
    while [ "$scan_address" -lt "$msp_end" ]; do
      printf "python \"print 'ZS407_FAULT_MSP kind=%s address=0x%08X value=0x%%08X' %% monitor.Machine.SystemBus.ReadDoubleWord(0x%08X)\"\n" \
        "$kind" "$scan_address" "$scan_address"
      scan_address=$((scan_address + 4))
    done
    printf 'quit\n'
  } > "$scenario"
}

run_scenario() {
  kind=$1
  scenario=$output/fault-$kind.resc
  raw_log=$output/fault-$kind.raw.log
  log=$output/fault-$kind.log
  rm -f "$scenario" "$raw_log" "$log"
  write_scenario "$kind" "$scenario"

  console_fifo=$output/fault-$kind.console.$$
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
    if [ "$elapsed" -ge 360 ]; then
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
    die "$kind HardFault scenario timed out"
  }
  [ "$status" -eq 0 ] || {
    sed -n '1,260p' "$log" >&2
    die "$kind HardFault scenario exited with status $status"
  }
  if grep -Eq 'Errors during compilation|There was an error executing command|No such command or device:|Could not tokenize|ZS407 twin .* assertion failed' "$log"; then
    sed -n '1,320p' "$log" >&2
    die "$kind HardFault scenario reported an error"
  fi
}

run_scenario psp
run_scenario msp

python3 - "$output/fault-psp.log" "$output/fault-msp.log" "$report" \
  "$binary" "$elf" "$symbols" "$capture_dir" \
  "$msp_base_address" "$msp_end_address" "$msp_size" \
  "$heap_base_address" "$heap_end_address" "$heap_size" \
  "$handler_address" "$c_handler_address" "$vector_irq_address" "$unhandled_address" \
  "$minimum_msp_stack_free" <<'PY'
import hashlib
import pathlib
import re
import struct
import sys

(
    psp_log_path,
    msp_log_path,
    report_path,
    binary_path,
    elf_path,
    symbols_path,
    capture_dir_path,
    msp_base_text,
    msp_end_text,
    msp_size_text,
    heap_base_text,
    heap_end_text,
    heap_size_text,
    handler_text,
    c_handler_text,
    vector_irq_text,
    unhandled_text,
    minimum_msp_text,
) = sys.argv[1:]

msp_base = int(msp_base_text, 0)
msp_end = int(msp_end_text, 0)
msp_size = int(msp_size_text)
heap_base = int(heap_base_text, 0)
heap_end = int(heap_end_text, 0)
heap_size = int(heap_size_text)
minimum_msp = int(minimum_msp_text)
capture_dir = pathlib.Path(capture_dir_path)


def fail(message):
    raise SystemExit(f"HardFault qualification failed: {message}")


def parse_atomic(lines, prefix, fields):
    matches = [line.strip() for line in lines if line.strip().startswith(prefix + " ")]
    if len(matches) != 1:
        fail(f"expected one atomic {prefix} line, found {len(matches)}")
    values = {}
    for field in fields:
        match = re.search(rf"(?:^| ){re.escape(field)}=(0x[0-9A-Fa-f]+|[0-9]+)(?: |$)", matches[0])
        if not match:
            fail(f"{prefix} lacks {field}: {matches[0]!r}")
        values[field] = int(match.group(1), 0)
    return values


expected_frame = {
    "stacked_r0": 0x10101010,
    "stacked_r1": 0x11111111,
    "stacked_r2": 0x22222222,
    "stacked_r3": 0x33333333,
    "stacked_r12": 0x12121212,
    "stacked_lr": 0xEEEEEEEE,
    "stacked_pc": 0x20009000,
}
expected_saved = {
    "save4": 0x44444444,
    "save5": 0x55555555,
    "save6": 0x66666666,
    "save7": 0x77777777,
    "save8": 0x88888888,
    "save9": 0x99999999,
    "save10": 0xAAAAAAAA,
    "save11": 0xBBBBBBBB,
}
entry_fields = ["core", "callee", "exc_return", *expected_frame, "stacked_psr", *expected_saved]
scenario_results = {}

for kind, log_path in (("psp", psp_log_path), ("msp", msp_log_path)):
    lines = pathlib.Path(log_path).read_text(errors="replace").splitlines()
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
        fail(f"{kind} unexpected Renode warning(s): " + " | ".join(unexpected_warnings[:4]))
    pre_fields = ["control", "active_sp", "other_sp", "fpccr", "irq"]
    if kind == "msp":
        pre_fields.append("pc")
    pre = parse_atomic(lines, f"ZS407_FAULT_PRE kind={kind}", pre_fields)
    entry = parse_atomic(lines, f"ZS407_FAULT_ENTRY kind={kind}", entry_fields)
    post = parse_atomic(
        lines,
        f"ZS407_FAULT_POST kind={kind}",
        ["control", "active_sp", "other_sp", "pc", "irq", "fpccr"],
    )

    for field, wanted in {**expected_frame, **expected_saved}.items():
        if entry[field] != wanted:
            fail(f"{kind} {field}=0x{entry[field]:08X}, expected 0x{wanted:08X}")
    if entry["stacked_psr"] & (1 << 24) == 0:
        fail(f"{kind} stacked xPSR lacks the Thumb bit")
    if post["pc"] < int(c_handler_text, 0):
        fail(f"{kind} reporter did not execute the C HardFault handler")

    if kind == "psp":
        if pre["control"] & 0x6 != 0x6:
            fail(f"PSP scenario CONTROL 0x{pre['control']:X} does not select PSP+FP")
        if pre["fpccr"] & 0xC0000000 != 0xC0000000:
            fail(f"PSP scenario FPCCR 0x{pre['fpccr']:08X} lacks ASPEN/LSPEN")
        if entry["exc_return"] != 0xFFFFFFED:
            fail(f"PSP EXC_RETURN 0x{entry['exc_return']:08X}, expected 0xFFFFFFED")
        if entry["core"] != pre["active_sp"] - 104:
            fail("PSP core pointer does not identify the low/core portion of the extended frame")
        if entry["callee"] != msp_end - 32:
            fail("PSP r4-r11 save area is not the veneer allocation at the top of MSP")
        if entry["stacked_psr"] & 0x1FF:
            fail("PSP scenario did not stack a Thread-mode IPSR value of zero")
    else:
        if not (int(vector_irq_text, 0) <= pre["pc"] <= int(unhandled_text, 0) + 2):
            fail(f"MSP scenario PC 0x{pre['pc']:08X} is not the Vector8C default handler")
        if pre["active_sp"] != msp_end or pre["other_sp"] <= pre["active_sp"]:
            fail("MSP scenario did not establish Handler mode on MSP over a PSP thread frame")
        if entry["exc_return"] != 0xFFFFFFF1:
            fail(f"MSP nested EXC_RETURN 0x{entry['exc_return']:08X}, expected 0xFFFFFFF1")
        if entry["core"] != pre["active_sp"] - 32:
            fail("MSP core pointer does not identify the nested basic frame")
        if entry["callee"] != entry["core"] - 32:
            fail("MSP r4-r11 save area is not directly below the nested core frame")
        if entry["stacked_psr"] & 0x1FF != 35:
            fail("MSP scenario did not stack outer exception number 35 in IPSR")

    word_pattern = re.compile(
        rf"ZS407_FAULT_MSP kind={kind} address=(0x[0-9A-Fa-f]{{8}}) value=(0x[0-9A-Fa-f]{{8}})"
    )
    words = []
    addresses = []
    for line in lines:
        match = word_pattern.fullmatch(line.strip())
        if match:
            addresses.append(int(match.group(1), 16))
            words.append(int(match.group(2), 16))
    if len(words) != msp_size // 4:
        fail(f"{kind} MSP scan returned {len(words)} words, expected {msp_size // 4}")
    if addresses != list(range(msp_base, msp_end, 4)):
        fail(f"{kind} MSP scan addresses are incomplete, duplicated, or out of order")
    untouched = 0
    for word in words:
        if word != 0x55555555:
            break
        untouched += 4
    if untouched < minimum_msp:
        fail(f"{kind} MSP free margin {untouched} < {minimum_msp} bytes")

    raw_path = capture_dir / f"fault-{kind}.rgb565"
    png_path = capture_dir / f"fault-{kind}.png"
    if raw_path.stat().st_size != 480 * 320 * 2:
        fail(f"{kind} raw screen is not exactly 480x320 RGB565")
    raw = raw_path.read_bytes()
    unique_pixels = len(set(struct.unpack(f"<{len(raw) // 2}H", raw)))
    if unique_pixels < 8:
        fail(f"{kind} fatal screen is flat ({unique_pixels} unique RGB565 values)")
    png = png_path.read_bytes()
    if png[:8] != b"\x89PNG\r\n\x1a\n" or len(png) < 24:
        fail(f"{kind} screenshot is not a PNG")
    width, height = struct.unpack(">II", png[16:24])
    if (width, height) != (480, 320):
        fail(f"{kind} PNG dimensions are {width}x{height}, expected 480x320")

    scenario_results[kind] = {
        "exc_return": entry["exc_return"],
        "core": entry["core"],
        "callee": entry["callee"],
        "stacked_pc": entry["stacked_pc"],
        "stacked_psr": entry["stacked_psr"],
        "msp_free": untouched,
        "unique_pixels": unique_pixels,
        "raw_sha": hashlib.sha256(raw).hexdigest(),
        "png_sha": hashlib.sha256(png).hexdigest(),
        "warning_count": len(warning_lines),
    }


def digest(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


report_lines = [
    "schema=tinysa-chibios-hardfault-v1",
    "result=PASS",
    "environment=RENODE_DIGITAL_TWIN",
    "hardware_qualified=NO",
    "release_seal=NOT_EVALUATED",
    f"candidate_binary_bytes={pathlib.Path(binary_path).stat().st_size}",
    f"candidate_binary_sha256={digest(binary_path)}",
    f"candidate_elf_sha256={digest(elf_path)}",
    f"candidate_symbols_sha256={digest(symbols_path)}",
    f"hardfault_handler=0x{int(handler_text, 0):08X}",
    f"hardfault_c_handler=0x{int(c_handler_text, 0):08X}",
    f"vector8c_external_irq19=0x{int(vector_irq_text, 0):08X}",
    f"unhandled_exception=0x{int(unhandled_text, 0):08X}",
    f"msp_base=0x{msp_base:08X}",
    f"msp_end=0x{msp_end:08X}",
    f"msp_size_bytes={msp_size}",
    f"heap_base=0x{heap_base:08X}",
    f"heap_end=0x{heap_end:08X}",
    f"heap_size_bytes={heap_size}",
    "memory_layout=PASS",
    "veneer_disassembly=PASS",
    "renode_hardfault_priority_model=NUMERIC_ZERO",
    "handler_origin_outer_exception=35",
    "handler_origin_outer_irq_priority=0x80",
    "handler_origin_priority_workaround=YES",
    "callee_r4_r11=44444444,55555555,66666666,77777777,88888888,99999999,AAAAAAAA,BBBBBBBB",
]
for kind in ("psp", "msp"):
    result = scenario_results[kind]
    report_lines.extend(
        [
            f"{kind}_fault_frame=PASS",
            f"{kind}_callee_registers=PASS",
            f"{kind}_exc_return=0x{result['exc_return']:08X}",
            f"{kind}_core_frame=0x{result['core']:08X}",
            f"{kind}_callee_frame=0x{result['callee']:08X}",
            f"{kind}_stacked_pc=0x{result['stacked_pc']:08X}",
            f"{kind}_stacked_xpsr=0x{result['stacked_psr']:08X}",
            f"{kind}_msp_stack_free_bytes={result['msp_free']}",
            f"{kind}_msp_stack_minimum_bytes={minimum_msp}",
            f"{kind}_fatal_screen_unique_pixels={result['unique_pixels']}",
            f"{kind}_fatal_screen_raw_sha256={result['raw_sha']}",
            f"{kind}_fatal_screen_png_sha256={result['png_sha']}",
            f"{kind}_known_model_warning_count={result['warning_count']}",
            f"{kind}_unexpected_model_warning_count=0",
        ]
    )
pathlib.Path(report_path).write_text("\n".join(report_lines) + "\n")
PY

cat "$report"
printf 'psp_scenario=%s\n' "$output/fault-psp.resc"
printf 'msp_scenario=%s\n' "$output/fault-msp.resc"
printf 'psp_log=%s\n' "$output/fault-psp.log"
printf 'msp_log=%s\n' "$output/fault-msp.log"
printf 'report=%s\n' "$report"
