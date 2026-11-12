# -*- coding: utf-8 -*-
"""Task 1.3b (system-run-state) — hazard-тесты автора: шкала загрузки ``system.progress.boot``.

Слепой набор (``test_boot_progress.py``) закрывает приёмку; здесь то, чего он не видит: boot без стора и при
``run_gate: false`` не меняется; барьер выключен (``boot_ready_timeout_s: 0``) — шаг «готов» не двигается, а
``finish`` закрывает шкалу; единственный писатель — initialize-поток; ``finish`` ровно один раз и при ``ready``,
и при ``not_ready``; провал ``initialize()`` оставляет ``done: false``.

Стенд — из слепого набора (настоящий ``initialize()`` PM, настоящие барьеры на фейковом реестре, настоящий
``StateStoreManager``). Ожидаемые значения — литералы. Всё блокирующее идёт в daemon-потоке с join-дедлайном.
"""

from __future__ import annotations

import threading
import time
from typing import Any
from unittest.mock import patch

import pytest

from ...process_module.progress import ProgressTracker
from ..process.process_manager_process import ProcessManagerProcess
from .test_boot_progress import (
    BOOT_PATH,
    _bare_boot_pm,
    _boot,
    _collapse,
    _flat,
    _proc_cfg,
    _RecStore,
    _Registry,
    _run_initialize,
)

_INIT_THREAD = "pm-initialize"  # имя initialize-потока в стенде слепого набора


def _spy_state_op(pm: ProcessManagerProcess) -> list[tuple[str, str]]:
    """Подменить ``pm._state_op`` журналом ``(путь, имя потока)`` записей шкалы; исходный ``_state_op`` зовётся."""
    calls: list[tuple[str, str]] = []
    orig = pm._state_op

    def spy(handler_name: str, payload: dict, ctx: str) -> None:
        if str(payload.get("path", "")).startswith("system.progress"):
            calls.append((payload["path"], threading.current_thread().name))
        return orig(handler_name, payload, ctx)

    pm._state_op = spy
    return calls


# --------------------------------------------------------------------------- #
# Без стора, run_gate: false, барьер выключен
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_no_store_boot_unchanged() -> None:
    """Стора нет: boot идёт как прежде (3 процесса стартовали, ``initialize()`` True), шкалы нет и записей нет."""
    configs = _flat("a", "b", "c")
    pm = _bare_boot_pm(configs, _Registry(set(), set()))
    calls = _spy_state_op(pm)
    assert _run_initialize(pm, configs, None) is True
    assert sorted(p.name for p in pm._process_registry.os_processes) == ["a", "b", "c"]
    assert calls == [], "без стора шкала не должна ничего писать"
    assert pm._boot_progress is None
    assert pm._run_state == "not_ready"  # итог boot тот же, что и со стором: молчащие дети -> not_ready


@pytest.mark.timeout(60)
@pytest.mark.parametrize("run_gate", [False, True])
def test_run_gate_false_boot_unchanged(run_gate: bool) -> None:
    """``run_gate: false``: boot и шкала те же, что при ``true`` (5, 20, 35, 50, 100), событие работы взведено;
    шкала от гейта не зависит."""
    configs = _flat("a", "b", "c")
    store = _RecStore()
    pm = _bare_boot_pm(configs, _Registry(set(), set()))
    pm._run_gate = run_gate
    if run_gate:
        pm._run_event.clear()
    else:
        pm._run_event.set()
    assert _run_initialize(pm, configs, store) is True
    assert sorted(p.name for p in pm._process_registry.os_processes) == ["a", "b", "c"]
    assert _collapse(store.boot_percents()) == [5, 20, 35, 50, 100], store.boot_percents()
    assert store.store.get(BOOT_PATH)["done"] is True
    # событие работы: при gate=false boot его не снимает (взведено), при true — не взводит (до system.run.start)
    assert pm._run_event.is_set() is (not run_gate)


@pytest.mark.timeout(60)
def test_boot_ready_timeout_zero_ready_step_stays_finish_closes() -> None:
    """``boot_ready_timeout_s: 0`` (барьер выключен): шаг «готов» не двигается — до ``finish`` процент не выше 50
    и ``done`` ложь; ``finish`` закрывает шкалу (100, done) ровно одной записью."""
    configs = _flat("a", "b", "c")
    with patch.object(ProcessManagerProcess, "_boot_ready_timeout", return_value=0.0):
        store, _pm, result = _boot(configs)
    assert result is True
    leaves = store.boot_leaves()
    assert [leaf["percent"] for leaf in leaves] == [5, 20, 35, 50, 100], store.boot_percents()
    assert [leaf["done"] for leaf in leaves] == [False, False, False, False, True]


