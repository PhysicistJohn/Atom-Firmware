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
  --passive)
    name=passive
    markers='ZS407_TWIN_BOOT=PASS ZS407_PASSIVE_HOOK=PASS ZS407_TWIN_PASSIVE=PASS ZS407_TWIN_RF_TONE=PASS'
    ;;
  *)
    printf 'Usage: %s [--smoke|--full|--passive]\n' "$0" >&2
    exit 2
    ;;
esac

if [ "$name" != passive ]; then
  "$ROOT/tools/fetch-digital-twin-firmware.sh" >/dev/null
fi
runtime=$($ROOT/tools/bootstrap-renode.sh)
output="$ROOT/.artifacts/digital-twin"
raw_log="$output/$name.raw.log"
log="$output/$name.log"
mkdir -p "$output"

cd "$ROOT"
set +e
"$runtime/renode" --disable-xwt --console --plain \
  "$ROOT/digital-twin/renode/tests/$name.resc" >"$raw_log" 2>&1
status=$?
set -e
tr -d '\r' <"$raw_log" >"$log"

if [ "$status" -ne 0 ]; then
  sed -n '1,240p' "$log" >&2
  die "Renode exited with status $status"
fi

if grep -Eq 'Errors during compilation|There was an error executing command|ZS407 twin .* assertion failed' "$log"; then
  sed -n '1,260p' "$log" >&2
  die 'digital-twin scenario reported an error'
fi

for marker in $markers; do
  grep -Fq "$marker" "$log" || {
    sed -n '1,260p' "$log" >&2
    die "missing digital-twin result marker: $marker"
  }
done

grep -E 'ZS407_(TWIN_(BOOT|JOG|TOUCH|UI_NORMAL|RF_TONE|PASSIVE|STATUS)|PASSIVE_HOOK)' "$log"
printf 'digital_twin_%s=passed\n' "$name"
printf 'log=%s\n' "$log"
