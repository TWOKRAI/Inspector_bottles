# -*- coding: utf-8 -*-
"""RegistersManager: контейнер, делегирование, подписки, set_field_value, plugin-расширения."""

from __future__ import annotations

from typing import Annotated, Any, ClassVar, Dict, List

import pytest

from multiprocess_framework.modules.data_schema_module import FieldMeta, RegisterDispatchMeta, SchemaBase

from multiprocess_framework.modules.registers_module import RegistersManager
from multiprocess_framework.modules.registers_module.core.field_info import extract_fields


class _Draw(SchemaBase):
    dp: Annotated[float, FieldMeta("DP", min=0.1, max=20.0)] = 1.4


class _ReadOnly(SchemaBase):
    x: Annotated[int, FieldMeta("X", readonly=True)] = 1


class _Disp(SchemaBase):
    register_dispatch: ClassVar[RegisterDispatchMeta] = RegisterDispatchMeta(
        process_targets=("p1",),
    )
    n: Annotated[int, FieldMeta("N", min=0, max=10)] = 0


def test_get_register_existing() -> None:
    d = _Draw()
    rm = RegistersManager({"draw": d})
    assert rm.get_register("draw") is d


def test_get_register_missing_returns_none() -> None:
    rm = RegistersManager({})
    assert rm.get_register("nope") is None


def test_set_register_dynamic() -> None:
    rm = RegistersManager({})
    d = _Draw()
    rm.set_register("draw", d)
    assert rm.get_register("draw") is d


def test_register_names() -> None:
    rm = RegistersManager({"a": _Draw(), "b": _Draw()})
    assert set(rm.register_names()) == {"a", "b"}


def test_model_dump_all_delegates_to_container() -> None:
    rm = RegistersManager({"draw": _Draw()})
    dumped = rm.model_dump_all()
    assert dumped == {"draw": {"dp": 1.4}}


def test_model_validate_all_delegates_to_container() -> None:
    rm = RegistersManager({"draw": _Draw()})
    rm.model_validate_all({"draw": {"dp": 2.0}}, strict=False)
    assert rm.get_register("draw") is not None
    assert rm.get_register("draw").dp == 2.0


def test_get_field_metadata_delegates() -> None:
    rm = RegistersManager({"draw": _Draw()})
    meta = rm.get_field_metadata("draw", "dp")
    assert meta.get("min") == 0.1
    assert meta.get("max") == 20.0


def test_validate_field_value_delegates() -> None:
    rm = RegistersManager({"draw": _Draw()})
    ok, err = rm.validate_field_value("draw", "dp", 0.05)
    assert ok is False
    assert err is not None
    ok2, err2 = rm.validate_field_value("draw", "dp", 5.0)
    assert ok2 is True
    assert err2 is None


def test_subscribe_and_notify() -> None:
    rm = RegistersManager({"d": _Draw()})
    seen: List[Any] = []

    def cb(v: Any) -> None:
        seen.append(v)

    rm.subscribe("d", "dp", cb)
    rm.notify_field_changed("d", "dp", 9.0)
    assert seen == [9.0]


def test_unsubscribe() -> None:
    rm = RegistersManager({"d": _Draw()})
    seen: List[Any] = []

    def cb(v: Any) -> None:
        seen.append(v)

    rm.subscribe("d", "dp", cb)
    rm.unsubscribe("d", "dp", cb)
    rm.notify_field_changed("d", "dp", 1.0)
    assert seen == []


def test_subscribe_all_global() -> None:
    rm = RegistersManager({"d": _Draw()})
    events: List[tuple] = []

    def gcb(reg: str, field: str, val: Any) -> None:
        events.append((reg, field, val))

    rm.subscribe_all(gcb)
    ok, _ = rm.set_field_value("d", "dp", 3.0)
    assert ok
    assert events == [("d", "dp", 3.0)]


def test_set_field_value_validates_and_notifies() -> None:
    rm = RegistersManager({"d": _Draw()})
    field_vals: List[Any] = []

    rm.subscribe("d", "dp", field_vals.append)
    ok, err = rm.set_field_value("d", "dp", 5.0)
    assert ok and err is None
    assert rm.get_register("d").dp == 5.0
    assert field_vals == [5.0]


