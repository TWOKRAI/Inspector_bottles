# -*- coding: utf-8 -*-
"""ParamsFormSection — форма параметров плагина инспектора (F.6, разрез god-файла).

Строит редакторы полей: типизированные виджеты через CardsFieldFactory (если доступен
live RegistersManager с FieldInfo) либо QLineEdit-fallback. Teardown change-сигналов —
внутренняя ответственность секции (disconnect перед удалением, чтобы не текли сигналы
при переключении нод).

Секция эмитит собственный ``field_changed(field_name, value)`` — процесс (адрес
SetPluginConfig) добавляет панель-оркестратор при переизлучении.
"""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFormLayout, QLabel, QLineEdit, QWidget

from .hikvision_embed import create_hikvision_widget

logger = logging.getLogger(__name__)


class ParamsFormSection(QWidget):
    """Форма параметров выбранного плагина (cards или QLineEdit-fallback)."""

    # Signal: (field_name, value) — процесс добавляет панель при переизлучении.
    field_changed = Signal(str, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # AppServices + live RegistersManager (FieldInfo) — задаются через set_services.
        self._services: Any = None
        self._registers_manager: Any = None
        # Хранит и QLineEdit (fallback) и FieldEditor (cards-режим).
        self._field_editors: dict[str, Any] = {}
        # Флаг: используем типизированные виджеты из CardsFieldFactory.
        self._use_cards: bool = False
        # Ссылки на встроенные контролы Hikvision (держим, иначе GC).
        self._hik_controller: Any = None
        self._hik_runner: Any = None
        # Параметры плагина — БЕЗ вложенного скролла: поля идут одно за другим.
        # Вертикальный overflow обрабатывает мастер-скролл (правый).
        self._layout = QFormLayout(self)
        self._layout.setContentsMargins(0, 4, 0, 4)
        self._layout.setSpacing(6)

    def set_services(self, services: Any, registers_manager: Any) -> None:
        """Передать AppServices + live RegistersManager (FieldInfo для cards)."""
        self._services = services
        self._registers_manager = registers_manager

    # ------------------------------------------------------------------ #
    #  Публичный API                                                       #
    # ------------------------------------------------------------------ #

    def build(
        self,
        plugin_name: str,
        params: dict[str, Any] | None,
        plugins_header: list[dict[str, Any]] | None,
    ) -> bool:
        """Очистить и построить форму: заголовки плагинов + редакторы полей.

        Args:
            plugin_name: имя плагина (= имя регистра). Поля резолвятся ПО НЕМУ через
                RegistersManager.get_fields — тот же путь, что вкладка Plugins.
            params: dict значений конфигурации выбранного плагина.
            plugins_header: список плагинов процесса — их имена показываются строками
                над полями (блок «плагины процесса»).

        Returns:
            True если использованы типизированные cards-виджеты, False — QLineEdit-fallback.
        """
        self.clear()

        for p in plugins_header or []:
            pname = p.get("plugin_name", "") if isinstance(p, dict) else str(p)
            label = QLabel(pname)
            label.setProperty("role", "plugin-name")
            self._layout.addRow(label)

        fields_used = self._try_build_cards_editors(plugin_name, params)
        self._use_cards = bool(fields_used)

        if not self._use_cards and params:
            self._build_lineedit_editors(params)

        return self._use_cards

    def insert_top_widget(self, widget: QWidget) -> None:
        """Вставить виджет первой строкой формы (для hikvision-встройки)."""
        self._layout.insertRow(0, widget)

    def embed_hikvision(self, services: Any, command_sender: Any, topology_bridge: Any) -> None:
        """Встроить контролы камеры Hikvision над полями плагина.

        Ссылки на controller/runner держим здесь (иначе GC); сброс — в clear().
        """
        widget, controller, runner = create_hikvision_widget(services, command_sender, topology_bridge)
        self._hik_runner = runner
        self._hik_controller = controller
        self.insert_top_widget(widget)

    def clear(self) -> None:
        """Удалить все виджеты параметров.

        Для FieldEditor: отключаем change_signal перед удалением, чтобы избежать
        утечек сигналов при переключении нод.
        """
        for _field_name, editor in self._field_editors.items():
            if not isinstance(editor, QLineEdit):
                try:
                    if editor.change_signal is not None:
                        editor.change_signal.disconnect()
                except (RuntimeError, TypeError):
                    pass  # Уже отключён или C++ объект удалён

        self._field_editors.clear()
        self._use_cards = False
        # Сбросить ссылки на встроенные контролы Hikvision (виджеты удалит цикл ниже).
        self._hik_controller = None
        self._hik_runner = None

        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    # ------------------------------------------------------------------ #
    #  Построение редакторов                                              #
    # ------------------------------------------------------------------ #

    def _try_build_cards_editors(self, plugin_name: str, params: dict[str, Any] | None) -> bool:
        """Создать типизированные виджеты через CardsFieldFactory.

        Требует и AppServices, и live RegistersManager (FieldInfo). RegistersManager
        ключует регистры по имени ПЛАГИНА (= имя регистра) — тот же путь, что вкладка
        Plugins. Возвращает False, если нужен QLineEdit-fallback.
        """
        if self._services is None:
            return False

        rm = self._registers_manager
        if rm is None:
            return False

        fields = rm.get_fields(plugin_name)
        if not fields:
            return False

        from multiprocess_prototype.frontend.forms.factory import CardsFieldFactory

        # TODO Phase G (G.4): form_context() не покрыт AppServices Protocol — пока None.
        form_ctx = None

        for field_info in fields:
            editor = CardsFieldFactory.create(field_info, parent=self, form_ctx=form_ctx)

            if params and field_info.field_name in params:
                try:
                    editor.setter(params[field_info.field_name])
                except Exception:
                    logger.debug(
                        "Не удалось установить значение '%s' для поля '%s'",
                        params[field_info.field_name],
                        field_info.field_name,
                    )

            # change_signal подключаем ПОСЛЕ setter — установка значения не эмитит.
            if editor.change_signal is not None:
                fn = field_info.field_name
                editor.change_signal.connect(lambda *_a, _fn=fn, _ed=editor: self._on_field_editor_changed(_fn, _ed))

            self._field_editors[field_info.field_name] = editor
            self._layout.addRow(editor.label, editor.widget)

        return True

    def _build_lineedit_editors(self, params: dict[str, Any]) -> None:
        """Создать QLineEdit-редакторы (fallback если CardsFieldFactory недоступен)."""
        for field_name, value in params.items():
            editor = QLineEdit(str(value))
            editor.setProperty("field_name", field_name)
            editor.editingFinished.connect(lambda fn=field_name, ed=editor: self._on_field_edited(fn, ed))
            self._field_editors[field_name] = editor
            self._layout.addRow(field_name, editor)

    # ------------------------------------------------------------------ #
    #  Обработчики изменений полей                                         #
    # ------------------------------------------------------------------ #

    def _on_field_edited(self, field_name: str, editor: QLineEdit) -> None:
        """QLineEdit-fallback изменён пользователем → field_changed(field, value)."""
        self.field_changed.emit(field_name, editor.text())

    def _on_field_editor_changed(self, field_name: str, editor: Any) -> None:
        """FieldEditor (cards) изменён пользователем → field_changed(field, value)."""
        self.field_changed.emit(field_name, editor.getter())
