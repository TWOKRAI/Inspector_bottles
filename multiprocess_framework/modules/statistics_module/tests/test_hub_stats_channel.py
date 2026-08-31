# -*- coding: utf-8 -*-
"""
Задача 2.1 — штатный канал «снапшот окна → hub» и его подключение к менеджеру.

Здесь судится ДОРОГА целиком, на настоящих объектах: ``StatsManager`` →
``AggregationWindow`` → ``HubStatsChannel`` → ``ObservabilityHub`` → дренаж →
``ObservabilityStore``. Тесты на форме записи и предохранителе петли — в
``channel_routing_module/tests/test_stats_aggregate_delivery.py``; фейковый
hub доказывает договорённости фейка, поэтому сквозная проба идёт по живой БД.
"""

import json
import os

import pytest

from ...channel_routing_module.observability import (
    STATS_AGGREGATE_KEY,
    ObservabilityDrainAdapter,
    ObservabilityHub,
    ObservabilityStore,
)
from ..channels.hub_stats_channel import STATS_HUB_CHANNEL, HubStatsChannel
from ..core.stats_manager import StatsManager

#: Темп окна, при котором фоновый таймер заведомо не вмешается в счёт: сбросы
#: делает сам тест, вызовом. Число далеко от дефолта схемы намеренно — иначе
#: тест сторожил бы дефолт, а не ручку.
_NEVER = 3600.0


@pytest.fixture()
def manager(tmp_path):
    """``StatsManager`` без лог-канала: в реестре остаётся только то, что проверяем."""
    mgr = StatsManager(
        "StatsManager",
        config={
            "enable_logging": False,
            "aggregation_interval": _NEVER,
            "channels": {"file_stats": {"type": "file", "file_path": str(tmp_path / "stats.json")}},
        },
    )
    mgr.initialize()
    yield mgr
    mgr.shutdown()


class _FailingHub:
    """Дубль hub'а, который ОТКАЗЫВАЕТ: фальшивка-всегда-успех глушила бы гейт."""

    def __init__(self):
        self.calls = 0

    def emit_stats_record(self, payload):
        self.calls += 1
        raise RuntimeError("канал hub'а переполнен")


def _flush(manager):
    """Закрыть окно вручную — не ждать таймер."""
    manager._buffer.flush_all()


# ---------------------------------------------------------------------------
# Подключение канала
# ---------------------------------------------------------------------------


def test_without_a_hub_the_manager_has_no_hub_channel(manager):
    """Процесс без hub'а — штатное состояние, а не ``AttributeError``."""
    assert STATS_HUB_CHANNEL not in manager._channel_registry.names()

    manager.record_metric("m", 1)
    _flush(manager)  # не падает: дороги просто нет


def test_attach_raises_the_channel(manager):
    hub = ObservabilityHub("camera_0")

    assert manager.attach_observability_hub(hub) is True
    assert STATS_HUB_CHANNEL in manager._channel_registry.names()


def test_the_channel_survives_config_reload(manager):
    """Пересборка конфига НЕ теряет канал в hub.

    Базовый ``reconfigure`` чистит реестр каналов и собирает его заново из
    конфига. Зарегистрируй канал снаружи — первая же перезагрузка унесла бы
    его молча, а плоскость выглядела бы живой: окно сбрасывается, счётчики
    растут, в стор не едет ничего.
    """
    hub = ObservabilityHub("camera_0")
    manager.attach_observability_hub(hub)

    manager.reconfigure({"enable_logging": False, "aggregation_interval": _NEVER})

    assert STATS_HUB_CHANNEL in manager._channel_registry.names()
    manager.record_metric("after.reload", 1)
    _flush(manager)
    assert len(hub.drain_all()["stats"]) == 1, "после reload снапшот обязан доехать"


def test_the_hub_channel_does_not_replace_the_fallback(tmp_path):
    """Канал в hub не считается «есть куда писать» вместо файлового приёмника.

    Hub — bounded-буфер, его содержимое живёт до дренажа. Зачти мы его в
    условии fallback'а, процесс без логгера остался бы без единственного
    приёмника, переживающего процесс.
    """
    mgr = StatsManager("StatsManager", config={"enable_logging": False, "aggregation_interval": _NEVER})
    mgr.initialize()
    try:
        mgr.attach_observability_hub(ObservabilityHub("camera_0"))
        names = mgr._channel_registry.names()
        assert "file_stats" in names and STATS_HUB_CHANNEL in names
    finally:
        mgr.shutdown()


