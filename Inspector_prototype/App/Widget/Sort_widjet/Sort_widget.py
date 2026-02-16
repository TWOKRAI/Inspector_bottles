# -*- coding: utf-8 -*-
"""
Виджет сортовых параметров: выбор рецепта, дерево параметров (таблица с раскрываемыми списками),
чекбоксы для bool, экспорт в Excel.
"""
import ast
import json
import yaml
from PyQt5 import QtWidgets, QtCore
from PyQt5.QtGui import QIntValidator
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QMessageBox, QTreeWidget, QTreeWidgetItem, QHeaderView, QFileDialog,
    QCheckBox, QLineEdit, QPushButton, QHBoxLayout, QWidget,
    QAbstractItemView,
)

from App.Widget.Sort_widjet.sort_data import SortData
from App.Widget.Sort_widjet.sort_excel_export import SortExcelExporter


def _normalize_value(v):
    """Привести значение к типу для отображения (bool/list/скаляр). Строку '[...]' парсит как JSON или literal."""
    if isinstance(v, bool):
        return v
    if isinstance(v, list):
        return v  # сохраняем тип элементов (dict/str)
    s = str(v).strip()
    if not s:
        return v
    low = s.lower()
    if low in ("true", "1", "yes"):
        return True
    if low in ("false", "0", "no"):
        return False
    # Строка как список: JSON "[{...}, ...]" или "[1,2]" / "a; b; c"
    if s.startswith("[") and s.endswith("]"):
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return parsed
        except (ValueError, TypeError, json.JSONDecodeError):
            pass
        try:
            parsed = ast.literal_eval(s)
            if isinstance(parsed, list):
                return parsed
        except (ValueError, SyntaxError):
            try:
                parsed = yaml.safe_load(s)
                if isinstance(parsed, list):
                    return parsed
            except Exception:
                pass
    if ";" in s:
        return [x.strip() for x in s.split(";")]
    return v


