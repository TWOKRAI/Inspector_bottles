# -*- coding: utf-8 -*-
"""Тесты кнопки «Запустить активный рецепт» — PipelinePresenter.launch_active_recipe.

7 unit-тестов:
- test_launch_no_recipe_manager_warns: ctx.recipe_manager is None → False
- test_launch_no_active_recipe_warns: get_active() == None → False
- test_launch_recipe_read_fails: read_recipe == None → critical, False
- test_launch_no_blueprint_warns: рецепт без blueprint → warning, False
- test_launch_no_proxy_warns: нет proxy в ctx.extras → warning, False
- test_launch_calls_replace_blueprint: proxy замокан, success=True → True
- test_launch_handles_replace_blueprint_failure: success=False → critical, False
- test_launch_handles_exception: proxy.replace_blueprint raises → critical, False

Запуск:
    python -m pytest multiprocess_prototype/frontend/widgets/tabs/pipeline/tests/test_launch_recipe.py -v
"""

from __future__ import annotations

from unittest.mock import MagicMock

from multiprocess_prototype.frontend.widgets.tabs.pipeline.presenter import (
    PipelinePresenter,
)


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------


def _make_ctx(recipe_manager=None, extras: dict | None = None) -> MagicMock:
    """Создать минимальный mock AppContext."""
    ctx = MagicMock()
    ctx.config = {"topology": {}}
    ctx.action_bus.return_value = None
    ctx.topology_holder.return_value = None
    ctx.plugin_registry.return_value = None
    ctx.recipe_manager = recipe_manager
    ctx.extras = extras or {}
    # Убедиться, что ctx.process_manager не существует (нет случайного proxy)
    del ctx.process_manager
    return ctx


_SENTINEL = object()  # маркер «не передано»


def _make_recipe_manager_mock(
    active_slug: str | None = "my_recipe",
    recipe_data=_SENTINEL,
) -> MagicMock:
    """Создать mock RecipeManager с нужным поведением.

    Если recipe_data не передан — используется дефолтный рецепт с blueprint.
    Передай ``recipe_data=None`` явно, чтобы вернуть None из read_recipe.
    """
    mgr = MagicMock()
    mgr.get_active.return_value = active_slug
    if recipe_data is _SENTINEL:
        # Дефолтный рецепт с blueprint
        mgr.read_recipe.return_value = {
            "meta": {"name": active_slug},
            "data": {
                "blueprint": {
                    "processes": [{"process_name": "proc1"}],
                    "wires": [],
                }
            },
        }
    else:
        mgr.read_recipe.return_value = recipe_data
    return mgr


# ---------------------------------------------------------------------------
# Тест 1: RecipeManager недоступен → warning, return False
# ---------------------------------------------------------------------------


class TestLaunchNoRecipeManager:
    """ctx.recipe_manager is None → QMessageBox.warning, return False."""

    def test_launch_no_recipe_manager_warns(self, monkeypatch) -> None:
        ctx = _make_ctx(recipe_manager=None)
        presenter = PipelinePresenter(ctx)

        warnings_shown = []
        from PySide6.QtWidgets import QMessageBox

        monkeypatch.setattr(
            QMessageBox,
            "warning",
            staticmethod(lambda *a, **kw: warnings_shown.append(a[2] if len(a) > 2 else "w")),
        )
        monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **kw: None))
        monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **kw: None))

        result = presenter.launch_active_recipe(parent=None)

        assert result is False
        assert len(warnings_shown) == 1
        assert "недоступен" in warnings_shown[0].lower() or "RecipeManager" in warnings_shown[0]


# ---------------------------------------------------------------------------
# Тест 2: нет активного рецепта → warning, return False
# ---------------------------------------------------------------------------


