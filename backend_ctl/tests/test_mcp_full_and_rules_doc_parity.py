# -*- coding: utf-8 -*-
"""Task 0.4, критерий 5 — страж паритета документа для НОВОГО инструмента задачи.

Acceptance criteria дословно: «добавление инструмента без строки в
``CONTROL_PANEL.md`` краснеет». Область этого теста — единственный НОВЫЙ
инструмент, который вводит сама Task 0.4 (``introspect_observability``, критерий
2 / М3), а не ретроактивный аудит всех инструментов реестра.

**Почему область сужена — честно, не молчанием.** ``CONTROL_PANEL.md`` документирует
МЕХАНИЗМ (четыре слоя конфигурации, вердикт, TTL) вокруг команды
``introspect.observability`` — он не претендует на роль общего индекса backend_ctl
MCP-инструментов. Проверка боем (см. отчёт тестера) показывает: из 50 инструментов
реестра 34 не упомянуты в этом файле вовсе — это не дефект Task 0.4, а факт про
формат документа. Тест, требующий там имени всех 50 инструментов, был бы неверным
контрактом, а не приёмочным критерием этой задачи.
"""

from __future__ import annotations

from pathlib import Path

_CONTROL_PANEL = (
    Path(__file__).resolve().parents[2] / "multiprocess_framework" / "docs" / "observability" / "CONTROL_PANEL.md"
)


def test_new_introspect_observability_tool_is_documented_in_control_panel() -> None:
    assert _CONTROL_PANEL.is_file(), f"справочник не найден по ожидаемому пути: {_CONTROL_PANEL}"
    text = _CONTROL_PANEL.read_text(encoding="utf-8")
    assert "introspect_observability" in text, (
        "CONTROL_PANEL.md не упоминает introspect_observability — новый MCP-инструмент "
        "(критерий 2 / М3) не задокументирован в справочнике, который владеет секциями "
        "effective/counters/provenance/history/observation/audit/layers"
    )