@pytest.mark.timeout(60)
def test_waves_union_of_ready_across_gates_not_last_gate_result() -> None:
    """Цепочка a <- b <- c, итоговый барьер выключен: гейты волн дают РАЗНЫЕ подмножества ({a}, затем {b}); «готов»
    считается объединением {a, b} = 2/3, а не последним результатом 1/3. Литералы (N=3): 5; a запущен 20; гейт {a}
    37; b запущен 52; гейт {b} — объединение 68; c запущен 83; finish 100."""
    configs = {"a": _proc_cfg(), "b": _proc_cfg(["a"]), "c": _proc_cfg(["b"])}
    with patch.object(ProcessManagerProcess, "_wait_boot_ready"):
        store, _pm, result = _boot(configs)
    assert result is True
    assert _collapse(store.boot_percents()) == [5, 20, 37, 52, 68, 83, 100], store.boot_percents()


@pytest.mark.timeout(60)
def test_empty_topology_label_is_empty() -> None:
    """N = 0: метка итога пустая (не «запущено 0 из 0»), записей только две: 5 и финальная 100/done."""
    store, _pm, result = _boot({})
    assert result is True
    assert store.boot_percents() == [5, 100]
    assert store.store.get(BOOT_PATH)["label"] == ""


# --------------------------------------------------------------------------- #
# Единственный писатель, finish один раз, провал initialize()
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_initialize_thread_is_the_only_writer() -> None:
    """Все записи шкалы идут из initialize-потока; после ``initialize()`` шкала снята, и поздние хуки (рестарт,
    apply) из чужого потока не пишут ничего."""
    configs = _flat("a", "b", "c")
    store = _RecStore()
    pm = _bare_boot_pm(configs, _Registry(set(), set()))
    calls = _spy_state_op(pm)
    assert _run_initialize(pm, configs, store) is True
    assert len(calls) == 6  # 5, 20, 35, 50, 100 (ready) и итоговый finish (100, done)
    assert {thread for _path, thread in calls} == {_INIT_THREAD}, calls
    assert {path for path, _thread in calls} == {BOOT_PATH}
    assert pm._boot_progress is None

    sealed = store.store.get(BOOT_PATH)
    late = threading.Thread(
        target=lambda: (pm._boot_progress_started(1), pm._boot_progress_ready({"a": True}), pm._boot_progress_finish()),
        daemon=True,
        name="late-writer",
    )
    late.start()
    late.join(10.0)
    assert not late.is_alive()
    assert len(calls) == 6, "поздний хук записал в лист закрытой шкалы"
    assert store.store.get(BOOT_PATH) == sealed


@pytest.mark.timeout(60)
@pytest.mark.parametrize(
    ("reported", "expected_state"),
    [pytest.param(True, "ready", id="ready"), pytest.param(False, "not_ready", id="not_ready")],
)
def test_finish_called_exactly_once_on_ready_and_not_ready(reported: bool, expected_state: str) -> None:
    """И при ``ready``, и при ``not_ready`` ``ProgressTracker.finish`` зван ровно один раз, ``done`` у одной записи."""
    configs = _flat("a", "b")
    store = _RecStore()
    pm = _bare_boot_pm(configs, _Registry(set(), set()))
    if reported:
        now = time.time()
        pm._process_monitor.readiness_snapshot.return_value = {
            n: {"ready": True, "reasons": [], "paused": False, "at": now} for n in ("a", "b")
        }
    finish_calls: list[str] = []
    real_finish = ProgressTracker.finish

    def counting_finish(self: ProgressTracker, label: str = "") -> dict:
        finish_calls.append(label)
        return real_finish(self, label)

    with patch.object(ProgressTracker, "finish", counting_finish):
        assert _run_initialize(pm, configs, store) is True
    assert pm._run_state == expected_state
    assert finish_calls == [""], finish_calls
    assert [leaf["done"] for leaf in store.boot_leaves()].count(True) == 1
    assert store.boot_leaves()[-1]["done"] is True


@pytest.mark.timeout(60)
def test_failed_initialize_leaves_boot_not_done() -> None:
    """Провал ``initialize()`` на барьере: возвращает ``False``, лист ``boot`` остаётся на 50 % с ``done: false``."""
    configs = _flat("a", "b", "c")
    store = _RecStore()
    pm = _bare_boot_pm(configs, _Registry(set(), set()))
    box: dict[str, Any] = {}
    with (
        patch.object(ProcessManagerProcess, "_wait_boot_ready", side_effect=RuntimeError("barrier broke")),
        patch.object(ProcessManagerProcess, "_handle_critical_error"),
        patch.object(ProcessManagerProcess, "close_root"),
    ):
        box["result"] = _run_initialize(pm, configs, store)
    assert box["result"] is False
    leaf = store.store.get(BOOT_PATH)
    assert (leaf["percent"], leaf["done"]) == (50, False), leaf
    assert [leaf["done"] for leaf in store.boot_leaves()].count(True) == 0
