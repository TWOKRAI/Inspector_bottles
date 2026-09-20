# -*- coding: utf-8 -*-
"""RED-тесты Task 0.2 (`plans/observability-closure/phase-0-trust-gate.md`).

Ревью-находка M4: `process_restart_verified` считает дедлайн окна подтверждения
(``wait``) от момента ДО отправки `process.restart`, а не от момента, когда
запрос реально вернулся. Если запрос идёт дольше ``wait`` (например, потому что
``timeout`` у вызывающего больше ``wait`` и запрос честно тянется почти до
``timeout``), окно подтверждения оказывается уже съедено к моменту первого
опроса — цикл поллинга не делает ни одной итерации, и живой заново поднявшийся
процесс отдаётся как ``restarted: false``. Это ложь на грани логической ошибки.

Реализации фикса на момент написания тестов НЕТ (независимый тестер работает
ДО реализации, см. `.claude/CLAUDE.md` — "Task launch convention"). Тесты
1-4 ниже ожидаются КРАСНЫМИ. Тест класса `TestDeadInstanceGuardAlreadyHolds`
(критерий 4) — регрессионный замок на уже реализованное поведение текущего
кода; его статус (красный/зелёный) зафиксирован явно в отчёте тестера, не
скрыт.

Транспорт мокается (send_command/system_command) — по образцу
`test_restart_verified.py`. Время — ВИРТУАЛЬНОЕ (свой monotonic()/sleep()
патчатся поверх модуля `time`), чтобы буквальные wait=60/timeout=90 из
acceptance criteria проверялись мгновенно и детерминированно, без реального
ожидания и без шума разрешения `time.monotonic()` на Windows (~15.6 мс).
"""

from __future__ import annotations

import inspect
import threading
import time as time_module
from typing import Any, Dict, List, Optional

from backend_ctl.driver import BackendDriver


# ---------------------------------------------------------------------------
# Виртуальные часы: monotonic() читает счётчик, sleep() двигает его сам —
# ни один вызов в тесте реально не ждёт, даже когда wait=60.0 и timeout=90.0.
# ---------------------------------------------------------------------------


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
    request_delay: float,
    process: str = "lines",
):
    """Драйвер, где ДО-снимок и снимки ОКНА ПОДТВЕРЖДЕНИЯ различены явно (не
    одним позиционным списком, как в test_restart_verified.py) — так тест не
    может случайно перепутать «первый снимок вообще» с «первый опрос после
    возврата запроса», что здесь как раз и есть предмет проверки.

    ``request_delay`` — сколько виртуальных секунд «стоит» отправка
    `process.restart` (моделирует долгий graceful-restart запрос).
    """
    monkeypatch.setattr(time_module, "monotonic", clock.monotonic)
    monkeypatch.setattr(time_module, "sleep", clock.sleep)

    d = BackendDriver()
    calls: List[str] = []
    state = {"confirming": False, "poll_idx": 0, "poll_calls": 0}

    def fake_send(target, command, args=None, **kw):
        calls.append(command)
        if command == "supervision.status":
            if not state["confirming"]:
                entry = before_snapshot
            else:
                idx = min(state["poll_idx"], len(confirmation_snapshots) - 1)
                entry = confirmation_snapshots[idx]
                state["poll_idx"] += 1
                state["poll_calls"] += 1
            procs = {process: entry} if entry else {}
            return {"success": True, "result": {"success": True, "epoch": 0, "processes": procs}}
        return {"success": True, "result": {"success": True}}

    def fake_system(command, timeout=None):
        calls.append(f"system:{command.get('cmd')}:{command.get('process_name')}")
        clock.sleep(request_delay)  # запрос «занял» request_delay виртуальных секунд
        state["confirming"] = True
        return {"success": True}

    monkeypatch.setattr(d, "send_command", fake_send)
    monkeypatch.setattr(d, "system_command", fake_system)
    return d, calls, state


def _call_with_deadline(fn, *args, timeout_s: float = 5.0, **kwargs):
    """Гонит fn в daemon-потоке с дедлайном join.

    Правило проекта: тест, который может заблокироваться, обязан падать честно,
    а не вешать сборку — здесь это защита на случай, если виртуальные часы по
    какой-то причине не подхватятся и код уйдёт в реальное ожидание.
    """
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
            f"process_restart_verified не вернулся за {timeout_s}s реального времени — похоже на зависание"
        )
    if errors:
        raise errors[0]
    return box["value"]


class TestPollsFieldReported:
    """Критерий 1: ответ содержит `polls` — сколько снимков сделано в окне
    подтверждения. Ноль опросов не может произойти молча (значение должно
    быть числом, а не отсутствовать)."""

    def test_polls_counts_snapshots_taken_in_confirmation_window(self, monkeypatch) -> None:
        clock = _VirtualClock()
        d, _calls, _state = _driver_with_virtual_clock(
            monkeypatch,
            clock,
            before_snapshot=_entry(24808, restarts=0, alive=True),
            confirmation_snapshots=[
                _entry(24808, restarts=0, alive=True),  # 1-й опрос: ещё старый инстанс
                _entry(26476, restarts=1, alive=True),  # 2-й опрос: замена подтверждена
            ],
            request_delay=0.0,
        )
        res = _call_with_deadline(d.process_restart_verified, "lines", wait=5.0)
        # Литерал: ровно 2 опроса потребовалось до подтверждения замены.
        assert res.get("polls") == 2

    def test_first_successful_poll_is_still_counted_not_reported_as_zero(self, monkeypatch) -> None:
        """Даже когда замена видна с первого же опроса, `polls` обязан быть 1,
        а не 0 — «нашли сразу» не то же самое, что «не опрашивали вовсе»."""
        clock = _VirtualClock()
        d, _calls, _state = _driver_with_virtual_clock(
            monkeypatch,
            clock,
            before_snapshot=_entry(24808, restarts=0, alive=True),
            confirmation_snapshots=[_entry(26476, restarts=1, alive=True)],
            request_delay=0.0,
        )
        res = _call_with_deadline(d.process_restart_verified, "lines", wait=5.0)
        assert res.get("polls") == 1


