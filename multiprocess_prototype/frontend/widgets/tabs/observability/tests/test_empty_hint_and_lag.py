# -*- coding: utf-8 -*-
"""Ф5.2: пустота вкладки названа, задержка плоскости показана.

Две находки живого прогона закрываются здесь:

  * **Б-8** — вкладки «Логи»/«Статистика» структурно пусты. Наполнение log-плоскости
    сделано во фреймворке (порог истории), а плоскость метрик сегодня без эмитента —
    и вкладка обязана СКАЗАТЬ это, а не показывать пустую таблицу: молчащий сигнал
    через час неотличим от сломанного;
  * **Б-3 + Н-4** — задержка доставки нигде не показывалась. Теперь она видна там,
    где её вообще можно измерить: на живом хвосте, у принимающей стороны.

Последний тест ведёт панель к НАСТОЯЩЕМУ ``ObservabilityStore``: 293 зелёных теста
вкладок наполняли их фейками, и приёмка 3.6 «вкладки зелёные» была выполнена
буквально и не выполнена по духу. Хотя бы один тест на вкладку обязан ехать на
настоящем сторе.
"""

from __future__ import annotations

import pytest

from multiprocess_prototype.frontend.widgets.tabs.observability.record_history_panel import (
    EMPTY_HINTS,
    RecordHistoryPanel,
    _delivery_lag,
)


class _EmptySource:
    def list_records(self, **_kw):
        return []

    def count(self, kind=None):
        return 0

    def clear(self, kind=None):
        return 0


def _rec(kind="log", ts=100.0, observed=None, message="строка"):
    rec = {
        "kind": kind,
        "process": "camera_0",
        "module": "worker",
        "ts": ts,
        "severity": "info",
        "message": message,
        "extra": {},
    }
    if observed is not None:
        rec["observed_ts"] = observed
    return rec


class TestDeliveryLag:
    """Правило «что считать задержкой» — чистая функция, проверяется без Qt."""

    def test_lag_is_the_difference_between_reception_and_emission(self) -> None:
        assert _delivery_lag(_rec(ts=100.0, observed=100.25)) == pytest.approx(0.25)

    def test_history_record_has_no_lag_at_all(self) -> None:
        """У строки из истории отметки приёма нет и быть не может — в стор пишет эмитент."""
        assert _delivery_lag(_rec(ts=100.0)) is None

    def test_negative_difference_is_not_shown_as_a_lag(self) -> None:
        """«Задержка −0.3 с» — не ответ, а новая загадка (часы источника ушли вперёд)."""
        assert _delivery_lag(_rec(ts=100.0, observed=99.7)) is None

    @pytest.mark.parametrize("junk", [None, "строка", 42, {"observed_ts": "поздно", "ts": 1.0}])
    def test_junk_does_not_raise(self, junk) -> None:
        assert _delivery_lag(junk) is None

    def test_boolean_is_not_a_timestamp(self) -> None:
        """``True`` в Python — число, и без явной проверки дал бы задержку в 1 секунду."""
        assert _delivery_lag({"ts": 0.0, "observed_ts": True}) is None


class TestEmptyHint:
    def test_empty_stats_tab_names_the_reason(self, qtbot) -> None:
        panel = RecordHistoryPanel(_EmptySource(), "stats")
        qtbot.addWidget(panel)

        assert panel._lbl_empty.isVisibleTo(panel)
        assert "эмитента" in panel._lbl_empty.text(), "пустота метрик снова молчит"

    def test_empty_log_tab_points_at_the_threshold(self, qtbot) -> None:
        panel = RecordHistoryPanel(_EmptySource(), "log")
        qtbot.addWidget(panel)

        assert "observability.history.level" in panel._lbl_empty.text()

    def test_hint_disappears_when_rows_arrive(self, qtbot) -> None:
        """Подсказка самоограничивающаяся: с приходом записей она исчезает сама.

        Это и есть защита от устаревания: после Ф8.3 текст про отсутствие эмитента
        не превратится в ложь — он просто перестанет показываться.
        """
        source = _EmptySource()
        panel = RecordHistoryPanel(source, "stats")
        qtbot.addWidget(panel)
        assert panel._lbl_empty.isVisibleTo(panel)

        source.list_records = lambda **_kw: [_rec(kind="stats")]  # type: ignore[method-assign]
        panel.reload()

        assert not panel._lbl_empty.isVisibleTo(panel)

    def test_every_tab_kind_has_a_hint(self) -> None:
        assert set(EMPTY_HINTS) == {"log", "error", "stats"}


