# -*- coding: utf-8 -*-
"""Дыры, вскрытые матрицей инъекций Task 0.2 (`plans/observability-closure/injections-phase-0.md`).

Оба теста здесь появились не «на всякий случай», а по результату слом-инъекции,
которая дала **ноль** красных там, где заявленное свойство существует:

* **Инъекция C** — «считать только успешные опросы» (`polls += 1` после `continue`
  по ``__error__``). Ноль красных. Докстрока метода при этом прямо обещает
  обратное: «Опрос, вернувший ``__error__``… тоже считается в ``polls`` — это была
  реальная попытка и реальная секунда из бюджета ``wait``». Обещание без сторожа
  живёт ровно до первой правки цикла.
* **Инъекция E** — считать ``elapsed`` от начала окна подтверждения, а не от начала
  вызова. Ноль красных. Единственный существующий сторож
  (``test_restart_verified.py``: ``elapsed >= 0.5``) верен при ОБОИХ определениях,
  то есть согласен с любым ответом — а разница между ними для оператора в секундах
  graceful-stop'а, то есть в десятках секунд.

Оба свойства проверяются наблюдаемым ЧИСЛОМ в ответе, а не именем внутреннего
вызова: подмена реализации на эквивалентную не должна тихо снимать гарантию.
"""

from __future__ import annotations

import time as time_module
from typing import Any, Dict, List, Optional

from backend_ctl.driver import BackendDriver


class _VirtualClock:
    """Часы теста: patched поверх атрибутов МОДУЛЯ ``time`` (как у соседних файлов)."""

    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _entry(pid: Optional[int], *, restarts: int = 0, alive: bool = True) -> Dict[str, Any]:
    return {
        "incarnation": 0,
        "restart_count": 0,
        "last_exit": None,
        "status": "running",
        "pid": pid,
        "alive": alive,
        "started_at": 1000.0,
        "instance_restarts": restarts,
    }


def _driver(
    monkeypatch,
    clock: "_VirtualClock",
    *,
    before: Dict[str, Any],
    poll_plan: List[Any],
    request_delay: float = 0.0,
    process: str = "lines",
) -> BackendDriver:
    """Харнесс с ПЛАНОМ ОПРОСОВ, где элемент может быть отказом PM.

    ``poll_plan[i]`` — либо снимок процесса (dict), либо ``None``, означающий
    «PM не ответил на этом опросе» (драйвер увидит ``__error__`` и пойдёт на
    следующий круг). Именно этой формы нет в соседних харнессах: у них PM всегда
    отвечает, поэтому ветку ``continue`` они не проходят вовсе.
    """
    monkeypatch.setattr(time_module, "monotonic", clock.monotonic)
    monkeypatch.setattr(time_module, "sleep", clock.sleep)

    d = BackendDriver()
    state = {"confirming": False, "idx": 0}

    def fake_send(target, command, args=None, **kw):
        if command != "supervision.status":
            return {"success": True, "result": {"success": True}}
        if not state["confirming"]:
            return {"success": True, "result": {"success": True, "epoch": 0, "processes": {process: before}}}
        step = poll_plan[min(state["idx"], len(poll_plan) - 1)]
        state["idx"] += 1
        if step is None:
            # «PM моргнул на рестарте»: ответ без ключа processes — драйвер
            # обязан прочитать его как __error__ и продолжить ждать.
            return {"success": False, "error": "timeout"}
        return {"success": True, "result": {"success": True, "epoch": 0, "processes": {process: step}}}

    def fake_system(command, timeout=None):
        clock.sleep(request_delay)
        state["confirming"] = True
        return {"success": True}

    monkeypatch.setattr(d, "send_command", fake_send)
    monkeypatch.setattr(d, "system_command", fake_system)
    return d


class TestErroredPollIsStillCounted:
    """Инъекция C: опрос, на котором PM не ответил, обязан считаться в ``polls``."""

    def test_polls_counts_the_attempt_where_pm_did_not_answer(self, monkeypatch) -> None:
        """Два отказа PM, затем успех → ``polls == 3``, а не ``1``.

        Литерал 3 написан, а не выведен из длины плана: тест, считающий ожидание
        тем же выражением, что и код, согласится с любым ответом.
        """
        clock = _VirtualClock()
        d = _driver(
            monkeypatch,
            clock,
            before=_entry(100, restarts=0),
            poll_plan=[None, None, _entry(200, restarts=1)],
        )
        res = d.process_restart_verified("lines", wait=30.0, timeout=5.0)

        assert res["restarted"] is True, res.get("reason")
        assert res["polls"] == 3

    def test_a_window_spent_entirely_on_pm_failures_reports_those_polls(self, monkeypatch) -> None:
        """Окно, целиком ушедшее в отказы PM, отдаёт НЕнулевой ``polls``.

        Это вторая половина пары: без неё «ноль опросов» и «опросы были, но все
        мимо» читались бы одинаково — а различает их именно то, ради чего поле
        заводилось.
        """
        clock = _VirtualClock()
        d = _driver(
            monkeypatch,
            clock,
            before=_entry(100, restarts=0),
            poll_plan=[None],  # PM не отвечает до самого конца окна
        )
        res = d.process_restart_verified("lines", wait=2.0, timeout=5.0)

        assert res["restarted"] is False
        assert res["polls"] == 4  # окно 2.0с при шаге поллинга 0.5с


class TestElapsedCoversTheWholeCall:
    """Инъекция E: ``elapsed`` — цена всего вызова, а не длина окна подтверждения."""

    def test_elapsed_includes_the_time_spent_sending_the_request(self, monkeypatch) -> None:
        """Запрос тянулся 70с, подтверждение пришло с первого опроса → ``elapsed`` ≈ 70.5.

        При отсчёте от начала окна подтверждения было бы 0.5 — и оператор,
        спросивший «сколько стоил проверенный рестарт», получил бы ответ,
        занижённый в 140 раз. Проверяется числом из ответа, не именем вызова.
        """
        clock = _VirtualClock()
        d = _driver(
            monkeypatch,
            clock,
            before=_entry(100, restarts=0),
            poll_plan=[_entry(200, restarts=1)],
            request_delay=70.0,
        )
        res = d.process_restart_verified("lines", wait=60.0, timeout=90.0)

        assert res["restarted"] is True, res.get("reason")
        assert res["elapsed"] == 70.5
