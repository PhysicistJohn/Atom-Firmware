#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$ROOT/tools/lib.sh"
. "$ROOT/tools/twin-client-lib.sh"

TINYSA_ARTIFACTS_DIR=${TINYSA_ARTIFACTS_DIR:-"$ROOT/.artifacts"}
export TINYSA_ARTIFACTS_DIR

usage() {
  status=${1:-2}
  printf 'Usage: %s --candidate-bin PATH --candidate-elf PATH --candidate-symbols PATH [options]\n' "$0" >&2
  printf 'Options:\n' >&2
  printf '  --reference-bin PATH       override the pinned v0.2 reference binary\n' >&2
  printf '  --reference-elf PATH       override the pinned v0.2 reference ELF\n' >&2
  printf '  --reference-symbols PATH   Renode symbol-profile include for the reference\n' >&2
  printf '  --twin-root PATH           clean Atom-TinySA-Twin checkout used for execution\n' >&2
  printf '  --output PATH              artifact directory (default: .artifacts/digital-twin/selftest-visual)\n' >&2
  exit "$status"
}

absolute_file() {
  _directory=$(CDPATH= cd -- "$(dirname -- "$1")" && pwd)
  printf '%s/%s\n' "$_directory" "$(basename -- "$1")"
}

reference_bin=
reference_elf=
reference_symbols=
candidate_bin=
candidate_elf=
candidate_symbols=
twin_root=
output="$ROOT/.artifacts/digital-twin/selftest-visual"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --reference-bin)
      [ "$#" -ge 2 ] || usage
      reference_bin=$2
      shift 2
      ;;
    --reference-elf)
      [ "$#" -ge 2 ] || usage
      reference_elf=$2
      shift 2
      ;;
    --reference-symbols)
      [ "$#" -ge 2 ] || usage
      reference_symbols=$2
      shift 2
      ;;
    --candidate-bin)
      [ "$#" -ge 2 ] || usage
      candidate_bin=$2
      shift 2
      ;;
    --candidate-elf)
      [ "$#" -ge 2 ] || usage
      candidate_elf=$2
      shift 2
      ;;
    --candidate-symbols)
      [ "$#" -ge 2 ] || usage
      candidate_symbols=$2
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
    -h|--help)
      usage 0
      ;;
    *)
      usage
      ;;
  esac
done

[ -n "$candidate_bin" ] || usage
[ -n "$candidate_elf" ] || usage
[ -n "$candidate_symbols" ] || usage
[ -n "$twin_root" ] || usage
[ -f "$candidate_bin" ] || die "candidate binary not found: $candidate_bin"
[ -f "$candidate_elf" ] || die "candidate ELF not found: $candidate_elf"
[ -f "$candidate_symbols" ] || die "candidate symbol profile not found: $candidate_symbols"
candidate_bin=$(absolute_file "$candidate_bin")
candidate_elf=$(absolute_file "$candidate_elf")
candidate_symbols=$(absolute_file "$candidate_symbols")
capture_twin_identity "$twin_root"
twin_root=$TWIN_ROOT

if [ -z "$reference_bin" ] || [ -z "$reference_elf" ]; then
  reference_info=$("$twin_root/tools/fetch-digital-twin-firmware.sh")
  [ -n "$reference_bin" ] || reference_bin=$(printf '%s\n' "$reference_info" | sed -n 's/^binary=//p')
  [ -n "$reference_elf" ] || reference_elf=$(printf '%s\n' "$reference_info" | sed -n 's/^elf=//p')
fi
[ -f "$reference_bin" ] || die "reference binary not found: $reference_bin"
[ -f "$reference_elf" ] || die "reference ELF not found: $reference_elf"
reference_bin=$(absolute_file "$reference_bin")
reference_elf=$(absolute_file "$reference_elf")
if [ -n "$reference_symbols" ]; then
  [ -f "$reference_symbols" ] || die "reference symbol profile not found: $reference_symbols"
  reference_symbols=$(absolute_file "$reference_symbols")
fi