@pytest.mark.parametrize("disabled", [True, False])
def test_the_operator_can_take_the_hub_channel_off_by_config(tmp_path, disabled):
    """Существующая дверь ``channels.<имя>.enabled=false`` действует и на него.

    Новой ручки задача не заводит (правило Б.1): канал снимается тем же
    ключом, что остальные, и снятие переживает пересборку.

    **Пара, а не одиночный ассерт отсутствия.** «Канала нет» зеленело бы и в
    редакции, где канал не поднимается никогда — то есть ровно там, где
    плоскость мертва. Судить можно только по РАЗНИЦЕ между двумя значениями
    ключа.
    """
    channels = {STATS_HUB_CHANNEL: {"enabled": not disabled}}
    mgr = StatsManager(
        "StatsManager",
        config={"enable_logging": False, "aggregation_interval": _NEVER, "channels": channels},
    )
    mgr.initialize()
    try:
        hub = ObservabilityHub("camera_0")
        # БОЕВАЯ дорога: процесс подключает hub через attach, а не через
        # `register_manager` + `_setup_channels()`. Прежняя редакция теста ходила
        # вторым путём и «доказывала» ручку в обход той дороги, которой ходит
        # процесс, — на боевой она не действовала вовсе (находка ревью 2.1,
        # правило §3.2 спеки: доказательство сборкой, не юнитом в обход).
        raised = mgr.attach_observability_hub(hub)
        channel = mgr._channel_registry.get(STATS_HUB_CHANNEL)

        assert raised is not disabled
        # Судим ЛИЧНОСТЬ канала, а не занятость имени: под этим именем умеет
        # вставать FileStatsChannel из общего цикла секции `channels`.
        assert isinstance(channel, HubStatsChannel) is not disabled

        # И главное — судим по ЭФФЕКТУ: доезжает ли снапшот.
        mgr.record_metric("door.check", 1)
        _flush(mgr)
        assert bool(hub.drain_all()["stats"]) is not disabled
    finally:
        mgr.shutdown()


def test_the_service_name_never_becomes_a_file_channel(tmp_path):
    """Служебное имя со своим сборщиком не поднимается общим циклом `channels`.

    Страж работает ровно там, где hub'а НЕТ: с подключённым hub'ом блок
    регистрации стоит после цикла и перезатирает самозванца тем же именем, так
    что подмена не видна. Тест без hub'а — единственный, кого убивает снятие
    стража (найдено ревью 2.1: прежний тест оставался зелёным при снятом
    страже, то есть находка ADR-SM-010 не сторожилась ничем).
    """
    mgr = StatsManager(
        "StatsManager",
        config={
            "enable_logging": False,
            "aggregation_interval": _NEVER,
            "channels": {STATS_HUB_CHANNEL: {"type": "file", "file_path": str(tmp_path / "x.json")}},
        },
    )
    mgr.initialize()  # hub НЕ подключён
    try:
        assert mgr._channel_registry.get(STATS_HUB_CHANNEL) is None, (
            "под служебным именем встал файловый приёмник — дверь оператора включает не тот канал"
        )
    finally:
        mgr.shutdown()


# ---------------------------------------------------------------------------
# Форма и учёт
# ---------------------------------------------------------------------------


def test_one_window_gives_exactly_one_record_whatever_the_number_of_metrics(manager):
    """Одна запись на СНАПШОТ, не на метрику — ради горизонта стора.

    Запись-на-метрику дала бы 8 процессов × 20 метрик × 360 окон/ч =
    57 600 строк/ч против сегодняшних ~5 040.
    """
    hub = ObservabilityHub("camera_0")
    manager.attach_observability_hub(hub)

    for i in range(20):
        manager.record_metric(f"m{i}", 1)
    _flush(manager)

    records = hub.drain_all()["stats"]
    assert len(records) == 1
    assert records[0]["total_count"] == 20
    assert len(records[0]["metrics"]) == 20


