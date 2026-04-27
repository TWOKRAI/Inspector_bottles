# multiprocess_prototype_v3/frontend/widgets/tabs_setting/sources_tab/widget.py
"""
SourcesTabWidget — вкладка «Источники»: единое дерево камер + регионов.

Дерево:
  camera_0             комментарий  simulator | 30fps
    □ Параметры
        ⚙ Тип           simulator                  Тип источника
        ⚙ FPS           30                         Частота кадров
        ⚙ Разрешение    640×480                    Размер кадра
    □ main_image     ✓  —          ...          640×480 main proc
      ⚙ x1          0                          Левый край
      ⚙ y1          0                          Верхний край
      ...
    □ region_1       ✓  —          ...          100×100

Колонки: Элемент | Актив./Значение | Дисплей | Комментарий | Сводка.
Для камер/регионов «Актив.» = toggle ✓/✗ (кликом).
Для строк-параметров «Актив.» = значение параметра (read-only).
«Дисплей» и «Комментарий» — редактируемые для камер/регионов.

Клик по любой строке (включая параметры) → detail panel внизу.
"""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from multiprocess_prototype_v3.frontend.widgets.tabs_setting.camera_tab.widget import (
    CameraTabWidget,
)
from multiprocess_prototype_v3.registers.schemas.processing_tab import PROCESSOR_REGISTER

logger = logging.getLogger(__name__)

# Роли
_ROLE_TYPE = Qt.ItemDataRole.UserRole  # "camera"|"region"|"cam_param"|"reg_param"
_ROLE_CAM = Qt.ItemDataRole.UserRole + 1
_ROLE_REG = Qt.ItemDataRole.UserRole + 2
_ROLE_PARAM = Qt.ItemDataRole.UserRole + 3  # param key для строк-параметров

_DEFAULT_REGION = "main_image"

_COL_NAME = 0
_COL_VAL = 1  # Актив./Значение
_COL_COMMENT = 2
_COL_SUMMARY = 3

# Параметры камеры для отображения в дереве
_CAM_PARAMS: list[tuple[str, str]] = [
    ("Тип", "Тип источника"),
    ("FPS", "Частота кадров"),
    ("Статус", "Состояние захвата"),
    ("Разрешение", "Размер кадра"),
]

# Параметры региона для отображения в дереве
_REG_PARAMS: list[tuple[str, str, str]] = [
    ("x1", "x1", "Левый край"),
    ("y1", "y1", "Верхний край"),
    ("x2", "x2", "Правый край"),
    ("y2", "y2", "Нижний край"),
    ("enabled", "enabled", "Активность региона"),
    ("is_main", "is_main", "Основной регион"),
    ("processing_enabled", "processing_enabled", "Обработка включена"),
    ("display", "display", "Дисплей для вывода"),
]


