"""ThemeEditorSection — редактор переменных темы оформления (v2).

Макет:
  Правая часть (контент):
    +-- Темы ───────────────────────────────────+
    │ QTableWidget: Название | Тип              │
    +-- Переменные темы ────────────────────────+
    │ QTreeWidget (группы → переменные)         │
    +───────────────────────────────────────────+

  Левая часть (action-колонка, через action_buttons()):
    [Применить тему]   ← primary
    [Обновить]
    ───────────────
    [Добавить]
    [Копировать]
    [Переименовать]
    [Удалить]
    ───────────────
    [По умолчанию]
    [Отменить]
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from multiprocess_prototype.registers.theme.schemas import (
    THEME_VAR_DESCRIPTIONS,
    THEME_VAR_GROUPS,
    ThemeVariables,
    get_default_variables,
)

if TYPE_CHECKING:
    from multiprocess_framework.modules.frontend_module.managers.theme_manager import ThemeManager
    from multiprocess_prototype.frontend.managers.theme_presets_manager import ThemePresetsManager

# Регулярка для проверки hex-цвета (#rrggbb)
_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class ThemeEditorSection(QWidget):
    """Секция «Оформление»: таблица тем + дерево переменных + action-кнопки."""

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
        # Снэпшот при загрузке/сохранении — для кнопки «Отменить»
        self._last_saved_vars: dict[str, str] = {}

        # Выбранная в таблице тема
        self._selected_theme: str = ""
        self._selected_is_default: bool = False

        self._init_buttons()
        self._init_ui()
        self._refresh_table()

    # ------------------------------------------------------------------
    # Инициализация кнопок (до UI, чтобы action_buttons() работал сразу)
    # ------------------------------------------------------------------

    def _init_buttons(self) -> None:
        """Создать все кнопки action-колонки."""
        self._btn_apply = QPushButton("Применить тему")
        self._btn_apply.setProperty("role", "primary")
        self._btn_apply.setToolTip("Применить текущую тему с редактированными переменными")

        self._btn_refresh = QPushButton("Обновить")
        self._btn_refresh.setToolTip("Перечитать список тем и переменные с диска")

        self._btn_add = QPushButton("Добавить")
        self._btn_add.setToolTip("Создать новую пустую custom-тему")

        self._btn_copy = QPushButton("Копировать")
        self._btn_copy.setToolTip("Скопировать выбранную тему как новую custom-тему")

        self._btn_rename = QPushButton("Переименовать")
        self._btn_rename.setToolTip("Переименовать выбранную custom-тему")

        self._btn_delete = QPushButton("Удалить")
        self._btn_delete.setToolTip("Удалить выбранную custom-тему")

        self._btn_defaults = QPushButton("По умолчанию")
        self._btn_defaults.setToolTip("Загрузить дефолтные значения выбранной темы")

        self._btn_revert = QPushButton("Отменить")
        self._btn_revert.setToolTip("Откатить изменения к последнему сохранённому состоянию")

        # Сигналы
        self._btn_apply.clicked.connect(self._on_apply)
        self._btn_refresh.clicked.connect(self._on_refresh)
        self._btn_add.clicked.connect(self._on_add)
        self._btn_copy.clicked.connect(self._on_copy)
        self._btn_rename.clicked.connect(self._on_rename)
        self._btn_delete.clicked.connect(self._on_delete)
        self._btn_defaults.clicked.connect(self._on_reset_defaults)
        self._btn_revert.clicked.connect(self._on_revert)

    # ------------------------------------------------------------------
    # Публичный API: кнопки для action-колонки SettingsTab
    # ------------------------------------------------------------------

    def action_buttons(self) -> list[QWidget]:
        """Кнопки для action-колонки SettingsTab."""
        return [
            self._btn_apply,
            self._btn_refresh,
            self._make_separator(),
            self._btn_add,
            self._btn_copy,
            self._btn_rename,
            self._btn_delete,
            self._make_separator(),
            self._btn_defaults,
            self._btn_revert,
        ]

    # ------------------------------------------------------------------
    # Инициализация UI (таблица тем + дерево переменных)
    # ------------------------------------------------------------------

    def _init_ui(self) -> None:
        """Построить layout контентной части."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # === Секция 1: Таблица тем ===
        themes_group = QGroupBox("Темы")
        themes_layout = QVBoxLayout(themes_group)
        themes_layout.setContentsMargins(4, 4, 4, 4)

        self._themes_table = QTableWidget(0, 2)
        self._themes_table.setHorizontalHeaderLabels(["Название", "Тип"])
        # Запрет редактирования
        self._themes_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        # Выделять строку целиком
        self._themes_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        # Отключить внутренний вертикальный скролл — высота будет фиксированной
        self._themes_table.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._themes_table.verticalHeader().setVisible(False)
        # Колонки: «Название» растягивается, «Тип» — по содержимому
        h = self._themes_table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)

        themes_layout.addWidget(self._themes_table)
        layout.addWidget(themes_group)

        # === Секция 2: Дерево переменных ===
        vars_group = QGroupBox("Переменные темы")
        vars_layout = QVBoxLayout(vars_group)
        vars_layout.setContentsMargins(4, 4, 4, 4)

        self._tree = QTreeWidget()
        self._tree.setColumnCount(3)
        self._tree.setHeaderLabels(["Параметр", "Значение", "Описание"])
        self._tree.setAlternatingRowColors(True)
        self._tree.setRootIsDecorated(True)
        # Без внутреннего вертикального скролла — мастер-скролл DiffScrollTabLayout
        self._tree.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        header = self._tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.resizeSection(1, 120)

        vars_layout.addWidget(self._tree)
        layout.addWidget(vars_group)

        # Сигналы дерева
        self._tree.itemChanged.connect(self._on_item_changed)
        self._tree.itemDoubleClicked.connect(self._on_item_double_clicked)

        # Сигнал таблицы тем
        self._themes_table.currentCellChanged.connect(self._on_theme_selected)

    # ------------------------------------------------------------------
    # Таблица тем
    # ------------------------------------------------------------------

    def _refresh_table(self) -> None:
        """Перезаполнить таблицу тем из presets_manager.list_all()."""
        self._themes_table.blockSignals(True)
        self._themes_table.setRowCount(0)

        themes = self._presets_manager.list_all()
        self._themes_table.setRowCount(len(themes))

        for row, (name, kind) in enumerate(themes):
            name_item = QTableWidgetItem(name)
            kind_item = QTableWidgetItem(kind)

            # default-темы — серый текст в колонке «Тип»
            if kind == "default":
                kind_item.setForeground(QBrush(QColor("#888888")))

            self._themes_table.setItem(row, 0, name_item)
            self._themes_table.setItem(row, 1, kind_item)

        self._themes_table.blockSignals(False)

        # Обновить фиксированную высоту таблицы
        self._update_table_height()

        # Выбрать первую строку по умолчанию
        if self._themes_table.rowCount() > 0:
            self._themes_table.selectRow(0)
            first_name = self._themes_table.item(0, 0)
            if first_name is not None:
                self._load_theme(first_name.text())

    def _update_table_height(self) -> None:
        """Установить фиксированную высоту таблицы по числу строк."""
        header_h = self._themes_table.horizontalHeader().height()
        row_count = self._themes_table.rowCount()
        # Высота строки — если строк нет, берём 30px
        row_h = self._themes_table.rowHeight(0) if row_count > 0 else 30
        total = header_h + row_count * row_h + 4  # +4 margin
        self._themes_table.setFixedHeight(total)

    def _select_table_row_by_name(self, name: str) -> None:
        """Найти и выбрать строку таблицы по имени темы."""
        for row in range(self._themes_table.rowCount()):
            item = self._themes_table.item(row, 0)
            if item is not None and item.text() == name:
                self._themes_table.selectRow(row)
                return

    # ------------------------------------------------------------------
    # Загрузка переменных темы
    # ------------------------------------------------------------------

    def _load_theme(self, name: str) -> None:
        """Загрузить переменные темы по имени и перестроить дерево."""
        variables: ThemeVariables = self._presets_manager.get_variables(name)
        # Собрать в плоский dict
        self._current_vars = {
            field: getattr(variables, field)
            for field in ThemeVariables.model_fields
        }
        # Дополнить пропущенные ключи дефолтами
        defaults = get_default_variables()
        for k, v in defaults.items():
            if k not in self._current_vars:
                self._current_vars[k] = v

        # Снэпшот — для «Отменить»
        self._last_saved_vars = dict(self._current_vars)

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
            group_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            group_item.setExpanded(True)

            for var_name in var_names:
                value = self._current_vars.get(var_name, "")
                description = THEME_VAR_DESCRIPTIONS.get(var_name, "")

                child = QTreeWidgetItem(group_item, [var_name, value, description])
                child.setFlags(
                    Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsSelectable
                    | Qt.ItemFlag.ItemIsEditable
                )
                self._apply_color_hint(child, value)

        self._tree.blockSignals(False)

        # Обновить фиксированную высоту дерева
        self._update_tree_height()

    def _update_tree_height(self) -> None:
        """Пересчитать и установить фиксированную высоту дерева.

        Без внутреннего скролла высота должна вмещать все строки —
        мастер-скролл DiffScrollTabLayout прокрутит всё.
        """
        self._tree.expandAll()
        total_h = self._tree.header().height() + 4  # +4 margin
        root = self._tree.invisibleRootItem()
        for i in range(root.childCount()):
            group = root.child(i)
            total_h += self._tree.rowHeight(
                self._tree.indexFromItem(group)
            )
            for j in range(group.childCount()):
                total_h += self._tree.rowHeight(
                    self._tree.indexFromItem(group.child(j))
                )
        self._tree.setFixedHeight(total_h)

    def _apply_color_hint(self, item: QTreeWidgetItem, value: str) -> None:
        """Установить фоновый цвет ячейки «Значение» если это hex-цвет (#rrggbb)."""
        if _HEX_RE.match(value):
            color = QColor(value)
            item.setBackground(1, QBrush(color))
            luminance = (
                0.299 * color.red()
                + 0.587 * color.green()
                + 0.114 * color.blue()
            )
            text_color = QColor("#000000") if luminance > 128 else QColor("#ffffff")
            item.setForeground(1, QBrush(text_color))
        else:
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
                result[child.text(0)] = child.text(1).strip()
        return result

    # ------------------------------------------------------------------
    # Вспомогательные методы
    # ------------------------------------------------------------------

    @staticmethod
    def _make_separator() -> QFrame:
        """Создать горизонтальный разделитель для action-колонки."""
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        return line

    def _update_crud_buttons_state(self) -> None:
        """Обновить enabled/disabled кнопок «Переименовать» и «Удалить»."""
        # Для default-тем эти операции недоступны
        can_modify = not self._selected_is_default and bool(self._selected_theme)
        self._btn_rename.setEnabled(can_modify)
        self._btn_delete.setEnabled(can_modify)

    # ------------------------------------------------------------------
    # Обработчики событий таблицы тем
    # ------------------------------------------------------------------

    def _on_theme_selected(
        self,
        current_row: int,
        _current_col: int,
        _prev_row: int,
        _prev_col: int,
    ) -> None:
        """Клик по строке таблицы тем → загрузить переменные."""
        if current_row < 0:
            return

        name_item = self._themes_table.item(current_row, 0)
        kind_item = self._themes_table.item(current_row, 1)
        if name_item is None:
            return

        self._selected_theme = name_item.text()
        self._selected_is_default = (
            kind_item is not None and kind_item.text() == "default"
        )
        self._update_crud_buttons_state()
        self._load_theme(self._selected_theme)

    # ------------------------------------------------------------------
    # Обработчики событий дерева переменных
    # ------------------------------------------------------------------

    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        """Двойной клик на ячейку «Значение» — открыть палитру для hex-цветов."""
        if column != 1 or item.childCount() > 0:
            return
        current_value = item.text(1).strip()
        if not _HEX_RE.match(current_value):
            return
        chosen = QColorDialog.getColor(
            QColor(current_value),
            self,
            "Выберите цвет",
            QColorDialog.ColorDialogOption.ShowAlphaChannel,
        )
        if chosen.isValid():
            hex_color = chosen.name()
            self._tree.blockSignals(True)
            item.setText(1, hex_color)
            self._current_vars[item.text(0)] = hex_color
            self._apply_color_hint(item, hex_color)
            self._tree.blockSignals(False)

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        """Редактирование ячейки в дереве → обновить _current_vars."""
        if column != 1:
            return
        var_name = item.text(0)
        var_value = item.text(1).strip()
        self._current_vars[var_name] = var_value
        self._tree.blockSignals(True)
        self._apply_color_hint(item, var_value)
        self._tree.blockSignals(False)

    # ------------------------------------------------------------------
    # Обработчики кнопок action-колонки
    # ------------------------------------------------------------------

    def _on_apply(self) -> None:
        """Применить тему с текущими переменными из дерева."""
        # Взять первую default-тему как QSS-базу
        defaults = self._presets_manager.list_defaults()
        base_theme = defaults[0] if defaults else self._theme_manager.current_theme

        current = self._collect_vars_from_tree()
        self._current_vars.update(current)
        self._last_saved_vars = dict(self._current_vars)
        self._theme_manager.apply_theme_with_variables(base_theme, self._current_vars)

    def _on_refresh(self) -> None:
        """Перечитать список тем и переменные с диска."""
        prev_selected = self._selected_theme
        self._refresh_table()
        # Восстановить ранее выбранную тему если она ещё существует
        if prev_selected:
            self._select_table_row_by_name(prev_selected)

    def _on_add(self) -> None:
        """Создать новую пустую custom-тему."""
        name, ok = QInputDialog.getText(
            self,
            "Новая тема",
            "Введите имя новой темы:",
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        self._presets_manager.save_custom(name, ThemeVariables())
        self._refresh_table()
        self._select_table_row_by_name(name)

    def _on_copy(self) -> None:
        """Скопировать выбранную тему в новую custom-тему."""
        if not self._selected_theme:
            return
        copy_name = self._selected_theme + "_copy"
        name, ok = QInputDialog.getText(
            self,
            "Копировать тему",
            "Введите имя копии:",
            text=copy_name,
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        self._presets_manager.copy_theme(self._selected_theme, name)
        self._refresh_table()
        self._select_table_row_by_name(name)

    def _on_rename(self) -> None:
        """Переименовать выбранную custom-тему."""
        if not self._selected_theme or self._selected_is_default:
            return
        new_name, ok = QInputDialog.getText(
            self,
            "Переименовать тему",
            "Введите новое имя:",
            text=self._selected_theme,
        )
        if not ok or not new_name.strip():
            return
        new_name = new_name.strip()
        self._presets_manager.rename_custom(self._selected_theme, new_name)
        self._refresh_table()
        self._select_table_row_by_name(new_name)

    def _on_delete(self) -> None:
        """Удалить выбранную custom-тему."""
        if not self._selected_theme or self._selected_is_default:
            return
        self._presets_manager.delete_custom(self._selected_theme)
        self._selected_theme = ""
        self._selected_is_default = False
        self._refresh_table()

    def _on_reset_defaults(self) -> None:
        """Загрузить дефолтные значения выбранной темы (без сохранения)."""
        if not self._selected_theme:
            return
        self._load_theme(self._selected_theme)

    def _on_revert(self) -> None:
        """Откатить переменные к последнему сохранённому состоянию."""
        self._current_vars = dict(self._last_saved_vars)
        self._rebuild_tree()
