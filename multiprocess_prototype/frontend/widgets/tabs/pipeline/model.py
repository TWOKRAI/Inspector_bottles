"""PipelineModel — SSOT-модель topology pipeline.

Чистый Python (+ dag_utils). Тестируется без Qt.
Адаптация v1 GraphEditorModel для topology dict формата.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from . import dag_utils


@dataclass
class ProcessNodeData:
    """Данные процесса в модели."""

    name: str
    plugin_name: str = ""
    category: str = "utility"
    config: dict[str, Any] = field(default_factory=dict)
    x: float = 0.0
    y: float = 0.0


@dataclass
class WireData:
    """Данные wire в модели."""

    source: str  # "process.plugin.port"
    target: str  # "process.plugin.port"


class PipelineModel:
    """SSOT-модель topology pipeline.

    Все мутации возвращают (old_topology, new_topology) для undo/redo.
    Использует dag_utils для валидации (cycle detection, topological sort).
    """

    def __init__(self, topology: dict | None = None) -> None:
        self._topology: dict = topology or {"processes": [], "wires": [], "displays": []}

    def from_topology_dict(self, topo: dict) -> None:
        """Загрузить topology из dict."""
        self._topology = copy.deepcopy(topo)

    def to_topology_dict(self) -> dict:
        """Экспортировать topology в dict (deep copy)."""
        return copy.deepcopy(self._topology)

    # ---- Read-only доступ ---- #

    def get_process_names(self) -> list[str]:
        """Список имён процессов."""
        return [
            p.get("process_name", "") if isinstance(p, dict) else getattr(p, "process_name", "")
            for p in self._topology.get("processes", [])
        ]

    def get_wires(self) -> list[dict]:
        """Список wire'ов (копии)."""
        return copy.deepcopy(self._topology.get("wires", []))

    def get_displays(self) -> list[dict]:
        """Список display-узлов (deep copy для read-only доступа)."""
        return copy.deepcopy(self._topology.get("displays", []))

    def get_edges_as_tuples(self) -> list[tuple[str, str]]:
        """Wire'ы как list[(source_process, target_process)] для dag_utils.

        Wire'ы, где source или target начинаются с «display.», пропускаются —
        display-узлы не являются процессами и не должны попадать в DAG-граф.
        """
        result: list[tuple[str, str]] = []
        for w in self._topology.get("wires", []):
            src = w.get("source", "") if isinstance(w, dict) else ""
            tgt = w.get("target", "") if isinstance(w, dict) else ""
            # Пропустить wire'ы с display-endpoint'ами
            if src.startswith("display.") or tgt.startswith("display."):
                continue
            src_proc = src.split(".")[0] if "." in src else src
            tgt_proc = tgt.split(".")[0] if "." in tgt else tgt
            if src_proc and tgt_proc:
                result.append((src_proc, tgt_proc))
        return result

    # ---- Мутации (все возвращают old_topo, new_topo) ---- #

    def add_process(
        self,
        name: str,
        plugin_name: str = "",
        category: str = "utility",
        config: dict | None = None,
    ) -> tuple[dict, dict]:
        """Добавить процесс. Возвращает (old_topo, new_topo)."""
        old = self.to_topology_dict()
        process_entry: dict[str, Any] = {
            "process_name": name,
            "plugins": [{"plugin_name": plugin_name}] if plugin_name else [],
        }
        if config:
            process_entry["config"] = config
        self._topology.setdefault("processes", []).append(process_entry)
        return old, self.to_topology_dict()

    def remove_process(self, name: str) -> tuple[dict, dict]:
        """Удалить процесс и каскадно все wire'ы. Возвращает (old_topo, new_topo)."""
        old = self.to_topology_dict()

        # Удалить процесс
        processes = self._topology.get("processes", [])
        self._topology["processes"] = [
            p
            for p in processes
            if (p.get("process_name") if isinstance(p, dict) else getattr(p, "process_name", "")) != name
        ]

        # Каскадное удаление wire'ов
        wires = self._topology.get("wires", [])
        self._topology["wires"] = [w for w in wires if not self._wire_involves_process(w, name)]

        return old, self.to_topology_dict()

    def add_display(
        self,
        node_id: str,
        display_id: str,
        display_name: str = "",
    ) -> tuple[dict, dict]:
        """Добавить display-привязку. Возвращает (old_topo, new_topo).

        G.4.2b: display = binding (не wire). node_id — source endpoint
        (process.plugin.port), display_id — канал из DisplayRegistry. Ключ — пара
        (node_id, display_id): один выход может быть привязан к нескольким каналам
        (fan-out), один канал — к нескольким выходам (fan-in). См. ADR DOM-001.

        Args:
            node_id: source endpoint выхода (process.plugin.port).
            display_id: ID SHM-канала из DisplayRegistry.
            display_name: отображаемое имя (опционально).

        Raises:
            ValueError: если пара (node_id, display_id) уже привязана.
        """
        for d in self._topology.get("displays", []):
            if d.get("node_id") == node_id and d.get("display_id") == display_id:
                raise ValueError(f"Привязка '{node_id}' → '{display_id}' уже существует")

        old = self.to_topology_dict()
        display_entry: dict[str, Any] = {
            "node_id": node_id,
            "display_id": display_id,
            "display_name": display_name,
        }
        self._topology.setdefault("displays", []).append(display_entry)
        return old, self.to_topology_dict()

    def add_wire(
        self,
        source: str,
        target: str,
        src_dtype: str = "any",
        tgt_dtype: str = "any",
    ) -> tuple[dict, dict]:
        """Добавить wire с cycle detection и type-aware валидацией.

        Args:
            source: endpoint "process.plugin.port"
            target: endpoint "process.plugin.port"
            src_dtype: dtype выходного порта ("image/bgr", "any" и т.д.)
            tgt_dtype: dtype входного порта

        Returns:
            (old_topo, new_topo)

        Raises:
            ValueError: если wire создаёт цикл, дублируется или типы несовместимы.
        """
        old = self.to_topology_dict()

        # Проверка совместимости типов
        if not dag_utils.validate_port_compatibility(src_dtype, tgt_dtype):
            raise ValueError(f"Несовместимые типы портов: {src_dtype} -> {tgt_dtype}")

        # Проверка дубликатов
        for w in self._topology.get("wires", []):
            if isinstance(w, dict) and w.get("source") == source and w.get("target") == target:
                raise ValueError(f"Wire {source} -> {target} уже существует")

        # G.4.2b: wire — только process→process. Связь с display = binding
        # (см. domain BindDisplay / topology["displays"]), не wire. Cycle detection:
        src_proc = source.split(".")[0] if "." in source else source
        tgt_proc = target.split(".")[0] if "." in target else target

        # Self-loop check
        if src_proc == tgt_proc:
            raise ValueError(f"Self-loop запрещён: {src_proc}")

        existing_edges = self.get_edges_as_tuples()
        if dag_utils.has_cycle(existing_edges, (src_proc, tgt_proc)):
            raise ValueError(f"Wire {source} -> {target} создаёт цикл")

        # Сохранить wire с dtype-информацией
        wire_entry: dict[str, Any] = {
            "source": source,
            "target": target,
        }
        if src_dtype != "any":
            wire_entry["src_dtype"] = src_dtype
        if tgt_dtype != "any":
            wire_entry["tgt_dtype"] = tgt_dtype

        self._topology.setdefault("wires", []).append(wire_entry)
        return old, self.to_topology_dict()

    def remove_wire(self, source: str, target: str) -> tuple[dict, dict]:
        """Удалить wire. Возвращает (old_topo, new_topo)."""
        old = self.to_topology_dict()
        wires = self._topology.get("wires", [])
        self._topology["wires"] = [
            w for w in wires if not (isinstance(w, dict) and w.get("source") == source and w.get("target") == target)
        ]
        return old, self.to_topology_dict()

    # ---- Валидация ---- #

    def validate(self) -> list[str]:
        """Полная валидация topology. Возвращает список ошибок."""
        errors: list[str] = []

        process_names = self.get_process_names()

        # Дубликаты имён
        seen: set[str] = set()
        for name in process_names:
            if name in seen:
                errors.append(f"Дублирующееся имя процесса: {name}")
            seen.add(name)

        # Проверка wire'ов (только process→process)
        edges = self.get_edges_as_tuples()
        for src_proc, tgt_proc in edges:
            if src_proc not in seen:
                errors.append(f"Wire ссылается на несуществующий процесс: {src_proc}")
            if tgt_proc not in seen:
                errors.append(f"Wire ссылается на несуществующий процесс: {tgt_proc}")

        # Циклы
        if dag_utils.has_cycle(edges):
            errors.append("Topology содержит цикл")

        # Orphan-процессы (предупреждение, не ошибка)
        connected: set[str] = set()
        for s, t in edges:
            connected.add(s)
            connected.add(t)
        orphans = [n for n in process_names if n and n not in connected]
        for o in orphans:
            errors.append(f"Изолированный процесс: {o}")

        # ---- Проверки display-привязок (G.4.2b: display = binding) ---- #
        # Привязка несёт source endpoint в node_id → проверяем, что процесс-источник
        # существует. Orphan-display невозможен (привязка по определению имеет источник).
        for d in self._topology.get("displays", []):
            src = d.get("node_id", "") if isinstance(d, dict) else ""
            src_proc = src.split(".")[0] if src else ""
            if src_proc and src_proc not in seen:
                errors.append(f"Display-привязка ссылается на несуществующий процесс: {src_proc}")

        return errors

    # ---- Приватные ---- #

    @staticmethod
    def _wire_involves_process(wire: dict, process_name: str) -> bool:
        """Проверить, связан ли wire с процессом."""
        src = wire.get("source", "") if isinstance(wire, dict) else ""
        tgt = wire.get("target", "") if isinstance(wire, dict) else ""
        src_proc = src.split(".")[0] if "." in src else src
        tgt_proc = tgt.split(".")[0] if "." in tgt else tgt
        return src_proc == process_name or tgt_proc == process_name