def test_set_field_value_invalid_returns_error() -> None:
    rm = RegistersManager({"d": _Draw()})
    ok, err = rm.set_field_value("d", "dp", 0.01)
    assert ok is False
    assert err is not None


def test_set_field_value_calls_send_callback() -> None:
    calls: List[str] = []

    def send_cb(channel: str, *args: object) -> None:
        calls.append(channel)

    rm = RegistersManager({"x": _Disp()}, send_callback=send_cb)
    rm.set_field_value("x", "n", 5)
    assert calls == ["control_p1"]


def test_set_field_value_readonly_rejected() -> None:
    rm = RegistersManager({"r": _ReadOnly()})
    ok, err = rm.set_field_value("r", "x", 2)
    assert ok is False
    assert err is not None


def test_set_field_value_missing_register() -> None:
    rm = RegistersManager({})
    ok, err = rm.set_field_value("ghost", "x", 1)
    assert ok is False
    assert err is not None
    assert "ghost" in err


def test_set_field_value_missing_field() -> None:
    rm = RegistersManager({"d": _Draw()})
    ok, err = rm.set_field_value("d", "nonexistent", 1)
    assert ok is False
    assert err is not None
    assert "nonexistent" in err


def test_set_connection() -> None:
    rm = RegistersManager({"d": _Draw()})
    rm.set_connection("d", "new_process")
    calls: list[str] = []
    rm.set_send_callback(lambda ch, *a: calls.append(ch))
    rm.set_field_value("d", "dp", 5.0)
    assert calls == ["control_new_process"]


def test_set_send_callback() -> None:
    calls_a: list[str] = []
    calls_b: list[str] = []

    rm = RegistersManager({"x": _Disp()}, send_callback=lambda ch, *a: calls_a.append(ch))
    rm.set_field_value("x", "n", 1)
    assert len(calls_a) == 1
    rm.set_send_callback(lambda ch, *a: calls_b.append(ch))
    rm.set_field_value("x", "n", 2)
    assert len(calls_b) == 1
    assert len(calls_a) == 1


def test_set_send_callback_none_disables() -> None:
    calls: list[str] = []
    rm = RegistersManager({"x": _Disp()}, send_callback=lambda ch, *a: calls.append(ch))
    rm.set_send_callback(None)
    rm.set_field_value("x", "n", 3)
    assert calls == []


def test_notify_field_changed_only_field_observers() -> None:
    field_seen: list[Any] = []
    global_seen: list[Any] = []
    send_seen: list[int] = []
    rm = RegistersManager({"d": _Draw()}, send_callback=lambda *a: send_seen.append(1))
    rm.subscribe("d", "dp", field_seen.append)
    rm.subscribe_all(lambda r, f, v: global_seen.append(v))
    rm.notify_field_changed("d", "dp", 9.0)
    assert field_seen == [9.0]
    assert global_seen == []
    assert send_seen == []


def test_observer_exception_does_not_break_others() -> None:
    results: list[Any] = []

    def bad_cb(v: Any) -> None:
        raise RuntimeError("boom")

    def good_cb(v: Any) -> None:
        results.append(v)

    rm = RegistersManager({"d": _Draw()})
    rm.subscribe("d", "dp", bad_cb)
    rm.subscribe("d", "dp", good_cb)
    rm.set_field_value("d", "dp", 5.0)
    assert results == [5.0]


def test_global_observer_exception_does_not_break_others() -> None:
    results: list[Any] = []

    def bad_gcb(r: str, f: str, v: Any) -> None:
        raise RuntimeError("boom")

    def good_gcb(r: str, f: str, v: Any) -> None:
        results.append(v)

    rm = RegistersManager({"d": _Draw()})
    rm.subscribe_all(bad_gcb)
    rm.subscribe_all(good_gcb)
    rm.set_field_value("d", "dp", 5.0)
    assert results == [5.0]


def test_send_callback_exception_logged_not_raised() -> None:
    def bad_send(ch: str, *a: object) -> None:
        raise ConnectionError("network down")

    rm = RegistersManager({"x": _Disp()}, send_callback=bad_send)
    ok, err = rm.set_field_value("x", "n", 5)
    assert ok is True
    assert err is None
    assert rm.get_register("x") is not None
    assert rm.get_register("x").n == 5


