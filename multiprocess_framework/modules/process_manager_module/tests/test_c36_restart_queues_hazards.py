"""C-36 (ADR-PMM-054) — hazard-тесты автора: порядок, срок метки, повторный рестарт, уборка счётчика.

Настоящие ``restart_process``, ``SharedResourcesManager``, ``ReaderGoneQueue`` и ``mp.Queue._rlock``.
Двойники: реестр OS-процессов (``make_pm``), ``communication``, методы логов.
Акцептанс слепого tester'а — ``test_c36_restart_queues_acceptance.py``; здесь только то, чего там нет.
"""

from __future__ import annotations

import threading
import time
from typing import Any
from unittest.mock import MagicMock

from multiprocess_framework.modules.shared_resources_module import SharedResourcesManager

from ..process import process_manager_process as pm_module
from ._c36_helpers import orphan_marker_event_lock
from .conftest import make_pm

_CAM_CONFIG = {
    "class": "os.getpid",
    "priority": "normal",
    "queues": {"system": {"maxsize": 100}, "data": {"maxsize": 100}},
}


def _make_cam_pm(**config: Any):
    srm = SharedResourcesManager()
    assert srm.initialize()
    assert srm.register_process("cam", _CAM_CONFIG)
    pm = make_pm({"cam": _CAM_CONFIG}, shared_resources=srm)
    pm.communication = MagicMock()
    pm._process_monitor.get_supervision_snapshot.return_value = {}
    for key, value in config.items():
        pm.update_config(key, value)
    return pm, srm


def _queues(srm) -> dict:
    return srm.queue_registry.get_process_queues("cam")


def _bounded(call, deadline_s: float = 20.0) -> tuple[Any, float]:
    """Вызов в daemon-потоке со сроком: зависание — красный тест, а не повисший прогон."""
    box: dict[str, Any] = {}

    def _run() -> None:
        started = time.monotonic()
        box["result"] = call()
        box["elapsed"] = time.monotonic() - started

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(deadline_s)
    assert not thread.is_alive(), f"вызов не вернулся за {deadline_s} с"
    return box["result"], box["elapsed"]


def _lines(log_mock) -> list[str]:
    return [str(c.args[0]) for c in log_mock.call_args_list]


def _counter(pm) -> Any:
    row = pm._cmd_supervision_status({"process": "cam"})["processes"].get("cam")
    return None if row is None else row.get("orphaned_read_locks")


def test_hung_mark_of_one_queue_does_not_leave_the_other_unmarked() -> None:
    """Замок ``Event`` очереди system осиротел (она первая в обходе): data всё равно помечена, ERROR называет system."""
    pm, srm = _make_cam_pm()
    old = _queues(srm)
    assert list(old) == ["system", "data"], "тест требует, чтобы зависшая очередь шла первой"
    orphan_marker_event_lock(old["system"])

    result, _ = _bounded(lambda: pm.restart_process("cam"))

    assert result is True
    assert old["data"].is_reader_gone() is True  # на ``old["system"]`` is_reader_gone звать нельзя: повиснет
    hung = [line for line in _lines(pm._log_error) if "не взведена" in line]
    assert len(hung) == 1 and "'system'" in hung[0] and "'cam'" in hung[0], hung


def test_mark_deadline_is_shared_by_all_queues_not_summed(monkeypatch) -> None:
    """Обе метки висят, срок 1.0 с: рестарт укладывается в один срок, а не в сумму двух."""
    pm, srm = _make_cam_pm()
    pm._MARK_GONE_DEADLINE_S = 1.0
    release = threading.Event()
    monkeypatch.setattr(pm_module, "set_reader_gone", lambda queues, gone: release.wait(30.0))
    try:
        result, elapsed = _bounded(lambda: pm.restart_process("cam"))
    finally:
        release.set()
    assert result is True
    assert 0.9 <= elapsed < 1.8, elapsed
    assert len([line for line in _lines(pm._log_error) if "не взведена" in line]) == 2


def test_old_queues_are_marked_before_they_are_replaced_in_psr() -> None:
    """Метка стоит уже на входе в ``register_process``: писатель не видит свежих очередей при немеченых старых."""
    pm, srm = _make_cam_pm()
    old = _queues(srm)
    seen: list[list[bool]] = []
    real_register = srm.register_process

    def _spy(*args: Any, **kwargs: Any):
        seen.append([old["system"].is_reader_gone(), old["data"].is_reader_gone()])
        return real_register(*args, **kwargs)

    srm.register_process = _spy
    assert pm.restart_process("cam") is True
    assert seen == [[True, True]]


