"""Гейт `atlas check` и `legacy_before` (Task 1.2, ADR-ATL-002 §1, §4).

Purpose: блокирует только новая blocking-находка против `<ref>` (merge-base или `--base`);
    перенос файла (строки `R` git diff -M) не делает старую находку новой.
Public API: BASELINE_PATH, check, legacy_before, translate_node.
Stability: lite
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts.atlas import store
from scripts.atlas.build import build
from scripts.atlas.tree import AtlasError, Tree, git, git_z, resolve, run_git

__all__ = ["BASELINE_PATH", "check", "legacy_before", "translate_node"]

BASELINE_PATH = "scripts/atlas/baseline.txt"
SHALLOW_MSG = "atlas: shallow clone — legacy_before is unreliable; run: git fetch --unshallow"
NOT_FOUND_MSG = "atlas: legacy_before not found — main ref missing or baseline not on it"


def legacy_before(root: str | Path, main_ref: str) -> str | None:
    """SHA коммита, добавившего baseline.txt в first-parent историю main_ref; нет файла в HEAD -> None."""
    if BASELINE_PATH not in Tree(root, "HEAD").files():
        return None
    if git(root, "rev-parse", "--is-shallow-repository") == "true":
        raise AtlasError(SHALLOW_MSG)
    try:
        tip = resolve(root, main_ref)
    except AtlasError:
        raise AtlasError(NOT_FOUND_MSG) from None
    proc = run_git(root, "log", "--first-parent", "--diff-filter=A", "--format=%H", tip, "--", BASELINE_PATH)
    lines = proc.stdout.decode("utf-8").split() if proc.returncode == 0 else []
    if not lines:
        raise AtlasError(NOT_FOUND_MSG)
    return lines[-1]


def _renames(root: str | Path, ref: str) -> dict[str, str]:
    """old -> new по строкам `R` из `git diff -M --name-status -z <ref> HEAD`."""
    tokens = git_z(root, "diff", "-M", "--name-status", "-z", ref, "HEAD")
    renames: dict[str, str] = {}
    i = 0
    while i < len(tokens):
        if tokens[i].startswith("R"):
            renames[tokens[i + 1]] = tokens[i + 2]
            i += 3
        else:
            i += 2
    return renames


def translate_node(node: str, renames: dict[str, str]) -> str:
    """`doc:<путь>` и `test:<путь>::<имя>` -> имя после переноса; остальные узлы без изменений."""
    kind, _, ident = node.partition(":")
    if kind not in ("doc", "test"):
        return node
    path, sep, rest = ident.partition("::")
    return f"{kind}:{renames.get(path, path)}{sep}{rest}"


def check(con: sqlite3.Connection, root: str | Path, main_ref: str, base: str | None = None) -> tuple[int, list[str]]:
    """(код выхода, строки вывода): 1 — есть новая blocking-находка, иначе 0."""
    ref = resolve(root, base) if base else git(root, "merge-base", resolve(root, main_ref), "HEAD")
    ref_id = build(con, root, ref, main_ref)
    head_id = build(con, root, "HEAD", main_ref, base=Tree(root, ref))
    renames = _renames(root, ref)
    known = {(f.code, translate_node(f.node, renames), f.detail) for f in store.read_build(con, ref_id).findings}
    new = sorted(
        (f for f in store.read_build(con, head_id).findings if (f.code, f.node, f.detail) not in known),
        key=lambda f: (f.code, f.node, f.detail),
    )
    lines = [f"{f.severity} {f.code} {f.node} {f.detail or '-'}" for f in new]
    counts = {s: sum(1 for f in new if f.severity == s) for s in ("blocking", "warning", "info")}
    lines.append(
        f"atlas check: {counts['blocking']} new blocking, {counts['warning']} new warning, {counts['info']} new info"
    )
    return (1 if counts["blocking"] else 0), lines
