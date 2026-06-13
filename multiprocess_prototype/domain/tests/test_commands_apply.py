# -*- coding: utf-8 -*-
"""
test_commands_apply.py -- тесты Project.apply() для всех 14 команд (Task B.4).

Тестирует:
  - каждую из 14 команд (happy path + rejection-сценарии)
  - каскадное удаление (RemoveProcess)
  - frozen-safety (apply не мутирует self)
  - apply возвращает новый экземпляр Project

In-memory fakes (не MagicMock) для Protocols.
"""

from __future__ import annotations

import pytest

from multiprocess_prototype.domain.commands import (
    ActivateRecipe,
    AddProcess,
    AssignTargetProcess,
    BindDisplay,
    ConnectWire,
    DeactivateRecipe,
    DisconnectWire,
    InsertPlugin,
    MovePlugin,
    RemovePlugin,
    RemoveProcess,
    RenameProcess,
    ReplaceTopology,
    SetPluginConfig,
    UnbindDisplay,
)
from multiprocess_prototype.domain.entities import (
    DisplayInstance,
    PluginInstance,
    Process,
    Project,
    Recipe,
    RecipeMeta,
    Topology,
    Wire,
)
from multiprocess_prototype.domain.entities.project import ApplyContext
from multiprocess_prototype.domain.errors import DomainError
from multiprocess_prototype.domain.events import (
    DisplayBound,
    DisplayUnbound,
    PluginConfigChanged,
    PluginInserted,
    PluginMoved,
    PluginRemoved,
    ProcessAdded,
    ProcessRemoved,
    ProcessRenamed,
    RecipeActivated,
    RecipeDeactivated,
    TargetProcessAssigned,
    TopologyReplaced,
    WireConnected,
    WireDisconnected,
)
from multiprocess_prototype.domain.tests._fakes import (
    FakeDisplayCatalog,
    FakePluginCatalog,
    FakeRecipeStore,
)


# ======================================================================
# Фикстуры
# ======================================================================


def _empty_project() -> Project:
    """Пустой проект для тестов."""
    return Project(topology=Topology())


def _project_with_processes(*names: str) -> Project:
    """Проект с указанными процессами (без плагинов)."""
    processes = tuple(Process(process_name=n) for n in names)
    return Project(topology=Topology(processes=processes))


def _empty_ctx() -> ApplyContext:
    """ApplyContext без catalogs (все None)."""
    return ApplyContext()


# ======================================================================
# AddProcess
# ======================================================================


def test_add_process_ok() -> None:
    """Добавление нового процесса в пустую топологию."""
    project = _empty_project()
    cmd = AddProcess(process_name="proc1")
    new_proj, events = project.apply(cmd, catalogs=_empty_ctx())

    assert len(new_proj.topology.processes) == 1
    assert new_proj.topology.processes[0].process_name == "proc1"
    assert len(events) == 1
    assert isinstance(events[0], ProcessAdded)
    assert events[0].process_name == "proc1"


def test_add_process_duplicate_raises() -> None:
    """Добавление процесса с дубликатом имени вызывает DomainError."""
    project = _project_with_processes("proc1")
    cmd = AddProcess(process_name="proc1")
    with pytest.raises(DomainError, match="process_name 'proc1' already exists"):
        project.apply(cmd, catalogs=_empty_ctx())


def test_add_process_with_unknown_plugin_raises() -> None:
    """Добавление процесса с неизвестным плагином вызывает DomainError."""
    project = _empty_project()
    cmd = AddProcess(
        process_name="proc1",
        plugins=(PluginInstance(plugin_name="unknown"),),
    )
    ctx = ApplyContext(plugins=FakePluginCatalog({"blur"}))
    with pytest.raises(DomainError, match="plugin 'unknown' not found"):
        project.apply(cmd, catalogs=ctx)


# ======================================================================
# RemoveProcess (с каскадным удалением)
# ======================================================================


