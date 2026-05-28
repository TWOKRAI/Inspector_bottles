# -*- coding: utf-8 -*-
"""Тесты кнопки «Запустить активный рецепт» — PipelinePresenter.launch_active_recipe.
Task E.1 -> F.4: мигрировано на RecipeStore Protocol (FakeRecipeStore).

8 unit-тестов (см. docstrings в каждом классе).

Запуск:
    python -m pytest multiprocess_prototype/frontend/widgets/tabs/pipeline/tests/test_launch_recipe.py -v
"""

from __future__ import annotations

from unittest.mock import MagicMock

from multiprocess_prototype.domain.tests._fakes import FakeRecipeStore
from multiprocess_prototype.frontend.widgets.tabs.pipeline.presenter import (
    PipelinePresenter,
)

from ._helpers import make_pipeline_services


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------


_SENTINEL = object()


def _make_recipe_store(
    active_slug: str | None = "my_recipe",
    recipe_data=_SENTINEL,
) -> FakeRecipeStore:
    """Создать FakeRecipeStore с нужным поведением."""
    raw: dict[str, dict] = {}
    if active_slug is not None:
        if recipe_data is _SENTINEL:
            raw[active_slug] = {
                "meta": {"name": active_slug},
                "data": {
                    "blueprint": {
                        "processes": [{"process_name": "proc1"}],
                        "wires": [],
                    }
                },
            }
        elif recipe_data is not None:
            raw[active_slug] = recipe_data
        # recipe_data=None -> slug в active но raw пуст (read_raw вернёт None)
    return FakeRecipeStore(raw=raw, active=active_slug)


def _make_services(store: FakeRecipeStore, config_extra: dict | None = None):
    """Создать AppServices с FakeRecipeStore."""
    services = make_pipeline_services(config_extra=config_extra)
    object.__setattr__(services, "recipes", store)
    return services


# ---------------------------------------------------------------------------
# Тест 1: нет активного рецепта -> warning, return False
# ---------------------------------------------------------------------------


class TestLaunchNoActiveRecipe:
    """get_active() == None -> warning, return False."""

    def test_launch_no_active_recipe_warns(self, monkeypatch) -> None:
        store = _make_recipe_store(active_slug=None)
        services = _make_services(store)
        presenter = PipelinePresenter(services)

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
# Тест 2: read_raw возвращает None -> critical, return False
# ---------------------------------------------------------------------------


class TestLaunchRecipeReadFails:
    """read_raw() == None -> QMessageBox.critical, return False."""

    def test_launch_recipe_read_fails(self, monkeypatch) -> None:
        store = _make_recipe_store(active_slug="broken", recipe_data=None)
        services = _make_services(store)
        presenter = PipelinePresenter(services)

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
# Тест 3: рецепт без blueprint -> warning, return False
# ---------------------------------------------------------------------------


class TestLaunchNoBlueprint:
    """Рецепт без секции blueprint -> warning, return False."""

    def test_launch_no_blueprint_warns(self, monkeypatch) -> None:
        store = _make_recipe_store(
            active_slug="empty_bp",
            recipe_data={"meta": {}, "data": {"active_services": []}},
        )
        services = _make_services(store)
        presenter = PipelinePresenter(services)

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
# Тест 4: нет proxy -> warning, return False
# ---------------------------------------------------------------------------


class TestLaunchNoProxy:
    """Нет proxy в config -> warning, return False."""

    def test_launch_no_proxy_warns(self, monkeypatch) -> None:
        store = _make_recipe_store()
        services = _make_services(store)
        presenter = PipelinePresenter(services)

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
# Тест 5: успешный вызов replace_blueprint -> information, return True
# ---------------------------------------------------------------------------


class TestLaunchCallsReplaceBlueprint:
    """Proxy замокан, replace_blueprint возвращает success=True -> True."""

    def test_launch_calls_replace_blueprint(self, monkeypatch) -> None:
        expected_blueprint = {
            "processes": [{"process_name": "proc1"}],
            "wires": [],
        }
        store = _make_recipe_store(
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

        services = _make_services(store, config_extra={"process_manager_proxy": proxy})
        presenter = PipelinePresenter(services)

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
        assert "1" in info_shown[0]


# ---------------------------------------------------------------------------
# Тест 6: replace_blueprint возвращает success=False -> critical, return False
# ---------------------------------------------------------------------------


class TestLaunchHandlesReplaceBlueprintFailure:
    """Proxy возвращает success=False -> critical, return False."""

    def test_launch_handles_replace_blueprint_failure(self, monkeypatch) -> None:
        store = _make_recipe_store()
        proxy = MagicMock()
        proxy.replace_blueprint.return_value = {
            "success": False,
            "replaced": [],
            "skipped_protected": [],
            "error": "boom",
            "rolled_back": True,
        }

        services = _make_services(store, config_extra={"process_manager_proxy": proxy})
        presenter = PipelinePresenter(services)

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
# Тест 7: replace_blueprint поднимает исключение -> critical, не падает
# ---------------------------------------------------------------------------


class TestLaunchHandlesException:
    """proxy.replace_blueprint raises Exception -> critical, return False."""

    def test_launch_handles_exception(self, monkeypatch) -> None:
        store = _make_recipe_store()
        proxy = MagicMock()
        proxy.replace_blueprint.side_effect = Exception("crash")

        services = _make_services(store, config_extra={"process_manager_proxy": proxy})
        presenter = PipelinePresenter(services)

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
