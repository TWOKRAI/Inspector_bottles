# -*- coding: utf-8 -*-
"""Task 0.4, критерий 2 — М3: MCP-зеркало команды ``introspect.observability``.

Независимый приёмочный тест (RED, ДО реализации). Контракт взят дословно из
acceptance criteria плана, а НЕ из чтения будущей реализации:

    Существует MCP-инструмент ``introspect_observability(process, section=None,
    full=False)``, зеркалящий соответствующую команду драйвера; ``section``
    сужает выдачу до одной из ``effective / counters / provenance / history /
    observation / audit / layers``; неизвестная секция — внятная ошибка, а не
    молчание.

Сегодня такого инструмента в реестре нет вовсе (driver-обёртка
``BackendDriver.observability_counters`` существует, но отдаёт только секцию
``counters`` — не полный зеркальный ответ, и в MCP её нет тоже).

Тесты вызывают хендлер из реестра напрямую с ФЕЙКОВЫМ driver'ом (единственная
обязанность хендлера — переслать вызов в ``send_command`` и, при необходимости,
сузить ответ до одной секции) — живого бэкенда у тестера на стадии RED нет и не
предполагается.
"""

from __future__ import annotations

import copy

from backend_ctl.mcp_tools import TOOLS, build_registry

#: Семь секций, названных дословно в acceptance criteria (порядок не важен).
NAMED_SECTIONS = ("effective", "counters", "provenance", "history", "observation", "audit", "layers")


class _FakeDriver:
    """Фиксирует вызовы ``send_command`` и отвечает заранее заданным словарём."""

    def __init__(self, response: dict) -> None:
        self.calls: list[tuple] = []
        self._response = response

    def send_command(self, target, command, args=None, *, timeout=None):
        self.calls.append((target, command, args, timeout))
        return copy.deepcopy(self._response)


def _full_driver_response(process: str = "gui") -> dict:
    """Полный ответ ``introspect.observability`` — по одной различимой метке на секцию."""
    response = {"success": True, "process": process}
    for name in NAMED_SECTIONS:
        response[name] = {"marker": f"{name}-data"}
    return response


def _spec():
    return build_registry()["introspect_observability"]


def test_tool_is_registered_in_mcp_registry() -> None:
    """М3: инструмент обязан существовать — это и есть суть находки М3."""
    names = {t.name for t in TOOLS}
    assert "introspect_observability" in names, (
        "introspect_observability отсутствует в реестре MCP-инструментов backend_ctl/mcp_tools.py: "
        "команда introspect.observability читается ТОЛЬКО драйвером, MCP-зеркала нет"
    )


def test_schema_requires_process() -> None:
    spec = _spec()
    assert spec.input_schema.get("required") == ["process"]


def test_schema_section_is_optional_enum_of_named_sections() -> None:
    spec = _spec()
    section_prop = spec.input_schema["properties"]["section"]
    assert sorted(section_prop.get("enum", [])) == sorted(NAMED_SECTIONS)
    assert "section" not in spec.input_schema.get("required", [])


def test_schema_declares_boolean_full_param() -> None:
    spec = _spec()
    assert spec.input_schema["properties"]["full"]["type"] == "boolean"


def test_handler_forwards_process_to_introspect_observability_command() -> None:
    """Хендлер обязан переслать вызов ТОЙ ЖЕ командой, что читает драйвер напрямую."""
    drv = _FakeDriver(_full_driver_response("gui"))
    _spec().handler(drv, {"process": "gui"})
    assert len(drv.calls) == 1, f"ожидался ровно один send_command, получено {len(drv.calls)}"
    target, command, _args, _timeout = drv.calls[0]
    assert target == "gui"
    assert command == "introspect.observability"


def test_no_section_mirrors_the_full_driver_response() -> None:
    """Без ``section`` — полное зеркало ответа драйвера, как в остальных introspect_*."""
    drv = _FakeDriver(_full_driver_response("gui"))
    result = _spec().handler(drv, {"process": "gui"})
    for name in NAMED_SECTIONS:
        assert result.get(name) == {"marker": f"{name}-data"}, f"секция {name!r} потерялась без фильтра"


def test_section_counters_returns_only_that_section_content() -> None:
    drv = _FakeDriver(_full_driver_response("gui"))
    result = _spec().handler(drv, {"process": "gui", "section": "counters"})
    assert result["counters"] == {"marker": "counters-data"}


def test_section_counters_drops_sibling_sections() -> None:
    """Сужение обязано быть настоящим — соседние секции не должны доехать вместе."""
    drv = _FakeDriver(_full_driver_response("gui"))
    result = _spec().handler(drv, {"process": "gui", "section": "counters"})
    leaked = [name for name in NAMED_SECTIONS if name != "counters" and name in result]
    assert leaked == [], f"section=counters принёс соседние секции: {leaked}"


def test_unknown_section_is_a_clear_error_not_silence() -> None:
    """Критерий 2 дословно: «неизвестная секция — внятная ошибка, а не молчание»."""
    drv = _FakeDriver(_full_driver_response("gui"))
    result = _spec().handler(drv, {"process": "gui", "section": "bogus_section_typo"})
    assert result.get("success") is False, "неизвестная секция обязана явно провалить вызов, а не отдать что попало"
    assert "bogus_section_typo" in str(result.get("error", "")), "ошибка обязана называть непонятую секцию по имени"
