# -*- coding: utf-8 -*-
"""
Задача 2.1 — доставка агрегата stats: маркер, нормализатор, предохранитель петли.

Три правки механики держатся на ОДНОМ признаке — :data:`STATS_AGGREGATE_KEY`.
Здесь проверяется каждая по отдельности и все три на одной записи: разойдись
они, запись стала бы агрегатом для одного потребителя и сырой метрикой для
другого, и предохранитель петли пропустил бы её молча.

Тесты автора (опасности механизма), не приёмка снаружи: сквозная доставка в
живую БД — в ``statistics_module/tests/test_hub_stats_channel.py``.
"""

import pytest

from ..observability import (
    STATS_AGGREGATE_KEY,
    ObservabilityDrainAdapter,
    ObservabilityHub,
    hub_record_to_display,
)
from ..observability.record_display import NUMBER_SEVERITY, SNAPSHOT_TOTAL_KEY, snapshot_message


def _aggregate_record(metrics=None, total=None, **extra):
    """Запись-агрегат в форме, которую кладёт ``HubStatsChannel``."""
    metrics = [{"name": "a.count", "type": "counter", "count": 2.0}] if metrics is None else metrics
    record = {
        STATS_AGGREGATE_KEY: True,
        "metrics": metrics,
        "total_count": len(metrics) if total is None else total,
        "window_ts": 100.0,
        "kind": "stats",
        "module": "camera_0",
        "ts": 101.0,
    }
    record.update(extra)
    return record


class _RecordingStats:
    """Дубль ``StatsManager``: считает, ЧТО ему отдали (и умеет отказывать)."""

    def __init__(self, fail=False):
        self.calls = []
        self._fail = fail

    def _note(self, kind, name, value, tags):
        if self._fail:
            raise RuntimeError("sink отказал")
        self.calls.append((kind, name, value, tags))

    def record_metric(self, name, value=1, tags=None):
        self._note("counter", name, value, tags)

    def record_timing(self, name, duration, tags=None):
        self._note("timing", name, duration, tags)

    def gauge(self, name, value, tags=None):
        self._note("gauge", name, value, tags)


# ---------------------------------------------------------------------------
# Правка 1 — API hub'а для готовой записи
# ---------------------------------------------------------------------------


def test_hub_puts_a_ready_record_into_the_stats_slot_with_its_envelope():
    """``emit_stats_record`` кладёт готовую запись и штампует конверт.

    Форма записи — целиком дело писателя; hub добавляет ровно ``kind``/
    ``module``/``ts`` и ничего не переписывает.
    """
    hub = ObservabilityHub("camera_0", clock=lambda: 42.0)

    hub.emit_stats_record({STATS_AGGREGATE_KEY: True, "metrics": [], "total_count": 0})

    drained = hub.drain_all()
    assert len(drained["stats"]) == 1, "запись обязана лечь в stats-слот, а не в log/error"
    assert drained["log"] == [] and drained["error"] == []
    record = drained["stats"][0]
    assert record["kind"] == "stats"
    assert record["module"] == "camera_0"
    assert record["ts"] == 42.0
    assert record[STATS_AGGREGATE_KEY] is True


def test_hub_does_not_stamp_the_callers_dict():
    """Конверт hub'а не появляется в объекте вызывающего.

    Снапшот принадлежит каналу, и «положил в hub» не должно означать «мой dict
    задним числом обзавёлся чужими полями»: следующий, кто прочитает его у
    себя, увидел бы ``ts`` соседа.
    """
    hub = ObservabilityHub("camera_0", clock=lambda: 42.0)
    payload = {STATS_AGGREGATE_KEY: True, "metrics": [], "total_count": 0}

    hub.emit_stats_record(payload)

    assert "kind" not in payload and "ts" not in payload and "module" not in payload


def test_hub_does_not_mark_records_itself():
    """Маркер ставит ПИСАТЕЛЬ, не hub.

    Поставь hub маркер сам — «положить готовую запись» стало бы синонимом
    «положить агрегат», и любой второй владелец слота (hub — примитив уровня 0,
    писателей у него может быть много) получил бы предохранитель петли даром и
    не по делу.
    """
    hub = ObservabilityHub("camera_0")

    hub.emit_stats_record({"metrics": []})

    assert STATS_AGGREGATE_KEY not in hub.drain_all()["stats"][0]


# ---------------------------------------------------------------------------
# Правка 2 — ветка снапшота в нормализаторе (§2-П6 спеки)
# ---------------------------------------------------------------------------


