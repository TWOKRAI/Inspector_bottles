# -*- coding: utf-8 -*-
"""Task 4.7c — слепые приёмочные тесты проводки бюджета в полёте в ``build_configs()``.

Переделка по вердикту CTO (docs/reviews/2026-10-01_task-4.7-cto-verdict.md, условия C2/C3 и «провод»).

Правило одно для всех узлов: процесс, получающий кадры от ЛЮБОГО писателя кольца (generic через
``chain_targets`` или wire), после ``SystemBlueprint.build_configs()`` получает ``chain_max_lag_items``
= lag (по умолчанию 2; B = min(глубин колец писателей) - 2, явный lag допустим, пока lag <= B - 2),
а IPC data-очередь остаётся ПОТОЛКОМ ПАМЯТИ **50 у всех** (C2): топология больше не выводит
``data_queue_maxsize`` из бюджета. Явный ``extras.data_queue_maxsize`` принимается как есть (это cap),
ошибки «очередь больше кольца» нет. Часть B - lag читается как транзитный запас и ИЗМЕРЯЕТСЯ
приёмником (``transit_over_budget``, см. test_t47c_frame_aware_bound.py), а не навязывается maxsize.

Допущение (место размера очереди не зафиксировано дизайном): размер data-очереди смотрим там, где
он живёт сегодня и откуда его читает спавн процесса — ``proc_dict["queues"]["data"]["maxsize"]``
из ``GenericProcessConfig.build()``; потолок отставания — ``proc_dict["config"]["chain_max_lag_items"]``
(то, что читает GenericProcess). Ключи рецепта — в ``extras`` процесса:
``frame_ring_depth``, ``chain_max_lag_items``, ``data_queue_maxsize`` (новый).

Все тесты — через настоящий SystemBlueprint (без фейков).
"""

from __future__ import annotations

import pytest

from ..topology.blueprint import ProcessConfig, SystemBlueprint, Wire


def _build(processes: list[ProcessConfig], wires: list[Wire] | None = None) -> dict[str, dict]:
    """build_configs() настоящего чертежа -> {process_name: proc_dict} (то, что уходит в спавн)."""
    bp = SystemBlueprint(name="t47c", processes=processes, wires=wires or [])
    built = {}
    for cfg in bp.build_configs():
        name, proc_dict = cfg.build()
        built[name] = proc_dict
    return built


def _data_queue(proc_dict: dict) -> int:
    return proc_dict["queues"]["data"]["maxsize"]


def _lag(proc_dict: dict) -> int:
    return proc_dict["config"].get("chain_max_lag_items", 0)


def test_reader_behind_generic_writer_50_2():
    """Писатель без настройки глубины (дефолт кольца 8) -> получатель: очередь 50 (cap), lag 2."""
    built = _build(
        [
            ProcessConfig(process_name="cam", chain_targets=["det"]),
            ProcessConfig(process_name="det"),
        ]
    )
    assert _data_queue(built["det"]) == 50
    assert _lag(built["det"]) == 2


def test_reader_queue_stays_50():
    """frame_ring_depth: 12 у писателя -> очередь по-прежнему 50 (старая модель выводила 8), lag 2.

    Половина «очередь 50» зелёная и сегодня (дефолт процесса); красным тест делает вторая половина —
    lag 2 из бюджета до реализации не выводится. Вместе они ловят и «ничего не сделали», и «оставили
    старую модель B - lag» (очередь 8)."""
    built = _build(
        [
            ProcessConfig(process_name="cam", chain_targets=["det"], extras={"frame_ring_depth": 12}),
            ProcessConfig(process_name="det"),
        ]
    )
    assert _data_queue(built["det"]) == 50
    assert _lag(built["det"]) == 2


def test_two_writers_depth_8_and_12_give_queue_50_lag_2():
    """Два писателя в один процесс, глубины 8 и 12 -> бюджет по минимуму (D = 8, B = 6): lag 2; очередь 50."""
    built = _build(
        [
            ProcessConfig(process_name="cam_a", chain_targets=["det"], extras={"frame_ring_depth": 8}),
            ProcessConfig(process_name="cam_b", chain_targets=["det"], extras={"frame_ring_depth": 12}),
            ProcessConfig(process_name="det"),
        ]
    )
    assert _data_queue(built["det"]) == 50
    assert _lag(built["det"]) == 2


def test_reader_behind_wire_50_2():
    """Процесс, которому кадры приходят по wire (приёмник wire-кольца), тоже «за писателем кольца»:
    у wire нет chain_targets на этом пути, и правило обязано сработать так же — очередь 50, lag 2."""
    built = _build(
        [
            ProcessConfig(process_name="src"),
            ProcessConfig(process_name="dst"),
        ],
        wires=[Wire(source="src.capture.frame", target="dst.detect.frame")],
    )
    assert _data_queue(built["dst"]) == 50
    assert _lag(built["dst"]) == 2


