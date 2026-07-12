# -*- coding: utf-8 -*-
"""Тесты сохранения pipeline-графа в рецепт через PipelinePresenter.save_to_active_recipe.
Task E.1 -> F.4: мигрировано на RecipeStore Protocol (FakeRecipeStore).

Запуск:
    python -m pytest multiprocess_prototype/frontend/widgets/tabs/pipeline/tests/test_save_recipe.py -v
"""

from __future__ import annotations

from multiprocess_prototype.domain.tests._fakes import FakeRecipeStore
from multiprocess_prototype.frontend.widgets.tabs.pipeline.presenter import (
    PipelinePresenter,
)

from ._helpers import make_pipeline_services


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------


def _make_recipe_raw(slug: str = "test_recipe") -> dict:
    """Создать минимальный v3-рецепт (top-level формат, как на диске)."""
    return {
        "name": slug,
        "version": 3,
        "description": "",
        "blueprint": {"processes": [], "wires": [], "displays": []},
        "active_services": ["camera_service"],
    }


def _make_services_with_recipe(slug: str = "test_recipe") -> tuple:
    """Создать services с FakeRecipeStore, содержащим рецепт. Вернуть (services, store)."""
    raw = {slug: _make_recipe_raw(slug)}
    store = FakeRecipeStore(raw=raw, active=slug)
    services = make_pipeline_services(recipe_manager=None)
    # Подменяем recipes на наш store (make_pipeline_services с None создаёт пустой)
    object.__setattr__(services, "recipes", store)
    return services, store


# ---------------------------------------------------------------------------
# Тест 1: успешное сохранение blueprint в raw store
# ---------------------------------------------------------------------------


class TestSaveToActiveRecipeWritesBlueprint:
    """После save_to_active_recipe store содержит blueprint и display_bindings."""

    def test_save_to_active_recipe_writes_blueprint(self, monkeypatch) -> None:
        """blueprint.processes и display_bindings записаны в raw store рецепта."""
        slug = "my_recipe"
        services, store = _make_services_with_recipe(slug)
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

        # Проверяем raw-данные в store (не на диске).
        # Fix recipe-v3-engine-decouple: top-level blueprint, displays ВНУТРИ
        # blueprint.displays (не legacy data:-вложение). active_services сохраняется
        # top-level (пишем в прочитанный raw, не затирая остальные ключи).
        saved = store._raw[slug]
        assert "data" not in saved  # legacy-вложение убрано

        assert "blueprint" in saved
        bp = saved["blueprint"]
        assert "processes" in bp
        process_names = [p["process_name"] for p in bp["processes"]]
        assert "cam" in process_names
        assert "proc" in process_names

        assert "displays" in bp
        assert len(bp["displays"]) == 1
        assert bp["displays"][0]["display_id"] == "main_output"

        assert saved.get("active_services") == ["camera_service"]

    def test_save_no_top_level_gui_positions(self, monkeypatch) -> None:
        """AU-1 регресс: после save top-level gui_positions ОТСУТСТВУЕТ.

        Позиции живут только в blueprint.metadata.gui_positions (канонизация durable —
        см. test_save_writes_layout_into_blueprint_metadata). Top-level дубль не пишется
        и legacy-дубль из raw вычищается (normalize_recipe_v3_raw, аудит Ф4.8).
        """
        slug = "pos_recipe"
        services, store = _make_services_with_recipe(slug)
        # Подсунуть legacy top-level дубль в исходный raw — save обязан его вычистить.
        store._raw[slug]["gui_positions"] = {"stale_node": [1.0, 1.0]}
        presenter = PipelinePresenter(services)

        presenter._model.add_process("node_a", plugin_name="PA", category="source")
        presenter._layout.gui_positions["node_a"] = (100.0, 200.0)

        from PySide6.QtWidgets import QMessageBox

        monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **kw: None))
        monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **kw: None))
        monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **kw: None))

        result = presenter.save_to_active_recipe(parent=None)
        assert result is True

        saved = store._raw[slug]
        # top-level дубль (в т.ч. legacy stale) вычищен
        assert "gui_positions" not in saved
        # позиции — в канонической секции blueprint.metadata
        assert saved["blueprint"]["metadata"]["gui_positions"]["node_a"] == [100.0, 200.0]

    def test_save_writes_layout_into_blueprint_metadata(self, monkeypatch) -> None:
        """free-layout Task 2/3: gui_positions + locked_nodes пишутся в blueprint.metadata.

        Именно оттуда их читает load_topology_from_config и cold-start
        (unwrap_recipe сохраняет blueprint.metadata).
        """
        slug = "meta_recipe"
        services, store = _make_services_with_recipe(slug)
        presenter = PipelinePresenter(services)

        presenter._model.add_process("node_a", plugin_name="PA", category="source")
        presenter._layout.gui_positions["node_a"] = (100.0, 200.0)
        presenter._layout.locked_nodes.add("node_a")

        from PySide6.QtWidgets import QMessageBox

        monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **kw: None))
        monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **kw: None))
        monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **kw: None))

        assert presenter.save_to_active_recipe(parent=None) is True

        meta = store._raw[slug]["blueprint"]["metadata"]
        assert meta["gui_positions"]["node_a"] == [100.0, 200.0]
        assert meta["locked_nodes"] == ["node_a"]


