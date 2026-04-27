# multiprocess_prototype_v3/frontend/widgets/processing_panel_widget/presenter.py
"""Презентер панели обработки: контролы пишут в регистры напрямую; слой для будущей логики."""

from __future__ import annotations

import logging
from typing import Any, Optional

from multiprocess_prototype_v3.frontend.actions.builder import ActionBuilder

from .model import ProcessingPanelModel

logger = logging.getLogger(__name__)


class ProcessingPanelPresenter:
    """Зарезервировано под команды и синхронизацию вне register-bound контролов."""

    def __init__(
        self,
        *,
        view: Any,
        model: ProcessingPanelModel,
        action_bus: Optional[Any] = None,
    ) -> None:
        """Резерв: view/model для будущих команд без прямой привязки к контролам.

        action_bus — ActionBus для undo-able изменений полей (или None — нет шины).
        """
        self._view = view
        self._model = model
        self._bus = action_bus

    def on_field_changed(
        self,
        register_name: str,
        field_name: str,
        new_value: Any,
        old_value: Any,
    ) -> None:
        """Записать изменение поля через ActionBus (undo-able).

        Если bus не задан — логируем предупреждение и ничего не делаем.
        Прямой rm-вызов остаётся в register-bound контролах.
        """
        if self._bus is None:
            logger.warning(
                "on_field_changed вызван без action_bus: %s.%s", register_name, field_name
            )
            return
        action = ActionBuilder.field_set(
            register_name,
            field_name,
            new_value,
            old_value,
            description=f"{register_name}.{field_name}: {old_value} → {new_value}",
        )
        self._bus.execute(action)
