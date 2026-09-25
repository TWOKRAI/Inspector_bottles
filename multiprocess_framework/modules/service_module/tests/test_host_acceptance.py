# -*- coding: utf-8 -*-
"""Приёмка ServiceHost (Task 1b.5, RED) — независимый тестер, без implementation.

Контракт зафиксирован в DESIGN-брифинге Task 1b.5 (plans/2026-09-22_gui-service/
phase-1b-recipe-service.md, раздел «Task 1b.5»), а не подсмотрен в коде: на момент
написания ``multiprocess_framework/modules/service_module/host.py`` не существует —
любой импорт ``ServiceHost`` падает ``ModuleNotFoundError`` (подкласс ``ImportError``).

Что пиним:
  - ``ServiceHost(registry=None)`` — DI реестра, дефолт = singleton ``ServiceRegistry``.
  - ``handlers() -> dict[str, Callable[[dict], dict]]`` с ключами ровно
    ``service.list``, ``service.status``, ``service.start``, ``service.stop``,
    ``service.restart``; каждый хендлер зовётся как ``handler({"name": "auth"})``
    и возвращает ПЛОСКИЙ dict (без конверта ``result`` — тот появляется только на
    стороне ``request``/``RemoteServiceManager``, см. ловушку 1b.1 в шапке брифинга).
  - Плоские ответы: ``service.list`` -> ``{"success", "services": [{"name",
    "display_name","lifecycle","metadata"}, ...]}``; ``service.status`` ->
    ``{"success","name","lifecycle","detail"}``; start/stop/restart ->
    ``{"success","name","lifecycle"}``; неизвестное имя ->
    ``{"success": False, "error": "unknown_service", "name": <name>}``.
  - ``lifecycle`` — строковые значения ``ServiceLifecycle`` (interfaces.py:16).
  - start/stop идемпотентны; сервис, чей ``start`` бросает исключение, переходит
    в lifecycle ``error``, а хост остаётся работоспособным (не падает целиком).
  - Параллельный ``start`` одного сервиса из нескольких потоков — класс сервиса
    инстанцируется РОВНО один раз.
  - Медленный ``start`` одного сервиса не блокирует ``service.list`` из другого
    потока.
  - Сам модуль ``host.py`` не импортирует ``Services``, ``PySide6``,
    ``multiprocess_prototype`` (граница слоёв фреймворка, CLAUDE.md п.9).

Изоляция: ``ServiceRegistry`` — process-wide singleton (registry.py:54-75), поэтому
фикстура ``_clean_registry`` (тот же паттерн, что ``test_registry.py::_clean_registry``)
очищает его перед и после каждого теста — ни один тест не видит записи соседа.

Интерпретация, которую я не смог вывести буквально из DESIGN (см. отчёт тестировщика,
раздел "что я истолковал"): плоская форма ответа ``service.start`` для сервиса, чей
``start()`` бросил исключение. DESIGN даёт литерал только для success-ответа и для
unknown_service; для внутреннего исключения пин только свойство "lifecycle -> error,
хост остаётся отвечающим" — тест ниже проверяет это свойство, не гадая про точный
текст ``error``.
"""

from __future__ import annotations

import threading
import time

import pytest

