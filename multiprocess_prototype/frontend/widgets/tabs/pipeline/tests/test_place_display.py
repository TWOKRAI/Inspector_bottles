# -*- coding: utf-8 -*-
"""Task 4.1 — unit-тесты PipelinePresenter: place_display и жизненный цикл display-бокса.

Покрытые сценарии (из плана pipeline-place-display-node.md, Task 4.1):
  1. place_display создаёт DisplayNodeItem на scene, dispatch НЕ звался.
  2. Выживание: placed-бокс остаётся после _on_topology_replaced (reload).
  3. Удаление unbound: remove_selected([id]) → бокс исчез, dispatch не звался,
     id убран из _placed_display_ids.
  4. Переход в bound: place_display → add_wire → BindDisplay dispatched;
     после reload ровно один бокс (нет дубля), id убран из _placed_display_ids.
  5. Fan-in: два источника → один display_id → один бокс, два binding-ребра.
  6. Сброс при смене рецепта: place_display → _on_recipe_activated → set пуст,
     непривязанный бокс исчез.

Доп. тест: идемпотентность повторного place_display того же id (один бокс).

Используются:
  - make_pipeline_services_with_orchestrator (реальный dispatch + EventBus)
  - FakeDisplayCatalog с двумя каналами («main», «preview»)
  - GraphScene (qtbot для Qt-инфраструктуры)
  - FakeCommandDispatcher + FakeEventBus для unit-сценариев без реального dispatch

Refs: plans/pipeline-place-display-node.md (Task 4.1)
"""

from __future__ import annotations

import pytest

from multiprocess_prototype.domain.events import RecipeActivated, TopologyReplaced
from multiprocess_prototype.domain.protocols.plugin_catalog import PluginSpec, PortSpec
from multiprocess_prototype.domain.tests._fakes import (
    FakeCommandDispatcher,
    FakeDisplayCatalog,
    FakeEventBus,
)
from multiprocess_prototype.frontend.widgets.tabs.pipeline.graph.display_node_item import (
    DisplayNodeItem,
)
from multiprocess_prototype.frontend.widgets.tabs.pipeline.graph.graph_scene import GraphScene
from multiprocess_prototype.frontend.widgets.tabs.pipeline.presenter import PipelinePresenter

from ._helpers import make_pipeline_services, make_pipeline_services_with_orchestrator


# ---------------------------------------------------------------------------
# Константы / настройки
# ---------------------------------------------------------------------------

_PLUGIN_SPECS = {
    "capture": PluginSpec(
        name="capture",
        category="source",
        ports=(PortSpec(name="frame", dtype="image/bgr", direction="output"),),
    ),
    "blur": PluginSpec(
        name="blur",
        category="filter",
        ports=(
            PortSpec(name="frame", dtype="image/bgr", direction="input"),
            PortSpec(name="out", dtype="image/bgr", direction="output"),
        ),
    ),
}

# Базовая топология: один источник без wire и без displays
_TOPO_SOURCE_ONLY = {
    "processes": [
        {"process_name": "cam", "plugins": [{"plugin_name": "capture"}]},
    ],
    "wires": [],
    "displays": [],
}


def _make_orchestrator_services(topology: dict | None = None):
    """Services с реальным orchestrator, двумя display-каналами и plugin_specs."""
    return make_pipeline_services_with_orchestrator(
        topology=topology or dict(_TOPO_SOURCE_ONLY),
        plugin_specs=_PLUGIN_SPECS,
        display_ids={"main", "preview"},
    )


def _make_fake_services(topology: dict | None = None, events=None):
    """Services с FakeCommandDispatcher (нет реальных domain-правил)."""
    # FakeDisplayCatalog уже импортирован на уровне модуля.
    from multiprocess_prototype.domain.protocols.display_catalog import DisplaySpec

    display_catalog = FakeDisplayCatalog(
        specs={
            "main": DisplaySpec(display_id="main", display_name="Основной"),
            "preview": DisplaySpec(display_id="preview", display_name="Превью"),
        }
    )
    svc = make_pipeline_services(
        topology=topology or dict(_TOPO_SOURCE_ONLY),
        events=events,
    )
    # Подменяем каталог дисплеев на тот, у которого есть наши каналы
    # (make_pipeline_services возвращает FakeDisplayCatalog() без каналов)
    object.__setattr__(svc, "displays", display_catalog)  # Protocol — read-only поле нельзя
    return svc