class TestLaunchNoActiveRecipe:
    """get_active() == None → warning «нет активного рецепта», return False."""

    def test_launch_no_active_recipe_warns(self, monkeypatch) -> None:
        mgr = _make_recipe_manager_mock(active_slug=None)
        ctx = _make_ctx(recipe_manager=mgr)
        presenter = PipelinePresenter(ctx)

        warnings_shown = []
        from PySide6.QtWidgets import QMessageBox

        monkeypatch.setattr(
            QMessageBox,
            "warning",
            staticmethod(lambda *a, **kw: warnings_shown.append(a[2] if len(a) > 2 else "w")),
        )
        monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **kw: None))
        monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **kw: None))

        result = presenter.launch_active_recipe(parent=None)

        assert result is False
        assert len(warnings_shown) == 1
        assert "рецепт" in warnings_shown[0].lower()


# ---------------------------------------------------------------------------
# Тест 3: read_recipe возвращает None → critical, return False
# ---------------------------------------------------------------------------


class TestLaunchRecipeReadFails:
    """read_recipe() == None → QMessageBox.critical, return False."""

    def test_launch_recipe_read_fails(self, monkeypatch) -> None:
        mgr = _make_recipe_manager_mock(active_slug="broken", recipe_data=None)
        ctx = _make_ctx(recipe_manager=mgr)
        presenter = PipelinePresenter(ctx)

        criticals_shown = []
        from PySide6.QtWidgets import QMessageBox

        monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **kw: None))
        monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **kw: None))
        monkeypatch.setattr(
            QMessageBox,
            "critical",
            staticmethod(lambda *a, **kw: criticals_shown.append(a[2] if len(a) > 2 else "c")),
        )

        result = presenter.launch_active_recipe(parent=None)

        assert result is False
        assert len(criticals_shown) == 1


# ---------------------------------------------------------------------------
# Тест 4: рецепт без blueprint → warning, return False
# ---------------------------------------------------------------------------


class TestLaunchNoBlueprint:
    """Рецепт без секции blueprint → warning, return False."""

    def test_launch_no_blueprint_warns(self, monkeypatch) -> None:
        mgr = _make_recipe_manager_mock(
            active_slug="empty_bp",
            recipe_data={"meta": {}, "data": {"active_services": []}},
        )
        ctx = _make_ctx(recipe_manager=mgr)
        presenter = PipelinePresenter(ctx)

        warnings_shown = []
        from PySide6.QtWidgets import QMessageBox

        monkeypatch.setattr(
            QMessageBox,
            "warning",
            staticmethod(lambda *a, **kw: warnings_shown.append(a[2] if len(a) > 2 else "w")),
        )
        monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **kw: None))
        monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **kw: None))

        result = presenter.launch_active_recipe(parent=None)

        assert result is False
        assert len(warnings_shown) == 1
        assert "blueprint" in warnings_shown[0].lower()


# ---------------------------------------------------------------------------
# Тест 5: нет proxy → warning, return False
# ---------------------------------------------------------------------------


class TestLaunchNoProxy:
    """Нет proxy в ctx.extras и нет ctx.process_manager → warning, return False."""

    def test_launch_no_proxy_warns(self, monkeypatch) -> None:
        mgr = _make_recipe_manager_mock()  # возвращает рецепт с blueprint
        ctx = _make_ctx(recipe_manager=mgr, extras={})
        presenter = PipelinePresenter(ctx)

        warnings_shown = []
        from PySide6.QtWidgets import QMessageBox

        monkeypatch.setattr(
            QMessageBox,
            "warning",
            staticmethod(lambda *a, **kw: warnings_shown.append(a[2] if len(a) > 2 else "w")),
        )
        monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **kw: None))
        monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **kw: None))

        result = presenter.launch_active_recipe(parent=None)

        assert result is False
        assert len(warnings_shown) == 1
        assert "proxy" in warnings_shown[0].lower() or "ProcessManager" in warnings_shown[0]


# ---------------------------------------------------------------------------
# Тест 6: успешный вызов replace_blueprint → information, return True
# ---------------------------------------------------------------------------


