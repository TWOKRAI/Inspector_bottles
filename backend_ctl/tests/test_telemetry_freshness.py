# -*- coding: utf-8 -*-
"""Task 0.10b: ``telemetry_snapshot`` видит возраст, класс свежести и дыры ревизий (B-4).

Запись писателя приходит дельтой ``state.changed`` на корень ``processes.cam`` (метка
``_fresh`` последней). Часы читателя подставные (``clock=`` драйвера), ``time.time`` не патчится.
Ожидаемые значения — литералы, посчитанные руками из правил ``freshness.classify`` (порог — два такта)
и ``gui_state_proxy`` (дыра — ``first_revision > last + 1``).

Тесты, которые могут зависнуть (повторный захват ``_telemetry_lock``), идут через ``_snapshot`` /
``_join_or_fail``: вызов живёт в daemon-потоке с дедлайном join, без sleep.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest

from backend_ctl.driver import BackendDriver
from backend_ctl.recorder import Recording, ReplayPlayer, collect_header
from backend_ctl.tests.conftest import wire_line
from multiprocess_framework.modules.state_store_module.core.freshness import stamp

P = "processes.cam"
FPS = f"{P}.state.fps"
HZ = f"{P}.workers.w.effective_hz"
DEADLINE_SEC = 10.0  # потолок ожидания daemon-потока: зависание превращается в красный, а не в висящий прогон


def _delta(path: str, new_value: Any) -> dict[str, Any]:
    return {
        "path": path,
        "old_value": None,
        "new_value": new_value,
        "source": "test",
        "timestamp": 0.0,
        "transaction_id": "t",
        "revision": 0,
    }


def _push(*deltas: dict[str, Any], **data_extra: Any) -> bytes:
    """Проводная строка ``state.changed``; ``data_extra`` — поля конверта (``first_revision``/``revision``)."""
    return wire_line({"command": "state.changed", "data": {"deltas": list(deltas), **data_extra}})


def _root(fps: Any, *, mark: dict[str, Any] | None) -> dict[str, Any]:
    """Запись процесса ``cam`` одной дельтой на корень; метка (если есть) последней, как кладёт писатель."""
    value: dict[str, Any] = {"state": {"fps": fps}, "workers": {"w": {"effective_hz": 5.0}}}
    if mark is not None:
        value["_fresh"] = mark
    return value


def _join_or_fail(thread: threading.Thread, what: str) -> None:
    thread.join(DEADLINE_SEC)
    if thread.is_alive():
        pytest.fail(f"{what} завис дольше {DEADLINE_SEC} с (вероятна повторная блокировка _telemetry_lock)")


def _snapshot(d: BackendDriver, **kwargs: Any) -> dict[str, Any]:
    """``telemetry_snapshot`` в daemon-потоке с дедлайном: зависание — красный тест, а не висящий прогон."""
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["result"] = d.telemetry_snapshot(**kwargs)
        except BaseException as exc:  # noqa: BLE001 — переносим исключение потока в тест
            box["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    _join_or_fail(thread, "telemetry_snapshot")
    if "error" in box:
        raise box["error"]
    return box["result"]


def test_snapshot_has_age_and_class() -> None:
    """Метрика несёт ``class`` и ``age_s``; служебные листья ``_fresh.*`` не метрики и не входят в ``count``."""
    d = BackendDriver(clock=lambda: 103.0)
    d.dispatch_raw(_push(_delta(P, _root(25.0, mark=stamp(1, 100.0, "a", 5.0)))))

    snap = _snapshot(d)
    metrics = snap["metrics"]

    fps = metrics[FPS]
    assert fps["class"] == "fresh"
    assert fps["age_s"] == 3.0
    assert fps["value"] == 25.0
    assert fps["process"] == "cam"
    assert fps["worker"] is None

    hz = metrics[HZ]
    assert hz["class"] == "fresh"
    assert hz["age_s"] == 3.0
    assert hz["value"] == 5.0
    assert hz["worker"] == "w"

    assert set(metrics) == {FPS, HZ}  # пути с _fresh в metrics нет
    assert snap["count"] == 2  # листья без _fresh.*: четыре листа метки в счёт не входят


def test_stamp_only_update_keeps_fresh() -> None:
    """Дельты только листьев метки (значение не писали) продлевают свежесть: метка читается заново, а не кешируется."""
    now = [0.0]
    d = BackendDriver(clock=lambda: now[0])
    d.dispatch_raw(_push(_delta(P, _root(25.0, mark=stamp(1, 100.0, "a", 5.0)))))  # первая дельта — dict на корень
    d.dispatch_raw(_push(_delta(f"{P}._fresh.seq", 2), _delta(f"{P}._fresh.src_ts", 105.0)))

    now[0] = 114.9  # 9.9 с от нового src_ts (порог 10 с); от старого src_ts было бы 14.9 с
    fresh = _snapshot(d, process="cam", metric="fps")["metrics"][FPS]
    assert fresh["class"] == "fresh"
    assert fresh["value"] == 25.0  # значение не переписывали
    assert fresh["age_s"] == pytest.approx(9.9)

    now[0] = 115.1  # 10.1 с от нового src_ts
    stale = _snapshot(d, process="cam", metric="fps")["metrics"][FPS]
    assert stale["class"] == "stale"
    assert stale["age_s"] == pytest.approx(10.1)


def test_label_update_after_first_read_is_seen() -> None:
    """Метка, обновлённая ПОСЛЕ первого чтения, видна на втором: класс по новой метке, а не по метке первого чтения."""
    now = [105.0]
    d = BackendDriver(clock=lambda: now[0])
    d.dispatch_raw(_push(_delta(P, _root(25.0, mark=stamp(1, 100.0, "a", 5.0)))))

    first = _snapshot(d, process="cam", metric="fps")["metrics"][FPS]  # первое чтение: 5.0 с от src_ts=100.0
    assert first["class"] == "fresh"
    assert first["age_s"] == 5.0

    d.dispatch_raw(_push(_delta(f"{P}._fresh.seq", 2), _delta(f"{P}._fresh.src_ts", 130.0)))  # только метка
    now[0] = 135.0  # 5.0 с от нового src_ts; от метки первого чтения было бы 35.0 с (порог 10 с)
    second = _snapshot(d, process="cam", metric="fps")["metrics"][FPS]
    assert second["class"] == "fresh"
    assert second["age_s"] == 5.0
    assert second["value"] == 25.0  # значение не переписывали


def _rev(first: int, revision: int) -> dict[str, Any]:
    return {"first_revision": first, "revision": revision}


@pytest.mark.parametrize(
    ("packets", "gap_count", "last_gap_at"),
    [
        pytest.param([_rev(1, 1), _rev(2, 2), _rev(4, 4)], 1, 123.0, id="gap_1_2_4"),
        pytest.param([_rev(1, 1), _rev(2, 2), _rev(3, 3)], 0, None, id="no_gap_1_2_3"),
        pytest.param([_rev(100, 100)], 0, None, id="first_is_base_100"),
        # диапазонный конверт: merge() на 3 листа даёт один пакет [3..5], он непрерывен целиком
        pytest.param([_rev(1, 1), _rev(2, 2), _rev(3, 5)], 0, None, id="range_after_2_first3_rev5"),
        pytest.param([_rev(1, 1), _rev(2, 2), _rev(4, 5)], 1, 123.0, id="range_gap_after_2_first4_rev5"),
        # пакеты без ревизии пропускаются: не база, не дыра, last остаётся 1 (иначе «0» дал бы дыру на 2)
        pytest.param([{}, _rev(1, 1), {}, _rev(2, 2)], 0, None, id="no_revision"),
        # скачок назад (рестарт хаба) — не дыра, новая база; затем 1 -> 3: first=3 > 1+1
        pytest.param([_rev(5, 5), _rev(6, 6), _rev(1, 1), _rev(3, 3)], 1, 123.0, id="backward_5_6_1_3"),
        # только revision без first_revision: пропуск (оба поля обязательны), а не откат first на revision
        pytest.param([_rev(1, 1), {"revision": 5}, _rev(2, 2)], 0, None, id="only_revision_no_first"),
        # не int (str, float, bool) — как отсутствие; дельты пакета при этом не теряются
        pytest.param(
            [
                _rev(1, 1),
                {"first_revision": "9", "revision": "9"},
                {"first_revision": 9.0, "revision": 9.0},
                {"first_revision": True, "revision": True},
                _rev(2, 2),
            ],
            0,
            None,
            id="malformed_revisions",
        ),
    ],
)
def test_revision_gap_counted(packets: list[dict[str, Any]], gap_count: int, last_gap_at: float | None) -> None:
    """Дыра ревизий — ``first_revision > last + 1``; считает драйвер (зеркало ``gui_state_proxy``), часы — ``clock``."""
    d = BackendDriver(clock=lambda: 123.0)
    for i, data in enumerate(packets):
        d.dispatch_raw(_push(_delta(f"{P}.state.p{i}", float(i)), **data))

    snap = _snapshot(d)
    assert snap["gap_count"] == gap_count
    assert snap["last_gap_at"] == last_gap_at
    assert snap["count"] == len(packets)  # ни один пакет не потерял свою дельту


def _leaf_cases() -> list[Any]:
    marked = _root(25.0, mark=stamp(1, 100.0, "a", 5.0))
    marked_none = {"state": {"fps": None, "lat": 25.0}, "_fresh": stamp(1, 100.0, "a", 5.0)}
    return [
        # лист вне processes.<X>: метки у него быть не может — no_data, значение сырое
        pytest.param(
            [(P, marked), ("system.mode", "run")],
            "system.mode",
            {"class": "no_data", "age_s": None, "value": "run", "process": None, "worker": None},
            id="outside_processes",
        ),
        # лист None (0.8 — снятый уровень): отсутствие значения, no_data, хотя метка процесса свежая
        pytest.param(
            [(P, marked_none)],
            FPS,
            {"class": "no_data", "age_s": None, "value": None, "process": "cam", "worker": None},
            id="none_leaf",
        ),
        # процесс без метки: класс no_data, а значение — СЫРОЙ лист, не None из read_value
        pytest.param(
            [("processes.cam2.state.fps", 7.0)],
            "processes.cam2.state.fps",
            {"class": "no_data", "age_s": None, "value": 7.0, "process": "cam2", "worker": None},
            id="unmarked_raw_value",
        ),
    ]


@pytest.mark.parametrize(("writes", "path", "expected"), _leaf_cases())
def test_leaf_classes(writes: list[Any], path: str, expected: dict[str, Any]) -> None:
    """Лист без метки, лист ``None`` и лист вне ``processes.<X>`` — ``no_data``; ``value`` — сырой лист."""
    d = BackendDriver(clock=lambda: 103.0)
    for write_path, value in writes:
        d.dispatch_raw(_push(_delta(write_path, value)))

    entry = _snapshot(d)["metrics"][path]
    assert entry["class"] == expected["class"]
    assert entry["age_s"] == expected["age_s"]
    assert entry["value"] == expected["value"]
    assert entry["process"] == expected["process"]
    assert entry["worker"] == expected["worker"]


class _FakeSend:
    """Подставной ``send_command``: записывает вызовы, отвечает успехом (как ``_recorder`` в test_telemetry_driver)."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def __call__(self, process: str, command: str, args: Any = None, **kw: Any) -> dict[str, Any]:
        self.calls.append((process, command, args))
        return {"success": True}


