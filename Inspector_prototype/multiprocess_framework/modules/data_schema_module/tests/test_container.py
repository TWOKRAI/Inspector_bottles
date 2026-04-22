# -*- coding: utf-8 -*-
"""
Тесты для RegistersContainer (container/registers_container.py).

Покрывает:
    - Создание контейнера
    - Доступ: __getattr__, __getitem__, __contains__, __len__, __iter__
    - Единственный источник правды (_registers)
    - model_dump_all / model_validate_all
    - snapshot / diff
    - to_dict / from_dict / to_json / from_json / to_yaml / from_yaml
    - save / load через FileStorage
    - Пустой контейнер
    - Конфликты имён (нет дублирования в __dict__)
"""
import unittest
from typing import Annotated

from data_schema_module import (
    RegistersContainer,
    SchemaBase,
    FieldMeta,
    FieldRouting,
    FileStorage,
)


# =============================================================================
# Тестовые схемы
# =============================================================================

class DrawRegisters(SchemaBase):
    dp: Annotated[float, FieldMeta("Разрешение", min=0.1, max=20.0)] = 1.4
    scale: Annotated[float, FieldMeta("Масштаб", min=0.1, max=4.0)] = 1.0


class CameraRegisters(SchemaBase):
    exposure: Annotated[int, FieldMeta("Экспозиция", min=0, max=10000)] = 500
    gain: Annotated[float, FieldMeta("Усиление", min=0.0, max=10.0)] = 1.0
    active: bool = True


_CTRL = FieldRouting(channel="ctrl")


class ProcessingRegisters(SchemaBase):
    threshold: Annotated[int, FieldMeta("Порог", min=0, max=255, routing=_CTRL)] = 128
    blur: Annotated[int, FieldMeta("Размытие", min=0, max=50)] = 3


def _make_container() -> RegistersContainer:
    return RegistersContainer({
        "draw": DrawRegisters,
        "camera": CameraRegisters,
        "processing": ProcessingRegisters,
    })


# =============================================================================
# Тесты создания
# =============================================================================

class TestRegistersContainerCreation(unittest.TestCase):
    """Тесты создания RegistersContainer."""

    def test_create_with_map(self):
        c = _make_container()
        self.assertIsNotNone(c)

    def test_empty_container(self):
        c = RegistersContainer({})
        self.assertEqual(len(c), 0)

    def test_single_register(self):
        c = RegistersContainer({"draw": DrawRegisters})
        self.assertEqual(len(c), 1)

    def test_registers_initialized_with_defaults(self):
        c = _make_container()
        self.assertEqual(c.draw.dp, 1.4)
        self.assertEqual(c.camera.exposure, 500)
        self.assertEqual(c.processing.threshold, 128)


# =============================================================================
# Тесты доступа
# =============================================================================

class TestRegistersContainerAccess(unittest.TestCase):
    """Тесты различных способов доступа к регистрам."""

    def setUp(self):
        self.c = _make_container()

    def test_getattr_access(self):
        draw = self.c.draw
        self.assertIsInstance(draw, DrawRegisters)

    def test_getitem_access(self):
        camera = self.c["camera"]
        self.assertIsInstance(camera, CameraRegisters)

    def test_getattr_equals_getitem(self):
        self.assertIs(self.c.draw, self.c["draw"])

    def test_contains_existing(self):
        self.assertIn("draw", self.c)
        self.assertIn("camera", self.c)

    def test_contains_nonexistent(self):
        self.assertNotIn("nonexistent", self.c)

    def test_len(self):
        self.assertEqual(len(self.c), 3)

    def test_iter(self):
        names = [name for name, _ in self.c]
        self.assertIn("draw", names)
        self.assertIn("camera", names)
        self.assertIn("processing", names)
        self.assertEqual(len(names), 3)

    def test_getattr_unknown_raises_attribute_error(self):
        with self.assertRaises(AttributeError) as ctx:
            _ = self.c.nonexistent
        self.assertIn("nonexistent", str(ctx.exception))

    def test_getitem_unknown_raises_key_error(self):
        with self.assertRaises(KeyError):
            _ = self.c["nonexistent"]

    def test_repr_contains_register_names(self):
        r = repr(self.c)
        self.assertIn("RegistersContainer", r)
        self.assertIn("draw", r)


# =============================================================================
# Тесты единственного источника правды
# =============================================================================

class TestRegistersContainerSingleSource(unittest.TestCase):
    """Тесты что _registers — единственный источник правды."""

    def setUp(self):
        self.c = _make_container()

    def test_no_register_names_in_dict(self):
        """Имена регистров не должны быть в __dict__ контейнера."""
        self.assertNotIn("draw", self.c.__dict__)
        self.assertNotIn("camera", self.c.__dict__)

    def test_model_validate_all_updates_instance(self):
        old_draw = self.c._registers["draw"]
        self.c.model_validate_all({
            "draw": {"dp": 2.0, "scale": 1.5},
        })
        new_draw = self.c._registers["draw"]
        self.assertIsNot(old_draw, new_draw)
        self.assertEqual(self.c.draw.dp, 2.0)

    def test_getattr_reflects_updated_register(self):
        self.c.model_validate_all({
            "camera": {"exposure": 1000, "gain": 2.0, "active": False},
        })
        self.assertEqual(self.c.camera.exposure, 1000)
        self.assertEqual(self.c.camera.gain, 2.0)
        self.assertFalse(self.c.camera.active)


# =============================================================================
# Тесты model_dump_all
# =============================================================================

