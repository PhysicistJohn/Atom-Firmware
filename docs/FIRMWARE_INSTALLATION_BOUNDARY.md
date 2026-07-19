# Firmware installation boundary

`Atom-Firmware` owns source, deterministic builds, simulation and physical
qualification records, and strict custom-build packaging. It does not own a
device updater.

The only supported handoff is:

1. Commit a clean F303/ZS407 source tree.
2. Run `tools/package-flasher-build.sh VERSION`.
3. Select the emitted `tinysa-flasher-build-v1.json` in standalone sibling
   `../Atom-Flasher`.

The JSON manifest, adjacent content-addressed BIN, and any immutable
qualification evidence are the complete Firmware-to-Flasher contract. A raw
BIN is not an installable custom target. Build success, an embedded version,
or historical hardware evidence cannot substitute for manifest admission.

Atom-Flasher exclusively owns artifact admission, CDC and DFU preflight,
native operator confirmation, physical writes, durable recovery journals, and
post-reboot continuity verification. `make flash`, `prog.sh`, the retired
`tools/flash-physical-dfu-evidence.py` path, and editor launch-to-program tasks
all fail closed or have been removed. Debugger configurations are attach-only.

The RC5 qualification bundle is an evidence archive. Its old candidate
predates the current custom-build manifest and is deliberately not presented
as installable. Its recorded transfers and read-backs remain historical facts;
they are not current instructions or authority to repeat a write.

This boundary also applies to future firmware targets. Supporting another
device or MCU requires a new reviewed manifest/interface version and matching
Atom-Flasher admission path; it must not reintroduce a Firmware-side writer.