def test_resubscribe_resets_base(monkeypatch: pytest.MonkeyPatch) -> None:
    """Переподписка сбрасывает базу ревизии: пакет 10 после 1, 2 — новая база, а не дыра (без сброса было бы 1)."""
    d = BackendDriver(clock=lambda: 123.0)
    monkeypatch.setattr(d, "send_command", _FakeSend())
    d.dispatch_raw(_push(_delta(f"{P}.state.a", 1.0), **_rev(1, 1)))
    d.dispatch_raw(_push(_delta(f"{P}.state.b", 2.0), **_rev(2, 2)))

    d.state_subscribe("processes.**")
    d.dispatch_raw(_push(_delta(f"{P}.state.c", 3.0), **_rev(10, 10)))
    snap = _snapshot(d)
    assert snap["gap_count"] == 0
    assert snap["last_gap_at"] is None

    # контроль: после сброса настоящая дыра считается (10 -> 12: first=12 > 11)
    d.dispatch_raw(_push(_delta(f"{P}.state.d", 4.0), **_rev(12, 12)))
    snap = _snapshot(d)
    assert snap["gap_count"] == 1
    assert snap["last_gap_at"] == 123.0


def test_replay_subscriptions_resets_base(monkeypatch: pytest.MonkeyPatch) -> None:
    """Повтор durable-подписок после реконнекта идёт мимо ``state_subscribe`` и тоже сбрасывает базу ревизии."""
    d = BackendDriver(clock=lambda: 123.0)
    monkeypatch.setattr(d, "send_command", _FakeSend())
    d.state_subscribe("processes.**")  # регистрирует намерение, которое потом повторится
    d.dispatch_raw(_push(_delta(f"{P}.state.a", 1.0), **_rev(1, 1)))
    d.dispatch_raw(_push(_delta(f"{P}.state.b", 2.0), **_rev(2, 2)))

    report = d.replay_subscriptions()
    assert [(r["command"], r["success"]) for r in report] == [("state.subscribe", True)]

    d.dispatch_raw(_push(_delta(f"{P}.state.c", 3.0), **_rev(10, 10)))
    snap = _snapshot(d)
    assert snap["gap_count"] == 0
    assert snap["last_gap_at"] is None