def test_child_that_did_not_stop_keeps_its_queues_unmarked_and_uncounted() -> None:
    """Живой читатель законно держит ``_rlock``: при неудачном стопе нет ни пробы, ни метки, ни новых очередей."""
    pm, srm = _make_cam_pm()
    old = _queues(srm)
    assert old["data"]._rlock.acquire(False) is True  # «читатель внутри get»
    pm._process_registry.stop_one = lambda *a, **k: False
    try:
        assert pm.restart_process("cam") is False
        assert _queues(srm)["data"] is old["data"]
        assert old["data"].is_reader_gone() is False
        assert _counter(pm) in (None, 0)
        assert [line for line in _lines(pm._log_warning) + _lines(pm._log_error) if "C-36" in line] == []
    finally:
        old["data"]._rlock.release()


def test_probe_gives_back_every_lock_it_took() -> None:
    """Свободный замок остаётся свободным после пробы — иначе проба сама делает переиспользуемую очередь глухой."""
    pm, srm = _make_cam_pm(restart_reuse_queues=True)
    assert pm.restart_process("cam") is True
    for qtype, q in _queues(srm).items():
        assert q._rlock.acquire(False) is True, f"проба не отпустила замок очереди {qtype}"
        q._rlock.release()


def test_fallback_bumps_incarnation_once_and_next_reuse_restart_is_quiet() -> None:
    """``true`` + занятый замок: incarnation +1; следующий рестарт переиспользует новые очереди без тревоги."""
    pm, srm = _make_cam_pm(restart_reuse_queues=True)
    assert _queues(srm)["data"]._rlock.acquire(False) is True
    assert pm.restart_process("cam") is True
    fresh = _queues(srm)
    assert pm._incarnations.get("cam") == 1
    pm._log_warning.reset_mock()
    pm._log_error.reset_mock()

    assert pm.restart_process("cam") is True

    assert _queues(srm)["data"] is fresh["data"]
    assert pm._incarnations.get("cam") == 1
    assert _counter(pm) == 1
    assert [line for line in _lines(pm._log_warning) + _lines(pm._log_error) if "C-36" in line] == []


def test_counter_dies_with_the_process_cleanup() -> None:
    """Снятый процесс не оставляет счётчик одноимённому преемнику (C36A-11)."""
    pm, srm = _make_cam_pm()
    assert _queues(srm)["data"]._rlock.acquire(False) is True
    assert pm.restart_process("cam") is True
    assert pm._orphaned_read_locks == {"cam": 1}

    pm._cleanup_process_resources("cam")

    assert pm._orphaned_read_locks == {}


def test_probe_failure_does_not_abort_restart() -> None:
    """PSR не отдал запись процесса: предупреждение, рестарт проходит."""
    pm, srm = _make_cam_pm()
    real_get = srm.get_process_data
    calls = {"n": 0}

    def _broken(name: str):
        calls["n"] += 1
        if calls["n"] <= 2:  # проба и метка; дальше настоящий ответ
            raise RuntimeError("psr сломан")
        return real_get(name)

    srm.get_process_data = _broken
    assert pm.restart_process("cam") is True
    assert len([line for line in _lines(pm._log_warning) if "psr сломан" in line]) == 2


def test_restart_retires_only_queues_that_are_recreated() -> None:
    """Тип не из конфига ``register_process`` не пересоздаёт: закрыв его, PM перестал бы доставлять в этот тип."""
    pm, srm = _make_cam_pm()
    assert srm.queue_registry.create_and_register_queues("cam", {"extra": {"maxsize": 10}})
    old = _queues(srm)

    assert pm.restart_process("cam") is True

    assert _queues(srm)["extra"] is old["extra"]
    old["extra"].put_nowait(b"x")  # не отпущена: put проходит
    assert old["extra"].get(timeout=5.0) == b"x"
    refused = []
    for qtype in ("system", "data"):
        try:
            old[qtype].put_nowait(b"x")
        except ValueError:
            refused.append(qtype)
    assert refused == ["system", "data"]


def test_reuse_true_restart_retires_nothing() -> None:
    pm, srm = _make_cam_pm(restart_reuse_queues=True)
    assert pm.restart_process("cam") is True
    _queues(srm)["data"].put_nowait(b"x")
    assert _queues(srm)["data"].get(timeout=5.0) == b"x"
