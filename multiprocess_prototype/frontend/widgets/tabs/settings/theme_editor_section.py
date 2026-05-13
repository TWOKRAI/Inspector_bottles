"""ThemeEditorSection — редактор переменных темы оформления (v3).

Макет:
  Правая часть (контент):
    +-- Темы ───────────────────────────────────+
    | QTableWidget: Название | Тип | Родительская|
    +------------------+------------------------+
    | Поиск...         |                        |
    +------------------+ Таблица параметров     |
    |                  |                        |
    | > Глобальное     | Имя | Значение | Описан.|
    |   Палитра        |                        |
    |   ...            |                        |
    | > Компоненты     |                        |
    |   Кнопки       <-|                        |
    |   ...            |                        |
    +------------------+------------------------+

  Левая часть (action-колонка, через action_buttons()):
    [Применить тему]   <- primary
    [Сохранить]
    [Обновить]
    ---------------
    [Добавить]
    [Копировать]
    [Переименовать]
    [Удалить]
    ---------------
    [По умолчанию]
    [Отменить]
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QPalette
from PySide6.QtWidgets import (
    QColorDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from multiprocess_prototype.frontend.widgets.primitives import TreeNavWidget
from multiprocess_prototype.registers.theme.schemas import (
    THEME_VAR_DESCRIPTIONS,
    THEME_VAR_TREE,
    ThemeVariables,
    get_default_variables,
)

if TYPE_CHECKING:
    from multiprocess_framework.modules.frontend_module.managers.theme_manager import ThemeManager
    from multiprocess_prototype.frontend.managers.theme_presets_manager import ThemePresetsManager

# Регулярка для проверки hex-цвета (#rrggbb)
_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _build_flat_nav_tree(tree: dict[str, dict[str, list[str]]]) -> dict[str, list[str]]:
    """Конвертировать THEME_VAR_TREE в формат TreeNavWidget: {категория: [подкатегория, ...]}."""
    result: dict[str, list[str]] = {}
    for category, subcats in tree.items():
        result[category] = list(subcats.keys())
    return result


class ThemeEditorSection(QWidget):
    """Секция 'Оформление': таблица тем + TreeNavWidget + QTableWidget переменных + action-кнопки."""

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
        # Снэпшот при загрузке/сохранении — для кнопки 'Отменить'
        self._last_saved_vars: dict[str, str] = {}

        # Выбранная в таблице тема
        self._selected_theme: str = ""
        self._selected_is_default: bool = False

        # Текущая выбранная категория/подкатегория для навигации
        self._current_category: str = ""
        self._current_subcategory: str = ""

        # Строка с inline color editor (-1 = не показан)
        self._color_editor_row: int = -1
        # Единственный экземпляр QColorDialog (переиспользуется)
        self._color_dialog: QColorDialog | None = None

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

        self._btn_save = QPushButton("Сохранить")
        self._btn_save.setToolTip("Сохранить текущие переменные в выбранную custom-тему")

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
        self._btn_save.clicked.connect(self._on_save)
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
            self._btn_save,
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
    # Инициализация UI
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

        self._themes_table = QTableWidget(0, 3)
        self._themes_table.setHorizontalHeaderLabels(
            ["Название", "Тип", "Родительская"]
        )
        # Запрет редактирования
        self._themes_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        # Выделять строку целиком
        self._themes_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        # Отключить внутренний вертикальный скролл — высота будет фиксированной
        self._themes_table.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._themes_table.verticalHeader().setVisible(False)
        # Пропорции колонок: Название(2) : Тип(1) : Родительская(2)
        h = self._themes_table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        h.setStretchLastSection(False)
        # Минимальные размеры задают пропорцию 2:1:2
        h.setMinimumSectionSize(40)
        self._themes_table.setColumnWidth(0, 200)
        self._themes_table.setColumnWidth(1, 100)
        self._themes_table.setColumnWidth(2, 200)

        themes_layout.addWidget(self._themes_table)
        layout.addWidget(themes_group)

        # === Секция 2: Навигация + таблица переменных ===
        vars_group = QGroupBox("Переменные темы")
        vars_outer_layout = QVBoxLayout(vars_group)
        vars_outer_layout.setContentsMargins(4, 4, 4, 4)
        vars_outer_layout.setSpacing(4)

        # Строка поиска
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Поиск переменных...")
        self._search_input.setClearButtonEnabled(True)
        self._search_input.textChanged.connect(self._on_search_changed)
        vars_outer_layout.addWidget(self._search_input)

        # Горизонтальный layout: TreeNavWidget слева + QTableWidget справа
        nav_and_table_layout = QHBoxLayout()
        nav_and_table_layout.setSpacing(8)

        # Навигация (слева)
        self._nav = TreeNavWidget(nav_width=200)
        nav_tree = _build_flat_nav_tree(THEME_VAR_TREE)
        self._nav.set_tree(nav_tree)
        self._nav.leaf_selected.connect(self._on_subcategory_selected)
        self._nav.category_selected.connect(self._on_category_selected)
        nav_and_table_layout.addWidget(self._nav)

        # Таблица переменных (справа)
        self._vars_table = QTableWidget(0, 3)
        self._vars_table.setHorizontalHeaderLabels(["Имя", "Значение", "Описание"])
        self._vars_table.setAlternatingRowColors(True)
        # Запрет редактирования по умолчанию; двойной клик — только для не-hex
        self._vars_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._vars_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._vars_table.verticalHeader().setVisible(False)
        # Без внутреннего вертикального скролла — мастер-скролл DiffScrollTabLayout
        self._vars_table.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        vh = self._vars_table.horizontalHeader()
        vh.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        vh.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        vh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        vh.resizeSection(0, 180)
        vh.resizeSection(1, 160)

        nav_and_table_layout.addWidget(self._vars_table, stretch=1)
        vars_outer_layout.addLayout(nav_and_table_layout)
        layout.addWidget(vars_group)

        # Сигналы таблицы переменных
        self._vars_table.cellClicked.connect(self._on_cell_clicked)
        self._vars_table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        self._vars_table.cellChanged.connect(self._on_cell_changed)

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
        # +3 пустых строки внизу таблицы для визуального запаса
        _EMPTY_ROWS = 3
        self._themes_table.setRowCount(len(themes) + _EMPTY_ROWS)

        for row, (name, kind) in enumerate(themes):
            name_item = QTableWidgetItem(name)
            kind_item = QTableWidgetItem(kind)
            parent = self._presets_manager.get_parent(name)
            parent_item = QTableWidgetItem(parent if parent else "\u2014")

            # default-темы — серый текст в колонках 'Тип' и 'Родительская'
            if kind == "default":
                gray = QBrush(QColor("#888888"))
                kind_item.setForeground(gray)
                parent_item.setForeground(gray)

            self._themes_table.setItem(row, 0, name_item)
            self._themes_table.setItem(row, 1, kind_item)
            self._themes_table.setItem(row, 2, parent_item)

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
        """Загрузить переменные темы по имени и перестроить таблицу."""
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

        # Снэпшот — для 'Отменить'
        self._last_saved_vars = dict(self._current_vars)

        self._rebuild_vars_table()

    # ------------------------------------------------------------------
    # Таблица переменных
    # ------------------------------------------------------------------

    def _get_vars_for_subcategory(self, category: str, subcategory: str) -> list[str]:
        """Получить список имён переменных для подкатегории."""
        return THEME_VAR_TREE.get(category, {}).get(subcategory, [])

    def _get_vars_for_category(self, category: str) -> list[str]:
        """Получить ВСЕ переменные из всех подкатегорий данной категории."""
        result: list[str] = []
        for var_list in THEME_VAR_TREE.get(category, {}).values():
            result.extend(var_list)
        return result

    def _rebuild_vars_table(self) -> None:
        """Перестроить QTableWidget из текущих переменных для выбранной навигации."""
        # Закрыть inline color editor перед перестроением
        self._close_color_editor()

        # Определить список переменных для отображения
        if self._current_subcategory:
            var_names = self._get_vars_for_subcategory(
                self._current_category, self._current_subcategory
            )
        elif self._current_category:
            var_names = self._get_vars_for_category(self._current_category)
        else:
            # Ничего не выбрано — показать всё из первой категории
            first_cat = next(iter(THEME_VAR_TREE), "")
            if first_cat:
                var_names = self._get_vars_for_category(first_cat)
                self._current_category = first_cat
            else:
                var_names = []

        self._populate_vars_table(var_names)

    def _populate_vars_table(self, var_names: list[str]) -> None:
        """Заполнить таблицу переменных указанным списком имён."""
        self._vars_table.blockSignals(True)
        self._vars_table.setRowCount(0)
        self._vars_table.setRowCount(len(var_names))

        for row, var_name in enumerate(var_names):
            value = self._current_vars.get(var_name, "")
            description = THEME_VAR_DESCRIPTIONS.get(var_name, "")

            # Колонка 0: Имя (не редактируемая)
            name_item = QTableWidgetItem(var_name)
            name_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self._vars_table.setItem(row, 0, name_item)

            # Колонка 1: Значение
            value_item = QTableWidgetItem(value)
            if _HEX_RE.match(value):
                # hex-цвета — не редактируемые напрямую, клик откроет color editor
                value_item.setFlags(
                    Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                )
            else:
                # px/rgba/шрифты — редактируемые по двойному клику
                value_item.setFlags(
                    Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsSelectable
                    | Qt.ItemFlag.ItemIsEditable
                )
            self._vars_table.setItem(row, 1, value_item)

            # Колонка 2: Описание (не редактируемая)
            desc_item = QTableWidgetItem(description)
            desc_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self._vars_table.setItem(row, 2, desc_item)

            # Превью цвета — виджет в колонке 1 (поверх текста нет — рядом)
            self._set_color_preview(row, value)

        self._vars_table.blockSignals(False)
        self._update_vars_table_height()

    def _set_color_preview(self, row: int, value: str) -> None:
        """Установить превью цвета в ячейке 'Значение' для hex-значений через QPalette."""
        if _HEX_RE.match(value):
            color = QColor(value)
            # Цветной квадратик через QLabel + QPalette
            preview = QLabel()
            preview.setFixedSize(20, 20)
            palette = preview.palette()
            palette.setColor(QPalette.ColorRole.Window, color)
            preview.setPalette(palette)
            preview.setAutoFillBackground(True)
            # Контейнер с горизонтальным layout для квадратика + текст
            container = QWidget()
            container_layout = QHBoxLayout(container)
            container_layout.setContentsMargins(4, 2, 4, 2)
            container_layout.setSpacing(6)
            container_layout.addWidget(preview)
            # Текст со значением
            label = QLabel(value)
            container_layout.addWidget(label)
            container_layout.addStretch()
            self._vars_table.setCellWidget(row, 1, container)
        else:
            # Для не-hex — убрать виджет, если был
            self._vars_table.removeCellWidget(row, 1)

    def _update_vars_table_height(self) -> None:
        """Пересчитать и установить фиксированную высоту таблицы переменных.

        Без внутреннего скролла высота должна вмещать все строки —
        мастер-скролл DiffScrollTabLayout прокрутит всё.
        """
        header_h = self._vars_table.horizontalHeader().height()
        row_count = self._vars_table.rowCount()
        if row_count == 0:
            self._vars_table.setFixedHeight(header_h + 40)
            return
        total_h = header_h + 4  # +4 margin
        for r in range(row_count):
            total_h += self._vars_table.rowHeight(r)
        self._vars_table.setFixedHeight(total_h)

    def _collect_vars_from_table(self) -> dict[str, str]:
        """Собрать текущие значения переменных из таблицы."""
        result: dict[str, str] = {}
        for row in range(self._vars_table.rowCount()):
            name_item = self._vars_table.item(row, 0)
            if name_item is None:
                continue
            var_name = name_item.text()
            # Проверить: если есть cellWidget (color preview), значение берём из _current_vars
            widget = self._vars_table.cellWidget(row, 1)
            if widget is not None:
                # Значение из _current_vars (уже обновлено color editor'ом)
                result[var_name] = self._current_vars.get(var_name, "")
            else:
                value_item = self._vars_table.item(row, 1)
                if value_item is not None:
                    result[var_name] = value_item.text().strip()
        return result

    # ------------------------------------------------------------------
    # Inline color editor (expandable row)
    # ------------------------------------------------------------------

    def _create_color_dialog(self) -> QColorDialog:
        """Создать новый экземпляр QColorDialog (не кэшировать — ownership у таблицы)."""
        dialog = QColorDialog(self)
        dialog.setOption(QColorDialog.ColorDialogOption.NoButtons, True)
        dialog.setOption(QColorDialog.ColorDialogOption.ShowAlphaChannel, False)
        dialog.currentColorChanged.connect(self._on_color_live_changed)
        return dialog

    def _open_color_editor(self, row: int) -> None:
        """Вставить строку под row с QColorDialog (expandable inline editor)."""
        # Закрыть предыдущий, если был
        self._close_color_editor()

        # Получить имя переменной и текущий цвет
        name_item = self._vars_table.item(row, 0)
        if name_item is None:
            return
        var_name = name_item.text()
        current_value = self._current_vars.get(var_name, "#000000")
        if not _HEX_RE.match(current_value):
            return

        # Запомнить строку, к которой привязан editor
        self._color_editor_target_row = row
        self._color_editor_var_name = var_name

        # Вставить новую строку под целевой
        editor_row = row + 1
        self._vars_table.blockSignals(True)
        self._vars_table.insertRow(editor_row)
        self._color_editor_row = editor_row

        # Создать новый QColorDialog (не кэшируем — setCellWidget передаёт ownership)
        self._color_dialog = self._create_color_dialog()
        self._color_dialog.setCurrentColor(QColor(current_value))
        dialog = self._color_dialog

        # Установить QColorDialog как cellWidget, заняв все 3 колонки через span
        self._vars_table.setSpan(editor_row, 0, 1, 3)
        self._vars_table.setCellWidget(editor_row, 0, dialog)
        # Высота строки под диалог
        self._vars_table.setRowHeight(editor_row, dialog.sizeHint().height())
        self._vars_table.blockSignals(False)

        self._update_vars_table_height()

    def _close_color_editor(self) -> None:
        """Закрыть inline color editor (убрать вставленную строку)."""
        if self._color_editor_row < 0:
            return

        row = self._color_editor_row
        self._color_editor_row = -1

        self._vars_table.blockSignals(True)
        # Qt удалит QColorDialog при removeRow — обнуляем ссылку
        self._color_dialog = None
        self._vars_table.setSpan(row, 0, 1, 1)  # Сбросить span
        self._vars_table.removeRow(row)
        self._vars_table.blockSignals(False)

        self._update_vars_table_height()

    def _on_color_live_changed(self, color: QColor) -> None:
        """Live-обновление значения при изменении цвета в QColorDialog."""
        if self._color_editor_row < 0:
            return

        hex_color = color.name()  # #rrggbb
        var_name = getattr(self, "_color_editor_var_name", "")
        if not var_name:
            return

        # Обновить _current_vars
        self._current_vars[var_name] = hex_color

        # Обновить превью в строке-цели
        target_row = getattr(self, "_color_editor_target_row", -1)
        if target_row >= 0:
            self._set_color_preview(target_row, hex_color)

    # ------------------------------------------------------------------
    # Обработчики навигации
    # ------------------------------------------------------------------

    def _on_subcategory_selected(self, category: str, subcategory: str) -> None:
        """Клик по подкатегории в TreeNavWidget — показать её переменные."""
        # Собрать текущие значения перед переключением
        self._flush_table_to_vars()

        self._current_category = category
        self._current_subcategory = subcategory
        self._rebuild_vars_table()

    def _on_category_selected(self, category: str) -> None:
        """Клик по категории в TreeNavWidget — показать ВСЕ переменные подкатегорий."""
        # Собрать текущие значения перед переключением
        self._flush_table_to_vars()

        self._current_category = category
        self._current_subcategory = ""
        self._rebuild_vars_table()

    def _on_search_changed(self, text: str) -> None:
        """Фильтрация TreeNavWidget по тексту поиска."""
        if text.strip():
            self._nav.filter(text.strip())
        else:
            self._nav.clear_filter()

    def _flush_table_to_vars(self) -> None:
        """Собрать текущие значения из таблицы в self._current_vars."""
        current = self._collect_vars_from_table()
        self._current_vars.update(current)

    # ------------------------------------------------------------------
    # Вспомогательные методы
    # ------------------------------------------------------------------

    @staticmethod
    def _make_separator() -> QWidget:
        """Создать горизонтальный разделитель для action-колонки.

        Тёмно-серая линия, короче на 20px (отступы по 10px с каждой стороны).
        """
        container = QWidget()
        container_layout = QHBoxLayout(container)
        container_layout.setContentsMargins(10, 4, 10, 4)
        container_layout.setSpacing(0)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Plain)
        line.setObjectName("ThemeDivider")
        line.setFixedHeight(2)
        container_layout.addWidget(line)
        return container

    def _update_crud_buttons_state(self) -> None:
        """Обновить enabled/disabled кнопок, зависящих от типа темы."""
        # Для default-тем сохранение, переименование и удаление недоступны
        can_modify = not self._selected_is_default and bool(self._selected_theme)
        self._btn_save.setEnabled(can_modify)
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
        """Клик по строке таблицы тем -> загрузить переменные."""
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
    # Обработчики событий таблицы переменных
    # ------------------------------------------------------------------

    def _on_cell_clicked(self, row: int, column: int) -> None:
        """Клик на ячейку таблицы переменных — для hex открыть color editor."""
        # Игнорировать клик на строке color editor
        if row == self._color_editor_row:
            return

        # Корректировать row, если color editor вставлен выше
        actual_row = row
        if self._color_editor_row >= 0 and row > self._color_editor_row:
            actual_row = row - 1

        # Клик на колонку 'Значение' (1) для hex
        if column == 1:
            name_item = self._vars_table.item(row, 0)
            if name_item is None:
                return
            var_name = name_item.text()
            value = self._current_vars.get(var_name, "")
            if _HEX_RE.match(value):
                # Если color editor уже открыт для этой строки — закрыть
                if (
                    self._color_editor_row >= 0
                    and getattr(self, "_color_editor_target_row", -1) == row
                ):
                    self._close_color_editor()
                else:
                    self._open_color_editor(row)
                return

    def _on_cell_double_clicked(self, row: int, column: int) -> None:
        """Двойной клик на ячейку 'Значение' — inline edit для px/rgba/шрифтов."""
        # Игнорировать строку color editor
        if row == self._color_editor_row:
            return

        if column != 1:
            return

        name_item = self._vars_table.item(row, 0)
        if name_item is None:
            return

        var_name = name_item.text()
        value = self._current_vars.get(var_name, "")

        # Hex-цвета обрабатываются через color editor (по клику), не по двойному клику
        if _HEX_RE.match(value):
            return

        # Для не-hex включить редактирование ячейки
        value_item = self._vars_table.item(row, 1)
        if value_item is not None:
            self._vars_table.editItem(value_item)

    def _on_cell_changed(self, row: int, column: int) -> None:
        """Редактирование ячейки в таблице -> обновить _current_vars."""
        if column != 1:
            return
        # Игнорировать строку color editor
        if row == self._color_editor_row:
            return

        name_item = self._vars_table.item(row, 0)
        value_item = self._vars_table.item(row, 1)
        if name_item is None or value_item is None:
            return

        var_name = name_item.text()
        var_value = value_item.text().strip()
        self._current_vars[var_name] = var_value

    # ------------------------------------------------------------------
    # Обработчики кнопок action-колонки
    # ------------------------------------------------------------------

    def _on_apply(self) -> None:
        """Применить тему с текущими переменными из таблицы."""
        # Взять первую default-тему как QSS-базу
        defaults = self._presets_manager.list_defaults()
        base_theme = defaults[0] if defaults else self._theme_manager.current_theme

        current = self._collect_vars_from_table()
        self._current_vars.update(current)
        self._theme_manager.apply_theme_with_variables(base_theme, self._current_vars)

    def _on_save(self) -> None:
        """Сохранить текущие переменные в выбранную custom-тему."""
        if not self._selected_theme or self._selected_is_default:
            return
        current = self._collect_vars_from_table()
        self._current_vars.update(current)
        variables = ThemeVariables.model_validate(self._current_vars)
        parent = self._presets_manager.get_parent(self._selected_theme)
        self._presets_manager.save_custom(
            self._selected_theme, variables, parent=parent,
        )
        self._last_saved_vars = dict(self._current_vars)

    def _on_refresh(self) -> None:
        """Перечитать список тем и переменные с диска."""
        prev_selected = self._selected_theme
        self._refresh_table()
        # Восстановить ранее выбранную тему если она ещё существует
        if prev_selected:
            self._select_table_row_by_name(prev_selected)

    def _on_add(self) -> None:
        """Создать новую custom-тему на базе текущей выбранной."""
        name, ok = QInputDialog.getText(
            self,
            "Новая тема",
            "Введите имя новой темы:",
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        # Родительская тема — выбранная default или parent выбранной custom
        if self._selected_is_default:
            parent = self._selected_theme
        else:
            parent = (
                self._presets_manager.get_parent(self._selected_theme)
                or self._selected_theme
            )
        # Создать на основе текущих переменных из таблицы
        current = self._collect_vars_from_table()
        self._current_vars.update(current)
        variables = ThemeVariables.model_validate(self._current_vars)
        self._presets_manager.save_custom(name, variables, parent=parent)
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
        self._rebuild_vars_table()
