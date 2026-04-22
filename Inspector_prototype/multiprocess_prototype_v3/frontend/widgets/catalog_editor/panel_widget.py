"""Виджет-таблица для просмотра и редактирования каталога операций."""

from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from registers.processor.catalog.loader import save_catalog
from registers.processor.catalog.schemas import ProcessingOperationDef

from .schemas import CatalogEditorUiConfig

# Допустимые значения поля on_error
_ON_ERROR_OPTIONS = ["skip", "fail_region", "fail_camera"]

# Индексы колонок таблицы
_COL_NAME = 0
_COL_TYPE_KEY = 1
_COL_MODULE_PATH = 2
_COL_PARAMS_SCHEMA = 3
_COL_ON_ERROR = 4
_COL_DESCRIPTION = 5
_COL_COUNT = 6


class CatalogEditorWidget(QWidget):
    """Таблица каталога операций с кнопками Add / Remove / Save."""

    # Сигнал: каталог изменён (после сохранения)
    catalog_changed = pyqtSignal()

    def __init__(
        self,
        ui: Optional[CatalogEditorUiConfig] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._ui = ui or CatalogEditorUiConfig()
        self._catalog_path: Optional[str] = None
        self._init_ui()

    # ------------------------------------------------------------------
    # Инициализация интерфейса
    # ------------------------------------------------------------------

    def _init_ui(self) -> None:
        """Создать таблицу и панель кнопок."""
        u = self._ui
        layout = QVBoxLayout(self)

        # --- Таблица ---
        self._table = QTableWidget(0, _COL_COUNT)
        self._table.setHorizontalHeaderLabels([
            u.col_name,
            u.col_type_key,
            u.col_module_path,
            u.col_params_schema,
            u.col_on_error,
            u.col_description,
        ])
        self._table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._table)

        # --- Панель кнопок ---
        btn_layout = QHBoxLayout()

        self._btn_add = QPushButton(u.btn_add)
        self._btn_add.clicked.connect(self._on_add)
        btn_layout.addWidget(self._btn_add)

        self._btn_remove = QPushButton(u.btn_remove)
        self._btn_remove.clicked.connect(self._on_remove)
        btn_layout.addWidget(self._btn_remove)

        btn_layout.addStretch()

        self._btn_save = QPushButton(u.btn_save)
        self._btn_save.clicked.connect(self._on_save)
        btn_layout.addWidget(self._btn_save)

        layout.addLayout(btn_layout)

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def set_catalog_path(self, path: str) -> None:
        """Установить путь к YAML-файлу для сохранения."""
        self._catalog_path = path

    def set_data(self, catalog: dict[str, ProcessingOperationDef]) -> None:
        """Заполнить таблицу из словаря type_key → ProcessingOperationDef."""
        self._table.setRowCount(0)
        for op in catalog.values():
            self._append_row(op)

    def get_catalog(self) -> Optional[dict[str, ProcessingOperationDef]]:
        """Собрать каталог из таблицы.

        Возвращает словарь type_key → ProcessingOperationDef.
        При невалидных данных показывает QMessageBox и возвращает None.
        """
        result: dict[str, ProcessingOperationDef] = {}
        for row in range(self._table.rowCount()):
            name = self._cell_text(row, _COL_NAME)
            type_key = self._cell_text(row, _COL_TYPE_KEY)
            module_path = self._cell_text(row, _COL_MODULE_PATH)
            params_schema = self._cell_text(row, _COL_PARAMS_SCHEMA)
            on_error_combo: QComboBox = self._table.cellWidget(row, _COL_ON_ERROR)  # type: ignore[assignment]
            on_error = on_error_combo.currentText() if on_error_combo else "skip"
            description = self._cell_text(row, _COL_DESCRIPTION)

            # Проверка: on_error должен быть из допустимых значений
            if on_error not in _ON_ERROR_OPTIONS:
                self._show_error(
                    f"Строка {row + 1}: недопустимое значение on_error='{on_error}'.\n"
                    f"Допустимые: {', '.join(_ON_ERROR_OPTIONS)}"
                )
                return None

            try:
                op = ProcessingOperationDef(
                    name=name,
                    type_key=type_key,
                    module_path=module_path,
                    params_schema=params_schema,
                    on_error=on_error,  # type: ignore[arg-type]
                    description=description,
                )
            except Exception as exc:
                self._show_error(f"Строка {row + 1}: ошибка валидации:\n{exc}")
                return None

            result[op.type_key] = op

        return result

    # ------------------------------------------------------------------
    # Обработчики кнопок
    # ------------------------------------------------------------------

    def _on_add(self) -> None:
        """Добавить новую строку с дефолтными значениями."""
        default_op = ProcessingOperationDef(
            name="Новая операция",
            type_key="new_operation",
            module_path="",
            params_schema="",
            on_error="skip",
            description="",
        )
        self._append_row(default_op)

    def _on_remove(self) -> None:
        """Удалить выделенную строку."""
        selected = self._table.currentRow()
        if selected >= 0:
            self._table.removeRow(selected)

    def _on_save(self) -> None:
        """Собрать каталог, провалидировать и сохранить в YAML."""
        if not self._catalog_path:
            self._show_error("Путь к каталогу не задан. Используйте set_catalog_path().")
            return

        catalog = self.get_catalog()
        if catalog is None:
            # get_catalog уже показал QMessageBox с ошибкой
            return

        try:
            save_catalog(self._catalog_path, catalog)
        except Exception as exc:
            self._show_error(f"Ошибка сохранения:\n{exc}")
            return

        self.catalog_changed.emit()

    # ------------------------------------------------------------------
    # Вспомогательные методы
    # ------------------------------------------------------------------

    def _append_row(self, op: ProcessingOperationDef) -> None:
        """Добавить строку в таблицу из ProcessingOperationDef."""
        row = self._table.rowCount()
        self._table.insertRow(row)

        self._table.setItem(row, _COL_NAME, QTableWidgetItem(op.name))
        self._table.setItem(row, _COL_TYPE_KEY, QTableWidgetItem(op.type_key))
        self._table.setItem(row, _COL_MODULE_PATH, QTableWidgetItem(op.module_path))
        self._table.setItem(row, _COL_PARAMS_SCHEMA, QTableWidgetItem(op.params_schema))
        self._table.setItem(row, _COL_DESCRIPTION, QTableWidgetItem(op.description))

        # on_error — выпадающий список
        combo = QComboBox()
        combo.addItems(_ON_ERROR_OPTIONS)
        idx = combo.findText(op.on_error)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        self._table.setCellWidget(row, _COL_ON_ERROR, combo)

    def _cell_text(self, row: int, col: int) -> str:
        """Получить текст ячейки или пустую строку."""
        item = self._table.item(row, col)
        return item.text().strip() if item else ""

    def _show_error(self, message: str) -> None:
        """Показать диалог с ошибкой валидации."""
        QMessageBox.critical(self, "Ошибка валидации", message)
