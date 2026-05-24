"""Тесты PluginManager — auto-discovery, reload, rescan, обработка ошибок.

Покрытие:
1. discover пустой директории -> пустой результат
2. discover с одним plugin.py -> корректная загрузка
3. reload / rescan — добавление нового файла
4. Failed import (синтаксическая ошибка) -> graceful, в errors
5. list_discovered() — проверка структуры
6. isinstance(pm, BaseManager) — наследование
7. get_stats / get_debug_info — формат
8. initialize / shutdown — жизненный цикл
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from multiprocess_framework.modules.base_manager import BaseManager, ObservableMixin
from multiprocess_framework.modules.process_module.plugins.manager import (
    PluginDiscoveryResult,
    PluginManager,
)
from multiprocess_framework.modules.process_module.plugins.registry import (
    PluginRegistry,
)


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_registry():
    """Очистить глобальный PluginRegistry до и после каждого теста."""
    PluginRegistry.clear()
    yield
    PluginRegistry.clear()


@pytest.fixture()
def empty_dir(tmp_path: Path) -> Path:
    """Пустая директория для сканирования."""
    d = tmp_path / "plugins"
    d.mkdir()
    return d


@pytest.fixture()
def plugin_dir_with_one(tmp_path: Path) -> Path:
    """Директория с одним корректным plugin.py.

    Создаёт структуру:
        tmp_path/
            test_pkg/
                __init__.py
                plugins/
                    sample/
                        __init__.py
                        plugin.py   <-- содержит @register_plugin
    """
    pkg_root = tmp_path / "test_pkg"
    pkg_root.mkdir()
    (pkg_root / "__init__.py").touch()

    plugins_dir = pkg_root / "plugins"
    plugins_dir.mkdir()
    (plugins_dir / "__init__.py").touch()

    sample_dir = plugins_dir / "sample"
    sample_dir.mkdir()
    (sample_dir / "__init__.py").touch()

    plugin_file = sample_dir / "plugin.py"
    plugin_file.write_text(
        textwrap.dedent("""\
        from multiprocess_framework.modules.process_module.plugins.registry import (
            PluginRegistry,
            register_plugin,
        )
        from multiprocess_framework.modules.process_module.plugins.base import (
            ProcessModulePlugin,
        )

        @register_plugin("test_sample", category="testing", description="тестовый плагин")
        class SamplePlugin(ProcessModulePlugin):
            name = "test_sample"
            category = "testing"

            def setup(self):
                pass

            def process(self, data):
                return data

            def teardown(self):
                pass
        """),
        encoding="utf-8",
    )

    # Добавляем tmp_path в sys.path чтобы import работал
    sys.path.insert(0, str(tmp_path))
    yield plugins_dir

    # Cleanup sys.path и sys.modules
    sys.path.remove(str(tmp_path))
    keys_to_remove = [k for k in sys.modules if k.startswith("test_pkg")]
    for k in keys_to_remove:
        del sys.modules[k]


@pytest.fixture()
def plugin_dir_with_syntax_error(tmp_path: Path) -> Path:
    """Директория с plugin.py содержащим синтаксическую ошибку."""
    pkg_root = tmp_path / "bad_pkg"
    pkg_root.mkdir()
    (pkg_root / "__init__.py").touch()

    plugins_dir = pkg_root / "plugins"
    plugins_dir.mkdir()
    (plugins_dir / "__init__.py").touch()

    broken_dir = plugins_dir / "broken"
    broken_dir.mkdir()
    (broken_dir / "__init__.py").touch()

    plugin_file = broken_dir / "plugin.py"
    plugin_file.write_text(
        "def broken(\n  это синтаксическая ошибка!!!\n",
        encoding="utf-8",
    )

    sys.path.insert(0, str(tmp_path))
    yield plugins_dir

    sys.path.remove(str(tmp_path))
    keys_to_remove = [k for k in sys.modules if k.startswith("bad_pkg")]
    for k in keys_to_remove:
        del sys.modules[k]


# ---------------------------------------------------------------------------
# Тест 1: discover пустой директории
# ---------------------------------------------------------------------------


def test_discover_empty_dir(empty_dir: Path):
    """discover() на пустой директории -> PluginDiscoveryResult с пустым loaded."""
    pm = PluginManager(registry=PluginRegistry, paths=[empty_dir])
    result = pm.discover()

    assert isinstance(result, PluginDiscoveryResult)
    assert result.loaded == []
    assert result.failed == []
    assert result.new_plugins == []
    assert result.total == 0
    assert pm.is_discovered is True


# ---------------------------------------------------------------------------
# Тест 2: discover с одним plugin.py
# ---------------------------------------------------------------------------


def test_discover_with_one_plugin(plugin_dir_with_one: Path):
    """discover() с реальным plugin.py -> PluginDiscoveryResult с непустым loaded."""
    pm = PluginManager(registry=PluginRegistry, paths=[plugin_dir_with_one])
    result = pm.discover()

    assert isinstance(result, PluginDiscoveryResult)
    assert len(result.loaded) > 0, "Должен быть хотя бы один загруженный модуль"
    assert result.failed == []
    assert "test_sample" in result.new_plugins
    assert pm.is_discovered is True


# ---------------------------------------------------------------------------
# Тест 3: reload / rescan — добавление нового файла
# ---------------------------------------------------------------------------


def test_reload_discovers_new_plugin(plugin_dir_with_one: Path, tmp_path: Path):
    """reload() обнаруживает новый plugin.py добавленный после discover()."""
    pm = PluginManager(registry=PluginRegistry, paths=[plugin_dir_with_one])
    result1 = pm.discover()
    assert len(result1.loaded) == 1

    # Добавляем второй плагин
    new_dir = plugin_dir_with_one / "new_plugin"
    new_dir.mkdir()
    (new_dir / "__init__.py").touch()
    (new_dir / "plugin.py").write_text(
        textwrap.dedent("""\
        from multiprocess_framework.modules.process_module.plugins.registry import (
            PluginRegistry,
            register_plugin,
        )
        from multiprocess_framework.modules.process_module.plugins.base import (
            ProcessModulePlugin,
        )

        @register_plugin("test_new", category="testing", description="новый тестовый плагин")
        class NewPlugin(ProcessModulePlugin):
            name = "test_new"
            category = "testing"

            def setup(self):
                pass

            def process(self, data):
                return data

            def teardown(self):
                pass
        """),
        encoding="utf-8",
    )

    result2 = pm.reload()
    assert len(result2.loaded) > 0, "reload должен обнаружить новый плагин"
    assert "test_new" in result2.new_plugins

    # rescan — алиас reload, тоже работает
    result3 = pm.rescan()
    assert isinstance(result3, PluginDiscoveryResult)

    # cleanup
    keys_to_remove = [k for k in sys.modules if "new_plugin" in k]
    for k in keys_to_remove:
        del sys.modules[k]


# ---------------------------------------------------------------------------
# Тест 4: failed import — graceful error
# ---------------------------------------------------------------------------


def test_discover_syntax_error_graceful(plugin_dir_with_syntax_error: Path):
    """discover() с синтаксической ошибкой в plugin.py — не падает, ошибка в failed."""
    pm = PluginManager(registry=PluginRegistry, paths=[plugin_dir_with_syntax_error])
    result = pm.discover()

    assert isinstance(result, PluginDiscoveryResult)
    assert len(result.failed) > 0, "Должна быть хотя бы одна ошибка"
    assert result.loaded == []
    # Проверяем алиас errors
    assert result.errors == result.failed

    # Менеджер не упал
    assert pm.is_discovered is True


# ---------------------------------------------------------------------------
# Тест 5: list_discovered() формат
# ---------------------------------------------------------------------------


def test_list_discovered_format(plugin_dir_with_one: Path):
    """list_discovered() возвращает список dict'ов с правильными ключами."""
    pm = PluginManager(registry=PluginRegistry, paths=[plugin_dir_with_one])
    pm.discover()

    plugins = pm.list_discovered()
    assert isinstance(plugins, list)
    assert len(plugins) > 0

    plugin = plugins[0]
    expected_keys = {"name", "category", "description", "class_path", "inputs", "outputs"}
    assert set(plugin.keys()) == expected_keys
    assert plugin["name"] == "test_sample"
    assert plugin["category"] == "testing"


