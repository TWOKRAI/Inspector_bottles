# -*- coding: utf-8 -*-
"""Тесты сохранения pipeline-графа в рецепт через PipelinePresenter.save_to_active_recipe.

4 smoke/integration-теста:
- test_save_to_active_recipe_writes_blueprint: YAML обновляется blueprint/display_bindings
- test_save_no_active_recipe_warns: без активного рецепта → False, не падает
- test_save_no_recipe_manager_warns: ctx.recipe_manager() → None → False
- test_save_handles_exception: recipe_mgr.save поднимает Exception → False

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

    # Создаём файл рецепта в tmp_dir
    _write_recipe_file(recipes_dir, slug)

    # Mock engine, чтобы get_active и recipes_dir работали
    engine_mock = MagicMock()
    engine_mock.get_active.return_value = slug
    engine_mock.recipes_dir = recipes_dir

    mgr = RecipeManager(engine=engine_mock)
    return mgr


def _make_ctx(recipe_manager=None) -> MagicMock:
    """Создать минимальный mock AppContext."""
    ctx = MagicMock()
    ctx.config = {"topology": {}}
    ctx.action_bus.return_value = None
    ctx.topology_holder.return_value = None
    ctx.plugin_registry.return_value = None
    ctx.recipe_manager.return_value = recipe_manager
    return ctx


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
        ctx = _make_ctx(recipe_manager=mgr)
        presenter = PipelinePresenter(ctx)

        # Добавляем процессы и display в модель
        presenter._model.add_process("cam", plugin_name="CapturePlugin", category="source")
        presenter._model.add_process("proc", plugin_name="MaskPlugin", category="processing")
        presenter._model.add_wire("cam.CapturePlugin.frame", "proc.MaskPlugin.frame")
        presenter._model.add_display("disp1", "main_output", display_name="Главный")
        presenter._model.add_wire("proc.MaskPlugin.result", "display.disp1.frame")

        # Мокаем QMessageBox чтобы не открывать GUI
        from PySide6.QtWidgets import QMessageBox

        monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **kw: None))
        monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **kw: None))
        monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **kw: None))

        result = presenter.save_to_active_recipe(parent=None)

        assert result is True

        # Читаем записанный YAML и проверяем содержимое
        recipe_path = recipes_dir / f"{slug}.yaml"
        assert recipe_path.exists(), "Файл рецепта не создан"

        with open(recipe_path, "r", encoding="utf-8") as f:
            saved = yaml.safe_load(f)

        assert "data" in saved, "Нет секции 'data' в YAML"
        data = saved["data"]

        # blueprint.processes содержит наши процессы
        assert "blueprint" in data, "Нет секции 'blueprint' в data"
        bp = data["blueprint"]
        assert "processes" in bp
        process_names = [p["process_name"] for p in bp["processes"]]
        assert "cam" in process_names
        assert "proc" in process_names

        # display_bindings содержит запись к main_output
        assert "display_bindings" in data, "Нет 'display_bindings' в data"
        assert len(data["display_bindings"]) == 1
        binding = data["display_bindings"][0]
        assert binding["display"] == "main_output"

        # Существующая секция active_services не потерялась
        assert data.get("active_services") == ["camera_service"], "Существующие данные рецепта были уничтожены"

    def test_save_updates_gui_positions(self, tmp_path: Path, monkeypatch) -> None:
        """gui_positions записываются в секцию data['gui_positions']."""
        recipes_dir = tmp_path / "recipes"
        recipes_dir.mkdir()
        slug = "pos_recipe"

        mgr = _make_recipe_manager_mock(recipes_dir, slug)
        ctx = _make_ctx(recipe_manager=mgr)
        presenter = PipelinePresenter(ctx)

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
        assert "node_a" in gui_pos, "gui_positions для node_a не сохранены"


# ---------------------------------------------------------------------------
# Тест 2: без активного рецепта → warning, return False
# ---------------------------------------------------------------------------


class TestSaveNoActiveRecipe:
    """Без активного рецепта — warning, метод возвращает False."""

    def test_save_no_active_recipe_warns(self, monkeypatch) -> None:
        """Если get_active() возвращает None — показать warning и вернуть False."""
        engine_mock = MagicMock()
        engine_mock.get_active.return_value = None
        engine_mock.recipes_dir = Path("/tmp/fake")

        from multiprocess_prototype.recipes.manager import RecipeManager

        mgr = RecipeManager(engine=engine_mock)

        ctx = _make_ctx(recipe_manager=mgr)
        presenter = PipelinePresenter(ctx)

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
        assert len(warnings_shown) == 1, "Ожидалось ровно одно warning"
        assert "рецепт" in warnings_shown[0].lower() or "active" in warnings_shown[0].lower()


# ---------------------------------------------------------------------------
# Тест 3: RecipeManager недоступен → warning, return False
# ---------------------------------------------------------------------------


class TestSaveNoRecipeManager:
    """Если ctx.recipe_manager() возвращает None — warning и False."""

    def test_save_no_recipe_manager_warns(self, monkeypatch) -> None:
        """ctx.recipe_manager() == None → QMessageBox.warning, return False."""
        ctx = _make_ctx(recipe_manager=None)
        presenter = PipelinePresenter(ctx)

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
# Тест 4: запись в файл вызывает исключение → critical, return False
# ---------------------------------------------------------------------------


class TestSaveHandlesException:
    """Исключение при записи YAML → QMessageBox.critical, return False."""

    def test_save_handles_exception(self, tmp_path: Path, monkeypatch) -> None:
        """Если read_recipe возвращает None — presenter показывает critical и возвращает False."""
        recipes_dir = tmp_path / "recipes"
        recipes_dir.mkdir()
        slug = "fail_recipe"

        # Создаём engine_mock у которого get_active возвращает slug,
        # а RecipeManager.read_recipe возвращает None (файл не найден или невалиден)
        engine_mock = MagicMock()
        engine_mock.get_active.return_value = slug
        engine_mock.recipes_dir = recipes_dir
        # НЕ создаём файл рецепта — read_recipe вернёт None

        from multiprocess_prototype.recipes.manager import RecipeManager

        mgr = RecipeManager(engine=engine_mock)

        ctx = _make_ctx(recipe_manager=mgr)
        presenter = PipelinePresenter(ctx)

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
        assert len(criticals_shown) == 1, "Ожидалось одно critical-сообщение"

    def test_save_handles_write_exception(self, tmp_path: Path, monkeypatch) -> None:
        """Если запись файла поднимает OSError — presenter ловит, возвращает False."""
        recipes_dir = tmp_path / "recipes"
        recipes_dir.mkdir()
        slug = "ioerr_recipe"

        mgr = _make_recipe_manager_mock(recipes_dir, slug)
        ctx = _make_ctx(recipe_manager=mgr)
        presenter = PipelinePresenter(ctx)

        criticals_shown = []

        from PySide6.QtWidgets import QMessageBox

        monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **kw: None))
        monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **kw: None))
        monkeypatch.setattr(
            QMessageBox,
            "critical",
            staticmethod(lambda *a, **kw: criticals_shown.append(a[2] if len(a) > 2 else "critical")),
        )

        # Делаем файл read-only, чтобы запись вызвала OSError
        recipe_file = recipes_dir / f"{slug}.yaml"
        recipe_file.chmod(0o444)

        try:
            result = presenter.save_to_active_recipe(parent=None)

            assert result is False
            assert len(criticals_shown) == 1, "Ожидалось одно critical-сообщение"
            assert "ошибка" in criticals_shown[0].lower() or "Ошибка" in criticals_shown[0]
        finally:
            # Восстанавливаем права чтобы pytest мог убрать tmp_path
            recipe_file.chmod(0o644)
