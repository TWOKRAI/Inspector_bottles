# -*- coding: utf-8 -*-
"""Task 0.10 — read-model отличает «нет данных», ноль, «устарело», «писатель ушёл» (M-6) и
несёт во времени точки истории время ИСТОЧНИКА метки, а не время приёма (M-16).

Что сторожит файл (формулировки сделаны ДО правки src; ожидаемые значения — литералы):

* ``read(path, key, alive_incarnation)`` — тот же ответ, что ``read_value`` (Task 0.2) над
  полным поддеревом, но метка читается ИЗ ТЕКУЩЕГО состояния на каждый вызов: ``seq`` и
  ``src_ts`` приходят порознь, и читатель, кэширующий метку с первой dict-дельты, видел бы
  ``stale`` у писателя, который публикует исправно (``test_stamp_only_update_keeps_fresh``).
* ``ts`` точки истории — ``src_ts`` метки того же такта. Порядок дельт живого тика —
  значения РАНЬШЕ метки, поэтому метку нельзя прочесть в момент записи точки (точка
  отстала бы на такт): механизм — «довыставление хвоста» (последняя точка каждого кольца,
  писавшегося с прошлого прихода ``<root>._fresh.src_ts``, получает ``src_ts``).
* Довыставление не двигает ``write_seq`` (инвариант 2: счётчик после записи держит границу
  ``==`` в ``ingest_poll_snapshot``) и не пишет в кольцо опросом (инвариант 1).
* ``.state.uptime`` пишет не писатель метки — его точки ВСЕГДА держат время приёма, иначе
  кольцо перестанет быть хронологическим (сторож
  ``test_uptime_point_keeps_receipt_time_and_ring_is_chronological``).

Часы читателя подставные (``clock=``); ``time.time`` не патчится, ``sleep`` нет. Ни один тест
не берёт лок и не ждёт поток, поэтому daemon-поток с дедлайном не нужен.
"""

from __future__ import annotations

from typing import Any

import pytest

from multiprocess_framework.modules.telemetry_readmodel_module import TelemetryReadModel

P = "processes.cam"
NO_DATA = {"class": "no_data", "value": None, "age_s": None}


def _mark(seq: int, src_ts: float, incarnation: str = "a", tick_sec: float = 5.0) -> dict[str, Any]:
    """Метка писателя литералом (форма — ``freshness.stamp``; дрейф ловит ``test_mark_fields_*``)."""
    return {"seq": seq, "src_ts": src_ts, "incarnation": incarnation, "tick_sec": tick_sec}


def _model(now: list[float]) -> TelemetryReadModel:
    """Read-model с подставными часами: «сейчас» — изменяемое значение теста."""
    return TelemetryReadModel(clock=lambda: now[0])


def _fixed(ts: float = 999.0) -> TelemetryReadModel:
    """Read-model, у которого ВРЕМЯ ПРИЁМА всегда ``ts`` (отличимо от времени источника)."""
    return TelemetryReadModel(clock=lambda: ts)


# --------------------------------------------------------------------------- #
# read: четыре ответа
# --------------------------------------------------------------------------- #
def test_stale_after_two_ticks() -> None:
    """Такт 5.0: до 10 с ``fresh``, после — ``stale`` с последним значением и возрастом от ``src_ts``.

    ``(100.0 + 10.1) - 100.0 != 10.1`` в float, поэтому возраст сравнивается через approx.
    """
    now = [100.0 + 9.9]
    m = _model(now)
    m.ingest(P, {"state": {"lat": 25.0}, "_fresh": _mark(1, 100.0)})

    assert m.read(P, "state.lat")["class"] == "fresh"

    now[0] = 100.0 + 10.1
    r = m.read(P, "state.lat")
    assert r["class"] == "stale"
    assert r["value"] == 25.0
    assert r["age_s"] == pytest.approx(10.1)


def test_zero_is_fresh_value() -> None:
    """Ноль — значение, а не «нет данных»: ``fps: 0`` -> ``fresh``, ``0``; ключа нет -> ``no_data``."""
    now = [101.0]
    m = _model(now)
    m.ingest(P, {"state": {"fps": 0}, "_fresh": _mark(1, 100.0)})

    zero = m.read(P, "state.fps")
    assert zero["class"] == "fresh"
    assert zero["value"] == 0
    assert zero["age_s"] == pytest.approx(1.0)

    assert m.read(P, "state.absent") == NO_DATA


