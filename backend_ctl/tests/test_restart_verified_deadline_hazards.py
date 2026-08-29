# -*- coding: utf-8 -*-
"""Дополнительные hazard-тесты Task 0.2 (`plans/observability-closure/phase-0-trust-gate.md`).

Это СВОИ тесты автора реализации — на риски, которые независимый тестер не мог
увидеть, не читая исходники фикса (см. `.claude/CLAUDE.md` — "Author writes hazard
tests for the mechanism"). RED-набор тестера (`test_restart_verified_timeout_wait_
ordering.py`) остаётся спекой на ПОВЕДЕНИЕ вердикта; этот файл — на МЕХАНИЗМ:

1. Патч виртуальных часов у RED-теста бьёт по атрибутам МОДУЛЯ `time`
   (`time.monotonic`/`time.sleep`). Если реализация перейдёт на
   `time.perf_counter()` (не патчится этим же механизмом) или захватит ссылку на
   функцию в момент импорта — патч тихо перестанет действовать: тест не упадёт по
   логике, код просто уйдёт в реальное ожидание. Guard ниже — trip-wire на именно
   этот регресс: гоняет вызов с большим ВИРТУАЛЬНЫМ `wait` в daemon-потоке с
   маленьким РЕАЛЬНЫМ join-бюджетом.
2. `wait <= 0` — нулевое и отрицательное окно подтверждения: сколько тогда
   `polls` и какой вердикт. Решено явно (0 опросов, честный `restarted=False`),
   не оставлено на волю случая.
3. `timeout=None` (путь по умолчанию) и `timeout` по обе стороны от капа —
   механика `min(timeout, 5.0)` /  `timeout is None → 5.0`. Тестер её увидеть не
   мог: его фейковый `system_command` не смотрит на переданный `timeout`, поэтому
   этот параметр можно сломать молча, и RED-набор тестера этого не заметит.

Часы — тем же способом, что у тестера (патч `time.monotonic`/`time.sleep`
МОДУЛЯ `time`), харнесс транспорта продублирован намеренно: файл тестера трогать
нельзя, а тянуть кросс-файловую зависимость ради общего фикстура дороже, чем
полсотни строк дублирования.
"""

from __future__ import annotations

import threading
import time as time_module
from typing import Any, Dict, List, Optional

from backend_ctl.driver import BackendDriver, _RESTART_REQUEST_TIMEOUT_S


class _VirtualClock:
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


def _driver_with_virtual_clock(
    monkeypatch,
    clock: "_VirtualClock",
    *,
    before_snapshot: Dict[str, Any],
    confirmation_snapshots: List[Dict[str, Any]],
    request_delay: float = 0.0,
    process: str = "lines",
):
    """Харнесс-двойник тестерского (`test_restart_verified_timeout_wait_ordering.py`),
    продублированный здесь намеренно — см. докстроку модуля. Отличие: фиксирует
    KWARGS каждого вызова `system_command` (нужно для проверки капа таймаута
    запроса, п.3), а не только последовательность имён команд.
    """
    monkeypatch.setattr(time_module, "monotonic", clock.monotonic)
    monkeypatch.setattr(time_module, "sleep", clock.sleep)

    d = BackendDriver()
    system_calls: List[Dict[str, Any]] = []
    state = {"confirming": False, "poll_idx": 0}

    def fake_send(target, command, args=None, **kw):
        if command == "supervision.status":
            if not state["confirming"]:
                entry = before_snapshot
            else:
                idx = min(state["poll_idx"], len(confirmation_snapshots) - 1)
                entry = confirmation_snapshots[idx]
                state["poll_idx"] += 1
            procs = {process: entry} if entry else {}
            return {"success": True, "result": {"success": True, "epoch": 0, "processes": procs}}
        return {"success": True, "result": {"success": True}}

    def fake_system(command, timeout=None):
        system_calls.append({"command": command, "timeout": timeout})
        clock.sleep(request_delay)
        state["confirming"] = True
        return {"success": True}

    monkeypatch.setattr(d, "send_command", fake_send)
    monkeypatch.setattr(d, "system_command", fake_system)
    return d, system_calls


