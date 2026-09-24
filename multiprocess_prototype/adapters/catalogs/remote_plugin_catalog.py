# -*- coding: utf-8 -*-
"""adapters/catalogs/remote_plugin_catalog.py — PluginCatalog из хаб-команды catalog.plugins.

Task 1b.2a: замена ``PluginCatalogFromRegistry`` (``plugin_catalog.py``) для GUI-процесса —
никакого импорта ``PluginRegistry`` или plugin-классов (``Plugins/``/``Services/``). Снимок
каталога приходит по IPC ОДИН раз при construction через ``catalog.plugins`` на хабе
(``ProcessManager``, см. ``process_module/commands/builtin_commands.py::_cmd_catalog_plugins``).

Envelope-ловушка (docs/reviews/2026-09-24_gui-1b.1-green.md, п.2): payload лежит под
``reply["result"]``, распаковывается здесь же — вызывающая сторона (``request``) отдаёт
конверт как есть.

Границы импортов: как у ``plugin_catalog.py`` — только ``domain.protocols``, никакого
Qt/GUI, никакого ``multiprocess_framework.modules.process_module.plugins.registry``.
"""

from __future__ import annotations

from typing import Any, Callable

from multiprocess_prototype.domain.protocols.plugin_catalog import (
    PluginCatalog,
    PluginSpec,
    PortSpec,
)

#: Сигнатура запроса к хабу: (command, args) -> reply-конверт {"success", "result"|"reason"}.
RequestFn = Callable[[str, dict], dict]


def _wire_ports(entries: list[dict[str, Any]] | None, direction: str) -> list[PortSpec]:
    """Конвертировать список port-dict-ов ``catalog.plugins`` в ``PortSpec``."""
    return [
        PortSpec(
            name=p["name"],
            dtype=p["dtype"],
            direction=direction,
            optional=bool(p.get("optional", False)),
            shape=p.get("shape", ""),
        )
        for p in entries or []
    ]


def _wire_to_spec(entry: dict[str, Any]) -> PluginSpec:
    """Конвертировать одну запись ``catalog.plugins``-payload в ``PluginSpec``.

    ``config_schema["fields"]`` несёт список FieldInfo-словарей плагина как есть
    (``FieldInfo.to_dict()`` со стороны хаба) — GUI-сторона восстанавливает их через
    ``FieldInfo.from_dict()`` (``RegistersManager.from_catalog``), а не здесь.
    """
    ports = tuple(_wire_ports(entry.get("inputs"), "input") + _wire_ports(entry.get("outputs"), "output"))
    register = entry.get("register") or {}
    fields = register.get("fields") or []

    return PluginSpec(
        name=entry["name"],
        category=entry.get("category", ""),
        description=entry.get("description", ""),
        config_schema={"fields": fields},
        ports=ports,
        has_registers=bool(fields),
        class_path=entry.get("class_path", ""),
    )


class RemotePluginCatalog:
    """Adapter: ``catalog.plugins`` (хаб) -> ``PluginCatalog`` Protocol, БЕЗ plugin-кода.

    Снимок берётся РОВНО один раз, при construction. ``list_plugins``/``resolve``/
    ``categories`` читают только этот снимок — ни одного повторного запроса к хабу.
    Сбой на construction (error reply ИЛИ исключение самого ``request``, например
    таймаут) — громкий ``RuntimeError``: тихий пустой каталог хуже падения, потому что
    выглядел бы как «у процесса нет плагинов», а не «хаб недоступен».
    """

    def __init__(self, request: RequestFn) -> None:
        try:
            reply = request("catalog.plugins", {})
        except Exception as exc:  # noqa: BLE001 — construction обязан быть громким
            raise RuntimeError(f"catalog.plugins: request failed: {exc}") from exc

        if not isinstance(reply, dict) or not reply.get("success"):
            raise RuntimeError(f"catalog.plugins: error reply: {reply!r}")

        payload = reply.get("result")
        if not isinstance(payload, dict) or not payload.get("success"):
            raise RuntimeError(f"catalog.plugins: payload error: {payload!r}")

        specs = tuple(_wire_to_spec(e) for e in payload.get("plugins") or [])
        self._specs: tuple[PluginSpec, ...] = specs
        self._by_name: dict[str, PluginSpec] = {s.name: s for s in specs}
        self.rev: str | None = payload.get("rev")

    def list_plugins(self) -> tuple[PluginSpec, ...]:
        """Вернуть все плагины из снимка."""
        return self._specs

    def resolve(self, plugin_name: str) -> PluginSpec | None:
        """Найти плагин по имени в снимке. ``None`` если не найден."""
        return self._by_name.get(plugin_name)

    def categories(self) -> tuple[str, ...]:
        """Уникальные категории плагинов снимка, отсортированные."""
        return tuple(sorted({s.category for s in self._specs}))


# Проверка structural subtyping (import-time, не runtime-checkable)
_: PluginCatalog = RemotePluginCatalog.__new__(RemotePluginCatalog)  # type: ignore[assignment]

__all__ = ["RemotePluginCatalog", "RequestFn"]