class SourcesTabWidget(QWidget):
    """Вкладка «Источники» — дерево камер/регионов + детальная панель."""

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
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._rm = registers_manager
        self._camera_registry = camera_registry
        self._camera_type = camera_type
        self._action_bus = action_bus

        # Дерево + тулбар
        tree_section = self._build_tree_section()

        # Detail panel
        self._detail = QStackedWidget()

        ph = QLabel("Выберите элемент в дереве")
        ph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ph.setStyleSheet("color: gray; font-size: 13px;")
        self._detail.addWidget(ph)  # page 0

        self._cam_detail = CameraTabWidget(
            camera_type=camera_type,
            registers_manager=registers_manager,
            callbacks_map=callbacks_map,
            command_handler=command_handler,
            ui=camera_tab_ui,
            touch_keyboard=touch_keyboard,
            camera_registry=None,
        )
        self._detail.addWidget(self._cam_detail)  # page 1

        self._reg_form = _RegionForm()
        self._reg_form.changed.connect(self._on_region_form_changed)
        self._detail.addWidget(self._reg_form)  # page 2

        # Layout
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(tree_section)
        splitter.addWidget(self._detail)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 1)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(splitter)

        self._populate_tree()
        if registers_manager is not None:
            registers_manager.subscribe(
                PROCESSOR_REGISTER, "vision_pipeline", self._on_register_changed
            )

    # ------------------------------------------------------------------
    # Дерево + тулбар
    # ------------------------------------------------------------------

    def _build_tree_section(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 4, 4, 4)

        self._tree = QTreeWidget()
        headers = ["Элемент", "Актив./Значение", "Комментарий", "Сводка"]
        self._tree.setHeaderLabels(headers)
        self._tree.setColumnWidth(_COL_NAME, 200)
        self._tree.setColumnWidth(_COL_VAL, 120)
        self._tree.setColumnWidth(_COL_COMMENT, 150)
        self._tree.setColumnWidth(_COL_SUMMARY, 280)
        self._tree.setMinimumHeight(350)
        self._tree.setIndentation(20)
        self._tree.setRootIsDecorated(True)
        self._tree.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self._tree.currentItemChanged.connect(self._on_tree_selection)
        # Toggle ✓/✗ кликом по столбцу «Актив.»
        self._tree.itemClicked.connect(self._on_item_clicked)
        # Inline-редактирование «Дисплей» и «Комментарий»
        self._tree.itemDoubleClicked.connect(self._on_item_dblclick)
        self._tree.itemChanged.connect(self._on_item_edited)
        lay.addWidget(self._tree)

        tb = QHBoxLayout()
        tb.setSpacing(6)
        for label, tip, slot in [
            ("+ Камера", "Добавить камеру", self._on_add_camera),
            ("+ Регион", "Добавить регион к выбранной камере", self._on_add_region),
            ("Удалить", "Удалить выбранный элемент", self._on_remove),
            ("↑", "Переместить вверх", self._on_move_up),
            ("↓", "Переместить вниз", self._on_move_down),
        ]:
            btn = QPushButton(label)
            btn.setToolTip(tip)
            btn.clicked.connect(slot)
            tb.addWidget(btn)
        tb.addStretch()
        lay.addLayout(tb)
        return w

    # ------------------------------------------------------------------
    # Inline-редактирование
    # ------------------------------------------------------------------

    def _on_item_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        """Toggle ✓/✗ кликом по столбцу «Актив.» для камер и регионов."""
        if column != _COL_VAL:
            return
        ntype = item.data(0, _ROLE_TYPE)
        if ntype == "region":
            cam = item.data(0, _ROLE_CAM)
            rname = item.data(0, _ROLE_REG)
            rbc = self._read_regions()
            for r in rbc.get(cam, []):
                if r.get("name") == rname:
                    r["enabled"] = not r.get("enabled", True)
                    break
            self._write_regions(rbc)
            self._populate_tree()

    def _on_item_dblclick(self, item: QTreeWidgetItem, column: int) -> None:
        """Разрешить inline-редактирование «Комментарий»."""
        ntype = item.data(0, _ROLE_TYPE)
        if ntype not in ("camera", "region"):
            return
        if column == _COL_COMMENT:
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            self._tree.editItem(item, column)

    def _on_item_edited(self, item: QTreeWidgetItem, column: int) -> None:
        """Сохранить результат inline-редактирования."""
        if column == _COL_COMMENT:
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)

    # ------------------------------------------------------------------
    # Заполнение дерева
    # ------------------------------------------------------------------

    def _populate_tree(self) -> None:
        # Сохранить выбор
        sel_type, sel_cam, sel_reg, sel_param = None, None, None, None
        cur = self._tree.currentItem()
        if cur:
            sel_type = cur.data(0, _ROLE_TYPE)
            sel_cam = cur.data(0, _ROLE_CAM)
            sel_reg = cur.data(0, _ROLE_REG)
            sel_param = cur.data(0, _ROLE_PARAM)

        self._tree.blockSignals(True)
        self._tree.clear()

        cam_ids = self._camera_registry.camera_ids() if self._camera_registry else [0]
        rbc = self._read_regions()
        restore: QTreeWidgetItem | None = None

        for cam_id in cam_ids:
            cam_key = f"camera_{cam_id}"
            st = (
                self._camera_registry.get_camera_state(cam_id)
                if self._camera_registry
                else {}
            )
            status = st.get("status", "stopped")
            fps = st.get("actual_fps", 0.0)

            # ── Камера ──
            ci = QTreeWidgetItem()
            ci.setText(_COL_NAME, cam_key)
            ci.setText(_COL_VAL, "✓")
            ci.setText(_COL_COMMENT, "")
            ci.setText(_COL_SUMMARY, f"{self._camera_type} | {status} | {fps:.0f} fps")
            ci.setData(0, _ROLE_TYPE, "camera")
            ci.setData(0, _ROLE_CAM, cam_key)
            bf = ci.font(0)
            bf.setBold(True)
            ci.setFont(0, bf)

            # Группа «Параметры» камеры (свёрнута по умолчанию)
            cam_pg = QTreeWidgetItem()
            cam_pg.setText(_COL_NAME, "Параметры")
            cam_pg.setData(0, _ROLE_TYPE, "cam_param")
            cam_pg.setData(0, _ROLE_CAM, cam_key)
            for c in range(4):
                cam_pg.setForeground(c, Qt.GlobalColor.gray)
            ci.addChild(cam_pg)

            cam_vals = {
                "Тип": self._camera_type,
                "FPS": f"{fps:.1f}",
                "Статус": status,
                "Разрешение": "—",
            }
            for pname, pdesc in _CAM_PARAMS:
                pi = self._make_param_item(pname, cam_vals.get(pname, "—"), pdesc)
                pi.setData(0, _ROLE_TYPE, "cam_param")
                pi.setData(0, _ROLE_CAM, cam_key)
                pi.setData(0, _ROLE_PARAM, pname)
                cam_pg.addChild(pi)
                if (
                    sel_type == "cam_param"
                    and sel_cam == cam_key
                    and sel_param == pname
                ):
                    restore = pi

            # ── Регионы ──
            regions = rbc.get(cam_key, [])
            self._ensure_default_region(regions)

            for reg in regions:
                name = reg.get("name", "?")
                x1, y1 = reg.get("x1", 0), reg.get("y1", 0)
                x2, y2 = reg.get("x2", 0), reg.get("y2", 0)
                enabled = reg.get("enabled", True)
                is_main = reg.get("is_main", False)
                proc = reg.get("processing_enabled", True)
                w_h = f"{x2 - x1}×{y2 - y1}"
                flags_str = " ".join(
                    f for f in [
                        "main" if is_main else None,
                        "proc" if proc else None,
                    ] if f
                )

                ri = QTreeWidgetItem()
                ri.setText(_COL_NAME, f"□ {name}")
                ri.setText(_COL_VAL, "✓" if enabled else "✗")
                ri.setText(_COL_COMMENT, str(reg.get("comment", "")))
                ri.setText(_COL_SUMMARY, f"{w_h} {flags_str}")
                ri.setData(0, _ROLE_TYPE, "region")
                ri.setData(0, _ROLE_CAM, cam_key)
                ri.setData(0, _ROLE_REG, name)

                # Группа «Параметры» региона (свёрнута по умолчанию)
                reg_pg = QTreeWidgetItem()
                reg_pg.setText(_COL_NAME, "Параметры")
                reg_pg.setData(0, _ROLE_TYPE, "reg_param")
                reg_pg.setData(0, _ROLE_CAM, cam_key)
                reg_pg.setData(0, _ROLE_REG, name)
                for c in range(4):
                    reg_pg.setForeground(c, Qt.GlobalColor.gray)
                ri.addChild(reg_pg)

                for pname, pkey, pdesc in _REG_PARAMS:
                    val = reg.get(pkey, "")
                    if isinstance(val, bool):
                        val = "✓" if val else "✗"
                    rpi = self._make_param_item(pname, str(val), pdesc)
                    rpi.setData(0, _ROLE_TYPE, "reg_param")
                    rpi.setData(0, _ROLE_CAM, cam_key)
                    rpi.setData(0, _ROLE_REG, name)
                    rpi.setData(0, _ROLE_PARAM, pkey)
                    reg_pg.addChild(rpi)
                    if (
                        sel_type == "reg_param"
                        and sel_cam == cam_key
                        and sel_reg == name
                        and sel_param == pkey
                    ):
                        restore = rpi

                ci.addChild(ri)
                if sel_type == "region" and sel_cam == cam_key and sel_reg == name:
                    restore = ri

            self._tree.addTopLevelItem(ci)
            ci.setExpanded(True)
            if sel_type == "camera" and sel_cam == cam_key:
                restore = ci

        self._tree.blockSignals(False)
        if restore is not None:
            self._tree.setCurrentItem(restore)

    @staticmethod
    def _make_param_item(name: str, value: str, desc: str) -> QTreeWidgetItem:
        """Создать строку-параметр (⚙ name | value | | desc)."""
        item = QTreeWidgetItem()
        item.setText(_COL_NAME, f"  ⚙ {name}")
        item.setText(_COL_VAL, value)
        item.setText(_COL_SUMMARY, desc)
        for c in range(4):
            item.setForeground(c, Qt.GlobalColor.gray)
        return item

    @staticmethod
    def _ensure_default_region(regions: list[dict[str, Any]]) -> None:
        for r in regions:
            if r.get("name") == _DEFAULT_REGION:
                return
        regions.insert(0, {
            "name": _DEFAULT_REGION,
            "x1": 0, "y1": 0, "x2": 640, "y2": 480,
            "enabled": True, "is_main": True, "processing_enabled": True,
        })

    # ------------------------------------------------------------------
    # Выбор → detail panel
    # ------------------------------------------------------------------

    def _on_tree_selection(
        self, current: QTreeWidgetItem | None, _prev: Any
    ) -> None:
        if current is None:
            self._detail.setCurrentIndex(0)
            return
        ntype = current.data(0, _ROLE_TYPE)

        if ntype in ("camera", "cam_param"):
            self._detail.setCurrentIndex(1)

        elif ntype in ("region", "reg_param"):
            cam = current.data(0, _ROLE_CAM)
            rname = current.data(0, _ROLE_REG)
            for r in self._read_regions().get(cam, []):
                if r.get("name") == rname:
                    self._reg_form.load(r)
                    self._detail.setCurrentIndex(2)
                    return
            self._detail.setCurrentIndex(0)
        else:
            self._detail.setCurrentIndex(0)

    # ------------------------------------------------------------------
    # Toolbar
    # ------------------------------------------------------------------

    def _on_add_camera(self) -> None:
        rbc = self._read_regions()
        idx = len(rbc)
        while f"camera_{idx}" in rbc:
            idx += 1
        cam_key = f"camera_{idx}"
        rbc[cam_key] = []
        self._ensure_default_region(rbc[cam_key])
        self._write_regions(rbc)
        self._populate_tree()

    def _on_add_region(self) -> None:
        cam = self._selected_cam()
        if not cam:
            return
        rbc = self._read_regions()
        regions = rbc.get(cam, [])
        self._ensure_default_region(regions)
        names = {r.get("name") for r in regions}
        idx = len(regions)
        while f"region_{idx}" in names:
            idx += 1
        regions.append({
            "name": f"region_{idx}",
            "x1": 0, "y1": 0, "x2": 100, "y2": 100,
            "enabled": True, "is_main": False, "processing_enabled": True,
        })
        rbc[cam] = regions
        self._write_regions(rbc)
        self._populate_tree()

    def _on_remove(self) -> None:
        cur = self._tree.currentItem()
        if cur is None:
            return
        ntype = cur.data(0, _ROLE_TYPE)
        if ntype == "region":
            rname = cur.data(0, _ROLE_REG)
            if rname == _DEFAULT_REGION:
                return
            cam = cur.data(0, _ROLE_CAM)
            rbc = self._read_regions()
            rbc[cam] = [r for r in rbc.get(cam, []) if r.get("name") != rname]
            self._write_regions(rbc)
            self._detail.setCurrentIndex(0)
            self._populate_tree()
        elif ntype == "camera":
            cam = cur.data(0, _ROLE_CAM)
            rbc = self._read_regions()
            rbc.pop(cam, None)
            self._write_regions(rbc)
            self._detail.setCurrentIndex(0)
            self._populate_tree()

    def _on_move_up(self) -> None:
        self._move_item(-1)

    def _on_move_down(self) -> None:
        self._move_item(1)

    def _move_item(self, direction: int) -> None:
        cur = self._tree.currentItem()
        if cur is None:
            return
        ntype = cur.data(0, _ROLE_TYPE)
        if ntype == "region":
            cam = cur.data(0, _ROLE_CAM)
            rname = cur.data(0, _ROLE_REG)
            rbc = self._read_regions()
            regions = rbc.get(cam, [])
            idx = next((i for i, r in enumerate(regions) if r.get("name") == rname), -1)
            if idx < 0:
                return
            j = idx + direction
            if j < 0 or j >= len(regions):
                return
            regions[idx], regions[j] = regions[j], regions[idx]
            rbc[cam] = regions
            self._write_regions(rbc)
            self._populate_tree()
        elif ntype == "camera":
            cam = cur.data(0, _ROLE_CAM)
            rbc = self._read_regions()
            keys = list(rbc.keys())
            idx = keys.index(cam) if cam in keys else -1
            if idx < 0:
                return
            j = idx + direction
            if j < 0 or j >= len(keys):
                return
            keys[idx], keys[j] = keys[j], keys[idx]
            self._write_regions({k: rbc[k] for k in keys})
            self._populate_tree()

    # ------------------------------------------------------------------
    # Region form → register
    # ------------------------------------------------------------------

    def _on_region_form_changed(self) -> None:
        cur = self._tree.currentItem()
        if cur is None:
            return
        ntype = cur.data(0, _ROLE_TYPE)
        if ntype in ("reg_param", "region"):
            cam = cur.data(0, _ROLE_CAM)
            old_name = cur.data(0, _ROLE_REG)
        else:
            return
        rbc = self._read_regions()
        regions = rbc.get(cam, [])
        form = self._reg_form.read()
        for i, r in enumerate(regions):
            if r.get("name") == old_name:
                regions[i] = {**r, **form}
                break
        rbc[cam] = regions
        self._write_regions(rbc)
        self._populate_tree()

    # ------------------------------------------------------------------
    # Register I/O
    # ------------------------------------------------------------------

    def _read_regions(self) -> dict[str, list[dict[str, Any]]]:
        rm = self._rm
        if rm is None:
            return {}
        reg = rm.get_register(PROCESSOR_REGISTER)
        if reg is None:
            return {}
        try:
            from multiprocess_prototype_v3.registers.schemas.pipeline.widget_bridge import (
                pipeline_config_from_register,
                post_list_from_pipeline,
            )
            return dict(post_list_from_pipeline(pipeline_config_from_register(reg)))
        except Exception:
            logger.debug("Не удалось прочитать регионы", exc_info=True)
            return {}

    def _write_regions(self, rbc: dict[str, list[dict]]) -> None:
        rm = self._rm
        if rm is None:
            return
        reg = rm.get_register(PROCESSOR_REGISTER)
        if reg is None:
            return
        try:
            from multiprocess_prototype_v3.registers.schemas.pipeline.widget_bridge import (
                apply_post_list_to_pipeline,
                pipeline_config_from_register,
            )
            cfg = apply_post_list_to_pipeline(
                pipeline_config_from_register(reg), rbc
            )
            rm.set_field_value(
                PROCESSOR_REGISTER,
                "vision_pipeline",
                cfg.model_dump(mode="python"),
            )
        except Exception:
            logger.exception("Не удалось записать регионы")

    def _on_register_changed(self, _r: str, _f: str, _v: Any) -> None:
        self._populate_tree()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _selected_cam(self) -> str | None:
        cur = self._tree.currentItem()
        return cur.data(0, _ROLE_CAM) if cur else None

    # ------------------------------------------------------------------
    # API для MainWindow
    # ------------------------------------------------------------------

    def sync_camera_type(self, camera_type: str) -> None:
        self._camera_type = camera_type
        self._cam_detail.sync_camera_type(camera_type)
        self._populate_tree()

    def update_camera_devices(self, devices: list) -> None:
        self._cam_detail.update_camera_devices(devices)

    def update_camera_parameters(self, params: dict) -> None:
        self._cam_detail.update_camera_parameters(params)


