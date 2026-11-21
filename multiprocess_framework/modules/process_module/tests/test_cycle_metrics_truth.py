# -*- coding: utf-8 -*-
"""Task 0.8 (M-1, M-2): зависшая стадия не выглядит здоровой, медленная — не выглядит мёртвой.

Сценарий дефекта (``frozen_hz.py``, ``design.md`` §3): 50 циклов с шагом 10 мс, затем
пауза 2 с. До правки ``effective_hz`` оставался 100.0 вечно (метки старше окна не
вытеснялись без нового ``record()``), а стадия медленнее 1 цикла/с публиковалась как
0.0 (при < 2 меток в окне) или выпадала из процесса (``hz > 0``). После правки частота
считается В МОМЕНТ ЧТЕНИЯ: меньшее из «окно от now», «обратный последний интервал» и
``1 / возраст последнего завершения``.

Часы — подмена имени ``time`` внутри ``cycle_metrics`` (глобальный ``time.perf_counter``
не трогаем: чужие потоки дали бы флейк). Без ``sleep``: время течёт только руками теста.
Ожидаемые значения — литералы, не выведенные из кода под проверкой.
"""

from __future__ import annotations

import threading

import pytest

from multiprocess_framework.modules.process_module.generic import cycle_metrics
from multiprocess_framework.modules.process_module.generic.cycle_metrics import CycleMetricsRecorder
from multiprocess_framework.modules.process_module.heartbeat.telemetry import build_worker_telemetry


class FakeTime:
    """Заменитель модуля ``time`` внутри ``cycle_metrics``: только ``perf_counter``."""

    def __init__(self) -> None:
        self.now = 0.0
        #: если задан — вызывается при каждом чтении часов (детерминированный тест лока)
        self.on_read = None

    def perf_counter(self) -> float:
        if self.on_read is not None:
            self.on_read()
        return self.now


@pytest.fixture
def clock(monkeypatch) -> FakeTime:
    fake = FakeTime()
    monkeypatch.setattr(cycle_metrics, "time", fake)
    return fake


def _complete(rec: CycleMetricsRecorder, clock: FakeTime, at: float, duration_s: float = 0.0) -> None:
    clock.now = at
    rec.record(duration_s)


def _fifty_cycles_10ms(clock: FakeTime) -> CycleMetricsRecorder:
    """Создан в 0.0; 50 завершений в 0.01, 0.02 … 0.50 (последнее — ровно в 0.5)."""
    clock.now = 0.0
    rec = CycleMetricsRecorder()
    for k in range(1, 51):
        _complete(rec, clock, k * 0.01)
    return rec


def _one_cycle_stalled(clock: FakeTime) -> CycleMetricsRecorder:
    """Создан в 0.0, единственное завершение в 0.5, чтение будет в 4.5 (возраст 4.0)."""
    clock.now = 0.0
    rec = CycleMetricsRecorder()
    _complete(rec, clock, 0.5)
    return rec


def _worker(status: str = "running", **fields) -> dict:
    return {"status": status, **fields}


# ---------------------------------------------------------------------------
# REDS: счёт частоты в момент чтения
# ---------------------------------------------------------------------------


def test_stall_rate_decays_as_inverse_age(clock) -> None:
    rec = _fifty_cycles_10ms(clock)
    clock.now = 2.5  # пауза 2.0 с после последнего завершения (0.5)

    snap = rec.get_cycle_metrics()

    assert snap["effective_hz"] == pytest.approx(0.5)
    assert snap["last_cycle_age_s"] == pytest.approx(2.0)
    assert snap["cycles"] == 50


def test_slow_stage_not_zero(clock) -> None:
    clock.now = 0.0
    rec = CycleMetricsRecorder()
    _complete(rec, clock, 3.0)
    _complete(rec, clock, 6.0)  # цикл раз в 3.0 с
    clock.now = 7.0  # читаем через 1.0 с после последнего

    snap = rec.get_cycle_metrics()

    assert snap["effective_hz"] == pytest.approx(1 / 3)
    assert snap["last_cycle_age_s"] == pytest.approx(1.0)


def test_read_at_same_instant_no_division_by_zero(clock) -> None:
    # вход 1: чтение в момент последнего завершения — возраст 0, границы 1/age нет
    rec = _fifty_cycles_10ms(clock)
    clock.now = 0.5
    snap = rec.get_cycle_metrics()
    assert snap["last_cycle_age_s"] == 0.0
    assert snap["effective_hz"] == pytest.approx(100.0)

    # вход 2: две метки в одно мгновение — размах 0 и интервал 0: частота неизвестна
    clock.now = 0.0
    twin = CycleMetricsRecorder()
    _complete(twin, clock, 1.0)
    _complete(twin, clock, 1.0)
    clock.now = 1.0
    twin_snap = twin.get_cycle_metrics()
    assert twin_snap["effective_hz"] is None
    assert twin_snap["last_cycle_age_s"] == 0.0
    assert twin_snap["cycles"] == 2


