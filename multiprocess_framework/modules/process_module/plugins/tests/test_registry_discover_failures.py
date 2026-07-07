# -*- coding: utf-8 -*-
"""Тесты Ф2.3: PluginRegistry.discover — WARNING + персистентный failed_imports.

R7 аудита: раньше `except Exception → logger.debug` — плагин с опечаткой
МОЛЧА исчезал из каталога. Теперь: WARNING-лог + модуль виден в
failed_imports() (и через introspect.plugins).
"""

from __future__ import annotations

import logging
import sys
import textwrap
from pathlib import Path

import pytest

from multiprocess_framework.modules.process_module.plugins.registry import (
    PluginRegistry,
)

GOOD_PLUGIN = textwrap.dedent("""\
    from multiprocess_framework.modules.process_module.plugins.registry import (
        register_plugin,
    )
    from multiprocess_framework.modules.process_module.plugins.base import (
        ProcessModulePlugin,
    )

    @register_plugin("reg_disc_good", category="testing")
    class GoodPlugin(ProcessModulePlugin):
        name = "reg_disc_good"
        category = "testing"

        def setup(self):
            pass

        def process(self, data):
            return data

        def teardown(self):
            pass
    """)

BROKEN_PLUGIN = "def broken(\n  опечатка — синтаксическая ошибка!!!\n"


@pytest.fixture(autouse=True)
def _clean_registry():
    PluginRegistry.clear()
    yield
    PluginRegistry.clear()


@pytest.fixture()
def mixed_plugin_dir(tmp_path: Path):
    """Пакет с одним корректным и одним сломанным plugin.py."""
    pkg_root = tmp_path / "reg_disc_pkg"
    for sub in ("", "good", "broken"):
        d = pkg_root / sub if sub else pkg_root
        d.mkdir(parents=True, exist_ok=True)
        (d / "__init__.py").touch()

    (pkg_root / "good" / "plugin.py").write_text(GOOD_PLUGIN, encoding="utf-8")
    (pkg_root / "broken" / "plugin.py").write_text(BROKEN_PLUGIN, encoding="utf-8")

    sys.path.insert(0, str(tmp_path))
    yield pkg_root

    sys.path.remove(str(tmp_path))
    for k in [k for k in sys.modules if k.startswith("reg_disc_pkg")]:
        del sys.modules[k]


class TestDiscoverFailedImports:
    def test_broken_plugin_lands_in_failed_imports(self, mixed_plugin_dir: Path) -> None:
        """Сломанный модуль не исчезает молча: он в failed_imports с текстом ошибки."""
        PluginRegistry.discover(str(mixed_plugin_dir))

        failed = PluginRegistry.failed_imports()
        assert len(failed) == 1
        (module_path, error_text), = failed.items()
        assert module_path == "reg_disc_pkg.broken.plugin"
        assert "SyntaxError" in error_text
        # Хороший плагин при этом загрузился
        assert "reg_disc_good" in PluginRegistry

    def test_broken_plugin_logged_as_warning(
        self, mixed_plugin_dir: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Уровень лога — WARNING (раньше debug: невидим при стандартной настройке)."""
        with caplog.at_level(logging.WARNING, logger="multiprocess_framework.modules.process_module.plugins.registry"):
            PluginRegistry.discover(str(mixed_plugin_dir))

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("reg_disc_pkg.broken.plugin" in r.getMessage() for r in warnings)

    def test_failed_import_cleared_after_fix_and_rediscover(self, mixed_plugin_dir: Path) -> None:
        """Починка файла + повторный discover снимают модуль из failed-list."""
        PluginRegistry.discover(str(mixed_plugin_dir))
        assert PluginRegistry.failed_imports()

        fixed = GOOD_PLUGIN.replace("reg_disc_good", "reg_disc_fixed")
        (mixed_plugin_dir / "broken" / "plugin.py").write_text(fixed, encoding="utf-8")

        PluginRegistry.discover(str(mixed_plugin_dir))
        assert PluginRegistry.failed_imports() == {}
        assert "reg_disc_fixed" in PluginRegistry

    def test_failed_imports_persistent_between_discovers(self, mixed_plugin_dir: Path) -> None:
        """Без починки повторный discover сохраняет модуль в failed-list."""
        PluginRegistry.discover(str(mixed_plugin_dir))
        PluginRegistry.discover(str(mixed_plugin_dir))
        assert "reg_disc_pkg.broken.plugin" in PluginRegistry.failed_imports()

    def test_clear_resets_failed_imports(self, mixed_plugin_dir: Path) -> None:
        PluginRegistry.discover(str(mixed_plugin_dir))
        PluginRegistry.clear()
        assert PluginRegistry.failed_imports() == {}

    def test_failed_imports_returns_copy(self, mixed_plugin_dir: Path) -> None:
        """Мутация возвращённого dict не трогает внутреннее состояние."""
        PluginRegistry.discover(str(mixed_plugin_dir))
        snapshot = PluginRegistry.failed_imports()
        snapshot.clear()
        assert PluginRegistry.failed_imports() != {}
