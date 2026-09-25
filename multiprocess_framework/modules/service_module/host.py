# -*- coding: utf-8 -*-
"""ServiceHost — хост жизненного цикла сервисов за командами ``service.*`` (Task 1b.5).

Хост живёт там, где его зарегистрировали (в прототипе — хаб ``ProcessManager``,
ADR-SVC-002), и отдаёт пять обработчиков ``handler(args: dict) -> dict``:

    service.list     -> {"success", "services": [{"name","display_name","lifecycle","metadata"}], "failed"}
    service.status   -> {"success", "name", "lifecycle", "detail"}
    service.start    -> {"success", "name", "lifecycle"}  (+ "pending": True, если старт не успел)
    service.stop     -> {"success", "name", "lifecycle"}
    service.restart  -> как service.start (stop, затем start)

Неизвестное имя на любой ручке с ``name``: ``{"success": False, "error": "unknown_service", "name"}``.
Сбой ``cls()``/``start()``/``stop()``: ``{"success": False, "error": "start_failed"|"stop_failed",
"message", "name", "lifecycle": "error"}``.

Ответы ПЛОСКИЕ: конверт ``{"success", "result": <плоский>}`` добавляет сторона запроса
(CommandManager/IPC), не хост.

Конкурентность:
  * ``start`` исполняется в daemon-потоке (один в полёте на сервис); обработчик ждёт его
    не дольше ``start_wait_sec`` и иначе отвечает ``pending: True`` — поток команд хаба не
    держится на медленном ``connect()`` (Modbus: 3.0 с × 3 попытки). Второй ``start`` на
    сервис с уже летящим стартом ждёт ТОТ ЖЕ старт, второго ``cls()`` нет.
  * На каждый сервис свой ``threading.Lock`` вокруг ``cls()``/``start()``/``stop()``; общий
    ``_guard`` держится только на время чтения/записи словарей хоста.
  * ``start_wait_sec=None`` — ждать до конца (синхронный режим внутрипроцессного адаптера).

Discovery ленивая: при заданном ``service_paths`` первый вызов любой ручки один раз
зовёт ``scanner.discover(*service_paths)``; сбойные файлы — в ``service.list["failed"]``.

Правило: НИКАКИХ импортов из Services/, Plugins/, multiprocess_prototype/, PySide6.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .interfaces import ServiceLifecycle
from .registry import ServiceEntry, ServiceRegistry

Handler = Callable[[dict], dict]


@dataclass
class _StartJob:
    """Старт в полёте: событие завершения + текст ошибки (``None`` — успех)."""

    done: threading.Event = field(default_factory=threading.Event)
    error: str | None = None


class ServiceHost:
    """Жизненный цикл сервисов реестра за плоскими обработчиками ``service.*``."""

    def __init__(
        self,
        registry: ServiceRegistry | None = None,
        start_wait_sec: float | None = 0.2,
        service_paths: Sequence[str | Path] | None = None,
    ) -> None:
        self._registry = registry if registry is not None else ServiceRegistry()
        self._start_wait_sec = start_wait_sec
        self._service_paths = list(service_paths) if service_paths is not None else None
        self._guard = threading.Lock()  # только словари ниже, никогда вокруг cls()/start()/stop()
        self._instances: dict[str, Any] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._jobs: dict[str, _StartJob] = {}
        self._discover_lock = threading.Lock()
        self._discovered = self._service_paths is None
        self._failed: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Публичное
    # ------------------------------------------------------------------

    def handlers(self) -> dict[str, Handler]:
        """Пять обработчиков ``service.*`` для регистрации в CommandManager."""
        return {
            "service.list": self._cmd_list,
            "service.status": self._cmd_status,
            "service.start": self._cmd_start,
            "service.stop": self._cmd_stop,
            "service.restart": self._cmd_restart,
        }

    # ------------------------------------------------------------------
    # Обработчики
    # ------------------------------------------------------------------

    def _cmd_list(self, args: dict) -> dict:
        self._ensure_discovered()
        services = [
            {
                "name": e.name,
                "display_name": e.cls.__name__,
                "lifecycle": e.lifecycle.value,
                "metadata": dict(e.meta),
            }
            for e in self._registry.list()
        ]
        return {"success": True, "services": services, "failed": dict(self._failed)}

    def _cmd_status(self, args: dict) -> dict:
        entry, name, err = self._entry(args)
        if entry is None:
            return err
        with self._guard:
            instance = self._instances.get(name)
            job = self._jobs.get(name)
        detail: dict[str, Any] = {}
        if job is not None:
            # Не трогаем get_status() экземпляра, чей start() ещё идёт в другом потоке.
            detail["pending"] = True
        elif instance is not None:
            try:
                status = instance.get_status()
                detail = dict(status) if isinstance(status, dict) else {"status": status}
            except Exception as exc:  # noqa: BLE001 — статус не должен ронять хост
                detail = {"status_error": f"{type(exc).__name__}: {exc}"}
        return {"success": True, "name": name, "lifecycle": entry.lifecycle.value, "detail": detail}

    def _cmd_start(self, args: dict) -> dict:
        entry, name, err = self._entry(args)
        if entry is None:
            return err
        with self._guard:
            job = self._jobs.get(name)
            if job is None:
                if entry.lifecycle == ServiceLifecycle.RUNNING:
                    return _ok(name, entry)
                job = _StartJob()
                self._jobs[name] = job
                threading.Thread(
                    target=self._run_start, args=(name, entry, job), name=f"service-start-{name}", daemon=True
                ).start()
        if not job.done.wait(self._start_wait_sec):
            return {**_ok(name, entry), "pending": True}
        if job.error is not None:
            return _fail("start_failed", name, job.error)
        return _ok(name, entry)

    def _cmd_stop(self, args: dict) -> dict:
        entry, name, err = self._entry(args)
        if entry is None:
            return err
        # Синхронно: при старте в полёте ждёт его конца на замке сервиса (см. ADR-SVC-002).
        with self._lock_for(name):
            if entry.lifecycle == ServiceLifecycle.STOPPED:
                return _ok(name, entry)
            with self._guard:
                instance = self._instances.get(name)
            if instance is None:
                entry.lifecycle = ServiceLifecycle.STOPPED
                return _ok(name, entry)
            try:
                ok = bool(instance.stop())
            except Exception as exc:  # noqa: BLE001 — сбой сервиса, не хоста
                entry.lifecycle = ServiceLifecycle.ERROR
                return _fail("stop_failed", name, f"Service '{name}' stop() failed: {exc}")
            entry.lifecycle = ServiceLifecycle.STOPPED if ok else ServiceLifecycle.ERROR
            if not ok:
                return _fail("stop_failed", name, f"Service '{name}' stop() returned False")
            return _ok(name, entry)

    def _cmd_restart(self, args: dict) -> dict:
        reply = self._cmd_stop(args)
        if not reply.get("success"):
            return reply
        return self._cmd_start(args)

    # ------------------------------------------------------------------
    # Внутреннее
    # ------------------------------------------------------------------

    def _run_start(self, name: str, entry: ServiceEntry, job: _StartJob) -> None:
        """Тело старта в daemon-потоке: ``cls()`` (один раз) + ``start({})`` под замком сервиса."""
        try:
            with self._lock_for(name):
                job.error = self._start_locked(name, entry)
        except BaseException as exc:  # noqa: BLE001 — поток обязан отпустить ждущих
            entry.lifecycle = ServiceLifecycle.ERROR
            job.error = f"Service '{name}' start() failed: {exc}"
        finally:
            with self._guard:
                self._jobs.pop(name, None)
            job.done.set()

    def _start_locked(self, name: str, entry: ServiceEntry) -> str | None:
        if entry.lifecycle == ServiceLifecycle.RUNNING:  # стартовал, пока ждали замок
            return None
        with self._guard:
            instance = self._instances.get(name)
        if instance is None:
            try:
                instance = entry.cls()
            except Exception as exc:  # noqa: BLE001
                entry.lifecycle = ServiceLifecycle.ERROR
                return f"Failed to instantiate service '{name}': {exc}"
            with self._guard:
                self._instances[name] = instance
        try:
            ok = bool(instance.start({}))
        except Exception as exc:  # noqa: BLE001
            entry.lifecycle = ServiceLifecycle.ERROR
            return f"Service '{name}' start() failed: {exc}"
        entry.lifecycle = ServiceLifecycle.RUNNING if ok else ServiceLifecycle.ERROR
        return None if ok else f"Service '{name}' start() returned False"

    def _lock_for(self, name: str) -> threading.Lock:
        with self._guard:
            lock = self._locks.get(name)
            if lock is None:
                lock = self._locks[name] = threading.Lock()
            return lock

    def _entry(self, args: dict) -> tuple[ServiceEntry | None, str, dict]:
        self._ensure_discovered()
        name = str((args or {}).get("name") or "")
        entry = self._registry.get(name)
        return entry, name, {"success": False, "error": "unknown_service", "name": name}

    def _ensure_discovered(self) -> None:
        """Один ``discover`` на жизнь хоста; сбой файла/всего discover — в ``failed``, не исключение."""
        if self._discovered:
            return
        with self._discover_lock:
            if self._discovered:
                return
            from .scanner import discover

            try:
                result = discover(*[Path(p) for p in self._service_paths or []])
                self._failed = dict(result.failed)
            except Exception as exc:  # noqa: BLE001 — список обязан ответить
                self._failed = {"<discover>": f"{type(exc).__name__}: {exc}"}
            self._discovered = True


def _ok(name: str, entry: ServiceEntry) -> dict:
    return {"success": True, "name": name, "lifecycle": entry.lifecycle.value}


def _fail(error: str, name: str, message: str) -> dict:
    return {
        "success": False,
        "error": error,
        "message": message,
        "name": name,
        "lifecycle": ServiceLifecycle.ERROR.value,
    }


__all__ = ["ServiceHost"]