def test_replay_uses_replay_clock() -> None:
    """Реплей читает свежесть по часам записи (playhead), а не по ``time.time()``; ts синтетические."""
    first = {"command": "state.changed", "data": {"deltas": [_delta(P, _root(25.0, mark=stamp(1, 995.0, "a", 5.0)))]}}
    second = {"command": "state.changed", "data": {"deltas": [_delta(FPS, 26.0)]}}  # значение обновилось, метка нет
    recording = Recording(
        {"created_ts": 1000.0, "snapshot": {}},
        [{"ts": 1000.0, "event": first}, {"ts": 1011.0, "event": second}],
        None,
        truncated=False,
        path="synthetic",
    )
    player = ReplayPlayer(recording, position="start")

    assert player.pump(1) == 1  # playhead на ts=1000.0: возраст 5.0 с при пороге 10 с
    entry = _snapshot(player.driver, process="cam", metric="fps")["metrics"][FPS]
    assert entry["class"] == "fresh"
    assert entry["age_s"] == 5.0
    assert entry["value"] == 25.0

    assert player.pump(1) == 1  # playhead на ts=1011.0: возраст 16.0 с, метку никто не продлил
    entry = _snapshot(player.driver, process="cam", metric="fps")["metrics"][FPS]
    assert entry["class"] == "stale"
    assert entry["age_s"] == 16.0
    assert entry["value"] == 26.0


