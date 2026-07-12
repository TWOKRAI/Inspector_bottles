# -*- coding: utf-8 -*-
"""Layout-состояние и операции вкладки Pipeline (Трек F, Task F.4 + F.7).

Позиции нод (`gui_positions`), фиксация (`locked_nodes`), placed-but-unbound
display-боксы (`placed_display_ids`), дебаунс-таймер авто-персиста
(`persist_timer`), авто-раскладка, сохранение/экспорт позиций и load/save
топологии вместе с layout-метаданными (gui_positions / locked_nodes в metadata
рецепта).

Владение состоянием (F.7): контроллер — ВЛАДЕЛЕЦ GUI-состояния. Раньше (F.4) сами
словари/множества жили в presenter-core, а контроллеры трогали их через
back-reference ``self._p``; теперь ``_gui_positions`` / ``_locked_nodes`` /
``_placed_display_ids`` / ``_persist_timer`` — поля этого контроллера, доступные
через публичные свойства (``gui_positions`` / ``locked_nodes`` /
``placed_display_ids`` / ``persist_timer``). Presenter-core и PipelineMutations
читают/пишут состояние ТОЛЬКО через этот публичный API.

Зависимости (F.7): стабильные коллабораторы (``services`` / ``model`` / ``topo``)
инжектятся снимком в конструктор — по образцу RuntimeController (F.3), а не
достаются из приватных полей presenter. Qt-реакции (scene, подавление сигналов,
рендер) идут через узкий host-контракт :class:`PipelineHost`. Прямого доступа к
приватным полям presenter больше нет.

Qt-зависимость: контроллер Qt-coupled — ``save_to_active_recipe`` тянет
``QMessageBox`` (GUI-реакция на успех/ошибку сохранения), ``_schedule_layout_persist``
использует ``QApplication``/``QTimer`` (ленивая инициализация дебаунс-таймера),
``auto_layout_scene`` двигает Qt-ноды в scene. QMessageBox оставлен дословно как
GUI-реакция (перенос без переписи).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .layout import auto_layout

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

    from multiprocess_prototype.domain.app_services import AppServices

    from ._host import PipelineHost
    from .graph.data import EdgeData, NodeData
    from .model import PipelineModel

logger = logging.getLogger(__name__)


class LayoutController:
    """Владелец GUI-состояния layout и операций сохранения/загрузки для Pipeline.

    Владеет позициями (``_gui_positions``), фиксацией (``_locked_nodes``),
    placed-but-unbound боксами (``_placed_display_ids``) и дебаунс-таймером
    авто-персиста (``_persist_timer``); отдаёт их через публичные свойства.
    Коллабораторы (``services``/``model``/``topo``) инжектятся; Qt-реакции — через
    host-контракт (``self._host``).
    """

    # Дебаунс авто-сохранения layout: 400мс после последнего сдвига/фиксации,
    # чтобы не писать файл рецепта на каждый пиксель перетаскивания.
    _PERSIST_DEBOUNCE_MS = 400

    def __init__(
        self,
        host: "PipelineHost",
        *,
        services: "AppServices",
        model: "PipelineModel",
        topo: Any,
    ) -> None:
        self._host = host
        self._services = services
        self._model = model
        # TopologyPresenter (load/save YAML) — стабильный снимок, инжектится.
        self._topo = topo
        # --- GUI-состояние (F.7: владелец — контроллер) -------------------- #
        self._gui_positions: dict[str, tuple[float, float]] = {}
        # Зафиксированные ноды: не двигаются drag'ом и пропускаются авто-раскладкой.
        # Применяется в codec (NodeData.locked); персист в рецепт
        # (metadata.locked_nodes) переживает перезапуск (free-layout Task 3).
        self._locked_nodes: set[str] = set()
        # Task 1.1: GUI-состояние «размещённые, но непривязанные» display-боксы.
        # _build_display_nodes дорисовывает боксы для этих display_id, чтобы они
        # переживали full scene reload в рамках сессии.
        self._placed_display_ids: set[str] = set()
        # free-layout Task 2: debounce-таймер авто-сохранения layout в активный
        # рецепт. Ленивая инициализация (нужен QApplication) — в headless тестах
        # без event loop авто-сохранение пропускается. См. _schedule_layout_persist.
        self._persist_timer: Any = None

    # ------------------------------------------------------------------ #
    #  Публичный API GUI-состояния (F.7: владелец — контроллер)            #
    # ------------------------------------------------------------------ #

    @property
    def gui_positions(self) -> dict[str, tuple[float, float]]:
        """Позиции нод node_id → (x, y). Возвращает живой словарь (мутабелен)."""
        return self._gui_positions

    @gui_positions.setter
    def gui_positions(self, value: dict[str, tuple[float, float]]) -> None:
        self._gui_positions = value

    @property
    def locked_nodes(self) -> set[str]:
        """Множество зафиксированных нод. Возвращает живое множество (мутабельно)."""
        return self._locked_nodes

    @locked_nodes.setter
    def locked_nodes(self, value: set[str]) -> None:
        self._locked_nodes = value

    @property
    def placed_display_ids(self) -> set[str]:
        """Placed-but-unbound display-боксы. Возвращает живое множество (мутабельно)."""
        return self._placed_display_ids

    @placed_display_ids.setter
    def placed_display_ids(self, value: set[str]) -> None:
        self._placed_display_ids = value

    @property
    def persist_timer(self) -> Any:
        """Дебаунс-таймер авто-персиста (QTimer|None). Ленивая инициализация."""
        return self._persist_timer

    def stop_persist_timer(self) -> None:
        """Остановить и сбросить дебаунс-таймер (teardown presenter.dispose, Н-3).

        singleShot QTimer БЕЗ parent; без stop() отложенный timeout после разрушения
        вкладки дёрнул бы _persist_layout_to_recipe на мёртвом окружении (scene уже
        удалена). Идемпотентен — повторный вызов безопасен.
        """
        if self._persist_timer is not None:
            try:
                self._persist_timer.stop()
            except RuntimeError:
                pass  # C++-объект таймера уже удалён Qt — останавливать нечего
            self._persist_timer = None

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
        self._placed_display_ids.clear()
        topology = self._services.topology.load().to_dict()
        self._model.from_topology_dict(topology)

        # Восстановить позиции и фиксацию из metadata (free-layout Task 2/3):
        # gui_positions → стартовое размещение без «Раскладки»; locked_nodes →
        # закреплённые ноды переживают перезапуск.
        metadata = topology.get("metadata", {})
        if isinstance(metadata, dict):
            gui_pos = metadata.get("gui_positions", {})
            if isinstance(gui_pos, dict):
                self._gui_positions = {k: tuple(v) for k, v in gui_pos.items()}
            locked = metadata.get("locked_nodes", [])
            if isinstance(locked, (list, tuple)):
                self._locked_nodes = {str(nid) for nid in locked}

        return self._host.topology_to_graph(topology)

    def load_topology_from_file(self, path: Path) -> tuple[list["NodeData"], list["EdgeData"]]:
        """Загрузить topology из YAML файла."""
        self._topo.load_from_file(path)
        bp = self._topo.blueprint
        data = bp.model_dump() if hasattr(bp, "model_dump") else {}
        self._model.from_topology_dict(data)
        return self._host.topology_to_graph(data)

    def export_topology_with_positions(self) -> dict:
        """Экспортировать topology dict с gui_positions в metadata."""
        topo = self._model.to_topology_dict()

        # Обновить позиции из scene + очистить мусор (ключи не из текущей сцены)
        self._sync_positions_from_scene()

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
    #  Перемещение / фиксация нод (free-layout)                            #
    # ------------------------------------------------------------------ #

    def on_node_moved(self, node_id: str, new_x: float, new_y: float) -> None:
        """Обработчик свободного перемещения ноды (free-layout).

        G.4.4: NODE_MOVE — GUI-only (позиции в _gui_positions/metadata), не
        topology-domain. Drag меняет ТОЛЬКО позицию (членство в процессе не
        трогается). Позиция дебаунс-сохраняется в активный рецепт (Task 2).
        """
        if self._host.is_suppressed:
            return
        self._gui_positions[node_id] = (new_x, new_y)
        self._schedule_layout_persist()

    def set_node_lock(self, node_id: str, locked: bool) -> None:
        """Зафиксировать/освободить ноду явно.

        Locked-нода не перетаскивается (ItemIsMovable=False) и пропускается
        auto_layout_scene. Состояние живёт в _locked_nodes, переприменяется в
        codec при reload и дебаунс-сохраняется в рецепт
        (metadata.locked_nodes) → переживает перезапуск (Task 3).
        """
        if not node_id:
            return
        if locked:
            self._locked_nodes.add(node_id)
        else:
            self._locked_nodes.discard(node_id)
        if self._host.scene:
            self._host.scene.set_node_locked(node_id, locked)
        self._schedule_layout_persist()

    def toggle_node_lock(self, node_id: str) -> None:
        """Переключить фиксацию ноды (правый клик по ноде)."""
        self.set_node_lock(node_id, node_id not in self._locked_nodes)

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
        scene = self._host.scene
        if scene is None:
            return
        self._gui_positions = dict(scene.get_all_node_positions())

    def _schedule_layout_persist(self) -> None:
        """Запланировать (дебаунс) авто-сохранение layout в активный рецепт.

        Ленивая инициализация QTimer: без QApplication (headless-тесты) — no-op,
        авто-сохранение пропускается (явный save_to_active_recipe не зависит от таймера).
        """
        from PySide6.QtWidgets import QApplication

        if QApplication.instance() is None:
            return
        if self._persist_timer is None:
            from PySide6.QtCore import QTimer

            self._persist_timer = QTimer()
            self._persist_timer.setSingleShot(True)
            self._persist_timer.timeout.connect(self._persist_layout_to_recipe)
        self._persist_timer.start(self._PERSIST_DEBOUNCE_MS)

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
        store = self._services.recipes
        active_slug = store.get_active()
        if active_slug is None:
            return

        # Только ноды текущей сцены → не писать в рецепт мусор от прошлых рецептов / legacy.
        self._sync_positions_from_scene()

        gui_positions = {node_id: list(pos) for node_id, pos in self._gui_positions.items()}
        try:
            store.save_layout(active_slug, gui_positions, sorted(self._locked_nodes))
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
        scene = self._host.scene
        if not scene:
            return
        from .graph.constants import CONTAINER_HEADER_H, CONTAINER_INNER_GAP, CONTAINER_PADDING, NODE_WIDTH

        topo = self._model.to_topology_dict()
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
        edges = list(self._model.get_edges_as_tuples())

        # Display-боксы (id = display_id) + binding-рёбра source-процесс → box.
        display_ids: set[str] = set(self._placed_display_ids)
        for d in self._model.get_displays():
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
        with self._host.block_signals():
            for layout_id, (x, y) in positions.items():
                if layout_id in plugin_counts:
                    # Процесс: разложить его плагин-ноды слева-направо группой.
                    members = scene.members_of(layout_id)
                    # Сортируем по plugin_index для стабильного порядка цепочки.
                    members.sort(key=lambda m: m.plugin_index)
                    for j, member in enumerate(members):
                        # Зафиксированную ноду авто-раскладка не трогает.
                        if getattr(member.data, "locked", False):
                            continue
                        mx = x + CONTAINER_PADDING + j * (NODE_WIDTH + CONTAINER_INNER_GAP)
                        my = y + inner_dy
                        member.setPos(mx, my)
                        self._gui_positions[member.node_id] = (mx, my)
                else:
                    # Display-бокс (или fallback) — двигаем сам узел (если не locked).
                    node_item = scene.get_node(layout_id)
                    if node_item is not None and getattr(getattr(node_item, "data", None), "locked", False):
                        continue
                    self._gui_positions[layout_id] = (x, y)
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

        store = self._services.recipes

        # Шаг 1: проверить активный рецепт
        active_slug = store.get_active()
        if active_slug is None:
            QMessageBox.warning(parent, "Сохранение рецепта", "Не выбран активный рецепт")
            return False

        # Шаг 2: сериализовать модель
        bp_dict, bindings, gui_positions = graph_to_blueprint(self._model)

        # Обновить gui_positions из scene (если привязана)
        scene = self._host.scene
        if scene:
            self._gui_positions.update(scene.get_all_node_positions())
        gui_positions = {node_id: list(pos) for node_id, pos in self._gui_positions.items()}

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
            # free-layout Task 2/3: layout живёт ТОЛЬКО в blueprint.metadata — именно
            # оттуда его читает load_topology_from_config и cold-start (unwrap_recipe
            # сохраняет blueprint.metadata). Top-level gui_positions больше не пишем: его
            # не читает ни один live-путь (аудит Ф4.8, AU-1), а normalize_recipe_v3_raw не
            # включает его в результат — Save больше не ВОССОЗДАЁТ удалённый 4.8-дубль.
            # (Физически удалить уже лежащий на диске top-level дубль — задача миграции
            # canonicalize_gui_positions; update_yaml_preserving отсутствующие ключи не трёт.)
            metadata = dict(bp_dict.get("metadata") or {})
            metadata["gui_positions"] = gui_positions
            metadata["locked_nodes"] = sorted(self._locked_nodes)
            bp_dict["metadata"] = metadata
            store.save_raw(active_slug, normalize_recipe_v3_raw(raw_recipe, bp_dict))

            logger.info("Pipeline сохранён в рецепт '%s'", active_slug)
        except Exception as exc:
            logger.exception("Ошибка при сохранении рецепта '%s'", active_slug)
            QMessageBox.critical(parent, "Сохранение рецепта", f"Ошибка: {exc}")
            return False

        QMessageBox.information(parent, "Сохранение рецепта", f"Рецепт сохранён: {active_slug}")
        return True


__all__ = ["LayoutController"]
