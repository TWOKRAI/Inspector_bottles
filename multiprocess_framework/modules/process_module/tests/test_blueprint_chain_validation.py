"""Тесты SystemBlueprint.check() — оживление validate_chain (Ф4.3, C-4).

Контекст: validate_chain (plugins/port.py) проверяет ВНУТРИПРОЦЕССНУЮ линейную
цепочку плагинов (auto-wiring по позиции) — до этой задачи имел 0 прод-вызовов
(только реэкспорт в plugins/__init__.py). check() уже валидировал МЕЖпроцессные
Wire через are_ports_compatible + однопарный _is_covered_by_auto_wiring для
внутрипроцессных входов; теперь check() дополнительно зовёт validate_chain для
детальной диагностики (какой плагин -> какой плагин, какой dtype несовместим).

Покрытие:
- несовместимая линейная цепочка внутри процесса -> детальная ошибка на check();
- совместимая цепочка -> без ошибок;
- вход, покрытый явным межпроцессным Wire (не соседним плагином в цепочке) —
  НЕ считается несовместимым с предыдущим по позиции плагином (fan-in, regression
  guard на ложные срабатывания).
"""

from __future__ import annotations

import pytest

from ...process_manager_module.topology.blueprint import SystemBlueprint
from ..plugins.base import ProcessModulePlugin
from ..plugins.port import Port
from ..plugins.registry import PluginRegistry


@pytest.fixture(autouse=True)
def _clean_registry():
    """Очистить глобальный PluginRegistry до и после каждого теста (см. test_plugin_manager.py)."""
    PluginRegistry.clear()
    yield
    PluginRegistry.clear()


class _GraySource(ProcessModulePlugin):
    name = "gray_source"
    category = "source"
    outputs = [Port(name="frame", dtype="image/gray", shape="(H, W, 1)")]

    def configure(self, ctx): ...
    def start(self, ctx): ...


class _NeedsBgr(ProcessModulePlugin):
    name = "needs_bgr"
    category = "processing"
    inputs = [Port(name="frame", dtype="image/bgr", shape="(H, W, 3)")]
    outputs = [Port(name="frame", dtype="image/bgr", shape="(H, W, 3)")]

    def configure(self, ctx): ...
    def start(self, ctx): ...


class _BgrSource(ProcessModulePlugin):
    name = "bgr_source"
    category = "source"
    outputs = [Port(name="frame", dtype="image/bgr", shape="(H, W, 3)")]

    def configure(self, ctx): ...
    def start(self, ctx): ...


class _MaskSource(ProcessModulePlugin):
    name = "mask_source"
    category = "source"
    outputs = [Port(name="mask", dtype="image/gray", shape="(H, W, 1)")]

    def configure(self, ctx): ...
    def start(self, ctx): ...


class _NeedsMaskOptional(ProcessModulePlugin):
    """Второй вход 'mask' — опциональный, обычно приходит через явный Wire (fan-in)."""

    name = "needs_mask_wired"
    category = "processing"
    inputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)"),
        Port(name="mask", dtype="image/gray", shape="(H, W, 1)"),
    ]
    outputs = [Port(name="frame", dtype="image/bgr", shape="(H, W, 3)")]

    def configure(self, ctx): ...
    def start(self, ctx): ...


def _register(*classes: type[ProcessModulePlugin]) -> None:
    for cls in classes:
        PluginRegistry.register(name=cls.name, plugin_class=cls, category=cls.category)


def test_incompatible_linear_chain_reports_detailed_error():
    _register(_GraySource, _NeedsBgr)
    bp = SystemBlueprint.model_validate(
        {
            "name": "chain_test",
            "processes": [
                {
                    "process_name": "proc",
                    "plugins": [
                        {"plugin_name": "gray_source", "plugin_class": ""},
                        {"plugin_name": "needs_bgr", "plugin_class": ""},
                    ],
                }
            ],
            "wires": [],
        }
    )
    errors = bp.check()
    assert any("gray_source" in e and "needs_bgr" in e for e in errors), errors


def test_compatible_linear_chain_no_chain_errors():
    _register(_BgrSource, _NeedsBgr)
    bp = SystemBlueprint.model_validate(
        {
            "name": "chain_ok",
            "processes": [
                {
                    "process_name": "proc",
                    "plugins": [
                        {"plugin_name": "bgr_source", "plugin_class": ""},
                        {"plugin_name": "needs_bgr", "plugin_class": ""},
                    ],
                }
            ],
            "wires": [],
        }
    )
    assert bp.check() == []


def test_wired_secondary_input_not_falsely_flagged_by_chain_check():
    """mask приходит явным межпроцессным Wire, а не от bgr_source по позиции —
    validate_chain НЕ должен ругаться на несовместимость frame-выхода bgr_source
    с mask-входом needs_mask_wired (это не соседняя пара по цепочке auto-wiring)."""
    _register(_BgrSource, _MaskSource, _NeedsMaskOptional)
    bp = SystemBlueprint.model_validate(
        {
            "name": "fanin_test",
            "processes": [
                {
                    "process_name": "mask_proc",
                    "plugins": [{"plugin_name": "mask_source", "plugin_class": ""}],
                },
                {
                    "process_name": "proc",
                    "plugins": [
                        {"plugin_name": "bgr_source", "plugin_class": ""},
                        {"plugin_name": "needs_mask_wired", "plugin_class": ""},
                    ],
                },
            ],
            "wires": [
                {
                    "source": "mask_proc.mask_source.mask",
                    "target": "proc.needs_mask_wired.mask",
                }
            ],
        }
    )
    errors = bp.check()
    # Wire валиден (gray -> gray) и покрывает 'mask'-вход needs_mask_wired.
    # validate_chain НЕ должен ругаться на несовместимость frame(bgr) выхода
    # bgr_source с mask(gray) входом needs_mask_wired — это разные порты,
    # 'mask' удовлетворён явным Wire, а не позицией в цепочке.
    assert errors == [], errors
