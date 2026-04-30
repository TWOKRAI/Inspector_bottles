# -*- coding: utf-8 -*-
"""
Интеграционные тесты data_schema_module.

Проверяет полный flow:
    Schema → Container → Serialization → Registry

Сценарии:
    1. Полный жизненный цикл: создание схем → контейнер → сериализация → восстановление
    2. Registry + Schema: регистрация, создание экземпляров, валидация
    3. Container + FileStorage: сохранение и загрузка
    4. Dict at Boundary: config_to_dict → process()
    5. Обратная совместимость: RegisterBase, RegisterMixin
    6. Routing + Container: маршрутизация через контейнер
"""
import json
import unittest
from pathlib import Path
from typing import Annotated, Tuple

from multiprocess_framework.modules.data_schema_module import (
    # Ядро
    SchemaBase,
    RegisterBase,
    SchemaMixin,
    RegisterMixin,
    FieldMeta,
    FieldRouting,
    # Type aliases
    Percent,
    HsvHue,
    HsvChannel,
    Pixels,
    NetworkPort,
    # Registry
    SchemaRegistry,
    register_schema,
    get_default_registry,
    # Serialization
    DataConverter,
    FormatType,
    registers_to_dict,
    registers_from_dict,
    registers_to_json,
    registers_from_json,
    registers_to_flat_dict,
    # Container
    RegistersContainer,
    config_to_dict,
    build_process_with_workers,
    process,
    FileStorage,
    # Validators
    DataValidator,
    # Helpers
    merge_with_defaults,
)


# =============================================================================
# Тестовые схемы
# =============================================================================

class CameraConfig(SchemaBase):
    """Конфигурация камеры."""
    exposure: Annotated[int, FieldMeta("Экспозиция", min=0, max=10000)] = 500
    gain: Annotated[float, FieldMeta("Усиление", min=0.0, max=10.0)] = 1.0
    fps: Annotated[int, FieldMeta("FPS", min=1, max=120)] = 30
    active: bool = True


_PROCESSING_CTRL = FieldRouting(channel="processing_ctrl")


class ProcessingConfig(SchemaBase):
    """Конфигурация обработки изображений."""
    hue_low: HsvHue = 0
    hue_high: HsvHue = 179
    sat_low: HsvChannel = 0
    sat_high: HsvChannel = 255
    threshold: Annotated[int, FieldMeta("Порог", min=0, max=255, routing=_PROCESSING_CTRL)] = 128
    scale: Percent = 50.0


class DisplayConfig(SchemaBase):
    """Конфигурация отображения."""
    width: Pixels = 1280
    height: Pixels = 720
    zoom: Annotated[float, FieldMeta("Масштаб", min=0.1, max=4.0)] = 1.0


class NetworkConfig(SchemaBase):
    """Сетевая конфигурация."""
    port: NetworkPort = 8080
    host: str = "localhost"
    timeout: Annotated[float, FieldMeta("Таймаут", min=0.1, max=60.0)] = 5.0


# =============================================================================
# 1. Полный жизненный цикл
# =============================================================================

