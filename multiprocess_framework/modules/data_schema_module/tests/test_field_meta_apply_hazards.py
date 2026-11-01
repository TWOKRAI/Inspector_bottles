# -*- coding: utf-8 -*-
"""Hazard-тесты автора Task 1.1: ``FieldMeta.apply`` / ``FieldMeta.enabled_if`` (ADR-DS-011).

Что может сломаться в ЭТОМ механизме, исходя из того, как он построен:

* метаданные ездят через IPC-кодек ``FieldInfo.to_dict -> JSON -> from_dict``; хаб новее GUI
  присылает незнакомый ``apply`` — без мягкого ``from_dict`` ``RegistersManager.from_catalog``
  выбросил бы регистр плагина целиком;
* проверка ссылок ``enabled_if`` стоит в ``get_all_fields_meta`` — там, где он не зовётся
  (``model_construct``, ``extract_fields`` хаба), ошибки нет; она появляется на GUI-копии,
  и её отказ не должен ронять соседние плагины;
* текст отказа не печатает значения условий (ADR-DS-010 п.3): называется ключ;
* ``enabled_if`` хранится копией — правка списка, переданного в конструктор, или словаря из
  ``to_dict`` не меняет метаданные класса.

Классы — локальные ``SchemaBase`` (без ``from __future__ import annotations``: аннотации
вычисляются сразу, локальные имена разрешать не нужно).
"""

import json
import logging
from enum import Enum
from typing import Annotated, Any

import pytest
from pydantic import create_model

from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase
from multiprocess_framework.modules.registers_module.core.field_info import extract_fields
from multiprocess_framework.modules.registers_module.core.manager import RegistersManager


class _Good(SchemaBase):
    """Здоровый регистр с новой мета: apply + enabled_if на существующее поле."""

    trigger_managed: bool = False
    gain: Annotated[float, FieldMeta("g", apply="live", enabled_if={"trigger_managed": [True]})] = 0.0


class _Bad(SchemaBase):
    """Ссылка на несуществующее поле. Определение не падает; extract_fields хаба — тоже."""

    gain: Annotated[float, FieldMeta("g", enabled_if={"no_such": [1]})] = 0.0


class _Legacy(SchemaBase):
    """Поле без apply и enabled_if — как у всех существующих регистров."""

    level: Annotated[int, FieldMeta("Level", min=0, max=10)] = 3


def _payload(cls: type, plugin_name: str) -> list[dict[str, Any]]:
    """Поля так, как они уезжают через IPC: ``FieldInfo.to_dict`` -> JSON -> dict."""
    fields = [fi.to_dict() for fi in extract_fields(plugin_name, cls, category="test")]
    return json.loads(json.dumps(fields))


def _entry(name: str, fields: list[dict[str, Any]]) -> dict[str, Any]:
    return {"name": name, "category": "test", "register": {"fields": fields}}


# ---------------------------------------------------------------------------
# Проверка ссылок: где срабатывает, где нет
# ---------------------------------------------------------------------------


def test_instantiating_class_with_bad_reference_raises_value_error_naming_the_ref() -> None:
    """``Bad()`` -> pydantic ``ValidationError`` (подкласс ``ValueError``) с именем ссылки."""
    with pytest.raises(ValueError, match="no_such"):
        _Bad()


def test_model_construct_does_not_raise_on_bad_reference() -> None:
    """Потолок ADR-DS-011: ``model_construct`` обходит валидаторы и ``get_all_fields_meta``."""
    obj = _Bad.model_construct()
    assert obj.gain == 0.0


def test_error_text_names_class_field_and_reference_but_not_the_condition_values() -> None:
    class _Secret(SchemaBase):
        gain: Annotated[float, FieldMeta("g", enabled_if={"no_such": ["s3cr3t-value"]})] = 0.0

    with pytest.raises(ValueError) as exc_info:
        _Secret.get_all_fields_meta()
    text = str(exc_info.value)
    assert "_Secret.gain" in text
    assert "no_such" in text
    assert "s3cr3t-value" not in text