def test_every_hop_of_a_chain_gets_lag_2_and_all_queues_are_50():
    """cam -> det -> disp: и det (за cam), и disp (за det) получают lag 2 — одно правило для всех
    узлов, не только для первого хопа; очередь у всех 50, у головы цепочки (без входа) lag нет."""
    built = _build(
        [
            ProcessConfig(process_name="cam", chain_targets=["det"]),
            ProcessConfig(process_name="det", chain_targets=["disp"]),
            ProcessConfig(process_name="disp"),
        ]
    )
    assert (_data_queue(built["det"]), _lag(built["det"])) == (50, 2)
    assert (_data_queue(built["disp"]), _lag(built["disp"])) == (50, 2)
    assert (_data_queue(built["cam"]), _lag(built["cam"])) == (50, 0)


def test_explicit_lag_valid_iff_at_most_b_minus_2():
    """Кольцо 8 -> B = 6 -> явный chain_max_lag_items допустим до B - 2 = 4 включительно.
    lag 4 (граница) собирается: lag 4, очередь 50. lag 5 (на единицу больше) -> ValueError при сборке.

    Красное сегодня из-за второй половины: явный lag никто не проверяет, lag 5 собирается молча
    (``pytest.raises`` тут не переворачивает полярность: вызов СЕГОДНЯ не бросает -> DID NOT RAISE).
    Текст ошибки не пинится — дизайн его не задаёт."""
    base = [ProcessConfig(process_name="cam", chain_targets=["det"])]

    ok = _build(base + [ProcessConfig(process_name="det", extras={"chain_max_lag_items": 4})])
    assert (_data_queue(ok["det"]), _lag(ok["det"])) == (50, 4)

    with pytest.raises(ValueError):
        _build(base + [ProcessConfig(process_name="det", extras={"chain_max_lag_items": 5})])


def test_explicit_queue_4_within_budget_is_kept():
    """Явная data_queue_maxsize: 4 принимается как есть (cap), lag 2 из бюджета кольца 8."""
    built = _build(
        [
            ProcessConfig(process_name="cam", chain_targets=["det"]),
            ProcessConfig(process_name="det", extras={"data_queue_maxsize": 4}),
        ]
    )
    assert _data_queue(built["det"]) == 4
    assert _lag(built["det"]) == 2


def test_explicit_queue_is_cap_no_error():
    """Явная data_queue_maxsize: 20 при кольце 8 -> сборка БЕЗ ошибки, очередь ровно 20 (cap рецепта),
    lag 2. Старая модель давала ошибку «очередь 20 больше кольца 8»; сегодня ключ молча теряется
    (extra=ignore) и очередь остаётся 50 — отсюда красное."""
    built = _build(
        [
            ProcessConfig(process_name="cam", chain_targets=["det"]),
            ProcessConfig(process_name="det", extras={"data_queue_maxsize": 20}),
        ]
    )
    assert _data_queue(built["det"]) == 20
    assert _lag(built["det"]) == 2


def test_wire_depth_from_source_ring_12():
    """phone_sketch-подобный чертёж: источник с frame_ring_depth 12 имеет И chain_targets, И порт-провод
    к тому же получателю. Глубина для получателя берётся из кольца ИСТОЧНИКА (12 -> D = 12, B = 10),
    а не дефолт 8 (B = 6) — иначе ручка глубины писателя мертва из-за провода (повтор CTO:
    ``wires=True -> lag=2`` при ``wires=False`` та же глубина давала B = 10).

    Свойство одно — «провод читает кольцо источника» — наблюдается двумя сборками в одном тесте
    (по отдельности первая зелёная и сегодня: явный lag пока никто не проверяет):
      а) явный chain_max_lag_items 5 допустим только при B = 10 (5 <= B - 2 = 8); при ошибочном B = 6
         предел 4 -> сборка отвергнет значение (ValueError) -> красно и для «реализации с багом провода»;
      б) без явного lag получатель получает lag 2 (красное и сегодня: lag не выводится) и очередь 50."""

    def procs(extras: dict) -> list[ProcessConfig]:
        return [
            ProcessConfig(process_name="camera_0", chain_targets=["seg"], extras={"frame_ring_depth": 12}),
            ProcessConfig(process_name="seg", extras=extras),
        ]

    wires = [Wire(source="camera_0.capture.frame", target="seg.segment.frame")]

    explicit = _build(procs({"chain_max_lag_items": 5}), wires)
    assert _lag(explicit["seg"]) == 5

    default = _build(procs({}), wires)
    assert _lag(default["seg"]) == 2
    assert _data_queue(default["seg"]) == 50


def test_process_without_ring_input_keeps_50():
    """GREEN по построению (контроль): процесс без входа от писателя кольца сохраняет data-очередь
    50 и не получает lag; писатель — тоже (у него нет входа). Должен остаться зелёным и после
    реализации."""
    built = _build(
        [
            ProcessConfig(process_name="cam", chain_targets=["det"]),
            ProcessConfig(process_name="det"),
            ProcessConfig(process_name="loner"),
        ]
    )
    assert _data_queue(built["loner"]) == 50
    assert _lag(built["loner"]) == 0
    assert _data_queue(built["cam"]) == 50