@pytest.mark.parametrize(
    ("path", "key"),
    [
        pytest.param(P, "state.absent", id="no_key"),
        pytest.param(P, "state", id="key_not_leaf"),
        pytest.param("processes.cam.state", "fps", id="path_not_process_root"),
        pytest.param(P, "state.latency_ms", id="none_leaf"),
        pytest.param(P, "state.fps.x", id="key_below_a_leaf"),
        pytest.param(P, "_fresh.seq.x", id="key_below_the_stamp_leaf"),
        pytest.param(P, "", id="empty_key"),
        pytest.param(P, None, id="non_string_key"),
        pytest.param("processes.nobody", "state.fps", id="no_stamp"),
    ],
)
def test_read_no_data_cases(path: str, key: Any) -> None:
    """Любой «нет данных» — один и тот же ответ ``{"class": "no_data", "value": None, "age_s": None}``.

    ``none_leaf``: лист ``None`` (Task 0.8: снятое значение) — отсутствие, а не исключение,
    и в кольцо истории он не попадает.
    """
    m = _model([101.0])
    m.ingest(P, {"state": {"fps": 10.0, "latency_ms": None}, "_fresh": _mark(1, 100.0)})

    assert m.read(path, key) == NO_DATA
    assert m.history(f"{P}.state.latency_ms") == []
    assert m.history(f"{P}._fresh.seq") == []


def test_mark_without_incarnation_is_no_data() -> None:
    """Метка без ``incarnation`` — не метка: ответ тот же, что у ``read_value`` над деревом (``no_data``).

    Недостающее поле НЕ подставляется значением ``None``: ключ с ``None`` прошёл бы правило (3)
    классификатора, и писатель без воплощения выглядел бы ``fresh`` там, где дерево скажет ``no_data``.
    """
    m = _model([101.0])
    m.ingest(
        P,
        {"state": {"fps": 10.0}, "_fresh": {"seq": 1, "src_ts": 100.0, "tick_sec": 5.0}},
    )

    assert m.read(P, "state.fps") == NO_DATA


def test_writer_gone_when_incarnation_differs() -> None:
    """``alive_incarnation`` доходит до классификатора: чужое воплощение -> ``writer_gone`` с последним значением."""
    m = _model([101.0])
    m.ingest(P, {"state": {"lat": 25.0}, "_fresh": _mark(1, 100.0, incarnation="a")})

    same = m.read(P, "state.lat", alive_incarnation="a")
    assert same["class"] == "fresh"

    gone = m.read(P, "state.lat", alive_incarnation="b")
    assert gone["class"] == "writer_gone"
    assert gone["value"] == 25.0
    assert gone["age_s"] == pytest.approx(1.0)


def test_stamp_only_update_keeps_fresh() -> None:
    """Живой тик 2+: метка приходит ОТДЕЛЬНЫМИ листьями, и ``fresh`` считается от нового ``src_ts``.

    Первая дельта — dict на корень (метка ``src_ts = 100.0`` внутри). Затем писатель шлёт только
    ``_fresh.seq`` и ``_fresh.src_ts = 105.0``: при ``now = 114.9`` возраст 9.9 -> ``fresh``;
    при ``now = 115.1`` возраст 10.1 -> ``stale``. Читатель, закэшировавший метку с первой
    dict-дельты, ответил бы ``stale`` уже на 114.9 (возраст 14.9).
    """
    now = [0.0]
    m = _model(now)
    m.ingest(P, {"state": {"fps": 10.0}, "_fresh": _mark(1, 100.0)})
    m.ingest(f"{P}._fresh.seq", 2)
    m.ingest(f"{P}._fresh.src_ts", 105.0)

    now[0] = 114.9
    assert m.read(P, "state.fps")["class"] == "fresh"

    now[0] = 115.1
    r = m.read(P, "state.fps")
    assert r["class"] == "stale"
    assert r["age_s"] == pytest.approx(10.1)