def test_reference_to_field_declared_later_in_the_same_class_is_accepted() -> None:
    """Порядок объявления не важен: проверка идёт после обхода всех ``model_fields``."""

    class _Later(SchemaBase):
        gain: Annotated[float, FieldMeta("g", enabled_if={"flag": [True]})] = 0.0
        flag: bool = False

    assert _Later.get_all_fields_meta()["gain"].enabled_if == {"flag": [True]}


# ---------------------------------------------------------------------------
# Конструктор и копии
# ---------------------------------------------------------------------------


def test_enabled_if_stores_a_copy_of_the_callers_lists() -> None:
    allowed = [True]
    meta = FieldMeta(enabled_if={"flag": allowed})
    allowed.append(False)
    assert meta.enabled_if == {"flag": [True]}


def test_tuple_of_values_is_accepted_and_stored_as_list() -> None:
    assert FieldMeta(enabled_if={"mode": ("a", "b")}).enabled_if == {"mode": ["a", "b"]}


@pytest.mark.parametrize("bad_key", ["", 5, None], ids=["empty-str", "int", "none"])
def test_constructor_rejects_non_string_or_empty_key(bad_key: Any) -> None:
    with pytest.raises(ValueError):
        FieldMeta(enabled_if={bad_key: [1]})


def test_constructor_rejects_non_mapping_enabled_if() -> None:
    with pytest.raises(ValueError):
        FieldMeta(enabled_if=[("mode", ["a"])])  # type: ignore[arg-type]


class _Mode(Enum):
    AUTO = "auto"


class _StrMode(str, Enum):
    AUTO = "auto"


@pytest.mark.parametrize(
    "item",
    [[1], {"k": 1}, (1,), _Mode.AUTO, _StrMode.AUTO, object()],
    ids=["list", "dict", "tuple", "enum", "str-enum", "object"],
)
def test_constructor_rejects_non_scalar_list_items_naming_key_not_values(item: Any) -> None:
    with pytest.raises(ValueError) as exc_info:
        FieldMeta(enabled_if={"mode": [item]})
    text = str(exc_info.value)
    assert "mode" in text
    # Ни repr, ни str элемента, ни (для Enum) его значение в текст не попадают.
    forbidden = {repr(item), str(item)}
    if isinstance(item, Enum):
        forbidden.add(str(item.value))
    for fragment in forbidden:
        assert fragment not in text


@pytest.mark.parametrize("item", [True, 0, 1.5, "auto", None], ids=["bool", "int", "float", "str", "none"])
def test_constructor_accepts_scalar_list_items(item: Any) -> None:
    assert FieldMeta(enabled_if={"mode": [item]}).enabled_if == {"mode": [item]}


def test_nested_list_item_is_rejected_so_to_dict_copy_cannot_alias_class_meta() -> None:
    """Воспроизведение ревью: вложенный список делал копию ``to_dict`` поверхностной."""
    with pytest.raises(ValueError):
        FieldMeta(enabled_if={"a": [[1]]})


def test_from_dict_nested_list_item_drops_enabled_if_with_warning_naming_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        back = FieldMeta.from_dict({"description": "x", "enabled_if": {"mode": [["secret-nested"]]}})
    assert back.enabled_if is None
    assert back.description == "x"
    assert "mode" in caplog.text
    assert "secret-nested" not in caplog.text


def test_to_dict_enabled_if_mutation_does_not_touch_the_class_meta() -> None:
    meta = FieldMeta(enabled_if={"flag": [True]})
    out = meta.to_dict()
    out["enabled_if"]["flag"].append(False)
    out["enabled_if"]["other"] = [1]
    assert meta.enabled_if == {"flag": [True]}


@pytest.mark.parametrize("mode", ["live", "restart", "config"])
def test_every_apply_mode_round_trips(mode: str) -> None:
    back = FieldMeta.from_dict(json.loads(json.dumps(FieldMeta(apply=mode).to_dict())))
    assert back.apply == mode


# ---------------------------------------------------------------------------
# from_dict мягок и говорит об этом
# ---------------------------------------------------------------------------


