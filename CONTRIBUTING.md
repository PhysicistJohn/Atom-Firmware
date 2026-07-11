# Personal contribution and publication policy

This is personal work owned by the GitHub account `PhysicistJohn`. It must not
be pushed, forked, or opened as a pull request using a Keysight or other
corporate identity.

The local repository is deliberately configured with:

- author `PhysicistJohn <54456354+PhysicistJohn@users.noreply.github.com>`;
- the official repository named `upstream` for fetch only;
- a disabled push URL;
- the repository hook path `.githooks`;
- a pre-push hook that rejects every push;
- the local credential helper disabled.

These local settings are defense in depth, not a substitute for checking the
active GitHub identity. Before publication:

1. authenticate an isolated SSH host alias or credential explicitly belonging
   to `PhysicistJohn`;
2. create or verify the PhysicistJohn fork in a browser/session showing that
   account;
3. add it as `origin` while retaining the official project as `upstream`;
4. review `git config --local --list`, `git remote -v`, and the proposed commits;
5. remove or deliberately amend the pre-push guard only for that reviewed
   personal remote;
6. perform a dry-run and verify the destination owner before the real push.

## Commit structure

- Personal research, tooling, and roadmap commits stay on PhysicistJohn branches.
- Upstream candidates use separate branches based on `upstream/main`.
- Do not mix generated toolchains, downloaded firmware, Ghidra projects, device
  captures containing identifiers, or secrets into commits.
- Preserve upstream authorship and history; do not squash the imported project
  into a new unattributed code dump.
- Do not describe personal firmware as official or use the tinySA trademark in
  a way that implies endorsement.
