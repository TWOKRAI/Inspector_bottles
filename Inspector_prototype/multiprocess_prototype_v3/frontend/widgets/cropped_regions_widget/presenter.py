# multiprocess_prototype_v3/frontend/widgets/cropped_regions_widget/presenter.py
"""Логика ROI без привязки к разметке Qt (кроме сообщений через view)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Optional

from multiprocess_prototype_v3.registers.schemas.pipeline.widget_bridge import (
    apply_crop_nested_to_pipeline,
    crop_nested_from_pipeline,
    pipeline_config_from_register,
)
from multiprocess_prototype_v3.registers.schemas.processing_tab import PROCESSOR_REGISTER

from .model import CroppedRegionsModel
from .params import (
    DEFAULT_CROPPED_PARAMS,
    coords_list_from_params,
    params_from_coords_list,
    params_to_rect,
    parse_int_coordinate,
)

if TYPE_CHECKING:
    from .view import CroppedRegionsPanelViewProtocol


_TABLE_COL_KEYS = ("name", "x", "y", "width", "height")


class CroppedRegionsPresenter:
    def __init__(self, *, view: CroppedRegionsPanelViewProtocol, model: CroppedRegionsModel) -> None:
        self._view = view
        self._model = model

    def _default_camera_id(self) -> str:
        ids = self._model.ui.camera_ids or []
        return ids[0] if ids else "default"

    def _logical_ids_from_register(self) -> List[str]:
        rm = self._model.registers_manager
        if rm is None:
            return []
        reg = rm.get_register(PROCESSOR_REGISTER)
        if reg is None:
            return []
        raw = getattr(reg, "logical_camera_ids", None)
        if isinstance(raw, list):
            return [str(x) for x in raw]
        return []

    def camera_ids_union(self) -> List[str]:
        cfg = list(self._model.ui.camera_ids or [])
        keys = list(self._model.crop_regions_by_camera.keys())
        logical = self._logical_ids_from_register()
        u = sorted(set(cfg) | set(keys) | set(logical))
        if not u:
            u = [self._default_camera_id()]
        return u

    def _fill_region_combo(self) -> None:
        cam, reg_sel = self._view.get_tree_selection()
        cam = cam or self._model.selected_camera
        regions = self._model.crop_regions_by_camera.get(cam, {})
        names = sorted(regions.keys())
        current = reg_sel
        self._view.set_region_combo_options(names, current)

    def load_from_register(self) -> None:
        """Считать vision_pipeline → ROI в model и обновить UI."""
        rm = self._model.registers_manager
        if rm is None:
            self._view.set_camera_options(self.camera_ids_union(), self._default_camera_id())
            self._view.refresh_table()
            self._fill_region_combo()
            return
        reg = rm.get_register(PROCESSOR_REGISTER)
        if reg is None or not hasattr(reg, "vision_pipeline"):
            self._apply_loaded_state({})
            return
        nested = crop_nested_from_pipeline(pipeline_config_from_register(reg))
        self._apply_loaded_state(nested)

    def _apply_loaded_state(self, normalized: dict) -> None:
        self._model.crop_regions_by_camera.clear()
        self._model.crop_regions_by_camera.update(normalized)
        ids = self.camera_ids_union()
        if self._model.selected_camera not in ids:
            self._model.selected_camera = ids[0]
        self._view.set_camera_options(ids, self._model.selected_camera)
        self._view.refresh_table()
        self._view.set_region_name_text("")
        self._view.apply_controls_params(DEFAULT_CROPPED_PARAMS)
        self._view.clear_table_selection()
        self._fill_region_combo()

    def on_region_combo_selected(self, region_name: str) -> None:
        """Выбор региона из ComboBox — выделить лист в дереве."""
        if not region_name:
            return
        self._view.select_region(self._model.selected_camera, region_name)

    def on_tree_selection(self, camera_id: Optional[str], region_key: Optional[str]) -> None:
        """Выделение в дереве: камера и/или регион."""
        if camera_id is None:
            self._view.set_region_name_text("")
            self._view.apply_controls_params(DEFAULT_CROPPED_PARAMS)
            self.refresh_rect_label()
            self._fill_region_combo()
            return
        self._model.selected_camera = camera_id
        if not region_key:
            self._view.set_region_name_text("")
            self._view.apply_controls_params(DEFAULT_CROPPED_PARAMS)
            self.refresh_rect_label()
            self._fill_region_combo()
            return
        regions = self._model.crop_regions_by_camera.get(camera_id, {})
        if region_key in regions:
            coords = regions[region_key]
            self._view.apply_controls_params(params_from_coords_list(coords))
            self._view.set_region_name_text(region_key)
        else:
            self._view.set_region_name_text("")
            self._view.apply_controls_params(DEFAULT_CROPPED_PARAMS)
        self.refresh_rect_label()
        self._fill_region_combo()

    def on_leaf_cell_changed(
        self, camera_id: str, region_name: str, column_key: str, value: Any
    ) -> None:
        """Правка ячейки листа: имя (переименование) или координаты."""
        self._model.selected_camera = camera_id
        if column_key not in _TABLE_COL_KEYS:
            return
        row_data = self._view.read_leaf_row(camera_id, region_name)
        if not row_data:
            return
        old_key = row_data.get("region_id") or region_name
        if not old_key:
            return
        regions = self._model.crop_regions_by_camera.setdefault(camera_id, {})
        if old_key not in regions:
            self._view.refresh_table()
            self._fill_region_combo()
            return

        u = self._view.ui

        if column_key == "name":
            new_name = (row_data.get("name") or "").strip()
            if new_name == old_key:
                return
            if not new_name:
                self._view.show_warning(u.group_regions, "Введите имя региона.")
                self._view.refresh_table()
                self._view.select_region(camera_id, old_key)
                self._fill_region_combo()
                return
            if new_name in regions:
                self._view.show_warning(u.group_regions, "Регион с таким именем уже есть.")
                self._view.refresh_table()
                self._view.select_region(camera_id, old_key)
                self._fill_region_combo()
                return
            coords = regions.pop(old_key)
            regions[new_name] = coords
            self._push_register()
            self._view.refresh_table()
            self._view.select_region(camera_id, new_name)
            self._fill_region_combo()
            if self._view.selected_region_key() == new_name:
                self._view.set_region_name_text(new_name)
                self._view.apply_controls_params(params_from_coords_list(coords))
            self.refresh_rect_label()
            return

        x = parse_int_coordinate(row_data.get("x"))
        y = parse_int_coordinate(row_data.get("y"))
        w = parse_int_coordinate(row_data.get("width"))
        h = parse_int_coordinate(row_data.get("height"))
        regions[old_key] = [x, y, w, h]
        self._push_register()
        self._view.refresh_table()
        self._view.select_region(camera_id, old_key)
        self._fill_region_combo()
        if self._view.selected_region_key() == old_key:
            self._view.apply_controls_params(params_from_coords_list(regions[old_key]))
        self.refresh_rect_label()

    def on_params_changed(self) -> None:
        """Контролы изменены — обновить выбранный регион и регистр."""
        cam, key = self._view.get_tree_selection()
        key = key or self._view.selected_region_key()
        cam = cam or self._model.selected_camera
        if not key:
            return
        regions = self._model.crop_regions_by_camera.setdefault(cam, {})
        if key in regions:
            regions[key] = coords_list_from_params(self._view.get_controls_params())
            self._view.refresh_table()
            self._view.select_region(cam, key)
            self._push_register()
            self._fill_region_combo()
        self.refresh_rect_label()

    def on_add(self) -> None:
        """Новый регион: имя из поля имени + текущие координаты."""
        u = self._view.ui
        name = self._view.get_region_name_text().strip()
        cam = self._model.selected_camera
        regions = self._model.crop_regions_by_camera.setdefault(cam, {})
        if not name:
            self._view.show_warning(u.group_regions, "Введите имя региона.")
            return
        if name in regions:
            self._view.show_warning(u.group_regions, "Регион с таким именем уже есть.")
            return
        regions[name] = coords_list_from_params(self._view.get_controls_params())
        self._view.refresh_table()
        self._view.select_region(cam, name)
        self._push_register()
        self._fill_region_combo()
        self.refresh_rect_label()

    def on_remove(self) -> None:
        """Удалить выбранный регион текущей камеры."""
        cam, key = self._view.get_tree_selection()
        key = key or self._view.selected_region_key()
        cam = cam or self._model.selected_camera
        if not key:
            return
        regions = self._model.crop_regions_by_camera.setdefault(cam, {})
        if key in regions:
            del regions[key]
        self._view.refresh_table()
        self._view.set_region_name_text("")
        self._view.apply_controls_params(DEFAULT_CROPPED_PARAMS)
        self._view.clear_table_selection()
        self._push_register()
        self._fill_region_combo()
        self.refresh_rect_label()

    def on_save_to_region(self) -> None:
        """Сохранить координаты; при смене имени — переименовать выбранный регион."""
        u = self._view.ui
        cam, key = self._view.get_tree_selection()
        key = key or self._view.selected_region_key()
        cam = cam or self._model.selected_camera
        new_name = self._view.get_region_name_text().strip()
        regions = self._model.crop_regions_by_camera.setdefault(cam, {})
        if not key:
            self._view.show_information(
                u.group_regions,
                "Выберите регион в дереве или добавьте регион.",
            )
            return
        if not new_name:
            self._view.show_warning(u.group_regions, "Введите имя региона.")
            return
        coords = coords_list_from_params(self._view.get_controls_params())
        if new_name != key:
            if new_name in regions:
                self._view.show_warning(u.group_regions, "Регион с таким именем уже есть.")
                return
            regions.pop(key, None)
            regions[new_name] = coords
        else:
            regions[key] = coords
        self._view.refresh_table()
        self._view.select_region(cam, new_name)
        self._view.set_region_name_text(new_name)
        self._push_register()
        self._fill_region_combo()
        self.refresh_rect_label()

    def refresh_rect_label(self) -> None:
        p = self._view.get_controls_params()
        r = params_to_rect(p)
        self._view.set_rect_label_text(
            f"Текущий rect: x={r['x']}, y={r['y']}, width={r['width']}, height={r['height']}"
        )

    def _push_register(self) -> None:
        rm = self._model.registers_manager
        if rm is None:
            return
        reg = rm.get_register(PROCESSOR_REGISTER)
        if reg is None:
            return
        cfg = apply_crop_nested_to_pipeline(
            pipeline_config_from_register(reg),
            self._model.crop_regions_by_camera,
            color_lower=list(reg.color_lower),
            color_upper=list(reg.color_upper),
            min_area=int(reg.min_area),
            max_area=int(reg.max_area),
        )
        rm.set_field_value(
            PROCESSOR_REGISTER,
            "vision_pipeline",
            cfg.model_dump(mode="python"),
        )
