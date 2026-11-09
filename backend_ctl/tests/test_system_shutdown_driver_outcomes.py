# -*- coding: utf-8 -*-
"""Task 1.4 (gui-graceful-close) — слепая приёмка ``BackendDriver.system_shutdown``: итоги по процессам (REDS 8).

Написано ДО реализации по критериям приёмки брифа (DESIGN/FILES задачи не читались). Транспорта нет: подкласс
драйвера с подменой ``system_command`` / ``supervision_status`` и ``connection_lost``-счётчиком (образец —
``test_system_shutdown_driver.py``). ``supervision_status`` отдаёт КОНВЕРТ ``send_command`` с вложенным ``result``
(форма — как в фейке ``test_restart_verified.py``) плюс ``system_stop``.

Контракт (из REDS 8): ``system_shutdown(...) -> {"accepted", "mode", "elapsed_s", "pm_gone", "outcomes",
"unconfirmed", "timed_out"}``; параметры ``wait`` и ``wait_timeout`` (по умолчанию ``None``). Драйвер опрашивает
``supervision.status`` до «у всех процессов (кроме ``ProcessManager``) есть итог», объединяя снимки (запись, снятая из
снимка, помнит последний итог), затем ждёт закрытия сокета PM.

Допущения (текста REDS не хватает):
  * поле итога в записи процесса ``supervision.status`` — ``stop_outcome`` (так оно названо в ``test_restart_verified``,
    T1.10); в REDS оно зовётся «outcome»;
  * разрыв посреди опроса — ``supervision_status`` бросает ``BackendUnavailable`` и ``connection_lost`` становится
    ``True``;
  * часы драйвера — подмена атрибута ``time`` модуля ``backend_ctl.driver`` объектом с ``monotonic``/``time``/``sleep``;
    ``sleep`` двигает оба времени.

Стражи (зелёные до правки): 8(д).  8(в) и 8(ж) красные до правки через отсутствующий ключ (``KeyError``).
"""

from __future__ import annotations

import threading
from typing import Any, Callable

import pytest

import backend_ctl.driver as driver_mod
from backend_ctl.driver import BackendDriver, BackendUnavailable

_CALL_DEADLINE_S = 20.0
_ACCEPTED_REPLY = {"success": True, "accepted": True, "mode": "graceful", "phase": "children"}


class _Clock:
    """Фальшивые часы: ``sleep`` двигает ``monotonic`` и ``time`` вместе; вечный цикл без сна — падение теста."""

    def __init__(self) -> None:
        self._mono = 500.0
        self._wall0 = 1_700_000_000.0
        self._mono0 = self._mono
        self._reads = 0

    def monotonic(self) -> float:
        self._reads += 1
        if self._reads > 500_000:
            raise AssertionError("драйвер крутит цикл без сна на фальшивых часах")
        return self._mono

    def time(self) -> float:
        return self._wall0 + (self._mono - self._mono0)

    def sleep(self, seconds: float) -> None:
        self._mono += max(0.0, float(seconds))


def _entry(alive: bool, outcome: str | None) -> dict[str, Any]:
    return {
        "incarnation": 0,
        "restart_count": 0,
        "last_exit": None,
        "status": "running" if alive else "stopped",
        "pid": 4242 if alive else None,
        "alive": alive,
        "started_at": 1000.0,
        "instance_restarts": 0,
        "stop_outcome": outcome,
    }


def _snap(**procs: tuple[bool, str | None]) -> dict[str, Any]:
    """Снимок: ``ProcessManager`` (жив, без итога) + перечисленные дети. ``None`` вместо кортежа — записи нет."""
    processes: dict[str, Any] = {"ProcessManager": _entry(True, None)}
    for name, spec in procs.items():
        if spec is not None:
            processes[name] = _entry(*spec)
    return {"processes": processes}


