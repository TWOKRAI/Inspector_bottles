"""Тесты SettingsTab — пилотный таб Settings end-to-end.

Использует monkeypatch для перенаправления SETTINGS_PATH и UI_PREFS_PATH
в tmp_path, qtbot для Qt-виджетов.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import yaml
import pytest

from multiprocess_prototype_2.config.schemas import SystemConfig
from multiprocess_prototype_2.frontend.app_context import AppContext
from multiprocess_prototype_2.frontend.bridge.command_sender import CommandSender


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------

def _make_mock_ctx() -> AppContext:
    """Создать тестовый AppContext с моками."""
    process = MagicMock()
    process.name = "gui_test"
    process._bridge = MagicMock()
    command_sender = CommandSender(process)
    return AppContext(
        process=process,
        command_sender=command_sender,
        bridge=process._bridge,
    )


@pytest.fixture
def ctx() -> AppContext:
    """Тестовый AppContext."""
    return _make_mock_ctx()


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
# Тесты SettingsTab
# ---------------------------------------------------------------------------


class TestSettingsTab:
    """Тесты SettingsTab (требуют qtbot для Qt-виджетов)."""

    def test_renders_all_sections(
        self, qtbot, ctx, settings_yaml, prefs_yaml, monkeypatch
    ) -> None:
        """Все 5 групп (system/camera/processing/display/storage) присутствуют."""
        import multiprocess_prototype_2.frontend.widgets.tabs.settings.yaml_io as yaml_io_mod
        import multiprocess_prototype_2.frontend.prefs.store as store_mod
        monkeypatch.setattr(yaml_io_mod, "SETTINGS_PATH", settings_yaml)
        monkeypatch.setattr(store_mod, "UI_PREFS_PATH", prefs_yaml)

        from multiprocess_prototype_2.frontend.widgets.tabs.settings.tab import SettingsTab
        tab = SettingsTab(ctx)
        qtbot.addWidget(tab)

        # Проверяем что все 5 секций представлены в field_editors
        editors = tab.field_editors()
        keys = set(editors.keys())
        sections = {k.split(".")[0] for k in keys}
        assert "system" in sections
        assert "camera" in sections
        assert "processing" in sections
        assert "display" in sections
        assert "storage" in sections

    def test_initial_values_match_yaml(
        self, qtbot, ctx, tmp_path, prefs_yaml, monkeypatch
    ) -> None:
        """Значения редакторов совпадают с тем что в YAML."""
        # Записываем YAML с нестандартным значением
        path = tmp_path / "system.yaml"
        cfg = SystemConfig()
        cfg.camera.fps = 60
        data = cfg.model_dump()
        path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")

        import multiprocess_prototype_2.frontend.widgets.tabs.settings.yaml_io as yaml_io_mod
        import multiprocess_prototype_2.frontend.prefs.store as store_mod
        monkeypatch.setattr(yaml_io_mod, "SETTINGS_PATH", path)
        monkeypatch.setattr(store_mod, "UI_PREFS_PATH", prefs_yaml)

        from multiprocess_prototype_2.frontend.widgets.tabs.settings.tab import SettingsTab
        tab = SettingsTab(ctx)
        qtbot.addWidget(tab)

        editors = tab.field_editors()
        fps_editor = editors.get("camera.fps")
        assert fps_editor is not None
        assert fps_editor.getter() == 60

    def test_change_marks_dirty(
        self, qtbot, ctx, settings_yaml, prefs_yaml, monkeypatch
    ) -> None:
        """Изменение значения редактора → is_dirty() returns True."""
        import multiprocess_prototype_2.frontend.widgets.tabs.settings.yaml_io as yaml_io_mod
        import multiprocess_prototype_2.frontend.prefs.store as store_mod
        monkeypatch.setattr(yaml_io_mod, "SETTINGS_PATH", settings_yaml)
        monkeypatch.setattr(store_mod, "UI_PREFS_PATH", prefs_yaml)

        from multiprocess_prototype_2.frontend.widgets.tabs.settings.tab import SettingsTab
        tab = SettingsTab(ctx)
        qtbot.addWidget(tab)

        assert not tab.is_dirty()

        # Изменяем значение через editor.setter (имитируем пользовательский ввод)
        editors = tab.field_editors()
        fps_editor = editors.get("camera.fps")
        assert fps_editor is not None

        # Меняем значение через setter — это само по себе не эмитит сигнал.
        # Напрямую устанавливаем значение через виджет — это эмитит change_signal.
        from PySide6.QtWidgets import QSpinBox
        if isinstance(fps_editor.widget, QSpinBox):
            # setValue эмитит valueChanged
            fps_editor.widget.setValue(fps_editor.widget.value() + 1)
        else:
            # Для других виджетов — используем setter + change_signal с правильным аргументом
            fps_editor.setter(fps_editor.getter())

        assert tab.is_dirty()

    def test_save_persists_to_yaml(
        self, qtbot, ctx, settings_yaml, prefs_yaml, monkeypatch
    ) -> None:
        """Изменение → save() → YAML обновлён на диске."""
        import multiprocess_prototype_2.frontend.widgets.tabs.settings.yaml_io as yaml_io_mod
        import multiprocess_prototype_2.frontend.prefs.store as store_mod
        monkeypatch.setattr(yaml_io_mod, "SETTINGS_PATH", settings_yaml)
        monkeypatch.setattr(store_mod, "UI_PREFS_PATH", prefs_yaml)

        from multiprocess_prototype_2.frontend.widgets.tabs.settings.tab import SettingsTab
        tab = SettingsTab(ctx)
        qtbot.addWidget(tab)

        # Меняем fps через setter
        editors = tab.field_editors()
        fps_editor = editors.get("camera.fps")
        fps_editor.setter(45)

        result = tab.save()
        assert result is True
        assert not tab.is_dirty()

        # Проверяем YAML на диске
        raw = yaml.safe_load(settings_yaml.read_text(encoding="utf-8"))
        assert raw["camera"]["fps"] == 45

    def test_save_rejects_invalid_value(
        self, qtbot, ctx, settings_yaml, prefs_yaml, monkeypatch
    ) -> None:
        """Невалидное значение → save() returns False, YAML не меняется."""
        import multiprocess_prototype_2.frontend.widgets.tabs.settings.yaml_io as yaml_io_mod
        import multiprocess_prototype_2.frontend.prefs.store as store_mod
        monkeypatch.setattr(yaml_io_mod, "SETTINGS_PATH", settings_yaml)
        monkeypatch.setattr(store_mod, "UI_PREFS_PATH", prefs_yaml)

        original_content = settings_yaml.read_text(encoding="utf-8")

        from multiprocess_prototype_2.frontend.widgets.tabs.settings.tab import SettingsTab
        tab = SettingsTab(ctx)
        qtbot.addWidget(tab)

        # Устанавливаем невалидное значение stop_timeout > max=30
        editors = tab.field_editors()
        stop_timeout_editor = editors.get("system.stop_timeout")
        if stop_timeout_editor is not None:
            # Подменяем getter чтобы вернуть невалидное значение
            stop_timeout_editor.getter = lambda: 999.0

        result = tab.save()
        assert result is False

        # YAML не должен измениться
        assert settings_yaml.read_text(encoding="utf-8") == original_content

    def test_reload_reverts_changes(
        self, qtbot, ctx, settings_yaml, prefs_yaml, monkeypatch
    ) -> None:
        """Изменение → reload() → editors показывают on-disk значения."""
        import multiprocess_prototype_2.frontend.widgets.tabs.settings.yaml_io as yaml_io_mod
        import multiprocess_prototype_2.frontend.prefs.store as store_mod
        monkeypatch.setattr(yaml_io_mod, "SETTINGS_PATH", settings_yaml)
        monkeypatch.setattr(store_mod, "UI_PREFS_PATH", prefs_yaml)

        from multiprocess_prototype_2.frontend.widgets.tabs.settings.tab import SettingsTab
        tab = SettingsTab(ctx)
        qtbot.addWidget(tab)

        editors = tab.field_editors()
        fps_editor = editors.get("camera.fps")
        original_fps = fps_editor.getter()

        # Меняем
        fps_editor.setter(99)
        assert fps_editor.getter() == 99

        # Reload
        tab.reload()
        assert fps_editor.getter() == original_fps
        assert not tab.is_dirty()

    def test_signal_emitted_on_success(
        self, qtbot, ctx, settings_yaml, prefs_yaml, monkeypatch
    ) -> None:
        """settings_saved эмитится при успешном save()."""
        import multiprocess_prototype_2.frontend.widgets.tabs.settings.yaml_io as yaml_io_mod
        import multiprocess_prototype_2.frontend.prefs.store as store_mod
        monkeypatch.setattr(yaml_io_mod, "SETTINGS_PATH", settings_yaml)
        monkeypatch.setattr(store_mod, "UI_PREFS_PATH", prefs_yaml)

        from multiprocess_prototype_2.frontend.widgets.tabs.settings.tab import SettingsTab
        tab = SettingsTab(ctx)
        qtbot.addWidget(tab)

        with qtbot.waitSignal(tab.settings_saved, timeout=2000):
            tab.save()

    def test_factory_create_returns_settings_tab(
        self, qtbot, ctx, settings_yaml, prefs_yaml, monkeypatch
    ) -> None:
        """SettingsTab.create(ctx) возвращает экземпляр SettingsTab."""
        import multiprocess_prototype_2.frontend.widgets.tabs.settings.yaml_io as yaml_io_mod
        import multiprocess_prototype_2.frontend.prefs.store as store_mod
        monkeypatch.setattr(yaml_io_mod, "SETTINGS_PATH", settings_yaml)
        monkeypatch.setattr(store_mod, "UI_PREFS_PATH", prefs_yaml)

        from multiprocess_prototype_2.frontend.widgets.tabs.settings.tab import SettingsTab
        tab = SettingsTab.create(ctx)
        qtbot.addWidget(tab)

        assert isinstance(tab, SettingsTab)

    def test_view_mode_toggle_persists_to_prefs(
        self, qtbot, ctx, settings_yaml, prefs_yaml, monkeypatch
    ) -> None:
        """Переключение режима → ui_prefs.yaml содержит settings.view_mode: table."""
        import multiprocess_prototype_2.frontend.widgets.tabs.settings.yaml_io as yaml_io_mod
        import multiprocess_prototype_2.frontend.prefs.store as store_mod
        monkeypatch.setattr(yaml_io_mod, "SETTINGS_PATH", settings_yaml)
        monkeypatch.setattr(store_mod, "UI_PREFS_PATH", prefs_yaml)

        from multiprocess_prototype_2.frontend.widgets.tabs.settings.tab import SettingsTab
        from multiprocess_prototype_2.frontend.forms import ViewMode
        tab = SettingsTab(ctx)
        qtbot.addWidget(tab)

        # Переключить в table через RegisterView
        tab._view.set_mode(ViewMode.TABLE)

        # Проверить что prefs сохранены
        from multiprocess_prototype_2.frontend.prefs.store import UiPrefsStore
        prefs = UiPrefsStore(path=prefs_yaml)
        assert prefs.get("settings.view_mode") == "table"

    def test_view_mode_restored_from_prefs(
        self, qtbot, ctx, settings_yaml, tmp_path, monkeypatch
    ) -> None:
        """Записать settings.view_mode: table → tab открывается в Table режиме."""
        prefs_path = tmp_path / "ui_prefs.yaml"
        # Предзаписываем prefs
        prefs_path.write_text(
            yaml.safe_dump({"settings": {"view_mode": "table"}}, allow_unicode=True),
            encoding="utf-8",
        )

        import multiprocess_prototype_2.frontend.widgets.tabs.settings.yaml_io as yaml_io_mod
        import multiprocess_prototype_2.frontend.prefs.store as store_mod
        monkeypatch.setattr(yaml_io_mod, "SETTINGS_PATH", settings_yaml)
        monkeypatch.setattr(store_mod, "UI_PREFS_PATH", prefs_path)

        from multiprocess_prototype_2.frontend.widgets.tabs.settings.tab import SettingsTab
        from multiprocess_prototype_2.frontend.forms import ViewMode
        tab = SettingsTab(ctx)
        qtbot.addWidget(tab)

        assert tab.view_mode() == ViewMode.TABLE

    def test_no_crash_when_yaml_missing(
        self, qtbot, ctx, tmp_path, prefs_yaml, monkeypatch
    ) -> None:
        """Если YAML отсутствует — tab создаётся без исключений (defaults)."""
        missing_path = tmp_path / "nonexistent.yaml"

        import multiprocess_prototype_2.frontend.widgets.tabs.settings.yaml_io as yaml_io_mod
        import multiprocess_prototype_2.frontend.prefs.store as store_mod
        monkeypatch.setattr(yaml_io_mod, "SETTINGS_PATH", missing_path)
        monkeypatch.setattr(store_mod, "UI_PREFS_PATH", prefs_yaml)

        from multiprocess_prototype_2.frontend.widgets.tabs.settings.tab import SettingsTab
        tab = SettingsTab(ctx)
        qtbot.addWidget(tab)

        # Должен создаться с defaults
        assert tab is not None
        editors = tab.field_editors()
        assert len(editors) > 0

    def test_group_titles_contain_russian_names(
        self, qtbot, ctx, settings_yaml, prefs_yaml, monkeypatch
    ) -> None:
        """RegisterView создаётся с русскими category_titles."""
        import multiprocess_prototype_2.frontend.widgets.tabs.settings.yaml_io as yaml_io_mod
        import multiprocess_prototype_2.frontend.prefs.store as store_mod
        monkeypatch.setattr(yaml_io_mod, "SETTINGS_PATH", settings_yaml)
        monkeypatch.setattr(store_mod, "UI_PREFS_PATH", prefs_yaml)

        from multiprocess_prototype_2.frontend.widgets.tabs.settings.tab import (
            SettingsTab,
            _SECTION_TITLES,
        )
        tab = SettingsTab(ctx)
        qtbot.addWidget(tab)

        # Проверяем что _SECTION_TITLES содержит русские названия
        assert _SECTION_TITLES["system"] == "Система"
        assert _SECTION_TITLES["camera"] == "Камера"
        assert _SECTION_TITLES["processing"] == "Обработка"
        assert _SECTION_TITLES["display"] == "Дисплей"
        assert _SECTION_TITLES["storage"] == "Хранение"
