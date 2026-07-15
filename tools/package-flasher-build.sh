#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$ROOT/tools/lib.sh"

usage() {
  printf 'Usage: %s VERSION [--simulation-passed] [--hardware-qualified EVIDENCE] [-- MAKE_ARGUMENT...]\n' "$0"
  printf 'Build a clean F303/ZS407 image twice and emit a no-auto-flash TinySA Flasher manifest.\n'
}

[ "$#" -ge 1 ] || { usage >&2; exit 2; }
version=$1
shift
simulation_passed=false
hardware_evidence=
make_arguments=
while [ "$#" -gt 0 ]; do
  case "$1" in
    --simulation-passed) simulation_passed=true; shift ;;
    --hardware-qualified)
      [ "$#" -ge 2 ] || die '--hardware-qualified requires an evidence file'
      hardware_evidence=$2
      shift 2
      ;;
    --)
      shift
      make_arguments="$*"
      break
      ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown package option: $1" ;;
  esac
done

case " $make_arguments " in
  *' TARGET='*|*' VERSION='*) die 'TARGET and VERSION are owned by the Flasher packaging gate' ;;
esac

git -C "$ROOT" diff --quiet -- || die 'tracked firmware worktree changes must be committed before packaging'
git -C "$ROOT" diff --cached --quiet -- || die 'staged firmware changes must be committed before packaging'
git -C "$ROOT" submodule status ChibiOS | grep -q '^ ' || \
  die 'initialize the exact ChibiOS submodule before packaging'

commit=$(git -C "$ROOT" rev-parse HEAD)
short_commit=$(printf '%s' "$commit" | cut -c1-7)
case "$version" in
  tinySA4_*-g"$short_commit") ;;
  *) die "VERSION must end in -g$short_commit for current commit $commit" ;;
esac
chibios_commit=$(git -C "$ROOT/ChibiOS" rev-parse HEAD)
source_date_epoch=$(git -C "$ROOT" show -s --format=%ct HEAD)
toolchain_bin=$($ROOT/tools/bootstrap-toolchain.sh)
export PATH="$toolchain_bin:$PATH"
export LC_ALL=C
toolchain=$(arm-none-eabi-gcc --version | sed -n '1p')
first_binary="$ROOT/.artifacts/flasher-build-first-$$.bin"
trap 'rm -f "$first_binary"' EXIT HUP INT TERM

build_once() {
  make -C "$ROOT" TARGET=F303 clean >/dev/null
  # Intentional word splitting: make arguments are operator-provided NAME=VALUE
  # tokens accepted only after `--`; TARGET and VERSION are rejected above.
  # shellcheck disable=SC2086
  SOURCE_DATE_EPOCH="$source_date_epoch" make -C "$ROOT" TARGET=F303 VERSION="$version" $make_arguments -j"$(host_jobs)"
}

build_once
binary="$ROOT/build/tinySA4.bin"
elf="$ROOT/build/tinySA4.elf"
[ -f "$binary" ] && [ -f "$elf" ] || die 'F303 build did not produce tinySA4 BIN and ELF'
[ -z "$(arm-none-eabi-nm -u "$elf")" ] || die 'firmware ELF contains unresolved symbols'
cp "$binary" "$first_binary"
first_hash=$(sha256_file "$first_binary")

build_once
second_hash=$(sha256_file "$binary")
[ "$first_hash" = "$second_hash" ] || die "two clean firmware builds differ ($first_hash != $second_hash)"

set -- \
  --binary "$binary" \
  --version "$version" \
  --source-commit "$commit" \
  --chibios-commit "$chibios_commit" \
  --source-date-epoch "$source_date_epoch" \
  --toolchain "$toolchain" \
  --output-root "$ROOT/.artifacts/flasher-builds"
[ "$simulation_passed" = true ] && set -- "$@" --simulation-passed
[ -z "$hardware_evidence" ] || set -- "$@" --hardware-qualified-evidence "$hardware_evidence"
python3 "$ROOT/tools/write-flasher-build-manifest.py" "$@"
printf 'reproducible_clean_builds=true\n'
printf 'automated_flash=false\n'