case "$output" in
  /*) ;;
  *) output="$ROOT/$output" ;;
esac
mkdir -p "$output/reference" "$output/candidate" "$output/comparison"

for variant in reference candidate comparison; do
  for case_number in 01 02 03 04 05 06 07 08 09 10 11 12 13 14; do
    rm -f "$output/$variant/case-$case_number.png" \
      "$output/$variant/case-$case_number.rgb565" \
      "$output/$variant/case-$case_number-measured.f32le" \
      "$output/$variant/case-$case_number-diff.png"
  done
done
rm -f "$output/reference/run.log" "$output/reference/run.raw.log" \
  "$output/candidate/run.log" "$output/candidate/run.raw.log" \
  "$output/comparison/report.json" "$output/comparison/report.md" \
  "$output/comparison/index.html" \
  "$output/comparison/contact-cases-01-07.png" \
  "$output/comparison/contact-cases-08-14.png" \
  "$output/SHA256SUMS"

if [ -n "${RENODE_RUNTIME:-}" ]; then
  runtime=$RENODE_RUNTIME
  runtime_source=caller-supplied
else
  runtime=$("$twin_root/tools/bootstrap-renode.sh")
  runtime_source=twin-bootstrap
fi
[ -x "$runtime/renode" ] || die "Renode runtime is incomplete: $runtime"
runtime=$(CDPATH= cd -- "$runtime" && pwd)
capture_twin_runtime_identity "$runtime" "$runtime_source"

run_variant() {
  variant=$1
  binary=$2
  elf=$3
  symbols=$4
  capture="$output/$variant"
  scenario="$capture/run.resc"
  raw_log="$capture/run.raw.log"
  log="$capture/run.log"

  {
    write_twin_scenario_provenance
    printf '$bin = @%s\n' "$binary"
    printf '$elf = @%s\n' "$elf"
    printf '$captureDir = @%s\n' "$capture"
    if [ -n "$symbols" ]; then
      printf '$symbols = @%s\n' "$symbols"
    fi
    printf 'include @%s/digital-twin/renode/zs407.resc\n' "$twin_root"
    printf 'include @%s/digital-twin/renode/tests/selftest-visual-body.resc\n' "$twin_root"
  } > "$scenario"

  console_fifo="$capture/console.$$"
  mkfifo "$console_fifo"
  exec 3<>"$console_fifo"
  rm -f "$console_fifo"

  printf 'selftest_visual_variant=%s\n' "$variant"
  set +e
  HOME="$runtime/home" DOTNET_BUNDLE_EXTRACT_BASE_DIR="$runtime/dotnet-bundle" \
    "$runtime/renode" --config "$runtime/config" --disable-xwt --console --plain \
    "$scenario" <&3 >"$raw_log" 2>&1
  status=$?
  set -e
  exec 3>&-
  tr -d '\r' < "$raw_log" > "$log"

  if [ "$status" -ne 0 ]; then
    sed -n '1,280p' "$log" >&2
    die "$variant Renode run exited with status $status"
  fi
  if grep -Eq 'Errors during compilation|There was an error executing command|No such command or device:|ZS407 twin .* assertion failed' "$log"; then
    sed -n '1,320p' "$log" >&2
    die "$variant Renode run reported an error"
  fi
  pass_count=$(grep -c 'ZS407_TWIN_SELFTEST=PASS case=' "$log" || true)
  ready_count=$(grep -c 'ZS407_TWIN_SELFTEST_VISUAL=READY case=' "$log" || true)
  settled_count=$(grep -c 'ZS407_TWIN_SELFTEST_DISPLAY=VISUALLY_SETTLED case=' "$log" || true)
  status_count=$(grep -c 'ZS407_TWIN_SELFTEST_STATUS case=' "$log" || true)
  screen_count=$(grep -c 'ZS407_TWIN_SCREEN=SAVED' "$log" || true)
  trace_memory_count=$(grep -c 'ZS407_TWIN_SELFTEST_TRACE_MEMORY=SAVED case=' "$log" || true)
  [ "$pass_count" -eq 14 ] || die "$variant reported $pass_count/14 passing self-tests"
  [ "$ready_count" -eq 14 ] || die "$variant retained $ready_count/14 visual result screens"
  [ "$settled_count" -eq 14 ] || die "$variant proved $settled_count/14 visually settled result screens"
  [ "$status_count" -eq 14 ] || die "$variant reported $status_count/14 visual metrics"
  [ "$screen_count" -eq 14 ] || die "$variant saved $screen_count/14 raw LCD frames"
  [ "$trace_memory_count" -eq 14 ] || die "$variant saved $trace_memory_count/14 trace-memory matrices"
  printf '%s_selftests=14/14\n' "$variant"
}

run_variant reference "$reference_bin" "$reference_elf" "$reference_symbols"
run_variant candidate "$candidate_bin" "$candidate_elf" "$candidate_symbols"
verify_twin_identity
verify_twin_runtime_identity "$runtime"

set +e
python3 "$ROOT/tools/compare-selftest-visuals.py" \
  --reference "$output/reference" \
  --candidate "$output/candidate" \
  --output "$output/comparison" \
  --reference-bin "$reference_bin" \
  --reference-elf "$reference_elf" \
  --candidate-bin "$candidate_bin" \
  --candidate-elf "$candidate_elf"
comparison_status=$?
set -e

checksums="$output/SHA256SUMS"
: > "$checksums"
for variant in reference candidate; do
  printf '%s  %s\n' "$(sha256_file "$output/$variant/run.resc")" \
    "$variant/run.resc" >> "$checksums"
  for case_number in 01 02 03 04 05 06 07 08 09 10 11 12 13 14; do
    for extension in png rgb565 measured.f32le; do
      case "$extension" in
        measured.f32le) artifact="$output/$variant/case-$case_number-$extension" ;;
        *) artifact="$output/$variant/case-$case_number.$extension" ;;
      esac
      [ -f "$artifact" ] || continue
      relative=${artifact#"$output"/}
      printf '%s  %s\n' "$(sha256_file "$artifact")" \
        "$relative" >> "$checksums"
    done
  done
done
for artifact in "$output"/comparison/case-??-diff.png \
  "$output"/comparison/contact-cases-??-??.png \
  "$output"/comparison/report.json \
  "$output"/comparison/report.md \
  "$output"/comparison/index.html; do
  [ -f "$artifact" ] || continue
  relative=${artifact#"$output"/}
  printf '%s  %s\n' "$(sha256_file "$artifact")" "$relative" >> "$checksums"
done
printf 'checksums=%s\n' "$checksums"
exit "$comparison_status"