def test_remove_process_cascade() -> None:
    """Каскадное удаление: 2 plugins, 3 wires к процессу, 1 display binding.

    Порядок событий:
      1. ProcessRemoved
      2. 3 x WireDisconnected
      3. 1 x DisplayUnbound
    """
    topology = Topology(
        processes=(
            Process(
                process_name="proc1",
                plugins=(
                    PluginInstance(plugin_name="blur"),
                    PluginInstance(plugin_name="resize"),
                ),
            ),
            Process(process_name="proc2"),
            Process(process_name="proc3"),
        ),
        wires=(
            Wire(source="proc1.blur", target="proc2"),  # затронут
            Wire(source="proc3", target="proc1.resize"),  # затронут
            Wire(source="proc1", target="proc3"),  # затронут
            Wire(source="proc2", target="proc3"),  # НЕ затронут
        ),
        displays=(
            DisplayInstance(
                node_id="proc1.blur.output",
                display_id="main",
            ),  # затронут
            DisplayInstance(
                node_id="proc2.plugin.output",
                display_id="secondary",
            ),  # НЕ затронут
        ),
    )
    project = Project(topology=topology)
    cmd = RemoveProcess(process_name="proc1")
    new_proj, events = project.apply(cmd, catalogs=_empty_ctx())

    # Процесс удалён
    assert len(new_proj.topology.processes) == 2
    assert all(p.process_name != "proc1" for p in new_proj.topology.processes)

    # Осталось только 1 wire (proc2 -> proc3)
    assert len(new_proj.topology.wires) == 1
    assert new_proj.topology.wires[0].source == "proc2"
    assert new_proj.topology.wires[0].target == "proc3"

    # Осталось только 1 display
    assert len(new_proj.topology.displays) == 1
    assert new_proj.topology.displays[0].node_id == "proc2.plugin.output"

    # Проверка порядка и типов событий
    assert len(events) == 5  # 1 ProcessRemoved + 3 WireDisconnected + 1 DisplayUnbound
    assert isinstance(events[0], ProcessRemoved)
    assert events[0].process_name == "proc1"

    wire_events = [e for e in events if isinstance(e, WireDisconnected)]
    assert len(wire_events) == 3

    display_events = [e for e in events if isinstance(e, DisplayUnbound)]
    assert len(display_events) == 1
    assert display_events[0].node_id == "proc1.blur.output"
    assert display_events[0].display_id == "main"


def test_remove_process_not_found_raises() -> None:
    """Удаление несуществующего процесса вызывает DomainError."""
    project = _empty_project()
    cmd = RemoveProcess(process_name="missing")
    with pytest.raises(DomainError, match="process 'missing' not found"):
        project.apply(cmd, catalogs=_empty_ctx())


# ======================================================================
# RenameProcess
# ======================================================================


def test_rename_process_ok() -> None:
    """Переименование процесса обновляет wires, display bindings и
    перекрёстные ссылки target_process/chain_targets (H1)."""
    topology = Topology(
        processes=(
            Process(process_name="old_name"),
            # "other" маршрутизирует на old_name через оба механизма
            Process(process_name="other", target_process="old_name", chain_targets=("old_name", "third")),
            Process(process_name="third"),
        ),
        wires=(
            Wire(source="old_name.blur", target="other"),
            Wire(source="other", target="old_name"),
        ),
        displays=(DisplayInstance(node_id="old_name.blur.out", display_id="main"),),
    )
    project = Project(topology=topology)
    cmd = RenameProcess(old_name="old_name", new_name="new_name")
    new_proj, events = project.apply(cmd, catalogs=_empty_ctx())

    # Процесс переименован
    assert new_proj.topology.find_process("new_name") is not None
    assert new_proj.topology.find_process("old_name") is None

    # Wires обновлены
    assert new_proj.topology.wires[0].source == "new_name.blur"
    assert new_proj.topology.wires[1].target == "new_name"

    # Display bindings обновлены
    assert new_proj.topology.displays[0].node_id == "new_name.blur.out"

    # H1: перекрёстные IPC-ссылки в других процессах обновлены, stale-имени нет
    other = new_proj.topology.find_process("other")
    assert other is not None
    assert other.target_process == "new_name"
    assert other.chain_targets == ("new_name", "third")  # third не тронут, порядок сохранён

    assert len(events) == 1
    assert isinstance(events[0], ProcessRenamed)
    assert events[0].old_name == "old_name"
    assert events[0].new_name == "new_name"


def test_rename_process_collision_raises() -> None:
    """Переименование в уже занятое имя вызывает DomainError."""
    project = _project_with_processes("a", "b")
    cmd = RenameProcess(old_name="a", new_name="b")
    with pytest.raises(DomainError, match="process_name 'b' already exists"):
        project.apply(cmd, catalogs=_empty_ctx())


def test_rename_process_not_found_raises() -> None:
    """Переименование несуществующего процесса вызывает DomainError."""
    project = _project_with_processes("a")
    cmd = RenameProcess(old_name="missing", new_name="new")
    with pytest.raises(DomainError, match="process 'missing' not found"):
        project.apply(cmd, catalogs=_empty_ctx())


