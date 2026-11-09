# -*- coding: utf-8 -*-
"""Task 1.1 (system-run-state) — слепой тест шва ``PluginOrchestrator.config_of(plugin) -> dict``.

Контракт — DESIGN п.6 ``plans/2026-10-27_system-run-state/tasks/1.1.md``: метод ищет ``p is plugin`` среди загруженных
плагинов (после ``boot()``), возвращает КОПИЮ ``dict(ctx.config)``; плагина нет в списке — ``{}``; живой словарь
контекста наружу не отдаётся. Ожидаемые значения — литералы (мета-ключи определения плагина в
``ctx.config`` не попадают).
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.generic.plugin_orchestrator import PluginOrchestrator
from multiprocess_framework.modules.process_module.plugins.base import PluginContext, ProcessModulePlugin
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices

_THIS = "multiprocess_framework.modules.process_module.tests.test_orchestrator_config_of"


class CfgPluginA(ProcessModulePlugin):
    name = "cfg_a"
    category = "processing"

    def configure(self, ctx: PluginContext) -> None: ...

    def start(self, ctx: PluginContext) -> None: ...

    def process(self, items):
        return items


class CfgPluginB(CfgPluginA):
    name = "cfg_b"


def _booted() -> PluginOrchestrator:
    orch = PluginOrchestrator(services=MockProcessServices(name="cfg_of"))
    orch.load_and_configure_managers(
        [
            # плоский формат: параметры на верхнем уровне определения
            {"plugin_class": f"{_THIS}.CfgPluginA", "plugin_name": "cfg_a", "run_gated": False, "camera_id": 3},
            # вложенный формат (GUI): параметры под ключом config
            {"plugin_class": f"{_THIS}.CfgPluginB", "plugin_name": "cfg_b", "config": {"run_gated": True}},
        ]
    )
    orch.boot()
    return orch


def test_config_of_returns_copy_or_empty() -> None:
    """Копия ``ctx.config`` своего плагина; чужой плагин -> ``{}``; мутация результата контекст не трогает."""
    orch = _booted()
    plugin_a, plugin_b = orch.plugins
    assert (plugin_a.name, plugin_b.name) == ("cfg_a", "cfg_b")

    # каждому плагину — его собственный конфиг (по тождеству плагина)
    assert orch.config_of(plugin_a) == {"run_gated": False, "camera_id": 3}
    assert orch.config_of(plugin_b) == {"run_gated": True}

    # результат — dict-копия: мутация не меняет контекст, второй вызов отдаёт нетронутые значения
    got = orch.config_of(plugin_a)
    assert type(got) is dict
    got["run_gated"] = "mutated"
    got["extra"] = 1
    assert orch.config_of(plugin_a) == {"run_gated": False, "camera_id": 3}
    assert orch.config_of(plugin_a) is not orch.config_of(plugin_a), "каждый вызов — свежая копия"

    # плагин, которого нет в списке оркестратора: чужой экземпляр того же класса и плагин другого оркестратора
    stranger = CfgPluginA()
    assert orch.config_of(stranger) == {}
    other = PluginOrchestrator(services=MockProcessServices(name="cfg_other"))
    other.load_and_configure_managers([{"plugin_class": f"{_THIS}.CfgPluginA", "plugin_name": "cfg_a", "x": 1}])
    assert other.config_of(plugin_a) == {}, "плагин до boot() чужого оркестратора не найден"
    other.boot()
    assert other.config_of(plugin_a) == {}, "тождество, не равенство имён: плагин чужого оркестратора -> {}"
    assert other.config_of(other.plugins[0]) == {"x": 1}