def test_snapshot_consistent_under_concurrent_ingest() -> None:
    """Smoke: писатель в соседнем потоке, читатель в основном; ``age_s + value == now`` на каждом чтении.

    Писатель кладёт значение ``i`` и ``src_ts = i`` одной дельтой на корень; часы стоят на 1000.0. Ловит зависание,
    ``RuntimeError`` итерации и ложные дыры под нагрузкой. Разъезд копий (метка из второго ``snapshot``) этот тест
    не гарантирует: его проверяет детерминированный ``test_snapshot_uses_one_copy``.
    """
    d = BackendDriver(clock=lambda: 1000.0)
    writes = 300
    writer_done = threading.Event()
    errors: list[BaseException] = []
    reads = [0]

    def writer() -> None:
        try:
            for i in range(1, writes + 1):
                d.dispatch_raw(
                    _push(_delta(P, {"state": {"fps": float(i)}, "_fresh": stamp(i, float(i), "a", 5.0)}), **_rev(i, i))
                )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            writer_done.set()

    def reader() -> None:
        try:
            while True:
                finished = writer_done.is_set()  # читаем ещё раз ПОСЛЕ конца записи: итог виден
                metrics = d.telemetry_snapshot(process="cam", metric="fps")["metrics"]
                entry = metrics.get(FPS)
                if entry is not None:
                    assert entry["age_s"] + entry["value"] == 1000.0
                    reads[0] += 1
                if finished:
                    return
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=writer, daemon=True), threading.Thread(target=reader, daemon=True)]
    for thread in threads:
        thread.start()
    for thread, name in zip(threads, ("писатель", "читатель"), strict=True):
        _join_or_fail(thread, name)

    assert errors == []
    assert reads[0] > 0
    final = _snapshot(d)
    assert final["gap_count"] == 0  # ревизии 1..300 непрерывны: счётчик под локом не гоняет ложные дыры
    assert final["metrics"][FPS]["value"] == float(writes)