def test_single_cycle_stall_decays(clock) -> None:
    rec = _one_cycle_stalled(clock)
    # вход 1: первое завершение через 0.5 с от создания, читаем сразу после (возраст 0.1):
    # темп 1/0.5 = 2.0, а не 1/возраст = 10 — интервал первого цикла считается от создания рекордера
    clock.now = 0.6
    assert rec.get_cycle_metrics()["effective_hz"] == pytest.approx(2.0)

    # вход 2: тот же рекордер, стадия молчит до 4.5 — спад как 1/возраст
    clock.now = 4.5

    snap = rec.get_cycle_metrics()

    assert snap["effective_hz"] == 0.25
    assert snap["last_cycle_age_s"] == 4.0


def test_no_cycles_yet_is_zero_and_unpublished(clock) -> None:
    """Циклов не было: 0.0 и возраста нет (воркер ждёт штатно — зависание до первого цикла не здесь)."""
    clock.now = 0.0
    rec = CycleMetricsRecorder()
    clock.now = 100.0

    snap = rec.get_cycle_metrics()

    assert snap["effective_hz"] == 0.0
    assert snap["last_cycle_age_s"] is None
    assert snap["cycles"] == 0


# ---------------------------------------------------------------------------
# REDS: сборщик телеметрии
# ---------------------------------------------------------------------------


def test_worker_payload_has_last_cycle_age(clock) -> None:
    rec = _fifty_cycles_10ms(clock)
    clock.now = 2.5
    workers = {"w": _worker(**rec.get_cycle_metrics())}

    # без include_cycles, метрики не гейтятся
    _path, data = build_worker_telemetry(workers, "p")
    assert data["workers"]["w"]["last_cycle_age_s"] == pytest.approx(2.0)

    # под гейтом, пропускающим только fps: возраст вне гейта, effective_hz — по гейту
    _path, gated = build_worker_telemetry(workers, "p", allowed_metrics={"fps"})
    assert gated["workers"]["w"]["last_cycle_age_s"] == pytest.approx(2.0)
    assert "effective_hz" not in gated["workers"]["w"]


def test_published_fps_after_stall(clock) -> None:
    rec = _fifty_cycles_10ms(clock)
    clock.now = 2.5
    _path, data = build_worker_telemetry({"w": _worker(**rec.get_cycle_metrics())}, "p")
    assert data["state"]["fps"] == pytest.approx(0.5)
    assert data["workers"]["w"]["effective_hz"] == pytest.approx(0.5)

    # второй вход: 0.25 — оставленное round(x, 1) дало бы 0.2
    slow = _one_cycle_stalled(clock)
    clock.now = 4.5
    _path, data = build_worker_telemetry({"w": _worker(**slow.get_cycle_metrics())}, "p")
    assert data["state"]["fps"] == 0.25
    assert data["workers"]["w"]["effective_hz"] == 0.25


def test_process_pair_from_slowest_worker() -> None:
    workers = {
        "fast": _worker(effective_hz=30.0, cycle_duration_ms=2.0, last_cycle_age_s=0.01),
        "slow": _worker(effective_hz=5.0, cycle_duration_ms=180.0, last_cycle_age_s=0.1),
    }
    _path, data = build_worker_telemetry(workers, "p")
    # пара ОДНОГО воркера: темп и задержка — оба от самого медленного
    assert data["state"]["fps"] == 5.0
    assert data["state"]["latency_ms"] == 180.0

    # второй вход: нулевая длительность цикла у воркера пары — показание, а не пропуск
    zero = {"only": _worker(effective_hz=5.0, cycle_duration_ms=0.0, last_cycle_age_s=0.1)}
    _path, data = build_worker_telemetry(zero, "p")
    assert data["state"]["latency_ms"] == 0.0


def test_stalled_worker_drives_pair(clock) -> None:
    """Стоящий воркер (статус ``stopped``, пауза 2 с) + здоровый (32 Гц) → пара от стоящего.

    Оба снимка — от настоящих рекордеров на одних подменённых часах (не рукописные).
    """
    stalled = _fifty_cycles_10ms(clock)  # последнее завершение в 0.5
    healthy = CycleMetricsRecorder()  # создан в 0.5, шаг 1/32 с (точно представим), до 2.5
    for k in range(1, 65):
        _complete(healthy, clock, 0.5 + k * 0.03125, duration_s=0.002)
    clock.now = 2.5

    workers = {
        "stalled": _worker("stopped", **stalled.get_cycle_metrics()),
        "healthy": _worker("running", **healthy.get_cycle_metrics()),
    }
    assert workers["healthy"]["effective_hz"] == pytest.approx(32.0)  # предпосылка: здоровый действительно быстр

    _path, data = build_worker_telemetry(workers, "p")

    assert data["state"]["fps"] == pytest.approx(0.5)  # стоящий тянет пару вниз, а не выпадает по статусу
    assert data["state"]["latency_ms"] == 0.0  # его цикл — 0 с (литерал сценария), напрямую, а не от здорового


