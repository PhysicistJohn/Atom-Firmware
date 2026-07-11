#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

"$ROOT/tools/fetch-digital-twin-firmware.sh" >/dev/null
runtime=$($ROOT/tools/bootstrap-renode.sh)

cd "$ROOT"
exec "$runtime/renode" --disable-xwt --console --plain \
  "$ROOT/digital-twin/renode/zs407.resc"
