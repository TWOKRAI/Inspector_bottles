"""Тесты SettingsTab — Task D.5 (Phase D): таб мигрирован на AppServices DI.

Использует make_test_app_services() builder вместо AppContext (zero MagicMock).
monkeypatch перенаправляет SETTINGS_PATH и UI_PREFS_PATH в tmp_path.
qtbot нужен для Qt-виджетов.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import yaml
import pytest

from multiprocess_prototype.backend.config.schemas import SystemConfig
from multiprocess_prototype.domain.tests.conftest import make_test_app_services


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------


@pytest.fixture
def services():
    """Тестовый AppServices через builder (zero MagicMock)."""
    return make_test_app_services()


@pytest.fixture
def settings_yaml(tmp_path: Path) -> Path:
    """Создать system.yaml с дефолтными значениями в tmp_path."""
    path = tmp_path / "system.yaml"
    cfg = SystemConfig()
    data = cfg.model_dump()
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def prefs_yaml(tmp_path: Path) -> Path:
    """Путь к ui_prefs.yaml в tmp_path (может не существовать)."""
    return tmp_path / "ui_prefs.yaml"


# ---------------------------------------------------------------------------
# Вспомогательный helper для тестов
# ---------------------------------------------------------------------------


def _sys(tab):
    """Прямой доступ к SystemSection (после Phase 7.1)."""
    return tab.presenter.section("system_settings")


# ---------------------------------------------------------------------------
# Тесты SettingsTab (D.5 — AppServices DI)
# ---------------------------------------------------------------------------


class TestSettingsTabWithAppServices:
    """Тесты SettingsTab (требуют qtbot для Qt-виджетов). Task D.5."""

    def test_constructs_with_app_services(self, qtbot, services, settings_yaml, prefs_yaml, monkeypatch) -> None:
        """Smoke: SettingsTab(services) создаётся без исключений."""
        import multiprocess_prototype.frontend.widgets.tabs.settings.yaml_io as yaml_io_mod
        import multiprocess_prototype.frontend.prefs.store as store_mod

        monkeypatch.setattr(yaml_io_mod, "SETTINGS_PATH", settings_yaml)
        monkeypatch.setattr(store_mod, "UI_PREFS_PATH", prefs_yaml)

        from multiprocess_prototype.frontend.widgets.tabs.settings.tab import SettingsTab

        tab = SettingsTab(services)
        qtbot.addWidget(tab)
        assert tab is not None

    def test_renders_all_sections(self, qtbot, services, settings_yaml, prefs_yaml, monkeypatch) -> None:
        """Все 5 групп (system/camera/processing/display/storage) присутствуют."""
        import multiprocess_prototype.frontend.widgets.tabs.settings.yaml_io as yaml_io_mod
        import multiprocess_prototype.frontend.prefs.store as store_mod

        monkeypatch.setattr(yaml_io_mod, "SETTINGS_PATH", settings_yaml)
        monkeypatch.setattr(store_mod, "UI_PREFS_PATH", prefs_yaml)

        from multiprocess_prototype.frontend.widgets.tabs.settings.tab import SettingsTab

        tab = SettingsTab(services)
        qtbot.addWidget(tab)

        # Проверяем что все 5 секций представлены в field_editors
        editors = _sys(tab).field_editors()
        keys = set(editors.keys())
        sections = {k.split(".")[0] for k in keys}
        assert "system" in sections
        assert "camera" in sections
        assert "processing" in sections
        assert "display" in sections
        assert "storage" in sections

    def test_initial_values_match_yaml(self, qtbot, services, tmp_path, prefs_yaml, monkeypatch) -> None:
        """Значения редакторов совпадают с тем что в YAML."""
        path = tmp_path / "system.yaml"
        cfg = SystemConfig()
        cfg.camera.fps = 60
        data = cfg.model_dump()
        path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")

        import multiprocess_prototype.frontend.widgets.tabs.settings.yaml_io as yaml_io_mod
        import multiprocess_prototype.frontend.prefs.store as store_mod

        monkeypatch.setattr(yaml_io_mod, "SETTINGS_PATH", path)
        monkeypatch.setattr(store_mod, "UI_PREFS_PATH", prefs_yaml)

        from multiprocess_prototype.frontend.widgets.tabs.settings.tab import SettingsTab

        tab = SettingsTab(services)
        qtbot.addWidget(tab)

        editors = _sys(tab).field_editors()
        fps_editor = editors.get("camera.fps")
        assert fps_editor is not None
        assert fps_editor.getter() == 60

    def test_change_marks_dirty(self, qtbot, services, settings_yaml, prefs_yaml, monkeypatch) -> None:
        """Изменение значения редактора → is_dirty() returns True."""
        import multiprocess_prototype.frontend.widgets.tabs.settings.yaml_io as yaml_io_mod
        import multiprocess_prototype.frontend.prefs.store as store_mod

        monkeypatch.setattr(yaml_io_mod, "SETTINGS_PATH", settings_yaml)
        monkeypatch.setattr(store_mod, "UI_PREFS_PATH", prefs_yaml)

        from multiprocess_prototype.frontend.widgets.tabs.settings.tab import SettingsTab

        tab = SettingsTab(services)
        qtbot.addWidget(tab)

        assert not _sys(tab).presenter.is_dirty()

        editors = _sys(tab).field_editors()
        fps_editor = editors.get("camera.fps")
        assert fps_editor is not None

        from PySide6.QtWidgets import QSpinBox

        if isinstance(fps_editor.widget, QSpinBox):
            fps_editor.widget.setValue(fps_editor.widget.value() + 1)
        else:
            fps_editor.setter(fps_editor.getter())

        assert _sys(tab).presenter.is_dirty()

    def test_save_persists_to_yaml(self, qtbot, services, settings_yaml, prefs_yaml, monkeypatch) -> None:
        """Изменение → save() → YAML обновлён на диске."""
        import multiprocess_prototype.frontend.widgets.tabs.settings.yaml_io as yaml_io_mod
        import multiprocess_prototype.frontend.prefs.store as store_mod

        monkeypatch.setattr(yaml_io_mod, "SETTINGS_PATH", settings_yaml)
        monkeypatch.setattr(store_mod, "UI_PREFS_PATH", prefs_yaml)

        from multiprocess_prototype.frontend.widgets.tabs.settings.tab import SettingsTab

        tab = SettingsTab(services)
        qtbot.addWidget(tab)

        editors = _sys(tab).field_editors()
        fps_editor = editors.get("camera.fps")
        fps_editor.setter(45)

        result = _sys(tab).presenter.save()
        assert result is True
        assert not _sys(tab).presenter.is_dirty()

        raw = yaml.safe_load(settings_yaml.read_text(encoding="utf-8"))
        assert raw["camera"]["fps"] == 45

    def test_save_rejects_invalid_value(self, qtbot, services, settings_yaml, prefs_yaml, monkeypatch) -> None:
        """Невалидное значение → save() returns False, YAML не меняется."""
        import multiprocess_prototype.frontend.widgets.tabs.settings.yaml_io as yaml_io_mod
        import multiprocess_prototype.frontend.prefs.store as store_mod

        monkeypatch.setattr(yaml_io_mod, "SETTINGS_PATH", settings_yaml)
        monkeypatch.setattr(store_mod, "UI_PREFS_PATH", prefs_yaml)

        original_content = settings_yaml.read_text(encoding="utf-8")

        from multiprocess_prototype.frontend.widgets.tabs.settings.tab import SettingsTab

        tab = SettingsTab(services)
        qtbot.addWidget(tab)

        editors = _sys(tab).field_editors()
        stop_timeout_editor = editors.get("system.stop_timeout")
        if stop_timeout_editor is not None:
            stop_timeout_editor.getter = lambda: 999.0

        result = _sys(tab).presenter.save()
        assert result is False
        assert settings_yaml.read_text(encoding="utf-8") == original_content

    def test_reload_reverts_changes(self, qtbot, services, settings_yaml, prefs_yaml, monkeypatch) -> None:
        """Изменение → reload() → editors показывают on-disk значения."""
        import multiprocess_prototype.frontend.widgets.tabs.settings.yaml_io as yaml_io_mod
        import multiprocess_prototype.frontend.prefs.store as store_mod

        monkeypatch.setattr(yaml_io_mod, "SETTINGS_PATH", settings_yaml)
        monkeypatch.setattr(store_mod, "UI_PREFS_PATH", prefs_yaml)

        from multiprocess_prototype.frontend.widgets.tabs.settings.tab import SettingsTab

        tab = SettingsTab(services)
        qtbot.addWidget(tab)

        editors = _sys(tab).field_editors()
        fps_editor = editors.get("camera.fps")
        original_fps = fps_editor.getter()

        fps_editor.setter(99)
        assert fps_editor.getter() == 99

        _sys(tab).presenter.reload()
        assert fps_editor.getter() == original_fps
        assert not _sys(tab).presenter.is_dirty()

    def test_signal_emitted_on_success(self, qtbot, services, settings_yaml, prefs_yaml, monkeypatch) -> None:
        """settings_saved эмитится при успешном save()."""
        import multiprocess_prototype.frontend.widgets.tabs.settings.yaml_io as yaml_io_mod
        import multiprocess_prototype.frontend.prefs.store as store_mod

        monkeypatch.setattr(yaml_io_mod, "SETTINGS_PATH", settings_yaml)
        monkeypatch.setattr(store_mod, "UI_PREFS_PATH", prefs_yaml)

        from multiprocess_prototype.frontend.widgets.tabs.settings.tab import SettingsTab

        tab = SettingsTab(services)
        qtbot.addWidget(tab)

        with qtbot.waitSignal(tab.settings_saved, timeout=2000):
            _sys(tab).presenter.save()

    def test_factory_create_from_services_returns_settings_tab(
        self, qtbot, services, settings_yaml, prefs_yaml, monkeypatch
    ) -> None:
        """SettingsTab.create_from_services(services) возвращает экземпляр SettingsTab."""
        import multiprocess_prototype.frontend.widgets.tabs.settings.yaml_io as yaml_io_mod
        import multiprocess_prototype.frontend.prefs.store as store_mod

        monkeypatch.setattr(yaml_io_mod, "SETTINGS_PATH", settings_yaml)
        monkeypatch.setattr(store_mod, "UI_PREFS_PATH", prefs_yaml)

        from multiprocess_prototype.frontend.widgets.tabs.settings.tab import SettingsTab

        tab = SettingsTab.create_from_services(services)
        qtbot.addWidget(tab)
        assert isinstance(tab, SettingsTab)

    def test_view_mode_toggle_persists_to_prefs(self, qtbot, services, settings_yaml, prefs_yaml, monkeypatch) -> None:
        """Переключение режима → ui_prefs.yaml содержит settings.view_mode: table."""
        import multiprocess_prototype.frontend.widgets.tabs.settings.yaml_io as yaml_io_mod
        import multiprocess_prototype.frontend.prefs.store as store_mod

        monkeypatch.setattr(yaml_io_mod, "SETTINGS_PATH", settings_yaml)
        monkeypatch.setattr(store_mod, "UI_PREFS_PATH", prefs_yaml)

        from multiprocess_prototype.frontend.widgets.tabs.settings.tab import SettingsTab
        from multiprocess_prototype.frontend.forms import ViewMode

        tab = SettingsTab(services)
        qtbot.addWidget(tab)

        _sys(tab).register_view.set_mode(ViewMode.TABLE)

        from multiprocess_prototype.frontend.prefs.store import UiPrefsStore

        prefs = UiPrefsStore(path=prefs_yaml)
        assert prefs.get("settings.view_mode") == "table"

    def test_view_mode_restored_from_prefs(self, qtbot, services, settings_yaml, tmp_path, monkeypatch) -> None:
        """Записать settings.view_mode: table → tab открывается в Table режиме."""
        prefs_path = tmp_path / "ui_prefs.yaml"
        prefs_path.write_text(
            yaml.safe_dump({"settings": {"view_mode": "table"}}, allow_unicode=True),
            encoding="utf-8",
        )

        import multiprocess_prototype.frontend.widgets.tabs.settings.yaml_io as yaml_io_mod
        import multiprocess_prototype.frontend.prefs.store as store_mod

        monkeypatch.setattr(yaml_io_mod, "SETTINGS_PATH", settings_yaml)
        monkeypatch.setattr(store_mod, "UI_PREFS_PATH", prefs_path)

        from multiprocess_prototype.frontend.widgets.tabs.settings.tab import SettingsTab
        from multiprocess_prototype.frontend.forms import ViewMode

        tab = SettingsTab(services)
        qtbot.addWidget(tab)
        assert _sys(tab).view_mode() == ViewMode.TABLE

    def test_no_crash_when_yaml_missing(self, qtbot, services, tmp_path, prefs_yaml, monkeypatch) -> None:
        """Если YAML отсутствует — tab создаётся без исключений (defaults)."""
        missing_path = tmp_path / "nonexistent.yaml"

        import multiprocess_prototype.frontend.widgets.tabs.settings.yaml_io as yaml_io_mod
        import multiprocess_prototype.frontend.prefs.store as store_mod

        monkeypatch.setattr(yaml_io_mod, "SETTINGS_PATH", missing_path)
        monkeypatch.setattr(store_mod, "UI_PREFS_PATH", prefs_yaml)

        from multiprocess_prototype.frontend.widgets.tabs.settings.tab import SettingsTab

        tab = SettingsTab(services)
        qtbot.addWidget(tab)

        assert tab is not None
        editors = _sys(tab).field_editors()
        assert len(editors) > 0

    def test_group_titles_contain_russian_names(self, qtbot, services, settings_yaml, prefs_yaml, monkeypatch) -> None:
        """RegisterView создаётся с русскими category_titles."""
        import multiprocess_prototype.frontend.widgets.tabs.settings.yaml_io as yaml_io_mod
        import multiprocess_prototype.frontend.prefs.store as store_mod

        monkeypatch.setattr(yaml_io_mod, "SETTINGS_PATH", settings_yaml)
        monkeypatch.setattr(store_mod, "UI_PREFS_PATH", prefs_yaml)

        from multiprocess_prototype.frontend.widgets.tabs.settings.tab import SettingsTab
        from multiprocess_prototype.frontend.widgets.tabs.settings.system.section import _SECTION_TITLES

        tab = SettingsTab(services)
        qtbot.addWidget(tab)

        assert _SECTION_TITLES["system"] == "Система"
        assert _SECTION_TITLES["camera"] == "Камера"
        assert _SECTION_TITLES["processing"] == "Обработка"
        assert _SECTION_TITLES["display"] == "Дисплей"
        assert _SECTION_TITLES["storage"] == "Хранение"

    def test_no_extras_deprecation_warnings(self, qtbot, services, settings_yaml, prefs_yaml, monkeypatch) -> None:
        """Settings tab не использует ctx.extras — нет DeprecationWarning от extras."""
        import multiprocess_prototype.frontend.widgets.tabs.settings.yaml_io as yaml_io_mod
        import multiprocess_prototype.frontend.prefs.store as store_mod

        monkeypatch.setattr(yaml_io_mod, "SETTINGS_PATH", settings_yaml)
        monkeypatch.setattr(store_mod, "UI_PREFS_PATH", prefs_yaml)

        from multiprocess_prototype.frontend.widgets.tabs.settings.tab import SettingsTab

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            tab = SettingsTab(services)
            qtbot.addWidget(tab)

        extras_warnings = [
            x for x in w if issubclass(x.category, DeprecationWarning) and "ctx.extras" in str(x.message)
        ]
        assert extras_warnings == [], f"Settings tab всё ещё использует ctx.extras: {extras_warnings}"
