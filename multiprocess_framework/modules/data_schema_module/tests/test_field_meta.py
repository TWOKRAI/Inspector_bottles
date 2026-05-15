# -*- coding: utf-8 -*-
"""
Unit-тесты для FieldMeta, FieldRouting и RegisterMixin.

Сценарии:
    FieldMeta:
        - инициализация и __repr__
        - get_description / get_info с i18n fallback
        - can_modify / is_visible: права доступа и readonly/hidden
        - validate_value: диапазон + права доступа
        - clamp / round_value / process_numeric
        - to_dict: структура и локализация
        - routing: dict и FieldRouting (нормализация)

    RegisterMixin / RegisterBase:
        - get_field_meta: кэш per (class, field)
        - get_all_fields_meta: кэш per class, не включает plain-поля
        - validate_field / validate_field_value (алиас)
        - get_safe_value
        - can_modify_field / get_visible_fields / get_editable_fields
        - get_routing_channels / get_fields_for_channel
        - update_field: успех, ошибка, без изменения при ошибке
        - values_dict == model_dump()
        - _check_field_constraints: min/max при создании

    RegistersContainer (расширенные):
        - __getattr__ — единственный источник правды
        - __contains__, __len__, __iter__
        - __getitem__
        - diff() — только изменённые поля
        - snapshot() — эквивалент to_dict()
        - Нет дублирования: обновление _registers отражается в container.attr

Запуск: из каталога refactored/modules — pytest data_schema_module/tests/ -v
"""

from __future__ import annotations

from typing import Annotated

import pytest

from ..core.field_meta import FieldMeta
from ..core.field_routing import FieldRouting
from ..core.schema_base import RegisterBase
from ..core.schema_mixin import _ALL_FIELDS_META_CACHE, _FIELD_META_CACHE
from ..container.registers_container import RegistersContainer


# =============================================================================
# Вспомогательные модели
# =============================================================================


class SampleRegisters(RegisterBase):
    speed: Annotated[
        float,
        FieldMeta(
            "Скорость",
            info="Скорость движения",
            info_i18n={"en": "Movement speed", "ru": "Скорость движения"},
            unit="м/с",
            min=0.0,
            max=50.0,
            transfer_k=10.0,
            round_k=1,
            routing={"channel": "ctrl_speed"},
            access_level=1,
        ),
    ] = 10.0

    temperature: Annotated[
        float,
        FieldMeta(
            "Температура",
            unit="°C",
            min=-40.0,
            max=120.0,
            readonly=True,
        ),
    ] = 25.0

    label: Annotated[
        str,
        FieldMeta(
            "Метка",
            hidden=True,
            access_level=5,
        ),
    ] = "default"

    # Plain-поле без FieldMeta
    enabled: bool = True


class AnotherRegisters(RegisterBase):
    value: Annotated[int, FieldMeta("Значение", min=0, max=100)] = 50


# =============================================================================
# FieldMeta: базовые свойства
# =============================================================================


class TestFieldMetaInit:
    def test_defaults(self):
        m = FieldMeta("Описание")
        assert m.description == "Описание"
        assert m.info == ""
        assert m.unit == ""
        assert m.min is None
        assert m.max is None
        assert m.transfer_k == 1.0
        assert m.round_k is None
        assert m.routing == {}
        assert m.access_level == 0
        assert m.readonly is False
        assert m.hidden is False

    def test_repr_contains_description(self):
        m = FieldMeta("Тест", min=0.0, max=1.0)
        r = repr(m)
        assert "Тест" in r
        assert "min=0.0" in r
        assert "max=1.0" in r

    def test_routing_from_dict(self):
        m = FieldMeta("X", routing={"channel": "ch1", "priority": 2})
        assert m.routing["channel"] == "ch1"
        assert m.routing["priority"] == 2

    def test_routing_from_field_routing(self):
        fr = FieldRouting(channel="ch2", priority=3)
        m = FieldMeta("X", routing=fr)
        assert m.routing["channel"] == "ch2"
        assert m.routing["priority"] == 3

    def test_routing_from_none(self):
        m = FieldMeta("X")
        assert m.routing == {}

    def test_routing_priority_zero_not_included(self):
        """FieldRouting.to_dict() не включает priority=0 (дефолт)."""
        fr = FieldRouting(channel="ch")
        assert "priority" not in fr.to_dict()


