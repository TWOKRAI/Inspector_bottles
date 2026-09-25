# -*- coding: utf-8 -*-
"""Hazard-тесты автора ServiceHost (Task 1b.5) — места, которые видны только из устройства.

Что может сломаться в ЭТОМ механизме:
  * старт в daemon-потоке: второй ``start`` во время полёта обязан ждать тот же старт, а не
    звать ``cls()`` второй раз; ответ ``pending`` не должен терять итог — поток сам доводит
    lifecycle до running/error;
  * замок на сервис: ``stop`` не должен вклиниться в идущий ``start()`` того же экземпляра,
    а замок одного сервиса не должен держать команды другого;
  * ``stop`` незапущенного — не ошибка и не вызов ``instance.stop()``;
  * ленивый discover: ровно один вызов при гонке первых команд, сбой discover не валит список.

Всё, что может заблокироваться, идёт в daemon-потоке с дедлайном join.
"""

from __future__ import annotations

import threading
import time

import pytest

from multiprocess_framework.modules.service_module import scanner as scanner_module
from multiprocess_framework.modules.service_module.host import ServiceHost
from multiprocess_framework.modules.service_module.interfaces import ServiceLifecycle
from multiprocess_framework.modules.service_module.registry import ServiceEntry, ServiceRegistry
from multiprocess_framework.modules.service_module.scanner import DiscoveryResult


@pytest.fixture(autouse=True)
def _clean_registry():
    ServiceRegistry().clear()
    yield
    ServiceRegistry().clear()


def _register(name: str, cls: type) -> None:
    ServiceRegistry().register(ServiceEntry(name=name, cls=cls, lifecycle=ServiceLifecycle.READY))


def _in_thread(fn, *args, deadline: float = 5.0):
    """Вызвать ``fn(*args)`` в daemon-потоке; вернуть (результат, секунды). Зависание — провал, не хэнг."""
    out: dict = {}

    def run() -> None:
        t0 = time.monotonic()
        out["value"] = fn(*args)
        out["elapsed"] = time.monotonic() - t0

    th = threading.Thread(target=run, daemon=True)
    th.start()
    th.join(deadline)
    assert not th.is_alive(), f"вызов не вернулся за {deadline}с"
    return out["value"], out["elapsed"]


def _wait_for(predicate, deadline: float = 5.0) -> bool:
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False


# ------------------------------------------------------------------
# (а) + pending: второй start во время полёта — тот же старт, без второго cls()
# ------------------------------------------------------------------


def test_second_start_while_pending_does_not_instantiate_again() -> None:
    inits: list[int] = []
    release = threading.Event()

    class _Gated:
        def __init__(self) -> None:
            inits.append(1)

        def start(self, config: dict) -> bool:
            return release.wait(5.0)

        def stop(self) -> bool:
            return True

        def get_status(self) -> dict:
            return {}

    _register("gated", _Gated)
    start = ServiceHost(start_wait_sec=0.05).handlers()["service.start"]

    threads_before = threading.active_count()
    first, _ = _in_thread(start, {"name": "gated"})
    second, _ = _in_thread(start, {"name": "gated"})
    # Второй start во время полёта не порождает второго стартующего потока.
    # (Один cls() держат ДВА предохранителя: переиспользование job И замок+перепроверка
    # RUNNING в потоке — снятие одного из них этот assert и ловит.)
    workers = threading.active_count() - threads_before
    release.set()
    assert workers == 1, f"стартующих потоков в полёте: {workers}, ожидался 1"

    assert first == {"success": True, "name": "gated", "lifecycle": "ready", "pending": True}
    assert second == {"success": True, "name": "gated", "lifecycle": "ready", "pending": True}
    assert _wait_for(lambda: ServiceRegistry().get("gated").lifecycle == ServiceLifecycle.RUNNING)
    assert len(inits) == 1


# ------------------------------------------------------------------
# pending: ответ быстрый, итог доводит поток (running и error)
# ------------------------------------------------------------------


