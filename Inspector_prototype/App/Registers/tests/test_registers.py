# -*- coding: utf-8 -*-
"""
Тесты RegistersManager и регистров App Inspector.

Проверяет:
    - создание RegistersManager с пакетами по умолчанию
    - наличие всех регистров
    - доступ к полям как plain-значениям
    - метаданные полей через FieldMeta
    - валидацию значений (validate_field)
    - обновление значений (update_field)
    - сериализацию (model_dump_all / to_json / to_dict)
    - load/save через FileStorage
    - RegisterBase.get_field_meta на уровне класса

Запуск: из корня Inspector_prototype — pytest App/Registers/tests/ -v
"""
import json
import tempfile
from pathlib import Path

import pytest

from App.Registers import RegistersManager
from App.Registers.models.registers.draw import DrawRegisters
from App.Registers.models.data.camera import CameraData
from App.Registers.models.data.region import RegionData


# =============================================================================
# Фикстуры
# =============================================================================

@pytest.fixture()
def rm() -> RegistersManager:
    """Свежий RegistersManager с дефолтными пакетами."""
    return RegistersManager()


# =============================================================================
# Тесты RegistersManager
# =============================================================================

class TestRegistersManager:

    def test_creates_with_default_packages(self, rm):
        """RegistersManager создаётся без ошибок с пакетами по умолчанию."""
        assert rm is not None

    def test_has_expected_registers(self, rm):
        """Все ожидаемые регистры присутствуют в контейнере."""
        names = rm.register_names()
        for expected in ["draw", "camera", "processing", "visual", "conveyor"]:
            assert expected in names, f"Регистр '{expected}' не найден"

    def test_register_accessible_as_attribute(self, rm):
        """Регистры доступны как атрибуты контейнера."""
        assert rm.draw is not None
        assert rm.camera is not None

    def test_field_is_plain_value(self, rm):
        """Поля возвращают plain-значение, а не объект-обёртку."""
        assert isinstance(rm.draw.dp, float)
        assert rm.draw.dp == 1.4

    def test_model_dump_is_flat(self, rm):
        """model_dump() возвращает плоский словарь значений (не вложенные объекты)."""
        d = rm.draw.model_dump()
        assert isinstance(d["dp"], float)
        assert isinstance(d["minDist"], float)

    def test_get_field_metadata_returns_dict(self, rm):
        """get_field_metadata возвращает словарь с нужными ключами."""
        meta = rm.get_field_metadata("draw", "dp")
        assert isinstance(meta, dict)
        assert meta.get("min") == 0.1
        assert meta.get("max") == 20.0
        assert "description" in meta

    def test_get_field_metadata_for_field_without_field_meta(self, rm):
        """Для поля без FieldMeta возвращается пустой dict."""
        meta = rm.get_field_metadata("post_processing", "regions")
        assert isinstance(meta, dict)

    def test_validate_field_valid_value(self, rm):
        """Валидное значение проходит проверку."""
        ok, err = rm.validate_field("draw", "dp", 2.0)
        assert ok is True
        assert err is None

    def test_validate_field_out_of_range(self, rm):
        """Значение за пределами min/max не проходит валидацию."""
        ok, err = rm.validate_field("draw", "dp", 999.0)
        assert ok is False
        assert err is not None

    def test_model_dump_all_structure(self, rm):
        """model_dump_all() возвращает словарь {имя_регистра: dict}."""
        data = rm.model_dump_all()
        assert "draw" in data
        assert "camera" in data
        assert isinstance(data["draw"], dict)
        assert "dp" in data["draw"]

    def test_to_json_and_from_json_roundtrip(self, rm):
        """Сериализация и десериализация через JSON сохраняет значения."""
        rm.draw.update_field("dp", 3.0)
        json_str = rm.to_json()
        data = json.loads(json_str)
        assert data["draw"]["dp"] == 3.0

        rm2 = RegistersManager()
        rm2.from_json(json_str)
        assert rm2.draw.dp == 3.0

    def test_reset_all(self, rm):
        """reset_all() возвращает все значения к дефолтам."""
        rm.draw.update_field("dp", 5.0)
        rm.reset_all()
        assert rm.draw.dp == 1.4


# =============================================================================
# Тесты DrawRegisters (RegisterBase)
# =============================================================================