# ---------------------------------------------------------------------------
# Вспомогательная функция: построить presenter + scene (без загрузки)
# ---------------------------------------------------------------------------


def _build_presenter_with_scene(services, qtbot):
    """Создать PipelinePresenter с GraphScene; вернуть (presenter, scene)."""
    p = PipelinePresenter(services)
    scene = GraphScene()
    p.set_scene(scene)
    nodes, edges = p.load_topology_from_config()
    p.load_scene_with_ports(nodes, edges)
    return p, scene


# ===========================================================================
# Сценарий 1: place_display создаёт DisplayNodeItem без dispatch
# ===========================================================================


class TestPlaceDisplayCreatesBox:
    """place_display → DisplayNodeItem на scene, dispatch НЕ вызывался."""

    def test_box_appears_in_scene(self, qtbot):
        """После place_display бокс присутствует в scene как DisplayNodeItem."""
        services = _make_orchestrator_services()
        p, scene = _build_presenter_with_scene(services, qtbot)

        p.place_display("main", 600.0, 50.0)

        node = scene.get_node("main")
        assert node is not None, "DisplayNodeItem должен появиться в scene"
        assert isinstance(node, DisplayNodeItem), "Тип узла должен быть DisplayNodeItem"

    def test_no_dispatch_called(self, qtbot):
        """place_display не вызывает services.commands.dispatch (binding ещё нет)."""
        # Используем FakeCommandDispatcher для подсчёта вызовов
        fake_bus = FakeEventBus()
        services = make_pipeline_services(
            topology=dict(_TOPO_SOURCE_ONLY),
            events=fake_bus,
        )
        # Перехватить команды через FakeCommandDispatcher из services
        fake_dispatch: FakeCommandDispatcher = services.commands  # type: ignore[assignment]

        p = PipelinePresenter(services)
        scene = GraphScene()
        p.set_scene(scene)
        p.load_topology_from_config()

        dispatch_count_before = len(fake_dispatch.dispatched)
        p.place_display("main", 600.0, 50.0)
        dispatch_count_after = len(fake_dispatch.dispatched)

        assert dispatch_count_after == dispatch_count_before, (
            f"dispatch вызывался {dispatch_count_after - dispatch_count_before} раз(а) "
            f"при place_display — ожидалось 0 вызовов"
        )

    def test_display_id_in_placed_set(self, qtbot):
        """После place_display display_id добавляется в _placed_display_ids."""
        services = _make_orchestrator_services()
        p, scene = _build_presenter_with_scene(services, qtbot)

        assert "main" not in p._placed_display_ids
        p.place_display("main", 600.0, 50.0)
        assert "main" in p._placed_display_ids

    def test_idempotent_repeated_place(self, qtbot):
        """Повторный place_display того же id → ровно один бокс, нет дубля."""
        services = _make_orchestrator_services()
        p, scene = _build_presenter_with_scene(services, qtbot)

        p.place_display("main", 600.0, 50.0)
        p.place_display("main", 650.0, 80.0)  # повтор

        # Ровно один бокс типа DisplayNodeItem с id «main»
        display_items = [item for item in scene.items() if isinstance(item, DisplayNodeItem)]
        main_boxes = [item for item in display_items if item.node_id == "main"]
        assert len(main_boxes) == 1, f"Ожидался 1 бокс 'main', найдено {len(main_boxes)}"


# ===========================================================================
# Сценарий 2: Выживание при reload (_on_topology_replaced)
# ===========================================================================