def test_read_between_value_and_stamp_deltas() -> None:
    """Между дельтой значения и дельтами метки: новое значение со старой меткой, без исключения.

    Возраст завышен не более чем на такт — безопасное направление; кэшем это не «чинится».
    """
    now = [109.9]
    m = _model(now)
    m.ingest(P, {"state": {"fps": 10.0}, "_fresh": _mark(1, 100.0)})
    m.ingest(f"{P}.state.fps", 11.0)  # значение новое, метка прежняя

    r = m.read(P, "state.fps")
    assert r["class"] == "fresh"
    assert r["value"] == 11.0
    assert r["age_s"] == pytest.approx(9.9)

    now[0] = 110.1  # по прежней метке уже два такта
    assert m.read(P, "state.fps")["class"] == "stale"

    m.ingest(f"{P}._fresh.seq", 2)  # seq новый, src_ts прежний: метка смешанная, но целая
    r = m.read(P, "state.fps")
    assert r["class"] == "stale"
    assert r["value"] == 11.0

    m.ingest(f"{P}._fresh.src_ts", 105.0)
    r = m.read(P, "state.fps")
    assert r["class"] == "fresh"
    assert r["age_s"] == pytest.approx(5.1)


def test_mark_fields_match_the_writer_stamp() -> None:
    """Сторож дрейфа: поля метки, которые собирает ``read``, — ровно поля ``freshness.stamp``.

    Форма метки живёт в ``state_store_module.core.freshness``; ``read`` перечисляет её поля
    у себя (приватное имя оттуда не импортируется). Добавят поле писателю, не тронув читателя —
    красным станет этот тест, а не молчаливое ``no_data`` в проде.
    """
    from multiprocess_framework.modules.state_store_module.core.freshness import stamp
    from multiprocess_framework.modules.telemetry_readmodel_module import telemetry_read_model as trm

    assert set(trm._MARK_FIELDS) == set(stamp(1, 100.0, "a", 5.0))


def test_writer_stamp_is_read_as_fresh() -> None:
    """Поведенческий эквивалент проверки полей: метка, собранная ``freshness.stamp``, читается как ``fresh``.

    Добавят поле писателю, не тронув ``read``, — красным станет и этот тест (ответ ``no_data``),
    а не только проверка приватной константы.
    """
    from multiprocess_framework.modules.state_store_module.core.freshness import stamp

    m = _model([101.0])
    m.ingest(P, {"state": {"fps": 10.0}, "_fresh": stamp(1, 100.0, "a", 5.0)})

    r = m.read(P, "state.fps")
    assert r["class"] == "fresh"
    assert r["value"] == 10.0
    assert r["age_s"] == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# M-16: время точки истории — время источника метки
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("deltas", "expected", "expected_write_seq"),
    [
        pytest.param(
            [
                (P, {"state": {"fps": 10.0}, "_fresh": _mark(1, 100.0)}),
                (f"{P}.state.fps", 11.0),
                (f"{P}._fresh.seq", 2),
                (f"{P}._fresh.src_ts", 105.0),
            ],
            [(100.0, 10.0), (105.0, 11.0)],
            4,
            id="leaf_deltas",
        ),
        pytest.param(
            [
                (f"{P}.state", {"fps": 10.0}),
                (f"{P}._fresh", _mark(1, 100.0)),
            ],
            [(100.0, 10.0)],
            2,
            id="dict_deltas_tick1",
        ),
    ],
)
def test_history_point_uses_source_time(
    deltas: list[tuple[str, Any]], expected: list[tuple[float, float]], expected_write_seq: int
) -> None:
    """Точка ``state.fps`` несёт ``src_ts`` метки своего такта, хотя значение пришло РАНЬШЕ метки.

    Часы read-model всегда ``999.0`` (время приёма): ``999.0`` в истории — значит довыставления нет.
    ``leaf_deltas`` — тик 2+: лист значения, затем листья метки (``11.0`` получает ``105.0``, а не
    ``100.0`` прежней метки). ``dict_deltas_tick1`` — тик 1: dict ``state``, затем dict ``_fresh``.

    ``write_seq`` — по одному на принятую дельту (4 и 2): довыставление счётчик не двигает.
    """
    m = _fixed(999.0)
    for path, value in deltas:
        m.ingest(path, value)

    assert m.history(f"{P}.state.fps") == expected
    assert m.write_seq == expected_write_seq


