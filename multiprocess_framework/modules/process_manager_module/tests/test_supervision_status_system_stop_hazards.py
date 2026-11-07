# -*- coding: utf-8 -*-
"""Task 1.2a (gui-graceful-close) — авторские тесты гонок хода системного стопа (ADR-PMM-041).

H9: опрос ``supervision.status`` против ``_begin_system_stop`` / ``_escalate_system_stop`` /
``_set_system_stop_phase`` — каждый снимок целый и является ЗНАЧЕНИЕМ (копия под локом), а не живым видом.
H10: два публикующих потока — фаза ``system.stop.phase`` в сторе не откатывается с ``done`` на ``children``.

Все потоки — daemon с дедлайном join. Ожидаемые значения — литералы.
"""

from __future__ import annotations

import threading
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from ..process.process_manager_process import ProcessManagerProcess

_JOIN_S = 10.0
_STOP_KEYS = {"phase", "mode", "initiator", "started_at", "deadline_at", "pre_stop_step"}


def _bare_pm() -> ProcessManagerProcess:
    """PM через ``__new__`` без ``__init__`` (как в существующих тестах supervision)."""
    with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
        pm = ProcessManagerProcess.__new__(ProcessManagerProcess)
    pm.name = "ProcessManager"
    pm._routing_epoch = 1
    pm._incarnations = {}
    mon = MagicMock()
    mon.get_supervision_snapshot.return_value = {}
    pm._process_monitor = mon
    for log in ("_log_info", "_log_warning", "_log_error", "_log_debug"):
        setattr(pm, log, MagicMock())
    pm._state_store_manager = None
    return pm


def _wait(predicate, timeout_s: float = _JOIN_S) -> bool:
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.001)
    return predicate()


def _join(thread: threading.Thread) -> None:
    thread.join(_JOIN_S)
    assert not thread.is_alive(), f"поток {thread.name} завис дольше {_JOIN_S} с"


# --------------------------------------------------------------------------- #
# H9. Снимок под опросом
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_status_poll_during_begin_is_consistent() -> None:
    """Опрос во время begin -> эскалации -> done: снимок либо None, либо целый словарь-значение."""
    pm = _bare_pm()
    snapshots: list[Any] = []
    quit_ev = threading.Event()
    errors: list[BaseException] = []

    def poll() -> None:
        try:
            while not quit_ev.is_set():
                snapshots.append(pm._cmd_supervision_status()["system_stop"])
        except BaseException as exc:  # noqa: BLE001 — пробросим в поток теста
            errors.append(exc)

    poller = threading.Thread(target=poll, daemon=True, name="h9-poller")
    poller.start()
    try:
        assert _wait(lambda: len(snapshots) >= 20), "опрос не стартовал"
        assert pm._begin_system_stop("graceful", "gui", None) is True
        mark = len(snapshots)
        assert _wait(lambda: sum(1 for s in snapshots[mark:] if s is not None) >= 20), "опрос не увидел стоп"
        assert pm._escalate_system_stop("force", 0.5) is True
        mark = len(snapshots)
        assert _wait(lambda: len(snapshots) >= mark + 20)
        pm._set_system_stop_phase("done")
        mark = len(snapshots)
        assert _wait(lambda: len(snapshots) >= mark + 20)
    finally:
        quit_ev.set()
        _join(poller)
    assert not errors, errors

    final = pm._cmd_supervision_status()["system_stop"]
    assert final["mode"] == "force" and final["phase"] == "done", final

    seen_stop = False
    rank = {"children": 0, "done": 1}
    last_rank = -1
    for snap in snapshots:
        if snap is None:
            assert not seen_stop, "после начала стопа опрос снова увидел None"
            continue
        seen_stop = True
        assert set(snap) == _STOP_KEYS, sorted(snap)
        assert snap["initiator"] == "gui" and snap["pre_stop_step"] is None, snap
        assert snap["started_at"] == final["started_at"], snap
        # Пара (mode, deadline_at) согласована: force — только с новым сроком, graceful — со старым.
        if snap["mode"] == "force":
            assert snap["deadline_at"] == final["deadline_at"], snap
        else:
            assert snap["mode"] == "graceful", snap
            assert snap["deadline_at"] == pytest.approx(snap["started_at"] + 5.0, abs=1e-6), snap
        # Фаза в порядке опроса не откатывается.
        assert rank[snap["phase"]] >= last_rank, snapshots
        last_rank = rank[snap["phase"]]

    # Снимок — значение: собранные ДО эскалации остались graceful/children (живой вид стал бы force/done).
    graceful = [s for s in snapshots if s is not None and s["mode"] == "graceful"]
    assert len(graceful) >= 20, f"снимков graceful {len(graceful)}: снимок не копия, а живой словарь"
    assert all(s["phase"] == "children" for s in graceful), graceful[:3]
    assert sum(1 for s in snapshots if s is not None and s["mode"] == "force" and s["phase"] == "children") >= 1


