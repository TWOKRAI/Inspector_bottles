# -*- coding: utf-8 -*-
"""Unit-тесты базового слоя controls v2 (config, infrastructure, traits)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from frontend_module.components.base.config import (
    BaseControlConfig,
    BindingConfig,
    LabelOverride,
    merge_config,
)
from frontend_module.components.base.infrastructure.register_adapter import (
    RegisterAdapter,
)
from frontend_module.components.base.infrastructure.signal_utils import (
    block_signals,
)
from frontend_module.components.base.infrastructure.value_transformer import (
    ValueTransformer,
)
from frontend_module.components.base.traits.access_trait import AccessTrait
from frontend_module.components.base.traits.debounce_trait import (
    DebounceTrait,
)
from frontend_module.components.base.traits.schema_trait import SchemaTrait
from frontend_module.components.base.traits.sync_trait import SyncTrait
from frontend_module.schemas.register_binding import RegisterFieldMeta, ResolvedMeta


@dataclass
class _Field:
    value: Any


@dataclass
class _FakeRegister:
    min_area: _Field
    color_lower: _Field


class _FakeRegistersManager:
    def __init__(self) -> None:
        self._registers: Dict[str, Any] = {
            "processor": _FakeRegister(min_area=_Field(10), color_lower=_Field([1, 2, 3])),
        }
        self._subs: Dict[tuple, List[Callable[[Any], None]]] = {}
        self._meta: Dict[tuple, dict] = {
            ("processor", "min_area"): {"min": 0, "max": 100, "description": "Area"},
        }

    def get_register(self, name: str) -> Any:
        return self._registers.get(name)

    def get_field_metadata(self, register_name: str, field_name: str) -> Optional[dict]:
        return self._meta.get((register_name, field_name))

    def set_field_value(
        self, register_name: str, field_name: str, value: Any
    ) -> tuple[bool, Optional[str]]:
        reg = self.get_register(register_name)
        if not reg:
            return False, "no register"
        setattr(reg, field_name, _Field(value))
        key = (register_name, field_name)
        for cb in list(self._subs.get(key, [])):
            cb(value)
        return True, None

    def subscribe(
        self, register_name: str, field_name: str, callback: Callable[[Any], None]
    ) -> None:
        key = (register_name, field_name)
        self._subs.setdefault(key, []).append(callback)

    def unsubscribe(
        self, register_name: str, field_name: str, callback: Callable[[Any], None]
    ) -> None:
        key = (register_name, field_name)
        lst = self._subs.get(key)
        if lst and callback in lst:
            lst.remove(callback)


class TestMergeConfig:
    def test_none_override_returns_default(self) -> None:
        d = BaseControlConfig(label="x", enabled=True)
        assert merge_config(d, None) is d

    def test_override_non_none_fields(self) -> None:
        a = BaseControlConfig(label="a", tooltip="t", enabled=True, access_level=0)
        b = BaseControlConfig(label="b", tooltip=None, enabled=False, access_level=1)
        m = merge_config(a, b)
        assert m.label == "b"
        assert m.tooltip == "t"
        assert m.enabled is False
        assert m.access_level == 1

    def test_type_mismatch_raises(self) -> None:
        with pytest.raises(TypeError):
            merge_config(BaseControlConfig(), BindingConfig("r", "f"))


class TestBindingConfig:
    def test_to_config_dict(self) -> None:
        assert BindingConfig("a", "b").to_config_dict() == {
            "register_name": "a",
            "field_name": "b",
            "access_level": 0,
        }
        assert BindingConfig("a", "b", access_level=2, index=1).to_config_dict() == {
            "register_name": "a",
            "field_name": "b",
            "access_level": 2,
            "index": 1,
        }


class TestLabelOverride:
    def test_to_merge_dict_skips_none(self) -> None:
        assert LabelOverride().to_merge_dict() == {}
        d = LabelOverride(label="L", min_val=1.0, max_val=9.0).to_merge_dict()
        assert d["label"] == "L"
        assert d["min"] == 1.0
        assert d["max"] == 9.0


class TestValueTransformer:
    def test_round_trip_with_transfer_k(self) -> None:
        meta = ResolvedMeta.merge(
            RegisterFieldMeta(min=0, max=1000, transfer_k=0.1, round_k=1),
            {},
            "f",
        )
        xf = ValueTransformer(meta)
        assert xf.to_storage(100.0) == pytest.approx(10.0)
        assert xf.to_ui(10.0) == pytest.approx(100.0)
        assert xf.get_step() == pytest.approx(10.0)

    def test_none_meta_defaults(self) -> None:
        xf = ValueTransformer(None)
        assert xf.to_storage(3.0) == 3
        assert xf.to_ui(3) == 3.0
        assert xf.clamp_to_range(5.0) == 5.0


class TestRegisterAdapter:
    def test_read_write_scalar(self) -> None:
        rm = _FakeRegistersManager()
        ad = RegisterAdapter(rm)
        assert ad.read("processor", "min_area") == 10
        ok, err = ad.write("processor", "min_area", 20)
        assert ok and err is None
        assert ad.read("processor", "min_area") == 20

    def test_read_write_indexed_same_callback_two_indices(self) -> None:
        """Один и тот же callback на разных index — обе подписки живы (ключ включает index)."""
        rm = _FakeRegistersManager()
        ad = RegisterAdapter(rm)
        seen: list = []

        def cb(v: Any) -> None:
            seen.append(v)

        ad.subscribe("processor", "color_lower", cb, index=0)
        ad.subscribe("processor", "color_lower", cb, index=1)
        ad.write("processor", "color_lower", [7, 8, 3])
        assert seen == [7, 8]

    def test_unsubscribe_removes_wrapped(self) -> None:
        rm = _FakeRegistersManager()
        ad = RegisterAdapter(rm)
        calls: list = []

        def cb(v: Any) -> None:
            calls.append(v)

        ad.subscribe("processor", "min_area", cb, index=None)
        ad.unsubscribe("processor", "min_area", cb, index=None)
        rm.set_field_value("processor", "min_area", 99)
        assert calls == []


class TestBlockSignals:
    def test_restores_after_block(self) -> None:
        w = MagicMock()
        w.blockSignals = MagicMock()
        with block_signals(w):
            pass
        assert w.blockSignals.call_args_list[0][0][0] is True
        assert w.blockSignals.call_args_list[-1][0][0] is False


class TestSyncTrait:
    def test_read_write_delegates(self) -> None:
        rm = _FakeRegistersManager()
        ad = RegisterAdapter(rm)
        b = BindingConfig("processor", "min_area")
        st = SyncTrait(b, ad)
        assert st.read() == 10
        ok, _ = st.write(5)
        assert ok
        assert st.read() == 5


class TestSchemaTrait:
    def test_label_and_effective_access(self) -> None:
        rm = _FakeRegistersManager()
        ad = RegisterAdapter(rm)
        b = BindingConfig("processor", "min_area", access_level=0)
        st = SchemaTrait(b, ad, config_override=LabelOverride(label="Название"))
        assert st.label == "Название"
        assert st.effective_access_level >= 0

    def test_refresh_reloads_meta_from_adapter(self) -> None:
        rm = _FakeRegistersManager()
        ad = RegisterAdapter(rm)
        b = BindingConfig("processor", "min_area", access_level=0)
        st = SchemaTrait(b, ad)
        assert st.description == "Area"
        rm._meta[("processor", "min_area")] = {
            "min": 0,
            "max": 100,
            "description": "Обновлено",
        }
        st.refresh()
        assert st.description == "Обновлено"


class TestAccessTrait:
    def test_can_modify(self) -> None:
        a = AccessTrait(required_level=2)
        a.update(1)
        assert not a.can_modify()
        a.update(2)
        assert a.can_modify()

    def test_set_required_level(self) -> None:
        a = AccessTrait(required_level=2)
        a.update(3)
        assert a.can_modify()
        a.set_required_level(5)
        assert not a.can_modify()
        a.update(5)
        assert a.can_modify()


@pytest.fixture
def qapp():
    from PyQt5.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class TestDebounceTrait:
    def test_flush_runs_pending(self, qapp) -> None:
        d = DebounceTrait(ms=5000)
        ran = []

        def cb() -> None:
            ran.append(1)

        d.schedule(cb)
        d.flush()
        assert ran == [1]