def test_the_channel_carries_the_window_count_not_its_own_recount(manager):
    """``total_count`` — из снапшота, а не ``len(metrics)``.

    Совпадают они ровно до потолка кардинальности 2.2; пересчёт по списку
    сделал бы «сколько метрик было» равным «сколько доехало» навсегда, и
    число опущенных стало бы структурно нулевым.
    """
    hub = ObservabilityHub("camera_0")
    channel = HubStatsChannel(hub)

    channel.write({"timestamp": 1.0, "metrics": [{"name": "a"}], "total_count": 9})

    assert hub.drain_all()["stats"][0]["total_count"] == 9


def test_an_empty_window_never_reaches_the_hub(manager):
    """Подавление пустых снапшотов (Р-4г) действует и на этой дороге.

    Иначе восемь процессов слали бы в стор по пустой строке каждое окно —
    ровно тот фон, который сняли задачей 3.2.
    """
    hub = ObservabilityHub("camera_0")
    manager.attach_observability_hub(hub)

    _flush(manager)

    assert hub.drain_all()["stats"] == []


def test_a_refusing_hub_is_counted_not_swallowed(manager):
    """Отказ hub'а — отказ канала, а не тихий успех.

    Дубль здесь УМЕЕТ отказывать намеренно: фальшивка-всегда-успех оставила бы
    учёт отказов непроверенным.
    """
    hub = _FailingHub()
    manager.attach_observability_hub(hub)
    manager.record_metric("m", 1)

    _flush(manager)

    assert hub.calls == 1, "канал обязан был попытаться"
    channel = manager._channel_registry.get(STATS_HUB_CHANNEL)
    assert channel.write({"metrics": [{"name": "m"}], "total_count": 1})["status"] == "error"


def test_the_window_ts_is_the_close_of_the_window_not_the_hub_clock(manager):
    """Возраст снапшота восстановим: у записи два времени, и они разные.

    ``ts`` конверта — когда запись легла в канал hub'а, ``window_ts`` — когда
    окно закрылось. При заторе дренажа их разность и есть возраст; сохрани мы
    одно, восстановить её было бы не из чего.
    """
    hub = ObservabilityHub("camera_0", clock=lambda: 500.0)
    channel = HubStatsChannel(hub)

    channel.write({"timestamp": 100.0, "metrics": [{"name": "a"}], "total_count": 1})

    record = hub.drain_all()["stats"][0]
    assert record["window_ts"] == 100.0
    assert record["ts"] == 500.0


# ---------------------------------------------------------------------------
# Сквозная дорога до живой БД
# ---------------------------------------------------------------------------


def test_the_snapshot_reaches_the_store_with_readable_content(manager, tmp_path):
    """Настоящая дорога целиком: метрика → окно → hub → дренаж → SQLite.

    Судится СОДЕРЖИМОЕ, а не наличие строки: без ветки нормализатора запись
    доехала бы пустой при зелёном «kind=stats > 0».
    """
    hub = ObservabilityHub("camera_0")
    manager.attach_observability_hub(hub)
    store = ObservabilityStore(str(tmp_path / "obs.db"))

    manager.record_metric("plugin.frames_total", 3)
    manager.record_timing("plugin.infer_seconds", 0.0167)
    _flush(manager)
    store.append_records(hub.drain_all()["stats"])

    rows = store.list_records(kind="stats")
    assert len(rows) == 1
    row = rows[0]
    assert row["process"] == "camera_0"
    extra = row["extra"] if isinstance(row["extra"], dict) else json.loads(row["extra"])
    by_name = {m["name"]: m for m in extra["metrics"]}
    assert by_name["plugin.frames_total"]["count"] == 3.0
    # Секунды доехали секундами (§2-П7): 0.0167, а не 16.7.
    assert by_name["plugin.infer_seconds"]["p95"] == pytest.approx(0.0167)
    assert extra[STATS_AGGREGATE_KEY] is True
    assert extra["total_count"] == 2


def test_the_snapshot_is_findable_by_metric_name(manager, tmp_path):
    """Приёмка «находится поиском 1.6 по имени метрики» — на живом индексе."""
    hub = ObservabilityHub("camera_0")
    manager.attach_observability_hub(hub)
    store = ObservabilityStore(str(tmp_path / "obs.db"))
    if not store.search_available:
        pytest.skip("в этой сборке SQLite нет FTS5 — поиск отключён штатно")

    manager.record_metric("plugin.frames_total", 1)
    _flush(manager)
    store.append_records(hub.drain_all()["stats"])

    found = store.search("plugin.frames_total")
    assert len(found) == 1
    assert found[0]["kind"] == "stats"


