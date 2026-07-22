# Historical private phase-image release policy

This policy describes the immutable Phase 0–6 archive created before the
repository became `PhysicistJohn/Atom-Firmware`. Its repository names,
visibility checks, tags, and release scripts are preserved as provenance and
are not the current publishing workflow. New custom builds use the v2 manifest
and are handed to Atom-Flasher as documented in
[`FIRMWARE_INSTALLATION_BOUNDARY.md`](FIRMWARE_INSTALLATION_BOUNDARY.md).

Each archived cumulative phase has an annotated tag and a private GitHub
prerelease in `PhysicistJohn/TinySA_Firmware`. A release contains the committed phase's BIN,
ELF, HEX, manifest, section report and stack report. Phases with output code
also contain the binary output-lock audit; Phase 6 contains the complete phase
matrix.

The frozen `tools/publish-phase-release.sh N` script refuses to publish unless all of these are
true:

- authenticated GitHub user is exactly `PhysicistJohn`;
- repository is exactly `PhysicistJohn/TinySA_Firmware` and reports private;
- origin fetch/push URL is the exact personal repository URL;
- upstream push URL is `no_push`;
- phase tag identifies the exact phase branch tip;
- ancestry and every local artifact hash pass the phase-chain audit;
- manifest says the build was reproducible and hardware qualification is false;
- Phase 5 and later include a passing binary output-lock audit.

The command is idempotent: an existing prerelease is updated and assets are
replaced only after the same checks. `--dry-run` performs all checks without
changing GitHub.

Every release title and body says **NO FLASH / NOT HARDWARE QUALIFIED**. GitHub
source archives are convenience snapshots; the manifest hashes identify the
firmware artifacts. A GitHub release does not qualify hardware, authorize RF
emissions or create an update path on the analyzer.
