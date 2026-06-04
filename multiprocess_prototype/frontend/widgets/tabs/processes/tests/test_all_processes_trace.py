# -*- coding: utf-8 -*-
"""Тесты AllProcessesPanel — trace branches (Task 2.1 frame-trace-fanin).

Проверяет:
- блок ветвей fan-in (trace_branches) появляется при непустом значении;
- блок ветвей скрыт при пустом/None;
- основная таблица critical-path сегментов работает как v1 (без регрессий).
"""

from __future__ import annotations

from multiprocess_prototype.frontend.widgets.tabs.processes._panels import (
    AllProcessesPanel,
)
from multiprocess_prototype.frontend.widgets.tabs.processes.presenter import (
    ProcessesPresenter,
)

from ._helpers import make_processes_services


# ------------------------------------------------------------------ #
#  Вспомогательная фабрика                                            #
# ------------------------------------------------------------------ #


def _make_panel(qtbot) -> AllProcessesPanel:
    """Создать AllProcessesPanel без bindings (минимальный Qt-тест).

    Вызываем show() чтобы isVisible() работало корректно: дочерние виджеты
    получают visibility только после показа родителя.
    """
    presenter = ProcessesPresenter(make_processes_services())
    panel = AllProcessesPanel(presenter, bindings=None)
    qtbot.addWidget(panel)
    panel.show()
    return panel


# ------------------------------------------------------------------ #
#  Блок ветвей fan-in                                                 #
# ------------------------------------------------------------------ #


class TestTraceBranchesBlock:
    def test_branches_hidden_by_default(self, qtbot):
        """При создании блок ветвей и вся trace-панель скрыты."""
        panel = _make_panel(qtbot)
        assert not panel._trace_box.isVisible()
        assert not panel._branches_table.isVisible()
        assert not panel._branches_label.isVisible()

    def test_branches_appear_on_non_empty_data(self, qtbot):
        """Непустой trace_branches → блок ветвей явно включён (не скрыт).

        Используем not isHidden() вместо isVisible() — _branches_table живёт
        внутри _trace_box, который может быть скрыт без данных segments.
        isHidden() отражает флаг самого виджета, а не цепочку родителей.
        """
        panel = _make_panel(qtbot)
        branches = [
            {"branch": "region_0", "total_ms": 12.0, "spans": 3},
            {"branch": "region_1", "total_ms": 8.5, "spans": 3},
            {"branch": "region_default", "total_ms": 6.0, "spans": 3},
        ]
        panel._on_trace_branches("system.trace_branches", branches)

        assert not panel._branches_table.isHidden()
        assert not panel._branches_label.isHidden()

    def test_branches_table_rows_count(self, qtbot):
        """Количество строк в мини-таблице = количество ветвей."""
        panel = _make_panel(qtbot)
        branches = [
            {"branch": "region_0", "total_ms": 12.0, "spans": 3},
            {"branch": "region_1", "total_ms": 8.5, "spans": 3},
        ]
        panel._on_trace_branches("system.trace_branches", branches)
        assert panel._branches_table.rowCount() == 2

    def test_branches_table_content(self, qtbot):
        """Данные ветвей корректно попадают в ячейки таблицы."""
        panel = _make_panel(qtbot)
        branches = [
            {"branch": "region_0", "total_ms": 12.5, "spans": 4},
        ]
        panel._on_trace_branches("system.trace_branches", branches)

        assert panel._branches_table.item(0, 0).text() == "region_0"
        assert panel._branches_table.item(0, 1).text() == "12.50"
        assert panel._branches_table.item(0, 2).text() == "4"

    def test_branches_hidden_on_empty_list(self, qtbot):
        """Пустой список → блок ветвей явно скрыт.

        Проверяем через isHidden() (флаг самого виджета), т.к. родительский
        _trace_box может быть скрыт: isVisible() вернёт False для обоих случаев.
        """
        panel = _make_panel(qtbot)
        # Сначала показываем блок ветвей
        panel._on_trace_branches("system.trace_branches", [{"branch": "x", "total_ms": 1.0, "spans": 1}])
        assert not panel._branches_table.isHidden()
        # Затем передаём пустой → скрываем
        panel._on_trace_branches("system.trace_branches", [])
        assert panel._branches_table.isHidden()
        assert panel._branches_label.isHidden()

    def test_branches_hidden_on_none(self, qtbot):
        """None → блок ветвей скрыт (linear pipeline case)."""
        panel = _make_panel(qtbot)
        panel._on_trace_branches("system.trace_branches", None)
        assert not panel._branches_table.isVisible()

    def test_branches_ms_zero_shows_dash(self, qtbot):
        """total_ms=0 → ячейка «—» согласно edge-case ТЗ."""
        panel = _make_panel(qtbot)
        panel._on_trace_branches(
            "system.trace_branches",
            [
                {"branch": "region_0", "total_ms": 0, "spans": 2},
            ],
        )
        assert panel._branches_table.item(0, 1).text() == "—"


# ------------------------------------------------------------------ #
#  Critical-path label и поддержка merge-спана                        #
# ------------------------------------------------------------------ #


class TestTraceCriticalPath:
    def test_critical_label_exists(self, qtbot):
        """Панель содержит подпись «critical path» над таблицей сегментов."""
        panel = _make_panel(qtbot)
        label = panel._trace_critical_label
        assert label is not None
        assert "critical" in label.text().lower() or "Critical" in label.text()

    def test_trace_segments_visible_after_data(self, qtbot):
        """Основная таблица critical-path показывается при непустых сегментах."""
        panel = _make_panel(qtbot)
        segments = [
            {"label": "cam→detector", "kind": "transport", "ms": 3.0},
        ]
        panel._on_trace_segments("system.trace_segments", segments)
        assert panel._trace_box.isVisible()

    def test_trace_segments_hidden_by_default(self, qtbot):
        """Без данных trace-панель скрыта (гейт INSPECTOR_FRAME_TRACE off)."""
        panel = _make_panel(qtbot)
        assert not panel._trace_box.isVisible()

    def test_merge_span_in_table(self, qtbot):
        """Merge-спан (kind=merge) отображается в основной таблице."""
        panel = _make_panel(qtbot)
        segments = [
            {"label": "merge @ stitcher", "kind": "merge", "ms": 5.0},
        ]
        panel._on_trace_segments("system.trace_segments", segments)
        # Строка merge + строка Итого = 2 строки
        assert panel._trace_table.rowCount() == 2
        assert panel._trace_table.item(0, 0).text() == "merge @ stitcher"
        # kind=merge → «слияние»
        assert panel._trace_table.item(0, 1).text() == "слияние"

    def test_linear_pipeline_no_branches(self, qtbot):
        """Линейный пайплайн: segments есть, branches нет → блок ветвей скрыт."""
        panel = _make_panel(qtbot)
        segments = [
            {"label": "cam→detector", "kind": "transport", "ms": 2.0},
            {"label": "detector:hsv", "kind": "process", "ms": 1.0},
        ]
        panel._on_trace_segments("system.trace_segments", segments)
        # trace_box виден
        assert panel._trace_box.isVisible()
        # блок ветвей скрыт (trace_branches не приходил)
        assert not panel._branches_table.isVisible()
