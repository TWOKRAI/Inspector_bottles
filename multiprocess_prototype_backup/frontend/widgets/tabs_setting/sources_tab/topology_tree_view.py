"""TopologyTreeView — дерево камер/регионов на базе EntityTreeWidget.

Иерархия в дереве (единый стиль с ProcessTreeView):
  ■ camera_0                 | ✓        |               | process_0 | process | 640×480 | 25fps
    □ Параметры
      ⚙ Тип                 | simulator| Тип источника |
      ⚙ FPS                 | 25       | Частота кадров|
      ...
    □ region_0_main          | ✓        |               | 640×480 main proc
      □ Параметры
        ⚙ x1                | 0        | Левый край    |
        ...

Сигналы:
    camera_param_changed(cam_key, pkey, value): изменён параметр камеры.
    region_param_changed(reg_key, pkey, value): изменён параметр региона.
    region_toggled(reg_key, enabled): переключена активность региона.
"""
from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QStandardItem

from multiprocess_prototype.frontend.widgets.base.editor.entity_tree_widget import (
    ROLE_CHILD,
    ROLE_PARAM,
    ROLE_PARENT,
    ROLE_TYPE,
    EntityTreeWidget,
)
from multiprocess_prototype.frontend.widgets.base.editor.topology_editor_model import TopologyEditorModel
from .sources_tree_config import SOURCES_TREE_CONFIG

logger = logging.getLogger(__name__)

# Булевы поля региона, которые переключаются по одиночному клику
_REG_BOOL_PARAMS = frozenset({"enabled", "is_main", "processing_enabled", "shm_enabled"})

# Индексы колонок
_COL_NAME = 0
_COL_VAL = 1

# Цвета (совпадают с EntityTreeWidget)
_COLOR_GRAY = QColor(140, 140, 140)
_COLOR_GROUP = QColor(150, 150, 150)

# Параметры камеры, которые не редактируются inline
_CAM_READONLY_PARAMS = {"resolution", "channels"}