from multiprocess_framework.modules.service_module.interfaces import ServiceLifecycle
from multiprocess_framework.modules.service_module.host import ServiceHost
from multiprocess_framework.modules.service_module.registry import (
    ServiceEntry,
    ServiceRegistry,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    """Очищает singleton ServiceRegistry перед и после каждого теста.

    Тот же паттерн, что ``test_registry.py::_clean_registry`` — ServiceRegistry
    process-wide singleton, "приватность" реестра для теста достигается очисткой,
    а не отдельным экземпляром (в проекте нет второго конструктора).
    """
    ServiceRegistry().clear()
    yield
    ServiceRegistry().clear()


def _register(name: str, cls: type, *, meta: dict | None = None) -> None:
    """Зарегистрировать класс-заглушку в singleton ServiceRegistry напрямую

    (без декоратора @register_service — тест не хочет side-effect импорта модуля).
    """
    ServiceRegistry().register(ServiceEntry(name=name, cls=cls, lifecycle=ServiceLifecycle.READY, meta=meta or {}))


class _OkService:
    """Заглушка IService: start/stop всегда успешны."""

    name = "ok"

    def start(self, config: dict) -> bool:
        return True

    def stop(self) -> bool:
        return True

    def get_status(self) -> dict:
        return {"name": self.name, "status": "running"}


class _RaisingStartService:
    """Заглушка IService: start() всегда бросает исключение."""

    name = "boom"

    def start(self, config: dict) -> bool:
        raise RuntimeError("boom-start")

    def stop(self) -> bool:
        return True

    def get_status(self) -> dict:
        return {"name": self.name, "status": "unknown"}


# ------------------------------------------------------------------
# service.list
# ------------------------------------------------------------------


def test_list_names_match_registry_as_set() -> None:
    """service.list вернёт ИМЕННО зарегистрированные имена (как множество) с полной формой записи."""
    _register("ok", _OkService)
    _register("boom", _RaisingStartService)

    host = ServiceHost(registry=ServiceRegistry())
    reply = host.handlers()["service.list"]({})

    assert reply["success"] is True
    names = {entry["name"] for entry in reply["services"]}
    assert names == {"ok", "boom"}

    for entry in reply["services"]:
        assert set(entry.keys()) == {"name", "display_name", "lifecycle", "metadata"}
        # Свежезарегистрированные через ServiceEntry(lifecycle=READY) — литерал строки enum.
        assert entry["lifecycle"] == "ready"


# ------------------------------------------------------------------
# service.start / service.stop — lifecycle + идемпотентность
# ------------------------------------------------------------------


def test_start_stop_lifecycle_and_repeated_stop_succeeds() -> None:
    """start -> running, stop -> stopped, повторный stop — тот же результат, без ошибки."""
    _register("ok", _OkService)
    host = ServiceHost(registry=ServiceRegistry())
    handlers = host.handlers()

    start_reply = handlers["service.start"]({"name": "ok"})
    assert start_reply == {"success": True, "name": "ok", "lifecycle": "running"}

    stop_reply = handlers["service.stop"]({"name": "ok"})
    assert stop_reply == {"success": True, "name": "ok", "lifecycle": "stopped"}

    # Идемпотентность: повторный stop на уже STOPPED — тот же ответ, не ошибка.
    stop_again = handlers["service.stop"]({"name": "ok"})
    assert stop_again == {"success": True, "name": "ok", "lifecycle": "stopped"}


# ------------------------------------------------------------------
# unknown name — единая форма ошибки на всех мутирующих ручках
# ------------------------------------------------------------------


def test_unknown_name_returns_unknown_service() -> None:
    """Неизвестное имя сервиса -> одна и та же плоская ошибка на любой ручке."""
    host = ServiceHost(registry=ServiceRegistry())
    handlers = host.handlers()

    for command in ("service.status", "service.start", "service.stop", "service.restart"):
        reply = handlers[command]({"name": "ghost"})
        assert reply == {"success": False, "error": "unknown_service", "name": "ghost"}, command


# ------------------------------------------------------------------
# start() бросает исключение -> lifecycle error, хост остаётся живым
# ------------------------------------------------------------------


def test_start_raising_sets_error_and_host_still_answers() -> None:
    """Сервис, чей start() бросает — lifecycle становится error, хост не падает целиком."""
    _register("boom", _RaisingStartService)
    host = ServiceHost(registry=ServiceRegistry())
    handlers = host.handlers()

    # Хендлер ОБЯЗАН вернуть структурированный ответ, а не пробросить исключение —
    # иначе "хост остаётся работоспособным" неверно уже на первом вызове.
    start_reply = handlers["service.start"]({"name": "boom"})
    assert isinstance(start_reply, dict)
    assert start_reply.get("success") is False

    # Хост всё ещё отвечает на другие команды, и видит именно error для этого сервиса.
    status_reply = handlers["service.status"]({"name": "boom"})
    assert status_reply["success"] is True
    assert status_reply["lifecycle"] == "error"


# ------------------------------------------------------------------
# concurrent start одного сервиса -> инстанцирован один раз
# ------------------------------------------------------------------


def test_concurrent_start_instantiates_once() -> None:
    """N потоков зовут service.start одного имени параллельно -> __init__ вызван 1 раз."""
    instantiations: list[int] = []
    counter_lock = threading.Lock()

    class _CountingService:
        name = "counted"

        def __init__(self) -> None:
            # Небольшая задержка расширяет гонку — без неё легко случайно попасть
            # в "повезло" на быстрой машине и не поймать реальный баг сериализации.
            time.sleep(0.05)
            with counter_lock:
                instantiations.append(1)

        def start(self, config: dict) -> bool:
            return True

        def stop(self) -> bool:
            return True

        def get_status(self) -> dict:
            return {"name": self.name, "status": "running"}

    _register("counted", _CountingService)
    host = ServiceHost(registry=ServiceRegistry())
    start_handler = host.handlers()["service.start"]

    errors: list[BaseException] = []

    def _call() -> None:
        try:
            start_handler({"name": "counted"})
        except BaseException as exc:  # noqa: BLE001 — тест обязан увидеть падение, не проглотить
            errors.append(exc)

    threads = [threading.Thread(target=_call, daemon=True) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)

    assert not any(t.is_alive() for t in threads), "service.start завис — поток не завершился за 5с"
    assert not errors, f"service.start бросил исключение в потоке: {errors}"
    assert len(instantiations) == 1, f"класс сервиса инстанцирован {len(instantiations)} раз, ожидался ровно 1"


# ------------------------------------------------------------------
# медленный start не блокирует другие команды хоста
# ------------------------------------------------------------------


def test_slow_start_does_not_block_other_command() -> None:
    """service.start одного сервиса, спящий 5с, не блокирует service.list из другого потока."""

    class _SlowService:
        name = "slow"

        def start(self, config: dict) -> bool:
            time.sleep(5.0)
            return True

        def stop(self) -> bool:
            return True

        def get_status(self) -> dict:
            return {"name": self.name, "status": "running"}

    _register("slow", _SlowService)
    host = ServiceHost(registry=ServiceRegistry())
    handlers = host.handlers()

    start_thread = threading.Thread(target=lambda: handlers["service.start"]({"name": "slow"}), daemon=True)
    start_thread.start()
    time.sleep(0.1)  # дать service.start уйти в sleep(5) на фоне

    t0 = time.monotonic()
    list_reply = handlers["service.list"]({})
    elapsed = time.monotonic() - t0

    assert elapsed < 0.5, f"service.list заблокирован медленным start() на {elapsed:.3f}с"
    assert list_reply["success"] is True

    start_thread.join(timeout=6.0)
    assert not start_thread.is_alive(), "фоновый service.start не завершился за 6с — хендлер завис"


# ------------------------------------------------------------------
# import-guard: host.py не тянет Services/PySide6/multiprocess_prototype
# ------------------------------------------------------------------


def test_host_module_imports_no_services_pyside_prototype() -> None:
    """AST-проверка импортов host.py — не substring-грep (тот ловит имя в докстринге)."""
    import ast
    import importlib
    from pathlib import Path

    module = importlib.import_module("multiprocess_framework.modules.service_module.host")
    source = Path(module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    forbidden_prefixes = ("Services", "PySide6", "multiprocess_prototype")
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(forbidden_prefixes):
                    violations.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith(forbidden_prefixes):
                violations.append(node.module)

    assert violations == [], f"host.py импортирует запрещённые модули: {violations}"