class TestRegistersContainerDumpAll(unittest.TestCase):
    """Тесты model_dump_all."""

    def setUp(self):
        self.c = _make_container()

    def test_model_dump_all_returns_dict(self):
        d = self.c.model_dump_all()
        self.assertIsInstance(d, dict)

    def test_model_dump_all_contains_all_registers(self):
        d = self.c.model_dump_all()
        self.assertIn("draw", d)
        self.assertIn("camera", d)
        self.assertIn("processing", d)

    def test_model_dump_all_values_are_dicts(self):
        d = self.c.model_dump_all()
        self.assertIsInstance(d["draw"], dict)
        self.assertIsInstance(d["camera"], dict)

    def test_model_dump_all_default_values(self):
        d = self.c.model_dump_all()
        self.assertEqual(d["draw"]["dp"], 1.4)
        self.assertEqual(d["camera"]["exposure"], 500)


# =============================================================================
# Тесты snapshot и diff
# =============================================================================

class TestRegistersContainerSnapshotDiff(unittest.TestCase):
    """Тесты snapshot() и diff()."""

    def setUp(self):
        self.c = _make_container()

    def test_snapshot_equals_to_dict(self):
        self.assertEqual(self.c.snapshot(), self.c.to_dict())

    def test_diff_empty_when_no_changes(self):
        snap = self.c.snapshot()
        diff = self.c.diff(snap)
        self.assertEqual(diff, {})

    def test_diff_returns_changed_fields(self):
        snap = self.c.snapshot()
        self.c.draw.update_field("dp", 2.5)
        diff = self.c.diff(snap)
        self.assertIn("draw", diff)
        self.assertEqual(diff["draw"]["dp"], 2.5)

    def test_diff_excludes_unchanged_registers(self):
        snap = self.c.snapshot()
        self.c.draw.update_field("dp", 2.5)
        diff = self.c.diff(snap)
        self.assertNotIn("camera", diff)
        self.assertNotIn("processing", diff)

    def test_diff_excludes_unchanged_fields_in_register(self):
        snap = self.c.snapshot()
        self.c.draw.update_field("dp", 2.5)
        diff = self.c.diff(snap)
        self.assertIn("dp", diff["draw"])
        self.assertNotIn("scale", diff.get("draw", {}))

    def test_diff_multiple_registers_changed(self):
        snap = self.c.snapshot()
        self.c.draw.update_field("dp", 3.0)
        self.c.camera.update_field("exposure", 1000)
        diff = self.c.diff(snap)
        self.assertIn("draw", diff)
        self.assertIn("camera", diff)

    def test_snapshot_is_deep_copy(self):
        snap = self.c.snapshot()
        self.c.draw.update_field("dp", 5.0)
        # Снапшот не должен измениться
        self.assertEqual(snap["draw"]["dp"], 1.4)


# =============================================================================
# Тесты сериализации (to_dict / from_dict / to_json / from_json)
# =============================================================================

class TestRegistersContainerSerialization(unittest.TestCase):
    """Тесты сериализации контейнера."""

    def setUp(self):
        self.c = _make_container()

    def test_to_dict(self):
        d = self.c.to_dict()
        self.assertIsInstance(d, dict)
        self.assertIn("draw", d)

    def test_from_dict(self):
        data = {
            "draw": {"dp": 3.0, "scale": 2.0},
            "camera": {"exposure": 800, "gain": 1.5, "active": True},
            "processing": {"threshold": 100, "blur": 5},
        }
        self.c.from_dict(data)
        self.assertEqual(self.c.draw.dp, 3.0)
        self.assertEqual(self.c.camera.exposure, 800)

    def test_to_json(self):
        import json
        js = self.c.to_json()
        self.assertIsInstance(js, str)
        parsed = json.loads(js)
        self.assertIn("draw", parsed)

    def test_from_json(self):
        import json
        data = {"draw": {"dp": 4.0, "scale": 1.0}}
        js = json.dumps(data)
        self.c.from_json(js)
        self.assertEqual(self.c.draw.dp, 4.0)

    def test_json_round_trip(self):
        self.c.draw.update_field("dp", 2.8)
        js = self.c.to_json()
        c2 = RegistersContainer({
            "draw": DrawRegisters,
            "camera": CameraRegisters,
            "processing": ProcessingRegisters,
        })
        c2.from_json(js)
        self.assertEqual(c2.draw.dp, 2.8)


# =============================================================================
# Тесты персистентности (save / load)
# =============================================================================

class TestRegistersContainerPersistence(unittest.TestCase):
    """Тесты сохранения и загрузки через FileStorage."""

    def setUp(self):
        import tempfile
        from pathlib import Path
        self.temp_dir = Path(tempfile.mkdtemp())
        self.storage = FileStorage(str(self.temp_dir))
        self.c = _make_container()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_save_and_load(self):
        self.c.draw.update_field("dp", 3.5)
        self.c.save(self.storage, "test_registers")

        c2 = RegistersContainer({
            "draw": DrawRegisters,
            "camera": CameraRegisters,
            "processing": ProcessingRegisters,
        })
        c2.load(self.storage, "test_registers")
        self.assertEqual(c2.draw.dp, 3.5)

    def test_save_creates_file(self):
        self.c.save(self.storage, "my_registers")
        self.assertTrue(self.storage.exists("my_registers"))

    def test_load_nonexistent_returns_false(self):
        result = self.c.load(self.storage, "nonexistent_key")
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
