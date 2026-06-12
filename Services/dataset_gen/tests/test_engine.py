"""Контракт DatasetEngine: пайплайн кадра, метки, симметрии, детерминизм."""

from __future__ import annotations

import numpy as np
import pytest

from Services.dataset_gen.core.engine import DatasetEngine
from Services.dataset_gen.interfaces import SampleGenerator


@pytest.fixture
def engine(base_config) -> DatasetEngine:
    return DatasetEngine(base_config)


class TestEngineBasics:
    def test_satisfies_sample_generator_protocol(self, engine):
        assert isinstance(engine, SampleGenerator)

    def test_classes_sorted_by_name(self, engine):
        assert engine.class_names == ["bar", "disk", "lshape"]
        assert engine.num_classes == 3

    def test_frame_shape_dtype_from_config(self, engine):
        frame, _ = engine.generate_sample()
        assert frame.shape == (96, 96, 3)
        assert frame.dtype == np.uint8


class TestSymmetryResolution:
    def test_auto_detected_map(self, engine):
        # given эталоны с известной симметрией → детектор обязан их распознать
        assert engine.symmetry_map == {"bar": "180", "disk": "full", "lshape": "none"}

    def test_manual_override_beats_detector(self, base_config):
        base_config.symmetry.overrides = {"disk": "none"}
        engine = DatasetEngine(base_config)
        assert engine.symmetry_map["disk"] == "none"

    def test_auto_detect_off_means_none(self, base_config):
        base_config.symmetry.auto_detect = False
        engine = DatasetEngine(base_config)
        assert set(engine.symmetry_map.values()) == {"none"}


class TestLabels:
    def test_label_coherent_for_asymmetric_class(self, engine):
        cls = engine.class_names.index("lshape")
        _, label = engine.generate_sample(cls)
        assert label.class_index == cls
        assert label.class_name == "lshape"
        assert 0.0 <= label.angle_deg < 360.0
        assert label.angle_valid is True
        assert label.angle_sin**2 + label.angle_cos**2 == pytest.approx(1.0)

    def test_full_symmetry_invalidates_angle(self, engine):
        cls = engine.class_names.index("disk")
        _, label = engine.generate_sample(cls)
        assert label.symmetry == "full"
        assert label.angle_valid is False
        assert (label.angle_sin, label.angle_cos) == (0.0, 0.0)

    def test_label_dict_has_training_contract_fields(self, engine):
        _, label = engine.generate_sample()
        d = label.to_dict()
        for key in (
            "class_index",
            "class_name",
            "angle_deg",
            "angle_sin",
            "angle_cos",
            "symmetry",
            "angle_valid",
        ):
            assert key in d


class TestDeterminism:
    def test_same_seed_same_frames(self, base_config):
        e1, e2 = DatasetEngine(base_config), DatasetEngine(base_config)
        f1, l1 = e1.generate_sample()
        f2, l2 = e2.generate_sample()
        assert (f1 == f2).all()
        assert l1 == l2

    def test_external_rng_overrides_internal(self, engine):
        f1, _ = engine.generate_sample(0, np.random.default_rng(99))
        f2, _ = engine.generate_sample(0, np.random.default_rng(99))
        assert (f1 == f2).all()


class TestRotationDisabled:
    def test_angle_zero_when_rotation_off(self, base_config):
        base_config.augment.rotation.enabled = False
        engine = DatasetEngine(base_config)
        _, label = engine.generate_sample(engine.class_names.index("lshape"))
        assert label.angle_deg == 0.0