def test_no_phantom_series_appears_in_later_windows(manager, tmp_path):
    """Петля закрыта на НАСТОЯЩЕЙ связке — судим по СЕРИЯМ, не по строкам.

    Прогон со снятым предохранителем (5 окон) показал: строк в сторе 1,2,3,4,5 —
    рост ЛИНЕЙНЫЙ, и счёт строк петлю не ловит. У агрегата нет ни ``metric``, ни
    ``value``, ни ``metric_type``, поэтому адаптер сворачивает весь снапшот в одну
    безымянную метрику ``record_metric("", 1)``, и со второго окна каждая запись
    несёт серию ``('', 1.0)``: серий 1 → 2 → 2 → 2. Красным инъекцию делает
    именно ``total_count`` на ВТОРОМ и дальше окне, поэтому окон здесь ≥ 2.

    Дубли в соседнем файле проверяют предохранитель на форме записи; здесь
    участвует реальный ``StatsManager``, который и был бы жертвой петли.
    """
    hub = ObservabilityHub("camera_0")
    manager.attach_observability_hub(hub)
    adapter = ObservabilityDrainAdapter(stats=manager)
    store = ObservabilityStore(str(tmp_path / "obs.db"))

    counts = []
    for _ in range(3):
        manager.record_metric("plugin.frames_total", 1)
        _flush(manager)
        drained = hub.drain_all()
        adapter.apply_drained(drained)  # ← сюда и вернулся бы снапшот
        store.append_records(drained["stats"])
        counts.append(len(store.list_records(kind="stats")))

    assert counts == [1, 2, 3], "одно окно — один снапшот (это НЕ признак петли, см. докстринг)"
    assert adapter.skipped_aggregates == 3
    # Вот он, настоящий признак: ни в одном окне не завелось лишней серии, и
    # уж тем более безымянной.
    for i, row in enumerate(store.list_records(kind="stats", newest_first=False), start=1):
        extra = row["extra"] if isinstance(row["extra"], dict) else json.loads(row["extra"])
        names = sorted(m.get("name") for m in extra["metrics"])
        assert names == ["plugin.frames_total"], f"окно {i}: лишняя серия {names}"
        assert extra["total_count"] == 1, f"окно {i}: серий {extra['total_count']}, а эмиссия одна"


def test_the_snapshot_row_size_is_named_in_bytes(manager, tmp_path):
    """Цена строки — числом, а не «незначительно» (приёмка «горизонт стора»)."""
    hub = ObservabilityHub("camera_0")
    manager.attach_observability_hub(hub)
    store = ObservabilityStore(str(tmp_path / "obs.db"))

    for i in range(20):
        manager.record_metric(f"plugin.metric_{i}", 1)
    _flush(manager)
    store.append_records(hub.drain_all()["stats"])

    row = store.list_records(kind="stats")[0]
    extra = row["extra"] if isinstance(row["extra"], str) else json.dumps(row["extra"], ensure_ascii=False)
    size = len(row["message"].encode()) + len(extra.encode())
    # Порог — не измерение, а сторож порядка величины: 20 метрик в одной
    # записи это единицы килобайт, а не десятки. Точное число называет отчёт
    # задачи, здесь ловится смена формы (repr вместо структуры, дубль метрик).
    assert size < 4096, f"снапшот 20 метрик весит {size} Б"


def test_the_db_file_is_written_where_asked(manager, tmp_path):
    """Контроль к предыдущим: БД именно та, что просили (а не дефолтная в репо)."""
    db = tmp_path / "obs.db"
    store = ObservabilityStore(str(db))
    hub = ObservabilityHub("camera_0")
    manager.attach_observability_hub(hub)
    manager.record_metric("m", 1)
    _flush(manager)
    store.append_records(hub.drain_all()["stats"])

    assert os.path.exists(db)


# ---------------------------------------------------------------------------
# Останов: последнее окно смены
# ---------------------------------------------------------------------------


