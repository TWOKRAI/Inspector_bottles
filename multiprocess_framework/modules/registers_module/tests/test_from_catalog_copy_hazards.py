# -*- coding: utf-8 -*-
"""Hazard-тесты автора (Task 1b.2b-pre) — что может сломаться ИМЕННО в этом механизме.

``RegistersManager.from_catalog`` строит СИНТЕТИЧЕСКУЮ копию регистра через
``pydantic.create_model(__base__=SchemaBase)`` над ``FieldInfo``, собранными из
каталог-payload (``FieldInfo.to_dict()``/``from_dict()``). Три вещи, которые может
уникально сломать ИМЕННО этот механизм (в отличие от ``from_registry``, который
строит настоящий класс плагина):

1. Одна запись каталога с полем, недопустимым для ``create_model`` (пример,
   измеренный эмпирически: ИМЕННО ``model_dump``/``model_validate`` из "защищённого
   namespace" ``model_*`` бросают ``ValueError`` на ``create_model`` — конфликт с
   методом ``BaseModel``, а не на записи значения; прочие имена вида ``model_*``
   собираются с ``UserWarning``, без исключения — ведущий ``_`` вообще не раскалывает
   ничего: pydantic молча не создаёт поле, а каталог такое имя и не может произвести,
   см. ADR-RM-007) — не должна ронять сборку остальных плагинов ("сосед-калека").
2. ``create_model`` строит НОВЫЙ класс на каждый вызов ``from_catalog`` — если бы
   классы кэшировались по имени плагина между менеджерами, два менеджера от одного
   payload делили бы состояние через общий class-level default (mutable default
   pydantic копирует per-instance, но проверяем прямой факт — разные объекты).
3. Копия использует тот же ``SchemaBase`` (``validate_assignment=True``), что и
   оригинал — значит она обязана реально ОТКАЗЫВАТЬ невалидные значения, а не молча
   принимать (иначе форма из каталога тихо перестаёт защищать от мусора).
4. ``FieldMeta.routing`` — Annotated-метаданные, не data-поле; при пересборке через
   ``create_model`` их легко потерять (передать только тип, забыть ``Annotated``) —
   тогда dispatch к бэкенду (``send_callback``) молча перестанет срабатывать для
   полей с ``routing={"process_targets": [...]}``.
5. ``validate()`` (FieldMeta.min/max/access_level) и pydantic ``validate_assignment``
   (тип/Literal на setattr) — ДВЕ РАЗНЫЕ проверки на РАЗНЫХ этапах. below-min (3)
   проверяет только первую; если копия построена без ``validate_assignment=True``,
   ЛЮБОЕ поле без FieldMeta.min/max (Literal, произвольный int/str) тихо принимает
   мусор — это отдельная дыра, закрытая тестом (e).
6. Отказ сборки копии (hazard 1) должен быть ВИДЕН, а не только не ронять сборку.
   ``RegistersManager._log_warning`` в отсутствие слота ``logger`` (вызов
   ``from_catalog`` без ``logger=``) молча проглатывает запись — форма поля видна,
   но правка отвечает «Регистр не найден» без единой строки лога (та же немая точка, что чинили Ф5/Ф6.х в
   ``stats_manager._note_observation_bypass``). Найдено ревью 2026-09-25, закрыто
   вторым каналом голоса (``get_std_logger``) — тест (f) проверяет НАБЛЮДАЕМЫЙ вывод
   (перехваченную запись лога), а не факт вызова метода по имени.

Только локальные ``SchemaBase``-классы (без импорта ``Plugins.*``/``Services.*`` —
Правило 9 CLAUDE.md, framework не знает о prototype/plugins) — payload собирается
через ``FieldInfo.to_dict()`` тем же способом, что и pytest-приёмка тестера.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any, Literal

import pytest

from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase
from multiprocess_framework.modules.registers_module.core.field_info import extract_fields
from multiprocess_framework.modules.registers_module.core.manager import RegistersManager


class _Good(SchemaBase):
    """Здоровый регистр — сосед калеки в hazard (a)."""

    level: Annotated[int, FieldMeta("Level", min=0, max=10)] = 3


class _Routed(SchemaBase):
    """Регистр с полем, у которого есть dispatch-цель (hazard d)."""

    gain: Annotated[int, FieldMeta("Gain", min=0, max=100, routing={"process_targets": ["proc_a"]})] = 5


class _Typed(SchemaBase):
    """Поля БЕЗ FieldMeta (или без min/max) — validate() их не проверяет вообще (hazard e)."""

    mode: Literal["a", "b"] = "a"
    count: int = 1


def _fields_payload(cls: type, plugin_name: str) -> list[dict[str, Any]]:
    return [fi.to_dict() for fi in extract_fields(plugin_name, cls, category="test")]


def _plugin_entry(name: str, fields: list[dict[str, Any]]) -> dict[str, Any]:
    return {"name": name, "category": "test", "register": {"fields": fields}}


# ---------------------------------------------------------------------------
# (a) поломка одной записи не роняет сборку и не задевает соседа
# ---------------------------------------------------------------------------


def test_poisoned_entry_does_not_break_neighbor() -> None:
    """Post: from_catalog не падает на поле, недопустимом для create_model; сосед редактируем."""
    good_fields = _fields_payload(_Good, "good")
    # Измерено эмпирически: ИМЕННО "model_dump" (не любое имя из "model_*") бросает
    # ValueError на create_model — конфликт с методом BaseModel.model_dump (а не на
    # записи значения). Прочие имена вида "model_*" собираются с UserWarning, без
    # исключения — см. модульный докстринг, пункт 1.
    bad_fields = [
        {
            "plugin_name": "bad",
            "field_name": "model_dump",
            "type": "int",
            "optional": False,
            "default": 0,
            "meta": None,
            "category": "test",
        }
    ]
    payload = {
        "success": True,
        "rev": "0" * 64,
        "plugins": [_plugin_entry("good", good_fields), _plugin_entry("bad", bad_fields)],
        "failed_imports": {},
    }

    rm = RegistersManager.from_catalog(payload)  # не должен бросить

    # Сосед-калека: инстанса нет, но get_fields()-кэш (наполняется до попытки
    # инстанцирования) не пострадал.
    assert rm.get_register("bad") is None
    assert [fi.field_name for fi in rm.get_fields("bad")] == ["model_dump"]

    # Здоровый плагин остаётся полностью редактируемым.
    assert rm.get_register("good") is not None
    assert rm.set_value("good", "level", 7) is True
    assert rm.get_register("good").level == 7


# ---------------------------------------------------------------------------
# (b) две сборки из одного payload не делят инстансы
# ---------------------------------------------------------------------------


def test_two_managers_share_no_instances() -> None:
    """Post: RegistersManager.from_catalog(payload) дважды -> разные объекты, независимая мутация."""
    fields = _fields_payload(_Good, "good")
    payload = {
        "success": True,
        "rev": "0" * 64,
        "plugins": [_plugin_entry("good", fields)],
        "failed_imports": {},
    }

    rm1 = RegistersManager.from_catalog(payload)
    rm2 = RegistersManager.from_catalog(payload)

    reg1, reg2 = rm1.get_register("good"), rm2.get_register("good")
    assert reg1 is not reg2, "два менеджера из одного payload делят инстанс регистра"

    assert rm1.set_value("good", "level", 9) is True
    assert reg2.level == 3, f"мутация rm1 просочилась в rm2: level={reg2.level!r}"


# ---------------------------------------------------------------------------
# (c) копия реально отклоняет невалидное значение — не молчаливый passthrough
# ---------------------------------------------------------------------------


def test_copy_rejects_below_min_and_keeps_old_value() -> None:
    """Post: set_value(below_min) -> False, значение в регистре не меняется."""
    fields = _fields_payload(_Good, "good")
    payload = {
        "success": True,
        "rev": "0" * 64,
        "plugins": [_plugin_entry("good", fields)],
        "failed_imports": {},
    }
    rm = RegistersManager.from_catalog(payload)

    ok = rm.set_value("good", "level", -1)  # min=0

    assert ok is False, "копия молча приняла значение ниже min — validate_assignment не работает"
    assert rm.get_register("good").level == 3, "значение изменилось несмотря на отказ set_value"


# ---------------------------------------------------------------------------
# (d) FieldMeta.routing переживает пересборку через create_model
# ---------------------------------------------------------------------------


def test_routing_survives_into_copy_and_reaches_send_callback() -> None:
    """Post: set_value на поле с routing.process_targets -> send_callback вызван РОВНО 1 раз."""
    fields = _fields_payload(_Routed, "routed")
    payload = {
        "success": True,
        "rev": "0" * 64,
        "plugins": [_plugin_entry("routed", fields)],
        "failed_imports": {},
    }

    calls: list[tuple[str, str, str, Any]] = []

    def _spy(channel: str, register_name: str, field_name: str, value: Any, snapshot: dict) -> None:
        calls.append((channel, register_name, field_name, value))

    rm = RegistersManager.from_catalog(payload, send_callback=_spy)

    ok = rm.set_value("routed", "gain", 42)

    assert ok is True
    assert calls == [("control_proc_a", "routed", "gain", 42)], (
        f"send_callback вызван не так, как ожидалось (routing.process_targets потерян?): {calls}"
    )


# ---------------------------------------------------------------------------
# (e) копия отвергает неверный Literal и неверный тип НА ЭТАПЕ setattr —
#     below-min (тест c) эту защиту не проверяет
# ---------------------------------------------------------------------------


def test_copy_rejects_wrong_literal_and_wrong_type_on_assignment() -> None:
    """Post: setattr-валидация (не validate()) отклоняет неверный Literal/тип.

    Найдено break-injection лида (I4: копия построена на SchemaBase-подклассе с
    ``model_config`` вида ``validate_assignment=False``) — тест (c)
    (``test_copy_rejects_below_min_and_keeps_old_value``) остаётся зелёным под этим
    брейком, потому что ``below_min`` ловится РАНЬШЕ setattr — в
    ``RegistersManager.validate_field_value`` -> ``FieldMeta.validate_value``,
    которая проверяет ТОЛЬКО access_level и числовой диапазон [min, max]. У полей
    БЕЗ FieldMeta (``count: int``) или с FieldMeta без min/max эта проверка вообще
    не участвует: ``isinstance(value, (int, float))`` не проходит ни для строки
    "zzz" (Literal-поле), ни для строки "abc" (int-поле) — ``validate_value``
    возвращает ``(True, None)`` для ЛЮБОГО значения. Единственная защита от
    неверного Literal/типа — pydantic ``validate_assignment=True`` на ``setattr``,
    ИМЕННО её проверяет этот тест (в отличие от below-min, который проверяет более
    раннюю, отдельную ветку — числовой диапазон).
    """
    fields = _fields_payload(_Typed, "typed")
    payload = {
        "success": True,
        "rev": "0" * 64,
        "plugins": [_plugin_entry("typed", fields)],
        "failed_imports": {},
    }
    rm = RegistersManager.from_catalog(payload)

    ok_literal, err_literal = rm.set_field_value("typed", "mode", "zzz")
    assert ok_literal is False, f"копия молча приняла невалидный Literal: err={err_literal!r}"
    assert rm.get_register("typed").mode == "a", "значение mode изменилось несмотря на отказ"

    ok_type, err_type = rm.set_field_value("typed", "count", "abc")
    assert ok_type is False, f"копия молча приняла строку вместо int: err={err_type!r}"
    assert rm.get_register("typed").count == 1, "значение count изменилось несмотря на отказ"


# ---------------------------------------------------------------------------
# (f) отказ сборки копии виден в логе, даже когда logger= не передан
# ---------------------------------------------------------------------------


def test_build_failure_is_observable_without_logger_passed(caplog: pytest.LogCaptureFixture) -> None:
    """Post: без ``logger=`` отказ сборки копии всё равно попадает в перехваченный лог.

    MAJOR-находка ревью 2026-09-25: ``RegistersManager._log_warning`` уходит в
    ``ObservableMixin._call_manager("logger", ...)``, у которого ТРИ тихих допуска
    (слота нет / менеджер ``None`` / слот выключен) — при ``RegistersManager.
    from_catalog(payload)`` БЕЗ ``logger=`` запись молча проглатывается: форма поля
    видна, а ``set_field_value`` отвечает «Регистр не найден» без единой строки
    лога — тот же класс дефекта, что чинили Ф5/Ф6.х в
    ``stats_manager._note_observation_bypass`` (``get_std_logger`` вместо
    ``_log_warning`` ИЛИ рядом с ним, когда голос обязан звучать независимо от
    того, поднят ли LoggerManager процесса).

    Проверяется НАБЛЮДАЕМЫЙ ВЫВОД (перехваченная запись лога с именем поломанного
    плагина в тексте), а не факт вызова ``get_std_logger`` по имени метода — спай на
    имя метода пережил бы рефакторинг на другой канал доставки и остался бы зелёным
    при реально немом логе (см. project-rules про спай на имени API).
    """
    bad_fields = [
        {
            "plugin_name": "bad_visible",
            "field_name": "model_dump",
            "type": "int",
            "optional": False,
            "default": 0,
            "meta": None,
            "category": "test",
        }
    ]
    payload = {
        "success": True,
        "rev": "0" * 64,
        "plugins": [_plugin_entry("bad_visible", bad_fields)],
        "failed_imports": {},
    }

    with caplog.at_level(
        logging.WARNING,
        logger="multiprocess_framework.modules.registers_module.core.manager",
    ):
        rm = RegistersManager.from_catalog(payload)  # БЕЗ logger=

    assert rm.get_register("bad_visible") is None  # сборка действительно не удалась

    said = [r.getMessage() for r in caplog.records if "bad_visible" in r.getMessage()]
    assert said, (
        "отказ сборки копии НЕ виден в логе без logger= — тот же немой контрол, что был "
        "у stats_manager до Ф5/Ф6.х (get_std_logger должен звучать независимо от "
        "_log_warning)"
    )


def test_undecodable_entry_does_not_break_neighbor(caplog: pytest.LogCaptureFixture) -> None:
    """(g) Описание, которое не разбирает ``FieldInfo.from_dict``, теряет только себя.

    Ревью итерации 2: разбор описания шёл вне ``try`` — поле без ``type`` давало
    ``KeyError`` из ``from_catalog``, и вместе с ним терялся здоровый сосед. Два вида
    порчи: поле без ключа ``type`` и поле-строка вместо словаря.
    """
    healthy = extract_fields("healthy", _Typed)
    payload = {
        "plugins": [
            _plugin_entry("no_type", [{"plugin_name": "no_type", "field_name": "x", "default": 0}]),
            _plugin_entry("str_field", ["not-a-dict"]),
            _plugin_entry("healthy", [f.to_dict() for f in healthy]),
        ]
    }

    with caplog.at_level(logging.WARNING):
        rm = RegistersManager.from_catalog(payload)

    assert rm.get_register("no_type") is None
    assert rm.get_register("str_field") is None
    assert rm.set_field_value("healthy", "count", 5) == (True, None)
    said = " ".join(r.getMessage() for r in caplog.records)
    assert "no_type" in said and "str_field" in said