@pytest.mark.parametrize(("start_result", "final"), [(True, "running"), (False, "error")])
def test_pending_start_is_finished_by_worker(start_result: bool, final: str) -> None:
    class _Slow:
        def start(self, config: dict) -> bool:
            time.sleep(0.4)
            return start_result

        def stop(self) -> bool:
            return True

        def get_status(self) -> dict:
            return {"state": "x"}

    _register("slow", _Slow)
    handlers = ServiceHost(start_wait_sec=0.05).handlers()

    reply, elapsed = _in_thread(handlers["service.start"], {"name": "slow"})
    assert reply.get("pending") is True
    assert elapsed < 0.3, f"start держал вызывающего {elapsed:.3f}с при start_wait_sec=0.05"

    # Пока старт в полёте, status не трогает get_status() экземпляра.
    status, _ = _in_thread(handlers["service.status"], {"name": "slow"})
    assert status["detail"] == {"pending": True}

    assert _wait_for(lambda: handlers["service.status"]({"name": "slow"})["lifecycle"] == final)


# ------------------------------------------------------------------
# (б) исключение в start -> error, хост отвечает; повторный start пробует снова
# ------------------------------------------------------------------


def test_start_failure_is_structured_and_retryable() -> None:
    attempts: list[int] = []

    class _FlakyOnce:
        def start(self, config: dict) -> bool:
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError("first attempt fails")
            return True

        def stop(self) -> bool:
            return True

        def get_status(self) -> dict:
            return {}

    _register("flaky", _FlakyOnce)
    start = ServiceHost().handlers()["service.start"]

    first, _ = _in_thread(start, {"name": "flaky"})
    assert first["success"] is False
    assert first["error"] == "start_failed"
    assert first["lifecycle"] == "error"
    assert "first attempt fails" in first["message"]

    second, _ = _in_thread(start, {"name": "flaky"})
    assert second == {"success": True, "name": "flaky", "lifecycle": "running"}
    assert len(attempts) == 2


# ------------------------------------------------------------------
# (в) stop незапущенного — не ошибка и не вызов instance.stop()
# ------------------------------------------------------------------


def test_stop_never_started_is_success_without_instance() -> None:
    created: list[int] = []

    class _Never:
        def __init__(self) -> None:
            created.append(1)

        def start(self, config: dict) -> bool:
            return True

        def stop(self) -> bool:
            raise AssertionError("stop() незапущенного сервиса вызываться не должен")

        def get_status(self) -> dict:
            return {}

    _register("never", _Never)
    stop = ServiceHost().handlers()["service.stop"]

    reply, _ = _in_thread(stop, {"name": "never"})
    assert reply == {"success": True, "name": "never", "lifecycle": "stopped"}
    assert created == []


# ------------------------------------------------------------------
# замок на сервис: stop не вклинивается в start того же; другой сервис не ждёт
# ------------------------------------------------------------------


def test_stop_during_inflight_start_answers_start_in_progress_without_waiting() -> None:
    """stop во время старта в полёте — сразу start_in_progress, не ждёт замок; после старта stop обычный."""
    events: list[str] = []

    class _Logged:
        def start(self, config: dict) -> bool:
            events.append("start_begin")
            time.sleep(5.0)
            events.append("start_end")
            return True

        def stop(self) -> bool:
            events.append("stop")
            return True

        def get_status(self) -> dict:
            return {}

    _register("logged", _Logged)
    handlers = ServiceHost(start_wait_sec=0.01).handlers()

    pending, _ = _in_thread(handlers["service.start"], {"name": "logged"})
    assert pending.get("pending") is True

    refused, elapsed = _in_thread(handlers["service.stop"], {"name": "logged"}, deadline=2.0)
    assert refused == {"success": False, "error": "start_in_progress", "name": "logged", "lifecycle": "ready"}
    assert elapsed < 0.5, f"stop ждал {elapsed:.3f}с при старте в полёте"
    restart, _ = _in_thread(handlers["service.restart"], {"name": "logged"}, deadline=2.0)
    assert restart["error"] == "start_in_progress"
    assert events == ["start_begin"]  # stop() не вызван, не вклинился в start()

    assert _wait_for(lambda: ServiceRegistry().get("logged").lifecycle == ServiceLifecycle.RUNNING, deadline=7.0)
    stopped, _ = _in_thread(handlers["service.stop"], {"name": "logged"})
    assert stopped == {"success": True, "name": "logged", "lifecycle": "stopped"}
    assert events == ["start_begin", "start_end", "stop"]


