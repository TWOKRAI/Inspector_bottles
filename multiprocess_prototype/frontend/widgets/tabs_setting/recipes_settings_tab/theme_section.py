# multiprocess_prototype/frontend/widgets/tabs_setting/recipes_settings_tab/theme_section.py
"""ThemeSection — секция выбора темы оформления в настройках.

ComboBox с доступными темами + кнопка «Обновить» для hot-reload.
Для модульных тем показывает список файлов-частей.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from multiprocess_prototype.frontend.managers.theme_manager import ThemeManager


class ThemeSection(QWidget):
    """Секция настроек: выбор и применение темы оформления."""

    def __init__(
        self,
        theme_manager: ThemeManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme_manager = theme_manager
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        group = QGroupBox("Тема оформления")
        group_layout = QVBoxLayout(group)

        # Строка: ComboBox + кнопки
        row = QHBoxLayout()

        self._combo = QComboBox()
        self._combo.setMinimumWidth(200)
        row.addWidget(self._combo)

        self._btn_apply = QPushButton("Применить")
        self._btn_apply.setProperty("role", "primary")
        row.addWidget(self._btn_apply)

        self._btn_reload = QPushButton("Обновить")
        self._btn_reload.setToolTip("Перечитать текущую тему с диска (после редактирования .qss)")
        row.addWidget(self._btn_reload)

        row.addStretch()
        group_layout.addLayout(row)

        # Информация о структуре темы
        self._info_label = QLabel()
        self._info_label.setObjectName("MutedLabel")
        self._info_label.setWordWrap(True)
        group_layout.addWidget(self._info_label)

        layout.addWidget(group)

        # Заполняем combo
        self._refresh_themes()
        self._update_info()

        # Сигналы
        self._btn_apply.clicked.connect(self._on_apply)
        self._btn_reload.clicked.connect(self._on_reload)
        self._combo.currentTextChanged.connect(self._update_info)

    def _refresh_themes(self) -> None:
        """Обновить список тем из папки styles/."""
        self._combo.blockSignals(True)
        self._combo.clear()
        themes = self._theme_manager.available_themes()
        self._combo.addItems(themes)
        # Выбрать текущую
        current = self._theme_manager.current_theme
        idx = self._combo.findText(current)
        if idx >= 0:
            self._combo.setCurrentIndex(idx)
        self._combo.blockSignals(False)

    def _update_info(self) -> None:
        """Показать информацию о выбранной теме."""
        name = self._combo.currentText()
        if not name:
            self._info_label.setText("")
            return

        tm = self._theme_manager
        if tm.is_modular(name):
            parts = tm.theme_parts(name)
            self._info_label.setText(
                f"Модульная тема ({len(parts)} файлов): {', '.join(parts)}"
            )
        else:
            self._info_label.setText(f"Одиночный файл: {name}.qss")

    def _on_apply(self) -> None:
        """Применить выбранную тему."""
        name = self._combo.currentText()
        if name:
            self._theme_manager.apply_theme(name)

    def _on_reload(self) -> None:
        """Перечитать текущую тему с диска и применить повторно."""
        self._theme_manager.reload_current()
        # Обновить список (вдруг добавили новый файл)
        self._refresh_themes()
        self._update_info()
