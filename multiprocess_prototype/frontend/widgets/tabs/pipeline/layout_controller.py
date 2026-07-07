# -*- coding: utf-8 -*-
"""Layout-состояние и операции вкладки Pipeline (Трек F, Task F.4).

Позиции нод (`gui_positions`), фиксация (`locked_nodes`), авто-раскладка,
сохранение/экспорт позиций и load/save топологии вместе с layout-метаданными
(gui_positions / locked_nodes в metadata рецепта). Вынесено из
``PipelinePresenter`` дословно — поведение заморожено характеризационными тестами
(``test_yaml_positions.py``, ``test_node_lock_and_layout.py``, ``test_save_recipe.py``)
и НЕ меняется этим разрезом.

Владение состоянием (ВАЖНО): сами словари ``_gui_positions`` / ``_locked_nodes`` /
``_placed_display_ids`` и дебаунс-таймер ``_persist_timer`` остаются полями
presenter-core — характеризационные тесты мутируют их напрямую как
``presenter._gui_positions[...]`` и читают ``presenter._persist_timer`` (перенос
владения в контроллер потребовал бы правки ожиданий тестов). Контроллер
инкапсулирует ОПЕРАЦИИ над этим состоянием, обращаясь к presenter через
back-reference ``self._p`` (host).

Qt-зависимость: контроллер Qt-coupled — ``save_to_active_recipe`` тянет
``QMessageBox`` (GUI-реакция на успех/ошибку сохранения), ``_schedule_layout_persist``
использует ``QApplication``/``QTimer`` (ленивая инициализация дебаунс-таймера),
``auto_layout_scene`` двигает Qt-ноды в scene. QMessageBox оставлен дословно как
GUI-реакция (перенос без переписи).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from .layout import auto_layout

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

    from .graph.data import EdgeData, NodeData
    from .presenter import PipelinePresenter

logger = logging.getLogger(__name__)


class LayoutController:
    """Контроллер layout-состояния и операций сохранения/загрузки для Pipeline.

    Единственная зависимость — presenter-host (``self._p``): контроллер читает и
    пишет его GUI-состояние (``_gui_positions``/``_locked_nodes``/
    ``_placed_display_ids``/``_persist_timer``), scene, модель, services и
    вспомогательные методы (``_topology_to_graph``/``_block_signals``).
    """

    # Дебаунс авто-сохранения layout: 400мс после последнего сдвига/фиксации,
    # чтобы не писать файл рецепта на каждый пиксель перетаскивания.
    _PERSIST_DEBOUNCE_MS = 400

    def __init__(self, presenter: "PipelinePresenter") -> None:
        self._p = presenter

    # ------------------------------------------------------------------ #
    #  Загрузка                                                            #
    # ------------------------------------------------------------------ #

    def load_topology_from_config(self) -> tuple[list["NodeData"], list["EdgeData"]]:
        """Загрузить topology из живого источника (services.topology, TopologyRepository).

        F.2b: ранее читалось из config["topology"] — устаревший стартовый snapshot,
        который не обновлялся. Теперь источник один — TopologyRepository (живой).
        Dict at Boundary: presenter работает с dict, поэтому .to_dict().

        follow-up ФИКС #4 (Task 2.1, шаг 4): явная загрузка топологии из config —
        семантически «новая сессия редактора», как и активация рецепта. Сбрасываем
        placed-but-unbound боксы здесь же: непривязанные боксы не сериализуются (binding
        нет), поэтому при загрузке новой топологии они не должны протекать из прошлой
        сессии. Раньше сброс был только в _on_recipe_activated.
        См. plans/pipeline-place-display-node.md (Task 2.1, шаг 4).
        """
        self._p._placed_display_ids.clear()
        topology = self._p._services.topology.load().to_dict()
        self._p._model.from_topology_dict(topology)

        # Восстановить позиции и фиксацию из metadata (free-layout Task 2/3):
        # gui_positions → стартовое размещение без «Раскладки»; locked_nodes →
        # закреплённые ноды переживают перезапуск.
        metadata = topology.get("metadata", {})
        if isinstance(metadata, dict):
            gui_pos = metadata.get("gui_positions", {})
            if isinstance(gui_pos, dict):
                self._p._gui_positions = {k: tuple(v) for k, v in gui_pos.items()}
            locked = metadata.get("locked_nodes", [])
            if isinstance(locked, (list, tuple)):
                self._p._locked_nodes = {str(nid) for nid in locked}

        return self._p._topology_to_graph(topology)

    def load_topology_from_file(self, path: Path) -> tuple[list["NodeData"], list["EdgeData"]]:
        """Загрузить topology из YAML файла."""
        self._p._topo.load_from_file(path)
        bp = self._p._topo.blueprint
        data = bp.model_dump() if hasattr(bp, "model_dump") else {}
        self._p._model.from_topology_dict(data)
        return self._p._topology_to_graph(data)

    def export_topology_with_positions(self) -> dict:
        """Экспортировать topology dict с gui_positions в metadata."""
        topo = self._p._model.to_topology_dict()

        # Обновить позиции из scene + очистить мусор (ключи не из текущей сцены)
        self._sync_positions_from_scene()

        # Записать позиции в metadata
        topo.setdefault("metadata", {})
        topo["metadata"]["gui_positions"] = {node_id: list(pos) for node_id, pos in self._p._gui_positions.items()}
        return topo

    def save_topology_to_file(self, path: Path) -> None:
        """Сохранить topology с позициями в YAML файл."""
        import yaml

        topo = self.export_topology_with_positions()
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(topo, f, default_flow_style=False, allow_unicode=True)

    # ------------------------------------------------------------------ #
    #  Перемещение / фиксация нод (free-layout)                            #
    # ------------------------------------------------------------------ #

    def on_node_moved(self, node_id: str, new_x: float, new_y: float) -> None:
        """Обработчик свободного перемещения ноды (free-layout).

        G.4.4: NODE_MOVE — GUI-only (позиции в _gui_positions/metadata), не
        topology-domain. Drag меняет ТОЛЬКО позицию (членство в процессе не
        трогается). Позиция дебаунс-сохраняется в активный рецепт (Task 2).
        """
        if self._p._suppress:
            return
        self._p._gui_positions[node_id] = (new_x, new_y)
        self._schedule_layout_persist()

    def set_node_lock(self, node_id: str, locked: bool) -> None:
        """Зафиксировать/освободить ноду явно.

        Locked-нода не перетаскивается (ItemIsMovable=False) и пропускается
        auto_layout_scene. Состояние живёт в _locked_nodes, переприменяется в
        _topology_to_graph при reload и дебаунс-сохраняется в рецепт
        (metadata.locked_nodes) → переживает перезапуск (Task 3).
        """
        if not node_id:
            return
        if locked:
            self._p._locked_nodes.add(node_id)
        else:
            self._p._locked_nodes.discard(node_id)
        if self._p._scene:
            self._p._scene.set_node_locked(node_id, locked)
        self._schedule_layout_persist()

    def toggle_node_lock(self, node_id: str) -> None:
        """Переключить фиксацию ноды (правый клик по ноде)."""
        self.set_node_lock(node_id, node_id not in self._p._locked_nodes)

    # ------------------------------------------------------------------ #
    #  Авто-персист layout в рецепт (free-layout Task 2/3)                 #
    # ------------------------------------------------------------------ #

    def _sync_positions_from_scene(self) -> None:
        """Синхронизировать _gui_positions с текущей сценой (только её ноды).

        Берём позиции ТОЛЬКО нод, реально присутствующих в сцене. Это убирает
        накопленный мусор: ключи нод прошлых рецептов (копились через .update при
        переключении рецепта) и legacy node_id чужого процесса (напр.
        ``camera_0.frame_saver`` от старого drag→MovePlugin кода). Иначе мусор
        записывался в активный рецепт и нода рендерилась «в чужом процессе».
        """
        if self._p._scene is None:
            return
        self._p._gui_positions = dict(self._p._scene.get_all_node_positions())

    def _schedule_layout_persist(self) -> None:
        """Запланировать (дебаунс) авто-сохранение layout в активный рецепт.

        Ленивая инициализация QTimer: без QApplication (headless-тесты) — no-op,
        авто-сохранение пропускается (явный save_to_active_recipe не зависит от таймера).
        """
        from PySide6.QtWidgets import QApplication

        if QApplication.instance() is None:
            return
        if self._p._persist_timer is None:
            from PySide6.QtCore import QTimer

            self._p._persist_timer = QTimer()
            self._p._persist_timer.setSingleShot(True)
            self._p._persist_timer.timeout.connect(self._persist_layout_to_recipe)
        self._p._persist_timer.start(self._PERSIST_DEBOUNCE_MS)

    def _persist_layout_to_recipe(self) -> None:
        """Тихо сохранить позиции/фиксацию в активный рецепт (по дебаунс-таймеру).

        Layout — GUI-метаданные: пишем ТОЧЕЧНО ``blueprint.metadata.{gui_positions,
        locked_nodes}`` через store.save_layout (ruamel, не перезаписывая весь blueprint)
        — комментарии рецепта целы, processes/wires не тронуты (editor↔runtime decoupling,
        [[project_pipeline_editor_runtime_decoupled]]). blueprint.metadata переживает
        cold-start (unwrap_recipe сохраняет blueprint; load_topology_from_config читает
        оттуда). Без активного рецепта / ошибки записи — только лог, без QMessageBox
        (авто-сохранение не должно дёргать пользователя).
        """
        store = self._p._services.recipes
        active_slug = store.get_active()
        if active_slug is None:
            return

        # Только ноды текущей сцены → не писать в рецепт мусор от прошлых рецептов / legacy.
        self._sync_positions_from_scene()

        gui_positions = {node_id: list(pos) for node_id, pos in self._p._gui_positions.items()}
        try:
            store.save_layout(active_slug, gui_positions, sorted(self._p._locked_nodes))
            logger.debug("Layout pipeline авто-сохранён в рецепт '%s'", active_slug)
        except Exception:
            logger.exception("Авто-сохранение layout в рецепт '%s' не удалось", active_slug)

    # ------------------------------------------------------------------ #
    #  Auto-layout                                                         #
    # ------------------------------------------------------------------ #

    def auto_layout_scene(self) -> None:
        """Применить Sugiyama auto-layout на уровне ПРОЦЕССОВ, плагины — группой.

        D.1: нода = плагин, но раскладка считается по процессам (рамкам): каждый
        процесс — один узел Sugiyama, его плагины раскладываются слева-направо
        внутри по индексу. Ширина узла = макс ширина контейнера (по числу
        плагинов), чтобы колонки не накладывались. Display-боксы участвуют как
        узлы-стоки (binding-ребро source-процесс → бокс).
        """
        if not self._p._scene:
            return
        from .graph.constants import CONTAINER_HEADER_H, CONTAINER_INNER_GAP, CONTAINER_PADDING, NODE_WIDTH

        topo = self._p._model.to_topology_dict()
        # Карта процесс → число плагинов (для ширины колонки и offset плагинов).
        plugin_counts: dict[str, int] = {}
        for proc in topo.get("processes", []):
            if proc.get("protected", False) if isinstance(proc, dict) else getattr(proc, "protected", False):
                continue
            pn = proc.get("process_name", "") if isinstance(proc, dict) else getattr(proc, "process_name", "")
            pls = proc.get("plugins", []) if isinstance(proc, dict) else getattr(proc, "plugins", [])
            if pn:
                plugin_counts[pn] = len(pls)

        nodes = list(plugin_counts.keys())
        edges = list(self._p._model.get_edges_as_tuples())

        # Display-боксы (id = display_id) + binding-рёбра source-процесс → box.
        display_ids: set[str] = set(self._p._placed_display_ids)
        for d in self._p._model.get_displays():
            display_id = d.get("display_id", "")
            if not display_id:
                continue
            display_ids.add(display_id)
            source_proc = d.get("node_id", "").split(".")[0]
            if source_proc:
                edges.append((source_proc, display_id))
        for display_id in display_ids:
            if display_id not in nodes:
                nodes.append(display_id)

        # Ширина колонки = макс ширина контейнера (учесть цепочку плагинов).
        max_plugins = max(plugin_counts.values(), default=1) or 1
        column_width = max_plugins * (NODE_WIDTH + CONTAINER_INNER_GAP) + 2 * CONTAINER_PADDING
        positions = auto_layout(nodes, edges, node_width=column_width)

        inner_dy = CONTAINER_HEADER_H + CONTAINER_PADDING
        with self._p._block_signals():
            for layout_id, (x, y) in positions.items():
                if layout_id in plugin_counts:
                    # Процесс: разложить его плагин-ноды слева-направо группой.
                    members = self._p._scene.members_of(layout_id)
                    # Сортируем по plugin_index для стабильного порядка цепочки.
                    members.sort(key=lambda m: m.plugin_index)
                    for j, member in enumerate(members):
                        # Зафиксированную ноду авто-раскладка не трогает.
                        if getattr(member.data, "locked", False):
                            continue
                        mx = x + CONTAINER_PADDING + j * (NODE_WIDTH + CONTAINER_INNER_GAP)
                        my = y + inner_dy
                        member.setPos(mx, my)
                        self._p._gui_positions[member.node_id] = (mx, my)
                else:
                    # Display-бокс (или fallback) — двигаем сам узел (если не locked).
                    node_item = self._p._scene.get_node(layout_id)
                    if node_item is not None and getattr(getattr(node_item, "data", None), "locked", False):
                        continue
                    self._p._gui_positions[layout_id] = (x, y)
                    if node_item is not None:
                        node_item.setPos(x, y)

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

        store = self._p._services.recipes

        # Шаг 1: проверить активный рецепт
        active_slug = store.get_active()
        if active_slug is None:
            QMessageBox.warning(parent, "Сохранение рецепта", "Не выбран активный рецепт")
            return False

        # Шаг 2: сериализовать модель
        bp_dict, bindings, gui_positions = graph_to_blueprint(self._p._model)

        # Обновить gui_positions из scene (если привязана)
        if self._p._scene:
            self._p._gui_positions.update(self._p._scene.get_all_node_positions())
        gui_positions = {node_id: list(pos) for node_id, pos in self._p._gui_positions.items()}

        # Шаг 3: прочитать текущий YAML рецепта через RecipeStore Protocol
        raw_recipe = store.read_raw(active_slug)
        if raw_recipe is None:
            QMessageBox.critical(parent, "Сохранение рецепта", "Не удалось прочитать рецепт")
            return False

        # Шаг 4: обновить top-level секции v3-рецепта (displays ВНУТРЬ blueprint) через
        # единый нормализатор (one source of truth): без legacy data:-вложения, прочие
        # ключи (name/version/active_services) сохраняются. save_raw — ruamel round-trip.
        try:
            from multiprocess_prototype.recipes.format import normalize_recipe_v3_raw

            bp_dict["displays"] = bindings
            # free-layout Task 2/3: дублируем layout в blueprint.metadata — именно
            # оттуда его читает load_topology_from_config и cold-start (unwrap_recipe
            # сохраняет blueprint.metadata). Top-level gui_positions оставляем для
            # обратной совместимости (Recipes-tab + старые рецепты).
            metadata = dict(bp_dict.get("metadata") or {})
            metadata["gui_positions"] = gui_positions
            metadata["locked_nodes"] = sorted(self._p._locked_nodes)
            bp_dict["metadata"] = metadata
            store.save_raw(active_slug, normalize_recipe_v3_raw(raw_recipe, bp_dict, gui_positions))

            logger.info("Pipeline сохранён в рецепт '%s'", active_slug)
        except Exception as exc:
            logger.exception("Ошибка при сохранении рецепта '%s'", active_slug)
            QMessageBox.critical(parent, "Сохранение рецепта", f"Ошибка: {exc}")
            return False

        QMessageBox.information(parent, "Сохранение рецепта", f"Рецепт сохранён: {active_slug}")
        return True


__all__ = ["LayoutController"]