class TestOrderingBugM4:
    """Критерии 2 и 3: вердикт не должен зависеть от соотношения timeout/wait,
    и дедлайн `wait` обязан стартовать ПОСЛЕ возврата запроса `process.restart`,
    а не до его отправки."""

    def test_restarted_true_with_literal_acceptance_values_wait60_timeout90(self, monkeypatch) -> None:
        """Буквальный пример из acceptance criteria: wait=60.0, timeout=90.0,
        запрос «стоит» 70 виртуальных секунд (между wait и timeout — реалистичный
        медленный graceful-restart, уложившийся в timeout вызывающего, но
        превысивший wait). Живой заново поднявшийся процесс обязан дать
        restarted=True — это и есть M4: без фикса дедлайн (0.0+60.0=60.0)
        считается ДО запроса и уже пройден к моменту его возврата (t=70.0),
        поэтому цикл поллинга не делает ни одной итерации.
        """
        clock = _VirtualClock()
        d, _calls, _state = _driver_with_virtual_clock(
            monkeypatch,
            clock,
            before_snapshot=_entry(24808, restarts=0, alive=True),
            confirmation_snapshots=[_entry(26476, restarts=1, alive=True)],
            request_delay=70.0,
        )
        res = _call_with_deadline(d.process_restart_verified, "lines", wait=60.0, timeout=90.0)
        assert res["restarted"] is True
        assert res["pid_after"] == 26476

    def test_confirmation_window_is_not_eaten_by_a_slow_request(self, monkeypatch) -> None:
        """Ложноотрицательная пара из критерия 3: request_delay (8.0) СТРОГО
        больше wait (5.0). Если бы окно wait отсчитывалось от момента ДО
        отправки запроса, оно было бы уже пройдено — цикл поллинга не должен
        был бы вообще стартовать. Правильное поведение: окно стартует от
        момента возврата запроса, так что все 5.0 секунд ещё доступны.
        """
        clock = _VirtualClock()
        d, _calls, _state = _driver_with_virtual_clock(
            monkeypatch,
            clock,
            before_snapshot=_entry(24808, restarts=0, alive=True),
            confirmation_snapshots=[_entry(999, restarts=3, alive=True)],
            request_delay=8.0,
        )
        res = _call_with_deadline(d.process_restart_verified, "lines", wait=5.0)
        assert res["restarted"] is True
        assert res["replaced"] is True
        assert res["alive"] is True
        assert res["pid_after"] == 999


class TestDeadInstanceGuardAlreadyHolds:
    """Критерий 4 (ложноположительная пара): выросший instance_restarts БЕЗ
    живого нового инстанса не должен читаться как restarted=True.

    ЧЕСТНО: судя по чтению driver.py (строки ~607-609,
    `restarted = bool(replaced and alive)`), эта защита уже реализована в
    текущем коде и уже покрыта существующим `test_restart_verified.py::
    TestVerdictFromFactNotReply::test_dead_new_instance_is_not_success`. Тест
    ниже — не новый RED для Task 0.2, а регрессионный замок: он обязан
    остаться зелёным и после фикса M4 (фикс трогает только момент старта
    дедлайна `wait`, а не формулу `restarted`). Включён в этот файл, чтобы
    вся acceptance-матрица Task 0.2 была в одном месте под одним прогоном.
    """

    def test_grown_counter_without_liveness_is_not_reported_as_restarted(self, monkeypatch) -> None:
        clock = _VirtualClock()
        d, _calls, _state = _driver_with_virtual_clock(
            monkeypatch,
            clock,
            before_snapshot=_entry(24808, restarts=0, alive=True),
            confirmation_snapshots=[_entry(26476, restarts=1, alive=False)],
            request_delay=0.0,
        )
        res = _call_with_deadline(d.process_restart_verified, "lines", wait=1.0)
        assert res["restarted"] is False
        assert res["replaced"] is True
        assert res["alive"] is False


class TestDocstringExplainsTimeoutVsWait:
    """Критерий 5: докстрока объясняет разницу timeout vs wait и содержит
    пример с обоими параметрами."""

    def test_docstring_shows_a_concrete_example_with_both_parameters(self) -> None:
        doc = inspect.getdoc(BackendDriver.process_restart_verified) or ""
        # Литералы: конкретный пример со ЗНАЧЕНИЯМИ обоих параметров рядом —
        # не абстрактное упоминание слова "timeout" (оно уже встречается в
        # докстроке как часть строки ошибки `{"error": "timeout"}`, что не
        # объясняет параметр).
        assert "wait=" in doc
        assert "timeout=" in doc