def test_no_cycled_workers_publishes_none() -> None:
    # воркер без CycleMetricsRecorder (нет last_cycle_age_s) и воркер без единого цикла
    workers = {
        "no_recorder": _worker(),
        "no_cycles": _worker(effective_hz=0.0, last_cycle_age_s=None, cycles=0),
    }
    _path, data = build_worker_telemetry(workers, "p")
    assert data["state"]["fps"] is None
    assert data["state"]["latency_ms"] is None

    # отработавший воркер с неизвестной частотой (None) в пару не входит → тоже None
    unknown = {"w": _worker(effective_hz=None, cycle_duration_ms=7.0, last_cycle_age_s=0.0)}
    _path, data = build_worker_telemetry(unknown, "p")
    assert data["state"]["fps"] is None
    assert data["state"]["latency_ms"] is None
    # и сам воркер публикует явный None, а не молчит (иначе merge оставит под новой меткой старое число)
    assert "effective_hz" in data["workers"]["w"]
    assert data["workers"]["w"]["effective_hz"] is None


def test_empty_snapshot_publishes_nothing() -> None:
    """Нет воркеров / упал сбор статусов (``workers == {}``) — публиковать нечего.

    Старое значение в дереве стареет через механизм свежести, а не затирается ``None``
    (``None`` — для «воркеры есть, но пары нет», см. тест выше).
    """
    assert build_worker_telemetry({}, "p") is None


def test_microsecond_latency_not_zero(clock) -> None:
    clock.now = 0.0
    rec = CycleMetricsRecorder()
    _complete(rec, clock, 1.0, duration_s=0.00004)  # цикл 40 мкс

    _path, data = build_worker_telemetry({"w": _worker(**rec.get_cycle_metrics())}, "p")

    assert data["state"]["latency_ms"] == 0.04


# ---------------------------------------------------------------------------
# Стражи (сверх REDS)
# ---------------------------------------------------------------------------


def test_race_two_writers_one_reader_guard() -> None:
    """Гонка: 2 писателя ``record`` + читатель ``get_cycle_metrics``, по 10 000 итераций.

    ЧЕСТНО: на CPython этот тест гонку без лока НЕ ловит (замер ревью: 0 из 20) — GIL
    гасит окно. Он страж «ничего не падает, счётчик сходится, возраст не отрицателен»,
    а не доказательство лока. Доказательство лока — детерминированный тест ниже.
    """
    rec = CycleMetricsRecorder()  # реальные часы
    n_iter = 10_000
    errors: list[BaseException] = []
    snaps: list[dict] = []

    def writer() -> None:
        try:
            for _ in range(n_iter):
                rec.record(0.0)
        except BaseException as exc:  # noqa: BLE001 — собрать, проверить в главном потоке
            errors.append(exc)

    def reader() -> None:
        try:
            for _ in range(n_iter):
                snaps.append(rec.get_cycle_metrics())
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=fn, daemon=True) for fn in (writer, writer, reader)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)

    assert not any(t.is_alive() for t in threads), "поток завис (дедлок лока?)"
    assert errors == []
    assert rec.get_cycle_metrics()["cycles"] == 2 * n_iter
    cycles_seen = [s["cycles"] for s in snaps]
    assert cycles_seen == sorted(cycles_seen), "число циклов у читателя шло назад"
    for s in snaps:
        age = s.get("last_cycle_age_s")  # .get: страж зелёный и на коде до правки (ключа там нет)
        assert age is None or age >= 0.0, f"отрицательный возраст: {s}"


class _SpyLock:
    """Лок с флагом ``held`` — чтобы проверять, ПОД ли локом идёт доступ."""

    def __init__(self) -> None:
        self._inner = threading.Lock()
        self.held = False

    def acquire(self, *args, **kwargs):
        ok = self._inner.acquire(*args, **kwargs)
        if ok:
            self.held = True
        return ok

    def release(self) -> None:
        self.held = False
        self._inner.release()

    def __enter__(self) -> "_SpyLock":
        self.acquire()
        return self

    def __exit__(self, *exc) -> bool:
        self.release()
        return False


_GUARDED_PREFIXES = ("_last_",)
_GUARDED_NAMES = {"_completions", "_cycles", "_cycle_duration_ms"}


