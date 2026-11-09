# -*- coding: utf-8 -*-
"""Task 1.4 (gui-graceful-close), раунд 2: ``system_shutdown`` читает ответ PM из конверта ``process.command.response``.

Авторские тесты исполнителя. Живой ответ PM — не плоский dict, а конверт
``{"type": "response", "success": <bool>, "result": {<ответ system.shutdown>}}``; ``success`` конверта равен
``result["success"]`` и потому ``True`` даже на отказе ``already_stopping``. Слепые тесты DR кормили драйвер ПЛОСКИМ
ответом и этого не видели (находка M1 ревью), поэтому здесь:

  * вложенные формы: ``already_stopping`` (опрос идёт), ``accepted True`` (``mode`` из ``result``), ошибка аргументов
    (опроса нет);
  * один тест на настоящих объектах: ответ собирают НАСТОЯЩИЕ ``ProcessManagerProcess._handle_process_command`` +
    ``_cmd_system_shutdown`` + ``RouterManager.reply_to_request`` (PM через ``__new__``, отправка перехвачена), и этот
    конверт разбирает драйвер;
  * усиление слабых ячеек DR: (г) проверяется по РАЗБОРУ снимков (конец по итогам, а не по счётчику вызовов), (е) — по
    перебазированию срока на момент снимка с ``system_stop``; снимок только с ``ProcessManager`` не кончает опрос (m2).

Транспорт фейковый: подмена ``system_command`` / ``supervision_status`` и часов модуля ``backend_ctl.driver``.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import backend_ctl.driver as driver_mod
from backend_ctl.driver import BackendDriver
from multiprocess_framework.modules.message_module.builders.command_envelopes import build_system_command_message
from multiprocess_framework.modules.process_manager_module.process.process_manager_process import (
    ProcessManagerProcess,
    _ChildrenStop,
)
from multiprocess_framework.modules.router_module.core.router_manager import RouterManager

_CALL_DEADLINE_S = 20.0


class _Clock:
    """Фальшивые часы: ``sleep`` двигает ``monotonic`` и ``time`` вместе."""

    def __init__(self) -> None:
        self.mono = 500.0
        self._wall0 = 1_700_000_000.0
        self._mono0 = self.mono
        self._reads = 0

    def monotonic(self) -> float:
        self._reads += 1
        if self._reads > 500_000:
            raise AssertionError("драйвер крутит цикл без сна на фальшивых часах")
        return self.mono

    def time(self) -> float:
        return self._wall0 + (self.mono - self._mono0)

    def sleep(self, seconds: float) -> None:
        self.mono += max(0.0, float(seconds))


def _entry(outcome: str | None) -> dict[str, Any]:
    return {"alive": outcome is None, "status": "running", "stop_outcome": outcome}


def _snap(**children: str | None) -> dict[str, Any]:
    """Снимок: ``ProcessManager`` + перечисленные дети (значение — ``stop_outcome``)."""
    processes: dict[str, Any] = {"ProcessManager": _entry(None)}
    processes.update({name: _entry(outcome) for name, outcome in children.items()})
    return {"processes": processes}


class _Drv(BackendDriver):
    """Драйвер без сокета: ответ команды, снимки по очереди (последний повторяется), разрыв по счётчику."""

    def __init__(
        self,
        reply: dict[str, Any],
        snapshots: list[dict[str, Any]],
        clock: _Clock | None = None,
        *,
        lost_after_status_calls: int | None = None,
        stop_info_after_s: float | None = None,
        deadline_offset_s: float = 1.0,
    ) -> None:
        self._reply = reply
        self._snapshots = snapshots
        self._clock = clock
        self._lost_after = lost_after_status_calls
        self._stop_info_after_s = stop_info_after_s
        self._deadline_offset = deadline_offset_s
        self._t0 = clock.mono if clock is not None else 0.0
        self.status_calls = 0
        self._post_reads = 0
        super().__init__()

    @property
    def connection_lost(self) -> bool:  # type: ignore[override]
        if self._lost_after is not None and self.status_calls >= self._lost_after:
            self._post_reads += 1
            return self._post_reads >= 2
        return False

    def system_command(self, command: dict, *, timeout: float | None = None) -> dict:  # type: ignore[override]
        return self._reply

    def supervision_status(self, *args: Any, **kwargs: Any) -> dict:  # type: ignore[override]
        self.status_calls += 1
        index = min(self.status_calls - 1, len(self._snapshots) - 1)
        result: dict[str, Any] = {"success": True, "epoch": 0, **self._snapshots[index]}
        if self._clock is not None and self._stop_info_after_s is not None:
            if self._clock.mono - self._t0 >= self._stop_info_after_s:
                result["system_stop"] = {
                    "phase": "children",
                    "mode": "graceful",
                    "initiator": "unknown",
                    "started_at": self._clock.time(),
                    "deadline_at": self._clock.time() + self._deadline_offset,
                    "pre_stop_step": None,
                }
        return {"success": True, "result": result}


def _envelope(result: dict[str, Any]) -> dict[str, Any]:
    """Конверт ``process.command.response`` в форме ``reply_to_request`` (``success`` — как у PM)."""
    return {
        "type": "response",
        "command": "process.command.response",
        "request_id": "r1",
        "success": ProcessManagerProcess._process_command_success(result),
        "result": result,
    }


def _run(drv: _Drv, clock: _Clock | None = None, **kwargs: Any) -> dict[str, Any]:
    """``system_shutdown`` в daemon-потоке с дедлайном; при ``clock`` — на фальшивых часах."""
    box: dict[str, Any] = {}

    def call() -> None:
        try:
            box["value"] = drv.system_shutdown(**kwargs)
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc

    with pytest.MonkeyPatch.context() as mp:
        if clock is not None:
            mp.setattr(driver_mod, "time", clock)
        thread = threading.Thread(target=call, daemon=True)
        thread.start()
        thread.join(_CALL_DEADLINE_S)
        assert not thread.is_alive(), f"system_shutdown завис дольше {_CALL_DEADLINE_S} с"
    if "error" in box:
        raise box["error"]
    return box["value"]


# --------------------------------------------------------------------------- #
# Вложенные формы ответа
# --------------------------------------------------------------------------- #


def test_nested_already_stopping_gives_accepted_false_and_polls_real_snapshots() -> None:
    """(1) success конверта True, result.accepted False: accepted False, опрос идёт и кончается по итогам."""
    reply = _envelope({"success": True, "accepted": False, "reason": "already_stopping", "phase": "children"})
    assert reply["success"] is True, "предусловие: конверт на отказе несёт success True"
    clock = _Clock()
    # 2-й снимок — итоги; сокет не закрывается: без разбора снимков опрос дошёл бы до wait_timeout.
    drv = _Drv(reply, [_snap(a=None), _snap(a="exited")], clock)

    res = _run(drv, clock, wait_timeout=5.0)

    assert res["accepted"] is False, res
    assert drv.status_calls == 2, f"supervision.status вызван {drv.status_calls} раз, ждали 2 (конец по итогам)"
    assert res["outcomes"] == {"a": "exited"}, res
    assert res["unconfirmed"] == [], res
    assert res["timed_out"] is False, res


def test_nested_accepted_true_reads_mode_from_result() -> None:
    """(2) ``result.accepted True``; ``mode`` берётся из ``result``, а не из запрошенного."""
    reply = _envelope({"success": True, "accepted": True, "mode": "force", "phase": "children"})
    clock = _Clock()
    drv = _Drv(reply, [_snap(a="killed")], clock, lost_after_status_calls=1)

    res = _run(drv, clock, mode="graceful")

    assert res["accepted"] is True, res
    assert res["mode"] == "force", res
    assert res["outcomes"] == {"a": "killed"}, res
    assert res["pm_gone"] is True, res


def test_nested_argument_error_returns_without_polling() -> None:
    """(3) ``result.error`` (конверт ``success`` False): ``accepted False``, опроса нет, ``outcomes None``."""
    reply = _envelope({"error": "mode: graceful|force"})
    assert reply["success"] is False, "предусловие: ответ-ошибка даёт success False у конверта"
    clock = _Clock()
    drv = _Drv(reply, [_snap(a=None)], clock)

    res = _run(drv, clock)

    assert drv.status_calls == 0, f"supervision.status вызван {drv.status_calls} раз при ошибке аргументов"
    assert res["accepted"] is False, res
    assert res["outcomes"] is None and res["unconfirmed"] is None and res["timed_out"] is False, res
    assert res["pm_gone"] is False, res


# --------------------------------------------------------------------------- #
# Настоящие объекты: ответ собирает код PM и роутера
# --------------------------------------------------------------------------- #


class _FakeGroup:
    def request_stop(self) -> None:
        pass

    def join_until(self, deadline: float) -> bool:
        return True

    def kill(self) -> None:
        pass

    def close(self) -> None:
        pass

    def result(self) -> dict[str, bool]:
        return {}


class _CommandManagerShim:
    """Вместо ``CommandManager``: отдаёт вложенную команду в настоящий ``_cmd_system_shutdown``."""

    def __init__(self, pm: ProcessManagerProcess) -> None:
        self._pm = pm

    def handle_command(self, inner_msg: dict, reply: Any = None) -> Any:
        return self._pm._cmd_system_shutdown(inner_msg["data"])


class _RealReplies:
    """PM (``__new__``) с настоящим ``RouterManager``: ``send`` перехвачен, ответ — то, что ушло бы в сокет."""

    def __init__(self) -> None:
        with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
            pm = ProcessManagerProcess.__new__(ProcessManagerProcess)
        pm.name = "ProcessManager"
        pm.shared_resources = None
        pm.config = {}
        pm._process_monitor = None
        pm._process_registry = MagicMock()
        pm._process_registry.children_stop = MagicMock(return_value=_FakeGroup())
        for log in ("_log_info", "_log_warning", "_log_error", "_log_debug"):
            setattr(pm, log, MagicMock())
        pm.stop_event = threading.Event()
        pm._system_stop_event = threading.Event()
        pm._children_stop = _ChildrenStop(pm)
        pm.command_manager = _CommandManagerShim(pm)
        router = RouterManager(manager_name="ProcessManager", process=SimpleNamespace(name="ProcessManager"))
        self.sent: list[dict[str, Any]] = []
        router.send = self.sent.append  # type: ignore[method-assign]
        pm.router_manager = router
        self.pm = pm

    def ask(self, command: dict[str, Any]) -> dict[str, Any]:
        """Настоящее ``process.command``-сообщение -> настоящий ответ PM (конверт из ``reply_to_request``)."""
        msg = build_system_command_message(command, sender="driver-x", request_id="r1")
        before = len(self.sent)
        self.pm._handle_process_command(msg)
        assert len(self.sent) == before + 1, "PM не отправил ровно один ответ"
        return self.sent[-1]


def test_driver_reads_envelopes_built_by_real_pm_and_router() -> None:
    """(4) Первый ``graceful`` — ``accepted True``; повтор — ``accepted False`` + ``already_stopping`` и опрос идёт."""
    real = _RealReplies()
    first = real.ask({"cmd": "system.shutdown", "mode": "graceful"})
    second = real.ask({"cmd": "system.shutdown", "mode": "graceful"})
    bad = real.ask({"cmd": "system.shutdown", "mode": "sideways"})

    # Предусловие: форма — именно конверт, а отказ повтора несёт success True на верхнем уровне.
    assert first["command"] == "process.command.response" and isinstance(first["result"], dict), first
    assert second["success"] is True and second["result"]["accepted"] is False, second
    assert bad["success"] is False and "error" in bad["result"], bad

    clock1 = _Clock()
    res_first = _run(_Drv(first, [_snap(a="exited")], clock1, lost_after_status_calls=1), clock1)
    assert res_first["accepted"] is True, res_first

    clock2 = _Clock()
    drv_second = _Drv(second, [_snap(a=None), _snap(a="terminated")], clock2)
    res_second = _run(drv_second, clock2, wait_timeout=5.0)
    assert res_second["accepted"] is False, res_second
    assert drv_second.status_calls == 2, drv_second.status_calls
    assert res_second["outcomes"] == {"a": "terminated"}, res_second

    clock3 = _Clock()
    drv_bad = _Drv(bad, [_snap(a=None)], clock3)
    res_bad = _run(drv_bad, clock3)
    assert res_bad["accepted"] is False and drv_bad.status_calls == 0, res_bad


# --------------------------------------------------------------------------- #
# Усиление слабых ячеек DR и m2
# --------------------------------------------------------------------------- #


def test_budget_is_rebased_to_first_snapshot_with_system_stop() -> None:
    """(е') ``system_stop`` виден лишь через 5 с, ``deadline_at = now+1``: срок — 20 с ОТ ЭТОГО СНИМКА (elapsed ~25).

    DR (е) при ``now+1`` не различает перебазирование и константу 20,0 (оба дают 20): здесь снимок с ``system_stop``
    приходит позже, и «20 от начала» (20,0) отличается от «20 от снимка» (25,0).
    """
    clock = _Clock()
    reply = _envelope({"success": True, "accepted": True, "mode": "graceful", "phase": "children"})
    drv = _Drv(reply, [_snap(a=None)], clock, stop_info_after_s=5.0, deadline_offset_s=1.0)

    res = _run(drv, clock, wait_timeout=None)

    assert res["timed_out"] is True, res
    assert 25.0 <= res["elapsed_s"] <= 25.5, f"elapsed_s={res['elapsed_s']!r}, ожидалось [25,0; 25,5]"


def test_only_process_manager_snapshot_does_not_end_the_poll() -> None:
    """(m2) Снимок только с ``ProcessManager`` не кончает опрос; он кончается, когда дети появились и дали итоги."""
    reply = _envelope({"success": True, "accepted": True, "mode": "graceful", "phase": "children"})

    clock = _Clock()
    drv = _Drv(reply, [_snap()], clock)
    res = _run(drv, clock, wait_timeout=0.5)
    assert res["timed_out"] is True, res
    assert res["outcomes"] == {} and res["unconfirmed"] == [], res
    assert drv.status_calls >= 3, drv.status_calls

    clock2 = _Clock()
    drv2 = _Drv(reply, [_snap(), _snap(), _snap(a="exited")], clock2, lost_after_status_calls=3)
    res2 = _run(drv2, clock2, wait_timeout=5.0)
    assert res2["timed_out"] is False, res2
    assert drv2.status_calls == 3, drv2.status_calls
    assert res2["outcomes"] == {"a": "exited"}, res2
