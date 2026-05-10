"""PluginConfigPanel — авто-форма редактирования конфига выбранного плагина.

При выборе карточки плагина строит форму из полей его PluginConfig.
Использует ParamsForm для авто-генерации виджетов по типам полей.

Сигнал config_changed(proc_key, plugin_index, updated_fields) эмитируется
при изменении любого поля формы.
"""

from __future__ import annotations

import importlib
import inspect
import logging
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from multiprocess_prototype.frontend.widgets.base.editor.params_form import ParamsForm

logger = logging.getLogger(__name__)

# Системные поля PluginConfig — не показывать в форме
_SYSTEM_FIELDS: frozenset[str] = frozenset({
    "plugin_class",
    "plugin_name",
    "category",
    "schema_id",
    "schema_version",
})


class PluginConfigPanel(QWidget):
    """Панель редактирования конфига выбранного плагина.

    Строит авто-форму из полей PluginConfig-наследника:
      - str  → QLineEdit
      - int  → QSpinBox
      - float → QDoubleSpinBox
      - bool → QCheckBox

    Системные поля (plugin_class, plugin_name, category и т.д.) скрыты.
    При изменении любого поля эмитирует config_changed.

    Пример использования:
        panel = PluginConfigPanel()
        panel.config_changed.connect(on_config_changed)
        panel.show_plugin("proc_1", 0, plugin_dict)
    """

    # (proc_key, plugin_index, updated_fields)
    config_changed = Signal(str, int, dict)

    # Кэш config-классов: путь к plugin_class → тип (или None если не найден)
    _config_cache: dict[str, type | None] = {}

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        # Текущий контекст плагина
        self._proc_key: str = ""
        self._plugin_index: int = 0
        self._plugin_dict: dict[str, Any] = {}
        self._config_class: type | None = None

        self._setup_ui()

    # ------------------------------------------------------------------
    # Построение UI
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """Инициализировать компоновку: заголовок, placeholder, scroll + форма."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        # Заголовок — имя плагина
        self._header = QLabel("")
        self._header.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(self._header)

        # Заглушка — видна когда ничего не выбрано
        self._placeholder = QLabel("Выберите плагин для редактирования")
        self._placeholder.setObjectName("MutedLabel")
        self._placeholder.setStyleSheet("color: #9E9E9E;")
        layout.addWidget(self._placeholder)

        # Scroll area с формой параметров
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        # Внутренний контейнер для QFormLayout через ParamsForm
        self._form = ParamsForm()
        self._form.params_changed.connect(self._on_params_changed)

        self._scroll.setWidget(self._form)
        self._scroll.setVisible(False)
        layout.addWidget(self._scroll, stretch=1)

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def show_plugin(
        self,
        proc_key: str,
        plugin_index: int,
        plugin_dict: dict[str, Any],
    ) -> None:
        """Загрузить плагин и построить форму по его PluginConfig.

        Args:
            proc_key:     Ключ родительского процесса (напр. "proc_1").
            plugin_index: Индекс плагина в списке plugins процесса.
            plugin_dict:  Словарь конфига плагина (из GenericProcessConfig.plugins).
        """
        self._proc_key = proc_key
        self._plugin_index = plugin_index
        self._plugin_dict = dict(plugin_dict)

        # Обновить заголовок
        plugin_name = plugin_dict.get("plugin_name") or plugin_dict.get("plugin_class", "")
        self._header.setText(plugin_name)

        # Найти config-класс
        plugin_class_path = plugin_dict.get("plugin_class", "")
        self._config_class = self._find_config_class(plugin_class_path)

        # Построить dict только из не-системных полей
        filtered_dict = self._filter_dict(plugin_dict)

        # Загрузить форму с подавлением сигналов
        self._form.blockSignals(True)
        try:
            self._form.set_schema(self._config_class, filtered_dict)
            # Удалить системные поля из формы (они могут быть унаследованы config_class)
            self._remove_system_fields_from_form()
        finally:
            self._form.blockSignals(False)

        # Показать форму, скрыть placeholder
        self._placeholder.setVisible(False)
        self._scroll.setVisible(True)

        logger.debug(
            "PluginConfigPanel: загружен плагин '%s' (proc='%s', idx=%d, config=%s)",
            plugin_name,
            proc_key,
            plugin_index,
            self._config_class.__name__ if self._config_class else "None",
        )

    def clear(self) -> None:
        """Очистить форму и показать placeholder."""
        self._proc_key = ""
        self._plugin_index = 0
        self._plugin_dict = {}
        self._config_class = None

        self._header.setText("")

        # Сбросить форму без сигналов
        self._form.blockSignals(True)
        try:
            self._form.set_schema(None, {})
        finally:
            self._form.blockSignals(False)

        self._scroll.setVisible(False)
        self._placeholder.setVisible(True)

        logger.debug("PluginConfigPanel: сброшена")

    # ------------------------------------------------------------------
    # Внутренние методы
    # ------------------------------------------------------------------

    def _find_config_class(self, plugin_class_path: str) -> type | None:
        """Найти PluginConfig-наследник по пути к классу плагина.

        Алгоритм:
        1. Из пути 'a.b.c.plugin.PluginClass' вычислить config-модуль 'a.b.c.config'
        2. Импортировать модуль
        3. Найти в нём подкласс PluginConfig через inspect

        Результат кэшируется в _config_cache.

        Args:
            plugin_class_path: Dotted path к классу плагина.

        Returns:
            Тип PluginConfig-наследника или None если не найден.
        """
        if not plugin_class_path:
            return None

        # Проверить кэш
        if plugin_class_path in PluginConfigPanel._config_cache:
            return PluginConfigPanel._config_cache[plugin_class_path]

        config_class = self._import_config_class(plugin_class_path)

        # Сохранить в кэш
        PluginConfigPanel._config_cache[plugin_class_path] = config_class
        return config_class

    def _import_config_class(self, plugin_class_path: str) -> type | None:
        """Выполнить импорт и поиск PluginConfig-наследника.

        Args:
            plugin_class_path: Dotted path к классу плагина.

        Returns:
            Тип или None при ошибке.
        """
        # Вычислить путь к модулю config: убрать последний сегмент (класс)
        # и последний пакет (plugin), заменить на 'config'
        # Пример: 'a.b.plugins.capture.plugin.CapturePlugin' → 'a.b.plugins.capture.config'
        parts = plugin_class_path.rsplit(".", 1)  # ['a.b.plugins.capture.plugin', 'CapturePlugin']
        if len(parts) < 2:
            logger.warning(
                "PluginConfigPanel: невалидный plugin_class_path '%s'", plugin_class_path
            )
            return None

        module_path = parts[0]  # 'a.b.plugins.capture.plugin'
        # Заменяем последний сегмент модуля (plugin) на 'config'
        module_parts = module_path.rsplit(".", 1)  # ['a.b.plugins.capture', 'plugin']
        if len(module_parts) < 2:
            config_module_path = f"{module_path}.config"
        else:
            config_module_path = f"{module_parts[0]}.config"

        try:
            config_module = importlib.import_module(config_module_path)
        except ImportError:
            logger.warning(
                "PluginConfigPanel: не удалось импортировать модуль конфига '%s'",
                config_module_path,
            )
            return None

        # Найти PluginConfig-наследник в модуле
        try:
            from multiprocess_framework.modules.process_module.generic.generic_process_config import (
                PluginConfig,
            )
        except ImportError:
            logger.error("PluginConfigPanel: не удалось импортировать PluginConfig")
            return None

        for _name, obj in inspect.getmembers(config_module, inspect.isclass):
            if issubclass(obj, PluginConfig) and obj is not PluginConfig:
                logger.debug(
                    "PluginConfigPanel: найден config-класс '%s' в '%s'",
                    obj.__name__,
                    config_module_path,
                )
                return obj

        logger.warning(
            "PluginConfigPanel: PluginConfig-наследник не найден в '%s'",
            config_module_path,
        )
        return None

    def _remove_system_fields_from_form(self) -> None:
        """Удалить виджеты системных полей из формы после set_schema.

        ParamsForm строит форму по model_fields класса, включая унаследованные
        системные поля (plugin_class, plugin_name, category и др.).
        Этот метод удаляет их из QFormLayout и _field_widgets.
        """
        for field_name in list(self._form._field_widgets.keys()):
            if field_name in _SYSTEM_FIELDS:
                widget = self._form._field_widgets.pop(field_name)
                # Удалить строку из QFormLayout по виджету
                self._form._layout.removeRow(widget)

    def _filter_dict(self, plugin_dict: dict[str, Any]) -> dict[str, Any]:
        """Убрать системные поля из словаря для формы.

        Args:
            plugin_dict: Исходный dict конфига плагина.

        Returns:
            Dict без _SYSTEM_FIELDS.
        """
        return {
            key: value
            for key, value in plugin_dict.items()
            if key not in _SYSTEM_FIELDS
        }

    def _on_params_changed(self, new_params: dict[str, Any]) -> None:
        """Обработать изменение любого поля формы.

        Собирает обновлённые поля (только не-системные) и эмитирует config_changed.

        Args:
            new_params: Полный dict параметров из ParamsForm.
        """
        if not self._proc_key:
            return

        self.config_changed.emit(
            self._proc_key,
            self._plugin_index,
            new_params,
        )

        logger.debug(
            "PluginConfigPanel: config_changed emitted для '%s'[%d]",
            self._proc_key,
            self._plugin_index,
        )


__all__ = ["PluginConfigPanel"]