# ======================================================================
# InsertPlugin
# ======================================================================


def test_insert_plugin_ok() -> None:
    """Вставка плагина в процесс (append)."""
    project = _project_with_processes("proc1")
    plugin = PluginInstance(plugin_name="blur")
    cmd = InsertPlugin(process_name="proc1", plugin=plugin)
    new_proj, events = project.apply(cmd, catalogs=_empty_ctx())

    proc = new_proj.topology.find_process("proc1")
    assert proc is not None
    assert len(proc.plugins) == 1
    assert proc.plugins[0].plugin_name == "blur"

    assert len(events) == 1
    assert isinstance(events[0], PluginInserted)
    assert events[0].process_name == "proc1"
    assert events[0].index == 0  # append в пустой список


def test_insert_plugin_unknown_plugin_raises() -> None:
    """Вставка неизвестного плагина вызывает DomainError."""
    project = _project_with_processes("proc1")
    plugin = PluginInstance(plugin_name="unknown")
    cmd = InsertPlugin(process_name="proc1", plugin=plugin)
    ctx = ApplyContext(plugins=FakePluginCatalog({"blur"}))
    with pytest.raises(DomainError, match="plugin 'unknown' not found"):
        project.apply(cmd, catalogs=ctx)


def test_insert_plugin_default_index_appends() -> None:
    """index=None добавляет плагин в конец."""
    # Создаём процесс с одним плагином
    topology = Topology(
        processes=(
            Process(
                process_name="proc1",
                plugins=(PluginInstance(plugin_name="existing"),),
            ),
        ),
    )
    project = Project(topology=topology)
    new_plugin = PluginInstance(plugin_name="new_plugin")
    cmd = InsertPlugin(process_name="proc1", plugin=new_plugin, index=None)
    new_proj, events = project.apply(cmd, catalogs=_empty_ctx())

    proc = new_proj.topology.find_process("proc1")
    assert proc is not None
    assert len(proc.plugins) == 2
    assert proc.plugins[0].plugin_name == "existing"
    assert proc.plugins[1].plugin_name == "new_plugin"
    assert events[0].index == 1  # type: ignore[union-attr]


def test_insert_plugin_explicit_index() -> None:
    """Вставка плагина по явному индексу."""
    topology = Topology(
        processes=(
            Process(
                process_name="proc1",
                plugins=(
                    PluginInstance(plugin_name="first"),
                    PluginInstance(plugin_name="last"),
                ),
            ),
        ),
    )
    project = Project(topology=topology)
    new_plugin = PluginInstance(plugin_name="middle")
    cmd = InsertPlugin(process_name="proc1", plugin=new_plugin, index=1)
    new_proj, events = project.apply(cmd, catalogs=_empty_ctx())

    proc = new_proj.topology.find_process("proc1")
    assert proc is not None
    assert len(proc.plugins) == 3
    assert proc.plugins[0].plugin_name == "first"
    assert proc.plugins[1].plugin_name == "middle"
    assert proc.plugins[2].plugin_name == "last"
    assert events[0].index == 1  # type: ignore[union-attr]


def test_insert_plugin_process_not_found_raises() -> None:
    """Вставка плагина в несуществующий процесс вызывает DomainError."""
    project = _empty_project()
    plugin = PluginInstance(plugin_name="blur")
    cmd = InsertPlugin(process_name="missing", plugin=plugin)
    with pytest.raises(DomainError, match="process 'missing' not found"):
        project.apply(cmd, catalogs=_empty_ctx())


# ======================================================================
# RemovePlugin
# ======================================================================


def test_remove_plugin_ok() -> None:
    """Удаление плагина по индексу."""
    topology = Topology(
        processes=(
            Process(
                process_name="proc1",
                plugins=(
                    PluginInstance(plugin_name="blur"),
                    PluginInstance(plugin_name="resize"),
                ),
            ),
        ),
    )
    project = Project(topology=topology)
    cmd = RemovePlugin(process_name="proc1", index=0)
    new_proj, events = project.apply(cmd, catalogs=_empty_ctx())

    proc = new_proj.topology.find_process("proc1")
    assert proc is not None
    assert len(proc.plugins) == 1
    assert proc.plugins[0].plugin_name == "resize"

    assert len(events) == 1
    assert isinstance(events[0], PluginRemoved)
    assert events[0].plugin_name == "blur"
    assert events[0].index == 0