class TestPersistLayoutDebounce:
    """free-layout Task 2/3: _persist_layout_to_recipe патчит ТОЛЬКО blueprint.metadata."""

    def test_persist_patches_metadata_only(self) -> None:
        """Авто-сохранение layout не трогает processes/wires рецепта."""
        slug = "persist_recipe"
        raw = {
            slug: {
                "name": slug,
                "version": 3,
                "blueprint": {
                    "processes": [{"process_name": "cam", "plugins": [{"plugin_name": "capture"}]}],
                    "wires": [{"source": "a", "target": "b"}],
                },
            }
        }
        from multiprocess_prototype.domain.tests._fakes import FakeRecipeStore

        store = FakeRecipeStore(raw=raw, active=slug)
        services = make_pipeline_services()
        object.__setattr__(services, "recipes", store)
        presenter = PipelinePresenter(services)

        presenter._layout.gui_positions["cam.capture"] = (321.0, 654.0)
        presenter._layout.locked_nodes.add("cam.capture")

        presenter._persist_layout_to_recipe()

        bp = store._raw[slug]["blueprint"]
        # processes/wires нетронуты
        assert bp["processes"] == [{"process_name": "cam", "plugins": [{"plugin_name": "capture"}]}]
        assert bp["wires"] == [{"source": "a", "target": "b"}]
        # layout записан в metadata
        assert bp["metadata"]["gui_positions"]["cam.capture"] == [321.0, 654.0]
        assert bp["metadata"]["locked_nodes"] == ["cam.capture"]

    def test_persist_no_active_recipe_is_noop(self) -> None:
        """Без активного рецепта авто-сохранение — тихий no-op (без исключений)."""
        from multiprocess_prototype.domain.tests._fakes import FakeRecipeStore

        store = FakeRecipeStore()
        services = make_pipeline_services()
        object.__setattr__(services, "recipes", store)
        presenter = PipelinePresenter(services)

        presenter._layout.gui_positions["x"] = (1.0, 2.0)
        presenter._persist_layout_to_recipe()  # не должно бросить


# ---------------------------------------------------------------------------
# Тест 2: без активного рецепта -> warning, return False
# ---------------------------------------------------------------------------


class TestSaveNoActiveRecipe:
    """Без активного рецепта — warning, False."""

    def test_save_no_active_recipe_warns(self, monkeypatch) -> None:
        # Store без active рецепта
        store = FakeRecipeStore()
        services = make_pipeline_services()
        object.__setattr__(services, "recipes", store)
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
# Тест 3: read_raw возвращает None -> critical, return False
# ---------------------------------------------------------------------------


class TestSaveReadRawFails:
    """store.read_raw вернул None -> critical, False."""

    def test_save_read_raw_fails(self, monkeypatch) -> None:
        # Active slug есть, но raw-данных нет
        store = FakeRecipeStore(active="ghost")
        services = make_pipeline_services()
        object.__setattr__(services, "recipes", store)
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


# ---------------------------------------------------------------------------
# Тест 4: save_raw вызывает исключение -> critical, return False
# ---------------------------------------------------------------------------


class TestFieldEditPersistsToRecipe:
    """Регресс: правка поля в инспекторе → save_to_active_recipe пишет НОВОЕ значение.

    Защита от бага field-edit-persist: SetPluginConfig обновлял domain-топологию под
    _suppress, но self._model (его сериализует graph_to_blueprint при save) оставался
    со СТАРЫМ конфигом → save писал устаревшее (правки полей не сохранялись в рецепт).
    Фикс: presenter синкает self._model из domain после dispatch (_on_inspector_field_changed).
    Нужен РЕАЛЬНЫЙ orchestrator — FakeCommandDispatcher не обновляет topology_store.
    """

    def test_field_edit_then_save_persists_new_value(self, monkeypatch) -> None:
        from ._helpers import make_pipeline_services_with_orchestrator

        slug = "edit_recipe"
        services = make_pipeline_services_with_orchestrator()

        store = FakeRecipeStore(
            raw={slug: {"name": slug, "version": 3, "blueprint": {"processes": [], "wires": [], "displays": []}}},
            active=slug,
        )
        object.__setattr__(services, "recipes", store)

        presenter = PipelinePresenter(services)
        # Выровнять view-модель с дефолтной топологией orchestrator (camera/processor),
        # чтобы graph_to_blueprint при save сериализовал эти процессы.
        presenter._model.from_topology_dict(services.topology.load().to_dict())

        from PySide6.QtWidgets import QMessageBox

        monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **kw: None))
        monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **kw: None))
        monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **kw: None))

        # Правка поля плагина процесса 'processor' (как из инспектора Pipeline).
        presenter._on_inspector_field_changed("processor", "threshold", 128)

        assert presenter.save_to_active_recipe(parent=None) is True

        # В сохранённом рецепте новое значение поля (а не старое/отсутствующее).
        saved_procs = store._raw[slug]["blueprint"]["processes"]
        proc = next(p for p in saved_procs if p["process_name"] == "processor")
        assert proc["plugins"][0]["config"]["threshold"] == 128


class TestSaveHandlesException:
    """Исключение при save_raw -> critical, False."""

    def test_save_handles_exception(self, monkeypatch) -> None:
        slug = "fail_recipe"
        raw = {slug: _make_recipe_raw(slug)}
        store = FakeRecipeStore(raw=raw, active=slug)

        # Заменяем save_raw на бросающую исключение
        def _raise(*args, **kwargs):
            raise OSError("Disk full")

        store.save_raw = _raise  # type: ignore[assignment]

        services = make_pipeline_services()
        object.__setattr__(services, "recipes", store)
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
        assert "ошибка" in criticals_shown[0].lower() or "Ошибка" in criticals_shown[0]
