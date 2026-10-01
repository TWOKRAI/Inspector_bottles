# -*- coding: utf-8 -*-
"""Task 4.7c — тесты автора на опасные места механизма бюджета «в полёте».

Слепой tester писал по критериям приёмки; здесь то, что видно только изнутри построения
``_apply_inflight_budgets``: обход топологии с циклами, один писатель на двух читателей с разными
явными бюджетами, несколько камер, не влияющих друг на друга, и ловушка «lag 0 = без границы».
Ожидаемые значения — литералы.
"""

from __future__ import annotations

import threading

import pytest

from ..topology.blueprint import ProcessConfig, SystemBlueprint


def _built(processes: list[ProcessConfig]) -> dict[str, dict]:
    bp = SystemBlueprint(name="t47c_hazard", processes=processes)
    return dict(cfg.build() for cfg in bp.build_configs())


def _queue(proc_dict: dict) -> int:
    return proc_dict["queues"]["data"]["maxsize"]


def _lag(proc_dict: dict) -> int:
    return proc_dict["config"].get("chain_max_lag_items", 0)


def _build_with_deadline(processes: list[ProcessConfig], seconds: float = 10.0) -> dict[str, dict]:
    """Сборка в демон-потоке с дедлайном: бесконечный обход упал бы тестом, а не повесил сьют."""
    box: dict = {}

    def run() -> None:
        try:
            box["built"] = _built(processes)
        except BaseException as exc:  # noqa: BLE001 — пробрасываем в основной поток
            box["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(seconds)
    assert not thread.is_alive(), "build_configs() завис на топологии с циклом"
    if "error" in box:
        raise box["error"]
    return box["built"]


def test_cycle_between_processes_does_not_loop():
    """a -> b -> a: обход один проход по chain_targets, не граф-обход; оба получают 4/2."""
    built = _build_with_deadline(
        [
            ProcessConfig(process_name="a", chain_targets=["b"]),
            ProcessConfig(process_name="b", chain_targets=["a"]),
        ]
    )
    assert (_queue(built["a"]), _lag(built["a"])) == (4, 2)
    assert (_queue(built["b"]), _lag(built["b"])) == (4, 2)


def test_self_feed_does_not_loop():
    """Процесс, адресующий самого себя, — писатель собственного входа: 4/2, без зависания."""
    built = _build_with_deadline([ProcessConfig(process_name="loop", chain_targets=["loop"])])
    assert (_queue(built["loop"]), _lag(built["loop"])) == (4, 2)


def test_hierarchical_target_address_counts_as_reader():
    """``det.worker`` адресует процесс ``det``: судится первый сегмент, как в _unaddressable_chain_targets."""
    built = _build_with_deadline(
        [
            ProcessConfig(process_name="cam", chain_targets=["det.worker"]),
            ProcessConfig(process_name="det"),
        ]
    )
    assert (_queue(built["det"]), _lag(built["det"])) == (4, 2)


def test_writer_feeding_two_readers_with_different_explicit_budgets():
    """Один писатель (кольцо 12) -> два читателя: у каждого свой явный бюджет, друг друга не трогают.

    r_small: явная очередь 2 -> (2, 2); r_big: явный lag 3 -> очередь добирается 10 - 3 = 7.
    """
    built = _build_with_deadline(
        [
            ProcessConfig(process_name="cam", chain_targets=["r_small", "r_big"], extras={"frame_ring_depth": 12}),
            ProcessConfig(process_name="r_small", extras={"data_queue_maxsize": 2}),
            ProcessConfig(process_name="r_big", extras={"chain_max_lag_items": 3}),
        ]
    )
    assert (_queue(built["r_small"]), _lag(built["r_small"])) == (2, 2)
    assert (_queue(built["r_big"]), _lag(built["r_big"])) == (7, 3)


def test_one_readers_bad_explicit_queue_names_that_reader_only():
    """Ошибка явной очереди называет ИМЕННО провинившегося читателя, а не соседа с тем же писателем."""
    bp = SystemBlueprint(
        name="t47c_hazard",
        processes=[
            ProcessConfig(process_name="cam", chain_targets=["good", "bad"]),
            ProcessConfig(process_name="good"),
            ProcessConfig(process_name="bad", extras={"data_queue_maxsize": 30}),
        ],
    )
    with pytest.raises(ValueError, match="очередь 30 больше кольца 8") as exc:
        bp.build_configs()
    assert "'bad'" in str(exc.value)
    assert "'good'" not in str(exc.value)


def test_three_cameras_each_reader_budget_from_its_own_writer_only():
    """Камеры 8, 8 и 12 кормят три РАЗНЫХ читателя: бюджет каждого — по своему писателю.

    Читатель камеры 12 получает 8/2, а не 4/2 от соседей с кольцом 8 (владелец: несколько камер
    не должны влиять друг на друга).
    """
    built = _build_with_deadline(
        [
            ProcessConfig(process_name="cam_a", chain_targets=["det_a"], extras={"frame_ring_depth": 8}),
            ProcessConfig(process_name="cam_b", chain_targets=["det_b"], extras={"frame_ring_depth": 8}),
            ProcessConfig(process_name="cam_c", chain_targets=["det_c"], extras={"frame_ring_depth": 12}),
            ProcessConfig(process_name="det_a"),
            ProcessConfig(process_name="det_b"),
            ProcessConfig(process_name="det_c"),
        ]
    )
    assert (_queue(built["det_a"]), _lag(built["det_a"])) == (4, 2)
    assert (_queue(built["det_b"]), _lag(built["det_b"])) == (4, 2)
    assert (_queue(built["det_c"]), _lag(built["det_c"])) == (8, 2)


def test_derived_lag_is_never_zero_behind_a_ring():
    """Ловушка: chain_max_lag_items == 0 в DataReceiver = «без границы». Читатель за кольцом
    любой допустимой глубины (4..12) получает lag >= 1 — в том числе на границе 4 (1, 1)."""
    for depth, expected in [(4, (1, 1)), (5, (1, 2)), (8, (4, 2)), (12, (8, 2))]:
        built = _build_with_deadline(
            [
                ProcessConfig(process_name="cam", chain_targets=["det"], extras={"frame_ring_depth": depth}),
                ProcessConfig(process_name="det"),
            ]
        )
        assert (_queue(built["det"]), _lag(built["det"])) == expected, depth
        assert _lag(built["det"]) >= 1


def test_writer_ring_below_4_fails_build_with_reader_name():
    """Писатель с кольцом 3 в рецепте: сборка падает и называет читателя (кому не хватило места)."""
    bp = SystemBlueprint(
        name="t47c_hazard",
        processes=[
            ProcessConfig(process_name="cam", chain_targets=["det"], extras={"frame_ring_depth": 3}),
            ProcessConfig(process_name="det"),
        ],
    )
    with pytest.raises(ValueError, match="'det'"):
        bp.build_configs()


def test_second_build_is_idempotent():
    """build_configs() дважды на одном чертеже даёт одно и то же: вывод бюджета не пишет в
    ProcessConfig (ни в extras, ни в поля), иначе второй вызов принял бы выведенное за явное."""
    bp = SystemBlueprint(
        name="t47c_hazard",
        processes=[
            ProcessConfig(process_name="cam", chain_targets=["det"], extras={"frame_ring_depth": 12}),
            ProcessConfig(process_name="det"),
        ],
    )
    first = {name: (_queue(d), _lag(d)) for name, d in (c.build() for c in bp.build_configs())}
    second = {name: (_queue(d), _lag(d)) for name, d in (c.build() for c in bp.build_configs())}
    assert first == second
    assert first["det"] == (8, 2)
    assert bp.processes[1].extras == {}
