# -*- coding: utf-8 -*-
"""Live-тест Ф2 Task 2.3 acceptance: «плагин с опечаткой виден через driver».

Сценарий: в Plugins/ подкладывается временный plugin.py с синтаксической
ошибкой → boot headless-бэкенда (PM выполняет PluginRegistry.discover в своём
процессе при initialize) → driver.introspect_plugins("ProcessManager") →
модуль-с-опечаткой в ``failed_imports`` с текстом ошибки (раньше: logger.debug,
плагин молча исчезал из каталога — R7 аудита).

Собственная module-фикстура на УНИКАЛЬНОМ порту (≥8770) — ловушка «двух
бэкендов» (см. backend_ctl/AGENTS.md, project_concurrent_backends_trap).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from backend_ctl.harness import BackendHarness

_PORT = 8776  # уникальный порт этого модуля (≥8770)
_PROBE_PREFIX = "_f23_broken_probe_"
_PLUGINS_ROOT = Path(__file__).resolve().parents[2] / "Plugins"


def _result(res: dict) -> dict:
    """Развернуть result-конверт (ответ PM приходит уже развёрнутым)."""
    if isinstance(res, dict) and isinstance(res.get("result"), dict):
        return res["result"]
    return res if isinstance(res, dict) else {}


@pytest.fixture(scope="module")
def broken_plugin_dir():
    """Временный сломанный plugin.py в Plugins/ (снимается в finally).

    Имя уникально по pid; stale-пробники от аварийных прогонов подчищаются
    на входе (leftover безвреден — boot его лишь логирует WARNING'ом, — но
    не должен накапливаться).
    """
    for stale in _PLUGINS_ROOT.glob(f"{_PROBE_PREFIX}*"):
        shutil.rmtree(stale, ignore_errors=True)

    probe = _PLUGINS_ROOT / f"{_PROBE_PREFIX}{os.getpid()}"
    probe.mkdir()
    (probe / "plugin.py").write_text(
        "def broken(\n  опечатка — синтаксическая ошибка!!!\n",
        encoding="utf-8",
    )
    try:
        yield probe
    finally:
        shutil.rmtree(probe, ignore_errors=True)


@pytest.fixture(scope="module")
def plugins_backend(broken_plugin_dir):
    """Headless-бэкенд, загруженный ПОСЛЕ подкладки сломанного плагина."""
    harness = BackendHarness(with_base=True, port=_PORT)
    drv = harness.start()
    try:
        yield drv
    finally:
        harness.stop()


@pytest.mark.harness_smoke
class TestPluginsVisibilityLive:
    def test_typo_plugin_visible_via_driver(self, plugins_backend, broken_plugin_dir) -> None:
        """Acceptance Ф2.3: сломанный модуль виден в failed_imports через driver."""
        res = plugins_backend.introspect_plugins("ProcessManager", timeout=8.0)
        body = _result(res)
        assert body.get("success") is True, body

        failed = body.get("failed_imports") or {}
        expected_module = f"Plugins.{broken_plugin_dir.name}.plugin"
        assert expected_module in failed, f"failed_imports={failed}"
        assert "SyntaxError" in failed[expected_module]

    def test_healthy_plugins_still_registered(self, plugins_backend) -> None:
        """Сломанный модуль не мешает остальному каталогу (contain, not crash)."""
        res = plugins_backend.introspect_plugins("ProcessManager", timeout=8.0)
        body = _result(res)
        assert body.get("success") is True, body
        assert body.get("count", 0) > 0
        assert body.get("plugins")
