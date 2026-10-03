"""Task 5.6, часть B: слепая приёмка литерального набора путей телеметрии счётчиков тракта.

Источник — строка acceptance «Телеметрия, литеральный набор путей» плана
`plans/transport-single-policy/phase-5.md`. Зовутся два СУЩЕСТВУЮЩИХ публичных сборщика из
`process_module/heartbeat/telemetry.py`:

  * ``build_router_shm_telemetry(router) -> dict`` — листья ``processes.<P>.state.shm.*``;
  * ``build_worker_telemetry(workers, name, allowed_metrics=None, *, include_cycles=False)
    -> (path, data) | None`` — ``data["state"]`` = листья ``processes.<P>.state.*``.

Фейки: роутер с ``get_shm_stats()`` (имена сырой статистики роутера — те же, что в ключе
``rs`` JSON стенда: ``door_drops``, ``not_inspected_door``, ``deferred_closes``,
``errors_delivery_failed``); снимок воркеров — dict ``wname -> статус`` с ключами счётчиков
под теми же именами, что в ``workers.<воркер>.<ключ>`` JSON стенда.

Процесс под ``every`` (processor, inspector) отдаёт счётчики; процесс под ``latest`` —
нет: у него в ``get_shm_stats`` нет ``not_inspected_door`` и воркеры не несут
``not_inspected_*``, поэтому листья обязаны ОТСУТСТВОВАТЬ, а не стоять нулём.

ЧТО ИНТЕРПРЕТИРОВАНО (не прочитано буквально — ключи ввода в плане не названы):
  * имя ключа в статусе воркера = имени листа в телеметрии (включая ``ipc_queue_depth``);
  * новые листья суммируются по воркерам (в плане: «суммы по воркерам»);
  * тест присутствия нулей берёт «ноль — показание» из комментария Task 4.5a в
    ``build_worker_telemetry`` и из JSON стенда (``not_inspected_door: 0`` стоит у every).
Тесты отсутствия (latest, ipc_queue_depth до замера) якорятся на СУЩЕСТВУЮЩИЙ лист
(``fps`` / ``stale_drops``), чтобы «ключа нет» не выполнялось тривиально из-за пустого вывода;
сегодня они зелёные ПО ПОСТРОЕНИЮ (листьев ещё нет нигде) и краснеют, если реализация начнёт
выдавать нули там, где счётчика нет.
"""

from __future__ import annotations

import pytest

from multiprocess_framework.modules.process_module.heartbeat.telemetry import (
    build_router_shm_telemetry,
    build_worker_telemetry,
)


# --- фейки -----------------------------------------------------------------------
class _Router:
    """Роутер с узким аксессором — путь, который предпочитает сборщик."""

    def __init__(self, stats: dict) -> None:
        self._stats = dict(stats)

    def get_shm_stats(self) -> dict:
        return dict(self._stats)


def _worker(**counters) -> dict:
    """Статус работающего воркера с реальной частотой (чтобы собрался агрегат ``state``)."""
    return {"status": "running", "effective_hz": 90.0, **counters}


_COUNTERS = (
    "lag_dropped_items",
    "not_inspected_lag",
    "not_inspected_stale_restore",
    "not_inspected_stale_exec",
    "not_inspected_handled",
    "ipc_queue_depth",
)
_NOT_INSPECTED = (
    "not_inspected_lag",
    "not_inspected_stale_restore",
    "not_inspected_stale_exec",
    "not_inspected_handled",
)


def _every_workers() -> dict:
    """Два воркера, у обоих все шесть ключей с РАЗНЫМИ значениями — сумма не равна ни одному слагаемому."""
    return {
        "data_receiver": _worker(
            lag_dropped_items=11,
            not_inspected_lag=7,
            not_inspected_stale_restore=2,
            not_inspected_stale_exec=4,
            not_inspected_handled=100,
            ipc_queue_depth=6,
        ),
        "pipeline_executor": _worker(
            lag_dropped_items=20,
            not_inspected_lag=3,
            not_inspected_stale_restore=5,
            not_inspected_stale_exec=9,
            not_inspected_handled=23,
            ipc_queue_depth=1,
        ),
    }


def _state(workers: dict) -> dict:
    out = build_worker_telemetry(workers, "processor")
    assert out is not None, "снимок с работающими воркерами обязан дать payload"
    path, data = out
    assert path == "processes.processor"
    assert "state" in data, f"в payload нет секции state: {data}"
    return data["state"]


# =================================================================================
# shm-листья процесса под every: processes.<P>.state.shm.<лист>
# =================================================================================
_EVERY_SHM_STATS = {
    "door_drops": 7,
    "not_inspected_door": 3,
    "deferred_closes": 5,
    "errors_delivery_failed": 2,
    "frame_stale_drops": 4,  # существующий счётчик -> лист stale_drops (якорь)
}