class _CheckedRecorder(CycleMetricsRecorder):
    """Рекордер, фиксирующий каждый доступ к полям состояния ВНЕ лока."""

    def __getattribute__(self, name):
        if name in _GUARDED_NAMES or name.startswith(_GUARDED_PREFIXES):
            if object.__getattribute__(self, "__dict__").get("_armed"):
                spy = object.__getattribute__(self, "_lock")
                if not spy.held:
                    object.__getattribute__(self, "_violations").append(("read", name))
        return super().__getattribute__(name)

    def __setattr__(self, name, value):
        if name in _GUARDED_NAMES or name.startswith(_GUARDED_PREFIXES):
            if self.__dict__.get("_armed") and not self._lock.held:
                self._violations.append(("write", name))
        super().__setattr__(name, value)


def test_state_and_clock_are_touched_only_under_lock(clock) -> None:
    """ДЕТЕРМИНИРОВАННО: доступ к полям состояния и чтение часов — только под локом.

    Гонку CPython не ловит, поэтому лок проверяется не поведением потоков, а флагом
    ``held`` подставного лока: любой доступ к ``_completions`` / ``_cycles`` /
    ``_cycle_duration_ms`` / ``_last_*`` и любое чтение часов вне ``with self._lock``
    записывается как нарушение. Убери ``with self._lock`` из ``record`` или из
    ``get_cycle_metrics`` — тест красный.
    """
    clock.now = 0.0
    rec = _CheckedRecorder()
    spy = _SpyLock()
    rec._lock = spy
    rec._violations = []
    clock_reads: list[bool] = []
    clock.on_read = lambda: clock_reads.append(spy.held)
    rec._armed = True

    clock.now = 1.0
    rec.record(0.01)
    clock.now = 2.0
    rec.record(0.01)
    clock.now = 3.0
    snap = rec.get_cycle_metrics()

    rec._armed = False
    assert snap["cycles"] == 2  # сценарий прошёл по-настоящему, а не вхолостую
    assert rec._violations == [], f"доступ к состоянию вне лока: {rec._violations}"
    assert len(clock_reads) == 3, f"ожидалось 3 чтения часов (2 record + 1 чтение), было {len(clock_reads)}"
    assert all(clock_reads), f"часы прочитаны вне лока: {clock_reads}"


def test_none_reaches_tree_and_read_model_ring() -> None:
    """``None``-лист от сборщика доходит до дерева и read-model, а кольцо истории не портит.

    Сборщик теперь публикует ``effective_hz`` / ``fps`` / ``latency_ms`` как явный ``None``
    (старое число не должно жить под свежей меткой). Это допустимо, только если потребители
    дерева и read-model держат ``None``-лист. Здесь — настоящий ``StateStoreManager``
    (``store.merge`` + ``handle_state_get``) и настоящая ``TelemetryReadModel``.
    """
    from multiprocess_framework.modules.state_store_module.manager.state_store_manager import StateStoreManager
    from multiprocess_framework.modules.telemetry_readmodel_module.telemetry_read_model import TelemetryReadModel

    ssm = StateStoreManager()
    model = TelemetryReadModel(clock=lambda: 0.0)
    fps_path = "processes.p.state.fps"

    def publish(workers: dict) -> None:
        path, data = build_worker_telemetry(workers, "p")
        for delta in ssm.store.merge(path, data, source="p"):
            model.ingest(delta.path, delta.new_value)

    # тик 1: живой воркер → число в дереве и точка в кольце
    publish({"w": _worker(effective_hz=5.0, cycle_duration_ms=2.0, last_cycle_age_s=0.1)})
    assert ssm.handle_state_get({"data": {"path": fps_path}})["value"] == 5.0
    assert model.history(fps_path) == [(0.0, 5.0)]

    # тик 2: пары нет (воркеры без рекордера) → явный None поверх старого числа
    publish({"w": _worker()})
    reply = ssm.handle_state_get({"data": {"path": fps_path}})
    assert reply["status"] == "ok"
    assert reply["value"] is None
    assert ssm.handle_state_get({"data": {"path": "processes.p.state.latency_ms"}})["value"] is None
    # read-model: None в снимке, кольцо не получило нечислового значения
    assert model.get(fps_path, default="absent") is None
    assert model.snapshot("processes.p.state")["processes.p.state.fps"] is None
    assert model.history(fps_path) == [(0.0, 5.0)]

    # None с самого начала: лист есть, истории нет
    fresh_model = TelemetryReadModel(clock=lambda: 0.0)
    fresh_ssm = StateStoreManager()
    path, data = build_worker_telemetry({"w": _worker()}, "q")
    for delta in fresh_ssm.store.merge(path, data, source="q"):
        fresh_model.ingest(delta.path, delta.new_value)
    assert fresh_ssm.handle_state_get({"data": {"path": "processes.q.state.fps"}})["value"] is None
    assert fresh_model.history("processes.q.state.fps") == []