def test_the_final_drain_closes_the_window_before_taking_the_buffer(manager, tmp_path):
    """Последний снапшот смены доезжает до стора, а не умирает в буфере hub'а.

    Порядок останова процесса: воркеры → ФИНАЛЬНЫЙ дренаж hub'а (и закрытие
    стора) → ``shutdown()`` менеджеров. Последний снапшот ``StatsManager``
    рождается в его ``shutdown()``, то есть ПОСЛЕ дренажа: без принудительного
    закрытия окна он лёг бы в hub, из которого уже никто не читает.

    Пара с контролем ниже: «снапшот в сторе» зеленело бы и в редакции, где
    окно закрылось само по таймеру.
    """
    from ...process_module.managers.observability_wiring import drain_process_observability

    hub = ObservabilityHub("camera_0")
    manager.attach_observability_hub(hub)
    store = ObservabilityStore(str(tmp_path / "obs.db"))

    manager.record_metric("last.window", 1)  # окно ОТКРЫТО, таймер не сработает (3600 с)

    drain_process_observability(hub, None, store, None, stats_to_flush=manager)

    rows = store.list_records(kind="stats")
    assert len(rows) == 1, "последнее окно обязано доехать"
    assert "last.window" in rows[0]["message"]


def test_without_the_final_flush_the_last_window_stays_in_the_manager(manager, tmp_path):
    """Контроль: тот же дренаж БЕЗ закрытия окна не привозит ничего.

    Без этой половины предыдущий тест не отличает «правка работает» от
    «окно и так успело закрыться».
    """
    from ...process_module.managers.observability_wiring import drain_process_observability

    hub = ObservabilityHub("camera_0")
    manager.attach_observability_hub(hub)
    store = ObservabilityStore(str(tmp_path / "obs.db"))

    manager.record_metric("last.window", 1)

    drain_process_observability(hub, None, store, None)  # как на такте heartbeat

    assert store.list_records(kind="stats") == []


def test_eviction_in_the_hub_is_reported_as_refusal_not_success(tmp_path):
    """Затор дренажа: канал вытеснил — значит НЕ принял, и говорит об этом.

    Находка ревью 2.1 с числами: 1100 окон без дренажа при ёмкости 1024 давали
    `hub.dropped['stats'] = 76`, а канал рапортовал `success` 1100 раз. Счётчик
    внутри hub'а виден снаружи, но приёмочная арифметика «эмитировано =
    доставлено + подавлено» считается по книгам менеджера и сходилась поверх
    вытеснения.

    Дефолт hub'а — `drop_oldest`, и он отвечает `success`, лишь растя счётчик:
    свежую запись принял, выбросив ЧУЖУЮ старую. Поэтому проверяется прирост.
    """
    capacity = 8
    hub = ObservabilityHub("camera_0", capacity=capacity)
    channel = HubStatsChannel(hub)

    statuses = []
    for i in range(capacity + 5):  # дренажа нет — кольцо переполнится
        statuses.append(channel.write({"timestamp": float(i), "metrics": [{"name": "m"}], "total_count": 1})["status"])

    assert statuses[:capacity] == ["success"] * capacity, "пока место есть — приём"
    assert set(statuses[capacity:]) == {"dropped"}, f"после переполнения обязан быть отказ: {statuses}"
    assert hub.dropped["stats"] == 5
    assert len(hub.drain_all()["stats"]) == capacity


def test_the_manager_counts_the_refusal_of_the_hub_channel(manager):
    """Отказ канала доходит до счётчиков менеджера, а не остаётся внутри hub'а.

    Контроль к предыдущему: там судился ответ канала, здесь — что общий писатель
    базы его УСЛЫШАЛ. Без этого «канал сказал dropped» осталось бы его личным
    делом, и арифметика приёмки по-прежнему сходилась бы.
    """
    hub = ObservabilityHub("camera_0", capacity=1)
    manager.attach_observability_hub(hub)

    for _ in range(3):  # три окна, дренажа нет, ёмкость 1
        manager.record_metric("m", 1)
        _flush(manager)

    refused = manager.get_stats()["channel_refused_by_channel"]
    assert refused.get(STATS_HUB_CHANNEL) == 2, f"ожидалось 2 отказа, получено {refused}"