class SortWidget(QtWidgets.QWidget):
    applied = pyqtSignal(int)
    saved = pyqtSignal(int)
    default = pyqtSignal(int)

    def __init__(self, sort_data, default_number=2, params_provider=None):
        super().__init__()
        if sort_data is None:
            sort_data = SortData()
        self.sort_data = sort_data
        self._params_provider = params_provider  # callable() -> dict текущих параметров приложения
        self.min_value = 0
        self.max_value = 21
        self.number_value = max(self.min_value, min(self.max_value, sort_data.get_current_recipe_number()))
        if self.number_value != sort_data.get_current_recipe_number():
            sort_data.set_current_recipe_number(self.number_value)

        self._refresh_timer = QtCore.QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self._on_refresh_timer)

        self._build_controls()
        self._build_tree()
        self._layout()
        self._connect_signals()
        self._refresh_table()
        self.update_buttons()

    def _build_controls(self):
        self.btn_left = QtWidgets.QPushButton("←")
        self.input = QtWidgets.QLineEdit()
        self.btn_right = QtWidgets.QPushButton("→")
        self.apply_btn = QtWidgets.QPushButton("Загрузить")
        self.save_btn = QtWidgets.QPushButton("Сохранить")
        self.default_btn = QtWidgets.QPushButton("По дефолту")
        self.export_excel_btn = QtWidgets.QPushButton("Форматировать в Excel")

        self.input.setAlignment(Qt.AlignCenter)
        self.input.setFixedWidth(60)
        self.input.setText(str(self.number_value))
        self.input.setValidator(QIntValidator(self.min_value, self.max_value))

        self.btn_left.setFixedSize(60, 50)
        self.btn_right.setFixedSize(60, 50)
        self.input.setFixedSize(70, 50)
        button_size = QtCore.QSize(100, 50)
        self.apply_btn.setFixedSize(button_size)
        self.save_btn.setFixedSize(button_size)
        self.default_btn.setFixedSize(button_size)
        self.export_excel_btn.setFixedHeight(50)

    def _build_tree(self):
        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Параметр", "Значение", "Информация"])
        self.tree.setAlternatingRowColors(True)
        self.tree.setAnimated(True)
        self.tree.setIndentation(20)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(2, QHeaderView.Stretch)
        self.tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table_ignore_changes = False

    def _layout(self):
        layout = QtWidgets.QVBoxLayout(self)

        row = QtWidgets.QHBoxLayout()
        row.addStretch()
        row.addWidget(self.btn_left)
        row.addSpacing(10)
        row.addWidget(self.input)
        row.addSpacing(10)
        row.addWidget(self.btn_right)
        row.addSpacing(10)
        row.addWidget(self.apply_btn)
        row.addSpacing(10)
        row.addWidget(self.save_btn)
        row.addSpacing(10)
        row.addWidget(self.default_btn)
        row.addSpacing(10)
        row.addWidget(self.export_excel_btn)
        row.addStretch()
        layout.addLayout(row)

        layout.addWidget(QtWidgets.QLabel("Параметры рецепта:"))
        layout.addWidget(self.tree)

    def _connect_signals(self):
        self.btn_left.clicked.connect(self.decrement)
        self.btn_right.clicked.connect(self.increment)
        self.input.textChanged.connect(self.validate_input)
        self.apply_btn.clicked.connect(self._emit_applied)
        self.save_btn.clicked.connect(self._emit_saved)
        self.default_btn.clicked.connect(self._emit_default)
        self.export_excel_btn.clicked.connect(self._export_to_excel)
        self.tree.itemExpanded.connect(self._on_item_expanded)

    def _show_confirmation_dialog(self, title, message):
        dialog = QMessageBox(
            QMessageBox.Question,
            title,
            f"<center>{message}</center>",
            QMessageBox.Yes | QMessageBox.No,
            parent=self,
        )
        dialog.setTextFormat(QtCore.Qt.RichText)
        dialog.setDefaultButton(QMessageBox.No)
        return dialog.exec_() == QMessageBox.Yes

    def _emit_applied(self):
        if self._show_confirmation_dialog(
            "Подтверждение применения",
            f"Вы уверены, что хотите применить значения в сорт-{self.number_value}?",
        ):
            self.applied.emit(self.number_value)

    def _emit_saved(self):
        if self._show_confirmation_dialog(
            "Подтверждение сохранения",
            f"Вы уверены, что хотите сохранить значения в сорт-{self.number_value}?",
        ):
            self.saved.emit(self.number_value)

    def _emit_default(self):
        if self._show_confirmation_dialog(
            "Подтверждение",
            f"Вы уверены, что хотите сделать значения сорта-{self.number_value} по дефолту?",
        ):
            self.default.emit(self.number_value)

    def _export_to_excel(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Экспорт в Excel",
            "value_settings.xlsx",
            "Excel (*.xlsx)",
        )
        if path:
            if SortExcelExporter.export_to_excel(self.sort_data, path):
                QMessageBox.information(self, "Экспорт", f"Данные сохранены в:\n{path}")
            else:
                QMessageBox.warning(self, "Экспорт", "Нет данных для экспорта.")

    def validate_input(self):
        try:
            new_value = int(self.input.text())
        except ValueError:
            new_value = self.min_value
        self.number_value = max(self.min_value, min(self.max_value, new_value))
        self.input.setText(str(self.number_value))
        self.sort_data.set_current_recipe_number(self.number_value)
        self._refresh_table()
        self.update_buttons()

    def get_value(self):
        return self.number_value

    def set_value(self, value):
        self.number_value = max(self.min_value, min(self.max_value, value))
        self.input.setText(str(self.number_value))
        self.sort_data.set_current_recipe_number(self.number_value)
        self._refresh_table()
        self.update_buttons()

    def update_buttons(self):
        self.btn_left.setEnabled(self.number_value > self.min_value)
        self.btn_right.setEnabled(self.number_value < self.max_value)

    def decrement(self):
        self.set_value(self.number_value - 1)

    def increment(self):
        self.set_value(self.number_value + 1)

    def set_params_provider(self, callable_provider):
        """Установить источник текущих параметров приложения (для обновления таблицы при изменении слайдеров и т.д.)."""
        self._params_provider = callable_provider

    def schedule_refresh(self):
        """Запланировать обновление таблицы через 300 мс (чтобы не перерисовывать на каждый тик слайдера)."""
        self._refresh_timer.stop()
        self._refresh_timer.start(300)

    def _on_refresh_timer(self):
        """Обновить таблицу текущими параметрами из приложения."""
        live = self._params_provider() if callable(self._params_provider) else None
        self._refresh_table(live_params=live)

    def _on_item_expanded(self, item):
        """При раскрытии по стрелке дерева — заполнить дочерние строки для параметра-списка."""
        param_name = item.data(0, Qt.UserRole)
        if not param_name or param_name == "list_item":
            return
        recipe = self.sort_data.get_recipe(self.number_value)
        val = recipe.get(param_name, [])
        if isinstance(_normalize_value(val), list):
            self._fill_list_children(item, param_name)

    def _value_to_display(self, value):
        """Единообразное отображение значения в ячейке (для скаляра в списке и т.д.)."""
        v = _normalize_value(value)
        if isinstance(v, bool):
            return "✓" if v else "○"
        if isinstance(v, list):
            return f"{len(v)} элемент(ов)"
        return str(value)

    def _make_value_cell_bool(self, param_name, value):
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(2, 0, 2, 0)
        cb = QCheckBox()
        cb.setChecked(bool(_normalize_value(value)))
        cb.stateChanged.connect(lambda state, p=param_name: self._save_bool_param(p, state == Qt.Checked))
        lay.addWidget(cb)
        lay.addStretch()
        return w

    def _save_bool_param(self, param_name, checked):
        if self._table_ignore_changes:
            return
        self.sort_data.set_recipe_param(self.number_value, param_name, checked)

    def _make_value_cell_scalar(self, param_name, value):
        le = QLineEdit()
        le.setText(str(value) if value is not None and value != "" else "")
        le.setPlaceholderText("значение")
        le.textChanged.connect(lambda text, p=param_name: self._save_scalar_param(p, text))
        return le

    def _save_scalar_param(self, param_name, text):
        if self._table_ignore_changes:
            return
        self.sort_data.set_recipe_param(self.number_value, param_name, text)

    def _make_value_cell_list(self, param_name, value_list, parent_item):
        """Виджет для строки-списка: подпись «N элемент(ов)», кнопки Развернуть/Свернуть, Добавить."""
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(2, 0, 2, 0)
        lst = value_list if isinstance(value_list, list) else []
        count = len(lst)
        label = QtWidgets.QLabel(f"{count} элемент(ов)")
        label.setObjectName("list_count_label")
        btn_toggle = QPushButton("▼ Развернуть")
        btn_toggle.setProperty("collapsed", True)
        btn_add = QPushButton("+ Добавить")

        def toggle():
            collapsed = btn_toggle.property("collapsed")
            if collapsed:
                parent_item.setExpanded(True)
                btn_toggle.setText("▲ Свернуть")
                btn_toggle.setProperty("collapsed", False)
                self._fill_list_children(parent_item, param_name)
            else:
                parent_item.setExpanded(False)
                btn_toggle.setText("▼ Развернуть")
                btn_toggle.setProperty("collapsed", True)

        def add_item():
            recipe = self.sort_data.get_recipe(self.number_value)
            raw = recipe.get(param_name, [])
            if not isinstance(raw, list):
                raw = []
            raw = list(raw)
            raw.append("")
            self.sort_data.set_recipe_param(self.number_value, param_name, raw)
            parent_item.setExpanded(True)
            btn_toggle.setText("▲ Свернуть")
            btn_toggle.setProperty("collapsed", False)
            self._fill_list_children(parent_item, param_name)
            label.setText(f"{len(raw)} элемент(ов)")

        btn_toggle.clicked.connect(toggle)
        btn_add.clicked.connect(add_item)
        lay.addWidget(label)
        lay.addWidget(btn_toggle)
        lay.addWidget(btn_add)
        lay.addStretch()
        return w

    def _list_item_display_text(self, item_value):
        """Текст для отображения элемента списка (dict — кратко или JSON, иначе str)."""
        if isinstance(item_value, dict):
            name = item_value.get("name", "")
            x1, y1 = item_value.get("x1", 0), item_value.get("y1", 0)
            x2, y2 = item_value.get("x2", 0), item_value.get("y2", 0)
            if name is not None or (x1, y1, x2, y2) != (0, 0, 0, 0):
                return f"{name} ({x1},{y1})-({x2},{y2})"
            return json.dumps(item_value, ensure_ascii=False)
        return str(item_value)

    def _fill_list_children(self, parent_item, param_name):
        """Заполнить дочерние строки списка (каждый элемент — строка с полем и кнопкой Удалить)."""
        while parent_item.childCount():
            parent_item.takeChild(0)
        recipe = self.sort_data.get_recipe(self.number_value)
        raw = recipe.get(param_name, [])
        raw = _normalize_value(raw) if not isinstance(raw, list) else raw
        if not isinstance(raw, list):
            raw = []
        for idx, item_value in enumerate(raw):
            child = QTreeWidgetItem(parent_item)
            child.setData(0, Qt.UserRole, "list_item")
            child.setData(0, Qt.UserRole + 1, param_name)
            child.setData(0, Qt.UserRole + 2, idx)
            child.setText(0, f"  [{idx + 1}]")
            child.setFlags(child.flags() & ~Qt.ItemIsEditable)
            cell_w = QWidget()
            cell_lay = QHBoxLayout(cell_w)
            cell_lay.setContentsMargins(2, 0, 2, 0)
            le = QLineEdit()
            le.setText(self._list_item_display_text(item_value))
            le.setPlaceholderText("значение или JSON")

            def on_text(t, p=param_name, i=idx):
                if self._table_ignore_changes:
                    return
                r = self.sort_data.get_recipe(self.number_value).get(p, [])
                r = _normalize_value(r) if not isinstance(r, list) else r
                if not isinstance(r, list):
                    r = []
                r = list(r)
                while len(r) <= i:
                    r.append("")
                try:
                    parsed = json.loads(t)
                    r[i] = parsed if isinstance(parsed, dict) else t
                except (ValueError, TypeError, json.JSONDecodeError):
                    r[i] = t
                self.sort_data.set_recipe_param(self.number_value, p, r)

            le.textChanged.connect(on_text)
            btn_del = QPushButton("− Удалить")
            btn_del.setFixedWidth(90)

            def on_del(p=param_name, i=idx):
                if self._table_ignore_changes:
                    return
                r = self.sort_data.get_recipe(self.number_value).get(p, [])
                if not isinstance(r, list):
                    r = []
                r = list(r)
                if 0 <= i < len(r):
                    r.pop(i)
                    self.sort_data.set_recipe_param(self.number_value, p, r)
                    self._refresh_table()

            btn_del.clicked.connect(on_del)
            cell_lay.addWidget(le)
            cell_lay.addWidget(btn_del)
            cell_lay.addStretch()
            self.tree.setItemWidget(child, 1, cell_w)
            # Пустая колонка «Информация» для дочерней строки
            self.tree.setItemWidget(child, 2, QtWidgets.QLabel(""))

    def _refresh_table(self, live_params=None):
        """Построить дерево параметров. Если передан live_params — показывать текущие значения из приложения."""
        self._table_ignore_changes = True
        try:
            self.tree.clear()
            recipe = self.sort_data.get_recipe(self.number_value)
            all_names = set(recipe.keys()) if recipe else set()
            all_names.update(self.sort_data.get_parameter_names())
            if live_params:
                all_names.update(live_params.keys())
            params = sorted(all_names) if all_names else self.sort_data.get_parameter_names()
            if not params and self.sort_data.get_parameter_names():
                params = self.sort_data.get_parameter_names()

            for name in params:
                if live_params is not None and name in live_params:
                    value = live_params.get(name, recipe.get(name, ""))
                else:
                    value = recipe.get(name, "")
                value_norm = _normalize_value(value)
                info = self.sort_data.get_parameter_info(name)

                row = QTreeWidgetItem(self.tree)
                row.setData(0, Qt.UserRole, name)
                row.setText(0, str(name))
                row.setFlags(row.flags() & ~Qt.ItemIsEditable)

                if isinstance(value_norm, bool):
                    row.setChildIndicatorPolicy(QTreeWidgetItem.DontShowIndicatorWhenChildless)
                    self.tree.setItemWidget(row, 1, self._make_value_cell_bool(name, value))
                elif isinstance(value_norm, list):
                    row.setChildIndicatorPolicy(QTreeWidgetItem.ShowIndicator)
                    self.tree.setItemWidget(row, 1, self._make_value_cell_list(name, value_norm, row))
                else:
                    row.setChildIndicatorPolicy(QTreeWidgetItem.DontShowIndicatorWhenChildless)
                    self.tree.setItemWidget(row, 1, self._make_value_cell_scalar(name, value))

                info_edit = QLineEdit()
                info_edit.setText(str(info))
                info_edit.setPlaceholderText("описание параметра")
                info_edit.textChanged.connect(lambda t, p=name: self._save_info_param(p, t))
                self.tree.setItemWidget(row, 2, info_edit)
        finally:
            self._table_ignore_changes = False

    def _save_info_param(self, param_name, text):
        if self._table_ignore_changes:
            return
        self.sort_data.set_parameter_info(param_name, text)

    def refresh_table(self, live_params=None):
        """Вызвать извне после сохранения рецепта или для обновления из текущих параметров приложения."""
        self._refresh_table(live_params=live_params)
