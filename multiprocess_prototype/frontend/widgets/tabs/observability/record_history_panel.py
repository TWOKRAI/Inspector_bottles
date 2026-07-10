# -*- coding: utf-8 -*-
"""
RecordHistoryPanel — переиспользуемая вкладка истории записей наблюдаемости (Ф5.19).

ОДИН виджет на три вкладки (Логи / Ошибки / Статистика) — каждый инстанс на свой
kind. Целую историю читает пагинацией из RecordSource (стор Ф5.20a), живой хвост
принимает методом ``append_live_records`` из hub→GUI-канала (Ф5.20b).

Переиспользует BaseAdminPanel (таблица/группа/read-only) — тот же паттерн, что
AuditLogPanel; отличия: фильтр по уровню, колонка источник/канал, кнопка
Копировать, live-append (аудит-лог статичен, наблюдаемость течёт).
"""

from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..settings.administration._base_panel import BaseAdminPanel
from .record_history_presenter import RecordHistoryPresenter
from .record_source import RecordSource

# Опции фильтра уровня по kind. stats → None (severity=metric_type, фильтр скрыт).
LEVEL_OPTIONS = {
    "log": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    "error": ["ERROR", "CRITICAL"],
}


def _format_ts(ts: Any) -> str:
    """float epoch → 'YYYY-MM-DD HH:MM:SS.mmm'; мусор/0 → '—'."""
    try:
        val = float(ts)
    except (TypeError, ValueError):
        return "—"
    if val <= 0:
        return "—"
    try:
        return datetime.fromtimestamp(val).strftime("%Y-%m-%d %H:%M:%S.") + f"{int((val % 1) * 1000):03d}"
    except (ValueError, OverflowError, OSError):
        return "—"