def test_snapshot_uses_one_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Метка и значения идут из ОДНОЙ копии read-model: один вызов ``snapshot`` на ``telemetry_snapshot``.

    Подставной ``snapshot`` считает вызовы и пишет новую пару «значение + метка» сразу после первого: вторая копия
    дала бы метку новее значения, и ``age_s + value`` разошлось бы с ``now``.
    """
    d = BackendDriver(clock=lambda: 1000.0)
    d.dispatch_raw(_push(_delta(P, {"state": {"fps": 1.0}, "_fresh": stamp(1, 1.0, "a", 5.0)})))
    model = d._telemetry_model
    original = model.snapshot
    calls: list[str] = []

    def snapshot_then_write(prefix: str) -> dict[str, Any]:
        out = original(prefix)
        calls.append(prefix)
        if len(calls) == 1:  # лок драйвера уже взят, модель своего не берёт: пишем прямо в неё
            model.ingest(P, {"state": {"fps": 2.0}, "_fresh": stamp(2, 2.0, "a", 5.0)})
        return out

    monkeypatch.setattr(model, "snapshot", snapshot_then_write)
    entry = _snapshot(d, process="cam", metric="fps")["metrics"][FPS]

    assert len(calls) == 1
    assert entry["value"] == 1.0
    assert entry["age_s"] + entry["value"] == 1000.0


def test_header_marks_survive_failed_state_section(monkeypatch: pytest.MonkeyPatch) -> None:
    """Метки процесса остаются в заголовке записи, даже когда секция ``state`` не собралась: реплей судит свежесть."""
    source = BackendDriver()
    source.dispatch_raw(_push(_delta(P, _root(25.0, mark=stamp(1, 995.0, "a", 5.0)))))

    def failing_state(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("state недоступен")

    monkeypatch.setattr(source, "send_command", failing_state)
    monkeypatch.setattr(source, "system_overview", lambda **kwargs: {"success": True})
    header = collect_header(source, 1000.0)
    assert header["snapshot"]["state"]["section"] == "state"  # секция state — с ошибкой

    player = ReplayPlayer(Recording(header, [], None, truncated=False, path="synthetic"), position="start")
    entry = _snapshot(player.driver, process="cam", metric="fps")["metrics"][FPS]
    assert entry["class"] == "fresh"  # created_ts=1000.0, src_ts=995.0, tick 5.0 -> 5.0 с
    assert entry["age_s"] == 5.0
    assert entry["value"] == 25.0


def test_raising_clock_keeps_deltas_and_counts_gap() -> None:
    """Часы, бросающие исключение, не стоят дельт пакета: дыра считается, ``last_gap_at`` остаётся ``None``."""
    broken = [True]

    def clock() -> float:
        if broken[0]:
            raise RuntimeError("часы сломаны")
        return 123.0

    d = BackendDriver(clock=clock)
    d.dispatch_raw(_push(_delta(f"{P}.state.a", 1.0), **_rev(1, 1)))
    d.dispatch_raw(_push(_delta(f"{P}.state.b", 2.0), **_rev(3, 3)))  # first=3 > 1 + 1
    broken[0] = False  # сам снимок читает те же часы

    snap = _snapshot(d)
    assert snap["ingested_total"] == 2
    assert snap["count"] == 2
    assert snap["gap_count"] == 1
    assert snap["last_gap_at"] is None
