"""SettingsTab — таб Settings с боковой навигацией.

Загружает config/system.yaml, авто-генерирует форму через RegisterView
(фабрика форм из T2), показывает группы Cards/Table, валидирует и
сохраняет обратно в YAML. Выбор Cards/Table запоминается в UiPrefsStore.

Боковая навигация (SideNavLayout) с 5 секциями:
- Администрация (заглушка)
- Настройки системы (RegisterView + кнопки сохранения)
- Настройка интерфейса (заглушка)
- Оформление (заглушка)
- История (заглушка)

Layout:
    QVBoxLayout
      +-- QHBoxLayout (header)
      |     +-- QLabel "Настройки"
      |     +-- stretch
      +-- SideNavLayout (stretch=1)
            nav (200px):              stack:
            ┌──────────────┐          ┌──────────────────────────┐
            │Администрация │          │ placeholder / content    │
            │Наст. системы │←default  │                          │
            │Наст. интерф. │          │                          │
            │Оформление    │          │                          │
            │История       │          │                          │
            └──────────────┘          └──────────────────────────┘
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pydantic
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from multiprocess_prototype.frontend.forms import RegisterView, ViewMode
from multiprocess_prototype.frontend.forms.field_editor import FieldEditor
from multiprocess_prototype.frontend.forms.view_mode_toggle import ViewModeToggle
from multiprocess_prototype.frontend.prefs.store import UiPrefsStore
from multiprocess_prototype.frontend.widgets.primitives import SideNavLayout

from .yaml_io import SETTINGS_PATH, load_settings, save_settings, schema_to_field_infos

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.app_context import AppContext


# Русские названия секций для group-box (RegisterView)
_SECTION_TITLES: dict[str, str] = {
    "system": "Система",
    "camera": "Камера",
    "processing": "Обработка",
    "display": "Дисплей",
    "storage": "Хранение",
}

# Секции боковой навигации (key, title)
_NAV_SECTIONS: list[tuple[str, str]] = [
    ("administration", "Администрация"),
    ("system_settings", "Настройки системы"),
    ("interface_settings", "Настройка интерфейса"),
    ("appearance", "Оформление"),
    ("history", "История"),
]
_DEFAULT_SECTION = "system_settings"


class SettingsTab(QWidget):
    """Пилотный таб Settings v2 — загрузка/редактирование/сохранение system.yaml.

    Использует RegisterView для авто-генерации формы по Pydantic-схеме SystemConfig.
    Два режима отображения: Cards / Table, выбор запоминается в UiPrefsStore.

    Сигналы:
        settings_saved(dict): эмитится при успешном сохранении (передаёт dict_form)
    """

    settings_saved = Signal(dict)

    def __init__(self, ctx: "AppContext", parent: QWidget | None = None) -> None:
        super().__init__(parent)

        # ----------------------------------------------------------------
        # Шаг 1: Загрузить конфиг и предпочтения
        # ----------------------------------------------------------------
        self._cfg = load_settings()
        self._prefs = UiPrefsStore()
        self._dirty = False

        # ----------------------------------------------------------------
        # Шаг 2-3: Получить field_infos и начальный режим
        # ----------------------------------------------------------------
        field_infos = schema_to_field_infos(self._cfg)

        try:
            initial_mode = ViewMode(self._prefs.get("settings.view_mode", "cards"))
        except ValueError:
            # Мусор в YAML — откатываемся к Cards
            initial_mode = ViewMode.CARDS

        # ----------------------------------------------------------------
        # Шаг 4: Создать RegisterView (со встроенным ViewModeToggle — Вариант A)
        # ----------------------------------------------------------------
        self._view = RegisterView(
            field_infos,
            initial_mode=initial_mode,
            category_titles=_SECTION_TITLES,
        )

        # ----------------------------------------------------------------
        # Шаг 5: Установить начальные значения из cfg через setter'ы
        # ----------------------------------------------------------------
        self._init_editor_values(field_infos)

        # ----------------------------------------------------------------
        # Шаг 6: Подключить сигналы изменения полей
        # ----------------------------------------------------------------
        for key, editor in self._view.editors().items():
            editor.change_signal.connect(self._on_field_changed)

        # ----------------------------------------------------------------
        # Шаг 6b: Подключить field_changed → ActionBus (Phase 11)
        # ----------------------------------------------------------------
        self._ctx = ctx
        self._view.field_changed.connect(self._on_field_changed_action_bus)

        # ----------------------------------------------------------------
        # Шаг 7: Подключить mode_changed → сохранение в prefs
        # ----------------------------------------------------------------
        self._view.mode_changed.connect(
            lambda mode_str: self._prefs.set("settings.view_mode", mode_str)
        )

        # ----------------------------------------------------------------
        # Шаг 8: Построить layout
        # ----------------------------------------------------------------
        self._setup_ui()

    # ------------------------------------------------------------------
    # Фабричный метод
    # ------------------------------------------------------------------

    @classmethod
    def create(cls, ctx: "AppContext") -> "SettingsTab":
        """Фабричный метод для TabFactory.custom_factories."""
        return cls(ctx)

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def reload(self) -> None:
        """Перечитать system.yaml и сбросить все изменения.

        Возвращает все поля к on-disk значениям.
        Сбрасывает dirty-флаг и убирает индикатор и красные рамки.
        """
        self._cfg = load_settings()
        field_infos = schema_to_field_infos(self._cfg)
        self._sync_editors_to_cfg(field_infos)
        self._clear_validation_errors()
        self._set_dirty(False)

    def save(self) -> bool:
        """Собрать значения из виджетов, валидировать и сохранить в YAML.

        Returns:
            True — сохранено успешно.
            False — ошибка валидации (Pydantic), YAML не меняется.
        """
        # Собрать dict_form: {section: {field: value}}
        dict_form: dict[str, Any] = {}
        for key, editor in self._view.editors().items():
            parts = key.split(".", 1)
            if len(parts) != 2:
                continue
            section, field_name = parts
            if section not in dict_form:
                dict_form[section] = {}
            dict_form[section][field_name] = editor.getter()

        # Валидация через Pydantic
        try:
            from multiprocess_prototype.config.schemas import SystemConfig
            validated = SystemConfig.model_validate(dict_form)
        except pydantic.ValidationError as exc:
            self._show_validation_errors(exc)
            return False

        # Сохранить
        self._clear_validation_errors()
        save_settings(validated)
        self._cfg = validated
        self.settings_saved.emit(dict_form)
        self._set_dirty(False)
        return True

    def is_dirty(self) -> bool:
        """True если есть несохранённые изменения."""
        return self._dirty

    def field_editors(self) -> dict[str, FieldEditor]:
        """Словарь editors (ключи вида 'section.field')."""
        return self._view.editors()

    def view_mode(self) -> ViewMode:
        """Текущий режим отображения (Cards/Table)."""
        return self._view.mode()

    # ------------------------------------------------------------------
    # Внутренние
    # ------------------------------------------------------------------

    def _init_editor_values(self, field_infos: list) -> None:
        """Установить начальные значения в editors из _cfg."""
        self._sync_editors_to_cfg(field_infos)

    def _sync_editors_to_cfg(self, field_infos: list) -> None:
        """Протолкнуть значения из _cfg в editors через setter."""
        editors = self._view.editors()
        for fi in field_infos:
            section_name = fi.plugin_name   # plugin_name = section_name (см. yaml_io)
            field_name = fi.field_name
            key = f"{section_name}.{field_name}"

            section_obj = getattr(self._cfg, section_name, None)
            if section_obj is None:
                continue

            value = getattr(section_obj, field_name, None)
            if value is None:
                continue

            editor = editors.get(key)
            if editor is None:
                continue

            try:
                editor.setter(value)
            except Exception:
                # Setter не смог принять значение — пропускаем
                pass

    def _on_field_changed(self) -> None:
        """Обработчик: поле изменилось → помечаем dirty."""
        self._set_dirty(True)

    def _on_field_changed_action_bus(
        self, register_name: str, field_name: str, old_value: object, new_value: object,
    ) -> None:
        """Изменение параметра настроек → ActionBus.record(field_set).

        Используем record() (не execute()): секции system/camera/display — это
        конфиг system.yaml, а не plugin-регистры. handler.apply() не нужен,
        виджет уже содержит новое значение.
        """
        bus = self._ctx.action_bus()
        if bus is None:
            return
        from multiprocess_prototype.frontend.actions.builder import V2ActionBuilder
        action = V2ActionBuilder.field_set_timed(
            register_name, field_name, new_value, old_value,
            description=f"{register_name}.{field_name} = {new_value}",
        )
        bus.record(action)

    def _set_dirty(self, dirty: bool) -> None:
        """Установить dirty-флаг и обновить индикатор."""
        self._dirty = dirty
        self._dirty_label.setVisible(dirty)

    def _show_validation_errors(self, exc: pydantic.ValidationError) -> None:
        """Показать inline-ошибки под невалидными полями (красная рамка)."""
        editors = self._view.editors()
        for error in exc.errors():
            loc = error.get("loc", ())
            if len(loc) >= 2:
                # loc = ('system', 'stop_timeout', ...)
                key = f"{loc[0]}.{loc[1]}"
                editor = editors.get(key)
                if editor is not None:
                    editor.widget.setStyleSheet("border: 1px solid red;")
                    editor.widget.setToolTip(f"Ошибка: {error['msg']}")

    def _clear_validation_errors(self) -> None:
        """Убрать красные рамки со всех виджетов."""
        for editor in self._view.editors().values():
            editor.widget.setStyleSheet("")
            editor.widget.setToolTip("")

    def _setup_ui(self) -> None:
        """Построить layout таба с боковой навигацией."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        # Header: заголовок "Настройки"
        header_layout = QHBoxLayout()
        title_label = QLabel("Настройки")
        font = title_label.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        title_label.setFont(font)
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        main_layout.addLayout(header_layout)

        # Боковая навигация с секциями
        self._side_nav = SideNavLayout()

        # Виджеты секций
        section_widgets: dict[str, QWidget] = {
            "administration": self._build_administration_section(),
            "system_settings": self._build_system_section(),
            "history": self._build_history_section(),
        }

        for key, title in _NAV_SECTIONS:
            widget = section_widgets.get(key) or self._build_placeholder(title)
            self._side_nav.add_section(key, title, widget)

        self._side_nav.set_current(_DEFAULT_SECTION)
        main_layout.addWidget(self._side_nav, stretch=1)

    def _build_administration_section(self) -> QWidget:
        """Секция «Администрация» — AdministrationSection или placeholder если нет ctx."""
        if self._ctx is None:
            return self._build_placeholder("Администрация")
        from .administration.section import AdministrationSection
        return AdministrationSection(self._ctx)

    def _build_system_section(self) -> QWidget:
        """Секция «Настройки системы» — RegisterView + вертикальные кнопки справа."""
        container = QWidget()
        columns = QHBoxLayout(container)
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(8)

        # Скрыть встроенный toggle внутри RegisterView
        self._view._toggle.hide()

        # Левая часть: RegisterView + индикатор dirty
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        left_layout.addWidget(self._view, stretch=1)

        # Индикатор несохранённых изменений
        self._dirty_label = QLabel("Изменения не сохранены")
        self._dirty_label.setStyleSheet("color: orange; font-weight: bold;")
        self._dirty_label.setVisible(False)
        left_layout.addWidget(self._dirty_label)

        columns.addWidget(left, stretch=1)

        # Правая часть: тумблер Cards/Table + вертикальные кнопки
        btn_layout = QVBoxLayout()
        btn_layout.setSpacing(8)

        # Тумблер Cards/Table (первый элемент)
        self._external_toggle = ViewModeToggle(initial_mode=self._view.mode())
        self._external_toggle.mode_changed.connect(
            lambda mode_str: self._view.set_mode(ViewMode(mode_str))
        )
        btn_layout.addWidget(self._external_toggle)

        reset_btn = QPushButton("Сбросить")
        reset_btn.setFixedWidth(100)
        reset_btn.setToolTip("Сбросить изменения и загрузить данные с диска")
        reset_btn.clicked.connect(self.reload)
        btn_layout.addWidget(reset_btn)

        save_btn = QPushButton("Сохранить")
        save_btn.setFixedWidth(100)
        save_btn.setToolTip("Сохранить изменения в config/system.yaml")
        save_btn.clicked.connect(self.save)
        btn_layout.addWidget(save_btn)

        btn_layout.addStretch()
        columns.addLayout(btn_layout)

        return container

    # ------------------------------------------------------------------
    # Секция «История» — таблица действий + кнопки Undo/Redo/Сбросить
    # ------------------------------------------------------------------

    def _build_history_section(self) -> QWidget:
        """Секция «История» — таблица действий ActionBus + управление."""
        container = QWidget()
        columns = QHBoxLayout(container)
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(8)

        # Левая часть: таблица действий
        _HISTORY_COLUMNS = ["Время", "Вкладка", "Параметр", "Значение"]
        self._history_table = QTableWidget(0, len(_HISTORY_COLUMNS))
        self._history_table.setHorizontalHeaderLabels(_HISTORY_COLUMNS)
        self._history_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows,
        )
        self._history_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers,
        )
        self._history_table.verticalHeader().setVisible(False)

        h = self._history_table.horizontalHeader()
        if h:
            h.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
            h.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
            h.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

        columns.addWidget(self._history_table, stretch=1)

        # Правая часть: кнопки управления
        btn_layout = QVBoxLayout()
        btn_layout.setSpacing(8)

        self._btn_undo = QPushButton("← Назад")
        self._btn_undo.setFixedWidth(100)
        self._btn_undo.setToolTip("Отменить последнее действие (Ctrl+Z)")
        self._btn_undo.setEnabled(False)
        self._btn_undo.clicked.connect(self._on_history_undo)
        btn_layout.addWidget(self._btn_undo)

        self._btn_redo = QPushButton("Вперёд →")
        self._btn_redo.setFixedWidth(100)
        self._btn_redo.setToolTip("Повторить отменённое действие (Ctrl+Y)")
        self._btn_redo.setEnabled(False)
        self._btn_redo.clicked.connect(self._on_history_redo)
        btn_layout.addWidget(self._btn_redo)

        self._btn_clear_history = QPushButton("Сбросить")
        self._btn_clear_history.setFixedWidth(100)
        self._btn_clear_history.setToolTip("Очистить всю историю действий")
        self._btn_clear_history.setEnabled(False)
        self._btn_clear_history.clicked.connect(self._on_history_clear)
        btn_layout.addWidget(self._btn_clear_history)

        btn_layout.addStretch()
        columns.addLayout(btn_layout)

        # Подписаться на изменения ActionBus
        bus = self._ctx.action_bus()
        if bus is not None:
            bus.add_change_callback(self._refresh_history)
            bus.add_change_callback(self._on_bus_undo_redo_sync)

        return container

    def _refresh_history(self) -> None:
        """Обновить таблицу истории из ActionBus."""
        bus = self._ctx.action_bus()
        if bus is None:
            return

        actions = bus.history(n=50)

        self._history_table.setRowCount(len(actions))
        for row, action in enumerate(actions):
            # Время
            ts = datetime.fromtimestamp(action.timestamp).strftime("%H:%M:%S")
            self._history_table.setItem(row, 0, QTableWidgetItem(ts))

            # Вкладка (register_name = plugin_name / section)
            tab_name = action.register_name or action.action_type
            self._history_table.setItem(row, 1, QTableWidgetItem(tab_name))

            # Параметр
            param = action.field_name or action.description
            self._history_table.setItem(row, 2, QTableWidgetItem(param))

            # Значение
            value = action.forward_patch.get("value", "")
            if action.action_type == "recipe_apply":
                value = action.forward_patch.get("recipe_name", "recipe")
            self._history_table.setItem(row, 3, QTableWidgetItem(str(value)))

        # Прокрутить к последней строке
        if actions:
            self._history_table.scrollToBottom()

        # Обновить состояние кнопок
        self._btn_undo.setEnabled(bus.can_undo())
        self._btn_redo.setEnabled(bus.can_redo())
        self._btn_clear_history.setEnabled(bus.can_undo() or bus.can_redo())

    def _on_history_undo(self) -> None:
        """Кнопка «Назад» — отменить последнее действие."""
        bus = self._ctx.action_bus()
        if bus is not None:
            bus.undo()

    def _on_history_redo(self) -> None:
        """Кнопка «Вперёд» — повторить отменённое действие."""
        bus = self._ctx.action_bus()
        if bus is not None:
            bus.redo()

    def _on_history_clear(self) -> None:
        """Кнопка «Сбросить» — очистить всю историю."""
        bus = self._ctx.action_bus()
        if bus is not None:
            bus.clear()

    def _on_bus_undo_redo_sync(self) -> None:
        """Синхронизация виджетов при undo/redo (callback от ActionBus)."""
        bus = self._ctx.action_bus()
        if bus is None:
            return
        event = bus.last_event
        if event is None:
            return
        event_type, action = event
        if event_type not in ("undo", "redo"):
            return
        if action.action_type != "field_set":
            return
        register_name = action.register_name or ""
        value = (
            action.backward_patch.get("value")
            if event_type == "undo"
            else action.forward_patch.get("value")
        )
        key = f"{register_name}.{action.field_name}"
        if key in self._view.editors():
            self._view.set_editor_value(key, value)

    @staticmethod
    def _build_placeholder(title: str) -> QWidget:
        """Заглушка для секции, которая ещё не реализована."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        label = QLabel(f"Раздел «{title}» в разработке")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("color: gray; font-size: 14px;")
        layout.addWidget(label)
        return widget