def test_from_dict_bad_apply_is_dropped_with_warning(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        back = FieldMeta.from_dict({"description": "x", "apply": "hot"})
    assert back.apply is None
    assert back.description == "x"
    assert "hot" in caplog.text


def test_from_dict_bad_enabled_if_is_dropped_with_warning_naming_key_not_values(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        back = FieldMeta.from_dict({"description": "x", "enabled_if": {"mode": "auto"}})
    assert back.enabled_if is None
    assert back.description == "x"
    assert "mode" in caplog.text
    assert "auto" not in caplog.text


def test_from_dict_non_mapping_enabled_if_is_dropped_with_warning(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        back = FieldMeta.from_dict({"enabled_if": ["mode"]})
    assert back.enabled_if is None
    assert "enabled_if" in caplog.text


def test_from_dict_valid_apply_and_enabled_if_emit_no_warning(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        back = FieldMeta.from_dict({"apply": "config", "enabled_if": {"flag": [True]}})
    assert (back.apply, back.enabled_if) == ("config", {"flag": [True]})
    assert caplog.text == ""


# ---------------------------------------------------------------------------
# IPC-кодек в сборе: from_catalog (GUI-копия через create_model)
# ---------------------------------------------------------------------------


def test_from_catalog_old_meta_without_new_keys_still_builds_the_copy() -> None:
    """Хаб старее GUI: в meta нет ни apply, ни enabled_if — копия строится, поля None."""
    fields = _payload(_Legacy, "legacy")
    assert "apply" not in fields[0]["meta"] and "enabled_if" not in fields[0]["meta"]
    manager = RegistersManager.from_catalog({"plugins": [_entry("legacy", fields)]})
    assert manager.get_register("legacy") is not None
    meta = manager.get_fields("legacy")[0].meta
    assert (meta.apply, meta.enabled_if) == (None, None)


def test_from_catalog_new_meta_survives_and_copy_checks_the_reference() -> None:
    fields = _payload(_Good, "good")
    manager = RegistersManager.from_catalog({"plugins": [_entry("good", fields)]})
    register = manager.get_register("good")
    assert register is not None
    gain = register.get_all_fields_meta()["gain"]
    assert (gain.apply, gain.enabled_if) == ("live", {"trigger_managed": [True]})
    assert gain.is_enabled({"trigger_managed": True}) is True
    assert gain.is_enabled({"trigger_managed": False}) is False


def test_from_catalog_future_apply_mode_does_not_drop_the_plugin_register(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Хаб новее GUI прислал ``apply: "hot"``: поле остаётся, режим отброшен, регистр цел."""
    fields = _payload(_Good, "good")
    for field in fields:
        if field["field_name"] == "gain":
            field["meta"]["apply"] = "hot"
    with caplog.at_level(logging.WARNING):
        manager = RegistersManager.from_catalog({"plugins": [_entry("good", fields)]})
    register = manager.get_register("good")
    assert register is not None
    gain = register.get_all_fields_meta()["gain"]
    assert gain.apply is None
    assert gain.enabled_if == {"trigger_managed": [True]}
    assert "hot" in caplog.text


def test_from_catalog_bad_reference_loses_only_that_plugin_copy_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Хаб пропустил битую ссылку (extract_fields проверки не зовёт): GUI-копия строится через
    ``model()`` и проверка срабатывает — одной строкой в журнал, сосед цел."""
    entries = [
        _entry("bad", _payload(_Bad, "bad")),
        _entry("good", _payload(_Good, "good")),
    ]
    with caplog.at_level(logging.WARNING):
        manager = RegistersManager.from_catalog({"plugins": entries})
    assert manager.get_register("bad") is None
    assert manager.get_register("good") is not None
    assert "no_such" in caplog.text
    assert [fi.field_name for fi in manager.get_fields("bad")] == ["gain"]  # форма для GUI осталась


def test_create_model_copy_accepts_valid_and_rejects_broken_reference() -> None:
    """Копия GUI напрямую: ``create_model(__base__=SchemaBase)`` + ``Annotated[..., FieldMeta]``."""
    flag = (bool, False)
    ok = create_model(
        "Ok",
        __base__=SchemaBase,
        flag=flag,
        gain=(Annotated[float, FieldMeta("g", enabled_if={"flag": [True]})], 0.0),
    )
    assert ok().gain == 0.0
    broken = create_model(
        "Broken",
        __base__=SchemaBase,
        flag=flag,
        gain=(Annotated[float, FieldMeta("g", enabled_if={"flga": [True]})], 0.0),
    )
    with pytest.raises(ValueError, match="flga"):
        broken()
