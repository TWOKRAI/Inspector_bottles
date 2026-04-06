# multiprocess_prototype/frontend/widgets/post_processing_widget/presenter.py
"""Логика постобработки регионов (без прямого Qt кроме сообщений через view)."""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, List, Optional, Tuple

from multiprocess_prototype_v2.registers.names import PROCESSOR_REGISTER
from multiprocess_prototype_v2.registers.vision_pipeline.widget_bridge import (
    apply_post_list_to_pipeline,
    pipeline_config_from_register,
    post_list_from_pipeline,
)

from .model import PostProcessingModel
from .params import (
    default_new_region,
    normalize_region_entry,
)

if TYPE_CHECKING:
    from .view import PostProcessingPanelViewProtocol


class PostProcessingPresenter:
    def __init__(self, *, view: PostProcessingPanelViewProtocol, model: PostProcessingModel) -> None:
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
        keys = list(self._model.post_regions_by_camera.keys())
        logical = self._logical_ids_from_register()
        u = sorted(set(cfg) | set(keys) | set(logical))
        if not u:
            u = [self._default_camera_id()]
        return u

    def _region_index(self, camera_id: str, region_name: str) -> int:
        regions = self._model.post_regions_by_camera.get(camera_id, [])
        for i, r in enumerate(regions):
            if str(r.get("name", "")) == region_name:
                return i
        return -1

    def _current_selection(self) -> Tuple[Optional[str], Optional[str]]:
        return self._view.get_tree_selection()

    def load_from_register(self) -> None:
        rm = self._model.registers_manager
        if rm is None:
            self._view.refresh_table()
            self._view.apply_form_from_region(None)
            return
        reg = rm.get_register(PROCESSOR_REGISTER)
        self._model.post_regions_by_camera.clear()
        if reg is not None:
            self._model.post_regions_by_camera.update(
                post_list_from_pipeline(pipeline_config_from_register(reg))
            )
        ids = self.camera_ids_union()
        if self._model.selected_camera not in ids:
            self._model.selected_camera = ids[0]
        self._view.refresh_table()
        self._view.apply_form_from_region(None)

    def on_tree_selection(self, camera_id: Optional[str], region_name: Optional[str]) -> None:
        if camera_id is None:
            self._view.apply_form_from_region(None)
            return
        self._model.selected_camera = camera_id
        if not region_name:
            self._view.apply_form_from_region(None)
            return
        regions = self._model.post_regions_by_camera.get(camera_id, [])
        for r in regions:
            if str(r.get("name", "")) == region_name:
                self._view.apply_form_from_region(r)
                return
        self._view.apply_form_from_region(None)

    def on_leaf_cell_changed(
        self, camera_id: str, region_name: str, column_key: str, value: object
    ) -> None:
        self._model.selected_camera = camera_id
        regions = self._model.post_regions_by_camera.setdefault(camera_id, [])
        row = self._region_index(camera_id, region_name)
        if row < 0:
            return
        if column_key == "enabled":
            regions[row]["enabled"] = bool(value)
        elif column_key == "is_main":
            regions[row]["is_main"] = bool(value)
        elif column_key == "processing_enabled":
            regions[row]["processing_enabled"] = bool(value)
        else:
            return
        self._push_register()
        self._view.block_form_signals(True)
        self._view.refresh_table()
        self._view.select_region(camera_id, region_name)
        self._view.apply_form_from_region(regions[row])
        self._view.block_form_signals(False)

    def on_form_apply(self) -> None:
        cam, name = self._current_selection()
        if not cam or not name:
            return
        self._model.selected_camera = cam
        regions = self._model.post_regions_by_camera.setdefault(cam, [])
        row = self._region_index(cam, name)
        if row < 0:
            return
        old = regions[row]
        merged = normalize_region_entry({**old, **self._view.read_form_region()})
        new_name = merged["name"]
        if new_name != old.get("name"):
            names = [r.get("name") for r in regions if r is not old]
            if new_name in names:
                u = self._view.ui
                self._view.show_warning(u.group_edit, "Регион с таким именем уже есть.")
                self._view.apply_form_from_region(old)
                return
        regions[row] = merged
        self._push_register()
        self._view.block_form_signals(True)
        self._view.refresh_table()
        self._view.select_region(cam, new_name)
        self._view.apply_form_from_region(regions[row])
        self._view.block_form_signals(False)

    def on_add(self) -> None:
        cam, _ = self._current_selection()
        cam = cam or self._model.selected_camera
        if not cam:
            ids = self.camera_ids_union()
            cam = ids[0] if ids else self._default_camera_id()
        self._model.selected_camera = cam
        regions = self._model.post_regions_by_camera.setdefault(cam, [])
        names = [str(r.get("name", "")) for r in regions]
        regions.append(default_new_region(names))
        self._push_register()
        self._view.refresh_table()
        new_name = str(regions[-1].get("name", ""))
        self._view.select_region(cam, new_name)
        self._view.apply_form_from_region(regions[-1])

    def on_remove(self) -> None:
        cam, name = self._current_selection()
        if not cam or not name:
            return
        self._model.selected_camera = cam
        regions = self._model.post_regions_by_camera.setdefault(cam, [])
        row = self._region_index(cam, name)
        if row < 0:
            return
        r = regions[row]
        u = self._view.ui
        if r.get("is_main") or r.get("name") == "main_image":
            self._view.show_warning(u.group_regions, "Нельзя удалить основной регион.")
            return
        if not self._view.confirm_delete(f"Удалить регион «{r.get('name', '')}»?"):
            return
        regions.pop(row)
        self._push_register()
        self._view.refresh_table()
        self._view.apply_form_from_region(None)

    def on_move(self, direction: int) -> None:
        cam, name = self._current_selection()
        if not cam or not name:
            return
        self._model.selected_camera = cam
        regions = self._model.post_regions_by_camera.setdefault(cam, [])
        row = self._region_index(cam, name)
        if row < 0:
            return
        j = row + direction
        if j < 0 or j >= len(regions):
            return
        regions[row], regions[j] = regions[j], regions[row]
        self._push_register()
        self._view.block_form_signals(True)
        self._view.refresh_table()
        self._view.select_region(cam, str(regions[j].get("name", "")))
        self._view.apply_form_from_region(regions[j])
        self._view.block_form_signals(False)

    def on_copy(self) -> None:
        cam, name = self._current_selection()
        if not cam or not name:
            return
        self._model.selected_camera = cam
        regions = self._model.post_regions_by_camera.setdefault(cam, [])
        row = self._region_index(cam, name)
        if row < 0:
            return
        self._model.clipboard_region = copy.deepcopy(regions[row])
        u = self._view.ui
        self._view.show_information(u.group_regions, "Регион скопирован в буфер вкладки.")

    def on_paste(self) -> None:
        src = self._model.clipboard_region
        if not src or not isinstance(src, dict):
            u = self._view.ui
            self._view.show_warning(u.group_regions, "Нет скопированного региона.")
            return
        cam, _ = self._current_selection()
        cam = cam or self._model.selected_camera
        if not cam:
            ids = self.camera_ids_union()
            cam = ids[0] if ids else self._default_camera_id()
        self._model.selected_camera = cam
        regions = self._model.post_regions_by_camera.setdefault(cam, [])
        names = [str(r.get("name", "")) for r in regions]
        base = str(src.get("name", "region")) + "_copy"
        new_name = base
        n = 1
        while new_name in names:
            new_name = f"{base}_{n}"
            n += 1
        reg = normalize_region_entry({**src, "name": new_name})
        regions.append(reg)
        self._push_register()
        self._view.refresh_table()
        self._view.select_region(cam, new_name)
        self._view.apply_form_from_region(regions[-1])

    def on_show_region_stub(self) -> None:
        u = self._view.ui
        self._view.show_information(
            u.group_regions,
            "В прототипе кнопка не связана с окном просмотра (заглушка).",
        )

    def on_back_to_main_stub(self) -> None:
        u = self._view.ui
        self._view.show_information(
            u.group_regions,
            "В прототипе режим «основное изображение» не передаётся в процесс (заглушка).",
        )

    def _push_register(self) -> None:
        rm = self._model.registers_manager
        if rm is None:
            return
        reg = rm.get_register(PROCESSOR_REGISTER)
        if reg is None:
            return
        cfg = apply_post_list_to_pipeline(
            pipeline_config_from_register(reg),
            self._model.post_regions_by_camera,
        )
        rm.set_field_value(
            PROCESSOR_REGISTER,
            "vision_pipeline",
            cfg.model_dump(mode="python"),
        )
