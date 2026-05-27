# -*- coding: utf-8 -*-
"""SystemSection — секция «Настройки системы» для Settings таба.

Реализует:
- SectionProtocol   — интерфейс секции (key, title, widget, action_buttons, on_activated)
- SystemSettingsView — интерфейс вью для SystemSettingsPresenter

Структура UI:
    QWidget (container)
      └── QVBoxLayout
            └── RegisterView (cards / table с переключателем режима)

Кнопки «Режим», «Сбросить» и «Сохранить» возвращаются через action_buttons()
и регистрируются в action-колонке SettingsTab.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from multiprocess_prototype.frontend.forms import RegisterView, ViewMode
from multiprocess_prototype.frontend.forms.view_mode_toggle import ViewModeToggle
from multiprocess_prototype.frontend.prefs.store import UiPrefsStore

from ..yaml_io import schema_to_field_infos, load_settings

if TYPE_CHECKING:
    from .presenter import SystemSettingsPresenter
    from multiprocess_prototype.domain.app_services import AppServices

# Русские названия секций для group-box (RegisterView)
_SECTION_TITLES: dict[str, str] = {
    "system": "Система",
    "camera": "Камера",
    "processing": "Обработка",
    "display": "Дисплей",
    "storage": "Хранение",
}


class SystemSection(QWidget):
    """Секция «Настройки системы» — RegisterView + кнопки + presenter.

    Реализует SectionProtocol и SystemSettingsView — presenter вызывает view-методы
    напрямую на объекте секции.

    Сигналы (SectionWithEvents):
        section_dirty_changed(bool): эмитится при смене dirty-флага.
        section_data_saved(dict):    эмитится при успешном сохранении.
    """

    section_dirty_changed = Signal(bool)
    section_data_saved = Signal(dict)

    def __init__(
        self,
        services: "AppServices | None" = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._services = services

        # Предпочтения (режим отображения)
        self._prefs = UiPrefsStore()

        # Загрузить конфиг и field_infos
        cfg = load_settings()
        field_infos = schema_to_field_infos(cfg)

        # Определить начальный режим из prefs
        try:
            initial_mode = ViewMode(self._prefs.get("settings.view_mode", "cards"))
        except ValueError:
            initial_mode = ViewMode.CARDS

        # RegisterView — основной виджет редактирования полей.
        # form_ctx=None: SettingsSystem не использует plugin binding.
        # Поля GUI-локальные (тема, i18n, режим отображения).
        # Legacy путь: editor.change_signal → presenter.on_field_changed (dirty),
        #              RegisterView.field_changed → presenter.on_field_changed_action_bus (undo/redo).
        # scrollable=False: SystemSection живёт внутри DiffScrollTabLayout —
        # внешний мастер-скроллбар сам крутит содержимое, а внутренний
        # QScrollArea ломал бы sizeHint секции и блокировал диф-скролл.
        self._register_view = RegisterView(
            field_infos,
            initial_mode=initial_mode,
            category_titles=_SECTION_TITLES,
            form_ctx=None,
            scrollable=False,
            show_toggle=False,
        )

        # Сохранять режим в prefs при смене
        self._register_view.mode_changed.connect(lambda mode_str: self._prefs.set("settings.view_mode", mode_str))

        # Presenter инжектируется позже через set_presenter() — до этого момента None.
        # Это позволяет тестам подсунуть mock-presenter через SectionSpec.presenter_factory.
        self._presenter: "SystemSettingsPresenter | None" = None

        # Построить UI (кнопки используют слоты-врапперы, не _presenter напрямую)
        self._build_ui()

    # ------------------------------------------------------------------
    # SectionProtocol
    # ------------------------------------------------------------------

    @property
    def key(self) -> str:
        """Уникальный идентификатор секции."""
        return "system_settings"

    @property
    def title(self) -> str:
        """Отображаемое название секции."""
        return "Настройки системы"

    def widget(self) -> QWidget:
        """Корневой QWidget секции."""
        return self

    def action_buttons(self) -> list[QWidget]:
        """Кнопки для action-колонки: тумблер режима, Сбросить, Сохранить."""
        return [self._external_toggle, self._btn_reset, self._btn_save]

    def on_activated(self) -> None:
        """Ничего не делаем при переключении на секцию."""

    def on_deactivated(self) -> None:
        """Ничего не делаем при уходе с секции."""

    def bus_change_callback(self) -> "Callable[[], None] | None":
        """Вернуть колбэк для подписки на изменения ActionBus (SectionWithEvents)."""
        return self._presenter.on_bus_undo_redo_sync if self._presenter is not None else None

    # ------------------------------------------------------------------
    # SystemSettingsView Protocol
    # ------------------------------------------------------------------

    def set_editor_value(self, key: str, value: object) -> None:
        """Установить значение редактора по ключу 'section.field'."""
        self._register_view.set_editor_value(key, value)

    def get_editor_values(self) -> dict[str, object]:
        """Получить текущие значения всех редакторов {key: value}."""
        return {key: editor.getter() for key, editor in self._register_view.editors().items()}

    def set_dirty_indicator(self, dirty: bool) -> None:
        """Обновить индикатор несохранённых изменений (кнопка Сохранить)."""
        # Кнопка Сохранить визуально сигнализирует о dirty-состоянии
        self._btn_save.setEnabled(dirty)
        self._btn_reset.setEnabled(dirty)

    def show_validation_error(self, key: str, message: str) -> None:
        """Подсветить редактор с ошибкой и установить tooltip."""
        editors = self._register_view.editors()
        editor = editors.get(key)
        if editor is not None:
            editor.widget.setProperty("hasError", True)
            editor.widget.style().unpolish(editor.widget)
            editor.widget.style().polish(editor.widget)
            editor.widget.setToolTip(f"Ошибка: {message}")

    def clear_validation_errors(self) -> None:
        """Снять все подсветки ошибок с редакторов."""
        for editor in self._register_view.editors().values():
            editor.widget.setProperty("hasError", False)
            editor.widget.style().unpolish(editor.widget)
            editor.widget.style().polish(editor.widget)
            editor.widget.setToolTip("")

    def set_save_enabled(self, enabled: bool) -> None:
        """Установить доступность кнопки «Сохранить»."""
        self._btn_save.setEnabled(enabled)

    def set_reset_enabled(self, enabled: bool) -> None:
        """Установить доступность кнопки «Сбросить»."""
        self._btn_reset.setEnabled(enabled)

    # ------------------------------------------------------------------
    # Публичные аксессоры для SettingsTab
    # ------------------------------------------------------------------

    @property
    def presenter(self) -> "SystemSettingsPresenter | None":
        """Вернуть presenter секции (для подписки на ActionBus)."""
        return self._presenter

    def set_presenter(self, presenter: "SystemSettingsPresenter") -> None:
        """Инжектировать presenter в секцию.

        Порядок операций намеренен:
          1. Сохранить presenter.
          2. Подключить callback'и (on_dirty_changed, on_settings_saved).
          3. sync_editors_to_cfg() — ДО подключения editor.change_signal,
             иначе change_signal эмитится во время sync → on_field_changed() →
             dirty=True при старте приложения (баг).
          4. Подключить editor.change_signal и register_view.field_changed.

        ВАЖНО: вызывается из BaseTreeNavTab._apply_presenter_factory ПЕРЕД
        _connect_section_events — так bus_change_callback() уже возвращает
        валидный callable.
        """
        self._presenter = presenter

        # Шаг 2: подключить callback'и presenter'а к Qt-сигналам секции (SectionWithEvents)
        self._presenter.on_dirty_changed = lambda dirty: self.section_dirty_changed.emit(dirty)
        self._presenter.on_settings_saved = lambda data: self.section_data_saved.emit(data)

        # Шаг 3: синхронизировать редакторы с конфигом ДО подключения change_signal.
        # Сигналы редакторов ещё не подключены → on_field_changed не вызывается →
        # dirty остаётся False.
        self._presenter.sync_editors_to_cfg()

        # Шаг 4: подключить сигналы редакторов к presenter'у.
        # АУДИТ (Track 3.5): две подписки намеренны — они обслуживают РАЗНЫЕ цели:
        #   1. editor.change_signal → on_field_changed: только dirty-флаг (кнопки Сохранить/Сбросить).
        #      Сигнатура: () — без аргументов.
        #   2. RegisterView.field_changed → on_field_changed_action_bus: запись в ActionBus (undo/redo).
        #      Сигнатура: (register_name, field_name, old_value, new_value).
        # Удаление любой из подписок нарушит UX (исчезнет dirty-флаг) или undo/redo.
        for editor in self._register_view.editors().values():
            editor.change_signal.connect(self._presenter.on_field_changed)
        self._register_view.field_changed.connect(self._presenter.on_field_changed_action_bus)

    def field_editors(self) -> dict:
        """Вернуть словарь редакторов (делегация от SettingsTab)."""
        return self._register_view.editors()

    def view_mode(self) -> ViewMode:
        """Вернуть текущий режим отображения."""
        return self._register_view.mode()

    @property
    def register_view(self) -> RegisterView:
        """Публичный доступ к RegisterView (для тестов и tab._view)."""
        return self._register_view

    # ------------------------------------------------------------------
    # Построение UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        """Создать RegisterView и разместить в layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._register_view)

        # Внешний тумблер режима (встроенный в RegisterView скрыт)
        self._external_toggle = ViewModeToggle(initial_mode=self._register_view.mode())
        self._external_toggle.mode_changed.connect(lambda mode_str: self._register_view.set_mode(ViewMode(mode_str)))

        # Кнопка «Сбросить»
        self._btn_reset = QPushButton("Сбросить")
        self._btn_reset.setToolTip("Сбросить изменения и загрузить данные с диска")
        self._btn_reset.setEnabled(False)
        # Используем слот-враппер: в момент _build_ui presenter ещё None
        self._btn_reset.clicked.connect(self._on_reset_clicked)

        # Кнопка «Сохранить»
        self._btn_save = QPushButton("Сохранить")
        self._btn_save.setToolTip("Сохранить изменения в config/system.yaml")
        self._btn_save.setEnabled(False)
        self._btn_save.clicked.connect(self._on_save_clicked)

    # ------------------------------------------------------------------
    # Слоты кнопок
    # ------------------------------------------------------------------

    def _on_reset_clicked(self) -> None:
        """Делегировать сброс presenter'у (guard на случай None)."""
        if self._presenter is not None:
            self._presenter.reload()

    def _on_save_clicked(self) -> None:
        """Делегировать сохранение presenter'у (guard на случай None)."""
        if self._presenter is not None:
            self._presenter.save()