class TestDrawRegisters:

    def test_default_values(self):
        """Дефолтные значения соответствуют ожидаемым."""
        r = DrawRegisters()
        assert r.dp == 1.4
        assert r.minDist == 50.0
        assert r.draw is True

    def test_get_field_meta_class_method(self):
        """get_field_meta() работает на уровне класса."""
        meta = DrawRegisters.get_field_meta("dp")
        assert meta is not None
        assert meta.min == 0.1
        assert meta.max == 20.0
        assert meta.transfer_k == 0.1
        assert meta.round_k == 1

    def test_get_field_meta_returns_none_for_plain_field(self):
        """Поле без FieldMeta возвращает None."""
        meta = DrawRegisters.get_field_meta("draw")
        assert meta is None

    def test_update_field_valid(self):
        """update_field() обновляет значение при корректном вводе."""
        r = DrawRegisters()
        ok, err = r.update_field("dp", 2.0)
        assert ok is True
        assert r.dp == 2.0

    def test_update_field_out_of_range(self):
        """update_field() отклоняет значение за диапазоном."""
        r = DrawRegisters()
        ok, err = r.update_field("dp", 999.0)
        assert ok is False
        assert err is not None
        assert r.dp == 1.4  # значение не изменилось

    def test_validate_assignment_type_error(self):
        """validate_assignment=True ловит неверный тип при прямом setattr."""
        r = DrawRegisters()
        with pytest.raises(Exception):
            r.dp = "not_a_float"

    def test_model_dump_is_flat(self):
        """model_dump() возвращает плоский dict значений."""
        r = DrawRegisters()
        d = r.model_dump()
        assert d == {
            "draw": True,
            "dp": 1.4,
            "minDist": 50.0,
            "param1": 100.0,
            "param2": 30.0,
            "minRadius": 0.0,
            "maxRadius": 0.0,
        }

    def test_values_dict_equals_model_dump(self):
        """values_dict() эквивалентен model_dump()."""
        r = DrawRegisters()
        assert r.values_dict() == r.model_dump()

    def test_get_routing_channels(self):
        """get_routing_channels() возвращает все каналы маршрутизации."""
        channels = DrawRegisters().get_routing_channels()
        assert "control_draw" in channels

    def test_get_fields_for_channel(self):
        """get_fields_for_channel() возвращает поля для канала."""
        r = DrawRegisters()
        fields = r.get_fields_for_channel("control_draw")
        assert "dp" in fields
        assert "minDist" in fields

    def test_constraint_validation_on_init(self):
        """@model_validator ловит нарушение min/max при создании экземпляра."""
        with pytest.raises(ValueError, match="меньше минимального"):
            DrawRegisters(dp=0.0)

    def test_get_visible_fields(self):
        """get_visible_fields() возвращает все незапрятанные поля."""
        r = DrawRegisters()
        fields = r.get_visible_fields(access_level=0)
        assert "dp" in fields
        assert "draw" in fields


# =============================================================================
# Тесты FileStorage + save/load
# =============================================================================

class TestFileStorage:

    def test_save_and_load(self, rm, tmp_path):
        """Сохранение и загрузка через FileStorage сохраняют значения."""
        from multiprocess_framework.refactored.modules.data_schema_module import FileStorage

        storage = FileStorage(tmp_path / "registers")
        rm.draw.update_field("dp", 7.7)
        rm.save(storage, "test_container")

        rm2 = RegistersManager()
        loaded = rm2.load(storage, "test_container")
        assert loaded is True
        assert rm2.draw.dp == 7.7

    def test_load_missing_returns_false(self, tmp_path):
        """Загрузка несуществующего контейнера возвращает False."""
        from multiprocess_framework.refactored.modules.data_schema_module import FileStorage

        rm = RegistersManager()
        storage = FileStorage(tmp_path / "registers")
        result = rm.load(storage, "nonexistent")
        assert result is False


# =============================================================================
# Тесты дата-моделей
# =============================================================================

class TestDataModels:

    def test_camera_data_defaults(self):
        """CameraData создаётся с дефолтными значениями."""
        cam = CameraData()
        assert cam.name == "unknown"
        assert cam.regions == {}

    def test_region_data_defaults(self):
        """RegionData создаётся с дефолтными значениями."""
        reg = RegionData()
        assert reg.x1 == 0
        assert reg.enabled is True
        assert reg.chains == []

    def test_camera_data_with_regions(self):
        """CameraData корректно хранит вложенные RegionData."""
        cam = CameraData(
            name="cam_01",
            regions={"roi_1": RegionData(x1=10, y1=20, x2=100, y2=200)},
        )
        assert cam.regions["roi_1"].x1 == 10
        assert cam.model_dump()["regions"]["roi_1"]["x1"] == 10
