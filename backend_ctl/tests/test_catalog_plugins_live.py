# -*- coding: utf-8 -*-
"""Live-приёмка Task 1b.2a: ``catalog.plugins`` на хабе сразу после boot, ДО switch.

Независимый тестер (без implementation) — контракт из DESIGN брифинга Task 1b.2a:
хаб-команда ``catalog.plugins`` на "ProcessManager", тот же конверт-паттерн, что у
``recipe.*`` (Task 1b.1: payload под ``reply["result"]``, см.
docs/reviews/2026-09-24_gui-1b.1-green.md, п.2). Сегодня PM наполняет PluginRegistry
только на switch-пути (orchestrator_hooks.py:65-78) — сразу после boot каталог пуст,
т.е. это КРАСНЫЙ тест по конструкции, ДО того как появится сама команда ``catalog.plugins``.

Собственная module-фикстура на УНИКАЛЬНОМ порту (≥8770, вне занятых 8765-8768/8850-8852/
8776 — см. backend_ctl/AGENTS.md, project_concurrent_backends_trap).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from backend_ctl.harness import BackendHarness
from backend_ctl.protocol import unwrap

_PORT = 8905  # уникальный порт этого модуля


def _local_discover_count() -> int:
    """Тот же plugin_paths-ресолв, что делает orchestrator на boot (launch.py:641-650)."""
    from multiprocess_framework.modules.app_module import discover as app_discover
    from multiprocess_framework.modules.process_module.plugins.registry import (
        PluginRegistry,
    )
    from multiprocess_prototype.backend.config.schemas import load_system_config
    from multiprocess_prototype.backend.launch import PROJECT_ROOT
    from multiprocess_prototype.main import CONFIG_PATH

    sys_config = load_system_config(CONFIG_PATH)
    plugin_paths = [
        str(PROJECT_ROOT / p) if not Path(p).is_absolute() else p
        for p in (sys_config.discovery.plugin_paths if sys_config.discovery.auto_discover else [])
    ]
    app_discover(plugin_paths=plugin_paths, service_paths=[])
    return len(PluginRegistry.list())


@pytest.fixture(scope="module")
def catalog_backend():
    """Headless-бэкенд на своём порту — НИКАКИХ команд switch/apply до самого теста."""
    harness = BackendHarness(with_base=True, port=_PORT)
    drv = harness.start()
    try:
        yield drv
    finally:
        harness.stop()


@pytest.mark.harness_smoke
def test_catalog_plugins_live_right_after_boot(catalog_backend) -> None:
    """Acceptance: catalog.plugins сразу после boot возвращает ПОЛНЫЙ каталог, не пустой."""
    expected_count = _local_discover_count()
    print(f"[test_catalog_plugins_live_right_after_boot] локальный discover count = {expected_count}")

    res = catalog_backend.send_command("ProcessManager", "catalog.plugins", timeout=8.0)
    body = unwrap(res, leaf=True)
    assert body.get("success") is True, f"catalog.plugins не success: {res!r}"

    plugins = body.get("plugins")
    assert isinstance(plugins, list), f"plugins не список: {body!r}"
    assert len(plugins) == expected_count, (
        f"catalog.plugins сразу после boot вернул {len(plugins)} плагинов, "
        f"локальный discover нашёл {expected_count} — каталог не полный на момент ответа"
    )

    rev = body.get("rev")
    assert isinstance(rev, str) and len(rev) == 64, f"rev не 64-hex: {rev!r}"
    int(rev, 16)  # ValueError если не hex