class TestFullLifecycle(unittest.TestCase):
    """Полный жизненный цикл: Schema → Container → Serialization → Restore."""

    def setUp(self):
        self.container = RegistersContainer({
            "camera": CameraConfig,
            "processing": ProcessingConfig,
            "display": DisplayConfig,
        })

    def test_create_container_with_defaults(self):
        self.assertEqual(self.container.camera.exposure, 500)
        self.assertEqual(self.container.processing.threshold, 128)
        self.assertEqual(self.container.display.width, 1280)

    def test_update_and_verify(self):
        ok, err = self.container.camera.update_field("exposure", 1000)
        self.assertTrue(ok)
        self.assertEqual(self.container.camera.exposure, 1000)

    def test_snapshot_and_restore(self):
        self.container.camera.update_field("exposure", 2000)
        self.container.processing.update_field("threshold", 200)

        snap = self.container.snapshot()
        self.assertEqual(snap["camera"]["exposure"], 2000)
        self.assertEqual(snap["processing"]["threshold"], 200)

        # Восстановить из снапшота
        new_container = RegistersContainer({
            "camera": CameraConfig,
            "processing": ProcessingConfig,
            "display": DisplayConfig,
        })
        new_container.model_validate_all(snap)
        self.assertEqual(new_container.camera.exposure, 2000)
        self.assertEqual(new_container.processing.threshold, 200)

    def test_json_round_trip(self):
        self.container.camera.update_field("gain", 3.5)
        js = self.container.to_json()

        new_container = RegistersContainer({
            "camera": CameraConfig,
            "processing": ProcessingConfig,
            "display": DisplayConfig,
        })
        new_container.from_json(js)
        self.assertEqual(new_container.camera.gain, 3.5)

    def test_diff_after_changes(self):
        snap = self.container.snapshot()
        self.container.camera.update_field("fps", 60)
        self.container.display.update_field("zoom", 2.0)

        diff = self.container.diff(snap)
        self.assertIn("camera", diff)
        self.assertIn("display", diff)
        self.assertNotIn("processing", diff)
        self.assertEqual(diff["camera"]["fps"], 60)
        self.assertEqual(diff["display"]["zoom"], 2.0)


# =============================================================================
# 2. Registry + Schema
# =============================================================================

class TestRegistryWithSchema(unittest.TestCase):
    """Тесты интеграции Registry со SchemaBase."""

    def setUp(self):
        self.registry = SchemaRegistry()
        self.registry.register("Camera", CameraConfig)
        self.registry.register("Processing", ProcessingConfig)

    def test_create_instance_from_registry(self):
        instance = self.registry.create_instance("Camera")
        self.assertIsInstance(instance, CameraConfig)
        self.assertEqual(instance.exposure, 500)

    def test_create_instance_with_data(self):
        instance = self.registry.create_instance("Camera", {"exposure": 800, "fps": 60})
        self.assertEqual(instance.exposure, 800)
        self.assertEqual(instance.fps, 60)

    def test_validate_valid_data(self):
        ok, instance, err = self.registry.validate("Camera", {
            "exposure": 1000,
            "gain": 2.0,
            "fps": 30,
            "active": True,
        })
        self.assertTrue(ok)
        self.assertIsNone(err)

    def test_validate_invalid_data_constraint_violation(self):
        ok, instance, err = self.registry.validate("Camera", {
            "exposure": 99999,  # > max 10000
        })
        self.assertFalse(ok)
        self.assertIsNotNone(err)

    def test_get_defaults(self):
        defaults = self.registry.get_defaults("Camera")
        self.assertEqual(defaults["exposure"], 500)
        self.assertEqual(defaults["gain"], 1.0)

    def test_decorator_with_isolated_registry(self):
        isolated = SchemaRegistry()

        @register_schema("NetworkCfg", registry=isolated)
        class NetworkCfg(SchemaBase):
            port: NetworkPort = 9090

        self.assertTrue(isolated.has_schema("NetworkCfg"))
        inst = isolated.create_instance("NetworkCfg")
        self.assertEqual(inst.port, 9090)


# =============================================================================
# 3. Container + FileStorage
# =============================================================================

class TestContainerWithFileStorage(unittest.TestCase):
    """Тесты сохранения и загрузки контейнера через FileStorage."""

    def setUp(self):
        import tempfile
        self.temp_dir = Path(tempfile.mkdtemp())
        self.storage = FileStorage(str(self.temp_dir))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_save_and_load_container(self):
        container = RegistersContainer({
            "camera": CameraConfig,
            "network": NetworkConfig,
        })
        container.camera.update_field("exposure", 3000)
        container.network.update_field("port", 9090)

        container.save(self.storage, "test_config")

        restored = RegistersContainer({
            "camera": CameraConfig,
            "network": NetworkConfig,
        })
        restored.load(self.storage, "test_config")

        self.assertEqual(restored.camera.exposure, 3000)
        self.assertEqual(restored.network.port, 9090)

    def test_multiple_saves_and_loads(self):
        container = RegistersContainer({"camera": CameraConfig})

        container.camera.update_field("fps", 60)
        container.save(self.storage, "config_v1")

        container.camera.update_field("fps", 90)
        container.save(self.storage, "config_v2")

        r1 = RegistersContainer({"camera": CameraConfig})
        r1.load(self.storage, "config_v1")
        self.assertEqual(r1.camera.fps, 60)

        r2 = RegistersContainer({"camera": CameraConfig})
        r2.load(self.storage, "config_v2")
        self.assertEqual(r2.camera.fps, 90)


