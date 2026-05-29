# -*- coding: utf-8 -*-
"""Diff текущей editor-топологии vs blueprint активного рецепта (G.6.4).

Чистая domain-утилита: сравнивает два topology-dict (формат Topology.to_dict /
recipe blueprint). НЕ использует framework RecipeEngine.is_dirty (в GUI-процессе
бесполезен — изолированный пустой TreeStore). Без Qt-зависимостей — тестируется
без QApplication.

Семантика «current vs saved»:
- added   — есть в current, нет в saved (несохранённые добавления);
- removed — есть в saved, нет в current (несохранённые удаления).

metadata / gui_positions игнорируются (не семантика топологии).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TopologyDiff:
    """Различия между текущей топологией и сохранённой (blueprint рецепта)."""

    processes_added: list[str] = field(default_factory=list)
    processes_removed: list[str] = field(default_factory=list)
    processes_changed: list[str] = field(default_factory=list)
    wires_added: list[tuple[str, str]] = field(default_factory=list)
    wires_removed: list[tuple[str, str]] = field(default_factory=list)
    displays_added: list[tuple[str, str]] = field(default_factory=list)
    displays_removed: list[tuple[str, str]] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        """True если различий нет (топологии семантически равны)."""
        return not (
            self.processes_added
            or self.processes_removed
            or self.processes_changed
            or self.wires_added
            or self.wires_removed
            or self.displays_added
            or self.displays_removed
        )

    def summary(self) -> list[str]:
        """Человекочитаемый список различий (по одной строке на изменение)."""
        lines: list[str] = []
        for name in self.processes_added:
            lines.append(f"+ процесс: {name}")
        for name in self.processes_removed:
            lines.append(f"− процесс: {name}")
        for name in self.processes_changed:
            lines.append(f"~ конфигурация: {name}")
        for src, tgt in self.wires_added:
            lines.append(f"+ связь: {src} → {tgt}")
        for src, tgt in self.wires_removed:
            lines.append(f"− связь: {src} → {tgt}")
        for node_id, display_id in self.displays_added:
            lines.append(f"+ дисплей: {node_id} → {display_id}")
        for node_id, display_id in self.displays_removed:
            lines.append(f"− дисплей: {node_id} → {display_id}")
        return lines


def _process_map(topo: dict) -> dict[str, dict]:
    """Map process_name → запись процесса (только dict-записи)."""
    result: dict[str, dict] = {}
    for proc in topo.get("processes", []) or []:
        if isinstance(proc, dict):
            name = proc.get("process_name", "")
            if name:
                result[name] = proc
    return result


def _norm_process(proc: dict) -> dict:
    """Нормализованное представление процесса для сравнения «изменён ли».

    Сравниваем смысловую часть (плагины + их config + целевой процесс), а не
    весь dict — иначе несущественные сериализационные различия дают ложный diff.
    """
    plugins: list[dict] = []
    for pl in proc.get("plugins", []) or []:
        if isinstance(pl, dict):
            plugins.append(
                {
                    "plugin_name": pl.get("plugin_name", ""),
                    "config": pl.get("config", {}) or {},
                }
            )
    return {"plugins": plugins, "target_process": proc.get("target_process", "") or ""}


def _wire_set(topo: dict) -> set[tuple[str, str]]:
    """Множество (source, target) проводов."""
    result: set[tuple[str, str]] = set()
    for wire in topo.get("wires", []) or []:
        if isinstance(wire, dict):
            src = wire.get("source", "")
            tgt = wire.get("target", "")
            if src and tgt:
                result.add((src, tgt))
    return result


def _display_set(topo: dict) -> set[tuple[str, str]]:
    """Множество (node_id, display_id) привязок дисплеев."""
    result: set[tuple[str, str]] = set()
    for disp in topo.get("displays", []) or []:
        if isinstance(disp, dict):
            node_id = disp.get("node_id", "")
            display_id = disp.get("display_id", "")
            if node_id and display_id:
                result.add((node_id, display_id))
    return result


def topology_diff(current: dict[str, Any], saved: dict[str, Any]) -> TopologyDiff:
    """Сравнить текущую топологию с сохранённой (blueprint рецепта).

    Args:
        current: editor-топология (services.topology.load().to_dict()).
        saved: blueprint активного рецепта (dict).

    Returns:
        TopologyDiff с разбивкой по процессам / проводам / дисплеям.
    """
    cur_p = _process_map(current)
    sav_p = _process_map(saved)
    cur_names = set(cur_p)
    sav_names = set(sav_p)

    diff = TopologyDiff()
    diff.processes_added = sorted(cur_names - sav_names)
    diff.processes_removed = sorted(sav_names - cur_names)
    diff.processes_changed = sorted(
        n for n in (cur_names & sav_names) if _norm_process(cur_p[n]) != _norm_process(sav_p[n])
    )

    cur_w = _wire_set(current)
    sav_w = _wire_set(saved)
    diff.wires_added = sorted(cur_w - sav_w)
    diff.wires_removed = sorted(sav_w - cur_w)

    cur_d = _display_set(current)
    sav_d = _display_set(saved)
    diff.displays_added = sorted(cur_d - sav_d)
    diff.displays_removed = sorted(sav_d - cur_d)

    return diff
