# -*- coding: utf-8 -*-
"""
Тесты для type aliases из core/field_types.py.

Проверяет каждый type alias на:
    - корректные min/max ограничения
    - единицы измерения (unit)
    - использование в SchemaBase (создание, валидация)
"""
import unittest
from typing import Annotated, get_args

from multiprocess_framework.modules.data_schema_module import (
    SchemaBase,
    FieldMeta,
    Percent,
    NormalizedFloat,
    Scale,
    Milliseconds,
    Seconds,
    Pixels,
    ImageScale,
    HsvHue,
    HsvChannel,
    NetworkPort,
    FpsLimit,
)


def _get_field_meta_from_alias(alias) -> FieldMeta:
    """Извлечь FieldMeta из Annotated type alias."""
    args = get_args(alias)
    for arg in args:
        if isinstance(arg, FieldMeta):
            return arg
    raise AssertionError(f"FieldMeta не найден в {alias}")


class TestPercentAlias(unittest.TestCase):
    """Тесты type alias Percent."""

    def setUp(self):
        self.meta = _get_field_meta_from_alias(Percent)

    def test_min_is_zero(self):
        self.assertEqual(self.meta.min, 0.0)

    def test_max_is_hundred(self):
        self.assertEqual(self.meta.max, 100.0)

    def test_unit_is_percent(self):
        self.assertEqual(self.meta.unit, "%")

    def test_round_k(self):
        self.assertEqual(self.meta.round_k, 1)

    def test_in_schema_valid(self):
        class S(SchemaBase):
            p: Percent = 50.0

        s = S()
        self.assertEqual(s.p, 50.0)

    def test_in_schema_below_min_raises(self):
        class S(SchemaBase):
            p: Percent = 50.0

        with self.assertRaises(ValueError):
            S(p=-1.0)

    def test_in_schema_above_max_raises(self):
        class S(SchemaBase):
            p: Percent = 50.0

        with self.assertRaises(ValueError):
            S(p=101.0)


class TestNormalizedFloatAlias(unittest.TestCase):
    """Тесты type alias NormalizedFloat."""

    def setUp(self):
        self.meta = _get_field_meta_from_alias(NormalizedFloat)

    def test_min_is_zero(self):
        self.assertEqual(self.meta.min, 0.0)

    def test_max_is_one(self):
        self.assertEqual(self.meta.max, 1.0)

    def test_round_k(self):
        self.assertEqual(self.meta.round_k, 3)

    def test_in_schema_valid(self):
        class S(SchemaBase):
            v: NormalizedFloat = 0.5

        s = S()
        self.assertEqual(s.v, 0.5)

    def test_in_schema_out_of_range_raises(self):
        class S(SchemaBase):
            v: NormalizedFloat = 0.5

        with self.assertRaises(ValueError):
            S(v=1.5)


class TestScaleAlias(unittest.TestCase):
    """Тесты type alias Scale."""

    def setUp(self):
        self.meta = _get_field_meta_from_alias(Scale)

    def test_min_positive(self):
        self.assertGreater(self.meta.min, 0.0)

    def test_max_is_hundred(self):
        self.assertEqual(self.meta.max, 100.0)

    def test_round_k(self):
        self.assertEqual(self.meta.round_k, 2)

    def test_in_schema_valid(self):
        class S(SchemaBase):
            s: Scale = 1.0

        s = S()
        self.assertEqual(s.s, 1.0)


class TestMillisecondsAlias(unittest.TestCase):
    """Тесты type alias Milliseconds."""

    def setUp(self):
        self.meta = _get_field_meta_from_alias(Milliseconds)

    def test_min_is_zero(self):
        self.assertEqual(self.meta.min, 0.0)

    def test_max_is_none(self):
        self.assertIsNone(self.meta.max)

    def test_unit(self):
        self.assertIn("мс", self.meta.unit)

    def test_in_schema_valid(self):
        class S(SchemaBase):
            t: Milliseconds = 100.0

        s = S()
        self.assertEqual(s.t, 100.0)

    def test_negative_raises(self):
        class S(SchemaBase):
            t: Milliseconds = 100.0

        with self.assertRaises(ValueError):
            S(t=-1.0)


class TestSecondsAlias(unittest.TestCase):
    """Тесты type alias Seconds."""

    def setUp(self):
        self.meta = _get_field_meta_from_alias(Seconds)

    def test_min_is_zero(self):
        self.assertEqual(self.meta.min, 0.0)

    def test_max_is_none(self):
        self.assertIsNone(self.meta.max)

    def test_unit(self):
        self.assertIn("с", self.meta.unit)

    def test_in_schema_valid(self):
        class S(SchemaBase):
            t: Seconds = 5.0

        s = S()
        self.assertEqual(s.t, 5.0)


class TestPixelsAlias(unittest.TestCase):
    """Тесты type alias Pixels."""

    def setUp(self):
        self.meta = _get_field_meta_from_alias(Pixels)

    def test_min_is_zero(self):
        self.assertEqual(self.meta.min, 0)

    def test_max_is_large(self):
        self.assertGreater(self.meta.max, 0)

    def test_unit(self):
        self.assertIn("px", self.meta.unit)

    def test_in_schema_valid(self):
        class S(SchemaBase):
            w: Pixels = 640

        s = S()
        self.assertEqual(s.w, 640)

    def test_negative_raises(self):
        class S(SchemaBase):
            w: Pixels = 640

        with self.assertRaises(ValueError):
            S(w=-10)