def test_prime_restamps_tail_too() -> None:
    """``prime`` — тоже push-дорога: значение раньше метки в первичном снимке получает ``src_ts``."""
    m = TelemetryReadModel(
        initial_cache={
            f"{P}.state.fps": 10.0,
            f"{P}._fresh.seq": 1,
            f"{P}._fresh.src_ts": 100.0,
        },
        clock=lambda: 999.0,
    )

    assert m.history(f"{P}.state.fps") == [(100.0, 10.0)]


def test_stamp_of_one_process_does_not_restamp_another() -> None:
    """Хвост — на корень процесса: метка ``cam`` не перекрашивает точки ``cam2``."""
    m = _fixed(999.0)
    m.ingest("processes.cam.state.fps", 10.0)
    m.ingest("processes.cam2.state.fps", 20.0)
    m.ingest("processes.cam._fresh.src_ts", 100.0)

    assert m.history("processes.cam.state.fps") == [(100.0, 10.0)]
    assert m.history("processes.cam2.state.fps") == [(999.0, 20.0)]

    m.ingest("processes.cam2._fresh.src_ts", 200.0)
    assert m.history("processes.cam2.state.fps") == [(200.0, 20.0)]


def test_history_without_stamp_keeps_receipt_time() -> None:
    """СТОРОЖ: метки нет вообще — точка держит время приёма ``999.0`` (иначе краснеют часы и реплей)."""
    m = _fixed(999.0)
    m.ingest(f"{P}.state.fps", 10.0)
    m.ingest(P, {"state": {"fps": 11.0}})

    assert m.history(f"{P}.state.fps") == [(999.0, 10.0), (999.0, 11.0)]


def test_uptime_point_keeps_receipt_time_and_ring_is_chronological() -> None:
    """СТОРОЖ: ``.state.uptime`` пишет ``ProcessMonitor`` (~1 Гц), не писатель метки — время приёма всегда.

    Метка тика ``src_ts = 100.5`` приходит с задержкой доставки, когда часы уже ``103.0``, а
    точки ``uptime`` пришли при ``101.0``, ``102.0``, ``103.0``. Ожидание — ``[101.0, 102.0, 103.0]``.
    Если бы ``uptime`` довыставлялся, последняя точка стала бы ``100.5`` и кольцо перестало быть
    хронологическим. Без задержки доставки проверка хронологии была бы вакуумной.
    """
    now = [101.0]
    m = _model(now)
    m.ingest(f"{P}.state.uptime", 1.0)
    now[0] = 102.0
    m.ingest(f"{P}.state.uptime", 2.0)
    now[0] = 103.0
    m.ingest(f"{P}.state.uptime", 3.0)
    m.ingest(f"{P}._fresh.src_ts", 100.5)

    ring = m.history(f"{P}.state.uptime")
    times = [ts for ts, _ in ring]
    assert times == [101.0, 102.0, 103.0]
    assert times == sorted(times)
    assert [v for _, v in ring] == [1.0, 2.0, 3.0]


@pytest.mark.parametrize(
    "bad",
    [None, "x", float("nan"), float("inf"), True, 10**400],
    ids=["none", "str", "nan", "inf", "bool", "huge_int"],
)
def test_unusable_source_time_keeps_receipt_time(bad: Any) -> None:
    """СТОРОЖ: ``src_ts`` не конечное число — довыставления нет, точка остаётся на времени приёма.

    ``bool`` — не число (как у ``freshness``); ``10**400`` — ``int`` вне диапазона ``float``
    (``float()`` бросает ``OverflowError``): исключение в потоке приёма уронило бы весь снимок.
    """
    m = _fixed(999.0)
    m.ingest(P, {"state": {"fps": 10.0}, "_fresh": _mark(1, bad)})

    assert m.history(f"{P}.state.fps") == [(999.0, 10.0)]


