# -*- coding: utf-8 -*-
"""Тесты AuditLogPanel — PR4 Group C.

Проверяет:
  - test_panel_loads_audit   — таблица заполняется из storage.list_audit()
  - test_filter_applies      — кнопка «Применить» передаёт фильтры в list_audit()
  - test_pagination_next     — кнопка «→» увеличивает offset на 100
  - test_detail_dialog_opens — двойной клик открывает _AuditDetailDialog
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt

from multiprocess_prototype.frontend.widgets.tabs.settings.administration.audit_log_panel import (
    AuditLogPanel,
    _AuditDetailDialog,
)

# ---------------------------------------------------------------------------
# Вспомогательные данные
# ---------------------------------------------------------------------------

_DT_NOW = datetime(2026, 5, 11, 12, 0, 0, tzinfo=timezone.utc)


def _make_entry(
    username: str = "alice",
    action_type: str = "field_update",
    resource: str | None = "settings.fps",
    before_json: str | None = None,
    after_json: str | None = None,
):
    """Создать mock AuditEntry с нужными полями."""
    entry = MagicMock()
    entry.entry_id = "e1"
    entry.ts = _DT_NOW
    entry.user_id = "u-alice"
    entry.username = username
    entry.action_type = action_type
    entry.resource = resource
    entry.before_json = before_json
    entry.after_json = after_json
    entry.comment = ""
    return entry


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_storage():
    """Мок SqliteAuditStorage с пустым list_audit по умолчанию."""
    storage = MagicMock()
    storage.list_audit.return_value = []
    return storage


@pytest.fixture
def mock_auth_manager():
    """Мок IAuthManager с пустым list_users по умолчанию."""
    mgr = MagicMock()
    mgr.list_users.return_value = []
    return mgr


@pytest.fixture
def mock_ctx(mock_storage, mock_auth_manager):
    """Мок AuthContext: audit = mock_storage, manager = mock_auth_manager."""
    ctx = MagicMock()
    ctx.audit = mock_storage
    ctx.manager = mock_auth_manager
    ctx.state = None
    return ctx


# ---------------------------------------------------------------------------
# test_panel_loads_audit
# ---------------------------------------------------------------------------


class TestAuditLogPanelLoadAudit:
    """Таблица заполняется из list_audit()."""

    def test_panel_loads_audit_two_rows(self, qtbot, mock_ctx, mock_storage):
        """При list_audit() с 2 записями таблица содержит 2 строки."""
        mock_storage.list_audit.return_value = [
            _make_entry("alice"),
            _make_entry("bob", action_type="login"),
        ]

        panel = AuditLogPanel(mock_ctx)
        qtbot.addWidget(panel)

        assert panel._table.rowCount() == 2

    def test_panel_loads_audit_empty(self, qtbot, mock_ctx, mock_storage):
        """При пустом list_audit() таблица содержит 0 строк."""
        mock_storage.list_audit.return_value = []

        panel = AuditLogPanel(mock_ctx)
        qtbot.addWidget(panel)

        assert panel._table.rowCount() == 0

    def test_panel_loads_audit_first_cell_time(self, qtbot, mock_ctx, mock_storage):
        """Первая ячейка первой строки — отформатированное время записи."""
        mock_storage.list_audit.return_value = [_make_entry("alice")]

        panel = AuditLogPanel(mock_ctx)
        qtbot.addWidget(panel)

        item = panel._table.item(0, 0)
        assert item is not None
        # Время должно содержать хотя бы дату
        assert "2026" in item.text()

    def test_panel_calls_list_audit_on_init(self, qtbot, mock_ctx, mock_storage):
        """list_audit вызывается при создании панели."""
        panel = AuditLogPanel(mock_ctx)
        qtbot.addWidget(panel)

        mock_storage.list_audit.assert_called()


# ---------------------------------------------------------------------------
# test_filter_applies
# ---------------------------------------------------------------------------


class TestAuditLogPanelFilterApplies:
    """Кнопка «Применить» передаёт фильтры в list_audit()."""

    def test_filter_applies_resets_offset(self, qtbot, mock_ctx, mock_storage):
        """Нажатие «Применить» сбрасывает offset до 0."""
        panel = AuditLogPanel(mock_ctx)
        qtbot.addWidget(panel)

        # Симулируем непустой offset
        panel._offset = 200

        qtbot.mouseClick(panel._btn_apply, Qt.MouseButton.LeftButton)

        assert panel._offset == 0

    def test_filter_applies_calls_list_audit(self, qtbot, mock_ctx, mock_storage):
        """После «Применить» list_audit вызывается заново."""
        panel = AuditLogPanel(mock_ctx)
        qtbot.addWidget(panel)

        mock_storage.list_audit.reset_mock()

        qtbot.mouseClick(panel._btn_apply, Qt.MouseButton.LeftButton)

        mock_storage.list_audit.assert_called_once()

    def test_filter_resource_text_passed_to_list_audit(self, qtbot, mock_ctx, mock_storage):
        """Текст из поля «Ресурс» передаётся как resource= в list_audit."""
        panel = AuditLogPanel(mock_ctx)
        qtbot.addWidget(panel)

        panel._edit_resource.setText("settings.fps")
        mock_storage.list_audit.reset_mock()

        panel._load(offset=0)

        call_kwargs = mock_storage.list_audit.call_args[1]
        assert call_kwargs.get("resource") == "settings.fps"

    def test_filter_empty_resource_passes_none(self, qtbot, mock_ctx, mock_storage):
        """Пустое поле «Ресурс» → resource=None в list_audit."""
        panel = AuditLogPanel(mock_ctx)
        qtbot.addWidget(panel)

        panel._edit_resource.setText("")
        mock_storage.list_audit.reset_mock()

        panel._load(offset=0)

        call_kwargs = mock_storage.list_audit.call_args[1]
        assert call_kwargs.get("resource") is None


# ---------------------------------------------------------------------------
# test_pagination_next
# ---------------------------------------------------------------------------


class TestAuditLogPanelPaginationNext:
    """Кнопка «→» увеличивает offset на PAGE_SIZE (100)."""

    def test_pagination_next_increases_offset(self, qtbot, mock_ctx, mock_storage):
        """После «→» offset увеличивается на 100."""
        # Возвращаем полную страницу, чтобы кнопка «→» была enabled
        mock_storage.list_audit.return_value = [_make_entry() for _ in range(100)]

        panel = AuditLogPanel(mock_ctx)
        qtbot.addWidget(panel)

        assert panel._offset == 0

        qtbot.mouseClick(panel._btn_next, Qt.MouseButton.LeftButton)

        assert panel._offset == 100

    def test_pagination_next_twice(self, qtbot, mock_ctx, mock_storage):
        """Два нажатия «→» → offset = 200."""
        mock_storage.list_audit.return_value = [_make_entry() for _ in range(100)]

        panel = AuditLogPanel(mock_ctx)
        qtbot.addWidget(panel)

        qtbot.mouseClick(panel._btn_next, Qt.MouseButton.LeftButton)
        qtbot.mouseClick(panel._btn_next, Qt.MouseButton.LeftButton)

        assert panel._offset == 200

    def test_pagination_prev_decreases_offset(self, qtbot, mock_ctx, mock_storage):
        """После «←» offset уменьшается на 100 (не ниже 0)."""
        mock_storage.list_audit.return_value = [_make_entry() for _ in range(100)]

        panel = AuditLogPanel(mock_ctx)
        qtbot.addWidget(panel)

        # Установим offset вручную
        panel._offset = 200
        panel._btn_prev.setEnabled(True)

        qtbot.mouseClick(panel._btn_prev, Qt.MouseButton.LeftButton)

        assert panel._offset == 100

    def test_pagination_prev_at_zero_stays_zero(self, qtbot, mock_ctx, mock_storage):
        """«←» при offset=0 не делает offset отрицательным."""
        mock_storage.list_audit.return_value = []

        panel = AuditLogPanel(mock_ctx)
        qtbot.addWidget(panel)

        panel._offset = 0
        panel._btn_prev.setEnabled(True)

        panel._on_prev_page()

        assert panel._offset == 0


# ---------------------------------------------------------------------------
# test_detail_dialog_opens
# ---------------------------------------------------------------------------


class TestAuditLogPanelDetailDialog:
    """Двойной клик по строке открывает детальный диалог."""

    def test_detail_dialog_opens_on_double_click(self, qtbot, mock_ctx, mock_storage, monkeypatch):
        """_open_detail_dialog вызывается при двойном клике по строке."""
        mock_storage.list_audit.return_value = [_make_entry("alice")]

        panel = AuditLogPanel(mock_ctx)
        qtbot.addWidget(panel)

        opened_dialogs: list = []

        def fake_open_detail(entry):
            opened_dialogs.append(entry)

        monkeypatch.setattr(panel, "_open_detail_dialog", fake_open_detail)

        # Эмулируем двойной клик по первой ячейке
        item = panel._table.item(0, 0)
        assert item is not None
        panel._on_row_double_clicked(item)

        assert len(opened_dialogs) == 1

    def test_detail_dialog_shows_before_json(self, qtbot, mock_storage):
        """_AuditDetailDialog отображает before_json в read-only QTextEdit."""
        entry = _make_entry(before_json='{"fps": 25}', after_json='{"fps": 30}')

        dlg = _AuditDetailDialog(entry)
        qtbot.addWidget(dlg)

        # Найдём QTextEdit с before_json
        text_edits = dlg.findChildren(__import__("PySide6.QtWidgets", fromlist=["QTextEdit"]).QTextEdit)
        texts = [te.toPlainText() for te in text_edits]
        assert '{"fps": 25}' in texts

    def test_detail_dialog_shows_after_json(self, qtbot, mock_storage):
        """_AuditDetailDialog отображает after_json в read-only QTextEdit."""
        entry = _make_entry(before_json='{"fps": 25}', after_json='{"fps": 30}')

        dlg = _AuditDetailDialog(entry)
        qtbot.addWidget(dlg)

        text_edits = dlg.findChildren(__import__("PySide6.QtWidgets", fromlist=["QTextEdit"]).QTextEdit)
        texts = [te.toPlainText() for te in text_edits]
        assert '{"fps": 30}' in texts

    def test_detail_dialog_row_out_of_range(self, qtbot, mock_ctx, mock_storage):
        """Двойной клик при пустой таблице не вызывает ошибку."""
        mock_storage.list_audit.return_value = []

        panel = AuditLogPanel(mock_ctx)
        qtbot.addWidget(panel)

        # Создаём item с невалидным row (не добавлен в таблицу)
        from PySide6.QtWidgets import QTableWidgetItem

        item = QTableWidgetItem("x")
        # row() вернёт -1 для item'а не в таблице → _on_row_double_clicked должен молча выйти
        panel._on_row_double_clicked(item)
        # Нет исключений — тест пройден


# ---------------------------------------------------------------------------
# Новые тесты по замечаниям ревьюера
# ---------------------------------------------------------------------------


class TestAuditLogPanelUserIdFilter:
    """ComboBox хранит user_id, а не username — фильтр передаёт правильное значение."""

    def test_user_filter_passes_user_id_not_username(self, qtbot, mock_storage, mock_auth_manager):
        """После выбора пользователя в ComboBox list_audit вызывается с user_id, не username."""
        # Настраиваем auth_manager с одним пользователем
        mock_auth_manager.list_users.return_value = [
            {"username": "alice", "user_id": "u-alice"},
        ]

        ctx = MagicMock()
        ctx.audit = mock_storage
        ctx.manager = mock_auth_manager
        ctx.state = None

        panel = AuditLogPanel(ctx)
        qtbot.addWidget(panel)

        # Выбираем элемент «alice» (индекс 1, так как 0 — «Все»)
        panel._combo_user.setCurrentIndex(1)
        mock_storage.list_audit.reset_mock()

        panel._load(offset=0)

        call_kwargs = mock_storage.list_audit.call_args[1]
        # Должен передаваться user_id «u-alice», а не username «alice»
        assert call_kwargs.get("user_id") == "u-alice"
        assert call_kwargs.get("user_id") != "alice"

    def test_user_filter_all_passes_none(self, qtbot, mock_storage, mock_auth_manager):
        """Выбор «Все» (индекс 0) → user_id=None в list_audit."""
        mock_auth_manager.list_users.return_value = [
            {"username": "alice", "user_id": "u-alice"},
        ]

        ctx = MagicMock()
        ctx.audit = mock_storage
        ctx.manager = mock_auth_manager
        ctx.state = None

        panel = AuditLogPanel(ctx)
        qtbot.addWidget(panel)

        # «Все» — индекс 0
        panel._combo_user.setCurrentIndex(0)
        mock_storage.list_audit.reset_mock()

        panel._load(offset=0)

        call_kwargs = mock_storage.list_audit.call_args[1]
        assert call_kwargs.get("user_id") is None


class TestAuditDetailDialogEscapesHtml:
    """_AuditDetailDialog экранирует HTML в пользовательских данных."""

    def test_detail_dialog_escapes_html_in_username(self, qtbot):
        """username с HTML-тегами рендерится как escape-последовательности, не разметка."""
        entry = _make_entry(username="<script>alert(1)</script>")
        entry.user_id = "<b>uid</b>"
        entry.action_type = "<i>action</i>"
        entry.resource = "<em>res</em>"
        entry.comment = "<u>note</u>"

        dlg = _AuditDetailDialog(entry)
        qtbot.addWidget(dlg)

        from PySide6.QtWidgets import QLabel

        labels = dlg.findChildren(QLabel)
        all_text = " ".join(lbl.text() for lbl in labels)

        # Escaped-версии должны присутствовать
        assert "&lt;script&gt;" in all_text
        assert "&lt;b&gt;" in all_text
        assert "&lt;i&gt;" in all_text
        assert "&lt;em&gt;" in all_text
        assert "&lt;u&gt;" in all_text

        # Сырые теги не должны присутствовать как теги (не как текст)
        # Проверяем что сырые строки тегов НЕ встречаются
        assert "<script>" not in all_text
        assert "<b>uid</b>" not in all_text

    def test_detail_dialog_normal_text_unchanged(self, qtbot):
        """Обычный текст без HTML не искажается escape."""
        entry = _make_entry(username="alice", action_type="field_update", resource="settings.fps")
        entry.comment = "обычный комментарий"

        dlg = _AuditDetailDialog(entry)
        qtbot.addWidget(dlg)

        from PySide6.QtWidgets import QLabel

        labels = dlg.findChildren(QLabel)
        all_text = " ".join(lbl.text() for lbl in labels)

        assert "alice" in all_text
        assert "field_update" in all_text
        assert "settings.fps" in all_text