# =============================================================================
# FieldMeta: локализация
# =============================================================================


class TestFieldMetaI18n:
    def test_get_description_no_lang(self):
        m = FieldMeta("Default")
        assert m.get_description() == "Default"

    def test_get_description_with_lang_found(self):
        m = FieldMeta("Default", description_i18n={"en": "English", "ru": "Русский"})
        assert m.get_description("en") == "English"
        assert m.get_description("ru") == "Русский"

    def test_get_description_with_lang_fallback(self):
        m = FieldMeta("Default", description_i18n={"en": "English"})
        assert m.get_description("de") == "Default"

    def test_get_info_with_lang(self):
        m = FieldMeta("D", info="Info", info_i18n={"en": "English info"})
        assert m.get_info("en") == "English info"
        assert m.get_info("de") == "Info"


# =============================================================================
# FieldMeta: доступ
# =============================================================================


class TestFieldMetaAccess:
    def test_can_modify_default(self):
        m = FieldMeta("X")
        assert m.can_modify(0) is True
        assert m.can_modify(10) is True

    def test_can_modify_readonly(self):
        m = FieldMeta("X", readonly=True)
        assert m.can_modify(0) is False
        assert m.can_modify(99) is False

    def test_can_modify_access_level(self):
        m = FieldMeta("X", access_level=3)
        assert m.can_modify(2) is False
        assert m.can_modify(3) is True
        assert m.can_modify(5) is True

    def test_is_visible_default(self):
        m = FieldMeta("X")
        assert m.is_visible(0) is True

    def test_is_visible_hidden(self):
        m = FieldMeta("X", hidden=True)
        assert m.is_visible(0) is False
        assert m.is_visible(99) is False

    def test_is_visible_access_level(self):
        m = FieldMeta("X", access_level=5)
        assert m.is_visible(4) is False
        assert m.is_visible(5) is True


# =============================================================================
# FieldMeta: валидация и числовые операции
# =============================================================================


class TestFieldMetaValidation:
    def test_validate_value_no_constraints(self):
        m = FieldMeta("X")
        ok, err = m.validate_value(999.0)
        assert ok is True
        assert err is None

    def test_validate_value_in_range(self):
        m = FieldMeta("X", min=0.0, max=100.0)
        ok, err = m.validate_value(50.0)
        assert ok is True

    def test_validate_value_below_min(self):
        m = FieldMeta("X", min=0.0, max=100.0)
        ok, err = m.validate_value(-1.0)
        assert ok is False
        assert err is not None
        assert "минимального" in err

    def test_validate_value_above_max(self):
        m = FieldMeta("X", min=0.0, max=100.0)
        ok, err = m.validate_value(101.0)
        assert ok is False
        assert "максимального" in err

    def test_validate_value_no_access(self):
        m = FieldMeta("X", access_level=3)
        ok, err = m.validate_value(50.0, access_level=2)
        assert ok is False
        assert "доступа" in err

    def test_validate_value_string_no_range_check(self):
        """Строковые значения не проверяются по min/max."""
        m = FieldMeta("X", min=0.0, max=100.0)
        ok, err = m.validate_value("hello")
        assert ok is True

    def test_clamp_within_range(self):
        m = FieldMeta("X", min=0.0, max=10.0)
        assert m.clamp(5.0) == 5.0

    def test_clamp_below_min(self):
        m = FieldMeta("X", min=0.0, max=10.0)
        assert m.clamp(-5.0) == 0.0

    def test_clamp_above_max(self):
        m = FieldMeta("X", min=0.0, max=10.0)
        assert m.clamp(15.0) == 10.0

    def test_clamp_no_bounds(self):
        m = FieldMeta("X")
        assert m.clamp(9999.0) == 9999.0

    def test_round_value_with_round_k(self):
        m = FieldMeta("X", round_k=2)
        assert m.round_value(3.14159) == 3.14

    def test_round_value_no_round_k(self):
        m = FieldMeta("X")
        assert m.round_value(3.14159) == 3.14159

    def test_process_numeric(self):
        m = FieldMeta("X", min=0.0, max=5.0, round_k=1)
        # clamp(6.7) → 5.0; round(5.0, 1) → 5.0
        assert m.process_numeric(6.7) == 5.0
        # clamp(3.14) → 3.14; round(3.14, 1) → 3.1
        assert m.process_numeric(3.14) == 3.1


