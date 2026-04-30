"""InspectorPanel — панель инспектора свойств выбранного узла графа.

Содержит три секции:
  - ProcessIdCombo — выбор процесса
  - DisplayTargetCombo — multi-select дисплеев
  - ParamsForm — авто-генерируемая форма параметров

Все изменения проходят через ActionBus с поддержкой undo/redo.
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import Callable
from copy import deepcopy
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QGroupBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from frontend.actions.builder import ActionBuilder
from frontend.actions.bus import ActionBus
from frontend.actions.schemas import ActionType
from ..canvas.model import GraphEditorModel

from ..bridges.display_target_combo import DisplayTargetCombo
from .params_form import ParamsForm
from ..bridges.process_id_combo import ProcessIdCombo

logger = logging.getLogger(__name__)


class InspectorPanel(QWidget):
    """Панель инспектора свойств выбранного узла графа.

    Signals:
        node_modified(str, dict): (node_id, fields_after) — после успешного изменения.
    """

    node_modified = Signal(str, dict)

    def __init__(
        self,
        *,
        model: GraphEditorModel,
        action_bus: ActionBus,
        catalog: dict[str, Any],
        region_id: str,
        known_processes_provider: Callable[[], list[str]],
        known_displays_provider: Callable[[], list[str]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self._model = model
        self._action_bus = action_bus
        self._catalog = catalog
        self._region_id = region_id
        self._known_processes_provider = known_processes_provider
        self._known_displays_provider = known_displays_provider

        # Текущий выбранный узел
        self._current_node_id: str | None = None

        # Кэш резолва params_class: dotted_path -> type
        self._params_class_cache: dict[str, type] = {}

        # Блокировка рекурсивных сигналов (при programmatic update)
        self._suppress_changes = False

        self._init_ui()

        # Подписка на ActionBus для refresh при undo/redo
        self._action_bus.add_change_callback(self._on_action_bus_changed)

    def _init_ui(self) -> None:
        """Инициализация UI."""
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(4, 4, 4, 4)

        # Заголовок
        self._title_label = QLabel("Выберите ноду в графе")
        self._title_label.setObjectName("PanelTitleLg")
        self._main_layout.addWidget(self._title_label)

        # --- GroupBox «Общее» ---
        self._general_group = QGroupBox("Общее")
        general_layout = QVBoxLayout(self._general_group)

        self._operation_label = QLabel("")
        general_layout.addWidget(self._operation_label)

        self._process_id_combo = ProcessIdCombo()
        general_layout.addWidget(self._process_id_combo)

        self._main_layout.addWidget(self._general_group)

        # --- GroupBox «Display» ---
        self._display_group = QGroupBox("Display")
        display_layout = QVBoxLayout(self._display_group)

        self._display_target_combo = DisplayTargetCombo()
        display_layout.addWidget(self._display_target_combo)

        self._main_layout.addWidget(self._display_group)

        # --- GroupBox «Параметры» ---
        self._params_group = QGroupBox("Параметры")
        params_layout = QVBoxLayout(self._params_group)

        self._params_form = ParamsForm()
        params_layout.addWidget(self._params_form)

        self._main_layout.addWidget(self._params_group)

        # Placeholder (показывается когда нет выбранной ноды)
        self._placeholder = QLabel("Выберите ноду в графе")
        self._placeholder.setObjectName("MutedLabel")
        self._main_layout.addWidget(self._placeholder)

        # Распорка
        self._main_layout.addStretch(1)

        # Скрыть секции до выбора ноды
        self._set_sections_visible(False)

        # Подключение сигналов виджетов
        self._process_id_combo.process_id_changed.connect(self._on_process_id_changed)
        self._display_target_combo.display_targets_changed.connect(
            self._on_display_targets_changed,
        )
        self._params_form.params_changed.connect(self._on_params_changed)

    def _set_sections_visible(self, visible: bool) -> None:
        """Показать/скрыть секции инспектора."""
        self._general_group.setVisible(visible)
        self._display_group.setVisible(visible)
        self._params_group.setVisible(visible)
        self._placeholder.setVisible(not visible)
        if visible:
            self._title_label.setVisible(True)

    # ------------------------------------------------------------------
    # Публичные методы
    # ------------------------------------------------------------------

    def show_node_by_id(self, node_id: str) -> None:
        """Показать свойства узла по его id.

        Args:
            node_id: Идентификатор узла в модели графа.
        """
        nodes = self._model.nodes
        node = nodes.get(node_id)
        if node is None:
            self.clear()
            return

        self._current_node_id = node_id
        self._suppress_changes = True
        try:
            self._set_sections_visible(True)

            # Заголовок
            op_def = self._catalog.get(node.operation_ref)
            if op_def is None:
                self._title_label.setText(f"Узел: {node_id[:12]}…")
                self._operation_label.setText("Операция не найдена в каталоге")
                self._params_form.set_schema(None, {})
                self._display_group.setEnabled(False)
                self._suppress_changes = False
                return

            self._title_label.setText(f"{op_def.name}")
            self._operation_label.setText(f"Операция: {op_def.name} ({op_def.type_key})")

            # Process ID
            known_processes = self._known_processes_provider()
            self._process_id_combo.set_known_processes(
                known_processes,
                current=node.process_id,
            )

            # Display targets
            display_capable = getattr(op_def, "display_capable", False)
            self._display_group.setEnabled(display_capable)
            known_displays = self._known_displays_provider()
            self._display_target_combo.set_known_displays(
                known_displays,
                current=list(node.display_targets),
            )

            # Params
            params_class = self._resolve_params_class(op_def.params_schema)
            self._params_form.set_schema(params_class, dict(node.params))

        finally:
            self._suppress_changes = False

    def clear(self) -> None:
        """Сбросить текущий выбор и показать плейсхолдер."""
        self._current_node_id = None
        self._title_label.setText("Выберите ноду в графе")
        self._set_sections_visible(False)

    def refresh(self) -> None:
        """Перезагрузить данные текущей ноды из модели (после undo/redo)."""
        if self._current_node_id is not None:
            self.show_node_by_id(self._current_node_id)

    @property
    def current_node_id(self) -> str | None:
        """Текущий выбранный node_id."""
        return self._current_node_id

    # ------------------------------------------------------------------
    # Обработчики изменений виджетов
    # ------------------------------------------------------------------

    def _on_process_id_changed(self, new_process_id: str) -> None:
        """Process ID изменён через combo."""
        if self._suppress_changes or self._current_node_id is None:
            return
        self._apply_modification({"process_id": new_process_id})

    def _on_display_targets_changed(self, new_targets: list[str]) -> None:
        """Display targets изменены через combo."""
        if self._suppress_changes or self._current_node_id is None:
            return
        self._apply_modification({"display_targets": new_targets})

    def _on_params_changed(self, new_params: dict[str, Any]) -> None:
        """Параметры изменены через форму."""
        if self._suppress_changes or self._current_node_id is None:
            return
        self._apply_modification({"params": new_params})

    def _apply_modification(self, fields_after: dict[str, Any]) -> None:
        """Применить изменение к модели и записать в ActionBus.

        Args:
            fields_after: Словарь изменённых полей {имя_поля: новое_значение}.
        """
        node_id = self._current_node_id
        if node_id is None:
            return

        # Снимок до изменения (для undo register)
        nodes_before = self._snapshot_nodes()

        # Считываем текущие значения из модели для fields_before
        nodes = self._model.nodes
        node = nodes.get(node_id)
        if node is None:
            logger.warning("Узел %s не найден в модели при apply_modification", node_id)
            return

        try:
            fields_before, fields_after_actual = self._model.modify_node(
                node_id, fields_after,
            )
        except (KeyError, ValueError) as exc:
            logger.warning("Ошибка modify_node: %s", exc)
            # Revert виджетов к исходным значениям
            self.refresh()
            return

        # Снимок после изменения
        nodes_after = self._snapshot_nodes()

        # Создать и записать action
        action = ActionBuilder.graph_node_modify(
            region_id=self._region_id,
            node_id=node_id,
            fields_before=fields_before,
            fields_after=fields_after_actual,
            nodes_before=nodes_before,
            nodes_after=nodes_after,
        )
        self._action_bus.record(action)

        self.node_modified.emit(node_id, fields_after_actual)

    # ------------------------------------------------------------------
    # ActionBus callback
    # ------------------------------------------------------------------

    def _on_action_bus_changed(self) -> None:
        """Callback от ActionBus: refresh при undo/redo если затрагивает текущую ноду."""
        if self._current_node_id is None:
            return

        event = self._action_bus.last_event
        if event is None:
            return

        event_type, action = event
        if event_type not in ("undo", "redo"):
            return

        # Проверяем что action затрагивает текущую ноду
        if action.action_type == ActionType.GRAPH_NODE_MODIFY:
            patch_node_id = action.forward_patch.get("node_id")
            if patch_node_id == self._current_node_id:
                self.refresh()
        elif action.action_type in (
            ActionType.GRAPH_NODE_ADD,
            ActionType.GRAPH_NODE_REMOVE,
        ):
            # Узел мог быть удалён/восстановлен
            self.refresh()

    # ------------------------------------------------------------------
    # Вспомогательные методы
    # ------------------------------------------------------------------

    def _resolve_params_class(self, dotted_path: str) -> type | None:
        """Резолвить dotted path в класс параметров.

        Кэширует результат. При ошибке импорта возвращает None.
        """
        if dotted_path in self._params_class_cache:
            return self._params_class_cache[dotted_path]

        try:
            parts = dotted_path.rsplit(".", 1)
            if len(parts) != 2:
                logger.warning("Некорректный params_schema путь: %s", dotted_path)
                self._params_class_cache[dotted_path] = None  # type: ignore[assignment]
                return None

            module_path, class_name = parts
            module = importlib.import_module(module_path)
            cls = getattr(module, class_name)
            self._params_class_cache[dotted_path] = cls
            return cls
        except Exception as exc:
            logger.warning("Не удалось импортировать params_class %s: %s", dotted_path, exc)
            self._params_class_cache[dotted_path] = None  # type: ignore[assignment]
            return None

    def _snapshot_nodes(self) -> dict[str, Any]:
        """Снимок всех узлов модели (deepcopy dict-представления)."""
        nodes = self._model.nodes
        result = {}
        for nid, node in nodes.items():
            if hasattr(node, "model_dump"):
                result[nid] = node.model_dump()
            else:
                result[nid] = deepcopy(node)
        return result


__all__ = ["InspectorPanel"]