class _Drv(BackendDriver):
    """Драйвер без сокета: снимки по очереди (последний повторяется), счётчики обращений, разрыв."""

    def __init__(
        self,
        snapshots: list[dict[str, Any]],
        reply: dict[str, Any],
        clock: _Clock,
        *,
        lost_after_status_calls: int | None = None,
        lost_reads_needed: int = 2,
        break_at_call: int | None = None,
        deadline_offset_s: float | None = None,
    ) -> None:
        self._snapshots = snapshots
        self._reply = reply
        self._clock = clock
        self._lost_after = lost_after_status_calls
        self._lost_reads_needed = lost_reads_needed
        self._break_at = break_at_call
        self._deadline_offset = deadline_offset_s
        self._deadline_at: float | None = None
        self.status_calls = 0
        self.commands: list[dict] = []
        self._post_reads = 0
        self._broken = False
        super().__init__()

    @property
    def connection_lost(self) -> bool:  # type: ignore[override]
        if self._broken:
            return True
        if self._lost_after is not None and self.status_calls >= self._lost_after:
            self._post_reads += 1
            return self._post_reads >= self._lost_reads_needed
        return False

    def system_command(self, command: dict, *, timeout: float | None = None) -> dict:  # type: ignore[override]
        self.commands.append(command)
        return self._reply

    def supervision_status(self, *args: Any, **kwargs: Any) -> dict:  # type: ignore[override]
        self.status_calls += 1
        if self._break_at is not None and self.status_calls >= self._break_at:
            self._broken = True
            raise BackendUnavailable("t14: сокет закрыт PM")
        index = min(self.status_calls - 1, len(self._snapshots) - 1)
        result: dict[str, Any] = {"success": True, "epoch": 0, **self._snapshots[index]}
        if self._deadline_offset is not None:
            if self._deadline_at is None:
                self._deadline_at = self._clock.time() + self._deadline_offset
            result["system_stop"] = {
                "phase": "children",
                "mode": "graceful",
                "initiator": "unknown",
                "started_at": self._clock.time(),
                "deadline_at": self._deadline_at,
                "pre_stop_step": None,
            }
        return {"success": True, "result": result}


def _run(drv: _Drv, clock: _Clock, **kwargs: Any) -> dict[str, Any]:
    """``system_shutdown`` на фальшивых часах в daemon-потоке с дедлайном."""
    box: dict[str, Any] = {}

    def call() -> None:
        try:
            box["value"] = drv.system_shutdown(**kwargs)
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(driver_mod, "time", clock)
        thread = threading.Thread(target=call, daemon=True)
        thread.start()
        thread.join(_CALL_DEADLINE_S)
        assert not thread.is_alive(), f"system_shutdown завис дольше {_CALL_DEADLINE_S} с"
    if "error" in box:
        raise box["error"]
    return box["value"]


def _check(problems: list[str], label: str, body: Callable[[], None]) -> None:
    """Выполнить блок проверок сценария; ``AssertionError``/``KeyError`` — в список, чтобы видеть все сценарии."""
    try:
        body()
    except (AssertionError, KeyError, TypeError) as exc:
        problems.append(f"{label}: {type(exc).__name__}: {exc}")


