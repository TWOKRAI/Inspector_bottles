# multiprocess_prototype/frontend/widgets/settings/settings_tab/theme_editor_section.py
"""ThemeEditorSection — редактор переменных темы оформления.

Двухуровневое дерево: группы -> переменные с inline-редактированием.
Поддержка пресетов: загрузка, сохранение, удаление, сброс к умолчаниям.

Макет:
  ┌─ Базовая тема ──────────────────────────────────┐
  │ [ComboBox: innotech_theme] [Обновить]            │
  ├─ Пресеты ───────────────────────────────────────┤
  │ [ComboBox] [Загрузить] [Сохранить] [Удалить] [По умолчанию] │
  ├─ Переменные темы ───────────────────────────────┤
  │  QTreeWidget (группы -> переменные)              │
  ├──────────────────────────────────────────────────┤
  │              [Применить тему]                    │
  └──────────────────────────────────────────────────┘
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from multiprocess_framework.modules.frontend_module.core.qt_imports import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
    Qt,
)
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QColorDialog

from multiprocess_prototype.registers.theme.schemas import (
    THEME_VAR_DESCRIPTIONS,
    THEME_VAR_GROUPS,
    get_default_variables,
)

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.managers.theme_manager import ThemeManager
    from multiprocess_prototype.frontend.managers.theme_presets_manager import (
        ThemePresetsManager,
    )


# Регулярка для проверки hex-цвета
_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class ThemeEditorSection(QWidget):
    """Секция настроек: полный редактор переменных темы + пресеты."""

    def __init__(
        self,
        theme_manager: "ThemeManager",
        presets_manager: "ThemePresetsManager",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme_manager = theme_manager
        self._presets_manager = presets_manager
        # Текущие значения переменных (редактируемые в UI)
        self._current_vars: dict[str, str] = {}
        self._init_ui()

    # ------------------------------------------------------------------
    # Инициализация UI
    # ------------------------------------------------------------------

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # === Секция 1: Базовая тема ===
        theme_group = QGroupBox("Базовая тема")
        theme_layout = QHBoxLayout(theme_group)

        self._theme_combo = QComboBox()
        self._theme_combo.setMinimumWidth(200)
        theme_layout.addWidget(self._theme_combo)

        self._btn_refresh = QPushButton("Обновить")
        self._btn_refresh.setToolTip(
            "Перечитать список тем и текущие переменные с диска"
        )
        theme_layout.addWidget(self._btn_refresh)
        theme_layout.addStretch()

        layout.addWidget(theme_group)

        # === Секция 2: Пресеты ===
        presets_group = QGroupBox("Пресеты")
        presets_layout = QHBoxLayout(presets_group)

        self._preset_combo = QComboBox()
        self._preset_combo.setMinimumWidth(180)
        self._preset_combo.setEditable(True)
        self._preset_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        presets_layout.addWidget(self._preset_combo)

        self._btn_load_preset = QPushButton("Загрузить")
        self._btn_load_preset.setToolTip("Загрузить выбранный пресет в таблицу")
        presets_layout.addWidget(self._btn_load_preset)

        self._btn_save_preset = QPushButton("Сохранить")
        self._btn_save_preset.setToolTip(
            "Сохранить текущие значения как пресет (имя из поля ввода)"
        )
        presets_layout.addWidget(self._btn_save_preset)

        self._btn_delete_preset = QPushButton("Удалить")
        self._btn_delete_preset.setToolTip("Удалить выбранный пресет")
        presets_layout.addWidget(self._btn_delete_preset)

        self._btn_reset_defaults = QPushButton("По умолчанию")
        self._btn_reset_defaults.setToolTip(
            "Сбросить таблицу к значениям по умолчанию из variables.yaml темы"
        )
        presets_layout.addWidget(self._btn_reset_defaults)

        presets_layout.addStretch()
        layout.addWidget(presets_group)

        # === Секция 3: Дерево переменных ===
        vars_group = QGroupBox("Переменные темы")
        vars_layout = QVBoxLayout(vars_group)

        self._tree = QTreeWidget()
        self._tree.setColumnCount(3)
        self._tree.setHeaderLabels(["Параметр", "Значение", "Описание"])
        self._tree.setAlternatingRowColors(True)
        self._tree.setRootIsDecorated(True)

        # Настройка ширины столбцов
        header = self._tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.resizeSection(1, 120)

        vars_layout.addWidget(self._tree)
        layout.addWidget(vars_group, 1)  # stretch=1, дерево занимает основное место

        # === Кнопка «Применить тему» ===
        apply_layout = QHBoxLayout()
        apply_layout.addStretch()
        self._btn_apply = QPushButton("Применить тему")
        self._btn_apply.setProperty("role", "primary")
        self._btn_apply.setMinimumWidth(200)
        apply_layout.addWidget(self._btn_apply)
        apply_layout.addStretch()
        layout.addLayout(apply_layout)

        # === Заполнить данные ===
        self._refresh_themes()
        self._refresh_presets()
        self._load_variables_from_theme()

        # === Сигналы ===
        self._btn_refresh.clicked.connect(self._on_refresh)
        self._btn_load_preset.clicked.connect(self._on_load_preset)
        self._btn_save_preset.clicked.connect(self._on_save_preset)
        self._btn_delete_preset.clicked.connect(self._on_delete_preset)
        self._btn_reset_defaults.clicked.connect(self._on_reset_defaults)
        self._btn_apply.clicked.connect(self._on_apply)
        self._tree.itemChanged.connect(self._on_item_changed)
        self._tree.itemDoubleClicked.connect(self._on_item_double_clicked)

    # ------------------------------------------------------------------
    # Загрузка данных
    # ------------------------------------------------------------------

    def _refresh_themes(self) -> None:
        """Обновить список тем в комбобоксе."""
        self._theme_combo.blockSignals(True)
        self._theme_combo.clear()
        themes = self._theme_manager.available_themes()
        self._theme_combo.addItems(themes)
        current = self._theme_manager.current_theme
        idx = self._theme_combo.findText(current)
        if idx >= 0:
            self._theme_combo.setCurrentIndex(idx)
        self._theme_combo.blockSignals(False)

    def _refresh_presets(self) -> None:
        """Обновить список пресетов в комбобоксе."""
        self._preset_combo.blockSignals(True)
        current_text = self._preset_combo.currentText()
        self._preset_combo.clear()
        presets = self._presets_manager.list_presets()
        self._preset_combo.addItems(presets)
        # Восстановить выделение
        idx = self._preset_combo.findText(current_text)
        if idx >= 0:
            self._preset_combo.setCurrentIndex(idx)
        elif presets:
            self._preset_combo.setCurrentIndex(0)
        self._preset_combo.blockSignals(False)

    def _load_variables_from_theme(self) -> None:
        """Загрузить переменные из текущей темы и построить дерево."""
        theme_name = self._theme_combo.currentText()
        if theme_name:
            self._current_vars = self._theme_manager.read_default_variables(
                theme_name
            )
        else:
            self._current_vars = get_default_variables()
        self._rebuild_tree()

    def _load_variables_from_dict(self, data: dict[str, str]) -> None:
        """Загрузить переменные из словаря и перестроить дерево."""
        # Обновляем только известные ключи
        for key in self._current_vars:
            if key in data:
                self._current_vars[key] = data[key]
        self._rebuild_tree()

    # ------------------------------------------------------------------
    # Дерево переменных
    # ------------------------------------------------------------------

    def _rebuild_tree(self) -> None:
        """Перестроить QTreeWidget из текущих переменных."""
        self._tree.blockSignals(True)
        self._tree.clear()

        for group_name, var_names in THEME_VAR_GROUPS.items():
            group_item = QTreeWidgetItem(self._tree, [group_name, "", ""])
            group_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled  # type: ignore[arg-type]
            )
            group_item.setExpanded(True)

            for var_name in var_names:
                value = self._current_vars.get(var_name, "")
                description = THEME_VAR_DESCRIPTIONS.get(var_name, "")

                child = QTreeWidgetItem(group_item, [var_name, value, description])
                # Столбец «Значение» — редактируемый
                child.setFlags(
                    Qt.ItemFlag.ItemIsEnabled  # type: ignore[arg-type]
                    | Qt.ItemFlag.ItemIsSelectable
                    | Qt.ItemFlag.ItemIsEditable
                )
                # Цветовая подсветка ячейки значения
                self._apply_color_hint(child, value)

        self._tree.blockSignals(False)

    def _apply_color_hint(self, item: QTreeWidgetItem, value: str) -> None:
        """Установить фоновый цвет ячейки «Значение» если это hex-цвет."""
        if _HEX_RE.match(value):
            color = QColor(value)
            item.setBackground(1, QBrush(color))
            # Контрастный цвет текста
            luminance = 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()
            text_color = QColor("#000000") if luminance > 128 else QColor("#ffffff")
            item.setForeground(1, QBrush(text_color))
        else:
            # Сбросить фон для не-цветовых значений (шрифты и т.д.)
            item.setData(1, Qt.ItemDataRole.BackgroundRole, None)
            item.setData(1, Qt.ItemDataRole.ForegroundRole, None)

    def _collect_vars_from_tree(self) -> dict[str, str]:
        """Собрать текущие значения переменных из дерева."""
        result: dict[str, str] = {}
        root = self._tree.invisibleRootItem()
        for gi in range(root.childCount()):
            group_item = root.child(gi)
            for ci in range(group_item.childCount()):
                child = group_item.child(ci)
                var_name = child.text(0)
                var_value = child.text(1).strip()
                result[var_name] = var_value
        return result

    # ------------------------------------------------------------------
    # Обработчики событий
    # ------------------------------------------------------------------

    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        """Двойной клик на ячейку «Значение» — открыть палитру для hex-цветов."""
        if column != 1:
            return
        # Только для leaf-элементов (не групп)
        if item.childCount() > 0:
            return
        current_value = item.text(1).strip()
        if not _HEX_RE.match(current_value):
            return
        initial = QColor(current_value)
        chosen = QColorDialog.getColor(
            initial,
            self,
            "Выберите цвет",
            QColorDialog.ColorDialogOption.ShowAlphaChannel,
        )
        if chosen.isValid():
            hex_color = chosen.name()  # #rrggbb
            self._tree.blockSignals(True)
            item.setText(1, hex_color)
            self._current_vars[item.text(0)] = hex_color
            self._apply_color_hint(item, hex_color)
            self._tree.blockSignals(False)

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        """Обработка редактирования ячейки в дереве."""
        if column != 1:
            return
        var_name = item.text(0)
        var_value = item.text(1).strip()
        self._current_vars[var_name] = var_value
        # Обновить цветовую подсветку
        self._tree.blockSignals(True)
        self._apply_color_hint(item, var_value)
        self._tree.blockSignals(False)

    def _on_refresh(self) -> None:
        """Перечитать темы и переменные с диска."""
        self._refresh_themes()
        self._refresh_presets()
        self._load_variables_from_theme()

    def _on_load_preset(self) -> None:
        """Загрузить выбранный пресет в таблицу."""
        name = self._preset_combo.currentText().strip()
        if not name:
            return
        data = self._presets_manager.get_preset(name)
        if data is not None:
            self._load_variables_from_dict(data)

    def _on_save_preset(self) -> None:
        """Сохранить текущие значения как пресет."""
        name = self._preset_combo.currentText().strip()
        if not name:
            return
        current = self._collect_vars_from_tree()
        self._current_vars.update(current)
        self._presets_manager.save_preset(name, self._current_vars)
        self._refresh_presets()
        # Установить сохранённый пресет как выбранный
        idx = self._preset_combo.findText(name)
        if idx >= 0:
            self._preset_combo.setCurrentIndex(idx)

    def _on_delete_preset(self) -> None:
        """Удалить выбранный пресет."""
        name = self._preset_combo.currentText().strip()
        if not name:
            return
        self._presets_manager.delete_preset(name)
        self._refresh_presets()

    def _on_reset_defaults(self) -> None:
        """Сбросить таблицу к дефолтным значениям из темы."""
        self._load_variables_from_theme()

    def _on_apply(self) -> None:
        """Применить тему с текущими переменными из таблицы."""
        theme_name = self._theme_combo.currentText()
        if not theme_name:
            return
        current = self._collect_vars_from_tree()
        self._current_vars.update(current)
        self._theme_manager.apply_theme_with_variables(
            theme_name, self._current_vars
        )
