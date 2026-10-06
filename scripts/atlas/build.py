"""Сборка реестра и вывод `--json` (Task 1.2, ADR-ATL-001 §5).

Purpose: build() зовёт адаптеры по ключу кэша (sha, main_ref, отпечаток адаптеров); to_json() —
    детерминированный JSON: списки отсортированы, ensure_ascii=False, без времени сборки.
Public API: ADAPTERS, CORE_VERSION, SCHEMA_VERSION, build, fingerprint, to_json.
Stability: lite
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from scripts.atlas import store
from scripts.atlas.schema import Adapter, AdapterOutput, BuildContext
from scripts.atlas.tree import Tree, resolve

__all__ = ["ADAPTERS", "CORE_VERSION", "SCHEMA_VERSION", "build", "fingerprint", "to_json"]

ADAPTERS: tuple[Adapter, ...] = ()  # адаптеры подключают задачи 1.3 и далее
CORE_VERSION = "1"
SCHEMA_VERSION = 1


def fingerprint() -> str:
    """sha256 от CORE_VERSION и отсортированных `name:version` адаптеров: смена набора -> новый ключ кэша."""
    parts = [CORE_VERSION, *sorted(f"{a.name}:{a.version}" for a in ADAPTERS)]
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def build(con: sqlite3.Connection, root: str | Path, ref: str, main_ref: str, base: Tree | None = None) -> int:
    """Собрать реестр на ревизии `ref`; ключ уже в базе -> вернуть его id, адаптеры не зовутся."""
    sha = resolve(root, ref)
    key = fingerprint()
    cached = store.find_build(con, sha, main_ref, key)
    if cached is not None:
        return cached
    ctx = BuildContext(tree=Tree(root, sha), base=base, main_ref=main_ref)
    merged = AdapterOutput()
    for adapter in ADAPTERS:
        out = adapter.collect(ctx)
        merged.nodes += out.nodes
        merged.edges += out.edges
        merged.findings += out.findings
    return store.write_build(con, sha, main_ref, key, merged)


def to_json(con: sqlite3.Connection, build_id: int, legacy_before: str | None) -> str:
    """Контракт `--json`: ключи верхнего уровня в порядке ADR-ATL-001 §5; `plans` в 1.2 — null."""
    sha, main_ref = store.build_row(con, build_id)
    data = store.read_build(con, build_id)
    nodes = sorted(data.nodes, key=lambda n: (n.kind, n.id))
    edges = sorted(data.edges, key=lambda e: (e.kind, e.src, e.dst, e.via))
    findings = sorted(data.findings, key=lambda f: (f.code, f.node, f.detail))
    doc: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "head": sha,
        "main_ref": main_ref,
        "legacy_before": legacy_before,
        "nodes": [{"kind": n.kind, "id": n.id, "path": n.path, "status": n.status, "time": n.time} for n in nodes],
        "edges": [{"kind": e.kind, "src": e.src, "dst": e.dst, "via": e.via} for e in edges],
        "findings": [
            {
                "code": f.code,
                "severity": f.severity,
                "node": f.node,
                "detail": f.detail,
                "message": f.message,
                "source": f.source,
            }
            for f in findings
        ],
        "plans": None,
    }
    return json.dumps(doc, ensure_ascii=False, indent=2)
