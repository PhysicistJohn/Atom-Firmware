#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$ROOT/tools/lib.sh"

case "${1:---smoke}" in
  --smoke)
    name=boot
    markers='ZS407_TWIN_BOOT=PASS'
    ;;
  --full)
    name=full
    markers='ZS407_TWIN_BOOT=PASS ZS407_TWIN_JOG=PASS ZS407_TWIN_TOUCH=PASS ZS407_TWIN_UI_NORMAL=PASS ZS407_TWIN_RF_TONE=PASS'
    ;;
  --selftest)
    name=selftest
    markers='ZS407_TWIN_BOOT=PASS ZS407_TWIN_CAL_LOOPBACK=disconnected ZS407_TWIN_SELFTEST=PASS ZS407_TWIN_SELFTEST_FAILURE=PASS ZS407_TWIN_CAL_LOOPBACK=connected'
    ;;
  --usb)
    name=usb
    markers='ZS407_TWIN_BOOT=PASS ZS407_TWIN_USB_DESCRIPTOR=PASS ZS407_TWIN_USB_ENUM=PASS ZS407_TWIN_USB_CDC=PASS ZS407_TWIN_USB_STALL=PASS ZS407_TWIN_USB_EVENTS=PASS'
    ;;
  *)
    printf 'Usage: %s [--smoke|--full|--selftest|--usb]\n' "$0" >&2
    exit 2
    ;;
esac

"$ROOT/tools/fetch-digital-twin-firmware.sh" >/dev/null
runtime=$($ROOT/tools/bootstrap-renode.sh)
output="$ROOT/.artifacts/digital-twin"
raw_log="$output/$name.raw.log"
log="$output/$name.log"
mkdir -p "$output"

# Renode 1.16.1's redirected console thread can overflow an internal semaphore
# after several minutes if stdin is already at EOF. Keep an otherwise idle
# bidirectional FIFO descriptor open for the duration of unattended runs.
console_fifo="$output/$name.console.$$"
mkfifo "$console_fifo"
exec 3<>"$console_fifo"
rm -f "$console_fifo"

cd "$ROOT"
set +e
HOME="$runtime/home" DOTNET_BUNDLE_EXTRACT_BASE_DIR="$runtime/dotnet-bundle" \
  "$runtime/renode" --config "$runtime/config" --disable-xwt --console --plain \
  "$ROOT/digital-twin/renode/tests/$name.resc" <&3 >"$raw_log" 2>&1
status=$?
set -e
exec 3>&-
tr -d '\r' <"$raw_log" >"$log"

if [ "$status" -ne 0 ]; then
  sed -n '1,240p' "$log" >&2
  die "Renode exited with status $status"
fi

if grep -Eq 'Errors during compilation|There was an error executing command|No such command or device:|ZS407 twin .* assertion failed' "$log"; then
  sed -n '1,260p' "$log" >&2
  die 'digital-twin scenario reported an error'
fi

for marker in $markers; do
  grep -Fq "$marker" "$log" || {
    sed -n '1,260p' "$log" >&2
    die "missing digital-twin result marker: $marker"
  }
done

grep -E 'ZS407_TWIN_(BOOT|JOG|TOUCH|UI_NORMAL|RF_TONE|CAL_LOOPBACK|SELFTEST|USB|STATUS)' "$log"
printf 'digital_twin_%s=passed\n' "$name"
printf 'log=%s\n' "$log"
