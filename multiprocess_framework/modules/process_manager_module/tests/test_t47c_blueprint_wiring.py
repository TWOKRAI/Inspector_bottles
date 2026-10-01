# -*- coding: utf-8 -*-
"""Task 4.7c — слепые приёмочные тесты проводки бюджета в полёте в ``build_configs()``.

Правило одно для всех узлов: процесс, получающий кадры от ЛЮБОГО писателя кольца (generic через
``chain_targets`` или wire), после ``TopologyBlueprint.build_configs()`` получает data-очередь
``B - lag`` и ``chain_max_lag_items`` = lag, где B = min(глубин колец писателей) - 2.
Процесс без входа от писателя кольца сохраняет прежнюю data-очередь 50.

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


@pytest.mark.xfail(strict=True, reason="RED-спека 4.7c, переделка по вердикту CTO")
def test_reader_behind_generic_writer_4_2():
    """Писатель без настройки глубины (дефолт кольца 8) -> получатель: очередь 4, lag 2."""
    built = _build(
        [
            ProcessConfig(process_name="cam", chain_targets=["det"]),
            ProcessConfig(process_name="det"),
        ]
    )
    assert _data_queue(built["det"]) == 4
    assert _lag(built["det"]) == 2


@pytest.mark.xfail(strict=True, reason="RED-спека 4.7c, переделка по вердикту CTO")
def test_writer_depth12_reader_8_2():
    """frame_ring_depth: 12 у писателя -> очередь 8, lag 2."""
    built = _build(
        [
            ProcessConfig(process_name="cam", chain_targets=["det"], extras={"frame_ring_depth": 12}),
            ProcessConfig(process_name="det"),
        ]
    )
    assert _data_queue(built["det"]) == 8
    assert _lag(built["det"]) == 2


@pytest.mark.xfail(strict=True, reason="RED-спека 4.7c, переделка по вердикту CTO")
def test_two_writers_depth_8_and_12_give_queue_4():
    """Два писателя в один процесс, глубины 8 и 12 -> бюджет по минимуму: очередь 4, lag 2."""
    built = _build(
        [
            ProcessConfig(process_name="cam_a", chain_targets=["det"], extras={"frame_ring_depth": 8}),
            ProcessConfig(process_name="cam_b", chain_targets=["det"], extras={"frame_ring_depth": 12}),
            ProcessConfig(process_name="det"),
        ]
    )
    assert _data_queue(built["det"]) == 4
    assert _lag(built["det"]) == 2


@pytest.mark.xfail(strict=True, reason="RED-спека 4.7c, переделка по вердикту CTO")
def test_reader_behind_wire_4_2():
    """Процесс, которому кадры приходят по wire (приёмник wire-кольца), тоже «за писателем кольца»:
    у wire нет chain_targets на этом пути, и правило обязано сработать так же — очередь 4, lag 2."""
    built = _build(
        [
            ProcessConfig(process_name="src"),
            ProcessConfig(process_name="dst"),
        ],
        wires=[Wire(source="src.capture.frame", target="dst.detect.frame")],
    )
    assert _data_queue(built["dst"]) == 4
    assert _lag(built["dst"]) == 2


@pytest.mark.xfail(strict=True, reason="RED-спека 4.7c, переделка по вердикту CTO")
def test_every_hop_of_a_chain_gets_4_2_and_the_head_keeps_50():
    """cam -> det -> disp: и det (за cam), и disp (за det) получают 4/2 — одно правило для всех
    узлов, не только для первого хопа; голова цепочки без входа сохраняет 50."""
    built = _build(
        [
            ProcessConfig(process_name="cam", chain_targets=["det"]),
            ProcessConfig(process_name="det", chain_targets=["disp"]),
            ProcessConfig(process_name="disp"),
        ]
    )
    assert (_data_queue(built["det"]), _lag(built["det"])) == (4, 2)
    assert (_data_queue(built["disp"]), _lag(built["disp"])) == (4, 2)
    assert _data_queue(built["cam"]) == 50


@pytest.mark.xfail(strict=True, reason="RED-спека 4.7c, переделка по вердикту CTO")
def test_explicit_lag_3_gives_queue_3_lag_3():
    """Явный chain_max_lag_items: 3 у получателя при кольце 8 -> очередь добирается до 3 (6 - 3)."""
    built = _build(
        [
            ProcessConfig(process_name="cam", chain_targets=["det"]),
            ProcessConfig(process_name="det", extras={"chain_max_lag_items": 3}),
        ]
    )
    assert _data_queue(built["det"]) == 3
    assert _lag(built["det"]) == 3


@pytest.mark.xfail(strict=True, reason="RED-спека 4.7c, переделка по вердикту CTO")
def test_explicit_queue_4_within_budget_is_kept():
    """Явная data_queue_maxsize: 4 при кольце 8 (4 + lag 2 = 6 = бюджет) принимается как есть."""
    built = _build(
        [
            ProcessConfig(process_name="cam", chain_targets=["det"]),
            ProcessConfig(process_name="det", extras={"data_queue_maxsize": 4}),
        ]
    )
    assert _data_queue(built["det"]) == 4
    assert _lag(built["det"]) == 2


@pytest.mark.xfail(strict=True, reason="RED-спека 4.7c, переделка по вердикту CTO")
def test_explicit_queue_20_build_error():
    """Явная data_queue_maxsize: 20 при кольце 8 -> ошибка сборки «очередь 20 больше кольца 8»
    с именем процесса. Раньше ключ молча терялся (extra=ignore) и сборка проходила."""
    bp = SystemBlueprint(
        name="t47c",
        processes=[
            ProcessConfig(process_name="cam", chain_targets=["det"]),
            ProcessConfig(process_name="det", extras={"data_queue_maxsize": 20}),
        ],
    )
    with pytest.raises(ValueError, match="очередь 20 больше кольца 8") as exc:
        bp.build_configs()
    assert "det" in str(exc.value)


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