class TestPlacedBoxSurvivesReload:
    """placed-бокс не исчезает при full scene reload из _on_topology_replaced."""

    def test_box_survives_topology_replaced(self, qtbot):
        """После place_display + _on_topology_replaced бокс по-прежнему в scene."""
        services = _make_orchestrator_services()
        p, scene = _build_presenter_with_scene(services, qtbot)

        p.place_display("main", 600.0, 50.0)
        assert scene.get_node("main") is not None

        # Эмулировать TopologyReplaced (тот же путь, что dispatch триггерит)
        p._on_topology_replaced(TopologyReplaced(reason="test-reload"))

        node = scene.get_node("main")
        assert node is not None, "Бокс должен пережить _on_topology_replaced"
        assert isinstance(node, DisplayNodeItem)

    def test_box_survives_multiple_reloads(self, qtbot):
        """Бокс выживает после 3 подряд reload (нет дублей, нет исчезновений)."""
        services = _make_orchestrator_services()
        p, scene = _build_presenter_with_scene(services, qtbot)

        p.place_display("main", 600.0, 50.0)

        for i in range(3):
            p._on_topology_replaced(TopologyReplaced(reason=f"reload-{i}"))

        main_boxes = [item for item in scene.items() if isinstance(item, DisplayNodeItem) and item.node_id == "main"]
        assert len(main_boxes) == 1, f"Ожидался 1 бокс после 3 reload, найдено {len(main_boxes)}"

    def test_placed_set_not_cleared_on_topology_replaced(self, qtbot):
        """_on_topology_replaced НЕ очищает _placed_display_ids (иначе бокс пропадёт)."""
        services = _make_orchestrator_services()
        p, scene = _build_presenter_with_scene(services, qtbot)

        p.place_display("main", 600.0, 50.0)
        assert "main" in p._placed_display_ids

        p._on_topology_replaced(TopologyReplaced(reason="mutation-reload"))

        assert "main" in p._placed_display_ids, "_placed_display_ids не должен очищаться при _on_topology_replaced"


# ===========================================================================
# Сценарий 3: Удаление unbound-бокса
# ===========================================================================


class TestRemoveUnboundDisplay:
    """remove_selected([id]) для unbound-бокса → бокс исчез, dispatch не звался."""

    def test_box_removed_from_scene(self, qtbot):
        """После remove_selected unbound-бокс отсутствует в scene."""
        fake_bus = FakeEventBus()
        services = make_pipeline_services(
            topology=dict(_TOPO_SOURCE_ONLY),
            events=fake_bus,
        )
        p = PipelinePresenter(services)
        scene = GraphScene()
        p.set_scene(scene)
        p.load_topology_from_config()

        p.place_display("main", 600.0, 50.0)
        assert scene.get_node("main") is not None

        p.remove_selected(["main"])

        assert scene.get_node("main") is None, "Unbound бокс должен исчезнуть из scene"

    def test_no_dispatch_on_unbound_remove(self, qtbot):
        """remove_selected unbound-бокса не вызывает dispatch (нечего отвязывать)."""
        fake_bus = FakeEventBus()
        services = make_pipeline_services(
            topology=dict(_TOPO_SOURCE_ONLY),
            events=fake_bus,
        )
        fake_dispatch: FakeCommandDispatcher = services.commands  # type: ignore[assignment]

        p = PipelinePresenter(services)
        scene = GraphScene()
        p.set_scene(scene)
        p.load_topology_from_config()

        p.place_display("main", 600.0, 50.0)
        dispatch_count_before = len(fake_dispatch.dispatched)

        p.remove_selected(["main"])

        dispatch_count_after = len(fake_dispatch.dispatched)
        assert dispatch_count_after == dispatch_count_before, "dispatch не должен вызываться при удалении unbound-бокса"

    def test_id_removed_from_placed_set(self, qtbot):
        """После remove_selected id убран из _placed_display_ids."""
        fake_bus = FakeEventBus()
        services = make_pipeline_services(
            topology=dict(_TOPO_SOURCE_ONLY),
            events=fake_bus,
        )
        p = PipelinePresenter(services)
        scene = GraphScene()
        p.set_scene(scene)
        p.load_topology_from_config()

        p.place_display("main", 600.0, 50.0)
        assert "main" in p._placed_display_ids

        p.remove_selected(["main"])

        assert "main" not in p._placed_display_ids, "display_id должен быть убран из _placed_display_ids после remove"