def test_aggregate_survives_the_normalizer_with_its_content():
    """Агрегат доезжает до display-вида ЦЕЛИКОМ, а не четырьмя ключами.

    Именно здесь запись уехала бы в БД пустой (``message=""``,
    ``extra={"value": None}``) при зелёном «строка есть»: правило четырёх
    ключей сырой метрики выбрасывает всё, чего у агрегата и нет.
    """
    metrics = [
        {"name": "plugin.frames_total", "type": "counter", "count": 3.0},
        {"name": "plugin.infer_seconds", "type": "timing", "count": 1, "p95": 0.0167},
    ]

    display = hub_record_to_display(_aggregate_record(metrics))

    assert display["kind"] == "stats"
    # Task 3.1 (К7): у ВСЕХ числовых форм одно слово; прежнее "snapshot" различало
    # то, что уже различают kind и metric IS NULL.
    assert display["severity"] == NUMBER_SEVERITY
    # Содержимое ПОИМЁННО: «extra непустой» зеленело бы и на огрызке.
    assert display["extra"]["total_count"] == 2
    assert display["extra"]["window_ts"] == 100.0
    assert [m["name"] for m in display["extra"]["metrics"]] == [
        "plugin.frames_total",
        "plugin.infer_seconds",
    ]
    assert display["extra"]["metrics"][0]["count"] == 3.0
    assert display["extra"]["metrics"][1]["p95"] == 0.0167


def test_metric_names_reach_the_message_because_search_indexes_only_it():
    """Имена метрик — в ``message``: полнотекстовый индекс не смотрит в ``extra``.

    Положи мы имена только структурно, снапшот находился бы фильтром по виду
    записи и никогда по имени метрики — то есть на главный вопрос вкладки
    («что было с этой метрикой?») ответа бы не было.
    """
    metrics = [{"name": "plugin.frames_total", "type": "counter", "count": 1.0}]

    message = hub_record_to_display(_aggregate_record(metrics))["message"]

    assert "plugin.frames_total" in message


def test_repeated_names_collapse_but_the_series_count_stays_honest():
    """Одно имя × разные теги = разные серии; в тексте имя одно.

    Живой замер стенда: 384 серии на 4 имени давали 16 924 Б текста. Свёртка
    имён не имеет права соврать про число серий — потерь тут нет, и «опущено»
    появиться не должно.
    """
    metrics = [
        {"name": "dispatch.attempts", "type": "counter", "tags": {"key": "a"}, "count": 1.0},
        {"name": "dispatch.attempts", "type": "counter", "tags": {"key": "b"}, "count": 2.0},
        {"name": "dispatch.duration", "type": "timing", "tags": {"key": "a"}, "count": 1},
    ]

    message = snapshot_message(_aggregate_record(metrics, total=3))

    assert message.count("dispatch.attempts") == 1, "повтор имени в текст не едет"
    assert "count=3" in message, "число СЕРИЙ не свёрнуто вместе с именами"
    assert "имён 2" in message, "расхождение серий и имён названо, а не спрятано"
    assert "опущено" not in message, "свёрнутое имя — не потерянная серия"


def test_the_message_names_how_many_metrics_did_not_fit():
    """``total_count`` больше числа доехавших → разность названа вслух.

    В 2.1 потолка кардинальности ещё нет и разность всегда ноль; проверяется
    сама арифметика, а не сегодняшний ноль — иначе 2.2 введёт потолок, и
    молчание об опущенных обнаружилось бы живым прогоном.
    """
    one = [{"name": "a", "type": "counter", "count": 1.0}]

    assert "опущено" not in snapshot_message(_aggregate_record(one, total=1))

    voiced = snapshot_message(_aggregate_record(one, total=7))
    assert "опущено 6 из 7" in voiced


def test_a_raw_metric_record_keeps_its_old_shape():
    """Сырая метрика нормализуется ровно как раньше — ветка не увела её к себе.

    Контроль к предыдущим: без него «агрегат доезжает» зеленело бы и в
    редакции, где ветка агрегата съела ОБА класса записей.
    """
    raw = {"kind": "stats", "module": "camera_0", "ts": 1.0, "metric": "m", "value": 5, "metric_type": "gauge"}

    display = hub_record_to_display(raw)

    assert display["severity"] == NUMBER_SEVERITY
    assert display["message"] == "m"
    # Task 3.1: род метрики переехал из колонки severity в структуру — он не
    # уничтожен снятием трёх словарей из одной колонки, он лежит рядом с числом.
    assert display["extra"] == {"value": 5, "tags": {}, "metric_type": "gauge"}
    assert display["metric"] == "m"


