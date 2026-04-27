"""Презентер Chain Editor: связывает ChainEditorModel и ChainEditorWidget."""

from __future__ import annotations

import copy
import logging
from typing import Any

from registers.pipeline.processing_node import ProcessingNode
from registers.processor.catalog.schemas import ProcessingOperationDef
from services.processor.chain.autofill import autofill_inputs

from .model import ChainEditorModel
from .panel_widget import ChainEditorWidget

logger = logging.getLogger(__name__)


class ChainEditorPresenter:
    """Связывает ChainEditorModel и ChainEditorWidget.

    Отвечает за:
    - загрузку данных из модели в виджет
    - подписку на nodes_changed и синхронизацию модели при изменениях
    - вызов autofill_inputs после каждого изменения цепочки
    - запись изменений в action_bus (если подключён)
    """

    def __init__(
        self,
        *,
        model: ChainEditorModel,
        widget: ChainEditorWidget,
        action_bus: Any | None = None,
    ) -> None:
        """Инициализация: привязать модель к виджету и подписаться на сигналы.

        Args:
            model: Модель цепочки обработки.
            widget: Виджет таблицы цепочки.
            action_bus: ActionBus для записи изменений (опционально).
        """
        self._model = model
        self._widget = widget
        self._action_bus = action_bus

        # Передать текущее состояние в виджет
        self._push_to_widget()

        # Подписаться на изменения таблицы
        self._widget.nodes_changed.connect(self._on_nodes_changed)

    def load(
        self,
        nodes: dict[str, ProcessingNode],
        catalog: dict[str, ProcessingOperationDef],
        region_id: str,
    ) -> None:
        """Загрузить новые данные в модель и обновить виджет.

        Вызывается снаружи при смене региона или перезагрузке цепочки.
        """
        self._model.nodes = autofill_inputs(nodes)
        self._model.catalog = catalog
        self._model.region_id = region_id
        self._push_to_widget()

    def get_nodes(self) -> dict[str, ProcessingNode]:
        """Получить текущие узлы из виджета с пересчётом inputs."""
        return self._widget.get_nodes()

    # --- Внутренние методы ---

    def _push_to_widget(self) -> None:
        """Передать состояние модели в виджет."""
        # Сначала синхронизировать количество воркеров — до перерисовки таблицы
        self._widget.set_worker_count(self._model.worker_count)
        self._widget.set_data(
            nodes=self._model.nodes,
            catalog=self._model.catalog,
            region_id=self._model.region_id,
        )

    def _on_nodes_changed(self) -> None:
        """Обработчик сигнала nodes_changed: синхронизировать модель из виджета."""
        # Снимок до изменения (для undo)
        nodes_before = copy.deepcopy(self._model.nodes)

        # Читаем актуальное состояние из виджета (autofill уже применён внутри)
        updated_nodes = self._widget.get_nodes()
        # Применяем autofill ещё раз для гарантии консистентности модели
        self._model.nodes = autofill_inputs(updated_nodes)

        # Запись в bus (если подключён)
        if self._action_bus is not None:
            nodes_after = {
                k: v.model_dump() if hasattr(v, "model_dump") else v
                for k, v in self._model.nodes.items()
            }
            nodes_before_dump = {
                k: v.model_dump() if hasattr(v, "model_dump") else v
                for k, v in nodes_before.items()
            }
            from multiprocess_prototype_v3.frontend.actions.builder import ActionBuilder

            action = ActionBuilder.step_modify(
                self._model.region_id,
                "batch",
                nodes_before_dump,
                nodes_after,
            )
            self._action_bus.record(action)
