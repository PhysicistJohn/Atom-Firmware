#!/bin/sh

# Cross-repository helpers for firmware-owned qualification clients. The caller
# must source tools/lib.sh first so failures use the common die() formatter.

resolve_twin_root() {
  requested_root=$1
  [ -d "$requested_root" ] || die "twin root not found: $requested_root"
  (CDPATH= cd -- "$requested_root" && pwd)
}

resolve_external_twin_root() {
  external_root=$(resolve_twin_root "$1")
  owner_root=$(CDPATH= cd -- "$2" && pwd)
  [ "$external_root" != "$owner_root" ] || \
    die 'TINYSA_TWIN_ROOT resolves a compatibility launcher back to TinySA_Firmware'
  printf '%s\n' "$external_root"
}

capture_twin_identity() {
  TWIN_ROOT=$(resolve_twin_root "$1")
  command -v git >/dev/null 2>&1 || die 'git is required to bind twin provenance'
  [ "$(git -C "$TWIN_ROOT" rev-parse --is-inside-work-tree 2>/dev/null)" = true ] || \
    die "twin root is not a Git worktree: $TWIN_ROOT"

  twin_dirty=$(git -C "$TWIN_ROOT" status --porcelain --untracked-files=all -- \
    digital-twin/renode tools)
  [ -z "$twin_dirty" ] || \
    die 'twin execution paths must be committed and clean before qualification'

  TWIN_SOURCE_COMMIT=$(git -C "$TWIN_ROOT" rev-parse HEAD)
  TWIN_RENODE_TREE=$(git -C "$TWIN_ROOT" rev-parse HEAD:digital-twin/renode)
  TWIN_TOOLS_TREE=$(git -C "$TWIN_ROOT" rev-parse HEAD:tools)
  TWIN_BOOTSTRAP_BLOB=$(git -C "$TWIN_ROOT" rev-parse HEAD:tools/bootstrap-renode.sh)
}

verify_twin_identity() {
  expected_commit=$TWIN_SOURCE_COMMIT
  expected_tree=$TWIN_RENODE_TREE
  expected_tools=$TWIN_TOOLS_TREE
  expected_bootstrap=$TWIN_BOOTSTRAP_BLOB
  capture_twin_identity "$TWIN_ROOT"
  [ "$TWIN_SOURCE_COMMIT" = "$expected_commit" ] && \
    [ "$TWIN_RENODE_TREE" = "$expected_tree" ] && \
    [ "$TWIN_TOOLS_TREE" = "$expected_tools" ] && \
    [ "$TWIN_BOOTSTRAP_BLOB" = "$expected_bootstrap" ] || \
    die 'twin identity changed during qualification'
}

capture_twin_runtime_identity() {
  runtime_root=$1
  runtime_source=$2
  case "$runtime_source" in
    twin-bootstrap|caller-supplied) ;;
    *) die "invalid Renode runtime source: $runtime_source" ;;
  esac
  [ -x "$runtime_root/renode" ] || \
    die "Renode runtime is incomplete: $runtime_root"
  TWIN_RUNTIME_SOURCE=$runtime_source
  TWIN_RUNTIME_SHA256=$(sha256_file "$runtime_root/renode")
}

verify_twin_runtime_identity() {
  expected_source=$TWIN_RUNTIME_SOURCE
  expected_sha256=$TWIN_RUNTIME_SHA256
  capture_twin_runtime_identity "$1" "$expected_source"
  [ "$TWIN_RUNTIME_SHA256" = "$expected_sha256" ] || \
    die 'Renode runtime changed during qualification'
}

write_twin_scenario_provenance() {
  printf '# twin_source_commit=%s\n' "$TWIN_SOURCE_COMMIT"
  printf '# twin_renode_tree=%s\n' "$TWIN_RENODE_TREE"
  printf '# twin_tools_tree=%s\n' "$TWIN_TOOLS_TREE"
  printf '# twin_bootstrap_blob=%s\n' "$TWIN_BOOTSTRAP_BLOB"
  printf '# twin_runtime_source=%s\n' "$TWIN_RUNTIME_SOURCE"
  printf '# twin_runtime_sha256=%s\n' "$TWIN_RUNTIME_SHA256"
}