class TestLaunchCallsReplaceBlueprint:
    """Proxy замокан, replace_blueprint возвращает success=True → True, information показан."""

    def test_launch_calls_replace_blueprint(self, monkeypatch) -> None:
        expected_blueprint = {
            "processes": [{"process_name": "proc1"}],
            "wires": [],
        }
        mgr = _make_recipe_manager_mock(
            active_slug="demo_recipe",
            recipe_data={
                "meta": {"name": "demo_recipe"},
                "data": {"blueprint": expected_blueprint},
            },
        )

        proxy = MagicMock()
        proxy.replace_blueprint.return_value = {
            "success": True,
            "replaced": ["proc1"],
            "skipped_protected": [],
            "error": None,
            "rolled_back": False,
        }

        ctx = _make_ctx(
            recipe_manager=mgr,
            extras={"process_manager_proxy": proxy},
        )
        presenter = PipelinePresenter(ctx)

        info_shown = []
        from PySide6.QtWidgets import QMessageBox

        monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **kw: None))
        monkeypatch.setattr(
            QMessageBox,
            "information",
            staticmethod(lambda *a, **kw: info_shown.append(a[2] if len(a) > 2 else "i")),
        )
        monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **kw: None))

        result = presenter.launch_active_recipe(parent=None)

        assert result is True
        proxy.replace_blueprint.assert_called_once_with(expected_blueprint)
        assert len(info_shown) == 1
        assert "demo_recipe" in info_shown[0]
        assert "1" in info_shown[0]  # replaced: 1 процесс


# ---------------------------------------------------------------------------
# Тест 7: replace_blueprint возвращает success=False → critical, return False
# ---------------------------------------------------------------------------


class TestLaunchHandlesReplaceBlueprintFailure:
    """Proxy возвращает success=False → critical с error/rollback, return False."""

    def test_launch_handles_replace_blueprint_failure(self, monkeypatch) -> None:
        mgr = _make_recipe_manager_mock()
        proxy = MagicMock()
        proxy.replace_blueprint.return_value = {
            "success": False,
            "replaced": [],
            "skipped_protected": [],
            "error": "boom",
            "rolled_back": True,
        }

        ctx = _make_ctx(
            recipe_manager=mgr,
            extras={"process_manager_proxy": proxy},
        )
        presenter = PipelinePresenter(ctx)

        criticals_shown = []
        from PySide6.QtWidgets import QMessageBox

        monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **kw: None))
        monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **kw: None))
        monkeypatch.setattr(
            QMessageBox,
            "critical",
            staticmethod(lambda *a, **kw: criticals_shown.append(a[2] if len(a) > 2 else "c")),
        )

        result = presenter.launch_active_recipe(parent=None)

        assert result is False
        assert len(criticals_shown) == 1
        assert "boom" in criticals_shown[0]
        assert "выполнен" in criticals_shown[0]


# ---------------------------------------------------------------------------
# Тест 8: replace_blueprint поднимает исключение → critical, не падает
# ---------------------------------------------------------------------------


class TestLaunchHandlesException:
    """proxy.replace_blueprint raises Exception → critical, return False, не падает."""

    def test_launch_handles_exception(self, monkeypatch) -> None:
        mgr = _make_recipe_manager_mock()
        proxy = MagicMock()
        proxy.replace_blueprint.side_effect = Exception("crash")

        ctx = _make_ctx(
            recipe_manager=mgr,
            extras={"process_manager_proxy": proxy},
        )
        presenter = PipelinePresenter(ctx)

        criticals_shown = []
        from PySide6.QtWidgets import QMessageBox

        monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **kw: None))
        monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **kw: None))
        monkeypatch.setattr(
            QMessageBox,
            "critical",
            staticmethod(lambda *a, **kw: criticals_shown.append(a[2] if len(a) > 2 else "c")),
        )

        result = presenter.launch_active_recipe(parent=None)

        assert result is False
        assert len(criticals_shown) == 1
        assert "crash" in criticals_shown[0]
