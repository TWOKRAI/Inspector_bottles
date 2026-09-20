# -*- coding: utf-8 -*-
"""Остатки M4-класса, найденные ревью Ф0.5 на ДРУГИХ ногах того же вызова.

Task 0.2 закрывала одну ногу — отправку запроса. Ревьюер воспроизвёл ещё две, где
цель задачи («вердикт рестарта не зависит от соотношения `timeout` и `wait`»)
продолжала нарушаться:

* **нога опроса.** Каждый `supervision.status` в окне подтверждения уходил с ПОЛНЫМ
  `timeout` вызывающего. При `timeout > wait` один молчащий опрос съедал окно целиком:
  `wait=60, timeout=90` → `polls=1`, `elapsed=90.5`, `restarted=False` при реально
  перезапущенном процессе.
* **нога до-снимка.** `began` бралась ПОСЛЕ первого `supervision.status`, а тот тоже
  ходит к PM. `elapsed`, названный в докстроке «ценой ВСЕГО вызова», не включал его:
  до-снимок 40.0с + окно 0.5с давали `elapsed = 0.5`.

Оба сторожа существующих наборов молчали, потому что их харнессы отвечают мгновенно —
модель «PM всегда быстр» была зашита в фикстуру, а не проверена. Живьём тоже не жалит
по той же причине, и это делает дефект хуже, а не лучше: он ждёт медленного PM.

Часы виртуальные: буквальные `wait=60, timeout=90` проверяются мгновенно и без шума
разрешения `time.monotonic` на Windows (~15.6 мс).
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional

import pytest

from backend_ctl import driver as driver_module
from backend_ctl.driver import BackendDriver


class _Clock:
    """Виртуальные часы: `sleep` двигает время, а не ждёт."""

    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class _Driver(BackendDriver):
    """Драйвер с управляемой длительностью каждого обращения к PM."""

    def __init__(self, clock: _Clock, *, presnap_cost: float, poll_cost: float) -> None:
        self._clock = clock
        self._presnap_cost = presnap_cost
        self._poll_cost = poll_cost
        self._calls = 0
        #: Таймаут, с которым ушёл каждый `supervision.status` — предмет находки 2.
        self.poll_timeouts: List[Optional[float]] = []

    def supervision_status(self, process: Any = None, *, pm_name: str = "", timeout: Any = None) -> Dict[str, Any]:
        self._calls += 1
        первый = self._calls == 1
        self.poll_timeouts.append(timeout)
        # Обращение стоит времени — ровно то, чего не было в прежних харнессах.
        цена = self._presnap_cost if первый else self._poll_cost
        разрешено = цена if timeout is None else min(цена, timeout)
        self._clock.now += разрешено
        if разрешено < цена:
            # ЧЕСТНОСТЬ ФЕЙКА: если ответ не успел за отведённый таймаут — это ОТКАЗ,
            # а не ответ, пришедший позже. Первая редакция возвращала успех в любом
            # случае и тем смешивала «PM ответил за 90с» с «мы прождали 90с и что-то
            # получили»; тест на этом фейке мерил артефакт харнесса, а не свойство кода.
            return {"success": False, "error": "timeout"}
        pid = 100 if первый else 200
        restarts = 0 if первый else 1
        return {
            "success": True,
            "processes": {"p": {"pid": pid, "instance_restarts": restarts, "alive": True}},
        }

    def system_command(self, payload: Any, *, timeout: Any = None) -> Dict[str, Any]:
        return {"success": True}


def _run(drv: BackendDriver, **kw: Any) -> Dict[str, Any]:
    """Вызов в daemon-потоке с дедлайном: зависший тест хуже отсутствующего."""
    итог: Dict[str, Any] = {}

    def тело() -> None:
        итог.update(drv.process_restart_verified("p", **kw))

    t = threading.Thread(target=тело, daemon=True)
    t.start()
    t.join(timeout=5.0)
    assert not t.is_alive(), "process_restart_verified завис вместо того, чтобы вынести вердикт"
    return итог


@pytest.fixture()
def clock(monkeypatch: pytest.MonkeyPatch) -> _Clock:
    c = _Clock()
    import time as _t

    monkeypatch.setattr(_t, "monotonic", c.monotonic)
    monkeypatch.setattr(_t, "sleep", c.sleep)
    assert driver_module is not None
    return c


class TestPollLegRespectsTheWindow:
    """Находка 2 ревью: опрос не может стоить больше остатка окна `wait`."""

    def test_a_silent_pm_cannot_overrun_the_callers_wait_budget(self, clock: _Clock) -> None:
        """`wait=60, timeout=90`, PM молчит: вызов не тратит больше, чем попросили.

        **Первая редакция этого теста требовала `polls >= 2` и была неверна** — не код,
        а моя модель. Молчащий PM законно расходует окно одним долгим опросом: лишние
        опросы молчащего собеседника ничего не добавляют. Реальный дефект, который
        воспроизвёл ревьюер, — ПЕРЕРАСХОД: `elapsed = 90.5` при `wait = 60`, то есть
        вызов забирал у оператора в полтора раза больше времени, чем тот отвёл, и делал
        это тем охотнее, чем больше `timeout`. Здесь сторожится именно бюджет.
        """
        drv = _Driver(clock, presnap_cost=0.0, poll_cost=90.0)
        res = _run(drv, wait=60.0, timeout=90.0)
        assert res["elapsed"] <= 61.0, (
            f"вызов израсходовал {res['elapsed']}с при wait=60.0 — окно подтверждения "
            f"перерасходовано таймаутом опроса; таймауты={drv.poll_timeouts!r}"
        )

    def test_the_verdict_does_not_depend_on_the_timeout_to_wait_ratio(self, clock: _Clock) -> None:
        """Дословная цель Task 0.2 на ноге опроса: `timeout` не меняет вердикт.

        Один и тот же молчащий PM и одно и то же окно `wait=60`; меняется только
        `timeout` — 90 (больше окна) против 30 (меньше). Прежде первый давал
        `elapsed=90.5`, второй — укладывался в окно: соотношение решало.
        """
        drv_большой = _Driver(_Clock(), presnap_cost=0.0, poll_cost=90.0)
        import time as _t

        _t.monotonic, _t.sleep = drv_большой._clock.monotonic, drv_большой._clock.sleep
        большой = _run(drv_большой, wait=60.0, timeout=90.0)

        drv_малый = _Driver(_Clock(), presnap_cost=0.0, poll_cost=90.0)
        _t.monotonic, _t.sleep = drv_малый._clock.monotonic, drv_малый._clock.sleep
        малый = _run(drv_малый, wait=60.0, timeout=30.0)

        assert большой["restarted"] == малый["restarted"], (
            f"вердикт зависит от соотношения: timeout=90 → {большой['restarted']}, timeout=30 → {малый['restarted']}"
        )
        assert abs(большой["elapsed"] - малый["elapsed"]) <= 1.0, (
            f"цена вызова зависит от timeout, а не от wait: {большой['elapsed']} против {малый['elapsed']}"
        )

    def test_no_poll_is_issued_with_more_than_the_remaining_window(self, clock: _Clock) -> None:
        """Ни один опрос не уходит с таймаутом больше остатка окна.

        Литерал `60.0` — это `wait`; проверяется наблюдаемый эффект (аргумент, с которым
        реально позвали PM), а не имя внутренней функции: подмена `_poll_timeout`
        эквивалентным кодом свойство не должна ронять.
        """
        drv = _Driver(clock, presnap_cost=0.0, poll_cost=90.0)
        _run(drv, wait=60.0, timeout=90.0)
        опросы = drv.poll_timeouts[1:]  # [0] — до-снимок, он вне окна
        assert опросы, "опросов не было вовсе — проверять нечего"
        assert all(t is not None and t <= 60.0 for t in опросы), (
            f"опрос ушёл с таймаутом больше окна wait=60.0: {опросы!r}"
        )


class TestElapsedIncludesThePreSnapshot:
    """Находка 3 ревью: `elapsed` — цена ВСЕГО вызова, включая до-снимок."""

    def test_a_slow_pre_snapshot_is_visible_in_elapsed(self, clock: _Clock) -> None:
        """До-снимок 40с + окно: `elapsed` обязан быть не меньше 40, а не 0.5."""
        drv = _Driver(clock, presnap_cost=40.0, poll_cost=0.0)
        res = _run(drv, wait=1.0, timeout=90.0)
        assert res["elapsed"] >= 40.0, (
            f"elapsed не покрыл до-снимок: докстрока обещает «цену ВСЕГО вызова», а показано {res['elapsed']}"
        )
