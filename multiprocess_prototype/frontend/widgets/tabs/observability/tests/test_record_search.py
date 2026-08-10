# -*- coding: utf-8 -*-
"""Задача 1.6, вторая половина — вкладка ищет (движок закрыт коммитом ba36879e).

Движок отвечает на слово; здесь проверяется, что до него доходит рука оператора
и что обратно возвращается РАЗЛИЧИМЫЙ ответ. Три класса дефекта, по одному на
группу:

* **поиск доезжает до источника** — иначе поле ввода красивое и мёртвое;
* **пустая таблица объяснена** — «не нашлось», «не выполнен» и «истории нет»
  выглядят одинаково, а значат противоположное; спутать их хуже, чем не искать;
* **приостановленный хвост назван** — во время поиска live-append выключен, и
  молча замерший поток через минуту неотличим от сломанного.

Fake-источник здесь умеет ОТКАЗАТЬ (``fail_with``): дубль, который всегда
успешен, глушит ровно те проверки, ради которых написан. Плюс один тест на
РЕАЛЬНОЙ связке (ObservabilityStore + панель) — иначе зелёными остались бы одни
договорённости фейка.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from .test_record_history import _COL_MESSAGE, FakeSource, _rec


class SearchingFakeSource(FakeSource):
    """FakeSource + ``search``: подстрока по message/module/process + те же фильтры.

    Не копия FTS5 и не претендует на неё: панель проверяется на то, ЧТО она
    передаёт движку и как показывает ответ, а не на то, как движок ищет — это
    доказано на самом сторе (``test_store_search.py``).
    """

    def __init__(
        self,
        records: Optional[List[Dict[str, Any]]] = None,
        *,
        available: bool = True,
        reason: Optional[str] = None,
        fail_with: Optional[Exception] = None,
    ) -> None:
        super().__init__(records)
        self._available = available
        self.search_unavailable_reason = reason
        self._fail_with = fail_with
        self.calls: List[Dict[str, Any]] = []

    @property
    def search_available(self) -> bool:
        return self._available

    def search(
        self,
        query,
        *,
        kind=None,
        module=None,
        process=None,
        severity_in=None,
        min_severity=None,
        since=None,
        until=None,
        offset=0,
        limit=100,
        newest_first=True,
    ):
        self.calls.append({"query": query, "kind": kind, "module": module, "severity_in": severity_in})
        if self._fail_with is not None:
            raise self._fail_with
        rows = [r for r in self.records if kind is None or r.get("kind") == kind]
        if module is not None:
            rows = [r for r in rows if r.get("module") == module]
        if severity_in:
            allowed = {s.lower() for s in severity_in}
            rows = [r for r in rows if str(r.get("severity", "")).lower() in allowed]
        needle = str(query).lower()
        rows = [
            r for r in rows if needle in f"{r.get('message', '')} {r.get('module', '')} {r.get('process', '')}".lower()
        ]
        if newest_first:
            rows = list(reversed(rows))
        return rows[offset : offset + limit]


def _presenter(source, kind="log", **kw):
    from multiprocess_prototype.frontend.widgets.tabs.observability import RecordHistoryPresenter

    return RecordHistoryPresenter(source, kind, **kw)


# ===========================================================================
# Presenter (Qt-free)
# ===========================================================================


class TestPresenterSearch:
    def test_query_reaches_the_source_and_narrows_the_page(self):
        src = SearchingFakeSource([_rec("log", "камера подключена"), _rec("log", "маска пустая")])
        p = _presenter(src)
        p.set_search_query("камера")

        assert [r["message"] for r in p.load()] == ["камера подключена"]
        assert src.calls[-1]["query"] == "камера"

    def test_empty_query_returns_to_the_feed(self):
        """Пустая строка — не отказ движка, а «покажи ленту»: до источника не доходит."""
        src = SearchingFakeSource([_rec("log", "a"), _rec("log", "b")])
        p = _presenter(src)
        p.set_search_query("a")
        p.load()
        p.set_search_query("   ")

        assert p.searching is False
        assert [r["message"] for r in p.load()] == ["b", "a"]
        assert len(src.calls) == 1, "пустой запрос всё-таки уехал в источник"

    def test_filters_narrow_the_search_the_same_way_they_narrow_the_feed(self):
        src = SearchingFakeSource(
            [
                _rec("log", "камера подключена", module="capture", severity="info"),
                _rec("log", "камера отвалилась", module="seg", severity="error"),
            ]
        )
        p = _presenter(src)
        p.set_module_filter("seg")
        p.set_level_filter(["ERROR"])
        p.set_search_query("камера")

        assert [r["message"] for r in p.load()] == ["камера отвалилась"]
        assert src.calls[-1]["module"] == "seg"
        assert src.calls[-1]["severity_in"] == ["error"]

    def test_a_refusal_is_named_and_not_confused_with_nothing_found(self):
        """Худший исход задачи — «не выполнен», прочитанный как «не нашлось»."""
        src = SearchingFakeSource([_rec("log", "a")], fail_with=RuntimeError("запрос не понят: fts5 syntax"))
        p = _presenter(src)
        p.set_search_query('"незакрытая')

        assert p.load() == []
        assert p.search_error is not None
        assert "не понят" in p.search_error

    def test_nothing_found_leaves_no_error(self):
        """Обратная половина той же пары: пустой результат — это ответ, а не сбой."""
        src = SearchingFakeSource([_rec("log", "a")])
        p = _presenter(src)
        p.set_search_query("такого слова нет")

        assert p.load() == []
        assert p.search_error is None

    def test_the_error_does_not_outlive_the_query_that_caused_it(self):
        """Причина отказа снимается следующим удачным чтением, а не живёт вечно."""
        src = SearchingFakeSource([_rec("log", "a")], fail_with=RuntimeError("boom"))
        p = _presenter(src)
        p.set_search_query("x")
        p.load()
        assert p.search_error is not None

        src._fail_with = None
        p.load()
        assert p.search_error is None

    def test_a_source_without_search_names_the_reason_before_the_first_query(self):
        p = _presenter(FakeSource([_rec("log", "a")]))

        assert p.search_unavailable_reason is not None
        assert "не умеет искать" in p.search_unavailable_reason

    def test_a_source_that_cannot_search_here_passes_its_own_reason_through(self):
        """Сборка SQLite без FTS5: причину называет стор, панель её не выдумывает."""
        src = SearchingFakeSource(
            [_rec("log", "a")],
            available=False,
            reason="полнотекстовый индекс недоступен в этой сборке SQLite: no such module: fts5",
        )
        p = _presenter(src)

        assert p.search_unavailable_reason is not None
        assert "no such module: fts5" in p.search_unavailable_reason

    def test_no_source_at_all_is_named_too(self):
        p = _presenter(None)

        assert p.search_unavailable_reason is not None
        assert "стор не открыт" in p.search_unavailable_reason

    def test_search_on_an_unavailable_source_refuses_instead_of_asking(self):
        """Если поле всё-таки заполнено (не через панель) — отказ, а не тихая пустота."""
        src = SearchingFakeSource([_rec("log", "a")], available=False, reason="нет FTS5")
        p = _presenter(src)
        p.set_search_query("a")

        assert p.load() == []
        assert p.search_error == "нет FTS5"
        assert src.calls == [], "запрос ушёл в источник, который не умеет искать"

    def test_live_tail_is_suspended_while_searching(self):
        src = SearchingFakeSource([_rec("log", "a")])
        p = _presenter(src)
        rec = _rec("log", "свежая")
        assert p.matches_live(rec) is True

        p.set_search_query("свеж")
        assert p.matches_live(rec) is False, "хвост доливает строки мимо поиска"

        p.set_search_query(None)
        assert p.matches_live(rec) is True


# ===========================================================================
# Panel (widget-level)
# ===========================================================================


class TestPanelSearch:
    @pytest.fixture(autouse=True)
    def _qapp(self, qapp):
        pass

    def _panel(self, qtbot, source, kind="log"):
        from multiprocess_prototype.frontend.widgets.tabs.observability import RecordHistoryPanel

        panel = RecordHistoryPanel(source, kind)
        qtbot.addWidget(panel)
        return panel

    def _messages(self, panel):
        return [panel._table.item(r, _COL_MESSAGE).text() for r in range(panel._table.rowCount())]

    def test_enter_in_the_search_field_narrows_the_table(self, qtbot):
        src = SearchingFakeSource([_rec("log", "камера подключена"), _rec("log", "маска пустая")])
        panel = self._panel(qtbot, src)
        assert panel._table.rowCount() == 2

        panel._edit_search.setText("камера")
        panel._edit_search.returnPressed.emit()

        assert self._messages(panel) == ["камера подключена"]

    def test_clearing_the_field_returns_to_the_feed_without_enter(self, qtbot):
        """Крестик/Backspace возвращают ленту: иначе оператор остаётся в поиске молча."""
        src = SearchingFakeSource([_rec("log", "камера"), _rec("log", "маска")])
        panel = self._panel(qtbot, src)
        panel._edit_search.setText("камера")
        panel._edit_search.returnPressed.emit()
        assert panel._table.rowCount() == 1

        panel._edit_search.setText("")

        assert panel._table.rowCount() == 2
        assert panel._presenter.searching is False

    def test_typing_alone_does_not_search(self, qtbot):
        """Поиск — по Enter. Посимвольный запуск превратил бы набор в очередь проходов."""
        src = SearchingFakeSource([_rec("log", "камера")])
        panel = self._panel(qtbot, src)

        panel._edit_search.setText("кам")

        assert src.calls == []
        assert panel._table.rowCount() == 1

    def test_nothing_found_says_so_and_not_the_empty_history_hint(self, qtbot):
        src = SearchingFakeSource([_rec("log", "камера")])
        panel = self._panel(qtbot, src)

        panel._edit_search.setText("вертолёт")
        panel._edit_search.returnPressed.emit()

        assert panel._table.rowCount() == 0
        assert panel._lbl_empty.isVisibleTo(panel)
        text = panel._lbl_empty.text()
        assert "ничего не найдено" in text
        assert "вертолёт" in text
        assert "observability.history.level" not in text, "показана подсказка пустой истории вместо ответа поиска"

    def test_a_refused_search_shows_its_reason(self, qtbot):
        src = SearchingFakeSource([_rec("log", "камера")], fail_with=RuntimeError("запрос не понят: fts5 syntax"))
        panel = self._panel(qtbot, src)

        panel._edit_search.setText('"незакрытая')
        panel._edit_search.returnPressed.emit()

        assert panel._lbl_empty.isVisibleTo(panel)
        assert "не понят" in panel._lbl_empty.text()
        assert "ничего не найдено" not in panel._lbl_empty.text()

    def test_the_field_is_dead_with_a_named_reason_when_search_is_impossible(self, qtbot):
        src = SearchingFakeSource(
            [_rec("log", "камера")],
            available=False,
            reason="полнотекстовый индекс недоступен в этой сборке SQLite: no such module: fts5",
        )
        panel = self._panel(qtbot, src)

        assert panel._edit_search.isEnabled() is False
        assert "no such module: fts5" in panel._edit_search.toolTip()
        assert panel._table.rowCount() == 1, "лента перестала читаться из-за отсутствия поиска"

    def test_the_paused_tail_is_visible_in_the_page_label(self, qtbot):
        src = SearchingFakeSource([_rec("log", "камера")])
        panel = self._panel(qtbot, src)
        assert "поиск" not in panel._lbl_page.text()

        panel._edit_search.setText("камера")
        panel._edit_search.returnPressed.emit()

        assert "хвост приостановлен" in panel._lbl_page.text()
        assert panel.append_live_records([_rec("log", "камера свежая")]) == 0
        assert panel._table.rowCount() == 1

    def test_level_filter_still_narrows_while_searching(self, qtbot):
        """Фильтры и поиск — один набор условий, а не два спорящих режима."""
        src = SearchingFakeSource(
            [
                _rec("log", "камера подключена", severity="info"),
                _rec("log", "камера отвалилась", severity="error"),
            ]
        )
        panel = self._panel(qtbot, src)
        panel._edit_search.setText("камера")
        panel._edit_search.returnPressed.emit()
        assert panel._table.rowCount() == 2

        panel._combo_level.setCurrentText("ERROR")

        assert self._messages(panel) == ["камера отвалилась"]


# ===========================================================================
# Реальная связка: панель + ObservabilityStore (без фейков)
# ===========================================================================


class TestPanelOnTheRealStore:
    """Один тест на настоящих объектах — фейк доказывает только сам себя.

    Приёмка 1.6 звучит «вкладка ищет без внешней инфраструктуры», и проверить
    это можно ровно здесь: настоящий SQLite-стор, настоящая панель, слово из
    записи, набранное в поле.
    """

    @pytest.fixture(autouse=True)
    def _qapp(self, qapp):
        pass

    @pytest.fixture
    def store(self, tmp_path):
        from multiprocess_framework.modules.channel_routing_module.observability import (
            ObservabilityStore,
        )

        st = ObservabilityStore(str(tmp_path / "obs.db"))
        st.append_records(
            [
                {
                    "kind": "log",
                    "module": "capture",
                    "process": "camera_0",
                    "ts": 100.0,
                    "severity": "info",
                    "message": "hikvision камера подключена",
                },
                {
                    "kind": "log",
                    "module": "seg",
                    "process": "seg",
                    "ts": 200.0,
                    "severity": "warning",
                    "message": "маска пустая",
                },
                {
                    "kind": "log",
                    "module": "capture",
                    "process": "camera_0",
                    "ts": 300.0,
                    "severity": "error",
                    "message": "hikvision таймаут кадра",
                },
            ]
        )
        try:
            yield st
        finally:
            st.close()

    def test_a_word_from_a_record_is_found_through_the_field(self, qtbot, store):
        from multiprocess_prototype.frontend.widgets.tabs.observability import RecordHistoryPanel

        panel = RecordHistoryPanel(store, "log")
        qtbot.addWidget(panel)
        assert panel._edit_search.isEnabled() is True
        assert panel._table.rowCount() == 3

        panel._edit_search.setText("hikvision")
        panel._edit_search.returnPressed.emit()

        messages = [panel._table.item(r, _COL_MESSAGE).text() for r in range(panel._table.rowCount())]
        assert messages == ["hikvision таймаут кадра", "hikvision камера подключена"]  # свежие первыми

    def test_a_filter_narrows_the_real_search(self, qtbot, store):
        from multiprocess_prototype.frontend.widgets.tabs.observability import RecordHistoryPanel

        panel = RecordHistoryPanel(store, "log")
        qtbot.addWidget(panel)
        panel._edit_search.setText("hikvision")
        panel._edit_search.returnPressed.emit()
        assert panel._table.rowCount() == 2

        panel._combo_level.setCurrentText("ERROR")

        assert [panel._table.item(r, _COL_MESSAGE).text() for r in range(panel._table.rowCount())] == [
            "hikvision таймаут кадра"
        ]

    def test_a_broken_query_reaches_the_operator_as_a_reason(self, qtbot, store):
        """Живой ObservabilitySearchError доезжает до метки, а не в пустую таблицу."""
        from multiprocess_prototype.frontend.widgets.tabs.observability import RecordHistoryPanel

        panel = RecordHistoryPanel(store, "log")
        qtbot.addWidget(panel)

        panel._edit_search.setText('"незакрытая кавычка')
        panel._edit_search.returnPressed.emit()

        assert panel._table.rowCount() == 0
        assert panel._lbl_empty.isVisibleTo(panel)
        assert "не понят" in panel._lbl_empty.text()
