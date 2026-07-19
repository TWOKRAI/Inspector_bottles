# -*- coding: utf-8 -*-
"""Тесты B.4: capabilities(format="concise"|"help") + process-фильтр.

Acceptance плана: concise кратно меньше detailed; help содержит пример вызова
и подписочную подсказку. Рендер — чистая функция над Capabilities (fake-свод,
без IPC и без сокета).
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any, Dict

from backend_ctl.capability_render import render_concise, render_help
from backend_ctl.driver import BackendDriver
from backend_ctl.mcp_tools import call_tool
from backend_ctl.protocol import Capabilities, ProcessCapabilities


def _fake_caps() -> Capabilities:
    commands = [
        {
            "name": "register_update",
            "description": "Записать значение поля регистра",
            "tags": ["system"],
            "params_schema": [
                {"name": "register", "type": "str", "required": True},
                {"name": "field", "type": "str", "required": True},
                {"name": "value", "type": "Dict", "required": False},
            ],
        },
        {"name": "log.tail.subscribe", "description": "Подписка на логи", "tags": ["system"]},
        {"name": "introspect.status", "description": "Статус процесса", "tags": ["system"]},
    ]
    card = ProcessCapabilities(
        ok=True,
        process="cam",
        commands=commands,
        router_handlers=["heartbeat"],
        registers={"camera": ["fps", "exposure"]},
        raw={"success": True, "огромный": "сырой ответ " * 50},
    )
    return Capabilities(ok=True, processes={"cam": card}, topology={"cam": {"class": "X"}}, channels=[])


class TestConcise:
    def test_concise_is_multiple_times_smaller_than_detailed(self) -> None:
        caps = _fake_caps()
        detailed = json.dumps(dataclasses.asdict(caps), ensure_ascii=False)
        concise = json.dumps(render_concise(caps), ensure_ascii=False)
        assert len(concise) * 3 < len(detailed)  # «кратно меньше» — минимум втрое

    def test_concise_carries_names_only(self) -> None:
        res = render_concise(_fake_caps())
        card = res["processes"]["cam"]
        assert "introspect.status" in card["commands"]
        assert card["registers"] == {"camera": ["fps", "exposure"]}
        text = json.dumps(res, ensure_ascii=False)
        assert "params_schema" not in text and "сырой ответ" not in text


class TestHelp:
    def test_help_contains_generated_example_call(self) -> None:
        res = render_help(_fake_caps())
        by_name: Dict[str, Any] = {c["name"]: c for c in res["processes"]["cam"]["commands"]}
        example = by_name["register_update"]["example"]
        assert example["tool"] == "send_command"
        assert example["arguments"]["target"] == "cam"
        assert example["arguments"]["command"] == "register_update"
        # Обязательные поля — placeholder по типу; опциональные в пример не входят.
        assert example["arguments"]["args"] == {"register": "<str>", "field": "<str>"}

    def test_help_contains_subscription_hint(self) -> None:
        res = render_help(_fake_caps())
        by_name = {c["name"]: c for c in res["processes"]["cam"]["commands"]}
        sub = by_name["log.tail.subscribe"]["subscription"]
        assert sub["push_command"] == "log.record"
        assert sub["plane"] == "logs"
        assert "events_page" in sub["read_with"]
        assert "subscription" not in by_name["introspect.status"]  # не-подписка без подсказки

    def test_help_carries_correlation_keys(self) -> None:
        res = render_help(_fake_caps())
        assert res["correlation_keys"] == ["process", "worker", "ts"]


class TestProcessFilterAndMcp:
    def test_unknown_process_teaches(self) -> None:
        res = render_concise(_fake_caps(), "нет")
        assert res["success"] is False
        assert res["known_processes"] == ["cam"]

    def test_mcp_tool_formats(self, monkeypatch) -> None:
        d = BackendDriver()
        monkeypatch.setattr(d, "capabilities", lambda **kw: _fake_caps())
        concise = call_tool(d, "capabilities", {"format": "concise"})
        assert concise["format"] == "concise"
        help_res = call_tool(d, "capabilities", {"format": "help", "process": "cam"})
        assert list(help_res["processes"]) == ["cam"]
        bad = call_tool(d, "capabilities", {"format": "xml"})
        assert bad["success"] is False and "format" in bad["error"]

    def test_mcp_detailed_process_filter(self, monkeypatch) -> None:
        d = BackendDriver()
        monkeypatch.setattr(d, "capabilities", lambda **kw: _fake_caps())
        res = call_tool(d, "capabilities", {"process": "cam"})
        assert list(res["processes"]) == ["cam"]  # detailed отфильтрован и JSON-сериализуем
        assert res["success"] is True  # у всех форматов единый ключ успеха (ревью фазы B)
        missing = call_tool(d, "capabilities", {"process": "нет"})
        assert missing["success"] is False

    def test_malformed_cards_degrade_gracefully(self) -> None:
        """Битая карточка (bare-строка команды, None вместо полей) не роняет рендер."""
        card = ProcessCapabilities(
            ok=False,
            process="cam",
            commands=["голая-строка", {"name": "ok.cmd", "description": "", "tags": []}],
            router_handlers=[],
            registers={"camera": None},
        )
        caps = Capabilities(ok=False, processes={"cam": card}, topology={}, channels=[])
        concise = render_concise(caps)
        assert concise["processes"]["cam"]["commands"] == ["ok.cmd"]
        assert concise["processes"]["cam"]["registers"] == {"camera": []}
        help_res = render_help(caps)
        assert [c["name"] for c in help_res["processes"]["cam"]["commands"]] == ["ok.cmd"]
