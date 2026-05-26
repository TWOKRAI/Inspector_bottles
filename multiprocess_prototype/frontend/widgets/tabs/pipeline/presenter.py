"""PipelinePresenter -- центральный координатор Pipeline Editor.

Координирует: PipelineModel (SSOT) + ActionBus + GraphScene + TopologyHolder + Bridge.
Signal suppression предотвращает циклы при programmatic update.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator

from .graph.node_item import NodeData
from .graph.edge_item import EdgeData
from .graph.port_schema import PortSchema
from .model import PipelineModel
from .layout import auto_layout

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

    from multiprocess_prototype.frontend.app_context import AppContext
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

    def __init__(self, ctx: "AppContext") -> None:
        self._ctx = ctx
        self._model = PipelineModel()
        self._scene: GraphScene | None = None
        self._suppress = False
        self._gui_positions: dict[str, tuple[float, float]] = {}

        # Ленивый импорт TopologyPresenter (для load/save YAML)
        from multiprocess_prototype.frontend.widgets.topology.presenter import TopologyPresenter

        self._topo = TopologyPresenter()

        # Подписка на TopologyHolder (если доступен)
        holder = ctx.topology_holder()
        if holder:
            holder.on_changed(self._on_topology_changed_external)

    def set_scene(self, scene: "GraphScene") -> None:
        """Привязать GraphScene для обновления визуализации."""
        self._scene = scene

    def set_inspector(self, panel: "NodeInspectorPanel") -> None:
        """Привязать NodeInspectorPanel и настроить интеграцию с ActionBus.

        Передаёт AppContext в panel и подписывается на field_changed,
        target_process_changed, display_id_changed.
        """
        panel.set_context(self._ctx)
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
        rm = self._ctx.registers_manager()
        bus = self._ctx.action_bus()

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

        # Получить display_name из реестра если доступен
        new_display_name = ""
        registry = getattr(self._ctx, "display_registry", None)
        if registry is not None:
            try:
                entry = registry.get(new_display_id)
                if entry is not None:
                    new_display_name = getattr(entry, "name", "")
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
        """Загрузить topology из AppContext.config."""
        topology = self._ctx.config.get("topology", {})
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

        # Определить категорию и собрать port_schemas
        category = "utility"
        port_schemas: list[PortSchema] | None = None
        registry = self._ctx.plugin_registry()
        if registry:
            entry = registry.get(plugin_name)
            if entry:
                category = getattr(entry, "category", "utility")
                # Graceful fallback: если entry недоступен — port_schemas=None
                try:
                    schemas: list[PortSchema] = []
                    for port in entry.inputs:
                        schemas.append(
                            PortSchema(
                                name=port.name,
                                direction="input",
                                dtype=port.dtype,
                                optional=port.optional,
                            )
                        )
                    for port in entry.outputs:
                        schemas.append(
                            PortSchema(
                                name=port.name,
                                direction="output",
                                dtype=port.dtype,
                                optional=port.optional,
                            )
                        )
                    port_schemas = schemas if schemas else None
                except Exception:
                    port_schemas = None

        old_topo, new_topo = self._model.add_process(name, plugin_name, category)
        self._gui_positions[name] = (x, y)

        # ActionBus
        bus = self._ctx.action_bus()
        if bus:
            from multiprocess_prototype.frontend.actions.builder import V2ActionBuilder

            action = V2ActionBuilder.process_add(old_topo, new_topo, name)
            bus.execute(action)
        else:
            # Без ActionBus — прямое обновление holder
            holder = self._ctx.topology_holder()
            if holder:
                holder.set_topology(new_topo)

        # Обновить scene
        if self._scene:
            with self._block_signals():
                node_data = NodeData(name, name, category, category, x, y)
                self._scene.add_node(node_data, port_schemas=port_schemas)

        return name

    def remove_selected(self, selected_node_ids: list[str]) -> None:
        """Удалить выбранные ноды."""
        for node_id in selected_node_ids:
            old_topo, new_topo = self._model.remove_process(node_id)
            self._gui_positions.pop(node_id, None)

            bus = self._ctx.action_bus()
            if bus:
                from multiprocess_prototype.frontend.actions.builder import V2ActionBuilder

                action = V2ActionBuilder.process_remove(old_topo, new_topo, node_id)
                bus.execute(action)

            if self._scene:
                with self._block_signals():
                    self._scene.remove_node(node_id)

    def add_wire(self, source: str, target: str) -> bool:
        """Добавить wire с валидацией.

        Returns: True если wire создан.
        """
        try:
            old_topo, new_topo = self._model.add_wire(source, target)
        except ValueError as e:
            logger.warning("Wire rejected: %s", e)
            return False

        bus = self._ctx.action_bus()
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

    def on_node_moved(self, node_id: str, new_x: float, new_y: float) -> None:
        """Обработчик перемещения ноды (для undo/redo через ActionBus)."""
        if self._suppress:
            return
        old_x, old_y = self._gui_positions.get(node_id, (0.0, 0.0))
        self._gui_positions[node_id] = (new_x, new_y)

        bus = self._ctx.action_bus()
        if bus:
            from multiprocess_prototype.frontend.actions.builder import V2ActionBuilder

            action = V2ActionBuilder.node_move(node_id, old_x, old_y, new_x, new_y)
            bus.execute(action)

    # ------------------------------------------------------------------ #
    #  Topology sync                                                       #
    # ------------------------------------------------------------------ #

    def _on_topology_changed_external(self, new_topology: dict) -> None:
        """Callback от TopologyHolder — внешнее изменение topology.

        Обновляет модель и scene с signal suppression.
        """
        if self._suppress:
            return
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

    # ------------------------------------------------------------------ #
    #  Конвертация (оставлена для обратной совместимости)                   #
    # ------------------------------------------------------------------ #

    def _topology_to_graph(self, topo_dict: dict) -> tuple[list[NodeData], list[EdgeData]]:
        """Конвертировать topology dict → NodeData/EdgeData."""
        nodes = []
        edges = []

        processes = topo_dict.get("processes", [])
        registry = self._ctx.plugin_registry()

        for proc in processes:
            if isinstance(proc, dict):
                name = proc.get("process_name", "unnamed")
                plugins = proc.get("plugins", [])
            else:
                name = getattr(proc, "process_name", "unnamed")
                plugins = getattr(proc, "plugins", [])

            category = "utility"
            if plugins and registry:
                pname = (
                    plugins[0].get("plugin_name", "")
                    if isinstance(plugins[0], dict)
                    else getattr(plugins[0], "plugin_name", "")
                )
                if pname:
                    entry = registry.get(pname)
                    if entry:
                        category = getattr(entry, "category", "utility")

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
        читает текущий YAML рецепта, обновляет секции blueprint/display_bindings/
        gui_positions и записывает файл напрямую через recipes_dir.

        Args:
            parent: родительский виджет для QMessageBox (может быть None).

        Returns:
            True при успешном сохранении, False при любой ошибке.
        """
        import yaml
        from PySide6.QtWidgets import QMessageBox

        from .io import graph_to_blueprint

        # Шаг 1: проверить RecipeManager
        recipe_mgr = self._ctx.recipe_manager()
        if recipe_mgr is None:
            QMessageBox.warning(parent, "Сохранение рецепта", "RecipeManager недоступен")
            return False

        # Шаг 2: проверить активный рецепт
        active_slug = recipe_mgr.get_active()
        if active_slug is None:
            QMessageBox.warning(parent, "Сохранение рецепта", "Не выбран активный рецепт")
            return False

        # Шаг 3: сериализовать модель
        bp_dict, bindings, gui_positions = graph_to_blueprint(self._model)

        # Обновить gui_positions из scene (если привязана)
        if self._scene:
            self._gui_positions.update(self._scene.get_all_node_positions())
        gui_positions = {node_id: list(pos) for node_id, pos in self._gui_positions.items()}

        # Шаг 4: прочитать текущий YAML рецепта
        raw_recipe = recipe_mgr.read_recipe(active_slug)
        if raw_recipe is None:
            QMessageBox.critical(parent, "Сохранение рецепта", "Не удалось прочитать рецепт")
            return False

        # Шаг 5: обновить секции в data-части рецепта
        try:
            recipe_data = raw_recipe.get("data", {})
            if not isinstance(recipe_data, dict):
                recipe_data = {}

            recipe_data["blueprint"] = bp_dict
            recipe_data["display_bindings"] = bindings
            recipe_data["gui_positions"] = gui_positions

            raw_recipe["data"] = recipe_data

            # Записать YAML напрямую через recipes_dir (обходя TreeStore)
            recipes_dir = recipe_mgr.recipes_dir
            file_path = recipes_dir / f"{active_slug}.yaml"
            with open(file_path, "w", encoding="utf-8") as f:
                yaml.dump(raw_recipe, f, default_flow_style=False, allow_unicode=True)

            logger.info("Pipeline сохранён в рецепт '%s': %s", active_slug, file_path)
        except Exception as exc:
            logger.exception("Ошибка при сохранении рецепта '%s'", active_slug)
            QMessageBox.critical(parent, "Сохранение рецепта", f"Ошибка: {exc}")
            return False

        QMessageBox.information(parent, "Сохранение рецепта", f"Рецепт сохранён: {active_slug}")
        return True

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
