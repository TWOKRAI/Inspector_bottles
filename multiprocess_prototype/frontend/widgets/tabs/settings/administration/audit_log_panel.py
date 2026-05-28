# -*- coding: utf-8 -*-
"""AuditLogPanel — read-only панель просмотра аудит-лога.

Отображает таблицу записей AuditEntry из SqliteAuditStorage.
Поддерживает фильтры (пользователь, дата, ресурс), пагинацию (±100 записей)
и детальный просмотр по двойному клику.

Регистрируется как подсекция «Audit log» через фабрику в settings/_sections.py.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from html import escape
from typing import TYPE_CHECKING

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from Services.auth import AuditEntry

from multiprocess_prototype.frontend.widgets.tabs.settings.administration._formatters import (
    format_dt as _format_dt,
)

from ._base_panel import BaseAdminPanel

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.auth_context import AuthContext


class AuditLogPanel(BaseAdminPanel):
    """Read-only панель аудит-лога.

    Колонки: Время | Пользователь | Тип действия | Ресурс
    Фильтры: Пользователь (ComboBox), С / По (DateEdit), Ресурс (LineEdit).
    Пагинация: ← / → по 100 записей.
    Двойной клик → детальный QDialog с before/after_json.
    """

    _HEADER_TITLE = "Аудит-лог"
    _TABLE_COLUMNS = [
        ("ts", "Время", 300),
        ("username", "Пользователь", 110),
        ("action_type", "Тип действия", 120),
        ("resource", "Ресурс", 150),
    ]
    _PAGE_SIZE = 100

    def __init__(self, auth: "AuthContext | None", parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._storage = auth.audit if auth is not None else None
        self._auth_manager = auth.manager if auth is not None else None

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
        root = self._create_group()

        # Панель фильтров
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(8)

        filter_layout.addWidget(QLabel("Пользователь:"))
        self._combo_user = QComboBox()
        self._combo_user.setMinimumWidth(120)
        filter_layout.addWidget(self._combo_user)

        filter_layout.addWidget(QLabel("С:"))
        self._date_from = QDateEdit()
        self._date_from.setCalendarPopup(True)
        self._date_from.setDate(QDate.currentDate())
        filter_layout.addWidget(self._date_from)

        filter_layout.addWidget(QLabel("По:"))
        self._date_to = QDateEdit()
        self._date_to.setCalendarPopup(True)
        self._date_to.setDate(QDate.currentDate())
        filter_layout.addWidget(self._date_to)

        filter_layout.addWidget(QLabel("Ресурс:"))
        self._edit_resource = QLineEdit()
        self._edit_resource.setPlaceholderText("точное совпадение")
        self._edit_resource.setMinimumWidth(120)
        filter_layout.addWidget(self._edit_resource)

        filter_layout.addStretch()
        root.addLayout(filter_layout)

        # Таблица из BaseAdminPanel
        self._table = self._create_table()
        self._table.itemDoubleClicked.connect(self._on_row_double_clicked)

        root.addWidget(self._table, stretch=1)

        # Кнопки создаются здесь, но размещаются в action panel секции
        self._btn_apply = QPushButton("Применить")
        self._btn_apply.setToolTip("Применить фильтры")
        self._btn_apply.clicked.connect(lambda: self._load(offset=0))

        self._btn_reset_filter = QPushButton("Сбросить фильтр")
        self._btn_reset_filter.setToolTip("Сбросить все фильтры к значениям по умолчанию")
        self._btn_reset_filter.clicked.connect(self._on_reset_filter)

        self._btn_save_file = QPushButton("Сохранить в файл")
        self._btn_save_file.setToolTip("Экспортировать текущую страницу аудит-лога в CSV")
        self._btn_save_file.clicked.connect(self._on_save_to_file)

        self._btn_clear_all = QPushButton("Очистить всё")
        self._btn_clear_all.setToolTip("Очистить весь аудит-лог (необратимо)")
        self._btn_clear_all.clicked.connect(self._on_clear_all)

        # Пагинация
        pagination_layout = QHBoxLayout()
        pagination_layout.addStretch()

        self._btn_prev = QPushButton("←")
        self._btn_prev.setObjectName("PaginationArrow")
        self._btn_prev.setToolTip("Предыдущая страница")
        self._btn_prev.clicked.connect(self._on_prev_page)
        pagination_layout.addWidget(self._btn_prev)

        self._lbl_page = QLabel("Стр. 1")
        pagination_layout.addWidget(self._lbl_page)

        self._btn_next = QPushButton("→")
        self._btn_next.setObjectName("PaginationArrow")
        self._btn_next.setToolTip("Следующая страница")
        self._btn_next.clicked.connect(self._on_next_page)
        pagination_layout.addWidget(self._btn_next)

        pagination_layout.addStretch()
        root.addLayout(pagination_layout)

    def action_buttons(self) -> list[QPushButton]:
        """Кнопки действий для размещения в action panel секции."""
        return [
            self._btn_apply,
            self._btn_reset_filter,
            self._btn_save_file,
            self._btn_clear_all,
        ]

    # ------------------------------------------------------------------
    # Действия кнопок
    # ------------------------------------------------------------------

    def _on_reset_filter(self) -> None:
        """Сбросить все фильтры к значениям по умолчанию и перезагрузить."""
        self._combo_user.setCurrentIndex(0)  # «Все»
        self._date_from.setDate(QDate.currentDate())
        self._date_to.setDate(QDate.currentDate())
        self._edit_resource.clear()
        self._load(offset=0)

    def _on_save_to_file(self) -> None:
        """Экспортировать текущую страницу аудит-лога в CSV-файл."""
        if not self._entries:
            QMessageBox.information(self, "Экспорт", "Нет записей для экспорта.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Сохранить аудит-лог",
            "audit_log.csv",
            "CSV (*.csv);;Все файлы (*)",
        )
        if not path:
            return

        try:
            import csv

            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f, delimiter=";")
                writer.writerow(["Время", "Пользователь", "Тип действия", "Ресурс", "Комментарий"])
                for entry in self._entries:
                    writer.writerow(
                        [
                            _format_dt(entry.ts),
                            entry.username,
                            entry.action_type,
                            entry.resource or "",
                            entry.comment or "",
                        ]
                    )
            QMessageBox.information(self, "Экспорт", f"Сохранено {len(self._entries)} записей.")
        except Exception as exc:
            QMessageBox.critical(self, "Ошибка экспорта", str(exc))

    def _on_clear_all(self) -> None:
        """Очистить весь аудит-лог после подтверждения."""
        if self._storage is None:
            return

        reply = QMessageBox.warning(
            self,
            "Подтверждение очистки",
            "Очистить весь аудит-лог?\n\nЭто действие необратимо.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            self._storage.clear_audit()
        except Exception as exc:
            QMessageBox.critical(self, "Ошибка очистки", str(exc))
            return

        self._load(offset=0)

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
            uid = user.get("user_id", "")
            if username and uid:
                # Метка видна пользователю, userData — это user_id для фильтрации
                self._combo_user.addItem(username, userData=uid)

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
                _format_dt(entry.ts),
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

        # Основные поля — пользовательские данные экранируются html.escape
        # для защиты от HTML injection через поля записи аудита
        meta_lines = [
            f"<b>ID:</b> {escape(str(entry.entry_id))}",
            f"<b>Время:</b> {escape(str(entry.ts))}",
            f"<b>Пользователь:</b> {escape(entry.username)} ({escape(entry.user_id)})",
            f"<b>Тип действия:</b> {escape(entry.action_type)}",
            f"<b>Ресурс:</b> {escape(entry.resource) if entry.resource else '—'}",
            f"<b>Комментарий:</b> {escape(entry.comment) if entry.comment else '—'}",
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
