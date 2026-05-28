"""PipelinePresenter -- центральный координатор Pipeline Editor.

Task E.1: мигрирован на AppServices DI. Принимает services: AppServices.
ActionBus bridge оставлен через getattr(services.commands, "action_bus", ...)
для undo/redo (ActionBus API не покрыт CommandDispatcher Protocol).
Scene reload — через typed event TopologyReplaced (services.events), Phase G G.1.

Координирует: PipelineModel (SSOT) + ActionBus/Commands + GraphScene + TopologyRepo.
Signal suppression предотвращает циклы при programmatic update.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator

from multiprocess_prototype.domain.app_services import AppServices
from multiprocess_prototype.domain.events import TopologyReplaced

from .graph.node_item import NodeData
from .graph.edge_item import EdgeData
from .graph.port_schema import PortSchema
from .model import PipelineModel
from .layout import auto_layout
from .telemetry import WireMetricsModel

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

    from multiprocess_framework.modules.registers_module import RegistersManager

    from .graph.graph_scene import GraphScene
    from .inspector.inspector_panel import NodeInspectorPanel

logger = logging.getLogger(__name__)


class PipelinePresenter:
    """Enhanced presenter для Pipeline Editor Phase 13.

    Координирует:
    - PipelineModel (SSOT) — все мутации через модель
    - ActionBus — undo/redo для всех операций
    - GraphScene — визуализация
    - TopologyHolder — синхронизация с runtime
    - TopologyBridge — IPC (опционально)
    """

    def __init__(
        self,
        services: AppServices,
        *,
        registers_manager: "RegistersManager | None" = None,
    ) -> None:
        self._services = services
        # G.2: live RegistersManager — runtime-объект (FieldInfo-схемы + значения)
        # для inspector-карточек. Передаётся через RuntimeDeps (Q-F1=B), НЕ через
        # services.registers (domain RegistersBackend не может экспонировать framework FieldInfo).
        self._registers_manager = registers_manager
        self._model = PipelineModel()
        self._scene: GraphScene | None = None
        self._suppress = False
        self._gui_positions: dict[str, tuple[float, float]] = {}

        # Модель телеметрии wire-соединений (Task 7b.3)
        self._wire_metrics_model = WireMetricsModel()

        # Ленивый импорт TopologyPresenter (для load/save YAML)
        from multiprocess_prototype.frontend.widgets.topology.presenter import TopologyPresenter

        self._topo = TopologyPresenter()

        # ActionBus bridge: CommandDispatcherOrchestrator не покрывает
        # undo/redo/execute — получаем legacy ActionBus через adapter.
        # TODO Phase G (G.4): полностью заменить ActionBus на domain commands
        _bus_accessor = getattr(services.commands, "action_bus", None)
        self._action_bus = _bus_accessor() if callable(_bus_accessor) else None

        # Scene reload через typed EventBus (G.1): publisher-мост в app.py публикует
        # TopologyReplaced при каждой замене топологии (ловит и ActionBus-мутации).
        # Гранулярные события (ProcessAdded/WireConnected для инкрементального update) — G.4.
        self._topology_sub = services.events.subscribe(TopologyReplaced, self._on_topology_replaced)

    def set_scene(self, scene: "GraphScene") -> None:
        """Привязать GraphScene для обновления визуализации."""
        self._scene = scene

    def set_inspector(self, panel: "NodeInspectorPanel") -> None:
        """Привязать NodeInspectorPanel и настроить интеграцию с ActionBus.

        Передаёт AppServices в panel и подписывается на field_changed,
        target_process_changed, display_id_changed.
        """
        panel.set_services(self._services, registers_manager=self._registers_manager)
        panel.field_changed.connect(self._on_inspector_field_changed)
        panel.target_process_changed.connect(self._on_target_process_changed)
        panel.display_id_changed.connect(self._on_display_id_changed)

    def _on_inspector_field_changed(
        self,
        process_name: str,
        field_name: str,
        new_value: Any,
    ) -> None:
        """Обработчик изменения поля из NodeInspectorPanel.

        Получает old_value из RegistersManager, затем:
        - Если ActionBus доступен: создаёт undoable Action через V2ActionBuilder.
        - Иначе: прямой вызов rm.set_value() если rm доступен.
        - Warning если ни ActionBus ни rm недоступны.
        """
        # G.2: live RegistersManager — explicit runtime-dep (через RuntimeDeps, Q-F1=B).
        # Здесь нужен flat get_register(process_name) для old_value + no-bus fallback set_value.
        # bus.execute(field_set) путь ниже остаётся для G.4 (ActionBus→domain commands).
        rm = self._registers_manager
        bus = self._action_bus

        # Получить старое значение для undo
        old_value: Any = None
        if rm is not None:
            register = rm.get_register(process_name)
            if register is not None:
                old_value = getattr(register, field_name, None)

        if bus is not None:
            from multiprocess_prototype.frontend.actions.builder import V2ActionBuilder

            action = V2ActionBuilder.field_set_timed(
                register_name=process_name,
                field_name=field_name,
                new_value=new_value,
                old_value=old_value,
                description=f"Изменить {process_name}.{field_name}",
            )
            bus.execute(action)
        elif rm is not None:
            ok = rm.set_value(process_name, field_name, new_value)
            if not ok:
                logger.warning(
                    "Не удалось установить %s.%s = %s через RegistersManager",
                    process_name,
                    field_name,
                    new_value,
                )
        else:
            logger.warning(
                "field_changed: ни ActionBus ни RegistersManager недоступны для %s.%s = %s",
                process_name,
                field_name,
                new_value,
            )

    def _on_target_process_changed(self, node_id: str, new_process: str) -> None:
        """Обработчик выбора нового целевого процесса для plugin-узла.

        Записывает target_process как мета-поле в запись процесса в topology.
        Это метаданные для сериализации в blueprint (Task 7a.4), не переименование.

        Args:
            node_id: идентификатор узла (обычно совпадает с process_name).
            new_process: имя целевого процесса из активного рецепта.
        """
        if self._suppress:
            return

        processes = self._model._topology.get("processes", [])

        # Найти запись узла и записать target_process как мета-поле
        found = False
        for proc in processes:
            if isinstance(proc, dict):
                if proc.get("process_name") == node_id:
                    proc["target_process"] = new_process
                    found = True
                    break
            else:
                if getattr(proc, "process_name", "") == node_id:
                    try:
                        proc.target_process = new_process
                    except AttributeError:
                        pass
                    found = True
                    break

        if found:
            logger.debug(
                "target_process обновлён: узел '%s' → процесс '%s'",
                node_id,
                new_process,
            )
        else:
            logger.warning(
                "_on_target_process_changed: узел '%s' не найден в topology",
                node_id,
            )

    def _on_display_id_changed(self, node_id: str, new_display_id: str) -> None:
        """Обработчик выбора нового display для display-узла.

        Находит запись display в topology по node_id, обновляет display_id
        и display_name (если DisplayRegistry доступен).

        Args:
            node_id: идентификатор display-узла.
            new_display_id: новый выбранный display_id.
        """
        if self._suppress:
            return

        displays = self._model._topology.get("displays", [])

        # Получить display_name из реестра (services.displays — DisplayCatalog Protocol)
        new_display_name = ""
        try:
            spec = self._services.displays.resolve(new_display_id)
            if spec is not None:
                new_display_name = spec.display_name
        except Exception:
            logger.debug("Не удалось получить имя display '%s' из реестра", new_display_id, exc_info=True)

        found = False
        for disp in displays:
            if isinstance(disp, dict):
                if disp.get("node_id") == node_id:
                    disp["display_id"] = new_display_id
                    disp["display_name"] = new_display_name
                    found = True
                    break
            else:
                if getattr(disp, "node_id", "") == node_id:
                    try:
                        disp.display_id = new_display_id
                        disp.display_name = new_display_name
                    except AttributeError:
                        pass
                    found = True
                    break

        if found:
            logger.debug(
                "display_id обновлён: узел '%s' → display '%s' (name='%s')",
                node_id,
                new_display_id,
                new_display_name,
            )
        else:
            logger.warning(
                "_on_display_id_changed: display-узел '%s' не найден в topology",
                node_id,
            )

    # ------------------------------------------------------------------ #
    #  Signal suppression (из v1)                                         #
    # ------------------------------------------------------------------ #

    @contextmanager
    def _block_signals(self) -> Iterator[None]:
        """Подавить обработку сигналов при programmatic update."""
        prev = self._suppress
        self._suppress = True
        try:
            yield
        finally:
            self._suppress = prev

    @property
    def is_suppressed(self) -> bool:
        return self._suppress

    # ------------------------------------------------------------------ #
    #  Загрузка                                                            #
    # ------------------------------------------------------------------ #

    def load_topology_from_config(self) -> tuple[list[NodeData], list[EdgeData]]:
        """Загрузить topology из живого источника (services.topology, TopologyRepository).

        F.2b: ранее читалось из config["topology"] — устаревший стартовый snapshot,
        который не обновлялся. Теперь источник один — TopologyRepository (живой).
        Dict at Boundary: presenter работает с dict, поэтому .to_dict().
        """
        topology = self._services.topology.load().to_dict()
        self._model.from_topology_dict(topology)

        # Восстановить позиции из metadata
        metadata = topology.get("metadata", {})
        if isinstance(metadata, dict):
            gui_pos = metadata.get("gui_positions", {})
            if isinstance(gui_pos, dict):
                self._gui_positions = {k: tuple(v) for k, v in gui_pos.items()}

        return self._topology_to_graph(topology)

    def load_topology_from_file(self, path: Path) -> tuple[list[NodeData], list[EdgeData]]:
        """Загрузить topology из YAML файла."""
        self._topo.load_from_file(path)
        bp = self._topo.blueprint
        data = bp.model_dump() if hasattr(bp, "model_dump") else {}
        self._model.from_topology_dict(data)
        return self._topology_to_graph(data)

    def export_topology_with_positions(self) -> dict:
        """Экспортировать topology dict с gui_positions в metadata."""
        topo = self._model.to_topology_dict()

        # Обновить позиции из scene (если привязана)
        if self._scene:
            self._gui_positions.update(self._scene.get_all_node_positions())

        # Записать позиции в metadata
        topo.setdefault("metadata", {})
        topo["metadata"]["gui_positions"] = {node_id: list(pos) for node_id, pos in self._gui_positions.items()}
        return topo

    def save_topology_to_file(self, path: Path) -> None:
        """Сохранить topology с позициями в YAML файл."""
        import yaml

        topo = self.export_topology_with_positions()
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(topo, f, default_flow_style=False, allow_unicode=True)

    # ------------------------------------------------------------------ #
    #  Мутации через PipelineModel + ActionBus                             #
    # ------------------------------------------------------------------ #

    def add_process_from_plugin(self, plugin_name: str, x: float = 0.0, y: float = 0.0) -> str | None:
        """Добавить процесс из палитры плагинов.

        Returns: имя процесса или None если не удалось.
        """
        # Генерировать уникальное имя
        base_name = plugin_name.replace("_", "-")
        existing = set(self._model.get_process_names())
        name = base_name
        counter = 1
        while name in existing:
            name = f"{base_name}_{counter}"
            counter += 1

        # Определить категорию и собрать port_schemas через services.plugins (PluginCatalog)
        category = "utility"
        port_schemas: list[PortSchema] | None = None
        spec = self._services.plugins.resolve(plugin_name)
        if spec is not None:
            category = spec.category
            # PluginSpec хранит ports как tuple[PortSpec, ...] c direction
            try:
                schemas: list[PortSchema] = []
                for port_spec in spec.ports:
                    schemas.append(
                        PortSchema(
                            name=port_spec.name,
                            direction=port_spec.direction,
                            dtype=port_spec.dtype,
                            optional=port_spec.optional,
                        )
                    )
                port_schemas = schemas if schemas else None
            except Exception:
                port_schemas = None

        old_topo, new_topo = self._model.add_process(name, plugin_name, category)
        self._gui_positions[name] = (x, y)

        # ActionBus (legacy bridge, TODO Phase G (G.4): domain commands)
        bus = self._action_bus
        if bus:
            from multiprocess_prototype.frontend.actions.builder import V2ActionBuilder

            action = V2ActionBuilder.process_add(old_topo, new_topo, name)
            bus.execute(action)
        else:
            # Без ActionBus — прямое обновление через TopologyRepository
            from multiprocess_prototype.domain.entities.topology import Topology

            self._services.topology.save(Topology.from_dict(new_topo))

        # Обновить scene
        if self._scene:
            with self._block_signals():
                node_data = NodeData(name, name, category, category, x, y)
                self._scene.add_node(node_data, port_schemas=port_schemas)

        return name

    def remove_selected(self, selected_node_ids: list[str]) -> None:
        """Удалить выбранные ноды (включая display-узлы)."""
        # Множество известных display-узлов — чтобы развести process/display ветки
        display_node_ids = {d.get("node_id", "") for d in self._model.get_displays()}

        for node_id in selected_node_ids:
            is_display = node_id in display_node_ids

            if is_display:
                old_topo, new_topo = self._model.remove_display(node_id)
            else:
                old_topo, new_topo = self._model.remove_process(node_id)

            self._gui_positions.pop(node_id, None)

            # ActionBus undo/redo поддержан только для process_remove (legacy bridge)
            if not is_display:
                bus = self._action_bus
                if bus:
                    from multiprocess_prototype.frontend.actions.builder import V2ActionBuilder

                    action = V2ActionBuilder.process_remove(old_topo, new_topo, node_id)
                    bus.execute(action)

            if self._scene:
                with self._block_signals():
                    self._scene.remove_node(node_id)

    def add_wire(self, source: str, target: str, parent: "QWidget | None" = None) -> bool:
        """Добавить wire с валидацией совместимости портов.

        Перед добавлением wire проверяет совместимость типов портов через
        PluginRegistry.are_ports_compatible(). Если registry недоступен или
        порты не найдены — graceful degradation (wire добавляется без блокировки).

        Args:
            source: endpoint источника в формате "process.plugin.port"
            target: endpoint приёмника в формате "process.plugin.port"
                    или "display.<node_id>.frame" для display-узлов
            parent: родительский виджет для QMessageBox (может быть None)

        Returns:
            True если wire создан, False если заблокирован.
        """
        # --- Валидация совместимости портов ---
        if not self._validate_wire_ports(source, target, parent):
            return False

        try:
            old_topo, new_topo = self._model.add_wire(source, target)
        except ValueError as e:
            logger.warning("Wire rejected: %s", e)
            return False

        bus = self._action_bus
        if bus:
            from multiprocess_prototype.frontend.actions.builder import V2ActionBuilder

            action = V2ActionBuilder.wire_add(old_topo, new_topo, source, target)
            bus.execute(action)

        # Обновить scene
        if self._scene:
            with self._block_signals():
                src_proc = source.split(".")[0]
                tgt_proc = target.split(".")[0]
                self._scene.add_edge(EdgeData(src_proc, tgt_proc, ""))

        return True

    def _validate_wire_ports(
        self,
        source: str,
        target: str,
        parent: "QWidget | None" = None,
    ) -> bool:
        """Проверить совместимость портов source и target перед созданием wire.

        Task F.5: использует PluginCatalog Protocol (resolve -> PluginSpec.ports)
        вместо raw _registry bridge. PortSpec конвертируется в framework Port
        для проверки через are_ports_compatible.

        Graceful degradation:
        - PluginSpec не найден -> лог warning, вернуть True (legacy compat)
        - Port не найден -> лог warning, вернуть True
        - Display-цель -> использует wildcard Port(dtype="image/*")

        Returns:
            True -- wire можно создать, False -- wire заблокирован.
        """
        from multiprocess_framework.modules.process_module.plugins.port import (
            Port,
            are_ports_compatible,
        )
        from multiprocess_prototype.domain.protocols.plugin_catalog import PortSpec

        catalog = self._services.plugins

        def _find_port_spec(
            plugin_name: str,
            port_name: str,
            direction: str,
        ) -> "PortSpec | None":
            """Найти PortSpec по имени плагина, порта и направлению."""
            spec = catalog.resolve(plugin_name)
            if spec is None:
                return None
            for ps in spec.ports:
                if ps.name == port_name and ps.direction == direction:
                    return ps
            return None

        def _portspec_to_port(ps: "PortSpec") -> Port:
            """Сконструировать framework Port из domain PortSpec."""
            return Port(
                name=ps.name,
                dtype=ps.dtype,
                shape=ps.shape,
                optional=ps.optional,
            )

        # Шаг 1: разобрать source endpoint -> (process, plugin, port)
        src_parts = source.split(".")
        if len(src_parts) < 3:
            logger.debug("_validate_wire_ports: некорректный source endpoint '%s', пропуск", source)
            return True

        src_plugin_name = src_parts[1]
        src_port_name = src_parts[2]

        # Шаг 2: найти выходной порт источника через PluginCatalog Protocol
        src_spec = catalog.resolve(src_plugin_name)
        if src_spec is None:
            logger.warning(
                "_validate_wire_ports: плагин '%s' не найден в catalog (source=%s), пропуск",
                src_plugin_name,
                source,
            )
            return True

        out_ps = _find_port_spec(src_plugin_name, src_port_name, "output")
        if out_ps is None:
            logger.warning(
                "_validate_wire_ports: выходной порт '%s' не найден у плагина '%s', пропуск",
                src_port_name,
                src_plugin_name,
            )
            return True

        out_port = _portspec_to_port(out_ps)

        # Шаг 3: определить входной порт приёмника
        tgt_parts = target.split(".")
        is_display_target = tgt_parts[0] == "display"

        if is_display_target:
            # Display-узел принимает любой image-выход через wildcard
            in_port = Port(name="frame", dtype="image/*", shape="")
        else:
            if len(tgt_parts) < 3:
                logger.debug(
                    "_validate_wire_ports: некорректный target endpoint '%s', пропуск",
                    target,
                )
                return True

            tgt_plugin_name = tgt_parts[1]
            tgt_port_name = tgt_parts[2]

            tgt_spec = catalog.resolve(tgt_plugin_name)
            if tgt_spec is None:
                logger.warning(
                    "_validate_wire_ports: плагин '%s' не найден в catalog (target=%s), пропуск",
                    tgt_plugin_name,
                    target,
                )
                return True

            in_ps = _find_port_spec(tgt_plugin_name, tgt_port_name, "input")
            if in_ps is None:
                logger.warning(
                    "_validate_wire_ports: входной порт '%s' не найден у плагина '%s', пропуск",
                    tgt_port_name,
                    tgt_plugin_name,
                )
                return True

            in_port = _portspec_to_port(in_ps)

        # Шаг 4: проверить совместимость
        ok = are_ports_compatible(out_port, in_port)
        if not ok:
            logger.warning(
                "Несовместимые порты: %s (%s) -> %s (%s)",
                source,
                out_port.dtype,
                target,
                in_port.dtype,
            )
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(
                parent,
                "Несовместимые порты",
                f"Невозможно соединить порты:\n"
                f"  Источник: {source}\n"
                f"  Тип: {out_port.dtype}\n\n"
                f"  Приёмник: {target}\n"
                f"  Тип: {in_port.dtype}\n\n"
                f"Типы данных несовместимы.",
            )
            return False

        return True

    def on_node_moved(self, node_id: str, new_x: float, new_y: float) -> None:
        """Обработчик перемещения ноды (для undo/redo через ActionBus)."""
        if self._suppress:
            return
        old_x, old_y = self._gui_positions.get(node_id, (0.0, 0.0))
        self._gui_positions[node_id] = (new_x, new_y)

        bus = self._action_bus
        if bus:
            from multiprocess_prototype.frontend.actions.builder import V2ActionBuilder

            action = V2ActionBuilder.node_move(node_id, old_x, old_y, new_x, new_y)
            bus.execute(action)

    # ------------------------------------------------------------------ #
    #  Topology sync                                                       #
    # ------------------------------------------------------------------ #

    def _on_topology_replaced(self, _event: "TopologyReplaced") -> None:
        """Подписчик EventBus — топология заменена (полный refresh).

        TopologyReplaced несёт только reason, поэтому актуальную топологию тянем
        из repository (services.topology.load). Обновляет модель и scene с signal
        suppression.
        """
        if self._suppress:
            return
        new_topology = self._services.topology.load().to_dict()
        with self._block_signals():
            self._model.from_topology_dict(new_topology)
            if self._scene:
                nodes, edges = self._topology_to_graph(new_topology)
                self._scene.load_from_data(nodes, edges)

    # ------------------------------------------------------------------ #
    #  Auto-layout                                                         #
    # ------------------------------------------------------------------ #

    def auto_layout_scene(self) -> None:
        """Применить Sugiyama auto-layout."""
        if not self._scene:
            return
        nodes = self._model.get_process_names()
        edges = self._model.get_edges_as_tuples()
        positions = auto_layout(nodes, edges)

        with self._block_signals():
            for node_id, (x, y) in positions.items():
                self._gui_positions[node_id] = (x, y)
                node_item = self._scene.get_node(node_id)
                if node_item:
                    node_item.setPos(x, y)

    # ------------------------------------------------------------------ #
    #  Валидация и утилиты                                                 #
    # ------------------------------------------------------------------ #

    def validate(self) -> list[str]:
        """Валидация topology через PipelineModel."""
        return self._model.validate()

    def get_yaml_preview(self) -> str:
        """YAML превью."""
        return self._topo.get_yaml_preview()

    @property
    def model(self) -> PipelineModel:
        """Доступ к модели (read-only intent)."""
        return self._model

    @property
    def wire_metrics_model(self) -> WireMetricsModel:
        """Доступ к модели телеметрии wire-соединений (Task 7b.3).

        Returns:
            WireMetricsModel — источник данных для WireMetricsController.
        """
        return self._wire_metrics_model

    # ------------------------------------------------------------------ #
    #  Конвертация (оставлена для обратной совместимости)                   #
    # ------------------------------------------------------------------ #

    def _topology_to_graph(self, topo_dict: dict) -> tuple[list[NodeData], list[EdgeData]]:
        """Конвертировать topology dict → NodeData/EdgeData."""
        nodes = []
        edges = []

        processes = topo_dict.get("processes", [])

        for proc in processes:
            if isinstance(proc, dict):
                name = proc.get("process_name", "unnamed")
                plugins = proc.get("plugins", [])
            else:
                name = getattr(proc, "process_name", "unnamed")
                plugins = getattr(proc, "plugins", [])

            category = "utility"
            if plugins:
                pname = (
                    plugins[0].get("plugin_name", "")
                    if isinstance(plugins[0], dict)
                    else getattr(plugins[0], "plugin_name", "")
                )
                if pname:
                    spec = self._services.plugins.resolve(pname)
                    if spec is not None:
                        category = spec.category

            # Восстановить позицию из gui_positions
            x, y = self._gui_positions.get(name, (0.0, 0.0))
            nodes.append(
                NodeData(
                    node_id=name,
                    title=name,
                    subtitle=category,
                    category=category,
                    x=x,
                    y=y,
                )
            )

        wires = topo_dict.get("wires", [])
        for w in wires:
            if isinstance(w, dict):
                source = w.get("source", "")
                target = w.get("target", "")
            else:
                source = getattr(w, "source", "")
                target = getattr(w, "target", "")

            if source and target:
                source_proc = source.split(".")[0] if "." in source else source
                target_proc = target.split(".")[0] if "." in target else target
                edges.append(EdgeData(source_id=source_proc, target_id=target_proc))

        return nodes, edges

    def _blueprint_to_graph(self, bp) -> tuple[list[NodeData], list[EdgeData]]:
        """Конвертировать SystemBlueprint в граф-данные."""
        data = bp.model_dump() if hasattr(bp, "model_dump") else {}
        return self._topology_to_graph(data)

    # ------------------------------------------------------------------ #
    #  Сохранение в рецепт                                                #
    # ------------------------------------------------------------------ #

    def save_to_active_recipe(self, parent: "QWidget | None" = None) -> bool:
        """Сохранить текущий граф в активный рецепт.

        Вызывает graph_to_blueprint для сериализации модели,
        читает текущий YAML рецепта через store.read_raw(), обновляет секции
        blueprint/display_bindings/gui_positions и записывает через store.save_raw().

        Task F.4: использует RecipeStore Protocol (services.recipes) вместо
        legacy bridge через adapter._rm.

        Args:
            parent: родительский виджет для QMessageBox (может быть None).

        Returns:
            True при успешном сохранении, False при любой ошибке.
        """
        from PySide6.QtWidgets import QMessageBox

        from .io import graph_to_blueprint

        store = self._services.recipes

        # Шаг 1: проверить активный рецепт
        active_slug = store.get_active()
        if active_slug is None:
            QMessageBox.warning(parent, "Сохранение рецепта", "Не выбран активный рецепт")
            return False

        # Шаг 2: сериализовать модель
        bp_dict, bindings, gui_positions = graph_to_blueprint(self._model)

        # Обновить gui_positions из scene (если привязана)
        if self._scene:
            self._gui_positions.update(self._scene.get_all_node_positions())
        gui_positions = {node_id: list(pos) for node_id, pos in self._gui_positions.items()}

        # Шаг 3: прочитать текущий YAML рецепта через RecipeStore Protocol
        raw_recipe = store.read_raw(active_slug)
        if raw_recipe is None:
            QMessageBox.critical(parent, "Сохранение рецепта", "Не удалось прочитать рецепт")
            return False

        # Шаг 4: обновить секции в data-части рецепта
        try:
            recipe_data = raw_recipe.get("data", {})
            if not isinstance(recipe_data, dict):
                recipe_data = {}

            recipe_data["blueprint"] = bp_dict
            recipe_data["display_bindings"] = bindings
            recipe_data["gui_positions"] = gui_positions

            raw_recipe["data"] = recipe_data

            # Записать через RecipeStore Protocol
            store.save_raw(active_slug, raw_recipe)

            logger.info("Pipeline сохранён в рецепт '%s'", active_slug)
        except Exception as exc:
            logger.exception("Ошибка при сохранении рецепта '%s'", active_slug)
            QMessageBox.critical(parent, "Сохранение рецепта", f"Ошибка: {exc}")
            return False

        QMessageBox.information(parent, "Сохранение рецепта", f"Рецепт сохранён: {active_slug}")
        return True

    # ------------------------------------------------------------------ #
    #  Запуск активного рецепта                                           #
    # ------------------------------------------------------------------ #

    def launch_active_recipe(self, parent: "QWidget | None" = None) -> bool:
        """Запустить активный рецепт через ProcessManager-proxy.

        Получает blueprint из активного рецепта и вызывает
        ``proxy.replace_blueprint(blueprint)`` — горячую замену процессов
        без остановки GUI.

        Task F.4: использует RecipeStore Protocol (services.recipes).

        Args:
            parent: родительский виджет для QMessageBox (может быть None).

        Returns:
            True при успешном запуске, False при любой ошибке или при
            отсутствии proxy.
        """
        from PySide6.QtWidgets import QMessageBox

        store = self._services.recipes

        # Шаг 1: проверить активный рецепт
        active_slug = store.get_active()
        if active_slug is None:
            QMessageBox.warning(parent, "Запуск рецепта", "Не выбран активный рецепт")
            return False

        # Шаг 2: прочитать рецепт через RecipeStore Protocol
        current = store.read_raw(active_slug)
        if current is None:
            QMessageBox.critical(parent, "Запуск рецепта", "Не удалось прочитать рецепт")
            return False

        # Шаг 4: извлечь blueprint
        blueprint = current.get("blueprint") or current.get("data", {}).get("blueprint") or {}
        if not blueprint:
            QMessageBox.warning(
                parent,
                "Запуск рецепта",
                f"Рецепт '{active_slug}' не содержит blueprint",
            )
            return False

        # Шаг 5: найти ProcessManager-proxy
        # By design (Q-F1=B): process_manager_proxy — runtime layer, не AppServices Protocol.
        # Остаётся тихим bridge через config / RuntimeDeps.
        proxy = None

        # Попытка получить proxy через config extras (не deprecated ключи)
        pm_proxy = self._services.config.get("process_manager_proxy")
        if pm_proxy is not None:
            proxy = pm_proxy

        if proxy is None or not hasattr(proxy, "replace_blueprint"):
            QMessageBox.warning(
                parent,
                "Запуск рецепта",
                "ProcessManager-proxy недоступен в GUI-процессе.\nЗапуск возможен только при работающей системе.",
            )
            return False

        # Шаг 6: вызвать replace_blueprint
        try:
            result = proxy.replace_blueprint(blueprint)
            success = result.get("success", False)
            if success:
                replaced = result.get("replaced", [])
                skipped = result.get("skipped_protected", [])
                QMessageBox.information(
                    parent,
                    "Запуск рецепта",
                    f"Рецепт '{active_slug}' запущен.\n"
                    f"Заменено процессов: {len(replaced)}\n"
                    f"Пропущено (protected): {len(skipped)}",
                )
                return True
            else:
                error = result.get("error") or "неизвестная ошибка"
                rolled_back = result.get("rolled_back", False)
                QMessageBox.critical(
                    parent,
                    "Запуск рецепта",
                    f"Ошибка: {error}\nRollback: {'выполнен' if rolled_back else 'не выполнен'}",
                )
                return False
        except Exception as exc:
            logger.exception("launch_active_recipe failed")
            QMessageBox.critical(parent, "Запуск рецепта", f"Ошибка: {exc}")
            return False

    # ------------------------------------------------------------------ #
    #  Legacy API compatibility                                            #
    # ------------------------------------------------------------------ #

    def add_process(self, name: str, category: str = "utility") -> NodeData:
        """Legacy: добавить процесс (без ActionBus)."""
        self._topo.add_process(name)
        return NodeData(node_id=name, title=name, subtitle=category, category=category)

    def remove_process(self, name: str) -> None:
        """Legacy: удалить процесс."""
        self._topo.remove_process(name)