# ===========================================================================
# Сценарий 4: Переход в bound (place_display → add_wire → BindDisplay)
# ===========================================================================


class TestPlaceDisplayThenBind:
    """place_display + add_wire → BindDisplay dispatched; после reload один бокс."""

    def test_bind_dispatch_called(self, qtbot):
        """add_wire(src → display.<id>.frame) dispatches BindDisplay."""
        services = _make_orchestrator_services()
        p, scene = _build_presenter_with_scene(services, qtbot)

        p.place_display("main", 600.0, 50.0)
        result = p.add_wire("cam.capture.frame", "display.main.frame")

        assert result is True
        # Binding должен появиться в repository
        displays = services.topology.load().to_dict().get("displays", [])
        assert any(d.get("display_id") == "main" for d in displays), (
            "BindDisplay должен создать запись в topo['displays']"
        )

    def test_no_duplicate_box_after_bind_and_reload(self, qtbot):
        """После BindDisplay + reload ровно один бокс (нет дубля placed+bound)."""
        services = _make_orchestrator_services()
        p, scene = _build_presenter_with_scene(services, qtbot)

        p.place_display("main", 600.0, 50.0)
        p.add_wire("cam.capture.frame", "display.main.frame")
        # dispatch(BindDisplay) → TopologyReplaced → reload (уже произошёл внутри add_wire)

        main_boxes = [item for item in scene.items() if isinstance(item, DisplayNodeItem) and item.node_id == "main"]
        assert len(main_boxes) == 1, f"Ожидался ровно 1 бокс 'main' после bind, найдено {len(main_boxes)}"

    def test_placed_id_kept_after_bind(self, qtbot):
        """ФИКС #1: после BindDisplay display_id ОСТАЁТСЯ в _placed_display_ids.

        Инвертирует прежний test_placed_id_removed_after_bind. Сохранение записи в set
        держит бокс живым при undo BindDisplay (возврат в placed-but-unbound). Дедуп по
        display_id в _build_display_nodes всё равно гарантирует ровно один бокс на scene.
        См. plans/pipeline-place-display-node.md (Task 2.1) + follow-up ФИКС #1.
        """
        services = _make_orchestrator_services()
        p, scene = _build_presenter_with_scene(services, qtbot)

        p.place_display("main", 600.0, 50.0)
        assert "main" in p._placed_display_ids

        p.add_wire("cam.capture.frame", "display.main.frame")

        # ФИКС #1: после bind display_id НАМЕРЕННО остаётся в set (живучесть при undo)
        assert "main" in p._placed_display_ids, (
            "display_id должен ОСТАВАТЬСЯ в _placed_display_ids после BindDisplay (ФИКС #1: держит бокс живым при undo)"
        )

        # При этом на scene по-прежнему РОВНО ОДИН бокс (дедуп защищает от дубля)
        main_boxes = [item for item in scene.items() if isinstance(item, DisplayNodeItem) and item.node_id == "main"]
        assert len(main_boxes) == 1, (
            f"Несмотря на наличие id и в set, и в topo['displays'], бокс должен быть "
            f"ровно один (дедуп), найдено {len(main_boxes)}"
        )

    def test_box_still_on_scene_after_bind(self, qtbot):
        """Бокс остаётся на scene после BindDisplay (теперь рисуется как 'настоящий')."""
        services = _make_orchestrator_services()
        p, scene = _build_presenter_with_scene(services, qtbot)

        p.place_display("main", 600.0, 50.0)
        p.add_wire("cam.capture.frame", "display.main.frame")

        node = scene.get_node("main")
        assert node is not None, "Бокс должен остаться на scene после BindDisplay"
        assert isinstance(node, DisplayNodeItem)