def test_remove_plugin_invalid_index_raises() -> None:
    """Удаление плагина с невалидным индексом вызывает DomainError."""
    project = _project_with_processes("proc1")
    cmd = RemovePlugin(process_name="proc1", index=0)  # пустой список
    with pytest.raises(DomainError, match="plugin index 0 out of range"):
        project.apply(cmd, catalogs=_empty_ctx())


def test_remove_plugin_process_not_found_raises() -> None:
    """Удаление плагина из несуществующего процесса вызывает DomainError."""
    project = _empty_project()
    cmd = RemovePlugin(process_name="missing", index=0)
    with pytest.raises(DomainError, match="process 'missing' not found"):
        project.apply(cmd, catalogs=_empty_ctx())


# ======================================================================
# SetPluginConfig
# ======================================================================


def test_set_plugin_config_ok() -> None:
    """Установка значения поля конфигурации плагина."""
    topology = Topology(
        processes=(
            Process(
                process_name="proc1",
                plugins=(
                    PluginInstance(
                        plugin_name="blur",
                        config={"kernel_size": 3},
                    ),
                ),
            ),
        ),
    )
    project = Project(topology=topology)
    cmd = SetPluginConfig(
        process_name="proc1",
        plugin_index=0,
        field="kernel_size",
        value=5,
    )
    new_proj, events = project.apply(cmd, catalogs=_empty_ctx())

    proc = new_proj.topology.find_process("proc1")
    assert proc is not None
    assert proc.plugins[0].config["kernel_size"] == 5

    assert len(events) == 1
    assert isinstance(events[0], PluginConfigChanged)
    assert events[0].field == "kernel_size"
    assert events[0].value == 5


def test_set_plugin_config_adds_new_field() -> None:
    """Добавление нового поля в config плагина."""
    topology = Topology(
        processes=(
            Process(
                process_name="proc1",
                plugins=(PluginInstance(plugin_name="blur"),),
            ),
        ),
    )
    project = Project(topology=topology)
    cmd = SetPluginConfig(
        process_name="proc1",
        plugin_index=0,
        field="new_field",
        value="hello",
    )
    new_proj, events = project.apply(cmd, catalogs=_empty_ctx())
    proc = new_proj.topology.find_process("proc1")
    assert proc is not None
    assert proc.plugins[0].config["new_field"] == "hello"


# ======================================================================
# ConnectWire
# ======================================================================


def test_connect_wire_ok() -> None:
    """Подключение wire между двумя процессами."""
    project = _project_with_processes("a", "b")
    cmd = ConnectWire(source="a", target="b")
    new_proj, events = project.apply(cmd, catalogs=_empty_ctx())

    assert len(new_proj.topology.wires) == 1
    assert new_proj.topology.wires[0].source == "a"
    assert new_proj.topology.wires[0].target == "b"

    assert len(events) == 1
    assert isinstance(events[0], WireConnected)
    assert events[0].wire.source == "a"


def test_connect_wire_self_cycle_raises() -> None:
    """Wire из процесса в самого себя -- цикл."""
    project = _project_with_processes("a")
    cmd = ConnectWire(source="a", target="a")
    with pytest.raises(DomainError, match="cycle detected"):
        project.apply(cmd, catalogs=_empty_ctx())


def test_connect_wire_creates_cycle_raises() -> None:
    """Добавление wire, создающего цикл, вызывает DomainError."""
    topology = Topology(
        processes=(
            Process(process_name="a"),
            Process(process_name="b"),
            Process(process_name="c"),
        ),
        wires=(
            Wire(source="a", target="b"),
            Wire(source="b", target="c"),
        ),
    )
    project = Project(topology=topology)
    cmd = ConnectWire(source="c", target="a")  # замыкает цикл
    with pytest.raises(DomainError, match="cycle detected"):
        project.apply(cmd, catalogs=_empty_ctx())


def test_connect_wire_dangling_source_raises() -> None:
    """Wire с source, ссылающимся на несуществующий процесс."""
    project = _project_with_processes("a")
    cmd = ConnectWire(source="missing", target="a")
    with pytest.raises(DomainError, match="wire source process 'missing' not found"):
        project.apply(cmd, catalogs=_empty_ctx())


def test_connect_wire_dangling_target_raises() -> None:
    """Wire с target, ссылающимся на несуществующий процесс."""
    project = _project_with_processes("a")
    cmd = ConnectWire(source="a", target="missing")
    with pytest.raises(DomainError, match="wire target process 'missing' not found"):
        project.apply(cmd, catalogs=_empty_ctx())


# ======================================================================
# DisconnectWire
# ======================================================================


