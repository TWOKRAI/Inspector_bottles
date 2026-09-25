# -*- coding: utf-8 -*-
"""RED-приёмка Task 1b.5: RemoteServiceManager — GUI-сторона service.* без Services/PySide6.

Независимый тестер (без implementation) — контракт из DESIGN-брифинга Task 1b.5
(plans/2026-09-22_gui-service/phase-1b-recipe-service.md). На момент написания ни
``multiprocess_framework/modules/service_module/host.py``, ни
``multiprocess_prototype/adapters/catalogs/remote_service_manager.py`` не существуют —
импорт любого падает ``ModuleNotFoundError`` (подкласс ``ImportError``).

Ловушка 1b.1 (docs/reviews/2026-09-24_gui-1b.1-green.md, п.2), унаследованная сюда явно:
``ServiceHost.handlers()[...]`` возвращает ПЛОСКИЙ dict, а конверт ``{"success", "result":
<плоский>}`` существует только на стороне ``request``/``RemoteServiceManager`` — как у
``remote_plugin_catalog.py:67-106``. Фейковый ``request`` ниже собран РОВНО так: заворачивает
плоский ответ настоящего ``ServiceHost`` в конверт, а не выдумывает свою форму (правило
CLAUDE.md "фейк-харнесс доказывает харнесс" — здесь фейк это делает через настоящий объект,
не заглушку).

ОДНА ДОГАДКА (как у теста 1b.2a): ``display_name`` в ``service.list`` — классовое имя
(``entry.cls.__name__``), по аналогии с уже существующим локальным адаптером
(``adapters/catalogs/service_catalog.py::_entry_to_spec``, строка 59). DESIGN не пинит это
явно для ``ServiceHost`` (только форму ключей). Если разработчик выберет ``entry.name`` —
это находка, а не мой сломанный тест.
"""

from __future__ import annotations

import pytest

from multiprocess_framework.modules.service_module.host import ServiceHost
from multiprocess_framework.modules.service_module.interfaces import ServiceLifecycle
from multiprocess_framework.modules.service_module.registry import (
    ServiceEntry,
    ServiceRegistry,
)
from multiprocess_prototype.adapters.catalogs.remote_service_manager import (
    RemoteServiceManager,
)
from multiprocess_prototype.domain.errors import DomainError
from multiprocess_prototype.domain.protocols.service_catalog import ServiceSpec


@pytest.fixture(autouse=True)
def _clean_registry():
    """ServiceRegistry — process-wide singleton (см. test_host_acceptance.py): чистим вокруг теста."""
    ServiceRegistry().clear()
    yield
    ServiceRegistry().clear()


class _OkService:
    """Заглушка IService: start/stop всегда успешны."""

    name = "auth"

    def start(self, config: dict) -> bool:
        return True

    def stop(self) -> bool:
        return True

    def get_status(self) -> dict:
        return {"name": self.name, "status": "running"}


def _make_request(host: ServiceHost):
    """request(command, args) над РЕАЛЬНЫМ ServiceHost, конверт как на IPC-границе.

    Тот же паттерн, что recipe.*/catalog.plugins: payload плоского хендлера лежит под
    ``reply["result"]`` (DESIGN п.3 — "как remote_plugin_catalog.py:67-106 парсит").
    """
    handlers = host.handlers()

    def request(command: str, args: dict) -> dict:
        return {"success": True, "result": handlers[command](args)}

    return request


def test_protocol_contract_like_fake() -> None:
    """RemoteServiceManager ведёт себя как FakeServiceManager: lifecycle + идемпотентность,

    но поверх НАСТОЯЩЕГО ServiceHost (не выдуманного request) — закрывает дыру "фейк
    доказывает только фейк" (CLAUDE.md, правило про fake-harness).
    """
    ServiceRegistry().register(
        ServiceEntry(
            name="auth",
            cls=_OkService,
            lifecycle=ServiceLifecycle.READY,
            meta={"vendor": "x"},
        )
    )
    host = ServiceHost(registry=ServiceRegistry())
    manager = RemoteServiceManager(_make_request(host))

    specs = manager.list_services()
    assert specs == (ServiceSpec(service_id="auth", display_name="_OkService", metadata={"vendor": "x"}),)

    assert manager.resolve("ghost") is None
    resolved = manager.resolve("auth")
    assert resolved is not None
    assert resolved.service_id == "auth"

    assert manager.get_lifecycle("auth") == ServiceLifecycle.READY

    manager.start("auth")
    assert manager.get_lifecycle("auth") == ServiceLifecycle.RUNNING
    manager.start("auth")  # idempotent no-op — не должен бросить
    assert manager.get_lifecycle("auth") == ServiceLifecycle.RUNNING

    manager.stop("auth")
    assert manager.get_lifecycle("auth") == ServiceLifecycle.STOPPED
    manager.stop("auth")  # idempotent no-op
    assert manager.get_lifecycle("auth") == ServiceLifecycle.STOPPED

    manager.restart("auth")
    assert manager.get_lifecycle("auth") == ServiceLifecycle.RUNNING


def test_error_envelope_raises_domain_error() -> None:
    """Плоская ошибка unknown_service от настоящего ServiceHost -> DomainError,

    как у локального адаптера (adapters/catalogs/service_catalog.py: "Unknown service: ...").
    """
    host = ServiceHost(registry=ServiceRegistry())
    manager = RemoteServiceManager(_make_request(host))

    with pytest.raises(DomainError):
        manager.start("ghost")

    with pytest.raises(DomainError):
        manager.get_lifecycle("ghost")