# ===========================================================================
# Сценарий 5: Fan-in (два источника → один display_id)
# ===========================================================================


class TestFanInDisplay:
    """Fan-in: два источника привязаны к одному display_id."""

    def test_one_box_two_binding_edges(self, qtbot):
        """Fan-in: один бокс, два binding-ребра от двух источников."""
        topo = {
            "processes": [
                {"process_name": "cam", "plugins": [{"plugin_name": "capture"}]},
                {"process_name": "proc", "plugins": [{"plugin_name": "blur"}]},
            ],
            "wires": [],
            "displays": [],
        }
        services = make_pipeline_services_with_orchestrator(
            topology=topo,
            plugin_specs=_PLUGIN_SPECS,
            display_ids={"main", "preview"},
        )
        p, scene = _build_presenter_with_scene(services, qtbot)

        # Разместить бокс вручную (необязательно, bind создаст его через topo)
        p.place_display("main", 600.0, 50.0)

        # Привязать два источника к одному каналу
        ok1 = p.add_wire("cam.capture.frame", "display.main.frame")
        ok2 = p.add_wire("proc.blur.frame", "display.main.frame")
        assert ok1 is True
        assert ok2 is True

        # Ровно один бокс с id «main»
        main_boxes = [item for item in scene.items() if isinstance(item, DisplayNodeItem) and item.node_id == "main"]
        assert len(main_boxes) == 1, f"Fan-in: ожидался 1 бокс 'main', найдено {len(main_boxes)}"

        # Два binding-ребра (cam→main и proc→main)
        assert scene.edge_count() == 2, f"Fan-in: ожидалось 2 ребра, найдено {scene.edge_count()}"

    def test_fan_in_displays_in_repo(self, qtbot):
        """Fan-in: в topo['displays'] хранятся два binding-вхождения."""
        topo = {
            "processes": [
                {"process_name": "cam", "plugins": [{"plugin_name": "capture"}]},
                {"process_name": "proc", "plugins": [{"plugin_name": "blur"}]},
            ],
            "wires": [],
            "displays": [],
        }
        services = make_pipeline_services_with_orchestrator(
            topology=topo,
            plugin_specs=_PLUGIN_SPECS,
            display_ids={"main", "preview"},
        )
        p, scene = _build_presenter_with_scene(services, qtbot)

        p.place_display("main", 600.0, 50.0)
        p.add_wire("cam.capture.frame", "display.main.frame")
        p.add_wire("proc.blur.frame", "display.main.frame")

        displays = services.topology.load().to_dict().get("displays", [])
        main_bindings = [d for d in displays if d.get("display_id") == "main"]
        assert len(main_bindings) == 2, f"Fan-in: ожидалось 2 binding-записи в repo, найдено {len(main_bindings)}"


# ===========================================================================
# Сценарий 6: Сброс при смене рецепта (_on_recipe_activated)
# ===========================================================================


