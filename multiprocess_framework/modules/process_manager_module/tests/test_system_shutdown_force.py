# -*- coding: utf-8 -*-
"""Task 0.2 (gui-graceful-close): ``system.shutdown mode=force`` — приёмка вслепую (стадия 1).

Контракт — ``plans/2026-10-20_gui-graceful-close/tasks/0.2.md`` (DESIGN шаги 1–3), реализация не читалась.

Что пинуется:
  * ``_cmd_system_shutdown(data)`` принимает ``mode`` (``graceful`` по умолчанию | ``force``) и
    ``deadline_s`` (только ``force``, по умолчанию 1.0, допустимо 0.1..5.0 включительно);
  * ``force`` СНАЧАЛА ставит срок в ``_ChildrenStop`` (``_force_at``), затем взводит события; ответ
    сразу; повтор срок не сдвигает (первый вызов выигрывает);
  * настоящий ``_ChildrenStop.join_until(deadline)`` отдаёт группе ``min(deadline, _force_at)``, пока
    не было ``kill()``; после ``kill()`` срок не обрезается (фаза 3 области зовёт тот же ``join_until``);
  * ``graceful`` срока не ставит.

Объекты: настоящий ``_ChildrenStop`` + фейковые группа/реестр; PM строится через ``__new__`` (образец —
``test_process_manager_process.py``). Любой вызов, способный заблокироваться, идёт в daemon-потоке с
дедлайном ожидания.
"""

from __future__ import annotations

import math
import threading
import time
from typing import Any, Callable
from unittest.mock import MagicMock, patch

import pytest

from ..process.process_manager_process import ProcessManagerProcess, _ChildrenStop

_CALL_DEADLINE_S = 5.0

_ERR_MODE = {"error": "mode: graceful|force"}
_ERR_DEADLINE = {"error": "deadline_s: 0.1..5.0"}


class _FakeGroup:
    """Группа детей: пишет, какой срок ей передали, и ничего не ждёт."""

    def __init__(self) -> None:
        self.join_deadlines: list[float] = []
        self.kill_calls = 0
        self.request_stop_calls = 0

    def request_stop(self) -> None:
        self.request_stop_calls += 1

    def join_until(self, deadline: float) -> bool:
        self.join_deadlines.append(deadline)
        return True

    def kill(self) -> None:
        self.kill_calls += 1

    def close(self) -> None:
        pass

    def result(self) -> dict[str, bool]:
        return {}


class _SpyEvent(threading.Event):
    """Событие, запоминающее ``_force_at`` в момент ``set()`` (порядок «срок, потом событие»)."""

    def __init__(self, cs_getter: Callable[[], Any]) -> None:
        super().__init__()
        self._cs_getter = cs_getter
        self.force_at_seen_on_set: list[float | None] = []

    def set(self) -> None:  # noqa: A003 — переопределяем Event.set
        self.force_at_seen_on_set.append(getattr(self._cs_getter(), "_force_at", None))
        super().set()


class _Rig:
    """PM (через ``__new__``) + настоящий ``_ChildrenStop`` + фейковая группа."""

    def __init__(self) -> None:
        self.group = _FakeGroup()
        with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
            pm = ProcessManagerProcess.__new__(ProcessManagerProcess)
        pm.name = "ProcessManager"
        pm.shared_resources = None
        pm.config = {}
        pm._process_monitor = None
        pm._process_registry = MagicMock()
        pm._process_registry.children_stop = MagicMock(return_value=self.group)
        pm._log_info = MagicMock()
        pm._log_warning = MagicMock()
        pm._log_error = MagicMock()
        self.pm = pm
        self.cs = _ChildrenStop(pm)
        pm._children_stop = self.cs
        pm.stop_event = _SpyEvent(lambda: self.cs)
        pm._system_stop_event = _SpyEvent(lambda: self.cs)

    def command(self, data: dict | None = None) -> dict:
        """``_cmd_system_shutdown`` в daemon-потоке с дедлайном: ответ или провал теста."""
        return _bounded(lambda: self.pm._cmd_system_shutdown(data))

    @property
    def events_set(self) -> tuple[bool, bool]:
        return self.pm.stop_event.is_set(), self.pm._system_stop_event.is_set()