def test_disconnect_wire_ok() -> None:
    """Отключение существующего wire."""
    topology = Topology(
        processes=(
            Process(process_name="a"),
            Process(process_name="b"),
        ),
        wires=(Wire(source="a", target="b"),),
    )
    project = Project(topology=topology)
    cmd = DisconnectWire(source="a", target="b")
    new_proj, events = project.apply(cmd, catalogs=_empty_ctx())

    assert len(new_proj.topology.wires) == 0
    assert len(events) == 1
    assert isinstance(events[0], WireDisconnected)
    assert events[0].source == "a"
    assert events[0].target == "b"


def test_disconnect_wire_not_found_raises() -> None:
    """Отключение несуществующего wire вызывает DomainError (fail fast).

    Решение по открытому вопросу: raise, не silent.
    Consumer должен знать, что отключение не состоялось.
    """
    project = _project_with_processes("a", "b")
    cmd = DisconnectWire(source="a", target="b")
    with pytest.raises(DomainError, match="wire a -> b not found"):
        project.apply(cmd, catalogs=_empty_ctx())


# ======================================================================
# BindDisplay
# ======================================================================


def test_bind_display_ok() -> None:
    """Привязка display к узлу."""
    project = _project_with_processes("proc1")
    cmd = BindDisplay(node_id="proc1.blur", display_id="main")
    new_proj, events = project.apply(cmd, catalogs=_empty_ctx())

    assert len(new_proj.topology.displays) == 1
    assert new_proj.topology.displays[0].node_id == "proc1.blur"
    assert new_proj.topology.displays[0].display_id == "main"

    assert len(events) == 1
    assert isinstance(events[0], DisplayBound)


def test_bind_display_unknown_display_raises() -> None:
    """Привязка несуществующего display вызывает DomainError."""
    project = _project_with_processes("proc1")
    cmd = BindDisplay(node_id="proc1.blur", display_id="unknown")
    ctx = ApplyContext(displays=FakeDisplayCatalog({"main"}))
    with pytest.raises(DomainError, match="display 'unknown' not found"):
        project.apply(cmd, catalogs=ctx)


# ======================================================================
# UnbindDisplay
# ======================================================================


def test_unbind_display_ok() -> None:
    """Отвязка display от узла."""
    topology = Topology(
        processes=(Process(process_name="proc1"),),
        displays=(DisplayInstance(node_id="proc1.blur", display_id="main"),),
    )
    project = Project(topology=topology)
    cmd = UnbindDisplay(node_id="proc1.blur", display_id="main")
    new_proj, events = project.apply(cmd, catalogs=_empty_ctx())

    assert len(new_proj.topology.displays) == 0
    assert len(events) == 1
    assert isinstance(events[0], DisplayUnbound)
    assert events[0].node_id == "proc1.blur"
    assert events[0].display_id == "main"


def test_unbind_display_fan_out_keeps_others() -> None:
    """Fan-out: один выход привязан к двум дисплеям — unbind снимает ровно одну пару."""
    topology = Topology(
        processes=(Process(process_name="proc1"),),
        displays=(
            DisplayInstance(node_id="proc1.blur.frame", display_id="main"),
            DisplayInstance(node_id="proc1.blur.frame", display_id="secondary"),
        ),
    )
    project = Project(topology=topology)
    cmd = UnbindDisplay(node_id="proc1.blur.frame", display_id="main")
    new_proj, _ = project.apply(cmd, catalogs=_empty_ctx())

    # Снята только пара (proc1.blur.frame, main); вторая привязка осталась
    assert len(new_proj.topology.displays) == 1
    assert new_proj.topology.displays[0].display_id == "secondary"
    assert new_proj.topology.displays[0].node_id == "proc1.blur.frame"


def test_bind_display_duplicate_pair_raises() -> None:
    """Повторная привязка той же пары (node_id, display_id) → DomainError."""
    topology = Topology(
        processes=(Process(process_name="proc1"),),
        displays=(DisplayInstance(node_id="proc1.blur.frame", display_id="main"),),
    )
    project = Project(topology=topology)
    cmd = BindDisplay(node_id="proc1.blur.frame", display_id="main")
    with pytest.raises(DomainError, match="already bound"):
        project.apply(cmd, catalogs=_empty_ctx())


def test_bind_display_fan_out_allowed() -> None:
    """Fan-out разрешён: один выход → два разных дисплея."""
    topology = Topology(
        processes=(Process(process_name="proc1"),),
        displays=(DisplayInstance(node_id="proc1.blur.frame", display_id="main"),),
    )
    project = Project(topology=topology)
    cmd = BindDisplay(node_id="proc1.blur.frame", display_id="secondary")
    new_proj, events = project.apply(cmd, catalogs=_empty_ctx())

    assert len(new_proj.topology.displays) == 2
    assert isinstance(events[0], DisplayBound)