class TestResetOnRecipeActivated:
    """place_display → _on_recipe_activated → _placed_display_ids пуст, бокс исчез."""

    def test_placed_set_cleared_on_recipe_activated(self, qtbot):
        """_on_recipe_activated очищает _placed_display_ids."""
        services = _make_orchestrator_services()
        p, scene = _build_presenter_with_scene(services, qtbot)

        p.place_display("main", 600.0, 50.0)
        p.place_display("preview", 750.0, 50.0)
        assert len(p._placed_display_ids) == 2

        p._on_recipe_activated(RecipeActivated(slug="new-recipe"))

        assert len(p._placed_display_ids) == 0, "_placed_display_ids должен быть пустым после смены рецепта"

    def test_unbound_box_disappears_on_recipe_activated(self, qtbot):
        """Непривязанный бокс исчезает с холста после смены рецепта."""
        services = _make_orchestrator_services()
        p, scene = _build_presenter_with_scene(services, qtbot)

        p.place_display("main", 600.0, 50.0)
        assert scene.get_node("main") is not None

        p._on_recipe_activated(RecipeActivated(slug="new-recipe"))

        node = scene.get_node("main")
        assert node is None, "Unbound бокс должен исчезнуть после _on_recipe_activated"

    def test_bound_display_stays_after_recipe_switch(self, qtbot):
        """Привязанный дисплей из нового рецепта рисуется корректно после смены."""
        # Топология уже содержит bound-дисплей (как в новом рецепте)
        topo_with_bound = {
            "processes": [
                {"process_name": "cam", "plugins": [{"plugin_name": "capture"}]},
            ],
            "wires": [],
            "displays": [
                {"node_id": "cam.capture.frame", "display_id": "preview"},
            ],
        }
        services = make_pipeline_services_with_orchestrator(
            topology=topo_with_bound,
            plugin_specs=_PLUGIN_SPECS,
            display_ids={"main", "preview"},
        )
        p, scene = _build_presenter_with_scene(services, qtbot)

        # Добавить unbound-бокс поверх уже bound-preview
        p.place_display("main", 600.0, 50.0)

        # Симулировать смену рецепта
        p._on_recipe_activated(RecipeActivated(slug="new-recipe"))

        # Unbound-бокс «main» должен исчезнуть
        assert scene.get_node("main") is None, "Unbound 'main' должен исчезнуть"

        # Bound-дисплей «preview» должен остаться (из topo["displays"])
        # После _on_recipe_activated вызывается reload из topology repo
        # topology repo содержит тот же bound-preview
        preview_node = scene.get_node("preview")
        assert preview_node is not None, "Bound 'preview' должен остаться на scene"
        assert isinstance(preview_node, DisplayNodeItem)

    def test_no_reset_on_topology_replaced(self, qtbot):
        """TopologyReplaced (мутация) НЕ очищает _placed_display_ids."""
        services = _make_orchestrator_services()
        p, scene = _build_presenter_with_scene(services, qtbot)

        p.place_display("main", 600.0, 50.0)

        # Обычная мутация — TopologyReplaced, а НЕ RecipeActivated
        p._on_topology_replaced(TopologyReplaced(reason="add-process"))

        assert "main" in p._placed_display_ids, (
            "_placed_display_ids не должен очищаться от TopologyReplaced (только RecipeActivated)"
        )


# ===========================================================================
# ФИКС #1 (регресс): undo BindDisplay не теряет бокс
# ===========================================================================


class TestUndoAfterBindKeepsBox:
    """follow-up ФИКС #1: place → bind → undo → бокс остаётся (нет потери данных).

    Прежний код делал discard(display_id) после BindDisplay → при undo бокс исчезал
    из ОБОИХ источников (и из set, и из topo['displays']) безвозвратно. После ФИКСА #1
    id остаётся в set, поэтому undo возвращает бокс в placed-but-unbound состояние.
    """

    def test_undo_after_bind_keeps_box(self, qtbot):
        """place_display → add_wire(BindDisplay) → undo → get_node(id) не None."""
        services = _make_orchestrator_services()
        p, scene = _build_presenter_with_scene(services, qtbot)

        p.place_display("main", 600.0, 50.0)
        ok = p.add_wire("cam.capture.frame", "display.main.frame")
        assert ok is True

        # binding появился в repo
        displays = services.topology.load().to_dict().get("displays", [])
        assert any(d.get("display_id") == "main" for d in displays)

        # Ctrl+Z — отменяем BindDisplay через реальный orchestrator
        undone = services.commands.undo()
        assert undone is True, "undo BindDisplay должен сработать"

        # binding исчез из repo (теперь бокс держится только set'ом)
        displays_after = services.topology.load().to_dict().get("displays", [])
        assert not any(d.get("display_id") == "main" for d in displays_after), (
            "после undo binding 'main' не должен оставаться в topo['displays']"
        )

        # Главное: бокс остался на scene (placed-but-unbound, дорисован из set)
        node = scene.get_node("main")
        assert node is not None, (
            "ФИКС #1: бокс 'main' должен пережить undo BindDisplay "
            "(остаётся в _placed_display_ids → дорисовывается как unbound)"
        )
        assert isinstance(node, DisplayNodeItem)
        assert "main" in p._placed_display_ids


