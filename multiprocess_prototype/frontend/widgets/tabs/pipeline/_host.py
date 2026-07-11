# -*- coding: utf-8 -*-
"""Узкий типизированный host-контракт для контроллеров Pipeline (Трек F, Task F.7).

Контроллеры (:class:`LayoutController`, :class:`PipelineMutations`) обращаются к
presenter ТОЛЬКО через этот публичный интерфейс — GUI-реакции: доступ к scene,
подавление сигналов, рендер, снятие/восстановление выделения, валидация портов
(QMessageBox), notify-статус, ссылка на inspector.

Чего здесь НЕТ намеренно:
- GUI-состояние (позиции/фиксация/placed-боксы/дебаунс-таймер) — им владеет
  :class:`LayoutController`, контроллеры берут его оттуда, НЕ из presenter;
- приватные поля presenter (``_scene``/``_model``/``_services`` и т.п.) —
  стабильные зависимости (``services``/``model``/``topo``) инжектятся в контроллер
  явно (по образцу RuntimeController, F.3), а Qt-реакции идут через публичные
  методы этого контракта.

F.7: back-reference ``self._p`` в приватные поля presenter снят; presenter
удовлетворяет этому Protocol структурно (публичные методы/свойства).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ContextManager, Protocol, runtime_checkable

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

    from .graph.data import EdgeData, NodeData
    from .graph.graph_scene import GraphScene


@runtime_checkable
class PipelineHost(Protocol):
    """Публичный GUI-реакционный контракт presenter'а для контроллеров.

    Только то, что нельзя инжектить снимком: scene пере-привязывается
    (``set_scene``/``dispose``), suppression — мутабельный флаг, рендер/выделение/
    валидация — Qt-координация presenter'а.
    """

    @property
    def scene(self) -> "GraphScene | None":
        """Текущая GraphScene (может быть None до set_scene / после dispose)."""
        ...

    @property
    def is_suppressed(self) -> bool:
        """Активно ли окно подавления сигналов (programmatic update)."""
        ...

    @property
    def inspector(self) -> Any:
        """Привязанная NodeInspectorPanel (или None) — источник current_plugin_index."""
        ...

    def block_signals(self) -> "ContextManager[None]":
        """Контекст подавления обработки сигналов на время programmatic update."""
        ...

    def topology_to_graph(self, topo_dict: dict) -> "tuple[list[NodeData], list[EdgeData]]":
        """Конвертировать topology dict → (nodes, edges) + наполнить кэши presenter."""
        ...

    def load_scene_with_ports(self, nodes: "list[NodeData]", edges: "list[EdgeData]") -> None:
        """Отрисовать ноды (с port_schemas) и рёбра в scene."""
        ...

    def capture_selection(self) -> list[str]:
        """Снять node_id выделенных нод ДО scene reload."""
        ...

    def restore_selection(self, node_ids: list[str]) -> None:
        """Восстановить выделение ПОСЛЕ reload."""
        ...

    def validate_wire_ports(self, source: str, target: str, parent: "QWidget | None" = None) -> bool:
        """Проверить совместимость портов + QMessageBox при отказе (GUI-реакция)."""
        ...

    def report(self, message: str) -> None:
        """Показать сообщение пользователю (statusBar) через notify-callback."""
        ...


__all__ = ["PipelineHost"]