# =============================================================================
# 4. Dict at Boundary: process()
# =============================================================================

class TestDictAtBoundary(unittest.TestCase):
    """Тесты паттерна Dict at Boundary."""

    def test_schema_config_with_build(self):
        class ProcessCfg(SchemaBase):
            timeout: Annotated[float, FieldMeta("Таймаут", min=0.0, max=60.0)] = 5.0
            workers: int = 4

            def build(self) -> Tuple[str, dict]:
                return ("main_process", {
                    "class": "app.MainProcess",
                    "config": self.model_dump(),
                })

        cfg = ProcessCfg(timeout=10.0, workers=8)
        name, d = config_to_dict(cfg)
        self.assertEqual(name, "main_process")
        self.assertEqual(d["config"]["timeout"], 10.0)
        self.assertEqual(d["config"]["workers"], 8)

    def test_process_with_workers(self):
        class ProcCfg:
            def build(self):
                return ("proc", {"class": "Proc"})

        class WorkCfg:
            def __init__(self, name):
                self.name = name

            def build(self):
                return (self.name, {"class": "Worker"})

        name, d = process(ProcCfg(), WorkCfg("w1"), WorkCfg("w2"))
        self.assertEqual(name, "proc")
        self.assertIn("workers", d)
        self.assertIn("w1", d["workers"])
        self.assertIn("w2", d["workers"])


# =============================================================================
# 5. Обратная совместимость
# =============================================================================

class TestBackwardCompatibility(unittest.TestCase):
    """Тесты обратной совместимости алиасов."""

    def test_register_base_is_schema_base(self):
        self.assertIs(RegisterBase, SchemaBase)

    def test_register_mixin_is_schema_mixin(self):
        self.assertIs(RegisterMixin, SchemaMixin)

    def test_register_base_creates_schema(self):
        class OldStyleSchema(RegisterBase):
            value: Annotated[float, FieldMeta("Значение", min=0.0, max=100.0)] = 50.0

        s = OldStyleSchema()
        self.assertEqual(s.value, 50.0)
        self.assertIsInstance(s, SchemaBase)

    def test_old_style_schema_works_in_container(self):
        class OldRegisters(RegisterBase):
            speed: Annotated[float, FieldMeta("Скорость", min=0.0, max=50.0)] = 10.0

        container = RegistersContainer({"old": OldRegisters})
        self.assertEqual(container.old.speed, 10.0)

    def test_schema_manager_alias(self):
        from multiprocess_framework.modules.data_schema_module import SchemaManager
        self.assertIs(SchemaManager, SchemaRegistry)


# =============================================================================
# 6. Routing + Container
# =============================================================================

class TestRoutingWithContainer(unittest.TestCase):
    """Тесты маршрутизации через контейнер."""

    def setUp(self):
        self.container = RegistersContainer({
            "processing": ProcessingConfig,
        })

    def test_get_routing_channels(self):
        channels = self.container.processing.get_routing_channels()
        self.assertIn("processing_ctrl", channels)

    def test_get_fields_for_channel(self):
        fields = self.container.processing.get_fields_for_channel("processing_ctrl")
        self.assertIn("threshold", fields)

    def test_update_routed_field(self):
        ok, err = self.container.processing.update_field("threshold", 200)
        self.assertTrue(ok)
        self.assertEqual(self.container.processing.threshold, 200)