# =============================================================================
# FieldMeta: сериализация
# =============================================================================


class TestFieldMetaToDict:
    def test_to_dict_keys(self):
        m = FieldMeta("Desc", info="Info", unit="px", min=0.0, max=10.0)
        d = m.to_dict()
        for key in (
            "description",
            "info",
            "unit",
            "min",
            "max",
            "transfer_k",
            "round_k",
            "routing",
            "access_level",
            "readonly",
            "hidden",
            "examples",
        ):
            assert key in d

    def test_to_dict_values(self):
        m = FieldMeta("D", unit="м/с", min=1.0, max=100.0)
        d = m.to_dict()
        assert d["description"] == "D"
        assert d["unit"] == "м/с"
        assert d["min"] == 1.0
        assert d["max"] == 100.0

    def test_to_dict_with_lang(self):
        m = FieldMeta("Default", description_i18n={"en": "English"})
        assert m.to_dict("en")["description"] == "English"
        assert m.to_dict("de")["description"] == "Default"


# =============================================================================
# RegisterMixin: метаданные и кэш
# =============================================================================


class TestRegisterMixinMeta:
    def test_get_field_meta_returns_field_meta(self):
        meta = SampleRegisters.get_field_meta("speed")
        assert meta is not None
        assert meta.min == 0.0
        assert meta.max == 50.0

    def test_get_field_meta_returns_none_for_plain_field(self):
        assert SampleRegisters.get_field_meta("enabled") is None

    def test_get_field_meta_is_cached(self):
        """Повторный вызов возвращает тот же объект из кэша."""
        SampleRegisters.get_field_meta("speed")
        assert (SampleRegisters, "speed") in _FIELD_META_CACHE

    def test_get_all_fields_meta_excludes_plain_fields(self):
        all_meta = SampleRegisters.get_all_fields_meta()
        assert "speed" in all_meta
        assert "temperature" in all_meta
        assert "label" in all_meta
        assert "enabled" not in all_meta

    def test_get_all_fields_meta_is_cached(self):
        """Повторный вызов возвращает тот же dict из кэша."""
        SampleRegisters.get_all_fields_meta()
        assert SampleRegisters in _ALL_FIELDS_META_CACHE

    def test_different_classes_have_separate_caches(self):
        SampleRegisters.get_all_fields_meta()
        AnotherRegisters.get_all_fields_meta()
        assert _ALL_FIELDS_META_CACHE.get(SampleRegisters) is not _ALL_FIELDS_META_CACHE.get(AnotherRegisters)

    def test_get_field_metadata_returns_dict(self):
        r = SampleRegisters()
        d = r.get_field_metadata("speed")
        assert isinstance(d, dict)
        assert d["min"] == 0.0
        assert d["unit"] == "м/с"

    def test_get_field_metadata_no_meta_returns_empty(self):
        r = SampleRegisters()
        assert r.get_field_metadata("enabled") == {}

    def test_get_field_description_returns_info(self):
        r = SampleRegisters()
        desc = r.get_field_description("speed")
        assert "Скорость" in desc

    def test_get_field_descriptions_dict(self):
        r = SampleRegisters()
        descs = r.get_field_descriptions()
        assert "speed" in descs
        assert "enabled" not in descs


# =============================================================================
# RegisterMixin: валидация
# =============================================================================


class TestRegisterMixinValidation:
    def test_validate_field_valid(self):
        r = SampleRegisters()
        ok, err = r.validate_field("speed", 20.0, access_level=1)
        assert ok is True

    def test_validate_field_out_of_range(self):
        r = SampleRegisters()
        ok, err = r.validate_field("speed", 999.0, access_level=1)
        assert ok is False

    def test_validate_field_no_access(self):
        r = SampleRegisters()
        ok, err = r.validate_field("speed", 10.0, access_level=0)
        assert ok is False
        assert "доступа" in err

    def test_validate_field_value_alias(self):
        """validate_field_value — псевдоним для validate_field."""
        r = SampleRegisters()
        assert r.validate_field_value("speed", 10.0, 1) == r.validate_field("speed", 10.0, 1)

    def test_validate_field_plain_field_always_passes(self):
        r = SampleRegisters()
        ok, err = r.validate_field("enabled", True)
        assert ok is True

    def test_get_safe_value_clamps(self):
        r = SampleRegisters()
        assert r.get_safe_value("speed", 9999.0) == 50.0
        assert r.get_safe_value("speed", -1.0) == 0.0

    def test_get_safe_value_string_unchanged(self):
        r = SampleRegisters()
        assert r.get_safe_value("label", "hello") == "hello"