def test_driver_merges_snapshots_unconfirmed_timed_out_accepted() -> None:
    """REDS 8: объединение снимков, ``unconfirmed``, ``timed_out``, ``accepted`` из ответа, ``wait=False``."""
    problems: list[str] = []

    # (а) снимки: a без итога -> a exited, b без итога -> запись a снята, b killed. Конец по «у всех итог».
    def scenario_a() -> None:
        clock = _Clock()
        drv = _Drv(
            [
                _snap(a=(False, None)),
                _snap(a=(False, "exited"), b=(True, None)),
                _snap(a=None, b=(False, "killed")),
            ],
            _ACCEPTED_REPLY,
            clock,
            lost_after_status_calls=3,
            lost_reads_needed=2,
        )
        res = _run(drv, clock)
        assert res["outcomes"] == {"a": "exited", "b": "killed"}, f"outcomes={res['outcomes']!r}"
        assert "ProcessManager" not in res["outcomes"], "в outcomes есть ProcessManager"
        assert res["unconfirmed"] == [], f"unconfirmed={res['unconfirmed']!r}"
        assert res["timed_out"] is False, f"timed_out={res['timed_out']!r}"
        assert res["pm_gone"] is True, f"pm_gone={res['pm_gone']!r} (сокет закрылся на 2-й пробе после конца)"
        assert res["accepted"] is True, f"accepted={res['accepted']!r}"

    _check(problems, "(а)", scenario_a)

    # (а') то же, сокет не закрывается, wait_timeout 1,0.
    def scenario_a_prime() -> None:
        clock = _Clock()
        drv = _Drv(
            [_snap(a=(False, None)), _snap(a=(False, "exited"), b=(True, None)), _snap(a=None, b=(False, "killed"))],
            _ACCEPTED_REPLY,
            clock,
        )
        res = _run(drv, clock, wait_timeout=1.0)
        assert res["pm_gone"] is False, f"pm_gone={res['pm_gone']!r}"
        assert res["timed_out"] is False, f"timed_out={res['timed_out']!r}"
        assert res["elapsed_s"] <= 1.2, f"elapsed_s={res['elapsed_s']!r}, ожидалось <= 1,2"
        assert res["outcomes"] == {"a": "exited", "b": "killed"}, f"outcomes={res['outcomes']!r}"

    _check(problems, "(а')", scenario_a_prime)

    # (б) разрыв после 2-го снимка: b без итога.
    def scenario_b() -> None:
        clock = _Clock()
        drv = _Drv(
            [_snap(a=(False, None)), _snap(a=(False, "exited"), b=(True, None))],
            _ACCEPTED_REPLY,
            clock,
            break_at_call=3,
        )
        res = _run(drv, clock)
        assert res["outcomes"]["b"] is None, f"outcomes={res['outcomes']!r}"
        assert res["outcomes"]["a"] == "exited", f"outcomes={res['outcomes']!r}"
        assert res["unconfirmed"] == ["b"], f"unconfirmed={res['unconfirmed']!r}"
        assert res["pm_gone"] is True, f"pm_gone={res['pm_gone']!r}"

    _check(problems, "(б)", scenario_b)

    # (в) wait_timeout 0,3, итогов нет.
    def scenario_c() -> None:
        clock = _Clock()
        drv = _Drv([_snap(a=(True, None))], _ACCEPTED_REPLY, clock)
        res = _run(drv, clock, wait_timeout=0.3)
        assert res["timed_out"] is True, f"timed_out={res['timed_out']!r}"
        assert res["pm_gone"] is False, f"pm_gone={res['pm_gone']!r}"

    _check(problems, "(в)", scenario_c)

    # (г) ответ accepted False, already_stopping: драйвер всё равно опрашивает.
    def scenario_d() -> None:
        clock = _Clock()
        reply = {"success": True, "accepted": False, "reason": "already_stopping", "phase": "pre_stop"}
        drv = _Drv(
            [_snap(a=(True, None)), _snap(a=(False, "exited"))],
            reply,
            clock,
            lost_after_status_calls=2,
        )
        res = _run(drv, clock)
        assert drv.status_calls >= 2, f"supervision.status опрошен {drv.status_calls} раз, ожидалось >= 2"
        assert res["accepted"] is False, f"accepted={res['accepted']!r}"

    _check(problems, "(г)", scenario_d)

    # (д) СТРАЖ: ответ-ошибка параметров — без опроса.
    def scenario_e() -> None:
        clock = _Clock()
        drv = _Drv([_snap(a=(True, None))], {"error": "mode: graceful|force"}, clock)
        res = _run(drv, clock)
        assert drv.status_calls == 0, f"supervision.status вызван {drv.status_calls} раз при ошибке параметров"
        assert res["accepted"] is False, f"accepted={res['accepted']!r}"

    _check(problems, "(д)", scenario_e)

    # (е) wait_timeout=None: срок — от system_stop.deadline_at первого снимка.
    def scenario_f(offset: float, low: float, high: float) -> None:
        clock = _Clock()
        drv = _Drv([_snap(a=(True, None))], _ACCEPTED_REPLY, clock, deadline_offset_s=offset)
        res = _run(drv, clock, wait_timeout=None)
        assert res["timed_out"] is True, f"timed_out={res['timed_out']!r}"
        assert low <= res["elapsed_s"] <= high, f"elapsed_s={res['elapsed_s']!r}, ожидалось [{low}; {high}]"

    _check(problems, "(е) deadline_at=now+30", lambda: scenario_f(30.0, 42.0, 42.5))
    _check(problems, "(е) deadline_at=now+1", lambda: scenario_f(1.0, 20.0, 20.5))

    # (ж) wait=False.
    def scenario_g() -> None:
        clock = _Clock()
        drv = _Drv([_snap(a=(True, None))], _ACCEPTED_REPLY, clock)
        res = _run(drv, clock, wait=False)
        assert res["outcomes"] is None, f"outcomes={res['outcomes']!r}"
        assert res["unconfirmed"] is None, f"unconfirmed={res['unconfirmed']!r}"
        assert res["timed_out"] is False, f"timed_out={res['timed_out']!r}"
        assert drv.status_calls == 0, f"supervision.status вызван {drv.status_calls} раз при wait=False"

    _check(problems, "(ж)", scenario_g)

    assert not problems, "\n" + "\n".join(problems)