class TestLiveLagLabel:
    def test_live_batch_shows_the_worst_lag(self, qtbot) -> None:
        """Худшая запись пачки, а не последняя: вопрос — «не застряла ли плоскость»."""
        panel = RecordHistoryPanel(_EmptySource(), "log")
        qtbot.addWidget(panel)

        panel.append_live_records(
            [
                _rec(ts=100.0, observed=100.10, message="быстрая"),
                _rec(ts=100.0, observed=100.90, message="медленная"),
                _rec(ts=100.0, observed=100.20, message="средняя"),
            ]
        )

        assert panel._lbl_lag.text() == "задержка: 0.90 с"

    def test_records_without_a_stamp_leave_the_label_alone(self, qtbot) -> None:
        panel = RecordHistoryPanel(_EmptySource(), "log")
        qtbot.addWidget(panel)

        panel.append_live_records([_rec(ts=100.0)])

        assert panel._lbl_lag.text() == "", "метка задержки соврала при отсутствии отметки приёма"


class TestOnARealStore:
    def test_log_tab_reads_a_real_store_written_by_the_real_tap(self, qtbot, tmp_path) -> None:
        """Вкладка «Логи» на НАСТОЯЩЕМ сторе, наполненном НАСТОЯЩИМ tap'ом.

        Фейк-источник проверяет панель, но не проводку: у него ``kind`` кладёт сам
        тест, и «в стор всё приезжает ошибкой» (Б-4) на нём было НЕВИДИМО. Здесь
        запись проходит весь путь: LogRecord → StoreTapChannel → SQLite → панель.
        """
        from multiprocess_framework.modules.channel_routing_module.observability import (
            ObservabilityStore,
            StoreTapChannel,
        )

        store = ObservabilityStore(str(tmp_path / "obs.db"))
        try:
            tap = StoreTapChannel(store, process="camera_0")
            tap.write(
                {
                    "timestamp": 100.0,
                    "level": "INFO",
                    "scope": "system",
                    "message": "живая строка",
                    "module": "worker_module",
                    "extra": {},
                }
            )

            panel = RecordHistoryPanel(store, "log")
            qtbot.addWidget(panel)

            assert panel._table.rowCount() == 1, "вкладка «Логи» пуста на реальном сторе"
            assert panel._table.item(0, 4).text() == "живая строка"
            assert not panel._lbl_empty.isVisibleTo(panel)
        finally:
            store.close()

    def test_error_tab_sees_only_errors_from_the_same_real_store(self, qtbot, tmp_path) -> None:
        """Разделение вкладок держится на `kind`, и он теперь считается важностью."""
        from multiprocess_framework.modules.channel_routing_module.observability import (
            ObservabilityStore,
            StoreTapChannel,
        )

        store = ObservabilityStore(str(tmp_path / "obs.db"))
        try:
            tap = StoreTapChannel(store, process="camera_0")
            for level, message in (("INFO", "обычная"), ("ERROR", "упало")):
                tap.write(
                    {
                        "timestamp": 100.0,
                        "level": level,
                        "scope": "system",
                        "message": message,
                        "module": "worker_module",
                        "extra": {},
                    }
                )

            errors = RecordHistoryPanel(store, "error")
            qtbot.addWidget(errors)

            assert errors._table.rowCount() == 1
            assert errors._table.item(0, 4).text() == "упало"
        finally:
            store.close()