# ===========================================================================
# ФИКС #2 (#9, регресс): смешанное удаление — нет бокса-призрака
# ===========================================================================


class TestMixedRemoveSelected:
    """follow-up ФИКС #2: одновременное удаление process + unbound + bound боксов.

    Главный кейс бага: process итерируется первым → синхронный _on_topology_replaced
    от RemoveProcess рисует ещё-в-set unbound-бокс → призрак. Двухпроходный
    remove_selected с pre-pass устраняет это.
    """

    def _setup_mixed_scene(self, qtbot):
        """cam (process) + main (unbound) + preview (bound через place+add_wire)."""
        topo = {
            "processes": [
                {"process_name": "cam", "plugins": [{"plugin_name": "capture"}]},
                {"process_name": "proc", "plugins": [{"plugin_name": "blur"}]},
            ],
            "wires": [],
            "displays": [],
        }
        services = make_pipeline_services_with_orchestrator(
            topology=topo,
            plugin_specs=_PLUGIN_SPECS,
            display_ids={"main", "preview"},
        )
        p, scene = _build_presenter_with_scene(services, qtbot)

        # main — чисто-unbound бокс
        p.place_display("main", 600.0, 50.0)
        # preview — bound (place + add_wire → BindDisplay)
        p.place_display("preview", 750.0, 50.0)
        ok = p.add_wire("proc.blur.frame", "display.preview.frame")
        assert ok is True

        return services, p, scene

    def test_mixed_remove_process_first(self, qtbot):
        """Порядок [process, unbound, bound] — process первым (главный кейс бага)."""
        services, p, scene = self._setup_mixed_scene(qtbot)

        assert scene.get_node("cam") is not None
        assert scene.get_node("main") is not None
        assert scene.get_node("preview") is not None

        p.remove_selected(["cam", "main", "preview"])

        # Чисто-unbound бокс «main» исчез без призрака
        assert scene.get_node("main") is None, (
            "ФИКС #2: unbound 'main' не должен оставаться призраком при смешанном удалении с process-первым порядком"
        )
        # process «cam» удалён (RemoveProcess dispatched → topo больше не содержит)
        assert scene.get_node("cam") is None
        topo = services.topology.load().to_dict()
        assert not any(pr.get("process_name") == "cam" for pr in topo.get("processes", [])), (
            "RemoveProcess для 'cam' должен быть dispatched"
        )
        # bound «preview» отвязан (UnbindDisplay dispatched → нет в topo['displays'])
        assert not any(d.get("display_id") == "preview" for d in topo.get("displays", [])), (
            "UnbindDisplay для 'preview' должен быть dispatched"
        )

        # dispatcher здесь — реальный orchestrator (нет .dispatched); факт dispatch
        # UnbindDisplay/RemoveProcess проверен по repo выше. Дополнительно: на scene
        # нет дублей/призраков display-боксов.
        display_items = [item for item in scene.items() if isinstance(item, DisplayNodeItem)]
        assert display_items == [], (
            f"После смешанного удаления на scene не должно остаться display-боксов, "
            f"найдено {[it.node_id for it in display_items]}"
        )
        # main больше не в set
        assert "main" not in p._placed_display_ids
        assert "preview" not in p._placed_display_ids

    def test_mixed_remove_unbound_first(self, qtbot):
        """Порядок [unbound, bound, process] — другой порядок, тот же результат."""
        services, p, scene = self._setup_mixed_scene(qtbot)

        p.remove_selected(["main", "preview", "cam"])

        assert scene.get_node("main") is None
        assert scene.get_node("cam") is None
        display_items = [item for item in scene.items() if isinstance(item, DisplayNodeItem)]
        assert display_items == [], (
            f"Призрак/дубль display-бокса при порядке unbound-первым: {[it.node_id for it in display_items]}"
        )

    def test_mixed_remove_bound_between(self, qtbot):
        """Порядок [bound, process, unbound] — bound в середине."""
        services, p, scene = self._setup_mixed_scene(qtbot)

        p.remove_selected(["preview", "cam", "main"])

        assert scene.get_node("main") is None
        display_items = [item for item in scene.items() if isinstance(item, DisplayNodeItem)]
        assert display_items == []


