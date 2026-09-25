# -*- coding: utf-8 -*-
"""adapters/catalogs/remote_service_manager.py — ServiceManager поверх хаб-команд ``service.*``.

Task 1b.5: GUI-сторона сервисов без импорта ``Services/`` и без своего lifecycle —
всё исполняет ``ServiceHost`` на хабе (``ProcessManager``), здесь только разбор ответов.

Envelope-ловушка (docs/reviews/2026-09-24_gui-1b.1-green.md, п.2): ``request`` отдаёт
конверт ``{"success", "result": <плоский>}``; плоский ответ хоста лежит под ``result`` —
как в ``remote_plugin_catalog.py``. Любой отказ (транспорт, конверт, плоская ошибка) —
``DomainError``, как у локального ``ServiceManagerFromRegistry``.

Ответ ``service.start`` с ``pending: True`` — не ошибка: старт идёт на хабе, итог
видно через ``get_lifecycle``.

Границы импортов: только ``domain.*`` и ``service_module.interfaces``; никакого
Qt/GUI, ``Services/``, ``ServiceRegistry``.
"""

from __future__ import annotations

from typing import Any

from multiprocess_framework.modules.service_module.interfaces import ServiceLifecycle
from multiprocess_prototype.adapters.catalogs.remote_plugin_catalog import RequestFn
from multiprocess_prototype.domain.errors import DomainError
from multiprocess_prototype.domain.protocols.service_catalog import (
    ServiceManager,
    ServiceSpec,
)


class RemoteServiceManager:
    """Adapter: хаб-команды ``service.*`` -> ``ServiceManager`` Protocol."""

    def __init__(self, request: RequestFn) -> None:
        self._request = request

    def _call(self, command: str, args: dict) -> dict[str, Any]:
        """Запрос -> плоский payload; любой отказ -> ``DomainError``."""
        try:
            reply = self._request(command, args)
        except Exception as exc:  # noqa: BLE001 — транспорт в доменную ошибку
            raise DomainError(f"{command}: request failed: {exc}") from exc
        if not isinstance(reply, dict) or not reply.get("success"):
            raise DomainError(f"{command}: error reply: {reply!r}")
        payload = reply.get("result")
        if not isinstance(payload, dict):
            raise DomainError(f"{command}: bad payload: {payload!r}")
        if not payload.get("success"):
            if payload.get("error") == "unknown_service":
                raise DomainError(f"Unknown service: {payload.get('name')}")
            raise DomainError(payload.get("message") or f"{command}: {payload.get('error')}")
        return payload

    def list_services(self) -> tuple[ServiceSpec, ...]:
        payload = self._call("service.list", {})
        return tuple(
            ServiceSpec(
                service_id=s["name"],
                display_name=s.get("display_name", s["name"]),
                metadata=dict(s.get("metadata") or {}),
            )
            for s in payload.get("services") or []
        )

    def resolve(self, service_id: str) -> ServiceSpec | None:
        return next((s for s in self.list_services() if s.service_id == service_id), None)

    def get_lifecycle(self, service_id: str) -> ServiceLifecycle:
        return ServiceLifecycle(self._call("service.status", {"name": service_id})["lifecycle"])

    def start(self, service_id: str) -> None:
        self._call("service.start", {"name": service_id})

    def stop(self, service_id: str) -> None:
        self._call("service.stop", {"name": service_id})

    def restart(self, service_id: str) -> None:
        self._call("service.restart", {"name": service_id})


# Проверка structural subtyping (import-time)
_: ServiceManager = RemoteServiceManager.__new__(RemoteServiceManager)  # type: ignore[assignment]

__all__ = ["RemoteServiceManager"]