@pytest.mark.parametrize(
    "leaf, expected",
    [
        ("door_drops", 7),
        ("not_inspected_door", 3),
        ("deferred_closes", 5),
        ("errors_delivery_failed", 2),
    ],
)
def test_every_process_exports_shm_leaf_with_the_routers_value(leaf, expected):
    shm = build_router_shm_telemetry(_Router(_EVERY_SHM_STATS))
    assert leaf in shm, f"лист shm.{leaf} отсутствует: {sorted(shm)}"
    assert shm[leaf] == expected


def test_every_process_keeps_not_inspected_door_when_it_is_zero():
    """Ноль у процесса под every — показание, а не отсутствие: лист стоит со значением 0."""
    shm = build_router_shm_telemetry(_Router({**_EVERY_SHM_STATS, "not_inspected_door": 0}))
    assert shm.get("not_inspected_door", "ABSENT") == 0


@pytest.mark.parametrize("leaf", ["door_drops", "deferred_closes", "errors_delivery_failed"])
def test_latest_process_still_exports_the_three_common_shm_leaves_as_zero(leaf):
    """Интерпретация: в списке «отсутствуют» у latest только not_inspected_*; остальные три
    (как и прежние тринадцать) идут всегда, нулём — сборщик документирует «полный набор ключей»."""
    shm = build_router_shm_telemetry(_Router({"frame_stale_drops": 4}))
    assert shm.get(leaf, "ABSENT") == 0


def test_latest_process_has_no_not_inspected_door_leaf():
    """Роутер latest не отдаёт not_inspected_door -> листа shm.not_inspected_door нет вовсе.
    Якорь: существующий stale_drops == 4 (вывод непустой). Сегодня зелёный — листа нет нигде."""
    shm = build_router_shm_telemetry(_Router({"door_drops": 1, "frame_stale_drops": 4}))
    assert shm["stale_drops"] == 4
    assert "not_inspected_door" not in shm


# =================================================================================
# Суммы по воркерам: processes.<P>.state.<лист>
# =================================================================================
_SUMS = {
    "lag_dropped_items": 31,  # 11 + 20
    "not_inspected_lag": 10,  # 7 + 3
    "not_inspected_stale_restore": 7,  # 2 + 5
    "not_inspected_stale_exec": 13,  # 4 + 9
    "not_inspected_handled": 123,  # 100 + 23
    "ipc_queue_depth": 7,  # 6 + 1 (gauge: размер data-очереди на тике)
}


@pytest.mark.parametrize("leaf", _COUNTERS)
def test_every_process_state_leaf_is_the_sum_over_workers(leaf):
    state = _state(_every_workers())
    assert leaf in state, f"лист state.{leaf} отсутствует: {sorted(state)}"
    assert state[leaf] == _SUMS[leaf]


@pytest.mark.parametrize("leaf", _COUNTERS)
def test_every_process_state_leaf_stays_present_when_every_worker_reports_zero(leaf):
    """Нули в статусах воркеров -> лист стоит нулём (а не пропадает как «ложное значение»)."""
    zeroed = {name: _worker(**{k: 0 for k in _COUNTERS}) for name in ("data_receiver", "pipeline_executor")}
    state = _state(zeroed)
    assert state.get(leaf, "ABSENT") == 0


def test_state_sum_counts_only_workers_that_carry_the_counter():
    """Один воркер несёт счётчик, второй (message_processor) — нет: сумма = значению первого."""
    workers = {
        "data_receiver": _worker(lag_dropped_items=11),
        "message_processor": {"status": "running"},
    }
    assert _state(workers)["lag_dropped_items"] == 11


# =================================================================================
# latest: листья not_inspected_* и ipc_queue_depth до замера отсутствуют
# =================================================================================
def _latest_workers() -> dict:
    """Воркеры процесса под latest: lag_dropped_items есть (renderer/storage его несут), not_inspected_* нет."""
    return {
        "data_receiver": _worker(lag_dropped_items=2413),
        "pipeline_executor": _worker(),
    }


@pytest.mark.parametrize("leaf", _NOT_INSPECTED)
def test_latest_process_state_has_no_not_inspected_leaf(leaf):
    """Якорь: существующий fps == 90.0 (секция state собрана). Сегодня зелёный по построению."""
    state = _state(_latest_workers())
    assert state["fps"] == 90.0
    assert leaf not in state


def test_ipc_queue_depth_is_absent_until_the_first_measurement():
    """Ни один воркер не принёс глубину очереди -> листа нет (не 0): «не измерено» != «пусто»."""
    state = _state(_every_workers_without_depth())
    assert state["fps"] == 90.0
    assert "ipc_queue_depth" not in state


def _every_workers_without_depth() -> dict:
    workers = _every_workers()
    for w in workers.values():
        del w["ipc_queue_depth"]
    return workers


def test_ipc_queue_depth_measured_as_zero_is_a_reading_and_stays_present():
    """Замер дал 0 (очередь пуста) — это показание, лист стоит нулём."""
    workers = {"data_receiver": _worker(ipc_queue_depth=0)}
    assert _state(workers).get("ipc_queue_depth", "ABSENT") == 0
