#!/bin/sh
set -eu

printf '%s\n' 'Direct firmware writes are disabled in Atom-Firmware.' >&2
printf '%s\n' 'Package the committed Phase 6 image, then import its manifest into ../Atom-Flasher.' >&2
exit 2
