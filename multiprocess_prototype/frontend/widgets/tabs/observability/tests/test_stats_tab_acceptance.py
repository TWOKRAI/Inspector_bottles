# -*- coding: utf-8 -*-
"""Независимые приёмочные тесты вкладки «Статистика» (kind="stats").

Написаны ТОЛЬКО по контракту (record_source.py + форма записи kind=stats,
снятая с живого стенда) и по описанию публичного API RecordHistoryPanel,
без просмотра реализации record_history_panel.py / observability_tabs.py.

Ожидаемые значения — литералы, не выведены из кода испытуемого.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

from PySide6.QtWidgets import QComboBox, QLabel

from multiprocess_prototype.frontend.widgets.tabs.observability import (
    RecordHistoryPanel,
)
from multiprocess_prototype.frontend.widgets.tabs.observability.record_history_panel import (
    EMPTY_HINTS,
)


# ---------------------------------------------------------------------------
# Fake-источник, удовлетворяющий RecordSource Protocol (list_records/count/clear).
# ---------------------------------------------------------------------------


class FakeRecordSource:
    """In-memory источник записей — реализует контракт RecordSource дословно."""

    def __init__(self, records: List[Dict[str, Any]]):
        self._records = list(records)

    def list_records(
        self,
        kind: Optional[str] = None,
        module: Optional[str] = None,
        severity_in: Optional[List[str]] = None,
        offset: int = 0,
        limit: int = 100,
        newest_first: bool = True,
    ) -> List[Dict[str, Any]]:
        rows = [r for r in self._records if kind is None or r.get("kind") == kind]
        if module is not None:
            rows = [r for r in rows if r.get("module") == module]
        if severity_in is not None:
            rows = [r for r in rows if r.get("severity") in severity_in]
        rows = sorted(rows, key=lambda r: r["ts"], reverse=newest_first)
        return copy.deepcopy(rows[offset : offset + limit])

    def count(self, kind: Optional[str] = None) -> int:
        return len([r for r in self._records if kind is None or r.get("kind") == kind])

    def clear(self, kind: Optional[str] = None) -> int:
        before = len(self._records)
        self._records = [r for r in self._records if kind is not None and r.get("kind") != kind]
        return before - len(self._records)


# ---------------------------------------------------------------------------
# Фабрики записей — форма kind=stats снята с живого стенда (дана в задаче).
# ---------------------------------------------------------------------------


def make_stats_record(ts: float, message: str, *, process: str = "camera_0") -> Dict[str, Any]:
    return {
        "kind": "stats",
        "process": process,
        "module": process,
        "ts": ts,
        "severity": "snapshot",
        "severity_number": 0,
        "message": message,
        "extra": {
            "aggregate": True,
            "total_count": 2,
            "window_ts": ts - 0.001,
            "metrics": [
                {
                    "name": "capture.frames",
                    "type": "counter",
                    "tags": {"plugin": "capture", "camera": "0"},
                    "count": 219.0,
                },
                {
                    "name": "capture.fps",
                    "type": "gauge",
                    "tags": {"plugin": "capture", "camera": "0"},
                    "value": 21.31782945736588,
                },
            ],
        },
    }


def make_log_record(ts: float, message: str, severity: str = "INFO") -> Dict[str, Any]:
    levels = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
    return {
        "kind": "log",
        "process": "camera_0",
        "module": "camera_0",
        "ts": ts,
        "severity": severity,
        "severity_number": levels[severity],
        "message": message,
        "extra": {},
    }


def make_error_record(ts: float, message: str) -> Dict[str, Any]:
    return {
        "kind": "error",
        "process": "camera_0",
        "module": "camera_0",
        "ts": ts,
        "severity": "ERROR",
        "severity_number": 40,
        "message": message,
        "extra": {},
    }


def row_texts(table, row: int) -> List[str]:
    """Собрать текст всей строки таблицы (ячейки-items + cell-widgets)."""
    texts: List[str] = []
    for col in range(table.columnCount()):
        item = table.item(row, col)
        if item is not None and item.text():
            texts.append(item.text())
        widget = table.cellWidget(row, col)
        if widget is not None and hasattr(widget, "text"):
            try:
                text = widget.text()
            except TypeError:
                text = None
            if text:
                texts.append(text)
    return texts


def visible_label_texts(root) -> List[str]:
    return [label.text() for label in root.findChildren(QLabel) if label.isVisible()]


LEVEL_TOKENS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


def has_severity_level_combo(root) -> bool:
    """Есть ли выпадающий список с типичными именами уровней логирования."""
    for combo in root.findChildren(QComboBox):
        items = {combo.itemText(i).strip().upper() for i in range(combo.count())}
        if items & LEVEL_TOKENS:
            return True
    return False


# ---------------------------------------------------------------------------
# Критерий 1 — панель kind="stats" наполняется ровно записями kind=stats.
# ---------------------------------------------------------------------------


def test_stats_panel_loads_only_stats_records_from_store(qtbot):
    records = [
        make_stats_record(1000.0, "metrics snapshot A"),
        make_stats_record(1001.0, "metrics snapshot B"),
        make_stats_record(1002.0, "metrics snapshot C"),
        make_log_record(1000.5, "log line"),
        make_log_record(1001.5, "another log line"),
        make_error_record(1000.2, "boom"),
    ]
    source = FakeRecordSource(records)
    panel = RecordHistoryPanel(source, "stats", title="Статистика", page_size=100)
    qtbot.addWidget(panel)

    assert panel._table.rowCount() == 3, (
        f"ожидалось ровно 3 строки (записей kind=stats в сторе), получено {panel._table.rowCount()}"
    )


# ---------------------------------------------------------------------------
# Критерий 2 — живой хвост доезжает, свежие сверху, чужой kind не проходит.
# ---------------------------------------------------------------------------


def test_append_live_records_increases_row_count_and_puts_newest_on_top(qtbot):
    source = FakeRecordSource([make_stats_record(1000.0, "initial snapshot")])
    panel = RecordHistoryPanel(source, "stats", title="Статистика", page_size=100)
    qtbot.addWidget(panel)

    before = panel._table.rowCount()
    assert before == 1

    added = panel.append_live_records([make_stats_record(2000.0, "FRESH_LIVE_ROW")])

    assert added == 1, f"append_live_records должен вернуть 1, вернул {added}"
    assert panel._table.rowCount() == before + 1, (
        f"ожидалось {before + 1} строк после живого хвоста, получено {panel._table.rowCount()}"
    )

    top_row_text = " ".join(row_texts(panel._table, 0))
    assert "FRESH_LIVE_ROW" in top_row_text, (
        f"самая свежая запись живого хвоста должна оказаться в строке 0 (верхняя строка содержит: {top_row_text!r})"
    )


def test_append_live_records_rejects_foreign_kind_records(qtbot):
    source = FakeRecordSource([make_stats_record(1000.0, "initial snapshot")])
    panel = RecordHistoryPanel(source, "stats", title="Статистика", page_size=100)
    qtbot.addWidget(panel)

    before = panel._table.rowCount()

    added = panel.append_live_records(
        [
            make_log_record(2000.0, "foreign log record"),
            make_error_record(2001.0, "foreign error record"),
        ]
    )

    assert added == 0, f"панель stats не должна принять log/error, вернула added={added}"
    assert panel._table.rowCount() == before, (
        "число строк не должно измениться при попытке добавить чужой kind: "
        f"было {before}, стало {panel._table.rowCount()}"
    )


# ---------------------------------------------------------------------------
# Критерий 3 — число строк МОЖЕТ превысить page_size за счёт живого хвоста;
# тест обязан отличить реальный рост от упора в потолок страницы —
# двумя последовательными добавлениями через границу page_size.
# ---------------------------------------------------------------------------


def test_live_tail_row_count_grows_past_page_size_boundary(qtbot):
    page_size = 5
    initial_records = [make_stats_record(1000.0 + i, f"seed {i}") for i in range(3)]
    source = FakeRecordSource(initial_records)
    panel = RecordHistoryPanel(source, "stats", title="Статистика", page_size=page_size)
    qtbot.addWidget(panel)

    assert panel._table.rowCount() == 3, f"начальная загрузка: ожидалось 3 строки, получено {panel._table.rowCount()}"

    # Первая порция live-хвоста доводит ровно до границы page_size.
    added_1 = panel.append_live_records([make_stats_record(2000.0 + i, f"live-a {i}") for i in range(2)])
    assert added_1 == 2
    at_boundary = panel._table.rowCount()
    assert at_boundary == page_size, (
        f"после первой порции ожидалось ровно page_size={page_size} строк, получено {at_boundary}"
    )

    # Вторая порция обязана перевалить через page_size, а не застрять на потолке —
    # если рост уже когда-то ошибочно капается, эта проверка это поймает.
    added_2 = panel.append_live_records([make_stats_record(3000.0 + i, f"live-b {i}") for i in range(2)])
    assert added_2 == 2
    after_boundary = panel._table.rowCount()
    assert after_boundary == page_size + 2, (
        f"живой хвост обязан провезти строки МИМО page_size={page_size}: "
        f"ожидалось {page_size + 2}, получено {after_boundary} "
        f"(осталось на границе={after_boundary == at_boundary})"
    )


# ---------------------------------------------------------------------------
# Критерий 4 — подсказка пустоты для stats не утверждает «эмитента/приёмника
# метрик нет» и показывается только при нулевом числе строк.
# ---------------------------------------------------------------------------


def test_stats_empty_hint_text_does_not_claim_no_emitter():
    hint = EMPTY_HINTS.get("stats")
    assert hint is not None, "EMPTY_HINTS обязан содержать ключ 'stats'"

    misleading_substrings = [
        "эмитента нет",
        "эмиттера нет",
        "нет эмитента",
        "нет приёмника",
        "приёмника нет",
        "источника метрик нет",
        "метрики не поступают",
        "не публикуются",
        "нет источника метрик",
    ]
    lowered = hint.lower()
    for phrase in misleading_substrings:
        assert phrase not in lowered, (
            f"подсказка пустоты kind=stats утверждает устаревшую причину «{phrase}», хотя метрики едут: {hint!r}"
        )


def test_stats_empty_hint_shown_only_when_zero_rows(qtbot):
    hint = EMPTY_HINTS.get("stats")
    assert hint, "EMPTY_HINTS['stats'] должен быть непустой строкой для этого теста"

    empty_source = FakeRecordSource([])
    empty_panel = RecordHistoryPanel(empty_source, "stats", title="Статистика", page_size=100)
    qtbot.addWidget(empty_panel)
    empty_panel.show()
    qtbot.waitExposed(empty_panel)

    assert empty_panel._table.rowCount() == 0
    assert hint in visible_label_texts(empty_panel), (
        "при нулевом числе строк подсказка пустоты kind=stats обязана быть видимой"
    )

    filled_source = FakeRecordSource([make_stats_record(1000.0, "not empty")])
    filled_panel = RecordHistoryPanel(filled_source, "stats", title="Статистика", page_size=100)
    qtbot.addWidget(filled_panel)
    filled_panel.show()
    qtbot.waitExposed(filled_panel)

    assert filled_panel._table.rowCount() == 1
    assert hint not in visible_label_texts(filled_panel), (
        "при непустой таблице подсказка пустоты kind=stats не должна быть видимой"
    )


# ---------------------------------------------------------------------------
# Критерий 5 — у kind="stats" фильтр уровня отсутствует, у log/error — присутствует.
# ---------------------------------------------------------------------------


def test_log_panel_has_severity_level_filter(qtbot):
    source = FakeRecordSource([make_log_record(1000.0, "hello")])
    panel = RecordHistoryPanel(source, "log", title="Логи", page_size=100)
    qtbot.addWidget(panel)

    assert has_severity_level_combo(panel), (
        "у панели kind=log ожидается выпадающий список уровней логирования "
        f"(искали пересечение с {sorted(LEVEL_TOKENS)})"
    )


def test_stats_panel_has_no_severity_level_filter(qtbot):
    source = FakeRecordSource([make_stats_record(1000.0, "snap")])
    panel = RecordHistoryPanel(source, "stats", title="Статистика", page_size=100)
    qtbot.addWidget(panel)

    assert not has_severity_level_combo(panel), (
        "у панели kind=stats фильтр уровня бессмыслен (severity='snapshot', "
        "не уровень логирования) и не должен присутствовать, но найден combo "
        f"с пересечением {sorted(LEVEL_TOKENS)}"
    )
