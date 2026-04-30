"""SourcesTabWidget -- вкладка "Источники": composition shell.

Однонаправленный поток: action -> model -> tree/panel.
Запись в регистры только по кнопке "Применить".

Использует SystemTopologyEditor + SourcesSectionView.
"""
from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from multiprocess_prototype.frontend.actions.builder import ActionBuilder

from .camera_panel.widget import CameraTabWidget
from .constants import ROLE_TYPE, ROLE_CAM, ROLE_REG
from .region_form import RegionForm
from .topology_tree_view import TopologyTreeView

logger = logging.getLogger(__name__)


class SourcesTabWidget(QWidget):
    """Вкладка "Источники" -- дерево камер/регионов + детальная панель.

    Архитектура composition shell:
    - SourcesSectionView -- хранилище данных (из SystemTopologyEditor)
    - TopologyTreeView   -- дерево (read-only view)
    - TopologyBridge     -- запись в регистры
    - ActionBus          -- undo/redo через snapshot-based actions
    """

    def __init__(
        self,
        *,
        camera_type: str = "simulator",
        registers_manager: Any | None = None,
        callbacks_map: dict[str, Any] | None = None,
        command_handler: Any | None = None,
        camera_tab_ui: Any | None = None,
        post_processing_ui: Any | None = None,
        touch_keyboard: Any | None = None,
        camera_registry: Any | None = None,
        action_bus: Any | None = None,
        topology_editor: Any | None = None,
        topology_bridge: Any | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._camera_type = camera_type
        self._camera_registry = camera_registry
        self._action_bus = action_bus

        # Ссылки на editor/bridge
        self._topology_editor = topology_editor
        self._topology_bridge = topology_bridge

        # -- Model --
        # SourcesSectionView как duck-typed модель (.cameras, .regions, .dirty)
        self._section = topology_editor.sources if topology_editor is not None else None
        self._model = self._section

        # -- Tree View --
        self._tree = TopologyTreeView(self._model)

        # -- Toolbar --
        toolbar = self._build_toolbar()

        # Tree + Toolbar в один контейнер
        tree_section = QWidget()
        tree_layout = QVBoxLayout(tree_section)
        tree_layout.setContentsMargins(4, 4, 4, 4)
        tree_layout.addWidget(self._tree)
        tree_layout.addLayout(toolbar)

        # -- Detail Panel (stacked) --
        self._detail = QStackedWidget()

        # Page 0: placeholder
        ph = QLabel("Выберите элемент в дереве")
        ph.setObjectName("PlaceholderLabel")
        ph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._detail.addWidget(ph)

        # Page 1: CameraTabWidget
        self._cam_detail = CameraTabWidget(
            camera_type=camera_type,
            registers_manager=registers_manager,
            callbacks_map=callbacks_map,
            command_handler=command_handler,
            ui=camera_tab_ui,
            touch_keyboard=touch_keyboard,
            camera_registry=None,
        )
        self._detail.addWidget(self._cam_detail)

        # Page 2: RegionForm
        self._reg_form = RegionForm()
        self._detail.addWidget(self._reg_form)

        # -- Layout: splitter --
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(tree_section)
        splitter.addWidget(self._detail)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 1)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(splitter)

        # -- ActionBus: привязать topology handler --
        if action_bus is not None and hasattr(action_bus, '_topology_handler'):
            action_bus._topology_handler.set_model(self._model)

        # -- Wiring подписок на изменения модели --
        if topology_editor is not None:
            # Подписка через SystemTopologyEditor
            from multiprocess_prototype.registers.system_topology.schemas import SECTION_SOURCES
            topology_editor.subscribe(SECTION_SOURCES, self._on_model_changed)

        # Tree -> selection -> detail panel
        self._tree.item_selected.connect(self._on_item_selected)
        self._tree.selection_cleared.connect(lambda: self._detail.setCurrentIndex(0))

        # Tree -> toggle/param changes -> model
        self._tree.region_toggled.connect(self._on_region_toggled)
        self._tree.region_param_changed.connect(self._on_region_param_changed)
        self._tree.camera_param_changed.connect(self._on_camera_param_changed)

        # RegionForm -> model
        self._reg_form.changed.connect(self._on_region_form_changed)

        # Инициализировать дерево
        self._tree.refresh()

    # ------------------------------------------------------------------
    # Toolbar
    # ------------------------------------------------------------------

    def _build_toolbar(self) -> QHBoxLayout:
        """Построить панель кнопок."""
        tb = QHBoxLayout()
        tb.setSpacing(6)
        for label, tip, slot in [
            ("+ Камера", "Добавить камеру", self._on_add_camera),
            ("+ Регион", "Добавить регион к выбранной камере", self._on_add_region),
            ("Удалить", "Удалить выбранный элемент", self._on_remove),
            ("\u2191", "Переместить вверх", self._on_move_up),
            ("\u2193", "Переместить вниз", self._on_move_down),
        ]:
            btn = QPushButton(label)
            btn.setToolTip(tip)
            btn.clicked.connect(slot)
            tb.addWidget(btn)

        tb.addStretch()

        self._btn_apply = QPushButton("Применить")
        self._btn_apply.setToolTip("Сохранить изменения в регистры")
        self._btn_apply.setEnabled(False)
        self._btn_apply.clicked.connect(self._on_apply)
        tb.addWidget(self._btn_apply)

        return tb

    # ------------------------------------------------------------------
    # Model -> View
    # ------------------------------------------------------------------

    def _on_model_changed(self) -> None:
        """Callback при любом изменении модели."""
        self._tree.refresh()
        is_dirty = self._model.dirty
        self._btn_apply.setEnabled(is_dirty)
        # Визуальная индикация: accent стиль когда есть несохранённые изменения
        if is_dirty:
            self._btn_apply.setStyleSheet(
                "QPushButton { background-color: #e67e22; color: white; font-weight: bold; }"
            )
        else:
            self._btn_apply.setStyleSheet("")

    # ------------------------------------------------------------------
    # Tree selection -> detail panel
    # ------------------------------------------------------------------

    def _on_item_selected(self, key: str) -> None:
        """Переключить detail panel в зависимости от выбранного элемента."""
        item = self._tree._find_item(key)
        if item is None:
            self._detail.setCurrentIndex(0)
            return

        ntype = item.data(ROLE_TYPE)

        if ntype in ("camera", "cam_param", "cam_param_group"):
            self._detail.setCurrentIndex(1)

        elif ntype in ("region", "reg_param", "reg_param_group"):
            reg_key = item.data(ROLE_REG)
            regions = self._model.regions
            if reg_key and reg_key in regions:
                reg = regions[reg_key]
                rect = reg.get("rect", {})
                self._reg_form.load({
                    "name": reg_key,
                    "x1": rect.get("x", 0),
                    "y1": rect.get("y", 0),
                    "x2": rect.get("x", 0) + rect.get("width", 640),
                    "y2": rect.get("y", 0) + rect.get("height", 480),
                    "enabled": reg.get("enabled", True),
                    "is_main": reg.get("is_main", False),
                    "processing_enabled": reg.get("processing_enabled", True),
                })
                self._detail.setCurrentIndex(2)
            else:
                self._detail.setCurrentIndex(0)
        else:
            self._detail.setCurrentIndex(0)

    # ------------------------------------------------------------------
    # Toolbar actions -> model (с ActionBus)
    # ------------------------------------------------------------------

    def _on_add_camera(self) -> None:
        before = self._model.full_snapshot()
        cam_key, _reg_key = self._section.add_camera(self._camera_type)
        after = self._model.full_snapshot()
        self._record_action(ActionBuilder.topology_camera_add(cam_key, before, after))

    def _on_add_region(self) -> None:
        cam_key = self._selected_cam()
        if not cam_key:
            return
        before = self._model.full_snapshot()
        reg_key = self._section.add_region(cam_key)
        after = self._model.full_snapshot()
        self._record_action(ActionBuilder.topology_region_add(reg_key, before, after))

    def _on_remove(self) -> None:
        item = self._get_selected_item()
        if item is None:
            return

        ntype = item.data(ROLE_TYPE)
        before = self._model.full_snapshot()

        if ntype == "region":
            reg_key = item.data(ROLE_REG)
            try:
                self._model.remove_region(reg_key)
            except (KeyError, ValueError):
                return
            after = self._model.full_snapshot()
            self._record_action(ActionBuilder.topology_region_remove(reg_key, before, after))
            self._detail.setCurrentIndex(0)

        elif ntype == "camera":
            cam_key = item.data(ROLE_CAM)
            try:
                self._model.remove_camera(cam_key)
            except KeyError:
                return
            after = self._model.full_snapshot()
            self._record_action(ActionBuilder.topology_camera_remove(cam_key, before, after))
            self._detail.setCurrentIndex(0)

    def _on_move_up(self) -> None:
        self._move_item(-1)

    def _on_move_down(self) -> None:
        self._move_item(1)

    def _move_item(self, direction: int) -> None:
        item = self._get_selected_item()
        if item is None:
            return

        ntype = item.data(ROLE_TYPE)
        before = self._model.full_snapshot()

        if ntype == "region":
            reg_key = item.data(ROLE_REG)
            self._model.reorder_regions(reg_key, direction)
            after = self._model.full_snapshot()
            self._record_action(ActionBuilder.topology_reorder(reg_key, direction, before, after))

        elif ntype == "camera":
            cam_key = item.data(ROLE_CAM)
            self._model.reorder_cameras(cam_key, direction)
            after = self._model.full_snapshot()
            self._record_action(ActionBuilder.topology_reorder(cam_key, direction, before, after))

    # ------------------------------------------------------------------
    # Tree param signals -> model
    # ------------------------------------------------------------------

    def _on_region_toggled(self, reg_key: str, enabled: bool) -> None:
        before = self._model.full_snapshot()
        self._model.modify_region(reg_key, {"enabled": enabled})
        after = self._model.full_snapshot()
        self._record_action(ActionBuilder.topology_modify(reg_key, "enabled", before, after))

    def _on_region_param_changed(self, reg_key: str, pkey: str, value: Any) -> None:
        before = self._model.full_snapshot()
        self._model.modify_region(reg_key, {pkey: value})
        after = self._model.full_snapshot()
        self._record_action(ActionBuilder.topology_modify(reg_key, pkey, before, after))

    def _on_camera_param_changed(self, cam_key: str, pkey: str, value: Any) -> None:
        before = self._model.full_snapshot()
        self._model.modify_camera(cam_key, {pkey: value})
        after = self._model.full_snapshot()
        self._record_action(ActionBuilder.topology_modify(cam_key, pkey, before, after))

    # ------------------------------------------------------------------
    # RegionForm -> model
    # ------------------------------------------------------------------

    def _on_region_form_changed(self) -> None:
        # Найти текущий выбранный регион
        item = self._get_selected_item()
        if item is None:
            return
        ntype = item.data(ROLE_TYPE)
        if ntype not in ("region", "reg_param", "reg_param_group"):
            return

        reg_key = item.data(ROLE_REG)
        regions = self._model.regions
        if not reg_key or reg_key not in regions:
            return

        form = self._reg_form.read()
        x1, y1 = form.get("x1", 0), form.get("y1", 0)
        x2, y2 = form.get("x2", 0), form.get("y2", 0)

        fields = {
            "rect": {"x": x1, "y": y1, "width": max(0, x2 - x1), "height": max(0, y2 - y1)},
            "enabled": form.get("enabled", True),
            "is_main": form.get("is_main", False),
            "processing_enabled": form.get("processing_enabled", True),
        }

        before = self._model.full_snapshot()
        self._model.modify_region(reg_key, fields)
        after = self._model.full_snapshot()
        self._record_action(ActionBuilder.topology_modify(reg_key, "rect", before, after))

    # ------------------------------------------------------------------
    # Apply -> register
    # ------------------------------------------------------------------

    def _on_apply(self) -> None:
        """Сохранить модель в регистры через TopologyBridge."""
        if self._topology_bridge is not None:
            from multiprocess_prototype.registers.system_topology.schemas import SECTION_SOURCES
            if self._topology_bridge.apply(SECTION_SOURCES):
                self._btn_apply.setEnabled(False)
                self._btn_apply.setStyleSheet("")

    # ------------------------------------------------------------------
    # ActionBus helpers
    # ------------------------------------------------------------------

    def _record_action(self, action: Any) -> None:
        """Записать action в ActionBus (если доступен)."""
        if self._action_bus is not None:
            self._action_bus.record(action)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_selected_item(self):
        """Получить QStandardItem из текущего выделения дерева (первая колонка)."""
        index = self._tree._tree.selectionModel().currentIndex()
        if not index.isValid():
            return None
        return self._tree._model.itemFromIndex(
            self._tree._model.index(index.row(), 0, index.parent())
        )

    def _selected_cam(self) -> str | None:
        """Получить cam_key из текущего выбора в дереве."""
        item = self._get_selected_item()
        if item is None:
            return None
        return item.data(ROLE_CAM)

    # ------------------------------------------------------------------
    # Public API (backward compat)
    # ------------------------------------------------------------------

    def sync_camera_type(self, camera_type: str) -> None:
        """Обновить тип камеры."""
        self._camera_type = camera_type
        self._cam_detail.sync_camera_type(camera_type)
        self._tree.refresh()

    def update_camera_devices(self, devices: list) -> None:
        """Обновить список доступных устройств камер."""
        self._cam_detail.update_camera_devices(devices)

    def update_camera_parameters(self, params: dict) -> None:
        """Обновить параметры камеры."""
        self._cam_detail.update_camera_parameters(params)