# ===========================================================================
# #10: идемпотентность place_display с проверкой позиции
# ===========================================================================


class TestPlaceDisplayPositionUpdate:
    """#10: повторный place_display обновляет позицию (set дедуплицирует, но pos новая)."""

    def test_repeated_place_updates_position(self, qtbot):
        """place_display(main,600,50) → place_display(main,650,80): pos = (650,80)."""
        services = _make_orchestrator_services()
        p, scene = _build_presenter_with_scene(services, qtbot)

        p.place_display("main", 600.0, 50.0)
        p.place_display("main", 650.0, 80.0)

        # _gui_positions обновлён на последнюю позицию
        assert p._gui_positions["main"] == (650.0, 80.0), (
            f"Позиция в _gui_positions должна обновиться на (650,80), получено {p._gui_positions.get('main')}"
        )

        # И сам бокс на scene стоит в новой позиции
        node = scene.get_node("main")
        assert node is not None
        assert node.pos().x() == pytest.approx(650.0)
        assert node.pos().y() == pytest.approx(80.0)


# ===========================================================================
# #11: place_display для канала, которого нет в каталоге
# ===========================================================================


class TestPlaceDisplayUnknownChannel:
    """#11: place_display с display_id, которого НЕТ в FakeDisplayCatalog."""

    def test_unknown_channel_box_created_empty_name(self, qtbot):
        """Бокс создан, display_name пустое (резолв вернул '') либо = id."""
        # Каталог знает только main/preview; ставим неизвестный «ghost»
        services = _make_orchestrator_services()
        p, scene = _build_presenter_with_scene(services, qtbot)

        p.place_display("ghost", 600.0, 50.0)

        node = scene.get_node("ghost")
        assert node is not None, "Бокс для неизвестного канала всё равно должен создаться"
        assert isinstance(node, DisplayNodeItem)
        # _resolve_display_name вернул "" (канала нет в каталоге) →
        # display_name либо пустое, либо равно display_id (оба допустимы планом)
        resolved = p._resolve_display_name("ghost")
        assert resolved == "", "Неизвестный канал резолвится в пустое имя"


# ===========================================================================
# #12: повторный bind того же источника на тот же дисплей
# ===========================================================================


class TestRepeatBindSameSource:
    """#12: повторный add_wire(src → display.id.frame) не падает, дубль не создаётся."""

    def test_repeat_bind_same_source(self, qtbot):
        """Второй идентичный BindDisplay отвергается domain guard'ом → False, один бокс."""
        services = _make_orchestrator_services()
        p, scene = _build_presenter_with_scene(services, qtbot)

        p.place_display("main", 600.0, 50.0)

        ok1 = p.add_wire("cam.capture.frame", "display.main.frame")
        assert ok1 is True, "Первый bind должен пройти"

        # Повторный тот же bind: domain отвергает дубль (DomainError) →
        # presenter ловит и возвращает False (НЕ падает)
        ok2 = p.add_wire("cam.capture.frame", "display.main.frame")
        assert ok2 is False, "Повторный идентичный bind должен быть отвергнут (False)"

        # Ровно один бокс «main», binding не задвоился
        main_boxes = [item for item in scene.items() if isinstance(item, DisplayNodeItem) and item.node_id == "main"]
        assert len(main_boxes) == 1, f"После повторного bind ожидался 1 бокс, найдено {len(main_boxes)}"
        displays = services.topology.load().to_dict().get("displays", [])
        main_bindings = [d for d in displays if d.get("display_id") == "main"]
        assert len(main_bindings) == 1, f"Binding не должен задваиваться, найдено {len(main_bindings)}"