# ======================================================================
# AssignTargetProcess
# ======================================================================


def test_assign_target_process_ok() -> None:
    """Назначение целевого процесса."""
    project = _project_with_processes("proc1", "proc2")
    cmd = AssignTargetProcess(process_name="proc1", target="proc2")
    new_proj, events = project.apply(cmd, catalogs=_empty_ctx())

    proc = new_proj.topology.find_process("proc1")
    assert proc is not None
    assert proc.target_process == "proc2"

    assert len(events) == 1
    assert isinstance(events[0], TargetProcessAssigned)
    assert events[0].target == "proc2"


def test_assign_target_process_none() -> None:
    """Сброс целевого процесса (target=None)."""
    topology = Topology(
        processes=(
            Process(process_name="proc1", target_process="proc2"),
            Process(process_name="proc2"),
        ),
    )
    project = Project(topology=topology)
    cmd = AssignTargetProcess(process_name="proc1", target=None)
    new_proj, events = project.apply(cmd, catalogs=_empty_ctx())

    proc = new_proj.topology.find_process("proc1")
    assert proc is not None
    assert proc.target_process is None

    assert len(events) == 1
    assert isinstance(events[0], TargetProcessAssigned)
    assert events[0].target is None


def test_assign_target_process_not_found_raises() -> None:
    """Назначение target для несуществующего процесса вызывает DomainError."""
    project = _empty_project()
    cmd = AssignTargetProcess(process_name="missing", target="proc2")
    with pytest.raises(DomainError, match="process 'missing' not found"):
        project.apply(cmd, catalogs=_empty_ctx())


# ======================================================================
# ActivateRecipe
# ======================================================================


def test_activate_recipe_ok() -> None:
    """Активация рецепта из in-memory RecipeStore."""
    recipe_blueprint = Topology(
        processes=(Process(process_name="r_proc"),),
    )
    recipe = Recipe(
        meta=RecipeMeta(name="demo", created_at="2026-01-01T00:00:00"),
        blueprint=recipe_blueprint,
    )
    store = FakeRecipeStore({"demo": recipe})
    ctx = ApplyContext(recipes=store)

    project = _empty_project()
    cmd = ActivateRecipe(slug="demo")
    new_proj, events = project.apply(cmd, catalogs=ctx)

    assert new_proj.active_recipe == "demo"
    assert len(new_proj.topology.processes) == 1
    assert new_proj.topology.processes[0].process_name == "r_proc"

    assert len(events) == 2
    assert isinstance(events[0], TopologyReplaced)
    assert events[0].reason == "recipe:demo"
    assert isinstance(events[1], RecipeActivated)
    assert events[1].slug == "demo"


def test_activate_recipe_no_store_raises() -> None:
    """Активация рецепта без RecipeStore вызывает DomainError."""
    project = _empty_project()
    cmd = ActivateRecipe(slug="demo")
    ctx = ApplyContext(recipes=None)
    with pytest.raises(DomainError, match="recipe_store unavailable"):
        project.apply(cmd, catalogs=ctx)


def test_activate_recipe_unknown_raises() -> None:
    """Активация несуществующего рецепта вызывает DomainError."""
    store = FakeRecipeStore({})
    ctx = ApplyContext(recipes=store)
    project = _empty_project()
    cmd = ActivateRecipe(slug="nonexistent")
    with pytest.raises(DomainError, match="recipe 'nonexistent' not found"):
        project.apply(cmd, catalogs=ctx)


def test_activate_recipe_with_cycle_raises() -> None:
    """Рецепт с циклом в blueprint вызывает DomainError при активации."""
    cyclic_blueprint = Topology(
        processes=(
            Process(process_name="a"),
            Process(process_name="b"),
        ),
        wires=(
            Wire(source="a", target="b"),
            Wire(source="b", target="a"),
        ),
    )
    recipe = Recipe(
        meta=RecipeMeta(name="cyclic", created_at="2026-01-01T00:00:00"),
        blueprint=cyclic_blueprint,
    )
    store = FakeRecipeStore({"cyclic": recipe})
    ctx = ApplyContext(recipes=store)
    project = _empty_project()
    cmd = ActivateRecipe(slug="cyclic")
    with pytest.raises(DomainError, match="cycle detected"):
        project.apply(cmd, catalogs=ctx)


