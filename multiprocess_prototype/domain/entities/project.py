# -*- coding: utf-8 -*-
"""
Project -- корневой агрегат domain-слоя.

Хранит текущую топологию (editor state) и slug активного рецепта.
active_recipe -- строковый slug, не материализованный Recipe-объект.
Материализация рецепта выполняется adapter-ом в Phase C через RecipeStore.read(slug).

Метод apply() (Task B.4) -- чистая функция:
  (Project, ProjectCommand, ApplyContext) -> (new Project, list[ProjectEvent])
Никаких side effects: не пишет в YAML, не дёргает IPC, не публикует события.
Publishing делается на уровне выше (EventBus / adapter в Phase C/D).

Invariants проверяются внутри apply():
  - уникальность имён процессов
  - отсутствие висячих wire-ов
  - отсутствие циклов (DAG)
  - валидность ссылок на плагины (через PluginCatalog)
  - валидность ссылок на дисплеи (через DisplayCatalog)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import ConfigDict
from typing_extensions import Annotated, Self

from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase

from .display import DisplayInstance
from .process import Process
from .topology import Topology
from .wire import Wire
from ..commands import (
    ActivateRecipe,
    AddProcess,
    AssignTargetProcess,
    BindDisplay,
    ConnectWire,
    DeactivateRecipe,
    DisconnectWire,
    InsertPlugin,
    MovePlugin,
    ProjectCommand,
    RemovePlugin,
    RemoveProcess,
    RenameProcess,
    ReplaceTopology,
    SetPluginConfig,
    UnbindDisplay,
)
from ..events import (
    DisplayBound,
    DisplayUnbound,
    PluginConfigChanged,
    PluginInserted,
    PluginMoved,
    PluginRemoved,
    ProcessAdded,
    ProcessRemoved,
    ProcessRenamed,
    ProjectEvent,
    RecipeActivated,
    RecipeDeactivated,
    TargetProcessAssigned,
    TopologyReplaced,
    WireConnected,
    WireDisconnected,
)
from ..errors import DomainError
from ..protocols import DisplayCatalog, PluginCatalog, RecipeStore


# ======================================================================
# ApplyContext -- облегчённая проекция AppServices для Project.apply()
# ======================================================================


@dataclass(frozen=True, slots=True)
class ApplyContext:
    """Сужённая проекция AppServices для Project.apply().

    Все поля -- Optional: invariants по None-catalog пропускаются. Это
    позволяет тестировать Project.apply в изоляции от full AppServices.

    В production-коде (Phase D) ApplyContext строится из AppServices:
        ctx = ApplyContext(
            plugins=app_services.plugins,
            displays=app_services.displays,
            recipes=app_services.recipes,
        )
    """

    plugins: PluginCatalog | None = None
    displays: DisplayCatalog | None = None
    recipes: RecipeStore | None = None


# ======================================================================
# Helpers: извлечение process_name из node_id
# ======================================================================


def _extract_process_from_node(node_id: str) -> str:
    """Извлекает имя процесса из node_id.

    Формат node_id:
      - ``process_name``
      - ``process_name.plugin_name``
      - ``process_name.plugin_name.port_name``

    Всегда берёт первый сегмент по точке.

    >>> _extract_process_from_node("cam.blur.output")
    'cam'
    >>> _extract_process_from_node("cam")
    'cam'
    """
    return node_id.split(".")[0]


# ======================================================================
# Invariants (helper-функции, вызываются из apply)
# ======================================================================


def _check_unique_process_names(topology: Topology) -> None:
    """Проверяет уникальность имён процессов в топологии.

    Raises:
        DomainError: если обнаружен дубликат имени.
    """
    seen: set[str] = set()
    for proc in topology.processes:
        if proc.process_name in seen:
            raise DomainError(f"process_name '{proc.process_name}' already exists")
        seen.add(proc.process_name)


def _check_no_dangling_wires(topology: Topology) -> None:
    """Проверяет, что каждый wire ссылается на существующий процесс.

    Нормализует source/target через _extract_process_from_node и
    проверяет наличие соответствующего процесса в topology.processes.

    Raises:
        DomainError: если source или target ссылается на несуществующий процесс.
    """
    process_names = {p.process_name for p in topology.processes}
    for wire in topology.wires:
        src_proc = _extract_process_from_node(wire.source)
        if src_proc not in process_names:
            raise DomainError(
                f"dangling wire source: process '{src_proc}' not found (wire {wire.source} -> {wire.target})"
            )
        tgt_proc = _extract_process_from_node(wire.target)
        if tgt_proc not in process_names:
            raise DomainError(
                f"dangling wire target: process '{tgt_proc}' not found (wire {wire.source} -> {wire.target})"
            )


def _check_no_cycles(topology: Topology) -> None:
    """Проверяет отсутствие циклов в графе wire-связей между процессами.

    Строит направленный граф process_source -> process_target из wires,
    затем выполняет DFS с тремя цветами (white/gray/black).
    На back-edge (gray -> gray) -- DomainError.

    Raises:
        DomainError: если обнаружен цикл.
    """
    # Построить adjacency list
    graph: dict[str, list[str]] = {}
    for proc in topology.processes:
        graph.setdefault(proc.process_name, [])
    for wire in topology.wires:
        src = _extract_process_from_node(wire.source)
        tgt = _extract_process_from_node(wire.target)
        graph.setdefault(src, []).append(tgt)
        graph.setdefault(tgt, [])

    # DFS three-color: 0=white, 1=gray, 2=black
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {node: WHITE for node in graph}

    def _dfs(node: str) -> None:
        color[node] = GRAY
        for neighbor in graph[node]:
            if color[neighbor] == GRAY:
                raise DomainError(f"cycle detected: {node} -> {neighbor}")
            if color[neighbor] == WHITE:
                _dfs(neighbor)
        color[node] = BLACK

    for node in graph:
        if color[node] == WHITE:
            _dfs(node)


def _check_plugin_references(
    topology: Topology,
    catalogs: ApplyContext,
) -> None:
    """Проверяет, что все plugin_name в topology существуют в каталоге.

    Если catalogs.plugins is None -- invariant пропускается.

    Raises:
        DomainError: если плагин не найден в каталоге.
    """
    if catalogs.plugins is None:
        return
    for proc in topology.processes:
        for pi in proc.plugins:
            if catalogs.plugins.resolve(pi.plugin_name) is None:
                raise DomainError(f"plugin '{pi.plugin_name}' not found in catalog")


def _check_display_references(
    topology: Topology,
    catalogs: ApplyContext,
) -> None:
    """Проверяет, что все display_id в topology существуют в каталоге.

    Если catalogs.displays is None -- invariant пропускается.

    Raises:
        DomainError: если дисплей не найден в каталоге.
    """
    if catalogs.displays is None:
        return
    for di in topology.displays:
        if catalogs.displays.resolve(di.display_id) is None:
            raise DomainError(f"display '{di.display_id}' not found in catalog")


def _check_recipe_self_display_references(recipe: Any) -> None:
    """Привязки blueprint.displays активируемого рецепта → его СОБСТВЕННЫЕ recipe.displays.

    При активации каталог (DisplayCatalogFromRecipe) recipe-scoped и указывает на ЕЩЁ
    активный (старый) рецепт — активируемый станет активным лишь ПОСЛЕ этого apply
    (chicken-and-egg). Поэтому привязки нового рецепта нельзя проверять против старого
    каталога: рецепт с новым дисплеем (напр. 'mask') ложно роняет активацию.

    Рецепт самодостаточен: blueprint.displays ссылается на recipe.displays того же
    рецепта (Recipe-сущность это и гарантирует). Проверяем по ним — это и есть
    «каталог синхронизируется с дисплеями рецепта»: после активации recipe-scoped
    каталог увидит ровно эти определения.
    """
    own_ids = {d.id for d in recipe.displays}
    for binding in recipe.blueprint.displays:
        if binding.display_id not in own_ids:
            raise DomainError(f"display '{binding.display_id}' not found in catalog")


def _validate_topology(topology: Topology, catalogs: ApplyContext) -> None:
    """Выполняет все 5 invariants в одном проходе."""
    _check_unique_process_names(topology)
    _check_no_dangling_wires(topology)
    _check_no_cycles(topology)
    _check_plugin_references(topology, catalogs)
    _check_display_references(topology, catalogs)


# ======================================================================
# Project -- корневой агрегат
# ======================================================================


class Project(SchemaBase):
    """Корневой агрегат: текущая топология + активный рецепт (editor state).

    Project не хранит runtime-состояние (PID'ы, lifecycle, метрики).
    Runtime snapshot -- отдельный aggregate, добавляется в Phase E/G.
    """

    model_config = ConfigDict(
        frozen=True,
        populate_by_name=True,
        extra="forbid",
    )

    topology: Annotated[Topology, FieldMeta("Текущая топология проекта (editor state)")]
    active_recipe: Annotated[
        str | None,
        FieldMeta("Slug активного рецепта (None -- рецепт не выбран)"),
    ] = None

    # ------------------------------------------------------------------
    # Фабричные методы
    # ------------------------------------------------------------------

    @classmethod
    def from_topology(cls, topology: Topology) -> "Project":
        """Создать Project с заданной топологией и без активного рецепта.

        Convenience factory для bootstrap при старте приложения:
            project = Project.from_topology(topology_repo.load())

        Post:
            - project.topology is topology
            - project.active_recipe is None
        """
        return cls(topology=topology, active_recipe=None)

    # ------------------------------------------------------------------
    # Сериализация
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Создать Project из словаря."""
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        """Сериализовать в dict."""
        return self.model_dump(mode="json")

    # ------------------------------------------------------------------
    # apply() -- центральный метод aggregate root
    # ------------------------------------------------------------------

    def apply(
        self,
        command: ProjectCommand,
        *,
        catalogs: ApplyContext,
    ) -> tuple["Project", list[ProjectEvent]]:
        """Применяет команду к текущему Project.

        Pre:
          - command -- элемент ProjectCommand union.
          - catalogs -- ApplyContext с опциональными catalog'ами.
        Post:
          - возвращает (new_project, events).
          - new_project -- НОВЫЙ frozen Project (не self).
          - events -- список ProjectEvent, отражающих все изменения.
        Raises:
          - DomainError при нарушении invariant.
        Side effects: НЕТ. Чистая функция.
        """
        match command:
            case AddProcess() as cmd:
                return self._apply_add_process(cmd, catalogs)
            case RemoveProcess() as cmd:
                return self._apply_remove_process(cmd, catalogs)
            case RenameProcess() as cmd:
                return self._apply_rename_process(cmd, catalogs)
            case InsertPlugin() as cmd:
                return self._apply_insert_plugin(cmd, catalogs)
            case RemovePlugin() as cmd:
                return self._apply_remove_plugin(cmd, catalogs)
            case SetPluginConfig() as cmd:
                return self._apply_set_plugin_config(cmd, catalogs)
            case MovePlugin() as cmd:
                return self._apply_move_plugin(cmd, catalogs)
            case ConnectWire() as cmd:
                return self._apply_connect_wire(cmd, catalogs)
            case DisconnectWire() as cmd:
                return self._apply_disconnect_wire(cmd, catalogs)
            case BindDisplay() as cmd:
                return self._apply_bind_display(cmd, catalogs)
            case UnbindDisplay() as cmd:
                return self._apply_unbind_display(cmd, catalogs)
            case AssignTargetProcess() as cmd:
                return self._apply_assign_target_process(cmd, catalogs)
            case ActivateRecipe() as cmd:
                return self._apply_activate_recipe(cmd, catalogs)
            case DeactivateRecipe() as cmd:
                return self._apply_deactivate_recipe(cmd, catalogs)
            case ReplaceTopology() as cmd:
                return self._apply_replace_topology(cmd, catalogs)

    # ------------------------------------------------------------------
    # Приватные handler'ы для каждой команды
    # ------------------------------------------------------------------

    def _apply_add_process(
        self,
        cmd: AddProcess,
        catalogs: ApplyContext,
    ) -> tuple["Project", list[ProjectEvent]]:
        """Добавить новый Process в топологию.

        Invariants:
          - уникальность имени процесса
          - все plugin_name из cmd.plugins существуют в каталоге (если catalogs.plugins не None)
        """
        # Проверка уникальности имени
        if self.topology.find_process(cmd.process_name) is not None:
            raise DomainError(f"process_name '{cmd.process_name}' already exists")

        # Проверка ссылок на плагины
        if catalogs.plugins is not None:
            for pi in cmd.plugins:
                if catalogs.plugins.resolve(pi.plugin_name) is None:
                    raise DomainError(f"plugin '{pi.plugin_name}' not found in catalog")

        new_process = Process(
            process_name=cmd.process_name,
            plugins=cmd.plugins,
        )
        new_topology = self.topology.model_copy(update={"processes": (*self.topology.processes, new_process)})
        new_project = self.model_copy(update={"topology": new_topology})
        events: list[ProjectEvent] = [ProcessAdded(process_name=cmd.process_name, process=new_process)]
        return new_project, events

    def _apply_remove_process(
        self,
        cmd: RemoveProcess,
        catalogs: ApplyContext,
    ) -> tuple["Project", list[ProjectEvent]]:
        """Удалить Process из топологии с каскадом.

        Порядок событий (зафиксирован):
          1. ProcessRemoved(process_name)
          2. N x WireDisconnected для каждого wire, связанного с процессом
          3. M x DisplayUnbound для каждого display binding, связанного с процессом
        """
        if self.topology.find_process(cmd.process_name) is None:
            raise DomainError(f"process '{cmd.process_name}' not found")

        events: list[ProjectEvent] = [ProcessRemoved(process_name=cmd.process_name)]

        # Каскад: удаляем wires, связанные с процессом
        affected_wires = self.topology.find_wires_for(cmd.process_name)
        remaining_wires = tuple(w for w in self.topology.wires if w not in affected_wires)
        for wire in affected_wires:
            events.append(WireDisconnected(source=wire.source, target=wire.target))

        # Каскад: удаляем display bindings, связанные с процессом
        affected_displays = self.topology.find_display_bindings_for(cmd.process_name)
        remaining_displays = tuple(d for d in self.topology.displays if d not in affected_displays)
        for di in affected_displays:
            events.append(DisplayUnbound(node_id=di.node_id, display_id=di.display_id))

        # Убираем процесс
        remaining_processes = tuple(p for p in self.topology.processes if p.process_name != cmd.process_name)

        new_topology = self.topology.model_copy(
            update={
                "processes": remaining_processes,
                "wires": remaining_wires,
                "displays": remaining_displays,
            }
        )
        new_project = self.model_copy(update={"topology": new_topology})
        return new_project, events

    def _apply_rename_process(
        self,
        cmd: RenameProcess,
        catalogs: ApplyContext,
    ) -> tuple["Project", list[ProjectEvent]]:
        """Переименовать Process в топологии.

        Invariants:
          - old_name существует
          - new_name уникально (не занято)
        """
        if self.topology.find_process(cmd.old_name) is None:
            raise DomainError(f"process '{cmd.old_name}' not found")
        if self.topology.find_process(cmd.new_name) is not None:
            raise DomainError(f"process_name '{cmd.new_name}' already exists")

        # Переименование процесса + обновление перекрёстных ссылок на его имя
        # в ДРУГИХ процессах: target_process (адрес IPC-команд) и chain_targets
        # (получатели chain-маршрутизации). Без этого после A→B процессы со
        # stale-ссылкой шлют IPC на несуществующий процесс — битая маршрутизация,
        # молча проявляется только в runtime (находка аудита H1).
        def _rename_refs(proc: Process) -> Process:
            updates: dict[str, Any] = {}
            if proc.process_name == cmd.old_name:
                updates["process_name"] = cmd.new_name
            if proc.target_process == cmd.old_name:
                updates["target_process"] = cmd.new_name
            if cmd.old_name in proc.chain_targets:
                updates["chain_targets"] = tuple(cmd.new_name if t == cmd.old_name else t for t in proc.chain_targets)
            return proc.model_copy(update=updates) if updates else proc

        new_processes = tuple(_rename_refs(p) for p in self.topology.processes)

        # Обновление wire-ов: заменяем source/target, если содержат old_name
        def _rename_node(node_id: str) -> str:
            proc_name = _extract_process_from_node(node_id)
            if proc_name == cmd.old_name:
                # Заменяем только первый сегмент
                parts = node_id.split(".", 1)
                if len(parts) > 1:
                    return f"{cmd.new_name}.{parts[1]}"
                return cmd.new_name
            return node_id

        new_wires = tuple(
            w.model_copy(
                update={
                    "source": _rename_node(w.source),
                    "target": _rename_node(w.target),
                }
            )
            for w in self.topology.wires
        )

        # Обновление display bindings: переименуем node_id
        new_displays = tuple(d.model_copy(update={"node_id": _rename_node(d.node_id)}) for d in self.topology.displays)

        new_topology = self.topology.model_copy(
            update={
                "processes": new_processes,
                "wires": new_wires,
                "displays": new_displays,
            }
        )
        new_project = self.model_copy(update={"topology": new_topology})
        events: list[ProjectEvent] = [ProcessRenamed(old_name=cmd.old_name, new_name=cmd.new_name)]
        return new_project, events

    def _apply_insert_plugin(
        self,
        cmd: InsertPlugin,
        catalogs: ApplyContext,
    ) -> tuple["Project", list[ProjectEvent]]:
        """Вставить PluginInstance в цепочку плагинов Process.

        index=None означает добавление в конец (append).

        Invariants:
          - процесс с cmd.process_name существует
          - plugin_name существует в каталоге (если catalogs.plugins не None)
        """
        proc = self.topology.find_process(cmd.process_name)
        if proc is None:
            raise DomainError(f"process '{cmd.process_name}' not found")

        # Проверка ссылки на плагин
        if catalogs.plugins is not None:
            if catalogs.plugins.resolve(cmd.plugin.plugin_name) is None:
                raise DomainError(f"plugin '{cmd.plugin.plugin_name}' not found in catalog")

        plugins_list = list(proc.plugins)
        if cmd.index is None:
            actual_index = len(plugins_list)
            plugins_list.append(cmd.plugin)
        else:
            if cmd.index < 0 or cmd.index > len(plugins_list):
                raise DomainError(
                    f"plugin index {cmd.index} out of range "
                    f"(process '{cmd.process_name}' has {len(plugins_list)} plugins)"
                )
            actual_index = cmd.index
            plugins_list.insert(cmd.index, cmd.plugin)

        updated_proc = proc.model_copy(update={"plugins": tuple(plugins_list)})
        new_processes = tuple(
            updated_proc if p.process_name == cmd.process_name else p for p in self.topology.processes
        )
        new_topology = self.topology.model_copy(update={"processes": new_processes})
        new_project = self.model_copy(update={"topology": new_topology})
        events: list[ProjectEvent] = [
            PluginInserted(
                process_name=cmd.process_name,
                plugin=cmd.plugin,
                index=actual_index,
            )
        ]
        return new_project, events

    def _apply_remove_plugin(
        self,
        cmd: RemovePlugin,
        catalogs: ApplyContext,
    ) -> tuple["Project", list[ProjectEvent]]:
        """Удалить PluginInstance из цепочки плагинов Process по индексу.

        Решение по открытому вопросу: invalid index -> DomainError (fail fast).
        """
        proc = self.topology.find_process(cmd.process_name)
        if proc is None:
            raise DomainError(f"process '{cmd.process_name}' not found")
        if cmd.index < 0 or cmd.index >= len(proc.plugins):
            raise DomainError(
                f"plugin index {cmd.index} out of range (process '{cmd.process_name}' has {len(proc.plugins)} plugins)"
            )

        removed_plugin = proc.plugins[cmd.index]
        plugins_list = list(proc.plugins)
        plugins_list.pop(cmd.index)

        updated_proc = proc.model_copy(update={"plugins": tuple(plugins_list)})
        new_processes = tuple(
            updated_proc if p.process_name == cmd.process_name else p for p in self.topology.processes
        )
        new_topology = self.topology.model_copy(update={"processes": new_processes})
        new_project = self.model_copy(update={"topology": new_topology})
        events: list[ProjectEvent] = [
            PluginRemoved(
                process_name=cmd.process_name,
                plugin_name=removed_plugin.plugin_name,
                index=cmd.index,
            )
        ]
        return new_project, events

    def _apply_move_plugin(
        self,
        cmd: MovePlugin,
        catalogs: ApplyContext,
    ) -> tuple["Project", list[ProjectEvent]]:
        """Перенести PluginInstance из одного процесса в другой (Phase B).

        Семантика:
          - плагин убирается из from_process[from_index], вставляется в to_process
            (в конец при to_index=None); from==to → переупорядочивание;
          - концы проводов/привязок «from_process.<plugin>.*» переписываются на
            «to_process.<plugin>.*» (плагин сменил процесс — endpoint меняет префикс);
          - провод, у которого после переписывания ОБА конца в одном процессе, стал
            внутрипроцессной (неявной) цепочкой — удаляется как явный wire;
          - опустевший процесс-источник удаляется (эмитится ProcessRemoved);
          - результат валидируется (_validate_topology: dangling/циклы/каталог).
        """
        from_proc = self.topology.find_process(cmd.from_process)
        if from_proc is None:
            raise DomainError(f"process '{cmd.from_process}' not found")
        to_proc = self.topology.find_process(cmd.to_process)
        if to_proc is None:
            raise DomainError(f"process '{cmd.to_process}' not found")
        if cmd.from_index < 0 or cmd.from_index >= len(from_proc.plugins):
            raise DomainError(
                f"plugin index {cmd.from_index} out of range "
                f"(process '{cmd.from_process}' has {len(from_proc.plugins)} plugins)"
            )

        plugin = from_proc.plugins[cmd.from_index]
        same_process = cmd.from_process == cmd.to_process

        if same_process:
            # Переупорядочивание внутри одного процесса.
            plugins_list = list(from_proc.plugins)
            plugins_list.pop(cmd.from_index)
            to_index = cmd.to_index if cmd.to_index is not None else len(plugins_list)
            if to_index < 0 or to_index > len(plugins_list):
                raise DomainError(f"to_index {to_index} out of range")
            plugins_list.insert(to_index, plugin)
            updated_from = from_proc.model_copy(update={"plugins": tuple(plugins_list)})
            updated_to = updated_from
            source_removed = False
        else:
            from_list = list(from_proc.plugins)
            from_list.pop(cmd.from_index)
            to_list = list(to_proc.plugins)
            to_index = cmd.to_index if cmd.to_index is not None else len(to_list)
            if to_index < 0 or to_index > len(to_list):
                raise DomainError(f"to_index {to_index} out of range")
            to_list.insert(to_index, plugin)
            updated_from = from_proc.model_copy(update={"plugins": tuple(from_list)})
            updated_to = to_proc.model_copy(update={"plugins": tuple(to_list)})
            source_removed = len(from_list) == 0

        # Пересобрать процессы (источник опустел → выкинуть).
        new_processes_list: list[Process] = []
        for p in self.topology.processes:
            if p.process_name == cmd.from_process:
                if same_process:
                    new_processes_list.append(updated_from)
                elif not source_removed:
                    new_processes_list.append(updated_from)
                # source_removed → не добавляем (удаляем пустой процесс)
            elif p.process_name == cmd.to_process:
                new_processes_list.append(updated_to)
            else:
                new_processes_list.append(p)
        new_processes = tuple(new_processes_list)

        # Переписать endpoint'ы: from_process.<plugin>.* → to_process.<plugin>.*
        plugin_name = plugin.plugin_name

        def _rewrite(node_id: str) -> str:
            parts = node_id.split(".")
            if len(parts) >= 2 and parts[0] == cmd.from_process and parts[1] == plugin_name:
                parts[0] = cmd.to_process
                return ".".join(parts)
            return node_id

        new_wires_list = []
        for w in self.topology.wires:
            new_source = _rewrite(w.source)
            new_target = _rewrite(w.target)
            # Стал внутрипроцессным (оба конца в одном процессе) → неявная цепочка,
            # убираем явный wire.
            if _extract_process_from_node(new_source) == _extract_process_from_node(new_target):
                continue
            new_wires_list.append(w.model_copy(update={"source": new_source, "target": new_target}))
        new_wires = tuple(new_wires_list)

        new_displays = tuple(d.model_copy(update={"node_id": _rewrite(d.node_id)}) for d in self.topology.displays)

        new_topology = self.topology.model_copy(
            update={
                "processes": new_processes,
                "wires": new_wires,
                "displays": new_displays,
            }
        )

        # Валидация результата (dangling/циклы/уникальность/каталог).
        _validate_topology(new_topology, catalogs)

        new_project = self.model_copy(update={"topology": new_topology})
        events: list[ProjectEvent] = [
            PluginMoved(
                from_process=cmd.from_process,
                from_index=cmd.from_index,
                to_process=cmd.to_process,
                to_index=to_index,
                plugin=plugin,
                source_removed=source_removed,
            )
        ]
        if source_removed:
            events.append(ProcessRemoved(process_name=cmd.from_process))
        return new_project, events

    def _apply_set_plugin_config(
        self,
        cmd: SetPluginConfig,
        catalogs: ApplyContext,
    ) -> tuple["Project", list[ProjectEvent]]:
        """Установить значение поля конфигурации PluginInstance."""
        proc = self.topology.find_process(cmd.process_name)
        if proc is None:
            raise DomainError(f"process '{cmd.process_name}' not found")
        if cmd.plugin_index < 0 or cmd.plugin_index >= len(proc.plugins):
            raise DomainError(
                f"plugin index {cmd.plugin_index} out of range "
                f"(process '{cmd.process_name}' has {len(proc.plugins)} plugins)"
            )

        plugin = proc.plugins[cmd.plugin_index]
        new_config = dict(plugin.config)
        new_config[cmd.field] = cmd.value

        updated_plugin = plugin.model_copy(update={"config": new_config})
        plugins_list = list(proc.plugins)
        plugins_list[cmd.plugin_index] = updated_plugin

        updated_proc = proc.model_copy(update={"plugins": tuple(plugins_list)})
        new_processes = tuple(
            updated_proc if p.process_name == cmd.process_name else p for p in self.topology.processes
        )
        new_topology = self.topology.model_copy(update={"processes": new_processes})
        new_project = self.model_copy(update={"topology": new_topology})
        events: list[ProjectEvent] = [
            PluginConfigChanged(
                process_name=cmd.process_name,
                plugin_index=cmd.plugin_index,
                field=cmd.field,
                value=cmd.value,
            )
        ]
        return new_project, events

    def _apply_connect_wire(
        self,
        cmd: ConnectWire,
        catalogs: ApplyContext,
    ) -> tuple["Project", list[ProjectEvent]]:
        """Добавить Wire между двумя узлами топологии.

        Invariants:
          - оба узла ссылаются на существующие процессы
          - добавление не создаёт цикл
        """
        process_names = {p.process_name for p in self.topology.processes}
        src_proc = _extract_process_from_node(cmd.source)
        tgt_proc = _extract_process_from_node(cmd.target)

        if src_proc not in process_names:
            raise DomainError(f"wire source process '{src_proc}' not found")
        if tgt_proc not in process_names:
            raise DomainError(f"wire target process '{tgt_proc}' not found")

        new_wire = Wire(
            source=cmd.source,
            target=cmd.target,
            src_dtype=cmd.src_dtype,
            tgt_dtype=cmd.tgt_dtype,
        )
        new_topology = self.topology.model_copy(update={"wires": (*self.topology.wires, new_wire)})

        # Проверка на цикл после добавления wire
        _check_no_cycles(new_topology)

        new_project = self.model_copy(update={"topology": new_topology})
        events: list[ProjectEvent] = [WireConnected(wire=new_wire)]
        return new_project, events

    def _apply_disconnect_wire(
        self,
        cmd: DisconnectWire,
        catalogs: ApplyContext,
    ) -> tuple["Project", list[ProjectEvent]]:
        """Удалить Wire между двумя узлами топологии.

        Решение по открытому вопросу: wire не найден -> DomainError (fail fast).
        Consumer должен знать, что отключение не состоялось.
        """
        found = False
        remaining_wires: list[Wire] = []
        for wire in self.topology.wires:
            if wire.source == cmd.source and wire.target == cmd.target:
                found = True
            else:
                remaining_wires.append(wire)

        if not found:
            raise DomainError(f"wire {cmd.source} -> {cmd.target} not found")

        new_topology = self.topology.model_copy(update={"wires": tuple(remaining_wires)})
        new_project = self.model_copy(update={"topology": new_topology})
        events: list[ProjectEvent] = [WireDisconnected(source=cmd.source, target=cmd.target)]
        return new_project, events

    def _apply_bind_display(
        self,
        cmd: BindDisplay,
        catalogs: ApplyContext,
    ) -> tuple["Project", list[ProjectEvent]]:
        """Привязать DisplayInstance к узлу топологии.

        Invariants:
          - display_id существует в каталоге (если catalogs.displays не None)
          - пара (node_id, display_id) ещё не привязана (no-dup)
        """
        if catalogs.displays is not None:
            if catalogs.displays.resolve(cmd.display_id) is None:
                raise DomainError(f"display '{cmd.display_id}' not found in catalog")

        # No-dup: пара (node_id, display_id) уникальна (зеркало ConnectWire-цикла)
        for di in self.topology.displays:
            if di.node_id == cmd.node_id and di.display_id == cmd.display_id:
                raise DomainError(f"display '{cmd.display_id}' already bound to '{cmd.node_id}'")

        new_display = DisplayInstance(
            node_id=cmd.node_id,
            display_id=cmd.display_id,
        )
        new_topology = self.topology.model_copy(update={"displays": (*self.topology.displays, new_display)})
        new_project = self.model_copy(update={"topology": new_topology})
        events: list[ProjectEvent] = [DisplayBound(display=new_display)]
        return new_project, events

    def _apply_unbind_display(
        self,
        cmd: UnbindDisplay,
        catalogs: ApplyContext,
    ) -> tuple["Project", list[ProjectEvent]]:
        """Отвязать DisplayInstance от узла топологии.

        Ключ — пара (node_id, display_id): снимаем ровно одну привязку, не задевая
        прочие привязки того же выхода (fan-out). См. ADR DOM-001.
        """
        remaining = tuple(
            d for d in self.topology.displays if not (d.node_id == cmd.node_id and d.display_id == cmd.display_id)
        )
        new_topology = self.topology.model_copy(update={"displays": remaining})
        new_project = self.model_copy(update={"topology": new_topology})
        events: list[ProjectEvent] = [DisplayUnbound(node_id=cmd.node_id, display_id=cmd.display_id)]
        return new_project, events

    def _apply_assign_target_process(
        self,
        cmd: AssignTargetProcess,
        catalogs: ApplyContext,
    ) -> tuple["Project", list[ProjectEvent]]:
        """Назначить или сбросить целевой процесс (target_process) для Process.

        target=None сбрасывает привязку.
        """
        proc = self.topology.find_process(cmd.process_name)
        if proc is None:
            raise DomainError(f"process '{cmd.process_name}' not found")

        updated_proc = proc.model_copy(update={"target_process": cmd.target})
        new_processes = tuple(
            updated_proc if p.process_name == cmd.process_name else p for p in self.topology.processes
        )
        new_topology = self.topology.model_copy(update={"processes": new_processes})
        new_project = self.model_copy(update={"topology": new_topology})
        events: list[ProjectEvent] = [
            TargetProcessAssigned(
                process_name=cmd.process_name,
                target=cmd.target,
            )
        ]
        return new_project, events

    def _apply_activate_recipe(
        self,
        cmd: ActivateRecipe,
        catalogs: ApplyContext,
    ) -> tuple["Project", list[ProjectEvent]]:
        """Активировать Recipe по slug.

        Invariants:
          - catalogs.recipes не None (иначе DomainError)
          - recipe с данным slug существует в RecipeStore
          - blueprint рецепта проходит все invariants
        """
        if catalogs.recipes is None:
            raise DomainError("recipe_store unavailable")

        recipe = catalogs.recipes.read(cmd.slug)
        if recipe is None:
            raise DomainError(f"recipe '{cmd.slug}' not found")

        # Валидация blueprint рецепта через все invariants
        _check_unique_process_names(recipe.blueprint)
        _check_no_dangling_wires(recipe.blueprint)
        _check_no_cycles(recipe.blueprint)
        if catalogs.plugins is not None:
            _check_plugin_references(recipe.blueprint, catalogs)
        if catalogs.displays is not None:
            # Self-contained: привязки против СОБСТВЕННЫХ дисплеев рецепта, НЕ против
            # каталога старого активного рецепта (chicken-and-egg, см. helper).
            _check_recipe_self_display_references(recipe)

        new_project = self.model_copy(
            update={
                "topology": recipe.blueprint,
                "active_recipe": cmd.slug,
            }
        )
        events: list[ProjectEvent] = [
            TopologyReplaced(reason=f"recipe:{cmd.slug}"),
            RecipeActivated(slug=cmd.slug),
        ]
        return new_project, events

    def _apply_deactivate_recipe(
        self,
        cmd: DeactivateRecipe,
        catalogs: ApplyContext,
    ) -> tuple["Project", list[ProjectEvent]]:
        """Сбросить активный Recipe (нет активного рецепта)."""
        new_project = self.model_copy(update={"active_recipe": None})
        events: list[ProjectEvent] = [RecipeDeactivated()]
        return new_project, events

    def _apply_replace_topology(
        self,
        cmd: ReplaceTopology,
        catalogs: ApplyContext,
    ) -> tuple["Project", list[ProjectEvent]]:
        """Заменить топологию целиком.

        Не пошагово через invariants -- берём целиком,
        валидируем один проход по всем 5 invariants.
        """
        _validate_topology(cmd.topology, catalogs)
        new_project = self.model_copy(update={"topology": cmd.topology})
        events: list[ProjectEvent] = [TopologyReplaced(reason=cmd.reason)]
        return new_project, events