# =============================================================================
# RegisterMixin: доступ
# =============================================================================


class TestRegisterMixinAccess:
    def test_can_modify_field_requires_level(self):
        r = SampleRegisters()
        assert r.can_modify_field("speed", access_level=0) is False
        assert r.can_modify_field("speed", access_level=1) is True

    def test_can_modify_readonly_field(self):
        r = SampleRegisters()
        assert r.can_modify_field("temperature", access_level=99) is False

    def test_get_visible_fields_level_0(self):
        r = SampleRegisters()
        visible = r.get_visible_fields(access_level=0)
        assert "speed" not in visible  # access_level=1 требуется
        assert "label" not in visible  # hidden=True
        assert "enabled" in visible

    def test_get_visible_fields_level_5(self):
        r = SampleRegisters()
        visible = r.get_visible_fields(access_level=5)
        # label hidden=True — по-прежнему не видно
        assert "label" not in visible
        # speed видно при уровне 1+
        assert "speed" in visible

    def test_get_editable_fields(self):
        r = SampleRegisters()
        editable = r.get_editable_fields(access_level=1)
        assert "speed" in editable
        assert "temperature" not in editable  # readonly


# =============================================================================
# RegisterMixin: маршрутизация
# =============================================================================


class TestRegisterMixinRouting:
    def test_get_routing_channels(self):
        r = SampleRegisters()
        channels = r.get_routing_channels()
        assert "ctrl_speed" in channels

    def test_get_fields_for_channel(self):
        r = SampleRegisters()
        fields = r.get_fields_for_channel("ctrl_speed")
        assert "speed" in fields

    def test_get_fields_for_nonexistent_channel(self):
        r = SampleRegisters()
        assert r.get_fields_for_channel("nonexistent") == []


# =============================================================================
# RegisterMixin: обновление значений
# =============================================================================


class TestRegisterMixinUpdate:
    def test_update_field_valid(self):
        r = SampleRegisters()
        ok, err = r.update_field("speed", 30.0, access_level=1)
        assert ok is True
        assert r.speed == 30.0

    def test_update_field_invalid_range(self):
        r = SampleRegisters()
        ok, err = r.update_field("speed", 999.0, access_level=1)
        assert ok is False
        assert r.speed == 10.0  # не изменилось

    def test_update_field_no_access(self):
        r = SampleRegisters()
        ok, err = r.update_field("speed", 20.0, access_level=0)
        assert ok is False
        assert r.speed == 10.0

    def test_values_dict_equals_model_dump(self):
        r = SampleRegisters()
        assert r.values_dict() == r.model_dump()


# =============================================================================
# RegisterBase: @model_validator constraints
# =============================================================================


class TestRegisterBaseConstraints:
    def test_valid_creation(self):
        r = SampleRegisters(speed=5.0)
        assert r.speed == 5.0

    def test_creation_below_min_raises(self):
        with pytest.raises(ValueError, match="меньше минимального"):
            SampleRegisters(speed=-1.0)

    def test_creation_above_max_raises(self):
        with pytest.raises(ValueError, match="больше максимального"):
            SampleRegisters(speed=999.0)

    def test_plain_field_not_checked(self):
        """Поле без FieldMeta не проверяется @model_validator."""
        r = SampleRegisters(enabled=False)
        assert r.enabled is False


# =============================================================================
# FieldRouting
# =============================================================================