def test_level_sources_do_not_restamp_history() -> None:
    """Инвариант 1: опрос и ``record_history=False`` отдают УРОВЕНЬ, а не точку потока — кольцо не трогают.

    Метка, пришедшая этими дорогами, хвост не довыставляет: точка потока остаётся на времени приёма.
    """
    m = _fixed(999.0)
    m.ingest(f"{P}.state.fps", 10.0)

    m.ingest_poll_snapshot({f"{P}._fresh.src_ts": 100.0}, requested_at_seq=m.write_seq)
    m.ingest(f"{P}._fresh.src_ts", 100.0, record_history=False)

    assert m.history(f"{P}.state.fps") == [(999.0, 10.0)]

    m.ingest(f"{P}._fresh.src_ts", 105.0)  # поток: хвост довыставляется
    assert m.history(f"{P}.state.fps") == [(105.0, 10.0)]


def test_tick_with_only_a_stamp_keeps_the_previous_point() -> None:
    """Главное свойство довыставления: такт только с меткой (без значений) прежнюю точку не двигает.

    Самый частый живой случай: ``TreeStore.set`` отдаёт ``None`` для неизменного значения, и
    на такте приходят только ``_fresh.seq`` и ``_fresh.src_ts``. Точка принадлежит такту, в
    котором значение записано (``100.0``), а не последующим тактам без значений
    (``105.0``, ``110.0``): хвост после довыставления очищается.
    """
    m = _fixed(999.0)
    m.ingest(P, {"state": {"fps": 10.0}, "_fresh": _mark(1, 100.0)})
    m.ingest(f"{P}._fresh.seq", 2)
    m.ingest(f"{P}._fresh.src_ts", 105.0)
    m.ingest(f"{P}._fresh.seq", 3)
    m.ingest(f"{P}._fresh.src_ts", 110.0)

    assert m.history(f"{P}.state.fps") == [(100.0, 10.0)]


def test_restamp_does_not_move_the_poll_guard_boundary() -> None:
    """Довыставление не трогает ``_push_seq``: путь с номером ``== requested_at_seq`` по-прежнему вливается.

    Значение (``push_seq == seq``), затем приходит метка и довыставляет точку, затем ответ опроса,
    снятый на номере ``seq``. Если бы довыставление переписало ``push_seq`` пути текущим счётчиком,
    ответ был бы отброшен как «push позже запроса» (инвариант 2).
    """
    m = _fixed(999.0)
    m.ingest(f"{P}.state.fps", 10.0)
    seq = m.write_seq
    m.ingest(f"{P}._fresh.src_ts", 100.0)
    assert m.history(f"{P}.state.fps") == [(100.0, 10.0)]  # довыставление произошло

    applied = m.ingest_poll_snapshot({f"{P}.state.fps": 5.0}, requested_at_seq=seq)

    assert applied == [f"{P}.state.fps"]
    assert m.get(f"{P}.state.fps") == 5.0


def test_stamp_before_values_stamps_the_next_tick() -> None:
    """ПРЕДЕЛ (зафиксирован): метка РАНЬШЕ значений — точка такта N получает время такта N+1.

    Порядок живого тика обратный (значения раньше метки), и механизм построен на нём. Если порядок
    перевернётся, точка такта получит ``src_ts`` СЛЕДУЮЩЕЙ метки, а последняя точка останется на
    времени приёма (``999.0``). Тест не одобряет такой порядок, а фиксирует последствие.
    """
    m = _fixed(999.0)
    m.ingest(f"{P}._fresh.src_ts", 100.0)
    m.ingest(f"{P}.state.fps", 11.0)
    m.ingest(f"{P}._fresh.src_ts", 105.0)
    m.ingest(f"{P}.state.fps", 12.0)
    m.ingest(f"{P}._fresh.src_ts", 110.0)
    m.ingest(f"{P}.state.fps", 13.0)

    assert m.history(f"{P}.state.fps") == [(105.0, 11.0), (110.0, 12.0), (999.0, 13.0)]