# =============================================================================
# 7. DataValidator интеграция
# =============================================================================

class TestDataValidatorIntegration(unittest.TestCase):
    """Тесты DataValidator в связке со схемами."""

    def test_validate_camera_config(self):
        ok, instance, err = DataValidator.validate(
            {"exposure": 500, "gain": 1.0, "fps": 30, "active": True},
            CameraConfig,
        )
        self.assertTrue(ok)
        self.assertIsInstance(instance, CameraConfig)

    def test_validate_partial_camera_config(self):
        ok, instance, err = DataValidator.validate_partial(
            {"exposure": 1000},
            CameraConfig,
        )
        self.assertTrue(ok)
        self.assertEqual(instance.exposure, 1000)
        self.assertEqual(instance.gain, 1.0)  # дефолт

    def test_is_valid_with_schema(self):
        self.assertTrue(DataValidator.is_valid(
            {"exposure": 500, "gain": 1.0, "fps": 30, "active": True},
            CameraConfig,
        ))

    def test_is_not_valid_with_constraint_violation(self):
        self.assertFalse(DataValidator.is_valid(
            {"exposure": -100},  # < min
            CameraConfig,
        ))


# =============================================================================
# 8. merge_with_defaults
# =============================================================================

class TestMergeWithDefaults(unittest.TestCase):
    """Тесты merge_with_defaults."""

    def test_merge_partial_data(self):
        defaults = CameraConfig().model_dump()
        partial = {"exposure": 2000}
        merged = merge_with_defaults(partial, defaults)
        self.assertEqual(merged["exposure"], 2000)
        self.assertEqual(merged["gain"], 1.0)  # из defaults
        self.assertEqual(merged["fps"], 30)  # из defaults

    def test_merge_empty_data(self):
        defaults = CameraConfig().model_dump()
        merged = merge_with_defaults({}, defaults)
        self.assertEqual(merged, defaults)

    def test_merge_full_data(self):
        defaults = CameraConfig().model_dump()
        full = {"exposure": 100, "gain": 5.0, "fps": 60, "active": False}
        merged = merge_with_defaults(full, defaults)
        self.assertEqual(merged["exposure"], 100)
        self.assertFalse(merged["active"])


# =============================================================================
# 9. Полный сценарий: регистрация + контейнер + сериализация
# =============================================================================

class TestFullScenario(unittest.TestCase):
    """Полный сценарий использования модуля."""

    def test_complete_workflow(self):
        # 1. Создаём изолированный реестр
        registry = SchemaRegistry()

        # 2. Регистрируем схемы
        @register_schema("Camera", registry=registry)
        class Camera(SchemaBase):
            exposure: Annotated[int, FieldMeta("Экспозиция", min=0, max=10000)] = 500
            fps: int = 30

        @register_schema("Network", registry=registry)
        class Network(SchemaBase):
            port: NetworkPort = 8080
            host: str = "localhost"

        # 3. Проверяем реестр
        self.assertTrue(registry.has_schema("Camera"))
        self.assertTrue(registry.has_schema("Network"))

        # 4. Создаём контейнер
        container = RegistersContainer({
            "camera": Camera,
            "network": Network,
        })

        # 5. Изменяем значения
        container.camera.update_field("exposure", 1500)
        container.network.update_field("port", 9090)

        # 6. Сериализуем
        js = container.to_json()
        data = json.loads(js)
        self.assertEqual(data["camera"]["exposure"], 1500)
        self.assertEqual(data["network"]["port"], 9090)

        # 7. Восстанавливаем
        restored = RegistersContainer({"camera": Camera, "network": Network})
        restored.from_json(js)
        self.assertEqual(restored.camera.exposure, 1500)
        self.assertEqual(restored.network.port, 9090)

        # 8. Валидируем через реестр
        ok, instance, err = registry.validate("Camera", {"exposure": 2000, "fps": 60})
        self.assertTrue(ok)
        self.assertEqual(instance.exposure, 2000)


if __name__ == "__main__":
    unittest.main()