def test_subscribe_duplicate_ignored() -> None:
    rm = RegistersManager({"d": _Draw()})
    seen: list[Any] = []
    cb = seen.append
    rm.subscribe("d", "dp", cb)
    rm.subscribe("d", "dp", cb)
    rm.set_field_value("d", "dp", 5.0)
    assert seen == [5.0]


def test_unsubscribe_nonexistent_callback_no_error() -> None:
    rm = RegistersManager({"d": _Draw()})
    rm.unsubscribe("d", "dp", lambda v: None)


def test_unsubscribe_all_nonexistent_no_error() -> None:
    rm = RegistersManager({})
    rm.unsubscribe_all(lambda r, f, v: None)


def test_validate_field_value_missing_register() -> None:
    rm = RegistersManager({})
    ok, err = rm.validate_field_value("ghost", "x", 1)
    assert ok is False
    assert err is not None
    assert "ghost" in err


def test_model_dump_validate_roundtrip() -> None:
    rm = RegistersManager({"d": _Draw()})
    rm.set_field_value("d", "dp", 7.5)
    dumped = rm.model_dump_all()
    rm2 = RegistersManager({"d": _Draw()})
    rm2.model_validate_all(dumped)
    assert rm2.get_register("d") is not None
    assert rm2.get_register("d").dp == 7.5


def test_set_field_value_snapshot_in_send_callback() -> None:
    snapshots: List[Dict[str, Any]] = []

    def send_cb(
        ch: str,
        reg: str,
        field: str,
        val: Any,
        snapshot: Dict[str, Any],
    ) -> None:
        snapshots.append(snapshot)

    rm = RegistersManager({"x": _Disp()}, send_callback=send_cb)
    rm.set_field_value("x", "n", 5)
    assert len(snapshots) == 1
    assert snapshots[0]["n"] == 5


# ===========================================================================
# Plugin-based расширения: from_registry, get_fields, get_categories,
# set_value, validate, extract_fields
# ===========================================================================


class _PluginRegA(SchemaBase):
    """Register A — с FieldMeta для plugin-тестов."""

    threshold: Annotated[int, FieldMeta("Порог", min=0, max=100, unit="%")] = 50
    enabled: Annotated[bool, FieldMeta("Включён")] = True


class _PluginRegB(SchemaBase):
    """Register B — для второго плагина."""

    gain: Annotated[float, FieldMeta("Усиление", min=0.0, max=10.0)] = 1.0
    mode: Annotated[str, FieldMeta("Режим")] = "auto"


class _MockPluginEntry:
    """Мок PluginEntry (duck-typing _PluginEntryLike)."""

    def __init__(self, name: str, category: str, register_classes: list[type]) -> None:
        self.name = name
        self.category = category
        self.register_classes = register_classes


class _MockRegistry:
    """Мок PluginRegistry (duck-typing _PluginRegistryLike)."""

    def __init__(self, entries: list[_MockPluginEntry]) -> None:
        self._entries = entries

    def list(self) -> list[_MockPluginEntry]:
        return self._entries


@pytest.fixture
def mock_registry() -> _MockRegistry:
    """Registry с двумя плагинами и одним без register_classes."""
    return _MockRegistry(
        [
            _MockPluginEntry("plugin_a", "processing", [_PluginRegA]),
            _MockPluginEntry("plugin_b", "source", [_PluginRegB]),
            _MockPluginEntry("plugin_c", "lifecycle", []),  # без register
        ]
    )


# --- from_registry ---


class TestFromRegistry:
    """RegistersManager.from_registry()."""

    def test_builds_from_registry(self, mock_registry: _MockRegistry) -> None:
        """Строит менеджер из PluginRegistry."""
        mgr = RegistersManager.from_registry(mock_registry)
        names = mgr.register_names()
        assert "plugin_a" in names
        assert "plugin_b" in names
        assert "plugin_c" not in names  # нет register_classes

    def test_registers_have_defaults(self, mock_registry: _MockRegistry) -> None:
        """Регистры создаются с defaults."""
        mgr = RegistersManager.from_registry(mock_registry)
        reg_a = mgr.get_register("plugin_a")
        assert reg_a.threshold == 50
        assert reg_a.enabled is True

    def test_categories_populated(self, mock_registry: _MockRegistry) -> None:
        """Категории заполнены."""
        mgr = RegistersManager.from_registry(mock_registry)
        cats = mgr.get_categories()
        assert "processing" in cats
        assert "plugin_a" in cats["processing"]
        assert "source" in cats
        assert "plugin_b" in cats["source"]

    def test_empty_registry(self) -> None:
        """Пустой registry → пустой менеджер."""
        mgr = RegistersManager.from_registry(_MockRegistry([]))
        assert mgr.register_names() == []