# ---------------------------------------------------------------------------
# Правка 3 — предохранитель петли (§2-П4 спеки)
# ---------------------------------------------------------------------------


def test_the_adapter_refuses_to_feed_an_aggregate_back_into_stats():
    """Агрегат в ``StatsManager`` не возвращается — иначе петля."""
    sink = _RecordingStats()
    adapter = ObservabilityDrainAdapter(stats=sink)

    assert adapter.apply_stat(_aggregate_record()) is False
    assert sink.calls == []
    assert adapter.skipped_aggregates == 1


def test_the_adapter_still_delivers_raw_metrics():
    """Контроль: предохранитель закрыл агрегаты, а не плоскость целиком.

    Без этой пары «агрегат не доехал» зеленело бы и у адаптера, который не
    доставляет вообще ничего.
    """
    sink = _RecordingStats()
    adapter = ObservabilityDrainAdapter(stats=sink)

    raw = {"kind": "stats", "metric": "m", "value": 5, "metric_type": "gauge"}
    assert adapter.apply_stat(raw) is True
    assert sink.calls == [("gauge", "m", 5, {})]
    assert adapter.skipped_aggregates == 0


def test_skipped_aggregates_tells_deliberate_refusal_from_absent_sink():
    """``False`` у ``apply_stat`` двусмысленно — счётчик его разъясняет.

    «Стока нет» и «это агрегат, не отдаём» — разные вещи, и снаружи по одному
    только ``False`` они неразличимы.
    """
    no_sink = ObservabilityDrainAdapter(stats=None)
    assert no_sink.apply_stat({"kind": "stats", "metric": "m", "value": 1}) is False
    assert no_sink.skipped_aggregates == 0, "отсутствие стока — не пропуск агрегата"

    # И наоборот: агрегат считается пропущенным даже когда стока нет вовсе —
    # решение «не отдавать» принято раньше, чем вопрос «а есть ли кому».
    assert no_sink.apply_stat(_aggregate_record()) is False
    assert no_sink.skipped_aggregates == 1


def test_one_window_of_emissions_gives_one_snapshot_not_a_geometric_series():
    """Арифметика петли: N окон → N снапшотов, а не рост числа метрик.

    Главное свойство предохранителя, и мерить его надо ЧИСЛОМ за несколько
    окон: на одном окне «петли нет» неотличимо от «петля есть, но ещё не
    провернулась».
    """
    hub = ObservabilityHub("camera_0")
    sink = _RecordingStats()
    adapter = ObservabilityDrainAdapter(stats=sink)

    for window in range(3):
        hub.emit_stats_record(
            {
                STATS_AGGREGATE_KEY: True,
                "metrics": [{"name": f"m{window}", "type": "counter", "count": 1.0}],
                "total_count": 1,
            }
        )
        adapter.apply_drained(hub.drain_all())

    assert sink.calls == [], "ни одна метрика снапшота не легла обратно в менеджер"
    assert adapter.skipped_aggregates == 3


# ---------------------------------------------------------------------------
# Один признак на все три места
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("marked", [True, False])
def test_normalizer_and_guard_branch_on_the_same_marker(marked):
    """Оба потребителя решают судьбу записи ОДНИМ признаком.

    Заведись у класса второй независимый признак — нашлась бы запись, которая
    для нормализатора агрегат, а для адаптера сырая метрика: она уехала бы в
    БД правильно и при этом провернула бы петлю.
    """
    record = _aggregate_record()
    if not marked:
        record.pop(STATS_AGGREGATE_KEY)
        # Без маркера это «сырая метрика без полей» — форма чужая, но выбор
        # ветки делается именно по маркеру, и проверяем мы выбор.

    display = hub_record_to_display(record)
    guarded = ObservabilityDrainAdapter(stats=_RecordingStats()).apply_stat(record) is False

    # Признак ветки — СОСТАВ конверта, а не severity: с Task 3.1 (К7) слово в
    # колонке у обеих веток одно ("number"), и прежний различитель ослеп бы
    # молча — тест зеленел бы при ЛЮБОМ выборе ветки. Ключ ``total_count``
    # кладёт в extra ровно ветка агрегата (правило конверта), у сырой метрики
    # конверт другой: {value, tags, metric_type}.
    normalized_as_aggregate = SNAPSHOT_TOTAL_KEY in display["extra"]
    assert normalized_as_aggregate is marked
    assert guarded is marked