@pytest.mark.parametrize("bad", [10**400, True], ids=["huge_int", "bool"])
def test_unusable_source_time_as_a_leaf_does_not_break_the_delta(bad: Any) -> None:
    """``src_ts`` листом негоден — довыставление молчит, а дельта применена, как обычная запись значения.

    Ни исключения (``float(10**400)`` -> ``OverflowError``), ни частично применённой дельты: лист в
    снимке, счётчик сдвинут на 1 за каждую дельту, точка значения на времени приёма, ``read`` — ``no_data``.
    """
    m = _fixed(999.0)
    m.ingest(f"{P}.state.fps", 10.0)
    m.ingest(f"{P}._fresh.src_ts", bad)  # не должно бросить

    assert m.get(f"{P}._fresh.src_ts") is bad
    assert m.write_seq == 2
    assert m.history(f"{P}.state.fps") == [(999.0, 10.0)]
    assert m.read(P, "state.fps") == NO_DATA


# --------------------------------------------------------------------------- #
# Хвост не течёт (тот же класс утечки, что у _push_seq)
# --------------------------------------------------------------------------- #
def test_stamp_tail_is_cleared_with_the_subtree() -> None:
    """Писатель, никогда не шлющий метку, не растит хвост: он чистится там же, где уходит кольцо.

    Приватный ``_stamp_tail`` проверяется так же, как ``_push_seq`` в
    ``test_write_seq_ordering_hazards.py``: утечка медленная и без симптома.
    """
    m = _fixed(999.0)
    for i in range(50):
        m.ingest(f"processes.p{i}.state.fps", 1.0)
    assert len(m._stamp_tail) == 50, "предпосылка: пути ждут метку"

    for i in range(50):
        m.ingest(f"processes.p{i}", None, deleted=True)

    assert m._stamp_tail == {}, f"осталось: {sorted(m._stamp_tail)[:5]}"


def test_stamp_tail_forgets_leaves_removed_by_a_subtree_replace() -> None:
    """Dict-дельта, снявшая лист, убирает его из хвоста; метка потом приходит без ошибки."""
    m = _fixed(999.0)
    m.ingest(P, {"state": {"fps": 1.0, "latency_ms": 2.0}})
    m.ingest(P, {"state": {"latency_ms": 3.0}})  # state.fps снят вместе с кольцом

    assert m.history(f"{P}.state.fps") == []
    assert m._stamp_tail == {P: {f"{P}.state.latency_ms"}}

    m.ingest(f"{P}._fresh.src_ts", 100.0)  # довыставление терпит снятые пути

    assert m.history(f"{P}.state.fps") == []
    assert m.history(f"{P}.state.latency_ms") == [(999.0, 2.0), (100.0, 3.0)]
    assert m._stamp_tail == {}


@pytest.mark.parametrize(
    ("deleted", "gone", "left"),
    [
        pytest.param("processes.p.state", "processes.p.state.fps", {"processes.p.workers.w1.effective_hz"}, id="state"),
        pytest.param(
            "processes.p.workers.w1", "processes.p.workers.w1.effective_hz", {"processes.p.state.fps"}, id="worker"
        ),
    ],
)
def test_stamp_tail_forgets_a_subtree_deleted_below_the_root(deleted: str, gone: str, left: set[str]) -> None:
    """``deleted=True`` на узел НИЖЕ корня убирает из хвоста пути этого узла, соседей не трогает.

    Чистка «только по ключу корня» (``processes.p``) пропустила бы оба случая: удаление корня
    покрывает ``test_stamp_tail_is_cleared_with_the_subtree``, а живьём уходят ``state`` и воркер.
    Приватный ``_stamp_tail`` — как ``_push_seq``: наблюдаемого следствия утечки снаружи нет.
    """
    m = _fixed(999.0)
    m.ingest("processes.p.state.fps", 1.0)
    m.ingest("processes.p.workers.w1.effective_hz", 2.0)
    assert m._stamp_tail == {"processes.p": {"processes.p.state.fps", "processes.p.workers.w1.effective_hz"}}

    m.ingest(deleted, None, deleted=True)

    assert m._stamp_tail == {"processes.p": left}
    assert m.history(gone) == []

    m.ingest("processes.p._fresh.src_ts", 100.0)  # довыставление терпит удалённое поддерево
    assert m._stamp_tail == {}
