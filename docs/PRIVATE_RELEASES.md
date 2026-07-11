# Private phase-image release policy

Each cumulative phase has an annotated tag and a private GitHub prerelease in
`PhysicistJohn/TinySA_Firmware`. A release contains the committed phase's BIN,
ELF, HEX, manifest, section report and stack report. Phases with output code
also contain the binary output-lock audit; Phase 6 contains the complete phase
matrix.

`tools/publish-phase-release.sh N` refuses to publish unless all of these are
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
