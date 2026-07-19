# External ZS407 executable digital twin

The Renode implementation, peripheral models, scenarios, runtime bootstrap,
and detailed fidelity documentation now live in the adjacent `Atom-TinySA-Twin`
repository. This firmware repository owns the exact BIN/ELF/symbol artifacts,
release policy, simulation acceptance criteria, physical comparison, and
hardware qualification.

## Local checkout contract

The default sibling layout is:

```text
Atom-Firmware/
Atom-TinySA-Twin/
```

Set `TINYSA_TWIN_ROOT` to use another checkout. The legacy commands remain as
thin delegates, so existing Atomizer and developer workflows continue to work:

```sh
tools/test-digital-twin.sh --smoke
tools/test-digital-twin.sh --full
tools/test-digital-twin.sh --selftest
tools/test-digital-twin.sh --usb
tools/run-digital-twin.sh
```

By default those delegates share this repository's ignored `.artifacts` cache.
Set `TINYSA_ARTIFACTS_DIR` to override it. Every pinned firmware artifact is
still size- and SHA-256-verified by the Twin fetcher.

Firmware candidate qualifiers take an explicit Twin checkout:

```sh
tools/qualify-chibios-general.sh ... --twin-root ../Atom-TinySA-Twin ...
tools/qualify-chibios-runtime-state.sh ... --twin-root ../Atom-TinySA-Twin ...
tools/qualify-chibios-fault-handler.sh ... --twin-root ../Atom-TinySA-Twin ...
tools/test-selftest-visual-regression.sh ... --twin-root ../Atom-TinySA-Twin
```

Qualification refuses uncommitted Twin execution paths and records the exact
Twin commit, `digital-twin/renode` tree, complete `tools` tree, and
Renode-bootstrap blob in generated scenarios and reports. The executed Renode
binary hash and whether it came from that bootstrap or `--runtime` are recorded
separately. Firmware and simulation provenance are therefore bound
independently after the repository split.

## Compatibility boundary

The active trio-composition contract is version 4 and is byte-identical in
Atom-Atomizer, Atom-Firmware, and Atom-SignalLab. Atomizer currently looks up bridge
launchers and `digital-twin/contracts/atomizer-twin-v1.json` under
`Atom-Firmware`, so those compatibility paths remain here and delegate
execution to `Atom-TinySA-Twin`. Atom-TinySA-Twin is an implementation dependency behind
Firmware's owned bridge, not a separate runtime-composition party. Contractual
ownership moves only in a coordinated new trio-contract version across the
three runtime repositories and a corresponding Atom-TinySA-Twin implementation
update.

The full model inventory, exact boot signature, RF/CAL/USB behavior, expected
Renode warnings, interactive commands, and emulator-specific upstream queue
are documented in `../Atom-TinySA-Twin/README.md` and
`../Atom-TinySA-Twin/docs/DIGITAL_TWIN.md`.
