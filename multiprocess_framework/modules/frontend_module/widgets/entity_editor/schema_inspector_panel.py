"""SchemaInspectorPanel — универсальная панель свойств.

Строит авто-форму из SchemaBase + FieldMeta для любого объекта
(регион, камера, ProcessingNode и т.д.).

Принимает item_key + schema_dict + schema_class, делегирует отрисовку
ParamsForm и транслирует её сигнал params_changed в field_changed(item_key, "__all__", dict).
"""

from __future__ import annotations

import logging
from typing import Any

from multiprocess_framework.modules.frontend_module.core.qt_imports import (
    QLabel,
    QVBoxLayout,
    QWidget,
    Signal,
)

from .params_form import ParamsForm

logger = logging.getLogger(__name__)


class SchemaInspectorPanel(QWidget):
    """Панель свойств: авто-форма по SchemaBase для любого элемента.

    Использование:
        panel = SchemaInspectorPanel()
        panel.field_changed.connect(on_field_changed)
        panel.show_item("node_1", node_dict, NodeParams)

    Сигнал field_changed испускается при каждом изменении любого поля формы.
    Второй аргумент всегда "__all__" — caller получает полный dict параметров.
    """

    # (item_key, "__all__", dict_всех_параметров)
    field_changed = Signal(str, str, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        # Основной вертикальный layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Заголовок — имя текущего элемента
        self._header = QLabel("")
        self._header.setObjectName("InspectorHeader")
        layout.addWidget(self._header)

        # Заглушка «Выберите элемент» — видна когда ничего не выбрано
        self._placeholder = QLabel("Выберите элемент")
        self._placeholder.setObjectName("MutedLabel")
        layout.addWidget(self._placeholder)

        # Форма параметров — скрыта до первого show_item
        self._form = ParamsForm()
        self._form.setVisible(False)
        layout.addWidget(self._form)

        # Растягиваем пространство вниз чтобы форма прижималась к верху
        layout.addStretch()

        # Состояние
        self._item_key: str | None = None
        self._schema_class: type | None = None

        # Guard: блокирует emit во время programmatic load
        self._suppress = False

        # Подключаем сигнал формы
        self._form.params_changed.connect(self._on_params_changed)

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def show_item(
        self,
        item_key: str,
        schema_dict: dict[str, Any],
        schema_class: type,
    ) -> None:
        """Загрузить элемент и построить форму по его схеме.

        Args:
            item_key: Уникальный ключ элемента (используется в field_changed).
            schema_dict: Текущие значения полей элемента (plain dict).
            schema_class: Pydantic-класс схемы (SchemaBase или его наследник).
        """
        self._item_key = item_key
        self._schema_class = schema_class

        # Обновляем заголовок
        self._header.setText(item_key)

        # Загружаем форму без рекурсивных emit
        self._suppress = True
        try:
            self._form.set_schema(schema_class, schema_dict)
        finally:
            self._suppress = False

        # Показываем форму, скрываем заглушку
        self._placeholder.setVisible(False)
        self._form.setVisible(True)

        logger.debug("SchemaInspectorPanel: загружен элемент '%s'", item_key)

    def clear(self) -> None:
        """Сбросить панель: скрыть форму, показать заглушку."""
        self._item_key = None
        self._schema_class = None
        self._header.setText("")

        self._form.setVisible(False)
        self._placeholder.setVisible(True)

        logger.debug("SchemaInspectorPanel: сброшена")

    def refresh(self, schema_dict: dict[str, Any]) -> None:
        """Обновить значения виджетов без пересборки формы (напр. undo/redo).

        Если элемент не загружен — ничего не делает.

        Args:
            schema_dict: Новые значения полей (plain dict).
        """
        if self._item_key is None or self._schema_class is None:
            return
        # set_values_silent уже содержит собственный suppress
        self._form.set_values_silent(schema_dict)

    # ------------------------------------------------------------------
    # Внутренние обработчики
    # ------------------------------------------------------------------

    def _on_params_changed(self, new_params: dict[str, Any]) -> None:
        """Принять изменения из ParamsForm и ретранслировать в field_changed.

        Не вызывается при programmatic load благодаря флагу _suppress.
        """
        if self._suppress:
            return

        if self._item_key is None:
            # Форма изменилась, но ключ элемента уже сброшен — игнорируем
            logger.warning("SchemaInspectorPanel: params_changed без item_key, пропускаем")
            return

        self.field_changed.emit(self._item_key, "__all__", new_params)
        logger.debug("SchemaInspectorPanel: field_changed emitted для '%s'", self._item_key)


__all__ = ["SchemaInspectorPanel"]
