"""PluginGraphAdapter — синхронизация NodeGraphQt ↔ WireEditorModel.

Паттерн из Pipeline Tab (NodeGraphQtAdapter), упрощённый:
- Нет ActionBus / undo-redo (будущая фаза)
- Wire мутации идут напрямую в WireEditorModel → WiresSectionView → SystemTopologyEditor
- Signal suppression context manager предотвращает бесконечные циклы
- Подписка на SECTION_PROCESSES — при изменении процессов перестраиваем канвас

Ключевая роль: единое дерево данных (SystemTopologyEditor) остаётся
source of truth. Канвас — read/write view поверх wires секции.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Iterator

from PySide6 import QtCore
from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QPen

from multiprocess_prototype.frontend.bridges.wire_data_bridge import WireStatus

from .graph_builder import GraphBuilder
from .plugin_process_node import PROCESS_NODE_TYPE, PluginProcessNode

if TYPE_CHECKING:
    from NodeGraphQt import NodeGraph

    from multiprocess_prototype.frontend.models.system_topology_editor import (
        SystemTopologyEditor,
    )
    from multiprocess_prototype.frontend.models.wire_model import WireEditorModel
    from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.models.cross_process_model import (
        CrossProcessModel,
    )

# ---------------------------------------------------------------------------
# Цветовая схема статусов wire-соединений
# ---------------------------------------------------------------------------

WIRE_STATUS_COLORS: dict[WireStatus, tuple[int, int, int]] = {
    WireStatus.NOT_APPLIED: (128, 128, 128),  # Серый — не применён
    WireStatus.PENDING: (255, 200, 0),         # Жёлтый — ожидает подтверждения
    WireStatus.IDLE: (100, 180, 255),           # Голубой — подключён, данных нет
    WireStatus.ACTIVE: (50, 220, 80),           # Зелёный — данные передаются
    WireStatus.BROKEN: (230, 60, 60),           # Красный — ошибка
}

logger = logging.getLogger(__name__)


class PluginGraphAdapter(QtCore.QObject):
    """Адаптер между NodeGraphQt (визуализация) и WireEditorModel (данные).

    Обеспечивает двустороннюю синхронизацию:
    - NodeGraphQt сигналы → WireEditorModel мутации
    - Изменения в topology editor → перестроение канваса

    Всё через единое дерево данных SystemTopologyEditor.
    """

    # Qt-сигналы для правой панели (Фаза 3)
    node_selected = QtCore.Signal(str)           # process_key
    wire_selected = QtCore.Signal(str)           # wire_key
    selection_cleared = QtCore.Signal()
    wire_rejected = QtCore.Signal(str, str, str)  # source, target, reason

    def __init__(
        self,
        graph: NodeGraph,
        wire_model: WireEditorModel,
        cross_model: CrossProcessModel,
        topology_editor: SystemTopologyEditor,
        *,
        parent: QtCore.QObject | None = None,
    ) -> None:
        super().__init__(parent)

        self._graph = graph
        self._wire_model = wire_model
        self._cross_model = cross_model
        self._editor = topology_editor

        self._builder = GraphBuilder(graph)

        # Identity mapping: process_key → PluginProcessNode
        self._node_map: dict[str, PluginProcessNode] = {}

        # Обратный маппинг: NodeGraphQt node.id → process_key
        self._reverse_map: dict[str, str] = {}

        # Маппинг wire: (source_addr, target_addr) → wire_key
        self._addr_wire_map: dict[tuple[str, str], str] = {}

        # Обратный маппинг: wire_key → pipe QGraphicsPathItem (для окраски)
        self._wire_key_to_pipe: dict[str, Any] = {}

        # Флаг подавления сигналов при programmatic update
        self._suppress: bool = False

        self._connect_signals()

        logger.debug("PluginGraphAdapter: инициализирован")

    # ------------------------------------------------------------------
    # Signal suppression
    # ------------------------------------------------------------------

    @contextmanager
    def _block_signals(self) -> Iterator[None]:
        """Context manager: подавляет обработку Qt-сигналов NodeGraphQt."""
        prev = self._suppress
        self._suppress = True
        try:
            yield
        finally:
            self._suppress = prev

    # ------------------------------------------------------------------
    # Подключение сигналов NodeGraphQt
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        """Подключить сигналы NodeGraphQt к обработчикам."""
        self._graph.port_connected.connect(self._on_port_connected)
        self._graph.port_disconnected.connect(self._on_port_disconnected)
        self._graph.node_selection_changed.connect(
            self._on_node_selection_changed,
        )

    def disconnect_signals(self) -> None:
        """Отключить все сигналы при dispose."""
        try:
            self._graph.port_connected.disconnect(self._on_port_connected)
            self._graph.port_disconnected.disconnect(self._on_port_disconnected)
            self._graph.node_selection_changed.disconnect(
                self._on_node_selection_changed,
            )
        except (RuntimeError, TypeError):
            pass

    # ------------------------------------------------------------------
    # Загрузка / обновление сцены
    # ------------------------------------------------------------------

    def load_scene(self) -> None:
        """Полная перезагрузка канваса из текущего состояния topology editor.

        Вызывается при:
        - Инициализации вкладки
        - Изменениях в секции processes (подписка)
        - Load Blueprint

        После построения сцены: строим маппинг wire_key → pipe item
        и сбрасываем все цвета в NOT_APPLIED (серый).
        """
        with self._block_signals():
            self._builder.clear()
            self._node_map.clear()
            self._reverse_map.clear()
            self._addr_wire_map.clear()
            self._wire_key_to_pipe.clear()

            # Обновить кэш cross_model
            self._cross_model.invalidate()

            # Построить сцену — получить node_map и маппинг адресов → wire_key
            wires = self._wire_model.wires
            self._node_map, addr_to_wire_key = self._builder.build(
                self._cross_model, wires,
            )

            # Заполнить маппинги нод
            for pk, qt_node in self._node_map.items():
                self._reverse_map[qt_node.id] = pk

            # Сохранить маппинг edge→wire_key из builder
            self._addr_wire_map.update(addr_to_wire_key)

            # Построить маппинг wire_key → pipe item и сбросить цвета
            self._rebuild_pipe_map()

        logger.info(
            "PluginGraphAdapter: сцена загружена — %d нод, %d wires",
            len(self._node_map),
            len(self._wire_model.wires),
        )

    def refresh_from_topology(self) -> None:
        """Перестроить канвас при изменении процессов/плагинов.

        Стратегия: полный rebuild. Оптимизация (diff) — в будущих фазах.
        """
        self.load_scene()

    # ------------------------------------------------------------------
    # Цвет pipes — runtime-статусы wire-соединений
    # ------------------------------------------------------------------

    def _rebuild_pipe_map(self) -> None:
        """Построить маппинг wire_key → pipe QGraphicsPathItem.

        Обходит items сцены NodeGraphQt, ищет pipe items (имеют input_port
        и output_port), сопоставляет их с _addr_wire_map по адресам портов.
        Все найденные pipes окрашиваются в цвет NOT_APPLIED (серый).
        """
        self._wire_key_to_pipe.clear()

        try:
            viewer = self._graph.viewer()
            if viewer is None:
                return
            scene = viewer.scene()
            if scene is None:
                return

            for item in scene.items():
                in_port = getattr(item, "input_port", None)
                out_port = getattr(item, "output_port", None)
                if in_port is None or out_port is None:
                    continue

                wire_key = self._find_wire_key_for_ports(in_port, out_port)
                if wire_key is not None:
                    self._wire_key_to_pipe[wire_key] = item
                    # Сбросить цвет в NOT_APPLIED
                    self._set_pipe_color(item, WireStatus.NOT_APPLIED)

        except Exception as exc:
            logger.debug("_rebuild_pipe_map: %s", exc)

    def _set_pipe_color(self, pipe_item: Any, status: WireStatus) -> None:
        """Установить цвет pipe item согласно статусу wire.

        NodeGraphQt pipe items — QGraphicsPathItem. Цвет задаётся через QPen.
        Для ACTIVE — толщина 3px, остальные — 2px.

        Args:
            pipe_item: QGraphicsPathItem из сцены NodeGraphQt.
            status: Статус wire для выбора цвета.
        """
        rgb = WIRE_STATUS_COLORS.get(status, WIRE_STATUS_COLORS[WireStatus.NOT_APPLIED])
        color = QColor(*rgb)
        width = 3 if status == WireStatus.ACTIVE else 2

        try:
            # Пробуем API NodeGraphQt если есть метод set_color
            if hasattr(pipe_item, "set_color"):
                pipe_item.set_color(*rgb)
                return
        except Exception:
            pass

        try:
            pen = pipe_item.pen()
            pen.setColor(color)
            pen.setWidth(width)
            pipe_item.setPen(pen)
        except Exception as exc:
            logger.debug("_set_pipe_color: не удалось установить цвет — %s", exc)

    def update_wire_colors(self, statuses: dict[str, WireStatus]) -> None:
        """Обновить цвета pipes на канвасе согласно runtime-статусам.

        Вызывается из ConstructorTabWidget при получении сигнала
        WireDataBridge.statuses_changed.

        Args:
            statuses: Словарь wire_key → WireStatus от WireDataBridge.
        """
        for wire_key, status in statuses.items():
            pipe_item = self._wire_key_to_pipe.get(wire_key)
            if pipe_item is not None:
                self._set_pipe_color(pipe_item, status)
            else:
                logger.debug(
                    "update_wire_colors: pipe для wire '%s' не найден в маппинге",
                    wire_key,
                )

    # ------------------------------------------------------------------
    # Qt-сигнал: port_connected (user drag wire)
    # ------------------------------------------------------------------

    def _on_port_connected(self, in_port: Any, out_port: Any) -> None:
        """Пользователь соединил два порта — создаём wire в модели.

        NodeGraphQt порядок: (input_port, output_port).
        Wire-модель: source (output) → target (input).
        """
        if self._suppress:
            return

        target_qt_node = in_port.node()
        source_qt_node = out_port.node()

        target_pk = self._reverse_map.get(target_qt_node.id)
        source_pk = self._reverse_map.get(source_qt_node.id)

        if target_pk is None or source_pk is None:
            logger.warning(
                "_on_port_connected: нода не найдена в reverse_map",
            )
            return

        # Port name на ноде: "plugin_name.port_name"
        # Wire address формат: "process_key.plugin_name.port_name"
        out_port_name = out_port.name()
        in_port_name = in_port.name()

        source_addr = f"{source_pk}.{out_port_name}"
        target_addr = f"{target_pk}.{in_port_name}"

        # Добавляем wire через WireEditorModel (валидация + запись в topology)
        wire_key = self._wire_model.add_wire(
            source=source_addr,
            target=target_addr,
            description=f"{source_pk} → {target_pk}",
        )

        if not wire_key:
            # Валидация не прошла — отменяем соединение в NodeGraphQt
            reason = "; ".join(
                self._wire_model.validate_wire(source_addr, target_addr),
            )
            logger.info(
                "Wire отклонён: %s → %s — %s",
                source_addr, target_addr, reason,
            )
            with self._block_signals():
                in_port.disconnect_from(out_port)
            self.wire_rejected.emit(source_addr, target_addr, reason)
            return

        # Зарегистрировать маппинг адресов → wire_key
        self._addr_wire_map[(source_addr, target_addr)] = wire_key

        # Найти pipe item в сцене и сохранить в маппинг wire_key → pipe
        self._register_pipe_for_wire(wire_key, in_port, out_port)

        logger.info(
            "Wire создан: %s — %s → %s",
            wire_key, source_addr, target_addr,
        )

    def _register_pipe_for_wire(
        self,
        wire_key: str,
        in_port: Any,
        out_port: Any,
    ) -> None:
        """Найти pipe item в сцене для пары портов и сохранить в маппинг.

        Вызывается после успешного создания wire через drag-connect.

        Args:
            wire_key: Ключ wire в конфигурации.
            in_port: Входной порт NodeGraphQt.
            out_port: Выходной порт NodeGraphQt.
        """
        try:
            viewer = self._graph.viewer()
            if viewer is None:
                return
            scene = viewer.scene()
            if scene is None:
                return

            # Ищем pipe item, у которого совпадают порты
            for item in scene.items():
                item_in = getattr(item, "input_port", None)
                item_out = getattr(item, "output_port", None)
                if item_in is None or item_out is None:
                    continue
                # Сравниваем по объекту (ссылка)
                if item_in is in_port and item_out is out_port:
                    self._wire_key_to_pipe[wire_key] = item
                    self._set_pipe_color(item, WireStatus.NOT_APPLIED)
                    logger.debug(
                        "_register_pipe_for_wire: pipe для wire '%s' зарегистрирован",
                        wire_key,
                    )
                    return

            logger.debug(
                "_register_pipe_for_wire: pipe для wire '%s' не найден в сцене",
                wire_key,
            )
        except Exception as exc:
            logger.debug("_register_pipe_for_wire: %s", exc)

    # ------------------------------------------------------------------
    # Qt-сигнал: port_disconnected
    # ------------------------------------------------------------------

    def _on_port_disconnected(self, in_port: Any, out_port: Any) -> None:
        """Пользователь разорвал соединение — удаляем wire из модели."""
        if self._suppress:
            return

        target_qt_node = in_port.node()
        source_qt_node = out_port.node()

        target_pk = self._reverse_map.get(target_qt_node.id)
        source_pk = self._reverse_map.get(source_qt_node.id)

        if target_pk is None or source_pk is None:
            return

        out_port_name = out_port.name()
        in_port_name = in_port.name()

        source_addr = f"{source_pk}.{out_port_name}"
        target_addr = f"{target_pk}.{in_port_name}"

        # Найти wire_key по source+target
        for wk, wire in self._wire_model.wires.items():
            if wire.get("source") == source_addr and wire.get("target") == target_addr:
                self._wire_model.remove_wire(wk)
                # Удалить из маппинга адресов → wire_key
                self._addr_wire_map.pop((source_addr, target_addr), None)
                # Удалить из маппинга wire_key → pipe
                self._wire_key_to_pipe.pop(wk, None)
                logger.info("Wire удалён: %s", wk)
                return

        logger.warning(
            "_on_port_disconnected: wire не найден для %s → %s",
            source_addr, target_addr,
        )

    # ------------------------------------------------------------------
    # Qt-сигнал: node_selection_changed
    # ------------------------------------------------------------------

    def _on_node_selection_changed(
        self,
        selected: list[Any],
        deselected: list[Any],
    ) -> None:
        """Обработчик смены выделения — для правой панели.

        NodeGraphQt v0.5.2 не имеет edge_selection_changed сигнала.
        Workaround: если нод не выбрано, проверяем через QTimer,
        не выбран ли pipe на сцене (после обновления scene.selectedItems).
        """
        if self._suppress:
            return

        if selected:
            qt_node = selected[0]
            pk = self._reverse_map.get(qt_node.id)
            if pk is not None:
                self.node_selected.emit(pk)
        else:
            # Нод не выбрано — может быть выбран pipe?
            # Задержка 50мс чтобы scene успела обновить selectedItems
            QTimer.singleShot(50, self._check_pipe_selection)

    def _check_pipe_selection(self) -> None:
        """Проверить, выбран ли pipe (wire) на сцене NodeGraphQt.

        Вызывается с задержкой через QTimer после снятия выделения с ноды.
        NodeGraphQt pipe items имеют атрибуты input_port и output_port.
        """
        if self._suppress:
            return
        try:
            viewer = self._graph.viewer()
            if viewer is None:
                return
            scene = viewer.scene()
            if scene is None:
                return

            for item in scene.selectedItems():
                # Pipe items в NodeGraphQt имеют input_port и output_port
                in_port = getattr(item, "input_port", None)
                out_port = getattr(item, "output_port", None)
                if in_port is not None and out_port is not None:
                    wire_key = self._find_wire_key_for_ports(in_port, out_port)
                    if wire_key:
                        self.wire_selected.emit(wire_key)
                        return

            # Ничего не выбрано — очистить выделение
            self.selection_cleared.emit()
        except Exception as exc:
            logger.debug("_check_pipe_selection: %s", exc)
            self.selection_cleared.emit()

    def _find_wire_key_for_ports(self, in_port: Any, out_port: Any) -> str | None:
        """Найти wire_key по NodeGraphQt портам pipe item.

        Args:
            in_port: Входной порт pipe item (target).
            out_port: Выходной порт pipe item (source).

        Returns:
            wire_key или None если не найден.
        """
        target_qt_node = in_port.node()
        source_qt_node = out_port.node()

        target_pk = self._reverse_map.get(target_qt_node.id)
        source_pk = self._reverse_map.get(source_qt_node.id)

        if target_pk is None or source_pk is None:
            return None

        source_addr = f"{source_pk}.{out_port.name()}"
        target_addr = f"{target_pk}.{in_port.name()}"

        return self._addr_wire_map.get((source_addr, target_addr))

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    @property
    def node_map(self) -> dict[str, PluginProcessNode]:
        """Маппинг process_key → PluginProcessNode (read-only copy)."""
        return dict(self._node_map)

    @property
    def graph(self) -> NodeGraph:
        return self._graph

    def wire_key_for_edge(self, source_addr: str, target_addr: str) -> str | None:
        """Публичный lookup wire_key по адресам портов.

        Args:
            source_addr: Адрес источника формата "process.plugin.port".
            target_addr: Адрес цели формата "process.plugin.port".

        Returns:
            wire_key или None если соединение не найдено.
        """
        return self._addr_wire_map.get((source_addr, target_addr))

    def fit_to_view(self) -> None:
        """Подогнать вид канваса под все ноды."""
        try:
            self._graph.fit_to_selection()
        except Exception:
            # Fallback если нет выделения
            all_nodes = self._graph.all_nodes()
            if all_nodes:
                self._graph.set_selection(all_nodes)
                self._graph.fit_to_selection()
                self._graph.clear_selection()


__all__ = ["PluginGraphAdapter", "WIRE_STATUS_COLORS"]