# --- get_fields ---


class TestGetFields:
    """get_fields() -> list[FieldInfo]."""

    def test_fields_extracted(self, mock_registry: _MockRegistry) -> None:
        """Поля извлекаются с метаданными."""
        mgr = RegistersManager.from_registry(mock_registry)
        fields = mgr.get_fields("plugin_a")
        assert len(fields) == 2  # threshold + enabled
        names = {f.field_name for f in fields}
        assert names == {"threshold", "enabled"}

    def test_field_has_meta(self, mock_registry: _MockRegistry) -> None:
        """FieldInfo содержит FieldMeta."""
        mgr = RegistersManager.from_registry(mock_registry)
        fields = mgr.get_fields("plugin_a")
        threshold_field = next(f for f in fields if f.field_name == "threshold")
        assert threshold_field.meta is not None
        assert threshold_field.min_value == 0
        assert threshold_field.max_value == 100
        assert threshold_field.unit == "%"

    def test_field_title(self, mock_registry: _MockRegistry) -> None:
        """FieldInfo.title из FieldMeta.description."""
        mgr = RegistersManager.from_registry(mock_registry)
        fields = mgr.get_fields("plugin_a")
        threshold_field = next(f for f in fields if f.field_name == "threshold")
        assert threshold_field.title == "Порог"

    def test_unknown_plugin_returns_empty(self, mock_registry: _MockRegistry) -> None:
        """Несуществующий плагин -> пустой список."""
        mgr = RegistersManager.from_registry(mock_registry)
        assert mgr.get_fields("nonexistent") == []

    def test_fields_cached(self, mock_registry: _MockRegistry) -> None:
        """Повторный вызов — из кэша."""
        mgr = RegistersManager.from_registry(mock_registry)
        fields1 = mgr.get_fields("plugin_a")
        fields2 = mgr.get_fields("plugin_a")
        assert fields1 is fields2


# --- set_value / validate ---


class TestSetValueValidate:
    """set_value / validate — алиасы для FW API."""

    def test_set_value_ok(self, mock_registry: _MockRegistry) -> None:
        """set_value обновляет значение."""
        mgr = RegistersManager.from_registry(mock_registry)
        ok = mgr.set_value("plugin_a", "threshold", 75)
        assert ok is True
        assert mgr.get_register("plugin_a").threshold == 75

    def test_set_value_invalid(self, mock_registry: _MockRegistry) -> None:
        """set_value с невалидным значением -> False."""
        mgr = RegistersManager.from_registry(mock_registry)
        ok = mgr.set_value("plugin_a", "threshold", 999)
        assert ok is False

    def test_validate_ok(self, mock_registry: _MockRegistry) -> None:
        """validate проходит для корректного значения."""
        mgr = RegistersManager.from_registry(mock_registry)
        ok, err = mgr.validate("plugin_a", "threshold", 50)
        assert ok is True
        assert err is None

    def test_validate_fail(self, mock_registry: _MockRegistry) -> None:
        """validate не проходит для невалидного значения."""
        mgr = RegistersManager.from_registry(mock_registry)
        ok, err = mgr.validate("plugin_a", "threshold", -10)
        assert ok is False
        assert err is not None


# --- extract_fields ---


class TestExtractFields:
    """extract_fields() утилита."""

    def test_extract_all_fields(self) -> None:
        """Извлекает все поля."""
        fields = extract_fields("test", _PluginRegA, category="processing")
        assert len(fields) == 2

    def test_field_default(self) -> None:
        """default корректен."""
        fields = extract_fields("test", _PluginRegA)
        threshold = next(f for f in fields if f.field_name == "threshold")
        assert threshold.default == 50

    def test_field_info_is_frozen(self) -> None:
        """FieldInfo — frozen dataclass."""
        fields = extract_fields("test", _PluginRegA)
        with pytest.raises(AttributeError):
            fields[0].field_name = "hacked"  # type: ignore[misc]