# ======================================================================
# DeactivateRecipe
# ======================================================================


def test_deactivate_recipe_ok() -> None:
    """Сброс активного рецепта."""
    project = Project(topology=Topology(), active_recipe="old_recipe")
    cmd = DeactivateRecipe()
    new_proj, events = project.apply(cmd, catalogs=_empty_ctx())

    assert new_proj.active_recipe is None
    assert len(events) == 1
    assert isinstance(events[0], RecipeDeactivated)


# ======================================================================
# ReplaceTopology
# ======================================================================


def test_replace_topology_ok() -> None:
    """Замена топологии целиком."""
    new_topo = Topology(
        processes=(
            Process(process_name="x"),
            Process(process_name="y"),
        ),
        wires=(Wire(source="x", target="y"),),
    )
    project = _empty_project()
    cmd = ReplaceTopology(topology=new_topo, reason="test_replace")
    new_proj, events = project.apply(cmd, catalogs=_empty_ctx())

    assert len(new_proj.topology.processes) == 2
    assert len(new_proj.topology.wires) == 1

    assert len(events) == 1
    assert isinstance(events[0], TopologyReplaced)
    assert events[0].reason == "test_replace"


def test_replace_topology_cycle_raises() -> None:
    """Замена на топологию с циклом вызывает DomainError."""
    cyclic_topo = Topology(
        processes=(
            Process(process_name="a"),
            Process(process_name="b"),
            Process(process_name="c"),
        ),
        wires=(
            Wire(source="a", target="b"),
            Wire(source="b", target="c"),
            Wire(source="c", target="a"),
        ),
    )
    project = _empty_project()
    cmd = ReplaceTopology(topology=cyclic_topo, reason="test")
    with pytest.raises(DomainError, match="cycle detected"):
        project.apply(cmd, catalogs=_empty_ctx())


def test_replace_topology_duplicate_names_raises() -> None:
    """Замена на топологию с дублирующимися именами вызывает DomainError."""
    bad_topo = Topology(
        processes=(
            Process(process_name="a"),
            Process(process_name="a"),
        ),
    )
    project = _empty_project()
    cmd = ReplaceTopology(topology=bad_topo, reason="test")
    with pytest.raises(DomainError, match="process_name 'a' already exists"):
        project.apply(cmd, catalogs=_empty_ctx())


def test_replace_topology_dangling_wire_raises() -> None:
    """Замена на топологию с висячим wire вызывает DomainError."""
    bad_topo = Topology(
        processes=(Process(process_name="a"),),
        wires=(Wire(source="a", target="missing"),),
    )
    project = _empty_project()
    cmd = ReplaceTopology(topology=bad_topo, reason="test")
    with pytest.raises(DomainError, match="dangling wire target"):
        project.apply(cmd, catalogs=_empty_ctx())


# ======================================================================
# Frozen-safety + identity
# ======================================================================


def test_apply_does_not_mutate_self() -> None:
    """apply() не мутирует исходный Project."""
    project = _project_with_processes("proc1")
    original_topo = project.topology

    cmd = AddProcess(process_name="proc2")
    new_proj, _ = project.apply(cmd, catalogs=_empty_ctx())

    # Оригинальный Project не изменился
    assert len(project.topology.processes) == 1
    assert project.topology is original_topo

    # Новый Project имеет обновлённую топологию
    assert len(new_proj.topology.processes) == 2


def test_apply_returns_new_project_instance() -> None:
    """apply() возвращает НОВЫЙ экземпляр Project, не self."""
    project = _project_with_processes("proc1")
    cmd = AddProcess(process_name="proc2")
    new_proj, _ = project.apply(cmd, catalogs=_empty_ctx())

    assert new_proj is not project
    assert new_proj != project  # Разное содержимое


def test_frozen_project_raises_on_mutation() -> None:
    """Попытка прямой мутации Project вызывает ошибку."""
    project = _empty_project()
    with pytest.raises(Exception):  # Pydantic ValidationError
        project.active_recipe = "something"  # type: ignore[misc]


# ======================================================================
# MovePlugin (Phase B)
# ======================================================================


def _project_chain() -> Project:
    """cam[capture] → proc[resize] → out[render], wired по портам."""
    cam = Process(process_name="cam", plugins=(PluginInstance(plugin_name="capture"),))
    proc = Process(process_name="proc", plugins=(PluginInstance(plugin_name="resize"),))
    out = Process(process_name="out", plugins=(PluginInstance(plugin_name="render"),))
    wires = (
        Wire(source="cam.capture.frame", target="proc.resize.frame"),
        Wire(source="proc.resize.frame", target="out.render.frame"),
    )
    return Project(topology=Topology(processes=(cam, proc, out), wires=wires))