# ======================================================================
# Форма редактирования региона
# ======================================================================


class _RegionForm(QWidget):
    """Детальная форма одного региона."""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._block = False

        group = QGroupBox("Редактирование региона")
        g = QGridLayout(group)
        row = 0

        g.addWidget(QLabel("Имя:"), row, 0)
        self._name = QLineEdit()
        g.addWidget(self._name, row, 1, 1, 3)
        row += 1

        for lbl, attr, col_off in [
            ("x1:", "_x1", 0), ("y1:", "_y1", 2),
            ("x2:", "_x2", 0), ("y2:", "_y2", 2),
        ]:
            if col_off == 0:
                row += 1
            g.addWidget(QLabel(lbl), row, col_off)
            spin = QSpinBox()
            spin.setRange(0, 100000)
            setattr(self, attr, spin)
            g.addWidget(spin, row, col_off + 1)

        row += 1
        self._enabled = QCheckBox("Включён")
        self._is_main = QCheckBox("Основной (main)")
        self._processing = QCheckBox("Обработка включена")
        g.addWidget(self._enabled, row, 0, 1, 2)
        g.addWidget(self._is_main, row, 2, 1, 2)
        row += 1
        g.addWidget(self._processing, row, 0, 1, 2)

        row += 1
        g.addWidget(QLabel("Дисплей:"), row, 0)
        self._display = QLineEdit()
        self._display.setPlaceholderText("Имя дисплея (напр. display_0)")
        g.addWidget(self._display, row, 1, 1, 3)

        row += 1
        g.addWidget(QLabel("Комментарий:"), row, 0)
        self._comment = QLineEdit()
        g.addWidget(self._comment, row, 1, 1, 3)

        layout = QVBoxLayout(self)
        layout.addWidget(group)
        layout.addStretch()

        self._name.editingFinished.connect(self._emit)
        self._display.editingFinished.connect(self._emit)
        self._comment.editingFinished.connect(self._emit)
        for sp in (self._x1, self._y1, self._x2, self._y2):
            sp.valueChanged.connect(self._emit)
        for cb in (self._enabled, self._is_main, self._processing):
            cb.stateChanged.connect(self._emit)

    def load(self, data: dict[str, Any]) -> None:
        self._block = True
        self._name.setText(str(data.get("name", "")))
        self._x1.setValue(int(data.get("x1", 0)))
        self._y1.setValue(int(data.get("y1", 0)))
        self._x2.setValue(int(data.get("x2", 0)))
        self._y2.setValue(int(data.get("y2", 0)))
        self._enabled.setChecked(bool(data.get("enabled", True)))
        self._is_main.setChecked(bool(data.get("is_main", False)))
        self._processing.setChecked(bool(data.get("processing_enabled", True)))
        self._display.setText(str(data.get("display", "")))
        self._comment.setText(str(data.get("comment", "")))
        self._block = False

    def read(self) -> dict[str, Any]:
        return {
            "name": self._name.text().strip(),
            "x1": self._x1.value(), "y1": self._y1.value(),
            "x2": self._x2.value(), "y2": self._y2.value(),
            "enabled": self._enabled.isChecked(),
            "is_main": self._is_main.isChecked(),
            "processing_enabled": self._processing.isChecked(),
            "display": self._display.text().strip(),
            "comment": self._comment.text().strip(),
        }

    def _emit(self) -> None:
        if not self._block:
            self.changed.emit()