class TestImageScaleAlias(unittest.TestCase):
    """Тесты type alias ImageScale."""

    def setUp(self):
        self.meta = _get_field_meta_from_alias(ImageScale)

    def test_min_positive(self):
        self.assertGreater(self.meta.min, 0.0)

    def test_max_is_reasonable(self):
        self.assertGreater(self.meta.max, 1.0)

    def test_transfer_k(self):
        self.assertIsNotNone(self.meta.transfer_k)
        self.assertGreater(self.meta.transfer_k, 1.0)

    def test_in_schema_valid(self):
        class S(SchemaBase):
            sc: ImageScale = 1.0

        s = S()
        self.assertEqual(s.sc, 1.0)


class TestHsvHueAlias(unittest.TestCase):
    """Тесты type alias HsvHue."""

    def setUp(self):
        self.meta = _get_field_meta_from_alias(HsvHue)

    def test_min_is_zero(self):
        self.assertEqual(self.meta.min, 0)

    def test_max_is_179(self):
        self.assertEqual(self.meta.max, 179)

    def test_unit_degrees(self):
        self.assertIn("°", self.meta.unit)

    def test_in_schema_valid(self):
        class S(SchemaBase):
            h: HsvHue = 90

        s = S()
        self.assertEqual(s.h, 90)

    def test_above_max_raises(self):
        class S(SchemaBase):
            h: HsvHue = 90

        with self.assertRaises(ValueError):
            S(h=180)


class TestHsvChannelAlias(unittest.TestCase):
    """Тесты type alias HsvChannel."""

    def setUp(self):
        self.meta = _get_field_meta_from_alias(HsvChannel)

    def test_min_is_zero(self):
        self.assertEqual(self.meta.min, 0)

    def test_max_is_255(self):
        self.assertEqual(self.meta.max, 255)

    def test_in_schema_valid(self):
        class S(SchemaBase):
            s: HsvChannel = 128

        s = S()
        self.assertEqual(s.s, 128)

    def test_above_max_raises(self):
        class S(SchemaBase):
            s: HsvChannel = 128

        with self.assertRaises(ValueError):
            S(s=256)


class TestNetworkPortAlias(unittest.TestCase):
    """Тесты type alias NetworkPort."""

    def setUp(self):
        self.meta = _get_field_meta_from_alias(NetworkPort)

    def test_min_is_one(self):
        self.assertEqual(self.meta.min, 1)

    def test_max_is_65535(self):
        self.assertEqual(self.meta.max, 65535)

    def test_in_schema_valid(self):
        class S(SchemaBase):
            port: NetworkPort = 8080

        s = S()
        self.assertEqual(s.port, 8080)

    def test_port_zero_raises(self):
        class S(SchemaBase):
            port: NetworkPort = 8080

        with self.assertRaises(ValueError):
            S(port=0)

    def test_port_above_max_raises(self):
        class S(SchemaBase):
            port: NetworkPort = 8080

        with self.assertRaises(ValueError):
            S(port=65536)


class TestFpsLimitAlias(unittest.TestCase):
    """Тесты type alias FpsLimit."""

    def setUp(self):
        self.meta = _get_field_meta_from_alias(FpsLimit)

    def test_min_is_zero(self):
        self.assertEqual(self.meta.min, 0)

    def test_max_is_reasonable(self):
        self.assertGreater(self.meta.max, 0)

    def test_unit(self):
        self.assertIsNotNone(self.meta.unit)

    def test_in_schema_valid(self):
        class S(SchemaBase):
            fps: FpsLimit = 30

        s = S()
        self.assertEqual(s.fps, 30)

    def test_negative_raises(self):
        class S(SchemaBase):
            fps: FpsLimit = 30

        with self.assertRaises(ValueError):
            S(fps=-1)


class TestTypeAliasesInCombination(unittest.TestCase):
    """Тест использования нескольких type aliases в одной схеме."""

    def test_combined_schema(self):
        class ProcessingConfig(SchemaBase):
            hue_low: HsvHue = 0
            hue_high: HsvHue = 179
            sat_low: HsvChannel = 0
            sat_high: HsvChannel = 255
            scale: Percent = 50.0
            timeout: Milliseconds = 100.0
            port: NetworkPort = 8080

        cfg = ProcessingConfig()
        self.assertEqual(cfg.hue_low, 0)
        self.assertEqual(cfg.hue_high, 179)
        self.assertEqual(cfg.sat_high, 255)
        self.assertEqual(cfg.scale, 50.0)
        self.assertEqual(cfg.port, 8080)

    def test_combined_schema_validation(self):
        class ProcessingConfig(SchemaBase):
            hue_low: HsvHue = 0
            hue_high: HsvHue = 179
            scale: Percent = 50.0

        with self.assertRaises(ValueError):
            ProcessingConfig(hue_high=200)  # > 179

        with self.assertRaises(ValueError):
            ProcessingConfig(scale=150.0)  # > 100


if __name__ == "__main__":
    unittest.main()