class TestFieldRouting:
    def test_basic(self):
        fr = FieldRouting(channel="ctrl")
        assert fr.channel == "ctrl"
        assert fr.priority == 0
        assert fr.transform is None

    def test_to_dict_minimal(self):
        fr = FieldRouting(channel="ctrl")
        d = fr.to_dict()
        assert d["channel"] == "ctrl"
        assert "priority" not in d
        assert "transform" not in d

    def test_to_dict_full(self):
        fr = FieldRouting(channel="ctrl", priority=2, transform="scale")
        d = fr.to_dict()
        assert d["priority"] == 2
        assert d["transform"] == "scale"

    def test_to_dict_process_targets(self):
        fr = FieldRouting(channel="ctrl", process_targets=("a", "b"))
        d = fr.to_dict()
        assert d["process_targets"] == ["a", "b"]

    def test_immutable(self):
        fr = FieldRouting(channel="ctrl")
        with pytest.raises((AttributeError, TypeError)):
            fr.channel = "other"

    def test_routing_preserved_in_field_meta(self):
        """FieldRouting нормализуется в dict в FieldMeta.routing."""
        fr = FieldRouting(channel="ctrl", priority=1)
        m = FieldMeta("X", routing=fr)
        assert m.routing["channel"] == "ctrl"
        assert m.routing["priority"] == 1


# =============================================================================
# RegistersContainer: единое состояние + дандеры + diff
# =============================================================================


class TestRegistersContainerEnhanced:
    @pytest.fixture()
    def container(self):
        return RegistersContainer(
            {
                "sample": SampleRegisters,
                "another": AnotherRegisters,
            }
        )

    def test_getattr_access(self, container):
        assert container.sample is not None
        assert isinstance(container.sample, SampleRegisters)

    def test_getitem_access(self, container):
        assert container["sample"] is container.sample

    def test_contains(self, container):
        assert "sample" in container
        assert "nonexistent" not in container

    def test_len(self, container):
        assert len(container) == 2

    def test_iter(self, container):
        names = [name for name, _ in container]
        assert "sample" in names
        assert "another" in names

    def test_repr(self, container):
        r = repr(container)
        assert "RegistersContainer" in r
        assert "sample" in r

    def test_single_source_of_truth(self, container):
        """После model_validate_all container.attr отражает новый экземпляр."""
        old_instance = container._registers["sample"]
        container.model_validate_all({"sample": {"speed": 20.0, "temperature": 25.0, "label": "x", "enabled": True}})
        new_instance = container._registers["sample"]
        assert new_instance is not old_instance
        # __getattr__ возвращает новый экземпляр
        assert container.sample is new_instance
        assert container.sample.speed == 20.0

    def test_no_stale_setattr(self, container):
        """Нет дублирования: __dict__ не содержит register-имён."""
        assert "sample" not in container.__dict__
        assert "another" not in container.__dict__

    def test_diff_empty_when_no_changes(self, container):
        snap = container.snapshot()
        assert container.diff(snap) == {}

    def test_diff_returns_changed_fields(self, container):
        snap = container.snapshot()
        container["sample"].update_field("speed", 25.0, access_level=1)
        changes = container.diff(snap)
        assert "sample" in changes
        assert changes["sample"]["speed"] == 25.0
        assert "temperature" not in changes.get("sample", {})

    def test_diff_does_not_include_unchanged_registers(self, container):
        snap = container.snapshot()
        container["sample"].update_field("speed", 25.0, access_level=1)
        changes = container.diff(snap)
        assert "another" not in changes

    def test_snapshot_equals_to_dict(self, container):
        assert container.snapshot() == container.to_dict()

    def test_getattr_raises_for_unknown(self, container):
        with pytest.raises(AttributeError, match="nonexistent"):
            _ = container.nonexistent


# =============================================================================
# FieldMeta: нормализация алиасов widget
# =============================================================================


class TestFieldMetaWidgetAliases:
    """Нормализация алиасов widget — один источник истины."""

    def test_combo_normalizes_to_literal(self):
        assert FieldMeta(widget="combo").widget == "literal"

    def test_spinbox_normalizes_to_int(self):
        assert FieldMeta(widget="spinbox").widget == "int"

    def test_numeric_normalizes_to_float(self):
        assert FieldMeta(widget="numeric").widget == "float"

    def test_canonical_unchanged(self):
        for w in ("checkbox", "slider", "int", "literal", "color3", "float", "str", "text", "path", "label"):
            assert FieldMeta(widget=w).widget == w, f"Канонический widget '{w}' не должен нормализоваться"

    def test_empty_widget_unchanged(self):
        assert FieldMeta(widget="").widget == ""