def test_slow_start_of_one_service_does_not_hold_stop_of_another() -> None:
    """(г) в разрезе хоста: замок сервиса A не общий — stop сервиса B отвечает сразу."""
    release = threading.Event()

    class _Stuck:
        def start(self, config: dict) -> bool:
            return release.wait(5.0)

        def stop(self) -> bool:
            return True

        def get_status(self) -> dict:
            return {}

    class _Fast:
        def start(self, config: dict) -> bool:
            return True

        def stop(self) -> bool:
            return True

        def get_status(self) -> dict:
            return {}

    _register("stuck", _Stuck)
    _register("fast", _Fast)
    handlers = ServiceHost(start_wait_sec=0.01).handlers()
    try:
        assert _in_thread(handlers["service.start"], {"name": "fast"})[0]["lifecycle"] == "running"
        assert _in_thread(handlers["service.start"], {"name": "stuck"})[0].get("pending") is True

        reply, elapsed = _in_thread(handlers["service.stop"], {"name": "fast"})
        list_reply, list_elapsed = _in_thread(handlers["service.list"], {})
    finally:
        release.set()

    assert reply == {"success": True, "name": "fast", "lifecycle": "stopped"}
    assert elapsed < 0.2, f"stop чужого сервиса ждал {elapsed:.3f}с"
    assert list_reply["success"] is True and list_elapsed < 0.2


# ------------------------------------------------------------------
# ленивый discover: ровно один при гонке; сбой — в failed, список отвечает
# ------------------------------------------------------------------


def test_lazy_discover_runs_exactly_once_under_concurrency(monkeypatch, tmp_path) -> None:
    calls: list[tuple] = []

    def fake_discover(*dirs):
        calls.append(dirs)
        time.sleep(0.1)  # расширяет окно гонки первых вызовов
        return DiscoveryResult(loaded=["ok/service.py"], failed=[("broken/service.py", "ImportError: x")])

    monkeypatch.setattr(scanner_module, "discover", fake_discover)
    host = ServiceHost(service_paths=[tmp_path])
    handlers = host.handlers()
    assert calls == [], "discover должен быть ленивым — не в конструкторе"

    replies: list[dict] = []
    threads = [
        threading.Thread(target=lambda c=c: replies.append(handlers[c]({"name": "x"})), daemon=True)
        for c in ("service.list", "service.status", "service.list", "service.start") * 2
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5.0)
    assert not any(t.is_alive() for t in threads)

    assert len(calls) == 1
    assert calls[0] == (tmp_path,)
    listing = handlers["service.list"]({})
    assert listing["failed"] == {"broken/service.py": "ImportError: x"}
    assert len(calls) == 1


def test_discover_crash_does_not_kill_list(monkeypatch, tmp_path) -> None:
    def exploding(*dirs):
        raise OSError("disk gone")

    monkeypatch.setattr(scanner_module, "discover", exploding)
    reply, _ = _in_thread(ServiceHost(service_paths=[tmp_path]).handlers()["service.list"], {})
    assert reply["success"] is True
    assert reply["services"] == []
    assert reply["failed"] == {"<discover>": "OSError: disk gone"}


def test_no_service_paths_means_no_discover(monkeypatch) -> None:
    monkeypatch.setattr(scanner_module, "discover", lambda *d: pytest.fail("discover без service_paths"))
    reply = ServiceHost().handlers()["service.list"]({})
    assert reply == {"success": True, "services": [], "failed": {}}