def _plugin_names(proc: Process) -> list[str]:
    return [p.plugin_name for p in proc.plugins]


def test_move_plugin_appends_and_removes_empty_source() -> None:
    """Перенос единственного плагина → источник опустел и удалён, цель получила плагин."""
    project = _project_chain()
    # capture (cam[0]) → proc (в конец)
    new_proj, events = project.apply(
        MovePlugin(from_process="cam", from_index=0, to_process="proc"),
        catalogs=_empty_ctx(),
    )
    names = {p.process_name for p in new_proj.topology.processes}
    assert "cam" not in names  # пустой источник удалён
    proc = new_proj.topology.find_process("proc")
    assert _plugin_names(proc) == ["resize", "capture"]  # append в конец

    moved = [e for e in events if isinstance(e, PluginMoved)]
    assert len(moved) == 1 and moved[0].source_removed is True
    assert any(isinstance(e, ProcessRemoved) and e.process_name == "cam" for e in events)


def test_move_plugin_drops_intraprocess_wire() -> None:
    """Провод cam.capture→proc.resize становится внутрипроцессным → удаляется."""
    project = _project_chain()
    new_proj, _ = project.apply(
        MovePlugin(from_process="cam", from_index=0, to_process="proc"),
        catalogs=_empty_ctx(),
    )
    sources = {w.source for w in new_proj.topology.wires}
    targets = {w.target for w in new_proj.topology.wires}
    # cam.capture.frame → proc.resize.frame стал внутрипроцессным (оба в proc) → нет
    assert "cam.capture.frame" not in sources
    # внешний провод proc.resize.frame → out.render.frame сохранён
    assert "out.render.frame" in targets


def test_move_plugin_rewrites_external_wire_endpoint() -> None:
    """Endpoint провода, ссылающийся на перемещённый плагин, переписывается на новый процесс."""
    project = _project_chain()
    # resize (proc[0]) → out: теперь resize в out, источник proc опустел/удалён
    new_proj, _ = project.apply(
        MovePlugin(from_process="proc", from_index=0, to_process="out"),
        catalogs=_empty_ctx(),
    )
    names = {p.process_name for p in new_proj.topology.processes}
    assert "proc" not in names
    out = new_proj.topology.find_process("out")
    assert _plugin_names(out) == ["render", "resize"]
    # cam.capture.frame → proc.resize.frame: proc.resize → out.resize → cam.capture→out.resize
    assert any(w.source == "cam.capture.frame" and w.target == "out.resize.frame" for w in new_proj.topology.wires)


def test_move_plugin_reorder_same_process() -> None:
    """from==to → переупорядочивание внутри процесса, источник не удаляется."""
    proc = Process(
        process_name="p",
        plugins=(PluginInstance(plugin_name="a"), PluginInstance(plugin_name="b")),
    )
    project = Project(topology=Topology(processes=(proc,)))
    # to_index=None → append после удаления → ["b", "a"]
    new_proj, events = project.apply(
        MovePlugin(from_process="p", from_index=0, to_process="p"),
        catalogs=_empty_ctx(),
    )
    p = new_proj.topology.find_process("p")
    assert _plugin_names(p) == ["b", "a"]
    assert not any(isinstance(e, ProcessRemoved) for e in events)


def test_move_plugin_invalid_source_raises() -> None:
    project = _project_chain()
    with pytest.raises(DomainError, match="not found"):
        project.apply(MovePlugin(from_process="nope", from_index=0, to_process="proc"), catalogs=_empty_ctx())


def test_move_plugin_invalid_dest_raises() -> None:
    project = _project_chain()
    with pytest.raises(DomainError, match="not found"):
        project.apply(MovePlugin(from_process="cam", from_index=0, to_process="nope"), catalogs=_empty_ctx())


def test_move_plugin_invalid_index_raises() -> None:
    project = _project_chain()
    with pytest.raises(DomainError, match="out of range"):
        project.apply(MovePlugin(from_process="cam", from_index=5, to_process="proc"), catalogs=_empty_ctx())


def test_move_plugin_does_not_mutate_self() -> None:
    project = _project_chain()
    before = len(project.topology.processes)
    project.apply(MovePlugin(from_process="cam", from_index=0, to_process="proc"), catalogs=_empty_ctx())
    assert len(project.topology.processes) == before  # self не изменился
    assert project.topology.find_process("cam") is not None
