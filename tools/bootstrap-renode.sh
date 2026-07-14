#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$ROOT/tools/lib.sh"
. "$ROOT/tools/twin-client-lib.sh"

TINYSA_ARTIFACTS_DIR=${TINYSA_ARTIFACTS_DIR:-"$ROOT/.artifacts"}
export TINYSA_ARTIFACTS_DIR
twin_root=$(resolve_external_twin_root \
  "${TINYSA_TWIN_ROOT:-$ROOT/../TinySA_Twin}" "$ROOT")
exec "$twin_root/tools/bootstrap-renode.sh" "$@"