def _bounded(fn: Callable[[], Any], deadline_s: float = _CALL_DEADLINE_S) -> Any:
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 — пробросим в поток теста
            box["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(deadline_s)
    assert not thread.is_alive(), f"вызов завис дольше {deadline_s} с"
    if "error" in box:
        raise box["error"]
    return box["value"]


def _join(cs: _ChildrenStop, deadline: float) -> bool:
    return _bounded(lambda: cs.join_until(deadline))


@pytest.fixture
def rig() -> _Rig:
    return _Rig()


@pytest.mark.parametrize("deadline_s", [0.1, 0.5, 1.0, 5.0])
def test_force_caps_children_join_at_deadline(rig: _Rig, deadline_s: float) -> None:
    """Группа, уже запущенная фазой 1, получает срок из окна ``[t_до + d, t_после + d]``, а не ``now + 10``.

    0.1 и 5.0 — границы допустимого диапазона (включительно); 0.5 и 1.0 — по брифу.
    """
    rig.cs.request_stop()
    t_before = time.monotonic()
    reply = rig.command({"mode": "force", "deadline_s": deadline_s})
    t_after = time.monotonic()
    assert reply.get("success") is True, reply

    assert _join(rig.cs, time.monotonic() + 10.0) is True
    assert len(rig.group.join_deadlines) == 1, rig.group.join_deadlines
    passed = rig.group.join_deadlines[0]
    assert t_before + deadline_s <= passed <= t_after + deadline_s, (
        f"группе передан срок {passed:.4f}, ожидалось в [{t_before + deadline_s:.4f}, {t_after + deadline_s:.4f}] "
        f"(d={deadline_s})"
    )


def test_force_sets_deadline_then_events_and_replies_immediately(rig: _Rig) -> None:
    t_before = time.monotonic()
    reply = rig.command({"mode": "force", "deadline_s": 1.0})
    t_after = time.monotonic()

    assert reply == {"success": True, "message": "Shutdown initiated", "mode": "force", "deadline_s": 1.0}
    assert t_after - t_before < 0.5, f"force ответил за {t_after - t_before:.3f} с — команда не должна ждать срок"
    assert rig.events_set == (True, True)
    # Порядок: к моменту set() каждого события срок уже стоял (иначе PM успеет начать стоп без срока).
    for name, spy in (("stop_event", rig.pm.stop_event), ("system_stop_event", rig.pm._system_stop_event)):
        assert spy.force_at_seen_on_set, f"{name}: set() не вызывался"
        assert all(seen is not None for seen in spy.force_at_seen_on_set), (
            f"{name}.set() вызван до того, как срок стопа был поставлен"
        )
    info_lines = [str(call.args[0]) for call in rig.pm._log_info.call_args_list if call.args]
    assert any("force: срок стопа детей 1.0 с" in line for line in info_lines), info_lines

    # Повтор: ответ success, срок первого не сдвинут (второй просит +4.0 с — в окно первого не попадёт).
    second = rig.command({"mode": "force", "deadline_s": 4.0})
    assert second.get("success") is True, second
    rig.cs.request_stop()
    assert _join(rig.cs, time.monotonic() + 100.0) is True
    passed = rig.group.join_deadlines[-1]
    assert t_before + 1.0 <= passed <= t_after + 1.0, (
        f"повторный force сдвинул срок: {passed:.4f} вне окна первого [{t_before + 1.0:.4f}, {t_after + 1.0:.4f}]"
    )


def test_force_before_group_exists_applies_when_group_appears(rig: _Rig) -> None:
    """``force`` пришёл до фазы 1 (группы ещё нет); потом ``join_until`` создаёт группу — срок обрезан."""
    assert rig.group.request_stop_calls == 0
    t_before = time.monotonic()
    reply = rig.command({"mode": "force", "deadline_s": 0.5})
    t_after = time.monotonic()
    assert reply.get("success") is True, reply
    assert rig.group.join_deadlines == []

    assert _join(rig.cs, time.monotonic() + 10.0) is True
    assert len(rig.group.join_deadlines) == 1, rig.group.join_deadlines
    passed = rig.group.join_deadlines[0]
    assert t_before + 0.5 <= passed <= t_after + 0.5, (
        f"срок {passed:.4f} вне окна [{t_before + 0.5:.4f}, {t_after + 0.5:.4f}]"
    )


def test_join_after_kill_not_capped(rig: _Rig) -> None:
    """После ``force`` и ``kill()`` фаза 3 зовёт тот же ``join_until`` — срок обрезаться не должен."""
    rig.cs.request_stop()
    t_before = time.monotonic()
    reply = rig.command({"mode": "force", "deadline_s": 1.0})
    t_after = time.monotonic()
    assert reply.get("mode") == "force", reply

    # Предусловие (иначе тест пуст): ДО kill() срок обрезается.
    assert _join(rig.cs, time.monotonic() + 10.0) is True
    capped = rig.group.join_deadlines[0]
    assert t_before + 1.0 <= capped <= t_after + 1.0, f"до kill() срок не обрезан: {capped:.4f}"

    _bounded(rig.cs.kill)
    assert rig.group.kill_calls == 1, "kill() не дошёл до группы"

    requested = time.monotonic() + 2.0
    assert _join(rig.cs, requested) is True
    assert rig.group.join_deadlines[1:] == [requested], (
        f"после kill() срок {requested:.4f} должен дойти до группы как есть, получено {rig.group.join_deadlines[1:]}"
    )


_BAD_PARAMS = [
    pytest.param({"mode": "x"}, _ERR_MODE, id="mode-x"),
    pytest.param({"mode": "force", "deadline_s": 0.05}, _ERR_DEADLINE, id="deadline-0.05"),
    pytest.param({"mode": "force", "deadline_s": 5.1}, _ERR_DEADLINE, id="deadline-5.1"),
    pytest.param({"mode": "force", "deadline_s": math.nan}, _ERR_DEADLINE, id="deadline-nan"),
    pytest.param({"mode": "force", "deadline_s": math.inf}, _ERR_DEADLINE, id="deadline-inf"),
    pytest.param({"mode": "force", "deadline_s": True}, _ERR_DEADLINE, id="deadline-True"),
    pytest.param({"mode": "force", "deadline_s": "1"}, _ERR_DEADLINE, id="deadline-str"),
]


@pytest.mark.parametrize(("data", "expected"), _BAD_PARAMS)
def test_bad_mode_or_deadline_rejected_no_event_set(rig: _Rig, data: dict, expected: dict) -> None:
    reply = rig.command(data)
    assert reply == expected, reply
    assert rig.events_set == (False, False), "при ошибке параметров события трогать нельзя"
    assert getattr(rig.cs, "_force_at", None) is None, "при ошибке параметров срок стопа не ставится"


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(None, id="no-args"),
        pytest.param({"mode": "graceful", "deadline_s": 0.5}, id="graceful-ignores-deadline"),
    ],
)
def test_graceful_unchanged_no_force_deadline(rig: _Rig, data: dict | None) -> None:
    """СТРАЖ (зелёный до и после): graceful как раньше — события взведены, срок детям НЕ обрезается."""
    rig.cs.request_stop()
    reply = rig.command(data)
    assert reply.get("success") is True, reply
    assert reply.get("message") == "Shutdown initiated", reply
    assert rig.events_set == (True, True)
    assert getattr(rig.cs, "_force_at", None) is None, "graceful поставил срок force"

    requested = time.monotonic() + 10.0
    assert _join(rig.cs, requested) is True
    assert rig.group.join_deadlines == [requested], rig.group.join_deadlines
