#!/usr/bin/env python3
"""Audit phase ancestry, tags, manifests, artifacts and private origin."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent
BRANCHES = [
    "physicistjohn/phase-0-build-safety",
    "physicistjohn/phase-1-host-core",
    "physicistjohn/phase-2-deterministic-firmware",
    "physicistjohn/phase-3-dsp-ui",
    "physicistjohn/phase-4-rf-experiments",
    "physicistjohn/phase-5-waveform-generator",
    "physicistjohn/phase-6-final-integration",
]
TAGS = [
    "phase-0-build-safety",
    "phase-1-host-core",
    "phase-2-deterministic-firmware",
    "phase-3-dsp-ui",
    "phase-4-rf-experiments",
    "phase-5-waveform-generator",
    "phase-6-final-integration",
]
ORIGIN = "https://github.com/PhysicistJohn/Atom-Firmware.git"


class AuditError(RuntimeError):
    pass


def run(command: list[str]) -> str:
    try:
        return subprocess.run(
            command, cwd=ROOT, check=True, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as error:
        detail = error.stderr.strip() if isinstance(error, subprocess.CalledProcessError) else str(error)
        raise AuditError(f"command failed: {' '.join(command)}: {detail}") from error


def git(*arguments: str) -> str:
    return run(["git", *arguments])


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_manifest(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            break
        key, value = line.split("=", 1)
        values[key] = value
    return values


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditError(message)


def github_private_check() -> None:
    require(run(["gh", "api", "user", "--jq", ".login"]) == "PhysicistJohn",
            "GitHub login is not PhysicistJohn")
    repository = json.loads(run([
        "gh", "api", "repos/PhysicistJohn/Atom-Firmware"
    ]))
    require(repository.get("full_name") == "PhysicistJohn/Atom-Firmware",
            "GitHub repository owner/name mismatch")
    require(repository.get("private") is True,
            "GitHub repository is not private")


def audit(through: int, check_github: bool) -> list[dict[str, object]]:
    require(git("remote", "get-url", "origin") == ORIGIN,
            "origin fetch URL mismatch")
    require(git("remote", "get-url", "--push", "origin") == ORIGIN,
            "origin push URL mismatch")
    require(git("remote", "get-url", "--push", "upstream") == "no_push",
            "upstream must remain fetch-only")
    require(git("config", "--local", "user.name") == "PhysicistJohn",
            "local Git author name mismatch")
    require(git("config", "--local", "user.email") ==
            "54456354+PhysicistJohn@users.noreply.github.com",
            "local Git author email mismatch")
    if check_github:
        github_private_check()

    rows: list[dict[str, object]] = []
    previous_commit: str | None = None
    hashes: set[str] = set()
    for phase in range(through + 1):
        branch = BRANCHES[phase]
        tag = TAGS[phase]
        branch_commit = git("rev-parse", branch)
        tag_commit = git("rev-list", "-n1", tag)
        require(branch_commit == tag_commit,
                f"phase {phase} tag does not identify its branch tip")
        if check_github:
            remote_branch = git("ls-remote", "origin", f"refs/heads/{branch}")
            remote_tag = git("ls-remote", "origin", f"refs/tags/{tag}^{{}}")
            require(remote_branch.partition("\t")[0] == branch_commit,
                    f"phase {phase} remote branch is missing or stale")
            require(remote_tag.partition("\t")[0] == tag_commit,
                    f"phase {phase} remote annotated tag is missing or stale")
        if previous_commit is not None:
            subprocess_result = subprocess.run(
                ["git", "merge-base", "--is-ancestor", previous_commit,
                 branch_commit], cwd=ROOT,
            )
            require(subprocess_result.returncode == 0,
                    f"phase {phase} does not descend from phase {phase - 1}")

        manifests = list((ROOT / ".artifacts/phase-images" /
                          f"phase-{phase}").glob("*/manifest.txt"))
        matching = [path for path in manifests if path.parent.name == branch_commit]
        require(len(matching) == 1,
                f"phase {phase} has no unique artifact for {branch_commit}")
        manifest_path = matching[0]
        manifest = read_manifest(manifest_path)
        require(manifest.get("phase") == str(phase),
                f"phase {phase} manifest phase mismatch")
        require(manifest.get("branch") == branch,
                f"phase {phase} manifest branch mismatch")
        require(manifest.get("commit") == branch_commit,
                f"phase {phase} manifest commit mismatch")
        require(manifest.get("reproducible_clean_builds") == "true",
                f"phase {phase} was not reproducibly built")
        require(manifest.get("hardware_qualified") == "false",
                f"phase {phase} has an invalid qualification claim")

        binary = manifest_path.parent / f"tinySA4_phase-{phase}.bin"
        elf = manifest_path.parent / f"tinySA4_phase-{phase}.elf"
        ihex = manifest_path.parent / f"tinySA4_phase-{phase}.hex"
        for artifact in (binary, elf, ihex):
            require(artifact.is_file(), f"missing artifact: {artifact}")
        binary_hash = sha256(binary)
        require(binary_hash == manifest.get("binary_sha256"),
                f"phase {phase} binary hash mismatch")
        require(sha256(elf) == manifest.get("elf_sha256"),
                f"phase {phase} ELF hash mismatch")
        require(sha256(ihex) == manifest.get("hex_sha256"),
                f"phase {phase} HEX hash mismatch")
        require(binary.stat().st_size == int(manifest["binary_size"]),
                f"phase {phase} binary size mismatch")
        require(binary_hash not in hashes,
                f"phase {phase} binary duplicates an earlier phase")
        hashes.add(binary_hash)
        if phase >= 5:
            require(manifest.get("output_lock_audit") == "passed",
                    f"phase {phase} lacks output-lock audit")
            lock_report = manifest_path.parent / "output-gate-audit.txt"
            require(lock_report.is_file() and
                    "output_lock=passed" in lock_report.read_text(encoding="utf-8"),
                    f"phase {phase} output-lock report failed")

        rows.append({
            "phase": phase,
            "branch": branch,
            "tag": tag,
            "commit": branch_commit,
            "version": manifest["version"],
            "binary_size": int(manifest["binary_size"]),
            "binary_sha256": binary_hash,
            "ccm_bytes": int(manifest.get("ccm_bytes") or 0),
            "hardware_qualified": False,
        })
        previous_commit = branch_commit
    return rows


def report(rows: list[dict[str, object]]) -> str:
    lines = [
        "# Reproducible phase image matrix",
        "",
        "Every image is **NOT HARDWARE QUALIFIED** and must not be flashed before the physical gates.",
        "",
        "| Phase | Branch/tag | Commit | Bytes | CCM | SHA-256 |",
        "| ---: | --- | --- | ---: | ---: | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row['phase']} | `{row['branch']}` / `{row['tag']}` | "
            f"`{str(row['commit'])[:12]}` | {row['binary_size']} | "
            f"{row['ccm_bytes']} | `{row['binary_sha256']}` |"
        )
    lines.extend([
        "",
        "The audit verified cumulative ancestry, exact tag-to-tip identity, all artifact hashes and sizes, reproducible-build flags, false hardware-qualification flags, private personal origin policy, and Phase 5+ binary output locks.",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--through", type=int, default=6)
    parser.add_argument("--github", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        if not 0 <= args.through <= 6:
            raise AuditError("--through must be 0..6")
        rows = audit(args.through, args.github)
        if args.report is not None:
            destination = args.report
            if not destination.is_absolute():
                destination = ROOT / destination
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(report(rows), encoding="utf-8")
        print(f"phase chain audit: passed phases=0..{args.through} "
              f"github={'checked-private' if args.github else 'not-requested'}")
        return 0
    except (AuditError, OSError, KeyError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