class TopologyTreeView(EntityTreeWidget):
    """Дерево топологии: камеры -> регионы -> параметры.

    Наследует EntityTreeWidget и переопределяет _populate() для загрузки
    данных из TopologyEditorModel. Использует sources-специфичные ROLE_TYPE
    значения ("camera", "region", "cam_param", "reg_param") для совместимости
    с SourcesTabWidget.

    Signals:
        camera_param_changed(cam_key, pkey, value): изменён параметр камеры.
        region_param_changed(reg_key, pkey, value): изменён параметр региона.
        region_toggled(reg_key, enabled): переключена активность региона.
    """

    camera_param_changed = Signal(str, str, object)  # (cam_key, pkey, value)
    region_param_changed = Signal(str, str, object)   # (reg_key, pkey, value)
    region_toggled = Signal(str, bool)                 # (reg_key, enabled)

    def __init__(self, model: TopologyEditorModel, *, parent=None) -> None:
        """Инициализировать дерево с заданной моделью топологии.

        Args:
            model: Модель редактора топологии (камеры + регионы).
            parent: Родительский виджет.
        """
        super().__init__(SOURCES_TREE_CONFIG, parent=parent)
        self._topo_model = model

        # Подключение обработчиков кликов
        self._tree.doubleClicked.connect(self._on_dblclick)
        self._tree.clicked.connect(self._on_click)

    # ------------------------------------------------------------------
    # Переопределение _populate — полностью кастомная логика
    # ------------------------------------------------------------------

    def _populate(self, root: QStandardItem) -> None:
        """Заполнить дерево из модели топологии.

        Строит иерархию: Camera -> Параметры + Регионы -> Параметры региона.
        Использует sources-специфичные ROLE_TYPE значения для совместимости
        с SourcesTabWidget (widget.py).

        Args:
            root: Корневой элемент модели (invisibleRootItem).
        """
        cameras = self._topo_model.cameras

        if not cameras:
            placeholder = QStandardItem("Нет данных")
            placeholder.setFlags(Qt.ItemFlag.ItemIsEnabled)
            root.appendRow([placeholder])
            return

        for cam_key, cam in cameras.items():
            cam_vals = self._flatten_camera(cam)

            # Строка камеры
            cam_row = self._make_camera_row(cam_key, cam_vals)
            root.appendRow(cam_row)
            cam_item = cam_row[0]

            # Группа параметров камеры
            cam_params_group = self._make_sources_group_item(
                "Параметры", "cam_param_group", cam_key
            )
            cam_item.appendRow(self._make_full_row(cam_params_group))
            self._populate_cam_params(cam_params_group, cam_key, cam_vals)

            # Регионы камеры, отсортированные по sort_order
            cam_regions = self._topo_model.regions_for_camera(cam_key)
            sorted_regions = sorted(
                cam_regions.items(),
                key=lambda kv: kv[1].get("sort_order", 0),
            )
            for reg_key, reg in sorted_regions:
                reg_vals = self._flatten_region(reg)

                reg_row = self._make_region_row(reg_key, reg_vals, cam_key)
                cam_item.appendRow(reg_row)
                reg_item = reg_row[0]

                # Группа параметров региона
                reg_params_group = self._make_sources_group_item(
                    "Параметры", "reg_param_group", cam_key, reg_key
                )
                reg_item.appendRow(self._make_full_row(reg_params_group))
                self._populate_reg_params(reg_params_group, cam_key, reg_key, reg_vals)

    # ------------------------------------------------------------------
    # Построители строк
    # ------------------------------------------------------------------

    def _make_camera_row(self, cam_key: str, cam_vals: dict) -> list[QStandardItem]:
        """Создать строку-заголовок камеры (bold, ■ иконка).

        Args:
            cam_key:  Ключ камеры.
            cam_vals: Плоский dict значений параметров камеры.

        Returns:
            Список из 4 QStandardItem.
        """
        level = self._config.parent_level

        # Сводка
        summary = ""
        if level.summary_builder is not None:
            try:
                summary = level.summary_builder(cam_vals)
            except Exception:
                summary = ""

        display_name = f"{level.icon} {cam_key}"

        name_item = QStandardItem(display_name)
        font = QFont()
        font.setBold(True)
        name_item.setFont(font)
        name_item.setData(cam_key, Qt.ItemDataRole.UserRole)
        # Sources-специфичные типы для совместимости с widget.py
        name_item.setData("camera", ROLE_TYPE)
        name_item.setData(cam_key, ROLE_PARENT)
        name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

        active_item = QStandardItem("✓")
        active_item.setFlags(active_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

        comment_item = QStandardItem("")
        comment_item.setFlags(comment_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

        summary_item = QStandardItem(summary)
        summary_item.setFlags(summary_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

        return self._pad_row([name_item, active_item, comment_item, summary_item])

    def _make_region_row(
        self, reg_key: str, reg_vals: dict, cam_key: str
    ) -> list[QStandardItem]:
        """Создать строку-заголовок региона (□ иконка, enabled ✓/✗).

        Args:
            reg_key:  Ключ региона.
            reg_vals: Плоский dict значений параметров региона.
            cam_key:  Ключ родительской камеры.

        Returns:
            Список из 4 QStandardItem.
        """
        level = self._config.child_level

        enabled = reg_vals.get("enabled", True)
        if isinstance(enabled, bool):
            active_str = "✓" if enabled else "✗"
        elif isinstance(enabled, str):
            active_str = "✓" if enabled.lower() == "true" else "✗"
        else:
            active_str = "✓"

        # Сводка
        summary = ""
        if level.summary_builder is not None:
            try:
                summary = level.summary_builder(reg_vals)
            except Exception:
                summary = ""

        display_name = f"{level.icon} {reg_key}"

        name_item = QStandardItem(display_name)
        name_item.setData(reg_key, Qt.ItemDataRole.UserRole)
        # Sources-специфичные типы для совместимости с widget.py
        name_item.setData("region", ROLE_TYPE)
        name_item.setData(cam_key, ROLE_PARENT)
        name_item.setData(reg_key, ROLE_CHILD)
        name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

        active_item = QStandardItem(active_str)
        active_item.setFlags(active_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

        comment_item = QStandardItem("")
        comment_item.setFlags(comment_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

        summary_item = QStandardItem(summary)
        summary_item.setFlags(summary_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

        return self._pad_row([name_item, active_item, comment_item, summary_item])

    def _make_sources_group_item(
        self,
        label: str,
        type_str: str,
        cam_key: str,
        reg_key: str | None = None,
    ) -> QStandardItem:
        """Создать item-группу с sources-специфичными ролями.

        Args:
            label:    Текст группы.
            type_str: Значение ROLE_TYPE ("cam_param_group" / "reg_param_group").
            cam_key:  Ключ камеры.
            reg_key:  Ключ региона (опционально).

        Returns:
            Настроенный QStandardItem.
        """
        item = QStandardItem(f"□ {label}")
        item.setForeground(_COLOR_GROUP)
        item.setData(type_str, ROLE_TYPE)
        item.setData(cam_key, ROLE_PARENT)
        if reg_key is not None:
            item.setData(reg_key, ROLE_CHILD)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        return item

    def _populate_cam_params(
        self,
        parent: QStandardItem,
        cam_key: str,
        cam_vals: dict,
    ) -> None:
        """Добавить строки параметров камеры в группу.

        Args:
            parent:   Родительский item (группа «Параметры»).
            cam_key:  Ключ камеры.
            cam_vals: Плоский dict значений параметров камеры.
        """
        for param_def in self._config.parent_level.params:
            raw_value = cam_vals.get(param_def.key)
            display_value = self._format_param_value(raw_value, param_def)

            row = self._make_param_row(
                f"⚙ {param_def.label}", display_value, param_def.comment
            )

            # Установить sources-специфичные роли
            item = row[0]
            item.setData("cam_param", ROLE_TYPE)
            item.setData(cam_key, ROLE_PARENT)
            item.setData(param_def.key, ROLE_PARAM)

            # Readonly-параметры — снять флаг ItemIsEditable у COL_VAL
            val_item = row[1]
            if param_def.key in _CAM_READONLY_PARAMS or not param_def.editable:
                val_item.setFlags(val_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

            parent.appendRow(row)

    def _populate_reg_params(
        self,
        parent: QStandardItem,
        cam_key: str,
        reg_key: str,
        reg_vals: dict,
    ) -> None:
        """Добавить строки параметров региона в группу.

        Args:
            parent:   Родительский item (группа «Параметры» региона).
            cam_key:  Ключ камеры.
            reg_key:  Ключ региона.
            reg_vals: Плоский dict значений параметров региона.
        """
        for param_def in self._config.child_level.params:
            raw_value = reg_vals.get(param_def.key)
            display_value = self._format_param_value(raw_value, param_def)

            row = self._make_param_row(
                f"⚙ {param_def.label}", display_value, param_def.comment
            )

            # Установить sources-специфичные роли
            item = row[0]
            item.setData("reg_param", ROLE_TYPE)
            item.setData(cam_key, ROLE_PARENT)
            item.setData(reg_key, ROLE_CHILD)
            item.setData(param_def.key, ROLE_PARAM)

            parent.appendRow(row)

    # ------------------------------------------------------------------
    # Преобразование dict-конфигураций в плоский формат
    # ------------------------------------------------------------------

    @staticmethod
    def _flatten_camera(cam: dict) -> dict[str, Any]:
        """Извлечь плоский dict значений параметров камеры.

        Args:
            cam: dict-конфигурация камеры из TopologyEditorModel.

        Returns:
            Плоский словарь {param_key: value}.
        """
        regs = cam.get("registers", {})
        shm = cam.get("shm_config", {})
        w = shm.get("width", 640)
        h = shm.get("height", 480)
        ch = shm.get("channels", 3)
        return {
            "camera_type": regs.get("camera_type", cam.get("camera_type", "simulator")),
            "fps": str(regs.get("fps", 30)),
            "resolution": f"{w}×{h}",
            "channels": "RGB" if ch == 3 else "Gray",
            "process_name": cam.get("process_name", ""),
            "execution_mode": cam.get("execution_mode", "process"),
            "region_processing": cam.get("region_processing", "dedicated_processor"),
            "ring_slots": str(shm.get("ring_slots", 3)),
        }

    @staticmethod
    def _flatten_region(reg: dict) -> dict[str, Any]:
        """Извлечь плоский dict значений параметров региона.

        Args:
            reg: dict-конфигурация региона из TopologyEditorModel.

        Returns:
            Плоский словарь {param_key: value}.
        """
        rect = reg.get("rect", {})
        x = rect.get("x", 0)
        y = rect.get("y", 0)
        w = rect.get("width", 0)
        h = rect.get("height", 0)
        return {
            "x1": str(x),
            "y1": str(y),
            "x2": str(x + w),
            "y2": str(y + h),
            "enabled": reg.get("enabled", True),
            "is_main": reg.get("is_main", False),
            "processing_enabled": reg.get("processing_enabled", True),
            "shm_enabled": reg.get("shm_enabled", False),
        }

    # ------------------------------------------------------------------
    # Переопределение save/restore selection для sources-специфичных ролей
    # ------------------------------------------------------------------

    def _save_selection(self) -> Any:
        """Сохранить выделение как tuple (ROLE_TYPE, ROLE_PARENT, ROLE_CHILD, ROLE_PARAM).

        Использует sources-специфичные типы (camera, region, cam_param, reg_param).
        """
        index = self._tree.selectionModel().currentIndex()
        if not index.isValid():
            return None
        item = self._model.itemFromIndex(
            self._model.index(index.row(), 0, index.parent())
        )
        if item is None:
            return None
        return (
            item.data(ROLE_TYPE),
            item.data(ROLE_PARENT),
            item.data(ROLE_CHILD),
            item.data(ROLE_PARAM),
        )

    # ------------------------------------------------------------------
    # Обработчики событий
    # ------------------------------------------------------------------

    def _on_click(self, index) -> None:  # noqa: ANN001
        """Обработать одиночный клик — toggle bool-значений.

        Переключает:
        - Активность региона (строка region, колонка COL_VAL).
        - Bool-параметры региона: enabled, is_main, processing_enabled, shm_enabled.

        Args:
            index: QModelIndex кликнутого элемента.
        """
        if self._suppress:
            return

        # Берём item из первой колонки строки для получения ролей
        first_col_index = self._model.index(index.row(), _COL_NAME, index.parent())
        name_item = self._model.itemFromIndex(first_col_index)
        if name_item is None:
            return

        item_type = name_item.data(ROLE_TYPE)

        # Toggle активности региона (клик по COL_VAL строки region)
        if item_type == "region" and index.column() == _COL_VAL:
            reg_key = name_item.data(ROLE_CHILD)
            val_index = self._model.index(index.row(), _COL_VAL, index.parent())
            val_item = self._model.itemFromIndex(val_index)
            if val_item is None:
                return
            current_enabled = val_item.text() == "✓"
            new_enabled = not current_enabled
            with self._block():
                val_item.setText("✓" if new_enabled else "✗")
            logger.debug("Toggle region '%s': enabled=%s", reg_key, new_enabled)
            self.region_toggled.emit(reg_key, new_enabled)

        # Toggle bool-параметра региона
        elif item_type == "reg_param" and index.column() == _COL_VAL:
            pkey = name_item.data(ROLE_PARAM)
            if pkey not in _REG_BOOL_PARAMS:
                return
            reg_key = name_item.data(ROLE_CHILD)
            val_index = self._model.index(index.row(), _COL_VAL, index.parent())
            val_item = self._model.itemFromIndex(val_index)
            if val_item is None:
                return
            # Текущее значение разбираем из ✓/✗
            current_val = val_item.text() == "✓"
            new_val = not current_val
            with self._block():
                val_item.setText("✓" if new_val else "✗")
            logger.debug("Toggle reg_param '%s'.%s: %s -> %s", reg_key, pkey, current_val, new_val)
            self.region_param_changed.emit(reg_key, pkey, new_val)

    def _on_dblclick(self, index) -> None:  # noqa: ANN001
        """Обработать двойной клик — inline editing.

        Phase 5: будет добавлен delegate для редактирования значений.
        Пока не реализовано.

        Args:
            index: QModelIndex дважды кликнутого элемента.
        """
        # TODO(Phase 5): подключить делегата для inline editing
        pass  # noqa: PIE790


__all__ = ["TopologyTreeView"]