class RecordHistoryPanel(BaseAdminPanel):
    """Read-only вкладка истории одного kind: история из стора + живой хвост."""

    _TABLE_COLUMNS = [
        ("ts", "Время", 190),
        ("severity", "Уровень", 90),
        ("module", "Источник", 150),
        ("message", "Сообщение", 300),
    ]
    _MAX_LIVE_ROWS = 500  # верхний предел отображаемых строк при live-append

    def __init__(
        self,
        source: Optional[RecordSource],
        kind: str,
        *,
        title: str = "",
        page_size: int = 100,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._HEADER_TITLE = title or kind.capitalize()
        self._presenter = RecordHistoryPresenter(source, kind, page_size=page_size)
        self._rows: List[Dict[str, Any]] = []
        self._setup_ui()
        self.reload()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        root = self._create_group()

        # Фильтры: уровень (если применим) + источник.
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(8)

        self._combo_level: QComboBox | None = None
        level_options = LEVEL_OPTIONS.get(self._presenter.kind)
        if level_options:
            filter_layout.addWidget(QLabel("Уровень:"))
            self._combo_level = QComboBox()
            self._combo_level.addItem("Все", userData=None)
            for lvl in level_options:
                self._combo_level.addItem(lvl, userData=lvl)
            self._combo_level.currentIndexChanged.connect(self._on_filters_changed)
            filter_layout.addWidget(self._combo_level)

        filter_layout.addWidget(QLabel("Источник:"))
        self._edit_module = QLineEdit()
        self._edit_module.setPlaceholderText("модуль (точное совпадение)")
        self._edit_module.setMinimumWidth(140)
        self._edit_module.returnPressed.connect(self._on_filters_changed)
        filter_layout.addWidget(self._edit_module)

        filter_layout.addStretch()
        root.addLayout(filter_layout)

        # Таблица.
        self._table = self._create_table()
        self._table.itemDoubleClicked.connect(self._on_row_double_clicked)
        root.addWidget(self._table, stretch=1)

        # Кнопки: Обновить / Копировать / Очистить.
        self._btn_reload = QPushButton("Обновить")
        self._btn_reload.setToolTip("Перечитать историю из стора")
        self._btn_reload.clicked.connect(self.reload)

        self._btn_copy = QPushButton("Копировать")
        self._btn_copy.setToolTip("Скопировать видимые записи в буфер обмена")
        self._btn_copy.clicked.connect(self._on_copy)

        self._btn_clear = QPushButton("Очистить")
        self._btn_clear.setToolTip("Очистить историю этой вкладки (необратимо)")
        self._btn_clear.clicked.connect(self._on_clear)

        # Пагинация ← / → + метка страницы.
        pagination_layout = QHBoxLayout()
        pagination_layout.addWidget(self._btn_reload)
        pagination_layout.addWidget(self._btn_copy)
        pagination_layout.addWidget(self._btn_clear)
        pagination_layout.addStretch()

        self._btn_prev = QPushButton("←")
        self._btn_prev.setObjectName("PaginationArrow")
        self._btn_prev.clicked.connect(self._on_prev_page)
        pagination_layout.addWidget(self._btn_prev)

        self._lbl_page = QLabel("Стр. 1")
        pagination_layout.addWidget(self._lbl_page)

        self._btn_next = QPushButton("→")
        self._btn_next.setObjectName("PaginationArrow")
        self._btn_next.clicked.connect(self._on_next_page)
        pagination_layout.addWidget(self._btn_next)

        pagination_layout.addStretch()
        root.addLayout(pagination_layout)

    # ------------------------------------------------------------------
    # Фильтры / загрузка
    # ------------------------------------------------------------------

    def _on_filters_changed(self) -> None:
        if self._combo_level is not None:
            level = self._combo_level.currentData()
            self._presenter.set_level_filter([level] if level else None)
        self._presenter.set_module_filter(self._edit_module.text())
        self.reload()

    def reload(self) -> None:
        """Перечитать текущую страницу истории и заполнить таблицу."""
        self._rows = self._presenter.load()
        self._fill_table(self._rows)
        self._update_pagination()

    def _fill_table(self, rows: List[Dict[str, Any]]) -> None:
        self._table.setRowCount(len(rows))
        for r, rec in enumerate(rows):
            self._set_row(r, rec)

    def _set_row(self, row: int, rec: Dict[str, Any]) -> None:
        cells = [
            _format_ts(rec.get("ts")),
            str(rec.get("severity", "") or "—"),
            str(rec.get("module", "") or "—"),
            str(rec.get("message", "") or ""),
        ]
        for col, text in enumerate(cells):
            item = QTableWidgetItem(text)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row, col, item)

    # ------------------------------------------------------------------
    # Живой хвост (Ф5.20b)
    # ------------------------------------------------------------------

    def append_live_records(self, records: List[Dict[str, Any]]) -> int:
        """Добавить live-записи хвоста (свежие — сверху). Возвращает число добавленных.

        Только на первой странице (иначе перемешали бы пагинацию) и только
        подходящие под kind+фильтры вкладки. Ограничение _MAX_LIVE_ROWS: старые
        строки снизу отбрасываются (drop_oldest — как в bounded-каналах hub'а).
        """
        if not self._presenter.on_first_page:
            return 0
        fresh = [rec for rec in records if self._presenter.matches_live(rec)]
        if not fresh:
            return 0
        # Свежие сверху. Инкрементально (O(fresh), не O(всей таблицы)): вставляем
        # строки в начало таблицы, не пересоздавая её целиком — под busy-хвостом
        # полный rebuild на каждый батч давал бы GUI-jank.
        self._rows = fresh + self._rows
        self._table.setUpdatesEnabled(False)
        try:
            for i, rec in enumerate(fresh):
                self._table.insertRow(i)
                self._set_row(i, rec)
            # drop_oldest: обрезаем хвост модели И таблицы до _MAX_LIVE_ROWS.
            while len(self._rows) > self._MAX_LIVE_ROWS:
                self._rows.pop()
                self._table.removeRow(self._table.rowCount() - 1)
        finally:
            self._table.setUpdatesEnabled(True)
        # Пагинация зависит от числа строк (has_next) — держим кнопки честными.
        self._update_pagination()
        return len(fresh)

    # ------------------------------------------------------------------
    # Кнопки
    # ------------------------------------------------------------------

    def _on_copy(self) -> None:
        """Скопировать видимые записи (TSV) в буфер обмена."""
        from PySide6.QtWidgets import QApplication

        lines = ["\t".join(c[1] for c in self._TABLE_COLUMNS)]
        for rec in self._rows:
            lines.append(
                "\t".join(
                    [
                        _format_ts(rec.get("ts")),
                        str(rec.get("severity", "")),
                        str(rec.get("module", "")),
                        str(rec.get("message", "")),
                    ]
                )
            )
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText("\n".join(lines))

    def _on_clear(self) -> None:
        self._presenter.clear()
        self.reload()

    # ------------------------------------------------------------------
    # Пагинация
    # ------------------------------------------------------------------

    def _on_prev_page(self) -> None:
        if self._presenter.has_prev:
            self._presenter.prev_page()
            self.reload()

    def _on_next_page(self) -> None:
        if self._presenter.has_next(self._rows):
            self._presenter.next_page()
            self.reload()

    def _update_pagination(self) -> None:
        self._lbl_page.setText(f"Стр. {self._presenter.page_number}")
        self._btn_prev.setEnabled(self._presenter.has_prev)
        self._btn_next.setEnabled(self._presenter.has_next(self._rows))

    # ------------------------------------------------------------------
    # Детальный просмотр
    # ------------------------------------------------------------------

    def _on_row_double_clicked(self, item: QTableWidgetItem) -> None:
        row = item.row()
        if 0 <= row < len(self._rows):
            _RecordDetailDialog(self._rows[row], parent=self).exec()


class _RecordDetailDialog(QDialog):
    """QDialog с полным содержимым записи (включая extra/context/traceback)."""

    def __init__(self, record: Dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Детали записи")
        self.setMinimumSize(520, 360)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        meta = [
            f"<b>Время:</b> {escape(_format_ts(record.get('ts')))}",
            f"<b>Kind:</b> {escape(str(record.get('kind', '')))}",
            f"<b>Уровень:</b> {escape(str(record.get('severity', '')))}",
            f"<b>Источник:</b> {escape(str(record.get('module', '')))}",
            f"<b>Сообщение:</b> {escape(str(record.get('message', '')))}",
        ]
        for line in meta:
            lbl = QLabel(line)
            lbl.setTextFormat(Qt.TextFormat.RichText)
            lbl.setWordWrap(True)
            layout.addWidget(lbl)

        layout.addWidget(QLabel("<b>extra:</b>"))
        extra_edit = QTextEdit()
        extra_edit.setReadOnly(True)
        import json

        try:
            extra_text = json.dumps(record.get("extra", {}), ensure_ascii=False, indent=2, default=str)
        except (TypeError, ValueError):
            extra_text = str(record.get("extra", {}))
        extra_edit.setPlainText(extra_text)
        layout.addWidget(extra_edit)

        btn_close = QPushButton("Закрыть")
        btn_close.clicked.connect(self.accept)
        h = QHBoxLayout()
        h.addStretch()
        h.addWidget(btn_close)
        layout.addLayout(h)
