# -*- coding: utf-8 -*-
"""Task 4.7c — тесты автора на опасные места механизма бюджета «в полёте».

Слепой tester писал по критериям приёмки; здесь то, что видно только изнутри построения
``_apply_inflight_budgets``: обход топологии с циклами, один писатель на двух читателей с разными
явными значениями, несколько камер, не влияющих друг на друга, и ловушка «lag 0 = без границы».
Контракт после переделки по вердикту CTO (C2/C3): топология пишет только ``chain_max_lag_items``
и ``inflight_budget`` (B = D - 2), data-очередь остаётся потолком памяти (50 или явный из рецепта).
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


def _budget(proc_dict: dict) -> int:
    return proc_dict["config"].get("inflight_budget", 0)


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
    """a -> b -> a: обход один проход по chain_targets, не граф-обход; оба получают очередь 50, lag 2."""
    built = _build_with_deadline(
        [
            ProcessConfig(process_name="a", chain_targets=["b"]),
            ProcessConfig(process_name="b", chain_targets=["a"]),
        ]
    )
    assert (_queue(built["a"]), _lag(built["a"])) == (50, 2)
    assert (_queue(built["b"]), _lag(built["b"])) == (50, 2)


def test_self_feed_does_not_loop():
    """Процесс, адресующий самого себя, — писатель собственного входа: 50/2, без зависания."""
    built = _build_with_deadline([ProcessConfig(process_name="loop", chain_targets=["loop"])])
    assert (_queue(built["loop"]), _lag(built["loop"])) == (50, 2)


def test_hierarchical_target_address_counts_as_reader():
    """``det.worker`` адресует процесс ``det``: судится первый сегмент, как в _unaddressable_chain_targets."""
    built = _build_with_deadline(
        [
            ProcessConfig(process_name="cam", chain_targets=["det.worker"]),
            ProcessConfig(process_name="det"),
        ]
    )
    assert (_queue(built["det"]), _lag(built["det"])) == (50, 2)


def test_writer_feeding_two_readers_with_different_explicit_budgets():
    """Один писатель (кольцо 12) -> два читателя: у каждого своё явное значение, друг друга не трогают.

    r_small: явная очередь 2 = потолок памяти -> (2, lag 2); r_big: явный lag 3 -> (очередь 50, lag 3).
    """
    built = _build_with_deadline(
        [
            ProcessConfig(process_name="cam", chain_targets=["r_small", "r_big"], extras={"frame_ring_depth": 12}),
            ProcessConfig(process_name="r_small", extras={"data_queue_maxsize": 2}),
            ProcessConfig(process_name="r_big", extras={"chain_max_lag_items": 3}),
        ]
    )
    assert (_queue(built["r_small"]), _lag(built["r_small"])) == (2, 2)
    assert (_queue(built["r_big"]), _lag(built["r_big"])) == (50, 3)


def test_explicit_queue_of_one_reader_does_not_touch_the_neighbour():
    """Явный потолок памяти 30 у одного читателя (кольцо 8) — не ошибка (C2) и соседа с тем же
    писателем не задевает: у good остаётся 50."""
    built = _build_with_deadline(
        [
            ProcessConfig(process_name="cam", chain_targets=["good", "bad"]),
            ProcessConfig(process_name="good"),
            ProcessConfig(process_name="bad", extras={"data_queue_maxsize": 30}),
        ]
    )
    assert (_queue(built["bad"]), _lag(built["bad"])) == (30, 2)
    assert (_queue(built["good"]), _lag(built["good"])) == (50, 2)


def test_one_readers_bad_explicit_lag_names_that_reader_only():
    """Явный lag 5 при кольце 8 (B = 6, предел B - 2 = 4): ошибка называет ИМЕННО провинившегося."""
    bp = SystemBlueprint(
        name="t47c_hazard",
        processes=[
            ProcessConfig(process_name="cam", chain_targets=["good", "bad"]),
            ProcessConfig(process_name="good"),
            ProcessConfig(process_name="bad", extras={"chain_max_lag_items": 5}),
        ],
    )
    with pytest.raises(ValueError) as exc:
        bp.build_configs()
    assert "'bad'" in str(exc.value)
    assert "'good'" not in str(exc.value)


def test_explicit_lag_on_ring_4_is_always_an_error():
    """Кольцо 4 -> B = 2 -> предел явного lag B - 2 = 0: допустимого явного значения нет вовсе
    (выведенный по умолчанию lag 1 при этом собирается — граница D = 4 жива)."""
    base = [ProcessConfig(process_name="cam", chain_targets=["det"], extras={"frame_ring_depth": 4})]
    built = _build_with_deadline(base + [ProcessConfig(process_name="det")])
    assert (_queue(built["det"]), _lag(built["det"]), _budget(built["det"])) == (50, 1, 2)
    for lag in (1, 2):
        bp = SystemBlueprint(
            name="t47c_hazard",
            processes=base + [ProcessConfig(process_name="det", extras={"chain_max_lag_items": lag})],
        )
        with pytest.raises(ValueError, match="'det'"):
            bp.build_configs()


def test_three_cameras_each_reader_budget_from_its_own_writer_only():
    """Камеры 8, 8 и 12 кормят три РАЗНЫХ читателя: бюджет каждого — по своему писателю.

    Читатель камеры 12 получает B = 10, а не 6 от соседей с кольцом 8 (владелец: несколько камер
    не должны влиять друг на друга); очередь у всех 50, lag 2.
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
    assert (_queue(built["det_a"]), _lag(built["det_a"]), _budget(built["det_a"])) == (50, 2, 6)
    assert (_queue(built["det_b"]), _lag(built["det_b"]), _budget(built["det_b"])) == (50, 2, 6)
    assert (_queue(built["det_c"]), _lag(built["det_c"]), _budget(built["det_c"])) == (50, 2, 10)


def test_derived_lag_is_never_zero_behind_a_ring():
    """Ловушка: chain_max_lag_items == 0 в DataReceiver = «без границы». Читатель за кольцом
    любой допустимой глубины (4..12) получает lag >= 1 — в том числе на границе 4 (lag 1)."""
    for depth, expected in [(4, (50, 1)), (5, (50, 2)), (8, (50, 2)), (12, (50, 2))]:
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
    ProcessConfig (ни в extras, ни в поля), иначе второй вызов принял бы выведенное за явное
    (выведенный lag 2 стал бы «явным», а при смене кольца не пересчитался бы)."""
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
    assert first["det"] == (50, 2)
    assert _budget(dict(c.build() for c in bp.build_configs())["det"]) == 10
    assert bp.processes[1].extras == {}