# ---------------------------------------------------------------------------
# Тест 6: isinstance(pm, BaseManager) — наследование
# ---------------------------------------------------------------------------


def test_isinstance_base_manager(empty_dir: Path):
    """PluginManager является наследником BaseManager и ObservableMixin."""
    pm = PluginManager(registry=PluginRegistry, paths=[empty_dir])

    assert isinstance(pm, BaseManager)
    assert isinstance(pm, ObservableMixin)
    assert pm.manager_name == "plugin_manager"


# ---------------------------------------------------------------------------
# Тест 7: get_stats / get_debug_info — формат
# ---------------------------------------------------------------------------


def test_get_stats_and_debug_info(empty_dir: Path):
    """get_stats() и get_debug_info() возвращают ожидаемые ключи."""
    pm = PluginManager(registry=PluginRegistry, paths=[empty_dir])

    stats = pm.get_stats()
    assert "manager_name" in stats
    assert stats["manager_name"] == "plugin_manager"
    assert "is_discovered" in stats
    assert "loaded_modules_count" in stats
    assert "registry_size" in stats
    assert "discover_count" in stats

    debug = pm.get_debug_info()
    assert "loaded_modules" in debug
    assert "plugin_paths" in debug
    assert "registry_plugins" in debug


# ---------------------------------------------------------------------------
# Тест 8: initialize / shutdown — жизненный цикл
# ---------------------------------------------------------------------------


def test_lifecycle_initialize_shutdown(empty_dir: Path):
    """initialize() и shutdown() корректно управляют состоянием."""
    pm = PluginManager(registry=PluginRegistry, paths=[empty_dir])

    assert pm.is_initialized is False

    assert pm.initialize() is True
    assert pm.is_initialized is True

    # Повторный вызов — idempotent
    assert pm.initialize() is True

    assert pm.shutdown() is True
    assert pm.is_initialized is False


# ---------------------------------------------------------------------------
# Тест 9: несуществующая директория
# ---------------------------------------------------------------------------


def test_discover_nonexistent_directory(tmp_path: Path):
    """discover() с несуществующей директорией — не падает, пустой результат."""
    nonexistent = tmp_path / "does_not_exist"
    pm = PluginManager(registry=PluginRegistry, paths=[nonexistent])
    result = pm.discover()

    assert isinstance(result, PluginDiscoveryResult)
    assert result.loaded == []
    assert result.failed == []


# ---------------------------------------------------------------------------
# Тест 10: создание без менеджеров (logger=None)
# ---------------------------------------------------------------------------


def test_create_without_managers(empty_dir: Path):
    """PluginManager(registry, paths, logger=None) создаётся без ошибок."""
    pm = PluginManager(
        registry=PluginRegistry,
        paths=[empty_dir],
        logger=None,
        stats=None,
        error=None,
    )
    assert pm is not None
    assert pm.manager_name == "plugin_manager"
    # Вызовы логирования не падают (silent fallback ObservableMixin)
    pm._log_info("тест без логгера")
    pm._log_warning("тест без логгера")
