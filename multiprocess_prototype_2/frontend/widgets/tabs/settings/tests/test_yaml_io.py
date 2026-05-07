"""Тесты yaml_io — загрузка/сохранение/schema_to_field_infos для system.yaml."""

from __future__ import annotations

from pathlib import Path

import yaml
import pytest

from multiprocess_prototype_2.config.schemas import SystemConfig
from multiprocess_prototype_2.frontend.widgets.tabs.settings.yaml_io import (
    load_settings,
    save_settings,
    schema_to_field_infos,
)


class TestLoadSettings:
    """Тесты load_settings()."""

    def test_load_returns_defaults_when_file_missing(self, tmp_path: Path) -> None:
        """Если файл отсутствует — возвращаются defaults SystemConfig."""
        missing_path = tmp_path / "nonexistent.yaml"
        cfg = load_settings(missing_path)

        assert isinstance(cfg, SystemConfig)
        # Defaults из схемы
        assert cfg.system.stop_timeout == 5.0
        assert cfg.camera.fps == 25
        assert cfg.processing.worker_pool_size == 0

    def test_load_round_trip(self, tmp_path: Path) -> None:
        """Записать SystemConfig → load → идентичный объект."""
        path = tmp_path / "system.yaml"
        cfg_original = SystemConfig()
        # Изменяем несколько значений
        cfg_original.system.stop_timeout = 10.0
        cfg_original.camera.fps = 30
        save_settings(cfg_original, path)

        cfg_loaded = load_settings(path)

        assert cfg_loaded.system.stop_timeout == 10.0
        assert cfg_loaded.camera.fps == 30
        assert cfg_loaded.camera.resolution_width == cfg_original.camera.resolution_width

    def test_load_with_partial_yaml(self, tmp_path: Path) -> None:
        """Частичный YAML — недостающие поля заполняются defaults."""
        path = tmp_path / "system.yaml"
        path.write_text("system:\n  stop_timeout: 15.0\n", encoding="utf-8")

        cfg = load_settings(path)

        assert cfg.system.stop_timeout == 15.0
        # Остальные поля — defaults
        assert cfg.camera.fps == 25


class TestSaveSettings:
    """Тесты save_settings()."""

    def test_save_atomic_writes_to_tmp_first(self, tmp_path: Path) -> None:
        """После успешного save() .tmp файла нет, целевой файл создан."""
        path = tmp_path / "system.yaml"
        cfg = SystemConfig()
        save_settings(cfg, path)

        # .tmp не должен существовать после успешного save
        tmp_file = path.with_suffix(".yaml.tmp")
        assert not tmp_file.exists()
        assert path.exists()

    def test_save_produces_valid_yaml(self, tmp_path: Path) -> None:
        """save() создаёт валидный YAML, читаемый yaml.safe_load."""
        path = tmp_path / "system.yaml"
        cfg = SystemConfig()
        cfg.system.log_dir = "/tmp/logs"
        save_settings(cfg, path)

        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(raw, dict)
        assert "system" in raw
        assert raw["system"]["log_dir"] == "/tmp/logs"

    def test_save_allows_unicode(self, tmp_path: Path) -> None:
        """allow_unicode=True: кириллица не эскейпится."""
        path = tmp_path / "system.yaml"
        cfg = SystemConfig()
        cfg.system.log_dir = "путь/к/логам"
        save_settings(cfg, path)

        content = path.read_text(encoding="utf-8")
        # Кириллица присутствует буквально, не как \uXXXX
        assert "путь/к/логам" in content


class TestSchemaToFieldInfos:
    """Тесты schema_to_field_infos()."""

    def test_covers_all_five_sections(self) -> None:
        """Результат содержит поля из всех 5 секций."""
        cfg = SystemConfig()
        field_infos = schema_to_field_infos(cfg)

        categories = {fi.category for fi in field_infos}
        assert "system" in categories
        assert "camera" in categories
        assert "processing" in categories
        assert "display" in categories
        assert "storage" in categories

    def test_plugin_name_equals_section_name(self) -> None:
        """plugin_name каждого FieldInfo совпадает с именем секции (для ключей editors)."""
        cfg = SystemConfig()
        field_infos = schema_to_field_infos(cfg)

        for fi in field_infos:
            assert fi.plugin_name in ("system", "camera", "processing", "display", "storage")
            assert fi.plugin_name == fi.category

    def test_editor_keys_are_section_dot_field(self) -> None:
        """Ключи editors в RegisterView будут вида 'section.field'."""
        cfg = SystemConfig()
        field_infos = schema_to_field_infos(cfg)

        keys = [f"{fi.plugin_name}.{fi.field_name}" for fi in field_infos]
        # Проверяем известные поля
        assert "system.stop_timeout" in keys
        assert "camera.fps" in keys
        assert "storage.db_path" in keys

    def test_non_empty_list(self) -> None:
        """schema_to_field_infos не возвращает пустой список."""
        cfg = SystemConfig()
        field_infos = schema_to_field_infos(cfg)

        assert len(field_infos) > 0
