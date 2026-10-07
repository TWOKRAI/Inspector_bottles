"""Схема реестра atlas: узел, ребро, находка, выход адаптера, контекст сборки (Task 1.2).

Purpose: общие типы ядра и адаптеров; поля — по ADR-ATL-001 §1-3.
Public API: Node, Edge, Finding, AdapterOutput, BuildContext, Adapter.
Stability: lite
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

__all__ = ["Adapter", "AdapterOutput", "BuildContext", "Edge", "Finding", "Node"]


@dataclass(frozen=True)
class Node:
    """Узел реестра; ключ — `kind:id`. `time` — секунды Unix коммита (у `commit`), иначе None."""

    kind: str
    id: str
    path: str | None = None
    status: str | None = None
    time: int | None = None


@dataclass(frozen=True)
class Edge:
    """Ребро `src -> dst` (оба — `kind:id`); `via` — откуда ребро выведено."""

    kind: str
    src: str
    dst: str
    via: str


@dataclass(frozen=True)
class Finding:
    """Находка; severity — blocking | warning | info; detail различает находки одного кода на узле."""

    code: str
    severity: str
    node: str
    detail: str
    message: str
    source: str


@dataclass
class AdapterOutput:
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)


@dataclass(frozen=True)
class BuildContext:
    """Что получает адаптер: дерево сборки, дерево базы (None при обычной сборке), main-ref."""

    tree: Any  # scripts.atlas.tree.Tree
    base: Any | None
    main_ref: str


class Adapter(Protocol):
    name: str
    version: int

    def collect(self, ctx: BuildContext) -> AdapterOutput: ...
