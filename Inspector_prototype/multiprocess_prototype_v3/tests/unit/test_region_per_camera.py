"""Unit-тесты Phase 4: per-camera regions, routing, CameraRegistry integration."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from multiprocess_prototype_v3.registers.pipeline.region import Region
from multiprocess_prototype_v3.registers.processor.schemas import ProcessorRegisters
from multiprocess_prototype_v3.backend.processes.processor.commands import (
    _apply_vision_pipeline,
    build_state_config_handlers,
)
from multiprocess_prototype_v3.frontend.managers.camera_registry import (
    CameraEntry,
    CameraRegistry,
)

# Model, Presenter, Schemas — circular import через __init__.py (panel_widget → Qt).
# Загружаем напрямую по файлу через importlib, минуя __init__.py.
import importlib.util
from pathlib import Path

_WIDGET_DIR = (
    Path(__file__).resolve().parents[2] / "frontend" / "widgets" / "processing" / "cropped_regions_widget"
)


def _load_module_from_file(name: str, file_path: Path):
    """Загрузить модуль по файлу, минуя пакетный __init__.py."""
    spec = importlib.util.spec_from_file_location(name, str(file_path))
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


try:
    _schemas_mod = _load_module_from_file(
        "multiprocess_prototype_v3.frontend.widgets.processing.cropped_regions_widget.schemas",
        _WIDGET_DIR / "schemas.py",
    )
    CroppedRegionsTabUiConfig = _schemas_mod.CroppedRegionsTabUiConfig

    _model_mod = _load_module_from_file(
        "multiprocess_prototype_v3.frontend.widgets.processing.cropped_regions_widget.model",
        _WIDGET_DIR / "model.py",
    )
    CroppedRegionsModel = _model_mod.CroppedRegionsModel

    _presenter_mod = _load_module_from_file(
        "multiprocess_prototype_v3.frontend.widgets.processing.cropped_regions_widget.presenter",
        _WIDGET_DIR / "presenter.py",
    )
    CroppedRegionsPresenter = _presenter_mod.CroppedRegionsPresenter

    _HAS_PRESENTER = True
except Exception:
    _HAS_PRESENTER = False

needs_presenter = pytest.mark.skipif(not _HAS_PRESENTER, reason="frontend imports not available")


# --- Фейковый View для presenter тестов (только при наличии PyQt5) ---

if _HAS_PRESENTER:

    @dataclass
    class FakeView:
        """Минимальный View-протокол для CroppedRegionsPresenter."""

        ui: CroppedRegionsTabUiConfig = field(default_factory=CroppedRegionsTabUiConfig)
        camera_options: List[str] = field(default_factory=list)
        selected_camera: str = ""
        region_combo_names: List[str] = field(default_factory=list)
        region_name_text: str = ""
        controls_params: Dict[str, Any] = field(default_factory=dict)
        rect_label_text: str = ""
        _tree_selection: tuple = (None, None)
        _warnings: List[str] = field(default_factory=list)

        def set_camera_options(self, ids: List[str], selected: str) -> None:
            self.camera_options = ids
            self.selected_camera = selected

        def set_region_combo_options(self, names: List[str], selected: Optional[str]) -> None:
            self.region_combo_names = names

        def refresh_table(self) -> None:
            pass

        def set_region_name_text(self, text: str) -> None:
            self.region_name_text = text

        def get_region_name_text(self) -> str:
            return self.region_name_text

        def apply_controls_params(self, params: Dict[str, Any]) -> None:
            self.controls_params = params

        def get_controls_params(self) -> Dict[str, Any]:
            return self.controls_params or {"x": 0, "y": 0, "width": 100, "height": 100}

        def clear_table_selection(self) -> None:
            pass

        def get_tree_selection(self):
            return self._tree_selection

        def selected_region_key(self) -> Optional[str]:
            return self._tree_selection[1]

        def select_region(self, camera_id: str, region_name: str) -> None:
            self._tree_selection = (camera_id, region_name)

        def set_rect_label_text(self, text: str) -> None:
            self.rect_label_text = text

        def show_warning(self, title: str, text: str) -> None:
            self._warnings.append(text)

        def show_information(self, title: str, text: str) -> None:
            pass

        def read_leaf_row(self, camera_id: str, region_name: str) -> Optional[Dict[str, Any]]:
            return None


# --- Тесты ---


class TestRegionSteps:
    """Task 4.1: Region schema с полем steps."""

    def test_default_steps_empty(self):
        r = Region()
        assert r.steps == []

    def test_steps_round_trip(self):
        steps_data = [{"op": "blur", "ksize": 5}, {"op": "threshold", "value": 128}]
        r = Region(steps=steps_data)
        dumped = r.model_dump()
        assert dumped["steps"] == steps_data
        restored = Region.model_validate(dumped)
        assert restored.steps == steps_data

    def test_steps_does_not_break_existing_fields(self):
        r = Region(enabled=False, sort_order=3)
        assert r.enabled is False
        assert r.sort_order == 3
        assert r.steps == []


class TestVisionPipelineRouting:
    """Task 4.2: vision_pipeline field имеет routing metadata."""

    def test_vision_pipeline_has_routing(self):
        meta = ProcessorRegisters.get_field_meta("vision_pipeline")
        assert meta is not None
        routing = meta.routing
        assert routing is not None
        # routing может быть FieldRouting или dict в зависимости от резолвинга
        if hasattr(routing, "channel"):
            assert routing.channel == "control_processor"
        else:
            assert routing["channel"] == "control_processor"

    def test_vision_pipeline_default_empty(self):
        reg = ProcessorRegisters()
        assert reg.vision_pipeline == {}


@needs_presenter
class TestCameraIdsUnionWithRegistry:
    """Task 4.4: presenter camera_ids_union() с CameraRegistry."""

    def _make_presenter(
        self,
        camera_registry=None,
        camera_ids=None,
        crop_regions_by_camera=None,
    ) -> CroppedRegionsPresenter:
        ui = CroppedRegionsTabUiConfig(camera_ids=camera_ids or [])
        model = CroppedRegionsModel(
            registers_manager=None,
            ui=ui,
            camera_registry=camera_registry,
            crop_regions_by_camera=crop_regions_by_camera or {},
        )
        view = FakeView(ui=ui)
        return CroppedRegionsPresenter(view=view, model=model)

    def test_with_registry(self):
        """CameraRegistry с камерами 0, 1, 2 → dropdown содержит '0', '1', '2'."""
        registry = CameraRegistry(
            [
                {"camera_id": 0, "camera_type": "simulator"},
                {"camera_id": 1, "camera_type": "webcam"},
                {"camera_id": 2, "camera_type": "hikvision"},
            ]
        )
        p = self._make_presenter(camera_registry=registry)
        ids = p.camera_ids_union()
        assert ids == ["0", "1", "2"]

    def test_without_registry_fallback(self):
        """Без CameraRegistry — fallback на ui.camera_ids."""
        p = self._make_presenter(camera_ids=["cam_a", "cam_b"])
        ids = p.camera_ids_union()
        assert ids == ["cam_a", "cam_b"]

    def test_registry_plus_data_keys(self):
        """Registry + существующие данные объединяются."""
        registry = CameraRegistry([{"camera_id": 0, "camera_type": "simulator"}])
        p = self._make_presenter(
            camera_registry=registry,
            crop_regions_by_camera={"0": {}, "extra": {}},
        )
        ids = p.camera_ids_union()
        assert "0" in ids
        assert "extra" in ids

    def test_empty_all_sources_default(self):
        """Пустые все источники → fallback на default camera id."""
        p = self._make_presenter()
        ids = p.camera_ids_union()
        assert len(ids) == 1


@needs_presenter
class TestPerCameraRegionCrud:
    """Task 4.4: CRUD региона на камере не затрагивает другие камеры."""

    def _make_presenter(self, camera_registry=None):
        ui = CroppedRegionsTabUiConfig(camera_ids=[])
        model = CroppedRegionsModel(
            registers_manager=None,
            ui=ui,
            camera_registry=camera_registry,
            selected_camera="0",
        )
        view = FakeView(ui=ui)
        return CroppedRegionsPresenter(view=view, model=model), model, view

    def test_add_region_per_camera(self):
        registry = CameraRegistry(
            [
                {"camera_id": 0, "camera_type": "simulator"},
                {"camera_id": 1, "camera_type": "webcam"},
            ]
        )
        p, model, view = self._make_presenter(camera_registry=registry)

        # Добавляем регион к камере "0"
        model.selected_camera = "0"
        view.region_name_text = "roi_left"
        view.controls_params = {"x": 10, "y": 20, "width": 100, "height": 50}
        p.on_add()

        assert "roi_left" in model.crop_regions_by_camera.get("0", {})

        # Камера "1" не затронута
        assert model.crop_regions_by_camera.get("1", {}) == {}

    def test_remove_region_per_camera(self):
        registry = CameraRegistry(
            [
                {"camera_id": 0, "camera_type": "simulator"},
                {"camera_id": 1, "camera_type": "webcam"},
            ]
        )
        p, model, view = self._make_presenter(camera_registry=registry)

        # Подготовка: регионы в обеих камерах
        model.crop_regions_by_camera["0"] = {"roi_a": [0, 0, 100, 100]}
        model.crop_regions_by_camera["1"] = {"roi_b": [10, 10, 50, 50]}

        # Удаляем из кам��ры "0"
        model.selected_camera = "0"
        view._tree_selection = ("0", "roi_a")
        p.on_remove()

        assert "roi_a" not in model.crop_regions_by_camera.get("0", {})
        # Камера "1" не затронута
        assert "roi_b" in model.crop_regions_by_camera["1"]


class TestBuildStateConfigHandlers:
    """Task 4.5: build_state_config_handlers содержит vision_pipeline."""

    def test_has_vision_pipeline_handler(self):
        service = MagicMock()
        handlers = build_state_config_handlers(service)
        assert "vision_pipeline" in handlers

    def test_has_existing_handlers(self):
        service = MagicMock()
        handlers = build_state_config_handlers(service)
        for key in ("color_lower", "color_upper", "min_area", "max_area"):
            assert key in handlers


class TestApplyVisionPipeline:
    """Task 4.5: _apply_vision_pipeline парсит pipeline dict."""

    def test_extracts_params_from_pipeline(self):
        service = MagicMock()
        pipeline_data = {
            "cameras": {
                "0": {
                    "enabled": True,
                    "regions": {
                        "roi_left": {
                            "rect": {"x": 0, "y": 0, "width": 100, "height": 100},
                            "enabled": True,
                            "processing_blocks": {
                                "color_detect": {
                                    "params": {
                                        "color_lower": [10, 20, 30],
                                        "color_upper": [100, 200, 255],
                                        "min_area": 200,
                                        "max_area": 10000,
                                    }
                                }
                            },
                        }
                    },
                }
            }
        }
        _apply_vision_pipeline(service, pipeline_data)
        service.set_color_range.assert_called_once_with(lower=[10, 20, 30], upper=[100, 200, 255])
        service.set_min_area.assert_called_once_with(200)
        service.set_max_area.assert_called_once_with(10000)

    def test_malformed_data_no_crash(self):
        """Некорректные данные не вызывают исключения."""
        service = MagicMock()
        _apply_vision_pipeline(service, "not a dict")
        _apply_vision_pipeline(service, {})
        _apply_vision_pipeline(service, {"cameras": "bad"})
        _apply_vision_pipeline(service, {"cameras": {"0": "bad"}})
        # Ни один вызов service не должен произойти
        service.set_color_range.assert_not_called()

    def test_empty_regions(self):
        """Пустые регионы — handler не падает, service не вызывается."""
        service = MagicMock()
        _apply_vision_pipeline(service, {"cameras": {"0": {"regions": {}}}})
        service.set_color_range.assert_not_called()


@needs_presenter
class TestPresenterPushRegisterRoundTrip:
    """L2: presenter → _push_register → RegistersManager → read back."""

    def test_round_trip(self):
        from multiprocess_prototype_v3.registers import create_registers

        rm, _ = create_registers()
        ui = CroppedRegionsTabUiConfig(camera_ids=["0"])
        model = CroppedRegionsModel(
            registers_manager=rm,
            ui=ui,
            selected_camera="0",
        )
        view = FakeView(ui=ui)
        presenter = CroppedRegionsPresenter(view=view, model=model)

        # Добавляем регион
        model.selected_camera = "0"
        view.region_name_text = "test_roi"
        view.controls_params = {"x": 10, "y": 20, "width": 200, "height": 150}
        presenter.on_add()

        # Читаем обратно из RegistersManager
        reg = rm.get_register("processor")
        pipeline = reg.vision_pipeline
        assert isinstance(pipeline, dict)

        # Проверяем структуру: cameras -> "0" -> regions -> "test_roi"
        cameras = pipeline.get("cameras", {})
        assert "0" in cameras
        regions = cameras["0"].get("regions", {})
        assert "test_roi" in regions
        rect = regions["test_roi"].get("rect", {})
        assert rect.get("x") == 10
        assert rect.get("y") == 20
        assert rect.get("width") == 200
        assert rect.get("height") == 150
