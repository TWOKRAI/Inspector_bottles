# -*- coding: utf-8 -*-
"""Тесты сохранения pipeline-графа в рецепт через PipelinePresenter.save_to_active_recipe.
Task E.1: мигрировано на AppServices. RecipeManager bridge через adapter._rm.

Запуск:
    python -m pytest multiprocess_prototype/frontend/widgets/tabs/pipeline/tests/test_save_recipe.py -v
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import yaml

from multiprocess_prototype.frontend.widgets.tabs.pipeline.presenter import (
    PipelinePresenter,
)

from ._helpers import make_pipeline_services


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------


def _make_recipe_yaml(slug: str = "test_recipe") -> dict:
    """Создать минимальный v2-рецепт в формате RecipeEngine."""
    return {
        "meta": {
            "name": slug,
            "description": "",
            "version": 2,
            "created_at": "2026-05-25T00:00:00+00:00",
        },
        "data": {
            "active_services": ["camera_service"],
        },
    }


def _write_recipe_file(recipes_dir: Path, slug: str) -> Path:
    """Записать тестовый YAML-файл рецепта в директорию."""
    data = _make_recipe_yaml(slug)
    path = recipes_dir / f"{slug}.yaml"
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
    return path


def _make_recipe_manager_mock(recipes_dir: Path, slug: str) -> MagicMock:
    """Создать mock RecipeManager с реальным read_recipe из tmp_path."""
    from multiprocess_prototype.recipes.manager import RecipeManager

    _write_recipe_file(recipes_dir, slug)

    engine_mock = MagicMock()
    engine_mock.get_active.return_value = slug
    engine_mock.recipes_dir = recipes_dir

    mgr = RecipeManager(engine=engine_mock)
    return mgr


# ---------------------------------------------------------------------------
# Тест 1: успешное сохранение blueprint в YAML
# ---------------------------------------------------------------------------


class TestSaveToActiveRecipeWritesBlueprint:
    """После save_to_active_recipe файл YAML содержит blueprint и display_bindings."""

    def test_save_to_active_recipe_writes_blueprint(self, tmp_path: Path, monkeypatch) -> None:
        """blueprint.processes и display_bindings записаны в YAML рецепта."""
        recipes_dir = tmp_path / "recipes"
        recipes_dir.mkdir()
        slug = "my_recipe"

        mgr = _make_recipe_manager_mock(recipes_dir, slug)
        services = make_pipeline_services(recipe_manager=mgr)
        presenter = PipelinePresenter(services)

        # Добавляем процессы и display в модель
        presenter._model.add_process("cam", plugin_name="CapturePlugin", category="source")
        presenter._model.add_process("proc", plugin_name="MaskPlugin", category="processing")
        presenter._model.add_wire("cam.CapturePlugin.frame", "proc.MaskPlugin.frame")
        presenter._model.add_display("disp1", "main_output", display_name="Главный")
        presenter._model.add_wire("proc.MaskPlugin.result", "display.disp1.frame")

        from PySide6.QtWidgets import QMessageBox

        monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **kw: None))
        monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **kw: None))
        monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **kw: None))

        result = presenter.save_to_active_recipe(parent=None)

        assert result is True

        recipe_path = recipes_dir / f"{slug}.yaml"
        assert recipe_path.exists()

        with open(recipe_path, "r", encoding="utf-8") as f:
            saved = yaml.safe_load(f)

        assert "data" in saved
        data = saved["data"]

        assert "blueprint" in data
        bp = data["blueprint"]
        assert "processes" in bp
        process_names = [p["process_name"] for p in bp["processes"]]
        assert "cam" in process_names
        assert "proc" in process_names

        assert "display_bindings" in data
        assert len(data["display_bindings"]) == 1
        binding = data["display_bindings"][0]
        assert binding["display"] == "main_output"

        assert data.get("active_services") == ["camera_service"]

    def test_save_updates_gui_positions(self, tmp_path: Path, monkeypatch) -> None:
        """gui_positions записываются в секцию data['gui_positions']."""
        recipes_dir = tmp_path / "recipes"
        recipes_dir.mkdir()
        slug = "pos_recipe"

        mgr = _make_recipe_manager_mock(recipes_dir, slug)
        services = make_pipeline_services(recipe_manager=mgr)
        presenter = PipelinePresenter(services)

        presenter._model.add_process("node_a", plugin_name="PA", category="source")
        presenter._gui_positions["node_a"] = (100.0, 200.0)

        from PySide6.QtWidgets import QMessageBox

        monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **kw: None))
        monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **kw: None))
        monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **kw: None))

        result = presenter.save_to_active_recipe(parent=None)
        assert result is True

        with open(recipes_dir / f"{slug}.yaml", "r", encoding="utf-8") as f:
            saved = yaml.safe_load(f)

        gui_pos = saved["data"].get("gui_positions", {})
        assert "node_a" in gui_pos


# ---------------------------------------------------------------------------
# Тест 2: без активного рецепта → warning, return False
# ---------------------------------------------------------------------------


class TestSaveNoActiveRecipe:
    """Без активного рецепта — warning, False."""

    def test_save_no_active_recipe_warns(self, monkeypatch) -> None:
        engine_mock = MagicMock()
        engine_mock.get_active.return_value = None
        engine_mock.recipes_dir = Path("/tmp/fake")

        from multiprocess_prototype.recipes.manager import RecipeManager

        mgr = RecipeManager(engine=engine_mock)

        services = make_pipeline_services(recipe_manager=mgr)
        presenter = PipelinePresenter(services)

        warnings_shown = []

        from PySide6.QtWidgets import QMessageBox

        monkeypatch.setattr(
            QMessageBox,
            "warning",
            staticmethod(lambda *a, **kw: warnings_shown.append(a[2] if len(a) > 2 else "warning")),
        )
        monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **kw: None))
        monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **kw: None))

        result = presenter.save_to_active_recipe(parent=None)

        assert result is False
        assert len(warnings_shown) == 1
        assert "рецепт" in warnings_shown[0].lower() or "active" in warnings_shown[0].lower()


# ---------------------------------------------------------------------------
# Тест 3: RecipeManager недоступен → warning, return False
# ---------------------------------------------------------------------------


class TestSaveNoRecipeManager:
    """services.recipes без _rm bridge → warning, False."""

    def test_save_no_recipe_manager_warns(self, monkeypatch) -> None:
        services = make_pipeline_services(recipe_manager=None)
        presenter = PipelinePresenter(services)

        warnings_shown = []

        from PySide6.QtWidgets import QMessageBox

        monkeypatch.setattr(
            QMessageBox, "warning", staticmethod(lambda *a, **kw: warnings_shown.append(a[2] if len(a) > 2 else "w"))
        )
        monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **kw: None))
        monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **kw: None))

        result = presenter.save_to_active_recipe(parent=None)

        assert result is False
        assert len(warnings_shown) == 1


# ---------------------------------------------------------------------------
# Тест 4: запись вызывает исключение → critical, return False
# ---------------------------------------------------------------------------


class TestSaveHandlesException:
    """Исключение при записи YAML → critical, False."""

    def test_save_handles_exception(self, tmp_path: Path, monkeypatch) -> None:
        recipes_dir = tmp_path / "recipes"
        recipes_dir.mkdir()
        slug = "fail_recipe"

        engine_mock = MagicMock()
        engine_mock.get_active.return_value = slug
        engine_mock.recipes_dir = recipes_dir

        from multiprocess_prototype.recipes.manager import RecipeManager

        mgr = RecipeManager(engine=engine_mock)

        services = make_pipeline_services(recipe_manager=mgr)
        presenter = PipelinePresenter(services)

        criticals_shown = []

        from PySide6.QtWidgets import QMessageBox

        monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **kw: None))
        monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **kw: None))
        monkeypatch.setattr(
            QMessageBox,
            "critical",
            staticmethod(lambda *a, **kw: criticals_shown.append(a[2] if len(a) > 2 else "critical")),
        )

        result = presenter.save_to_active_recipe(parent=None)

        assert result is False
        assert len(criticals_shown) == 1

    def test_save_handles_write_exception(self, tmp_path: Path, monkeypatch) -> None:
        recipes_dir = tmp_path / "recipes"
        recipes_dir.mkdir()
        slug = "ioerr_recipe"

        mgr = _make_recipe_manager_mock(recipes_dir, slug)
        services = make_pipeline_services(recipe_manager=mgr)
        presenter = PipelinePresenter(services)

        criticals_shown = []

        from PySide6.QtWidgets import QMessageBox

        monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **kw: None))
        monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **kw: None))
        monkeypatch.setattr(
            QMessageBox,
            "critical",
            staticmethod(lambda *a, **kw: criticals_shown.append(a[2] if len(a) > 2 else "critical")),
        )

        recipe_file = recipes_dir / f"{slug}.yaml"
        recipe_file.chmod(0o444)

        try:
            result = presenter.save_to_active_recipe(parent=None)

            assert result is False
            assert len(criticals_shown) == 1
            assert "ошибка" in criticals_shown[0].lower() or "Ошибка" in criticals_shown[0]
        finally:
            recipe_file.chmod(0o644)