# --------------------------------------------------------------------------- #
# H10. Фаза в сторе не откатывается
# --------------------------------------------------------------------------- #


class _SlowStore:
    """Двойник стора: запись ``phase=children`` медленная (окно гонки); журнал значений по пути."""

    def __init__(self) -> None:
        self.values: dict[str, Any] = {}
        self.calls: list[tuple[str, Any]] = []
        self.children_entered = threading.Event()
        self._lock = threading.Lock()
        self.slow_s = 0.0

    def handle_state_set(self, msg: dict) -> dict:
        data = msg["data"]
        path, value = data["path"], data["value"]
        if path == "system.stop.phase" and value == "children" and self.slow_s:
            self.children_entered.set()
            time.sleep(self.slow_s)
        with self._lock:
            changed = self.values.get(path, object()) != value
            self.values[path] = value
            self.calls.append((path, value))
        return {"status": "ok", "path": path, "changed": changed}

    def phase_writes(self) -> list[Any]:
        return [v for p, v in self.calls if p == "system.stop.phase"]


@pytest.mark.timeout(60)
@pytest.mark.parametrize("order", ["slow-children-write", "late-children-publisher"])
def test_store_phase_never_rolls_back_under_concurrent_publish(order: str) -> None:
    """Два издателя (``children`` и ``done``): в сторе последнее значение фазы — ``done``, записей ровно 5."""
    pm = _bare_pm()
    store = _SlowStore()
    pm._state_store_manager = store
    assert pm._begin_system_stop("graceful", "gui", None) is True
    errors: list[BaseException] = []

    def guarded(fn):
        def run() -> None:
            try:
                fn()
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        return run

    a_published = threading.Event()
    a_phase_set = threading.Event()
    a_go = threading.Event()

    def publisher_children() -> None:
        pm._set_system_stop_phase("children")
        a_phase_set.set()
        if order == "late-children-publisher":
            a_go.wait(_JOIN_S)
        pm._publish_system_stop()
        a_published.set()

    def publisher_done() -> None:
        pm._set_system_stop_phase("done")
        pm._publish_system_stop()

    if order == "slow-children-write":
        # A входит в медленную запись phase=children; B ставит done и публикует, пока A ещё пишет.
        store.slow_s = 0.3
        a = threading.Thread(target=guarded(publisher_children), daemon=True, name="h10-children")
        a.start()
        assert store.children_entered.wait(_JOIN_S), "издатель children не дошёл до стора"
        b = threading.Thread(target=guarded(publisher_done), daemon=True, name="h10-done")
        b.start()
        _join(b)
        _join(a)
    else:
        # Начало стопа уже опубликовано (4 записи, как в system.shutdown). A сменил фазу на children
        # раньше, но публикует ПОЗЖЕ B (done): поздний издатель не должен вернуть children.
        pm._publish_system_stop()
        assert len(store.calls) == 4, store.calls
        a = threading.Thread(target=guarded(publisher_children), daemon=True, name="h10-children")
        a.start()
        assert a_phase_set.wait(_JOIN_S), "издатель children не сменил фазу"
        b = threading.Thread(target=guarded(publisher_done), daemon=True, name="h10-done")
        b.start()
        _join(b)
        a_go.set()
        _join(a)
    assert not errors, errors
    assert a_published.is_set()

    assert store.values["system.stop.phase"] == "done", store.calls
    assert store.phase_writes()[-1] == "done", store.calls
    assert store.phase_writes().count("done") == 1, store.calls
    # Число вызовов == числу дельт: 4 при начале (phase, mode, initiator, started_at) + done.
    assert len(store.calls) == 5, store.calls
    assert pm._cmd_supervision_status()["system_stop"]["phase"] == "done"
