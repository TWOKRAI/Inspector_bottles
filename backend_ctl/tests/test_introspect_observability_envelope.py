# -*- coding: utf-8 -*-
"""`introspect_observability` разворачивает IPC-конверт, а не отдаёт его агенту.

**Почему отдельный файл, а не строка в приёмке.** Приёмочные тесты Task 0.4
(`test_mcp_full_and_rules_introspect_observability.py`) написаны против фейкового
драйвера, чей `send_command` возвращает **плоский** dict с секциями на верхнем
уровне. Против такого фейка сужение по `section` работает при любой реализации —
и с разворотом конверта, и без него. Форма фейка сама по себе была утверждением о
реальности, и утверждение оказалось неверным.

**Живой стенд 2026-08-29 (Ф0.5).** `introspect_observability(seg,
section="observation")` вернул
``{"success": true, "section": "observation", "sections_present": ["_fence",
"_receive_info", "_source_channel", "command", "queue_type", "request_id",
"result", "sender", "targets", "type"]}`` — то есть фильтр искал секцию среди
ключей ТРАНСПОРТА и честно доложил, что её там нет. Полезная нагрузка (13 ключей)
лежала под `result`. Ни одна секция не была достижима НИКОГДА, а ответ без
`section` вдобавок пробивал байтовый потолок конвертом: 18165 Б против 12000.

Класс — «тест на фейке доказывает фейк»: соседние инструменты разницы не видят,
потому что ходят через методы драйвера, которые конверт разворачивают сами.
"""

from __future__ import annotations

from typing import Any, Dict

from backend_ctl.mcp_tools import TOOLS

_HANDLER = next(t.handler for t in TOOLS if t.name == "introspect_observability")

#: Полезная нагрузка команды — то, что агент обязан увидеть.
_PAYLOAD: Dict[str, Any] = {
    "success": True,
    "process": "seg",
    "observation": {"rules": ["state.plugins.*.fps"], "rules_pending": []},
    "counters": {"buffer_dropped": 0},
}

#: Ровно та обёртка, которую отдаёт живой `send_command` (снята со стенда).
_ENVELOPE: Dict[str, Any] = {
    "type": "response",
    "command": "command.response",
    "sender": "seg",
    "targets": ["ProcessManager"],
    "queue_type": "system",
    "request_id": "bf8cd0e1-b376-4f11-86e0-2a3f99b17e49",
    "success": True,
    "result": _PAYLOAD,
    "_fence": {"sender": "seg", "inc": 0, "epoch": 0},
    "_source_channel": "ProcessManager_system",
    "_receive_info": {"router_id": "router_ProcessManager", "receive_time": 1788014442.7763774},
}


class _EnvelopeDriver:
    """Драйвер, отвечающий КОНВЕРТОМ, — как настоящий, а не как плоский фейк."""

    def send_command(self, process: str, command: str, **_kw: Any) -> Dict[str, Any]:
        assert command == "introspect.observability"
        return dict(_ENVELOPE)


def test_section_filter_sees_through_the_envelope() -> None:
    """Сужение находит секцию под `result`, а не рапортует «её нет»."""
    out = _HANDLER(_EnvelopeDriver(), {"process": "seg", "section": "observation"})
    assert "observation" in out, (
        f"фильтр не нашёл секцию под конвертом и, судя по ответу, искал её среди транспортных ключей: {out!r}"
    )
    assert out["observation"] == _PAYLOAD["observation"]


def test_transport_keys_never_reach_the_agent() -> None:
    """Конверт не доезжает: он и шум, и лишние байты под потолком усечения."""
    out = _HANDLER(_EnvelopeDriver(), {"process": "seg"})
    for noise in ("_fence", "_receive_info", "_source_channel", "queue_type", "targets"):
        assert noise not in out, f"транспортный ключ {noise!r} доехал до агента: {sorted(out)!r}"


def test_sections_present_lists_payload_sections_not_transport_keys() -> None:
    """Когда секции РЕАЛЬНО нет, подсказка называет соседей по нагрузке.

    Ложноположительная сторона пары: сообщение «её нет, вот что есть» обязано быть
    правдой о нагрузке. Со списком транспортных ключей оно посылало читателя
    искать несуществующего виновника.
    """
    out = _HANDLER(_EnvelopeDriver(), {"process": "seg", "section": "layers"})
    assert "layers" not in out
    assert out["sections_present"] == ["counters", "observation"], out["sections_present"]
