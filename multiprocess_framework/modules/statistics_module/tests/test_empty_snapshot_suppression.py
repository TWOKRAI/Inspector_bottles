# -*- coding: utf-8 -*-
"""Задача 3.2 (`plans/observability-roadmap.md`, этап 3), решение владельца Р-4г.

Пустой снапшот (`metrics snapshot (ts=…, count=0): []`) уходил в лог каждые 10 с у
каждого из восьми процессов — главный источник фона плоскости. Р-4г: периодические
пустые не отдаются, ФИНАЛЬНЫЙ при останове отдаётся всегда.

Почему не «не эмитить вовсе» (рекомендация плана была именно такой): у пустого снапшота
нашлись ДВА потребителя, которых находка Н-20 не называла.

* `probe_b3_shutdown_order_live` S4 требует снапшот в окне останова — по нему видно, что
  статистика дожила до финального сброса;
* `probe_b1_stats_tempo_live` мерит ТЕМП окна ростом `total_flushes` — счётчик обязан
  расти и на подавленном сбросе, иначе тихий процесс неотличим от вставшего окна.

Поэтому здесь три группы проверок: подавление, сохранённые признаки жизни и
неиспорченная приёмная сторона.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from ..core.aggregation_window import AggregationWindow

_METRIC = {"type": "counter", "name": "frames", "value": 1, "tags": {}}


class _Sink:
    """Сток, который ЗАПОМИНАЕТ, что ему отдали, и умеет отказать.

    Двойник, всегда отвечающий успехом, глушил бы проверки учёта: `total_flushed`
    зеленел бы при любой реализации.
    """

    def __init__(self, *, accepts: bool = True) -> None:
        self.batches: List[Tuple[str, List[Dict[str, Any]]]] = []
        self._accepts = accepts

    def __call__(self, channel: str, batch: List[Dict[str, Any]]) -> int:
        self.batches.append((channel, batch))
        return len(batch) if self._accepts else 0

    @property
    def snapshots(self) -> List[Dict[str, Any]]:
        return [snap for _ch, batch in self.batches for snap in batch]


def _window(sink: _Sink) -> AggregationWindow:
    """Окно с заведомо большим интервалом: сбросы в тесте только РУЧНЫЕ.

    Иначе фоновый таймер добавлял бы свои сбросы, и счётчики стали бы гонкой.
    """
    return AggregationWindow(flush_fn=sink, flush_interval=3600.0)


class TestEmptySnapshotIsSuppressed:
    def test_periodic_flush_of_an_empty_window_sends_nothing(self) -> None:
        """Свойство задачи 3.2 дословно."""
        sink = _Sink()
        window = _window(sink)
        # Канал зарегистрирован, метрика сброшена — дальше окно пустое, как на живом
        # стенде: `_channels_seen` не очищается, а `_metrics` очищается каждым сбросом.
        window.enqueue("log_stats", dict(_METRIC))
        window.flush_all()
        sink.batches.clear()

        window.flush_all()
        window.flush_all()

        assert sink.batches == [], "пустой снапшот не имеет права уехать стоку"
        assert window.stats["empty_suppressed"] == 2

    def test_addressed_flush_suppresses_the_same_way(self) -> None:
        """Вторая дорога к тем же стокам. Починка одной из двух — дефект на соседней развилке.

        Подготовка идёт ТОЖЕ адресным сбросом, а не ``flush_all``: инъекция в чужую
        дорогу не должна красить этот тест. Первый прогон инъекций показал ровно это —
        поломка ``flush_all`` валила проверку, чей предмет в ней не участвует.
        """
        sink = _Sink()
        window = _window(sink)
        window.enqueue("log_stats", dict(_METRIC))
        window.flush("log_stats")
        assert len(sink.snapshots) == 1, "непустой адресный сброс обязан уехать"
        sink.batches.clear()

        window.flush("log_stats")

        assert sink.batches == []
        assert window.stats["empty_suppressed"] == 1

    def test_suppression_does_not_wedge_the_window(self) -> None:
        """Подавленный сброс не имеет права заклинить окно: следующая метрика доезжает."""
        sink = _Sink()
        window = _window(sink)
        window.flush_all()

        window.enqueue("log_stats", dict(_METRIC))
        window.flush_all()

        assert len(sink.snapshots) == 1
        assert sink.snapshots[0]["total_count"] == 1


class TestSignsOfLifeSurvive:
    def test_final_flush_at_stop_is_sent_even_when_empty(self) -> None:
        """Признак «статистика дожила до останова» сохранён (probe_b3 S4)."""
        sink = _Sink()
        window = _window(sink)
        window.enqueue("log_stats", dict(_METRIC))
        window.flush_all()
        sink.batches.clear()

        window.stop()

        assert len(sink.snapshots) == 1, "финальный снапшот обязан уехать даже пустым"
        assert sink.snapshots[0]["total_count"] == 0
        assert sink.batches[0][0] == "log_stats"

    def test_flush_counter_grows_on_a_suppressed_flush(self) -> None:
        """Признак темпа окна сохранён (probe_b1 мерит рост total_flushes).

        Сброс СОСТОЯЛСЯ — окно опустошено, такт прошёл; не состоялась доставка. Не расти
        счётчику здесь — и тихий процесс выглядел бы снаружи как остановившееся окно.
        """
        sink = _Sink()
        window = _window(sink)
        before = window.stats["total_flushes"]

        window.flush_all()
        window.flush_all()
        window.flush_all()

        assert window.stats["total_flushes"] == before + 3

    def test_suppressed_flush_is_not_counted_as_handed_over(self) -> None:
        """`total_flushed` означает «сток принял». Подавленное не отдавалось никому."""
        sink = _Sink()
        window = _window(sink)

        window.flush_all()

        assert window.stats["total_flushed"] == 0
        assert window.stats["flush_failed"] == 0, "подавление — не потеря, путать нельзя"
        assert window.stats["empty_suppressed"] == 1


class TestNonEmptySideIsIntact:
    def test_non_empty_snapshot_still_reaches_every_channel(self) -> None:
        """Приёмная сторона: без этого теста подавление могло бы съесть вообще всё."""
        sink = _Sink()
        window = _window(sink)
        window.enqueue("log_stats", dict(_METRIC))
        window.enqueue("file_stats", dict(_METRIC))

        window.flush_all()

        channels = sorted(ch for ch, _batch in sink.batches)
        assert channels == ["file_stats", "log_stats"]
        for snap in sink.snapshots:
            assert snap["total_count"] == 1
            assert snap["metrics"][0]["name"] == "frames"
        assert window.stats["empty_suppressed"] == 0

    def test_refusing_sink_is_still_accounted(self) -> None:
        """Учёт «отдано против принято» не сломан подавлением."""
        sink = _Sink(accepts=False)
        window = _window(sink)
        window.enqueue("log_stats", dict(_METRIC))

        window.flush_all()

        assert window.stats["total_flushed"] == 0
        assert window.stats["flush_failed"] == 1, "сток не принял — это потеря, а не подавление"
        assert window.stats["empty_suppressed"] == 0
