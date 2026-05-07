"""SettingsTab — пилотный таб Settings end-to-end.

Загружает config/system.yaml, авто-генерирует форму через RegisterView
(фабрика форм из T2), показывает группы Cards/Table, валидирует и
сохраняет обратно в YAML. Выбор Cards/Table запоминается в UiPrefsStore.

Layout:
    QVBoxLayout
      +-- QHBoxLayout (header)
      |     +-- QLabel "Настройки"
      |     +-- stretch
      +-- RegisterView(fields)          ← stretch=1, внутри уже есть toggle
      +-- QFrame (button row)
            +-- QLabel "Изменения не сохранены" (visible only when dirty)
            +-- stretch
            +-- QPushButton "Сбросить"   → reload()
            +-- QPushButton "Сохранить"  → save()

Встроенный ViewModeToggle RegisterView (Вариант A):
    RegisterView уже содержит ViewModeToggle в своём header.
    SettingsTab подключается к register_view.mode_changed для сохранения
    режима в UiPrefsStore. Дублирования UI нет.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pydantic
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from multiprocess_prototype_2.frontend.forms import RegisterView, ViewMode
from multiprocess_prototype_2.frontend.forms.field_editor import FieldEditor
from multiprocess_prototype_2.frontend.prefs.store import UiPrefsStore

from .yaml_io import SETTINGS_PATH, load_settings, save_settings, schema_to_field_infos

if TYPE_CHECKING:
    from multiprocess_prototype_2.frontend.app_context import AppContext


# Русские названия секций для group-box
_SECTION_TITLES: dict[str, str] = {
    "system": "Система",
    "camera": "Камера",
    "processing": "Обработка",
    "display": "Дисплей",
    "storage": "Хранение",
}


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
            from multiprocess_prototype_2.config.schemas import SystemConfig
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
        """Построить layout таба."""
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

        # RegisterView (содержит встроенный ViewModeToggle сверху)
        main_layout.addWidget(self._view, stretch=1)

        # Button row
        button_frame = QFrame()
        button_frame.setFrameShape(QFrame.Shape.StyledPanel)
        button_layout = QHBoxLayout(button_frame)
        button_layout.setContentsMargins(8, 4, 8, 4)

        # Индикатор несохранённых изменений
        self._dirty_label = QLabel("Изменения не сохранены")
        self._dirty_label.setStyleSheet("color: orange; font-weight: bold;")
        self._dirty_label.setVisible(False)
        button_layout.addWidget(self._dirty_label)

        button_layout.addStretch()

        # Кнопка "Сбросить"
        reset_btn = QPushButton("Сбросить")
        reset_btn.setToolTip("Сбросить изменения и загрузить данные с диска")
        reset_btn.clicked.connect(self.reload)
        button_layout.addWidget(reset_btn)

        # Кнопка "Сохранить"
        save_btn = QPushButton("Сохранить")
        save_btn.setToolTip("Сохранить изменения в config/system.yaml")
        save_btn.clicked.connect(self.save)
        button_layout.addWidget(save_btn)

        main_layout.addWidget(button_frame)
