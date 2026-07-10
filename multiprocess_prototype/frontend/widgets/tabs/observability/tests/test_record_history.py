# -*- coding: utf-8 -*-
"""Тесты вкладок наблюдаемости Логи/Ошибки/Статистика (Ф5.19).

Presenter — Qt-free (пагинация/фильтры/live-match); панель и 3 вкладки —
widget-level (pytest-qt) с fake-стором и live-append.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest


class FakeSource:
    """In-memory RecordSource: список dict-записей, пагинация+фильтры как в сторе."""

    def __init__(self, records: Optional[List[Dict[str, Any]]] = None) -> None:
        # Храним в порядке вставки; newest_first → разворачиваем при чтении.
        self.records = list(records or [])

    def list_records(self, kind=None, module=None, severity_in=None, offset=0, limit=100, newest_first=True):
        rows = [r for r in self.records if kind is None or r.get("kind") == kind]
        if module is not None:
            rows = [r for r in rows if r.get("module") == module]
        if severity_in:
            allowed = {s.lower() for s in severity_in}
            rows = [r for r in rows if str(r.get("severity", "")).lower() in allowed]
        if newest_first:
            rows = list(reversed(rows))
        return rows[offset : offset + limit]

    def count(self, kind=None):
        return len([r for r in self.records if kind is None or r.get("kind") == kind])

    def clear(self, kind=None):
        before = len(self.records)
        self.records = [r for r in self.records if kind is not None and r.get("kind") != kind]
        return before - len(self.records)


def _rec(kind, message, module="worker", severity="info", ts=1.0, process=None):
    rec = {"kind": kind, "module": module, "ts": ts, "severity": severity, "message": message, "extra": {}}
    if process is not None:
        rec["process"] = process
    return rec


# Индексы колонок панели (5.21 (c) добавил «Процесс» между «Уровень» и «Источник»).
_COL_PROCESS = 2
_COL_MODULE = 3
_COL_MESSAGE = 4


# ===========================================================================
# Presenter (Qt-free)
# ===========================================================================


class TestPresenter:
    def test_load_filters_by_kind(self):
        from multiprocess_prototype.frontend.widgets.tabs.observability import RecordHistoryPresenter

        src = FakeSource([_rec("log", "a"), _rec("error", "b"), _rec("log", "c")])
        p = RecordHistoryPresenter(src, "log")
        rows = p.load()
        assert [r["message"] for r in rows] == ["c", "a"]  # newest_first

    def test_level_filter(self):
        from multiprocess_prototype.frontend.widgets.tabs.observability import RecordHistoryPresenter

        src = FakeSource([_rec("log", "i", severity="info"), _rec("log", "e", severity="error")])
        p = RecordHistoryPresenter(src, "log")
        p.set_level_filter(["ERROR"])
        assert [r["message"] for r in p.load()] == ["e"]

    def test_pagination(self):
        from multiprocess_prototype.frontend.widgets.tabs.observability import RecordHistoryPresenter

        src = FakeSource([_rec("log", str(i)) for i in range(5)])
        p = RecordHistoryPresenter(src, "log", page_size=2)
        assert len(p.load()) == 2
        assert p.has_next(p.load()) is True
        p.next_page()
        assert p.page_number == 2
        assert p.has_prev is True

    def test_matches_live_respects_kind_and_filter(self):
        from multiprocess_prototype.frontend.widgets.tabs.observability import RecordHistoryPresenter

        p = RecordHistoryPresenter(FakeSource(), "error")
        assert p.matches_live(_rec("error", "x", severity="error")) is True
        assert p.matches_live(_rec("log", "x")) is False
        p.set_level_filter(["critical"])
        assert p.matches_live(_rec("error", "x", severity="error")) is False

    def test_source_none_is_safe(self):
        from multiprocess_prototype.frontend.widgets.tabs.observability import RecordHistoryPresenter

        p = RecordHistoryPresenter(None, "log")
        assert p.load() == []
        assert p.clear() == 0


# ===========================================================================
# Panel (widget-level)
# ===========================================================================


class TestPanel:
    @pytest.fixture(autouse=True)
    def _qapp(self, qapp):
        pass

    def test_three_kinds_full_history(self, qtbot):
        """3 вкладки на одном виджете — каждая на свой kind, целая история из стора."""
        from multiprocess_prototype.frontend.widgets.tabs.observability import ObservabilityTabs

        src = FakeSource([_rec("log", "L1"), _rec("error", "E1"), _rec("stats", "fps", severity="gauge")])
        tabs = ObservabilityTabs(source=src)
        qtbot.addWidget(tabs)
        assert tabs.count() == 3
        assert tabs.panel("log")._table.rowCount() == 1
        assert tabs.panel("error")._table.rowCount() == 1
        assert tabs.panel("stats")._table.rowCount() == 1
        assert tabs.panel("log")._table.item(0, _COL_MESSAGE).text() == "L1"

    def test_live_append_prepends_matching(self, qtbot):
        """Живой хвост (mock-источник): подходящие записи — сверху таблицы."""
        from multiprocess_prototype.frontend.widgets.tabs.observability import RecordHistoryPanel

        src = FakeSource([_rec("log", "old")])
        panel = RecordHistoryPanel(src, "log", title="Логи")
        qtbot.addWidget(panel)
        assert panel._table.rowCount() == 1
        added = panel.append_live_records([_rec("log", "new"), _rec("error", "skip")])
        assert added == 1  # error отфильтрован
        assert panel._table.rowCount() == 2
        assert panel._table.item(0, _COL_MESSAGE).text() == "new"  # свежая сверху
        assert panel._table.item(1, _COL_MESSAGE).text() == "old"

    def test_live_append_trims_oldest_and_updates_pagination(self, qtbot):
        """drop_oldest: модель и таблица обрезаются до _MAX_LIVE_ROWS; пагинация обновляется."""
        from multiprocess_prototype.frontend.widgets.tabs.observability import RecordHistoryPanel

        panel = RecordHistoryPanel(FakeSource(), "log", page_size=100)
        qtbot.addWidget(panel)
        panel._MAX_LIVE_ROWS = 3
        added = panel.append_live_records([_rec("log", f"m{i}") for i in range(5)])
        assert added == 5
        assert panel._table.rowCount() == 3
        assert len(panel._rows) == 3
        assert panel._table.item(0, _COL_MESSAGE).text() == "m0"  # первая в батче — сверху
        # has_next честный: 3 строки >= page_size? нет (100) → Next выключен
        assert panel._btn_next.isEnabled() is False

    def test_live_append_skipped_off_first_page(self, qtbot):
        from multiprocess_prototype.frontend.widgets.tabs.observability import RecordHistoryPanel

        src = FakeSource([_rec("log", str(i)) for i in range(5)])
        panel = RecordHistoryPanel(src, "log", page_size=2)
        qtbot.addWidget(panel)
        panel._on_next_page()  # ушли со страницы 1
        assert panel.append_live_records([_rec("log", "live")]) == 0

    def test_bridge_signal_routes_to_panels(self, qtbot):
        """observability_received → on_observability_records → live-append по kind."""
        from multiprocess_prototype.frontend.bridge import DataReceiverBridge
        from multiprocess_prototype.frontend.widgets.tabs.observability import ObservabilityTabs

        tabs = ObservabilityTabs(source=FakeSource())
        qtbot.addWidget(tabs)
        bridge = DataReceiverBridge()
        tabs.bind_live_source(bridge)
        bridge.dispatch(
            {
                "data_type": "observability_record",
                "process": "cam",
                "records": [_rec("error", "boom", severity="error")],
            }
        )
        assert tabs.panel("error")._table.rowCount() == 1
        assert tabs.panel("error")._table.item(0, _COL_MESSAGE).text() == "boom"
        # 5.21 (c): запись без process добирает его из конверта (data.process="cam").
        assert tabs.panel("error")._table.item(0, _COL_PROCESS).text() == "cam"
        assert tabs.panel("log")._table.rowCount() == 0

    def test_process_column_shows_record_process(self, qtbot):
        """5.21 (c): колонка «Процесс» питается из record['process'] (≠ module)."""
        from multiprocess_prototype.frontend.widgets.tabs.observability import RecordHistoryPanel

        src = FakeSource([_rec("error", "boom", module="CapturePlugin", process="camera_0", severity="error")])
        panel = RecordHistoryPanel(src, "error")
        qtbot.addWidget(panel)
        assert panel._table.item(0, _COL_PROCESS).text() == "camera_0"
        assert panel._table.item(0, _COL_MODULE).text() == "CapturePlugin"

    def test_live_truncation_counter_visible(self, qtbot):
        """5.21 (e): вытеснение хвоста за _MAX_LIVE_ROWS видно в метке страницы."""
        from multiprocess_prototype.frontend.widgets.tabs.observability import RecordHistoryPanel

        panel = RecordHistoryPanel(FakeSource(), "log", page_size=100)
        qtbot.addWidget(panel)
        panel._MAX_LIVE_ROWS = 2
        panel.append_live_records([_rec("log", f"m{i}") for i in range(5)])
        assert panel._dropped_live == 3
        assert "усеч" in panel._lbl_page.text()
        assert "3" in panel._lbl_page.text()

    def test_reload_resets_truncation_counter(self, qtbot):
        """R4 (d) ревью 2026-07-10: после reload() таблица показывает историю из
        стора — счётчик «хвост усечён» сбрасывается вместе с tooltip'ом."""
        from multiprocess_prototype.frontend.widgets.tabs.observability import RecordHistoryPanel

        panel = RecordHistoryPanel(FakeSource([_rec("log", "old")]), "log", page_size=100)
        qtbot.addWidget(panel)
        panel._MAX_LIVE_ROWS = 2
        panel.append_live_records([_rec("log", f"m{i}") for i in range(5)])
        assert panel._dropped_live == 4  # 1 из стора + 5 live − лимит 2
        panel.reload()
        assert panel._dropped_live == 0
        assert "усеч" not in panel._lbl_page.text()
        assert panel._lbl_page.toolTip() == ""

    def test_owns_default_source_closed(self, qtbot):
        """5.21 (e): вкладки закрывают собственный стор (не переданный извне)."""
        from multiprocess_prototype.frontend.widgets.tabs.observability import ObservabilityTabs

        closed = {"n": 0}

        class ClosableSource(FakeSource):
            def close(self):
                closed["n"] += 1

        # Переданный извне источник НЕ закрываем (владелец — тест).
        external = ClosableSource()
        tabs = ObservabilityTabs(source=external)
        qtbot.addWidget(tabs)
        tabs.close_source()
        assert closed["n"] == 0  # не владеем — не закрыли

    def test_copy_puts_tsv_on_clipboard(self, qtbot):
        from PySide6.QtWidgets import QApplication

        from multiprocess_prototype.frontend.widgets.tabs.observability import RecordHistoryPanel

        panel = RecordHistoryPanel(FakeSource([_rec("log", "hello", module="cam")]), "log")
        qtbot.addWidget(panel)
        panel._on_copy()
        text = QApplication.clipboard().text()
        assert "hello" in text
        assert "cam" in text

    def test_clear_empties_history(self, qtbot):
        from multiprocess_prototype.frontend.widgets.tabs.observability import RecordHistoryPanel

        src = FakeSource([_rec("log", "a"), _rec("log", "b")])
        panel = RecordHistoryPanel(src, "log")
        qtbot.addWidget(panel)
        assert panel._table.rowCount() == 2
        panel._on_clear()
        assert panel._table.rowCount() == 0
        assert src.count("log") == 0
