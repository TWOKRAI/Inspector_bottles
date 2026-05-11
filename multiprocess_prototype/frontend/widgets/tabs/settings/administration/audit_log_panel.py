# -*- coding: utf-8 -*-
"""AuditLogPanel — read-only панель просмотра аудит-лога.

Отображает таблицу записей AuditEntry из SqliteAuditStorage.
Поддерживает фильтры (пользователь, дата, ресурс), пагинацию (±100 записей)
и детальный просмотр по двойному клику.

Используется как подсекция «Audit log» в AdministrationSection.
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import TYPE_CHECKING

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from Services.auth import AuditEntry

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.app_context import AppContext


class AuditLogPanel(QWidget):
    """Read-only панель аудит-лога.

    Колонки: Время | Пользователь | Тип действия | Ресурс
    Фильтры: Пользователь (ComboBox), С / По (DateEdit), Ресурс (LineEdit).
    Пагинация: ← / → по 100 записей.
    Двойной клик → детальный QDialog с before/after_json.
    """

    _TABLE_COLUMNS = [
        ("ts",          "Время",         150),
        ("username",    "Пользователь",  130),
        ("action_type", "Тип действия",  140),
        ("resource",    "Ресурс",        150),
    ]
    _PAGE_SIZE = 100

    def __init__(self, ctx: "AppContext", parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._ctx = ctx
        self._storage = ctx.audit_storage()
        self._auth_manager = ctx.auth_manager()

        self._offset: int = 0
        self._entries: list[AuditEntry] = []

        self._setup_ui()
        self._populate_user_filter()
        self._load(offset=0)

    # ------------------------------------------------------------------
    # Построение UI
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """Построить layout панели."""
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # Заголовок
        header_label = QLabel("Audit log")
        font = header_label.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 2)
        header_label.setFont(font)
        root.addWidget(header_label)

        # Панель фильтров
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(8)

        # Фильтр по пользователю
        filter_layout.addWidget(QLabel("Пользователь:"))
        self._combo_user = QComboBox()
        self._combo_user.setMinimumWidth(120)
        filter_layout.addWidget(self._combo_user)

        # Фильтр «С»
        filter_layout.addWidget(QLabel("С:"))
        self._date_from = QDateEdit()
        self._date_from.setCalendarPopup(True)
        self._date_from.setDate(QDate.currentDate())
        filter_layout.addWidget(self._date_from)

        # Фильтр «По»
        filter_layout.addWidget(QLabel("По:"))
        self._date_to = QDateEdit()
        self._date_to.setCalendarPopup(True)
        self._date_to.setDate(QDate.currentDate())
        filter_layout.addWidget(self._date_to)

        # Фильтр по ресурсу
        filter_layout.addWidget(QLabel("Ресурс:"))
        self._edit_resource = QLineEdit()
        self._edit_resource.setPlaceholderText("точное совпадение")
        self._edit_resource.setMinimumWidth(120)
        filter_layout.addWidget(self._edit_resource)

        # Кнопка применить
        self._btn_apply = QPushButton("Применить")
        self._btn_apply.setFixedWidth(90)
        self._btn_apply.clicked.connect(lambda: self._load(offset=0))
        filter_layout.addWidget(self._btn_apply)

        filter_layout.addStretch()
        root.addLayout(filter_layout)

        # Таблица
        self._table = QTableWidget(0, len(self._TABLE_COLUMNS))
        self._table.setHorizontalHeaderLabels(
            [col[1] for col in self._TABLE_COLUMNS]
        )
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.itemDoubleClicked.connect(self._on_row_double_clicked)

        h = self._table.horizontalHeader()
        for i, (_, _, width) in enumerate(self._TABLE_COLUMNS):
            if i == len(self._TABLE_COLUMNS) - 1:
                h.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
            else:
                self._table.setColumnWidth(i, width)
                h.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)

        root.addWidget(self._table, stretch=1)

        # Пагинация
        pagination_layout = QHBoxLayout()
        pagination_layout.addStretch()

        self._btn_prev = QPushButton("←")
        self._btn_prev.setFixedWidth(40)
        self._btn_prev.setToolTip("Предыдущая страница")
        self._btn_prev.clicked.connect(self._on_prev_page)
        pagination_layout.addWidget(self._btn_prev)

        self._lbl_page = QLabel("Стр. 1")
        pagination_layout.addWidget(self._lbl_page)

        self._btn_next = QPushButton("→")
        self._btn_next.setFixedWidth(40)
        self._btn_next.setToolTip("Следующая страница")
        self._btn_next.clicked.connect(self._on_next_page)
        pagination_layout.addWidget(self._btn_next)

        pagination_layout.addStretch()
        root.addLayout(pagination_layout)

    # ------------------------------------------------------------------
    # Фильтры
    # ------------------------------------------------------------------

    def _populate_user_filter(self) -> None:
        """Заполнить ComboBox пользователей из auth_manager.list_users()."""
        self._combo_user.clear()
        self._combo_user.addItem("Все", userData=None)

        if self._auth_manager is None:
            return

        try:
            users = self._auth_manager.list_users()
        except Exception:
            return

        for user in users:
            username = user.get("username", "")
            if username:
                self._combo_user.addItem(username, userData=username)

    # ------------------------------------------------------------------
    # Загрузка данных
    # ------------------------------------------------------------------

    def _load(self, offset: int = 0) -> None:
        """Загрузить записи аудита с текущими фильтрами."""
        self._offset = offset

        if self._storage is None:
            return

        # Читаем фильтры
        selected_user = self._combo_user.currentData()  # None → «Все»
        resource_text = self._edit_resource.text().strip() or None

        # Конвертируем QDate → datetime
        from_dt = self._qdate_to_datetime(self._date_from.date(), start_of_day=True)
        to_dt = self._qdate_to_datetime(self._date_to.date(), start_of_day=False)

        try:
            self._entries = self._storage.list_audit(
                user_id=selected_user,
                resource=resource_text,
                from_dt=from_dt,
                to_dt=to_dt,
                limit=self._PAGE_SIZE,
                offset=self._offset,
            )
        except Exception:
            self._entries = []

        self._fill_table()
        self._update_pagination_label()

    def _fill_table(self) -> None:
        """Заполнить таблицу из self._entries."""
        self._table.setRowCount(len(self._entries))
        for row, entry in enumerate(self._entries):
            cells = [
                self._format_dt(entry.ts),
                entry.username,
                entry.action_type,
                entry.resource or "—",
            ]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._table.setItem(row, col, item)

    # ------------------------------------------------------------------
    # Пагинация
    # ------------------------------------------------------------------

    def _on_prev_page(self) -> None:
        """Перейти на предыдущую страницу (offset -= PAGE_SIZE, min=0)."""
        new_offset = max(0, self._offset - self._PAGE_SIZE)
        if new_offset != self._offset:
            self._load(offset=new_offset)

    def _on_next_page(self) -> None:
        """Перейти на следующую страницу (offset += PAGE_SIZE)."""
        self._load(offset=self._offset + self._PAGE_SIZE)

    def _update_pagination_label(self) -> None:
        """Обновить метку текущей страницы."""
        page = self._offset // self._PAGE_SIZE + 1
        self._lbl_page.setText(f"Стр. {page}")

        # Отключить «←» на первой странице
        self._btn_prev.setEnabled(self._offset > 0)
        # Отключить «→» если получили меньше PAGE_SIZE записей
        self._btn_next.setEnabled(len(self._entries) >= self._PAGE_SIZE)

    # ------------------------------------------------------------------
    # Детальный просмотр
    # ------------------------------------------------------------------

    def _on_row_double_clicked(self, item: QTableWidgetItem) -> None:
        """Открыть диалог с полным содержимым записи."""
        row = item.row()
        if row < 0 or row >= len(self._entries):
            return
        entry = self._entries[row]
        self._open_detail_dialog(entry)

    def _open_detail_dialog(self, entry: AuditEntry) -> None:
        """Открыть QDialog с полным содержимым AuditEntry."""
        dlg = _AuditDetailDialog(entry, parent=self)
        dlg.exec()

    # ------------------------------------------------------------------
    # Форматирование
    # ------------------------------------------------------------------

    @staticmethod
    def _format_dt(value: datetime | None) -> str:
        """Отформатировать datetime для отображения в таблице."""
        if value is None:
            return "—"
        val_str = str(value)
        if "T" in val_str:
            parts = val_str.split("T")
            date_part = parts[0]
            time_part = parts[1].split(".")[0] if len(parts) > 1 else ""
            return f"{date_part} {time_part}".strip()
        return val_str

    @staticmethod
    def _qdate_to_datetime(qdate: QDate, *, start_of_day: bool) -> datetime:
        """Конвертировать QDate в datetime (UTC).

        start_of_day=True  → 00:00:00 UTC (нижняя граница)
        start_of_day=False → 23:59:59 UTC (верхняя граница)
        """
        py_date = date(qdate.year(), qdate.month(), qdate.day())
        if start_of_day:
            t = time(0, 0, 0)
        else:
            t = time(23, 59, 59)
        return datetime.combine(py_date, t, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Вспомогательный диалог детального просмотра
# ---------------------------------------------------------------------------


class _AuditDetailDialog(QDialog):
    """QDialog с полным содержимым записи аудита.

    Показывает все поля записи, а также before_json / after_json
    в read-only QTextEdit.
    """

    def __init__(self, entry: AuditEntry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Детали записи аудита")
        self.setMinimumSize(520, 400)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Основные поля
        meta_lines = [
            f"<b>ID:</b> {entry.entry_id}",
            f"<b>Время:</b> {entry.ts}",
            f"<b>Пользователь:</b> {entry.username} ({entry.user_id})",
            f"<b>Тип действия:</b> {entry.action_type}",
            f"<b>Ресурс:</b> {entry.resource or '—'}",
            f"<b>Комментарий:</b> {entry.comment or '—'}",
        ]
        for line in meta_lines:
            lbl = QLabel(line)
            lbl.setTextFormat(Qt.TextFormat.RichText)
            lbl.setWordWrap(True)
            layout.addWidget(lbl)

        # before_json
        layout.addWidget(QLabel("<b>Состояние до (before_json):</b>"))
        before_edit = QTextEdit()
        before_edit.setReadOnly(True)
        before_edit.setPlainText(entry.before_json or "")
        before_edit.setMaximumHeight(100)
        layout.addWidget(before_edit)

        # after_json
        layout.addWidget(QLabel("<b>Состояние после (after_json):</b>"))
        after_edit = QTextEdit()
        after_edit.setReadOnly(True)
        after_edit.setPlainText(entry.after_json or "")
        after_edit.setMaximumHeight(100)
        layout.addWidget(after_edit)

        # Кнопка закрыть
        btn_close = QPushButton("Закрыть")
        btn_close.clicked.connect(self.accept)
        h_layout = QHBoxLayout()
        h_layout.addStretch()
        h_layout.addWidget(btn_close)
        layout.addLayout(h_layout)
