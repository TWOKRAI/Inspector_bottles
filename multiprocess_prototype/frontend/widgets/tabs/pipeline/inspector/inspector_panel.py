"""NodeInspectorPanel — панель параметров выбранного узла pipeline.

Task E.1: мигрирован на AppServices DI. set_services(services) вместо
set_context(ctx). RegistersManager и form_context() не покрыты AppServices
Protocol — оставлены как bridge через adapter с TODO Phase F.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from multiprocess_prototype.domain.app_services import AppServices
    from multiprocess_prototype.frontend.forms.field_editor import FieldEditor

from ..graph.constants import CATEGORY_COLORS

logger = logging.getLogger(__name__)


class NodeInspectorPanel(QWidget):
    """Панель параметров выбранного узла pipeline.

    Показывает: имя процесса, категория, список плагинов, параметры.
    Если RegistersManager доступен — создаёт типизированные виджеты
    через CardsFieldFactory. Иначе — QLineEdit (fallback).

    Поддерживает два режима отображения:
    - show_plugin_node() — для plugin-узлов: combo «Процесс назначения» + параметры.
    - show_display_node() — для display-узлов: combo «Display» из DisplayRegistry.

    При отсутствии выбора — placeholder.

    Signals:
        field_changed(process_name, field_name, value): параметр изменён пользователем.
        target_process_changed(node_id, new_process_name): выбран новый процесс назначения.
        display_id_changed(node_id, new_display_id): выбран новый display.
    """

    # Signal: (process_name, field_name, new_value)
    field_changed = Signal(str, str, object)

    # Signal: (node_id, new_process_name) — пользователь выбрал целевой процесс
    target_process_changed = Signal(str, str)

    # Signal: (node_id, new_display_id) — пользователь выбрал display
    display_id_changed = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._current_process: str = ""
        self._current_node_id: str = ""
        self._suppress_changes: bool = False
        # Хранит и QLineEdit (fallback) и FieldEditor (cards-режим)
        self._field_editors: dict[str, Any] = {}
        # Флаг: используем типизированные виджеты из CardsFieldFactory
        self._use_cards: bool = False
        # AppServices — задаётся через set_services()
        self._services: AppServices | None = None
        # Текущий режим отображения: "plugin" или "display"
        self._mode: str = "plugin"
        # Combo «Процесс назначения» (для plugin-узлов)
        self._target_process_combo: QComboBox | None = None
        # Combo «Display» (для display-узлов)
        self._display_id_combo: QComboBox | None = None
        self._init_ui()

    def set_services(self, services: "AppServices") -> None:
        """Передать AppServices для доступа к registers, displays, recipes."""
        self._services = services

    def set_context(self, ctx: object) -> None:
        """Legacy bridge для backward compatibility. Deprecated.

        Если ctx имеет app_services — используем его. Иначе — сохраняем как fallback.
        TODO Phase F: удалить после полной миграции.
        """
        app_services = getattr(ctx, "app_services", None)
        if app_services is not None:
            self._services = app_services

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Placeholder
        self._placeholder = QLabel("Выберите узел")
        self._placeholder.setObjectName("InspectorPlaceholder")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._placeholder)

        # Content container (скрыт когда нет выбора)
        self._content = QWidget()
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(6)

        # Заголовок: имя процесса
        self._title = QLabel()
        self._title.setObjectName("InspectorTitle")
        content_layout.addWidget(self._title)

        # Badge: категория
        self._category_badge = QLabel()
        self._category_badge.setObjectName("InspectorCategoryBadge")
        content_layout.addWidget(self._category_badge)

        # Разделитель
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setObjectName("InspectorDivider")
        content_layout.addWidget(line)

        # Combo «Процесс назначения» (только для plugin-узлов)
        self._target_process_form = QWidget()
        tp_layout = QFormLayout(self._target_process_form)
        tp_layout.setContentsMargins(0, 0, 0, 0)
        tp_layout.setSpacing(4)
        self._target_process_combo = QComboBox()
        self._target_process_combo.setObjectName("TargetProcessCombo")
        tp_layout.addRow("Процесс назначения:", self._target_process_combo)
        content_layout.addWidget(self._target_process_form)
        self._target_process_form.setVisible(False)

        # Combo «Display» (только для display-узлов)
        self._display_id_form = QWidget()
        di_layout = QFormLayout(self._display_id_form)
        di_layout.setContentsMargins(0, 0, 0, 0)
        di_layout.setSpacing(4)
        self._display_id_combo = QComboBox()
        self._display_id_combo.setObjectName("DisplayIdCombo")
        di_layout.addRow("Display:", self._display_id_combo)
        content_layout.addWidget(self._display_id_form)
        self._display_id_form.setVisible(False)

        # Разделитель между combo и параметрами
        line2 = QFrame()
        line2.setFrameShape(QFrame.Shape.HLine)
        line2.setObjectName("InspectorDivider2")
        content_layout.addWidget(line2)
        self._divider2 = line2

        # Scroll area для параметров
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._params_widget = QWidget()
        self._params_layout = QFormLayout(self._params_widget)
        self._params_layout.setContentsMargins(0, 4, 0, 4)
        self._params_layout.setSpacing(6)
        self._scroll.setWidget(self._params_widget)
        content_layout.addWidget(self._scroll, stretch=1)

        self._content.setVisible(False)
        layout.addWidget(self._content, stretch=1)

        # Подключить обработчики изменений combo
        self._target_process_combo.currentIndexChanged.connect(self._on_target_process_combo_changed)
        self._display_id_combo.currentIndexChanged.connect(self._on_display_id_combo_changed)

    # ------------------------------------------------------------------ #
    #  Публичный API: show_plugin_node                                     #
    # ------------------------------------------------------------------ #

    def show_plugin_node(
        self,
        node_id: str,
        category: str = "utility",
        target_process: str = "",
        plugins: list[dict[str, Any]] | None = None,
        params: dict[str, Any] | None = None,
    ) -> None:
        """Показать inspector для plugin-узла (process node).

        Отображает combo «Процесс назначения» (заполняется из активного рецепта)
        и параметры плагина через CardsFieldFactory или QLineEdit (fallback).

        Args:
            node_id: идентификатор узла.
            category: категория плагина.
            target_process: текущее значение целевого процесса.
            plugins: список плагинов [{plugin_name, ...}].
            params: dict параметров {field_name: value}.
        """
        self._suppress_changes = True
        try:
            self._mode = "plugin"
            self._current_node_id = node_id
            self._current_process = node_id
            self._placeholder.setVisible(False)
            self._content.setVisible(True)

            # Заголовок
            self._title.setText(node_id)

            # Badge
            color = CATEGORY_COLORS.get(category, "#9e9e9e")
            self._category_badge.setText(category)
            self._category_badge.setStyleSheet(f"background-color: {color}; color: #fff;")

            # Скрыть display-combo, показать target_process-combo
            self._display_id_form.setVisible(False)
            self._target_process_form.setVisible(True)

            # Заполнить combo процессов из активного рецепта
            self._populate_target_process_combo(target_process)

            # Показать параметры плагина в scroll area
            self._clear_params()
            if plugins:
                for p in plugins:
                    pname = p.get("plugin_name", "") if isinstance(p, dict) else str(p)
                    label = QLabel(pname)
                    label.setProperty("role", "plugin-name")
                    self._params_layout.addRow(label)

            fields_used = self._try_build_cards_editors(node_id, params)
            self._use_cards = bool(fields_used)

            if not self._use_cards and params:
                self._build_lineedit_editors(params)

        finally:
            self._suppress_changes = False

    def show_display_node(
        self,
        node_id: str,
        display_id: str = "",
        display_name: str = "",
    ) -> None:
        """Показать inspector для display-узла.

        Отображает только combo «Display» заполненный из DisplayRegistry.
        Параметры не показываются (display-узел не имеет настраиваемых полей).

        Args:
            node_id: идентификатор узла.
            display_id: текущий выбранный display_id.
            display_name: имя выбранного дисплея (для отображения).
        """
        self._suppress_changes = True
        try:
            self._mode = "display"
            self._current_node_id = node_id
            self._current_process = node_id
            self._placeholder.setVisible(False)
            self._content.setVisible(True)

            # Заголовок
            title = display_name if display_name else node_id
            self._title.setText(title)

            # Badge — зелёный display
            from ..graph.constants import DISPLAY_CATEGORY_COLOR

            self._category_badge.setText("display")
            self._category_badge.setStyleSheet(f"background-color: {DISPLAY_CATEGORY_COLOR}; color: #fff;")

            # Показать display-combo, скрыть target_process-combo
            self._target_process_form.setVisible(False)
            self._display_id_form.setVisible(True)

            # Заполнить combo из DisplayRegistry
            self._populate_display_id_combo(display_id)

            # Очистить параметры (у display нет параметров)
            self._clear_params()

        finally:
            self._suppress_changes = False

    def show_node(
        self,
        process_name: str,
        category: str = "utility",
        plugins: list[dict[str, Any]] | None = None,
        params: dict[str, Any] | None = None,
    ) -> None:
        """Показать параметры plugin-узла (алиас для show_plugin_node).

        Обратная совместимость: делегирует в show_plugin_node без target_process.

        Args:
            process_name: имя процесса (используется как node_id).
            category: категория плагина.
            plugins: список плагинов [{plugin_name, ...}].
            params: dict параметров {field_name: value}.
        """
        self.show_plugin_node(
            node_id=process_name,
            category=category,
            target_process="",
            plugins=plugins,
            params=params,
        )

    # ------------------------------------------------------------------ #
    #  Заполнение combo                                                    #
    # ------------------------------------------------------------------ #

    def _populate_target_process_combo(self, current_value: str = "") -> None:
        """Заполнить combo «Процесс назначения» именами процессов из рецепта.

        Если RecipeManager или активный рецепт недоступны — combo пустое и disabled.

        Args:
            current_value: текущее значение, которое нужно выбрать.
        """
        combo = self._target_process_combo
        if combo is None:
            return

        combo.clear()
        process_names = self._get_process_names_from_recipe()

        if not process_names:
            combo.setEnabled(False)
            return

        combo.setEnabled(True)
        for name in process_names:
            combo.addItem(name)

        # Установить текущее значение
        if current_value:
            idx = combo.findText(current_value)
            if idx >= 0:
                combo.setCurrentIndex(idx)

    def _populate_display_id_combo(self, current_display_id: str = "") -> None:
        """Заполнить combo «Display» из DisplayRegistry.

        Если DisplayRegistry недоступен — combo пустое и disabled.

        Args:
            current_display_id: текущий выбранный display_id.
        """
        combo = self._display_id_combo
        if combo is None:
            return

        combo.clear()
        entries = self._get_display_entries()

        if not entries:
            combo.setEnabled(False)
            return

        combo.setEnabled(True)
        for entry in entries:
            label = f"{entry.name} ({entry.id})" if entry.name else entry.id
            combo.addItem(label, userData=entry.id)

        # Установить текущее значение
        if current_display_id:
            for i in range(combo.count()):
                if combo.itemData(i) == current_display_id:
                    combo.setCurrentIndex(i)
                    break

    def refresh_display_combo(self) -> None:
        """Обновить combo «Display» при изменении DisplayRegistry.

        Вызывается при подписке на state.displays.changed.
        Работает только в режиме display (иначе no-op).
        """
        if self._mode != "display":
            return
        # Получить текущий выбранный display_id
        current_id = ""
        if self._display_id_combo is not None:
            idx = self._display_id_combo.currentIndex()
            if idx >= 0:
                current_id = self._display_id_combo.itemData(idx) or ""

        self._suppress_changes = True
        try:
            self._populate_display_id_combo(current_id)
        finally:
            self._suppress_changes = False

    # ------------------------------------------------------------------ #
    #  Вспомогательные методы: получение данных из контекста               #
    # ------------------------------------------------------------------ #

    def _get_process_names_from_recipe(self) -> list[str]:
        """Получить имена процессов из активного рецепта.

        TODO Phase F: RecipeStore Protocol работает с Recipe entities.
        Здесь нужен raw dict доступ — используем legacy bridge через adapter.

        Returns:
            Список имён процессов или пустой список если недоступно.
        """
        if self._services is None:
            return []

        # Получаем legacy recipe_manager через adapter bridge
        rm = getattr(self._services.recipes, "_rm", None)
        if rm is None:
            return []

        try:
            active_slug = rm.get_active()
            if not active_slug:
                return []

            recipe_dict = rm.read_recipe(active_slug)
            if not isinstance(recipe_dict, dict):
                return []

            blueprint = recipe_dict.get("blueprint", {})
            if not isinstance(blueprint, dict):
                return []

            processes = blueprint.get("processes", [])
            names = []
            for proc in processes:
                if isinstance(proc, dict):
                    name = proc.get("process_name", "")
                else:
                    name = getattr(proc, "process_name", "")
                if name:
                    names.append(name)
            return names

        except Exception:
            logger.debug("Не удалось получить список процессов из рецепта", exc_info=True)
            return []

    def _get_display_entries(self) -> list[Any]:
        """Получить список DisplaySpec из DisplayCatalog (services.displays).

        Returns:
            Список DisplaySpec-like объектов или пустой список если недоступно.
        """
        if self._services is None:
            return []

        try:
            specs = self._services.displays.list_displays()
            # DisplaySpec имеет display_id и display_name. Combo использует .id и .name.
            # Создаём thin wrapper для backward compatibility с combo код.
            result = []
            for spec in specs:
                wrapper = type("_DisplayEntry", (), {"id": spec.display_id, "name": spec.display_name})()
                result.append(wrapper)
            return result
        except Exception:
            logger.debug("Не удалось получить список дисплеев из реестра", exc_info=True)
            return []

    # ------------------------------------------------------------------ #
    #  Обработчики сигналов combo                                          #
    # ------------------------------------------------------------------ #

    def _on_target_process_combo_changed(self, index: int) -> None:
        """Обработчик выбора процесса в combo «Процесс назначения»."""
        if self._suppress_changes:
            return
        if self._target_process_combo is None:
            return
        new_process = self._target_process_combo.currentText()
        if new_process and self._current_node_id:
            self.target_process_changed.emit(self._current_node_id, new_process)

    def _on_display_id_combo_changed(self, index: int) -> None:
        """Обработчик выбора display в combo «Display»."""
        if self._suppress_changes:
            return
        if self._display_id_combo is None:
            return
        new_display_id = self._display_id_combo.itemData(index) or ""
        if new_display_id and self._current_node_id:
            self.display_id_changed.emit(self._current_node_id, new_display_id)

    # ------------------------------------------------------------------ #
    #  Оригинальные методы (backward compatibility)                        #
    # ------------------------------------------------------------------ #

    def _try_build_cards_editors(
        self,
        process_name: str,
        params: dict[str, Any] | None,
    ) -> bool:
        """Попытаться создать типизированные виджеты через CardsFieldFactory.

        Returns:
            True если виджеты успешно созданы, False — нужен fallback.
        """
        if self._services is None:
            return False

        # TODO Phase F: RegistersBackend Protocol имеет другую сигнатуру
        # (get_field_specs(process_name, plugin_index) вместо get_fields(process_name)).
        # Используем legacy RegistersManager через adapter bridge.
        rm = getattr(self._services.registers, "_rm", None)
        if rm is None:
            return False

        # Получить FieldInfo из RegistersManager по имени процесса
        fields = rm.get_fields(process_name)
        if not fields:
            return False

        from multiprocess_prototype.frontend.forms.factory import CardsFieldFactory

        # TODO Phase F: form_context() не покрыт AppServices Protocol.
        # Для binding-aware editors нужен form_ctx. Пока — None (legacy путь).
        form_ctx = None

        for field_info in fields:
            editor = CardsFieldFactory.create(
                field_info,
                parent=self._params_widget,
                form_ctx=form_ctx,
            )

            # Установить значение из params если передан
            if params and field_info.field_name in params:
                try:
                    editor.setter(params[field_info.field_name])
                except Exception:
                    logger.debug(
                        "Не удалось установить значение '%s' для поля '%s'",
                        params[field_info.field_name],
                        field_info.field_name,
                    )

            # Подключить сигнал изменения если есть
            if editor.change_signal is not None:
                fn = field_info.field_name
                editor.change_signal.connect(lambda *_args, _fn=fn, _ed=editor: self._on_field_editor_changed(_fn, _ed))

            self._field_editors[field_info.field_name] = editor
            self._params_layout.addRow(editor.label, editor.widget)

        return True

    def _build_lineedit_editors(self, params: dict[str, Any]) -> None:
        """Создать QLineEdit-редакторы (fallback если CardsFieldFactory недоступен)."""
        for field_name, value in params.items():
            editor = QLineEdit(str(value))
            editor.setProperty("field_name", field_name)
            editor.editingFinished.connect(lambda fn=field_name, ed=editor: self._on_field_edited(fn, ed))
            self._field_editors[field_name] = editor
            self._params_layout.addRow(field_name, editor)

    def clear(self) -> None:
        """Очистить inspector (показать placeholder)."""
        self._current_process = ""
        self._current_node_id = ""
        self._placeholder.setVisible(True)
        self._content.setVisible(False)
        self._target_process_form.setVisible(False)
        self._display_id_form.setVisible(False)
        self._clear_params()

    def update_field(self, field_name: str, value: Any) -> None:
        """Обновить значение поля programmatically (undo/redo).

        Использует signal suppression чтобы не тригерить field_changed.
        Работает для обоих типов редакторов: FieldEditor и QLineEdit.
        """
        self._suppress_changes = True
        try:
            editor = self._field_editors.get(field_name)
            if editor is None:
                return

            if isinstance(editor, QLineEdit):
                # Fallback-режим: QLineEdit
                editor.setText(str(value))
            else:
                # Cards-режим: FieldEditor с setter
                try:
                    editor.setter(value)
                except Exception:
                    logger.warning(
                        "update_field: не удалось установить значение '%s' для поля '%s'",
                        value,
                        field_name,
                    )
        finally:
            self._suppress_changes = False

    @property
    def current_process(self) -> str:
        """Имя текущего отображаемого процесса."""
        return self._current_process

    def _on_field_edited(self, field_name: str, editor: QLineEdit) -> None:
        """Обработчик изменения поля пользователем (QLineEdit fallback)."""
        if self._suppress_changes:
            return
        value = editor.text()
        self.field_changed.emit(self._current_process, field_name, value)

    def _on_field_editor_changed(self, field_name: str, editor: "FieldEditor") -> None:
        """Обработчик изменения поля через FieldEditor (cards-режим).

        Args:
            field_name: имя поля.
            editor: FieldEditor, у которого сработал change_signal.
        """
        if self._suppress_changes:
            return
        value = editor.getter()
        self.field_changed.emit(self._current_process, field_name, value)

    def _clear_params(self) -> None:
        """Удалить все виджеты параметров.

        Для FieldEditor: отключаем change_signal перед удалением
        чтобы избежать утечек сигналов при переключении нод.
        """
        for field_name, editor in self._field_editors.items():
            if not isinstance(editor, QLineEdit):
                # FieldEditor — отключаем change_signal
                try:
                    if editor.change_signal is not None:
                        editor.change_signal.disconnect()
                except (RuntimeError, TypeError):
                    pass  # Уже отключён или C++ объект удалён

        self._field_editors.clear()
        self._use_cards = False

        while self._params_layout.count():
            item = self._params_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
