# -*- coding: utf-8 -*-
"""Вспомогательные фабрики для services-тестов (Task E.4, F.9).

make_services_services() строит AppServices с реальным ServiceManagerFromRegistry
поверх stub-реестра — это тестирует настоящий Protocol-путь (presenter делегирует
lifecycle в адаптер), а не мок ServiceManager.

_StubServiceEntry / _StubServiceRegistry — duck-typed заглушки ServiceEntry/Registry
(адаптер использует .list()/.get(), а _entry_to_spec — .name/.cls.__name__/.meta).
"""

from __future__ import annotations

from typing import Any

from multiprocess_framework.modules.service_module import ServiceLifecycle
from multiprocess_prototype.adapters import ServiceManagerFromRegistry
from multiprocess_prototype.domain.app_services import AppServices
from multiprocess_prototype.domain.tests._fakes import FakeAuthFacade, FakeConfigStore
from multiprocess_prototype.domain.tests.conftest import make_test_app_services


class _FakeService:
    """Сервис для unit-тестов lifecycle (не реальный IService)."""

    name: str = "fake_service"

    def __init__(self) -> None:
        self.started_with: list[dict] = []
        self.stop_called: int = 0
        self._start_result = True
        self._stop_result = True

    def start(self, config: dict) -> bool:
        self.started_with.append(config)
        return self._start_result

    def stop(self) -> bool:
        self.stop_called += 1
        return self._stop_result

    def get_status(self) -> dict:
        return {"name": self.name}


class _DefaultServiceCls:
    """Дефолтный cls для stub-entry (нужен _entry_to_spec: cls.__name__)."""

    def start(self, config: dict) -> bool:
        return True

    def stop(self) -> bool:
        return True


class _StubServiceEntry:
    """Duck-typed ServiceEntry: .name / .lifecycle / .meta / .cls."""

    def __init__(self, name: str, title: str | None = None, cls: type | None = None) -> None:
        self.name = name
        self.lifecycle = ServiceLifecycle.READY
        self.meta: dict[str, Any] = {"title": title} if title else {}
        self.cls = cls if cls is not None else _DefaultServiceCls


class _StubServiceRegistry:
    """Duck-typed ServiceRegistry: .list() / .get(name)."""

    def __init__(self, entries: list[_StubServiceEntry]) -> None:
        self._entries = entries

    def list(self) -> list[_StubServiceEntry]:
        return list(self._entries)

    def get(self, name: str) -> _StubServiceEntry | None:
        return next((e for e in self._entries if e.name == name), None)


def make_services_services(
    *,
    entries: list[_StubServiceEntry] | None = None,
    config: FakeConfigStore | None = None,
    auth: FakeAuthFacade | None = None,
) -> AppServices:
    """Создать AppServices для services-тестов.

    services.services — реальный ServiceManagerFromRegistry над stub-реестром.

    Args:
        entries: список stub-сервисов. По умолчанию — пустой реестр.
        config: FakeConfigStore (по умолчанию пустой — get_service_paths → ["Services"]).
        auth: FakeAuthFacade (по умолчанию all_permissions=True).
    """
    registry = _StubServiceRegistry(entries or [])
    manager = ServiceManagerFromRegistry(registry)  # type: ignore[arg-type]  # duck-typed
    return make_test_app_services(
        services=manager,
        config=config if config is not None else FakeConfigStore(),
        auth=auth if auth is not None else FakeAuthFacade(all_permissions=True),
    )


__all__ = [
    "_FakeService",
    "_StubServiceEntry",
    "_StubServiceRegistry",
    "make_services_services",
]
