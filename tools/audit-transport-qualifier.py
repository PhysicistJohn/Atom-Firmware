#!/usr/bin/env python3
"""Prove the physical transport qualifier has a narrow, non-flashing surface."""

from __future__ import annotations

import argparse
import ast
from pathlib import Path
import sys


class AuditError(RuntimeError):
    pass


ALLOWED_SHELL_COMMANDS = {
    "output off",
    "version",
    "modern transport selftest",
    "modern transport status",
    "modern passive status",
    "modern transport handoff ",
}


def call_name(call: ast.Call) -> str:
    function = call.func
    if isinstance(function, ast.Name):
        return function.id
    if isinstance(function, ast.Attribute):
        return function.attr
    return ""


def literal_prefix(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr) and node.values:
        first = node.values[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            return first.value
    return None


def audit(path: Path) -> str:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    forbidden_imports = {"ctypes", "os", "subprocess"}
    imports: set[str] = set()
    shell_commands: set[str] = set()
    functions = {node.name: node for node in tree.body
                 if isinstance(node, ast.FunctionDef)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".", 1)[0])
        elif isinstance(node, ast.Call):
            name = call_name(node)
            if name in {"system", "popen", "run", "Popen", "execv", "spawn"}:
                raise AuditError(f"forbidden process execution call: {name}")
            if name in {"write_bytes", "write_text", "unlink", "remove", "rename"}:
                raise AuditError(f"forbidden filesystem mutation call: {name}")
            if name == "command" and node.args:
                prefix = literal_prefix(node.args[0])
                if prefix is None or not any(
                        prefix == allowed or prefix.startswith(allowed)
                        for allowed in ALLOWED_SHELL_COMMANDS):
                    raise AuditError(f"unapproved shell command expression: {prefix!r}")
                shell_commands.add(prefix)
    unexpected = imports & forbidden_imports
    if unexpected:
        raise AuditError(f"forbidden imports: {sorted(unexpected)}")
    forbidden_literals = (
        "dfu-util", "0x08000000", "enter dfu", "reset dfu",
        "saveconfig", "clearconfig", "calibrate", "generator enable",
    )
    lowered = source.lower()
    if any(value in lowered for value in forbidden_literals):
        raise AuditError("firmware/DFU/persistence/output literal is present")
    if "output off" not in shell_commands or \
            not any(value.startswith("modern transport handoff ")
                    for value in shell_commands):
        raise AuditError("output-off or explicit handoff command is absent")
    for name in ("shell_preflight", "verify_recovery"):
        function = functions.get(name)
        if function is None or not function.body:
            raise AuditError(f"required physical function is absent: {name}")
        first = function.body[0]
        if not isinstance(first, ast.Expr) or \
                not isinstance(first.value, ast.Call) or \
                call_name(first.value) != "command" or \
                not first.value.args or \
                literal_prefix(first.value.args[0]) != "output off":
            raise AuditError(f"{name} does not begin with output off")
    exercise = functions.get("exercise_binary")
    if exercise is None or not exercise.body or \
            not isinstance(exercise.body[0], ast.Expr) or \
            not isinstance(exercise.body[0].value, ast.Call) or \
            call_name(exercise.body[0].value) != "shell_preflight":
        raise AuditError("binary exercise does not begin with shell preflight")
    return (
        "transport_qualifier_audit=passed\n"
        "process_execution=absent\n"
        "filesystem_mutation=absent\n"
        "dfu_and_flash=absent\n"
        "configuration_and_calibration_writes=absent\n"
        "generator_commands=absent\n"
        "first_physical_command=output-off\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("script", type=Path)
    args = parser.parse_args()
    try:
        if not args.script.is_file():
            raise AuditError(f"script not found: {args.script}")
        print(audit(args.script), end="")
        return 0
    except (AuditError, OSError, SyntaxError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
