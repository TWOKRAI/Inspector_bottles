# -*- coding: utf-8 -*-
"""Task 1.8 (L-9, `plans/lifecycle-stop-ownership.md`) — слепая приёмка ``idle=`` стопа и реестра, ДО реализации.

Контракт (стадия 0, `docs/reviews/2026-10-19_lifecycle-1.8-stage0.md` §4 D2-D3, REDS R7-R9):
  * ``ChildProcessStop(..., idle=callable)``: пока процесс жив, ``join_until`` ждёт между проходами не
    ``time.sleep``, а ``idle(pause)``; пауза в (0; ``STOP_POLL_S`` = 0,05] с; ``time.sleep`` модуля при
    живом ``idle`` не зовётся;
  * ``idle`` бросил — один WARNING, ожидание продолжается обычным сном, путь стопа не бросает;
  * ``ProcessRegistry.stop_wait_idle`` (атрибут, по умолчанию ``None``) доходит до ``ChildProcessStop``
    на каждом пути: ``stop_one``, ``stop_many``, ``stop_all``, ``children_stop``.

Слепо: источник — публичные имена и числа REDS. Любой вызов, способный зависнуть, идёт в daemon-потоке
с дедлайном join 12 с. Процессы — двойники с ``is_alive``/``terminate``/``kill``; настоящие процессы
здесь не нужны (живая проводка — ``test_pm_stop_drains_own_queue_acceptance.py``).
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from ..core import child_process_stop as cps_module
from ..core.child_process_stop import ChildProcessStop
from ..core.process_registry import ProcessRegistry

DEADLINE_S = 12.0


def _bounded(fn: Callable[[], Any], limit_s: float = DEADLINE_S) -> Any:
    """Вызов в daemon-потоке с дедлайном join; исключение потока перебрасывается в тест."""
    box: dict[str, Any] = {}

    def _run() -> None:
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 — перебрасывается ниже, в потоке теста
            box["error"] = exc

    th = threading.Thread(target=_run, name="bounded-call", daemon=True)
    th.start()
    th.join(limit_s)
    assert not th.is_alive(), f"вызов не вернулся за {limit_s} с — завис"
    if "error" in box:
        raise box["error"]
    return box.get("result")


class _AliveFor:
    """Двойник процесса: жив ровно ``passes`` первых опросов ``is_alive()``, затем мёртв."""

    def __init__(self, name: str, passes: int) -> None:
        self.name = name
        self.pid = 4242
        self._left = passes
        self.terminated = False
        self.killed = False

    def is_alive(self) -> bool:
        if self._left > 0:
            self._left -= 1
            return True
        return False

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True


class _Event:
    def __init__(self) -> None:
        self.set_calls = 0

    def set(self) -> None:
        self.set_calls += 1


class _LevelLogger:
    """Логгер стопа: пишет (уровень, текст) — граница, по которой проверяется «один WARNING»."""

    def __init__(self) -> None:
        self.records: list[tuple[str, str]] = []

    def _log_info(self, msg: str) -> None:
        self.records.append(("info", msg))

    def _log_warning(self, msg: str) -> None:
        self.records.append(("warning", msg))

    def _log_error(self, msg: str) -> None:
        self.records.append(("error", msg))

    def warnings(self) -> list[str]:
        return [text for level, text in self.records if level == "warning"]


# --------------------------------------------------------------------------- #
# R7. idle получает паузы; time.sleep модуля не зовётся
# --------------------------------------------------------------------------- #


def test_r7_idle_receives_every_pause_and_module_sleep_is_not_called(monkeypatch: pytest.MonkeyPatch) -> None:
    sleep_calls: list[float] = []

    def _boom(seconds: float) -> None:
        sleep_calls.append(seconds)
        raise AssertionError("time.sleep модуля child_process_stop вызван при живом idle")

    # Подмена только в пространстве имён модуля стопа: глобальный ``time`` тестового потока не трогаем.
    monkeypatch.setattr(cps_module, "time", SimpleNamespace(monotonic=time.monotonic, sleep=_boom))

    pauses: list[float] = []
    proc = _AliveFor("W", passes=3)
    stop = ChildProcessStop({"W": proc}, {"W": _Event()}, idle=pauses.append)

    done = _bounded(lambda: stop.join_until(time.monotonic() + 5.0))

    assert sleep_calls == [], f"time.sleep вызван с {sleep_calls}"
    assert done is True
    assert len(pauses) == 3, f"idle получил {len(pauses)} пауз за 3 прохода с живым процессом, ожидалось 3"
    assert all(0.0 < p <= 0.05 for p in pauses), f"паузы вне (0; 0,05]: {pauses}"


# --------------------------------------------------------------------------- #
# R8. idle бросает
# --------------------------------------------------------------------------- #


def test_r8_raising_idle_gives_one_warning_and_join_still_confirms_death() -> None:
    attempts: list[float] = []

    def _bad_idle(pause: float) -> None:
        attempts.append(pause)
        raise RuntimeError("idle exploded")

    logger = _LevelLogger()
    proc = _AliveFor("W", passes=3)
    stop = ChildProcessStop({"W": proc}, {"W": _Event()}, logger=logger, idle=_bad_idle)

    t0 = time.monotonic()
    done = _bounded(lambda: stop.join_until(time.monotonic() + 5.0))
    elapsed = time.monotonic() - t0

    assert done is True, "join_until после смерти процесса обязан вернуть True, даже если idle падал"
    assert attempts, "idle не вызывался вовсе — kwarg проигнорирован"
    assert len(logger.warnings()) == 1, f"WARNING о сбое idle: {logger.warnings()}, ожидался ровно 1"
    # Ожидание не превратилось в горячий цикл: каждый проход после сбоя всё равно спал свою паузу
    # (3 прохода по 0,05 с = 0,15 с; порог вдвое мягче — свойство «спит», а не точное время).
    assert elapsed >= 0.1, f"после сбоя idle ожидание не спало паузу: {elapsed:.3f} с за 3 прохода"


# --------------------------------------------------------------------------- #
# R9. Реестр передаёт stop_wait_idle на каждом пути стопа
# --------------------------------------------------------------------------- #


class _DiesAfter:
    """Двойник процесса, умирающий через ``lifetime_s`` после первого опроса — не от вызова idle.

    Смерть привязана ко времени, поэтому на реализации без ``idle`` тест заканчивается сам
    (ассертом «idle не вызван»), а не висит.
    """

    def __init__(self, name: str, lifetime_s: float = 0.3) -> None:
        self.name = name
        self.pid = 4243
        self._lifetime_s = lifetime_s
        self._born: float | None = None

    def is_alive(self) -> bool:
        now = time.monotonic()
        if self._born is None:
            self._born = now
        return now - self._born < self._lifetime_s

    def terminate(self) -> None:
        self._born = (self._born or time.monotonic()) - self._lifetime_s

    def kill(self) -> None:
        self.terminate()


def _registry_with_live_process(idle: Callable[[float], None]) -> ProcessRegistry:
    registry = ProcessRegistry()
    proc = _DiesAfter("W")
    registry.add_process(proc)  # type: ignore[arg-type]
    registry._stop_events["W"] = _Event()  # type: ignore[assignment]
    registry.stop_wait_idle = idle  # type: ignore[attr-defined]
    return registry


def _recording_idle() -> tuple[list[float], Callable[[float], None]]:
    pauses: list[float] = []

    def _idle(pause: float) -> None:
        pauses.append(pause)
        time.sleep(pause)  # idle обязан сам ждать: ChildProcessStop его паузой заменяет sleep

    return pauses, _idle


def _via_stop_one(registry: ProcessRegistry) -> Any:
    return registry.stop_one("W", 5.0)


def _via_stop_many(registry: ProcessRegistry) -> Any:
    return registry.stop_many(["W"], 5.0)


def _via_stop_all(registry: ProcessRegistry) -> Any:
    return registry.stop_all(5.0)


def _via_children_stop(registry: ProcessRegistry) -> Any:
    group = registry.children_stop(mark_reader_gone=False)
    group.request_stop()
    group.join_until(time.monotonic() + 5.0)
    return group.result()


@pytest.mark.parametrize(
    "path",
    [_via_stop_one, _via_stop_many, _via_stop_all, _via_children_stop],
    ids=["stop_one", "stop_many", "stop_all", "children_stop"],
)
def test_r9_every_registry_stop_path_waits_through_stop_wait_idle(path: Callable[[ProcessRegistry], Any]) -> None:
    pauses, idle = _recording_idle()
    registry = _registry_with_live_process(idle)

    result = _bounded(lambda: path(registry))

    assert pauses, f"{path.__name__}: stop_wait_idle не вызван ни разу — путь ждёт мимо реестра"
    assert all(p > 0.0 for p in pauses), f"{path.__name__}: пауза не положительна: {pauses}"
    # Процесс умер сам через 0,3 с — стоп подтверждён по любому из путей.
    assert result in ({"W": True}, True), f"{path.__name__}: смерть не подтверждена: {result!r}"