def _call_with_deadline(fn, *args, timeout_s: float = 5.0, **kwargs):
    """Тот же приём, что у тестера: daemon-поток + join-дедлайн. Честный fail с
    объясняющим сообщением вместо зависшей сборки, если виртуальные часы почему-то
    не подхватились (регресс на `time.perf_counter()` или захваченную ссылку)."""
    box: Dict[str, Any] = {}
    errors: List[BaseException] = []

    def _target() -> None:
        try:
            box["value"] = fn(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001 — харнесс обязан поймать всё, иначе join не имеет смысла
            errors.append(exc)

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    t.join(timeout_s)
    if t.is_alive():
        raise AssertionError(
            f"process_restart_verified не вернулся за {timeout_s}s РЕАЛЬНОГО времени — похоже, "
            "time.monotonic/time.sleep больше не патчатся (переход на time.perf_counter()? "
            "захваченная в момент импорта ссылка на функцию?), и код ушёл в настоящее ожидание"
        )
    if errors:
        raise errors[0]
    return box["value"]


class TestClockPatchGuard:
    """Хазард 1: если бы реализация держалась за `time.perf_counter()` вместо
    `time.monotonic()`, монки-патч часов молча переставал бы действовать — цикл
    подтверждения спинил бы РЕАЛЬНЫЕ ~20 секунд вместо виртуальных."""

    def test_large_virtual_wait_exhausts_without_real_delay(self, monkeypatch) -> None:
        clock = _VirtualClock()
        # Снимок в окне подтверждения НИКОГДА не показывает замену — цикл обязан
        # честно дойти до дедлайна (40 витков = 20.0 / 0.5), а не найти совпадение
        # на первой же итерации (что замаскировало бы регресс на perf_counter,
        # ведь один виток дёшев в реальном времени при любых часах).
        d, _calls = _driver_with_virtual_clock(
            monkeypatch,
            clock,
            before_snapshot=_entry(111, restarts=0, alive=True),
            confirmation_snapshots=[_entry(111, restarts=0, alive=True)],
            request_delay=0.0,
        )
        # wait=20 ВИРТУАЛЬНЫХ секунд, реальный join-бюджет — 2s. С патчибельными
        # часами 40 витков цикла (мокнутый send_command) укладываются в
        # миллисекунды реального времени. Если бы дедлайн считался по
        # НЕпатчнутому perf_counter — цикл спинил бы реальные ~20s, guard упал бы
        # по join с объясняющим сообщением, а не повесил сборку.
        res = _call_with_deadline(d.process_restart_verified, "lines", wait=20.0, timeout_s=2.0)
        assert res["polls"] == 40
        assert res["restarted"] is False


class TestZeroOrNegativeWaitWindow:
    """Хазард 2: `wait<=0` — окно подтверждения нулевое. Решение (не оставлено на
    удачу): дедлайн уже пройден до входа в цикл → 0 опросов, вердикт честно
    `restarted=False` с причиной «не подтверждена за {wait}s» — она буквально
    верна, опросов действительно не было ни одного.

    Оба теста намеренно кладут в окно подтверждения снимок, УЖЕ показывающий
    подтверждённую замену (pid сменился, alive=True) — если бы цикл всё-таки
    сделал хоть один опрос, тест поймал бы это по `restarted=True`/`polls>0`,
    а не только по факту «функция не зависла»."""

    def test_wait_zero_yields_zero_polls_and_honest_failure(self, monkeypatch) -> None:
        clock = _VirtualClock()
        d, _calls = _driver_with_virtual_clock(
            monkeypatch,
            clock,
            before_snapshot=_entry(111, restarts=0, alive=True),
            confirmation_snapshots=[_entry(222, restarts=1, alive=True)],
            request_delay=0.0,
        )
        res = _call_with_deadline(d.process_restart_verified, "lines", wait=0.0)
        assert res["polls"] == 0
        assert res["restarted"] is False
        assert res["replaced"] is False
        assert "не подтверждена" in res["reason"]

    def test_negative_wait_behaves_like_zero_not_like_unlimited(self, monkeypatch) -> None:
        """Отрицательный `wait` не должен читаться как «ждать бесконечно» —
        регрессионный замок именно в связке с НОВЫМ стартом дедлайна (после
        возврата запроса, а не до): `max(0.0, wait)` существовал и раньше, но
        здесь проверяется, что перестановка старта дедлайна его не обошла."""
        clock = _VirtualClock()
        d, _calls = _driver_with_virtual_clock(
            monkeypatch,
            clock,
            before_snapshot=_entry(111, restarts=0, alive=True),
            confirmation_snapshots=[_entry(222, restarts=1, alive=True)],
            request_delay=0.0,
        )
        res = _call_with_deadline(d.process_restart_verified, "lines", wait=-5.0)
        assert res["polls"] == 0
        assert res["restarted"] is False


class TestRequestTimeoutCap:
    """Хазарды 3 и 4: механика `min(timeout, 5.0)` / `timeout is None → 5.0`.
    Тестер её не видел — его фейковый `system_command` игнорирует переданный
    `timeout`, поэтому эту механику можно сломать молча, и его зелёный набор
    этого не заметит. Проверяем ЗНАЧЕНИЕ, с которым реально вызывается
    `system_command`, а не только итоговый вердикт."""

    def test_timeout_none_sends_request_with_the_cap(self, monkeypatch) -> None:
        clock = _VirtualClock()
        d, calls = _driver_with_virtual_clock(
            monkeypatch,
            clock,
            before_snapshot=_entry(111, restarts=0, alive=True),
            confirmation_snapshots=[_entry(222, restarts=1, alive=True)],
            request_delay=0.0,
        )
        _call_with_deadline(d.process_restart_verified, "lines", wait=5.0, timeout=None)
        assert len(calls) == 1
        # Литерал из ТЗ (Task 0.2, шаг 1): "при timeout=None — 5.0".
        assert calls[0]["timeout"] == 5.0

    def test_timeout_smaller_than_cap_is_not_raised_to_the_cap(self, monkeypatch) -> None:
        clock = _VirtualClock()
        d, calls = _driver_with_virtual_clock(
            monkeypatch,
            clock,
            before_snapshot=_entry(111, restarts=0, alive=True),
            confirmation_snapshots=[_entry(222, restarts=1, alive=True)],
            request_delay=0.0,
        )
        _call_with_deadline(d.process_restart_verified, "lines", wait=5.0, timeout=2.0)
        assert calls[0]["timeout"] == 2.0

    def test_timeout_larger_than_cap_is_capped(self, monkeypatch) -> None:
        clock = _VirtualClock()
        d, calls = _driver_with_virtual_clock(
            monkeypatch,
            clock,
            before_snapshot=_entry(111, restarts=0, alive=True),
            confirmation_snapshots=[_entry(222, restarts=1, alive=True)],
            request_delay=0.0,
        )
        _call_with_deadline(d.process_restart_verified, "lines", wait=5.0, timeout=90.0)
        assert calls[0]["timeout"] == 5.0

    def test_cap_constant_matches_the_literal_named_in_the_spec(self) -> None:
        """Именованная константа модуля существует и равна значению из ТЗ (5.0),
        а не плавающему числу, продублированному где-то ещё в коде."""
        assert _RESTART_REQUEST_TIMEOUT_S == 5.0
