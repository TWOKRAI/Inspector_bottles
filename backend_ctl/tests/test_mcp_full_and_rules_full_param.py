# -*- coding: utf-8 -*-
"""Task 0.4 (plans/observability-closure/phase-0-trust-gate.md), критерий 1 — М2.

Независимый приёмочный тест, написан ДО реализации (RED, тестер вслепую от
acceptance criteria, без чтения будущего diff'а). Источник контракта — не
implementation-детали, а сам механизм: :func:`backend_ctl.dispatch._cap_heavy`
усекает ЛЮБОЙ ответ инструмента (см. его докстринг и ``_UNCAPPED_TOOLS`` в
:mod:`backend_ctl.mcp_tools`), кроме поимённого исключения. Значит агент обязан
иметь возможность попросить ``full=true`` у КАЖДОГО инструмента, которого касается
усечение, — а JSON Schema сегодня объявляет ``full`` только у трёх инструментов
(``system_overview``, ``state_get_subtree``, ``telemetry_history``) из полного
реестра. Подсказка про усечение (``_hint``, "full=true — полный объём") печатается
всем поровну, но параметра для этого физически нет в схеме почти у всех.
"""

from __future__ import annotations

import jsonschema

from backend_ctl.mcp_tools import TOOLS, _UNCAPPED_TOOLS


def _cappable_tools():
    """Инструменты, которых касается байтовый потолок (см. ``dispatch._cap_heavy``).

    Исключение — тот же именованный набор, которым живёт сам механизм усечения:
    заводить второй список исключений специально для схемы означало бы, что два
    списка могут разойтись между собой независимо от того, что делает код.
    """
    return [t for t in TOOLS if t.name not in _UNCAPPED_TOOLS]


def test_every_cappable_tool_declares_full_param() -> None:
    """Критерий 1: у КАЖДОГО капающегося инструмента в схеме есть параметр ``full``.

    Провалившиеся инструменты обязаны быть названы поимённо в сообщении — не
    «N инструментов не прошли».
    """
    missing = sorted(t.name for t in _cappable_tools() if "full" not in t.input_schema.get("properties", {}))
    assert missing == [], (
        f"{len(missing)} капающихся инструментов не объявляют параметр full в схеме "
        f"(агент не может физически попросить полный ответ, хотя подсказка об усечении "
        f"печатается всем): {missing}"
    )


def test_full_param_is_boolean_type() -> None:
    """``full`` объявлен как ``boolean`` у каждого инструмента, у которого он есть."""
    wrong_type = sorted(
        t.name
        for t in _cappable_tools()
        if "full" in t.input_schema.get("properties", {})
        and t.input_schema["properties"]["full"].get("type") != "boolean"
    )
    assert wrong_type == [], f"параметр full объявлен НЕ как boolean у: {wrong_type}"


#: Placeholder-значения по JSON-типу — заполнить ЧУЖИЕ required-поля схемы, чтобы
#: провал validate() отвечал именно за ``full``, а не за то, что мы не передали
#: обязательный ``path``/``process`` инструмента. Порядок предпочтения важен для
#: полей с несколькими допустимыми типами (например ``["string", "array"]``).
_PLACEHOLDER_BY_TYPE = {
    "string": "x",
    "integer": 1,
    "number": 1.0,
    "boolean": True,
    "array": [],
    "object": {},
    "null": None,
}


def _placeholder_for(prop_schema: dict):
    # `enum` бьёт тип: у `await_condition` обязательное поле `kind` — строка ИЗ
    # СПИСКА, и заглушка "x" валила валидацию по причине, не имеющей отношения к
    # `full`. Тест обязан падать на отсутствии `full`, а не на том, что генератор
    # не умеет читать enum: иначе красное сообщение уводит разбор в сторону.
    enum = prop_schema.get("enum")
    if enum:
        return enum[0]
    types = prop_schema.get("type", "string")
    types = types if isinstance(types, list) else [types]
    return _PLACEHOLDER_BY_TYPE.get(types[0], "x")


def _minimal_valid_instance(schema: dict) -> dict:
    """Инстанс, удовлетворяющий ТОЛЬКО ``required`` схемы (без ``full``)."""
    props = schema.get("properties", {})
    return {name: _placeholder_for(props.get(name, {})) for name in schema.get("required", [])}


def test_full_true_validates_against_every_cappable_tool_schema() -> None:
    """``jsonschema.validate(<минимальный валидный вызов> | full=True, схема)`` обязан проходить.

    Критерий 1 дословно требует «jsonschema.validate({"full": True}, схема) проходит
    у всех капающихся инструментов» — но буквально ``{"full": true}`` само по себе
    ломается о ЧУЖИЕ required-поля (``telemetry_history`` требует ``path`` —
    находка при первом прогоне, не имеющая отношения к параметру ``full``). Чтобы
    проверка судила именно про ``full``, а не про то, что мы не передали ``path``,
    к ``full: true`` добавляются placeholder-значения остальных required-полей.

    Инструмент без параметра ``full`` вовсе (уже назван предыдущим тестом) сюда не
    включается — иначе сообщение задвоило бы одну и ту же причину под двумя тестами.
    """
    fails = []
    for tool in _cappable_tools():
        if "full" not in tool.input_schema.get("properties", {}):
            continue
        instance = {**_minimal_valid_instance(tool.input_schema), "full": True}
        try:
            jsonschema.validate(instance, tool.input_schema)
        except jsonschema.ValidationError as exc:
            fails.append((tool.name, exc.message))
    assert fails == [], f"full:true (+ прочие required) не проходит схему у: {fails}"


def test_uncapped_exception_list_is_explicit_named_and_consistent() -> None:
    """Список исключений из усечения — явный именованный frozenset, а не «эти как-то».

    Находка: эта часть критерия 1 уже выполнена без всякой реализации —
    ``_UNCAPPED_TOOLS`` уже существует, документирован (докстринг называет ПОЧЕМУ
    каждый из трёх исключён) и не пуст. Тест фиксирует это, чтобы регресс (кто-то
    заменит осмысленный набор на динамическое условие) был виден.
    """
    assert isinstance(_UNCAPPED_TOOLS, frozenset), "исключения обязаны быть неизменяемым именованным набором"
    assert _UNCAPPED_TOOLS == frozenset({"events", "events_page", "register_snapshot"})
    all_names = {t.name for t in TOOLS}
    unknown = _UNCAPPED_TOOLS - all_names
    assert unknown == set(), f"в исключениях есть имена, которых нет в реестре инструментов: {unknown}"
