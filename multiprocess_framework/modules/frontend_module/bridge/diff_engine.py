"""Движок вычисления diff между двумя topology dict.

Pure Python, 0 внешних зависимостей.
Используется для определения изменений в топологии перед применением команд.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class ProcessDiff:
    """Изменения одного процесса."""

    process_name: str
    kind: Literal["added", "removed", "modified"]
    old_config: dict[str, Any] | None  # None для added
    new_config: dict[str, Any] | None  # None для removed
    changed_fields: list[str] = field(default_factory=list)  # только для modified


@dataclass(frozen=True)
class WireDiff:
    """Изменения одного wire."""

    wire_key: str  # формат: f"{source}|{target}"
    kind: Literal["added", "removed", "modified"]
    old_config: dict[str, Any] | None
    new_config: dict[str, Any] | None


@dataclass(frozen=True)
class TopologyDiff:
    """Полный diff между двумя topology."""

    processes: list[ProcessDiff] = field(default_factory=list)
    wires: list[WireDiff] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        """True если есть хотя бы одно изменение."""
        return bool(self.processes or self.wires)

    @property
    def added_processes(self) -> list[ProcessDiff]:
        """Список добавленных процессов."""
        return [p for p in self.processes if p.kind == "added"]

    @property
    def removed_processes(self) -> list[ProcessDiff]:
        """Список удалённых процессов."""
        return [p for p in self.processes if p.kind == "removed"]

    @property
    def modified_processes(self) -> list[ProcessDiff]:
        """Список изменённых процессов."""
        return [p for p in self.processes if p.kind == "modified"]

    @property
    def added_wires(self) -> list[WireDiff]:
        """Список добавленных wire."""
        return [w for w in self.wires if w.kind == "added"]

    @property
    def removed_wires(self) -> list[WireDiff]:
        """Список удалённых wire."""
        return [w for w in self.wires if w.kind == "removed"]

    def summary(self) -> str:
        """Краткая сводка изменений.

        Формат: '+2 процессов, -1 процессов, ~3 процессов, +1 wire'ов'
        Пустой diff: 'Нет изменений'
        """
        parts: list[str] = []

        added_p = len(self.added_processes)
        removed_p = len(self.removed_processes)
        modified_p = len(self.modified_processes)
        added_w = len(self.added_wires)
        removed_w = len(self.removed_wires)

        if added_p:
            parts.append(f"+{added_p} процессов")
        if removed_p:
            parts.append(f"-{removed_p} процессов")
        if modified_p:
            parts.append(f"~{modified_p} процессов")
        if added_w:
            parts.append(f"+{added_w} wire'ов")
        if removed_w:
            parts.append(f"-{removed_w} wire'ов")

        return ", ".join(parts) if parts else "Нет изменений"


__all__ = [
    "ProcessDiff",
    "WireDiff",
    "TopologyDiff",
    "compute_diff",
]


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------


def _build_process_index(processes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Построить индекс {process_name: config_dict} из списка процессов."""
    index: dict[str, dict[str, Any]] = {}
    for proc in processes:
        name = proc.get("process_name")
        if name is not None:
            index[str(name)] = proc
    return index


def _build_wire_index(wires: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Построить индекс {source|target: config_dict} из списка wire."""
    index: dict[str, dict[str, Any]] = {}
    for wire in wires:
        source = wire.get("source", "")
        target = wire.get("target", "")
        key = f"{source}|{target}"
        index[key] = wire
    return index


def _find_changed_fields(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    """Найти ключи верхнего уровня, значения которых отличаются."""
    all_keys = set(old.keys()) | set(new.keys())
    return sorted(k for k in all_keys if old.get(k) != new.get(k))


# ---------------------------------------------------------------------------
# Основная функция
# ---------------------------------------------------------------------------


def compute_diff(old: dict[str, Any], new: dict[str, Any]) -> TopologyDiff:
    """Вычислить diff между двумя topology dict.

    Сравнивает процессы и wire по именам/ключам.
    Edge cases: отсутствие "processes" или "wires" → считаются пустыми.
    """
    # --- Diff процессов ---
    old_procs = old.get("processes") or []
    new_procs = new.get("processes") or []

    old_proc_index = _build_process_index(old_procs)
    new_proc_index = _build_process_index(new_procs)

    old_names = set(old_proc_index.keys())
    new_names = set(new_proc_index.keys())

    process_diffs: list[ProcessDiff] = []

    # Добавленные процессы
    for name in sorted(new_names - old_names):
        process_diffs.append(
            ProcessDiff(
                process_name=name,
                kind="added",
                old_config=None,
                new_config=new_proc_index[name],
            )
        )

    # Удалённые процессы
    for name in sorted(old_names - new_names):
        process_diffs.append(
            ProcessDiff(
                process_name=name,
                kind="removed",
                old_config=old_proc_index[name],
                new_config=None,
            )
        )

    # Изменённые процессы
    for name in sorted(old_names & new_names):
        old_cfg = old_proc_index[name]
        new_cfg = new_proc_index[name]
        if old_cfg != new_cfg:
            changed = _find_changed_fields(old_cfg, new_cfg)
            process_diffs.append(
                ProcessDiff(
                    process_name=name,
                    kind="modified",
                    old_config=old_cfg,
                    new_config=new_cfg,
                    changed_fields=changed,
                )
            )

    # --- Diff wire ---
    old_wires = old.get("wires") or []
    new_wires = new.get("wires") or []

    old_wire_index = _build_wire_index(old_wires)
    new_wire_index = _build_wire_index(new_wires)

    old_keys = set(old_wire_index.keys())
    new_keys = set(new_wire_index.keys())

    wire_diffs: list[WireDiff] = []

    # Добавленные wire
    for key in sorted(new_keys - old_keys):
        wire_diffs.append(
            WireDiff(
                wire_key=key,
                kind="added",
                old_config=None,
                new_config=new_wire_index[key],
            )
        )

    # Удалённые wire
    for key in sorted(old_keys - new_keys):
        wire_diffs.append(
            WireDiff(
                wire_key=key,
                kind="removed",
                old_config=old_wire_index[key],
                new_config=None,
            )
        )

    # Изменённые wire
    for key in sorted(old_keys & new_keys):
        old_cfg = old_wire_index[key]
        new_cfg = new_wire_index[key]
        if old_cfg != new_cfg:
            wire_diffs.append(
                WireDiff(
                    wire_key=key,
                    kind="modified",
                    old_config=old_cfg,
                    new_config=new_cfg,
                )
            )

    return TopologyDiff(processes=process_diffs, wires=wire_diffs)
