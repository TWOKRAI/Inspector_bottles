"""Hazard-тесты автора для `ObjectSpawner.set_factory()` (Task 1.2a, план line-sim-layer-editor).

Что может сломаться в ЭТОМ механизме, как он построен:
- форс-брак, взведённый на старой фабрике и ещё не выпущенный, теряется при подмене
  (флаг живёт в фабрике, а не в спавнере) — нажатие оператора пропадает молча;
- перенос флага «на всякий случай» взводит брак на новой фабрике, когда его не просили;
- подмена трогает уже активные объекты или расписание спавна (нумерация id).
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import yaml

from Services.dataset_gen.core.catalog import imwrite_unicode
from Services.line_sim import ObjectFactory, ObjectSpawner, ScenePreset


def _make_factory(tmp_path: Path, name: str) -> ObjectFactory:
    root = tmp_path / name
    class_dir = root / "catalog" / "only_class"
    class_dir.mkdir(parents=True)
    sprite = np.zeros((16, 16, 4), dtype=np.uint8)
    sprite[:, :, :3] = 128
    sprite[:, :, 3] = 255
    imwrite_unicode(class_dir / "sprite.png", cv2.cvtColor(sprite, cv2.COLOR_RGBA2BGRA))
    preset_path = root / "preset.yaml"
    preset_path.write_text(
        yaml.safe_dump({"catalog_dir": "catalog", "layers": [], "defect_probability": 0.0}), encoding="utf-8"
    )
    return ObjectFactory(ScenePreset.from_yaml(preset_path))


def _spawn_one(spawner: ObjectSpawner, encoder: float, rng: np.random.Generator):
    before = {o.passport.object_id for o in spawner.active_objects()}
    spawner.tick(now_encoder=encoder, now_wall_s=0.0, rng=rng)
    new = [o for o in spawner.active_objects() if o.passport.object_id not in before]
    assert len(new) == 1, f"ожидался ровно один новый объект, получено {len(new)}"
    return new[0]


def test_pending_forced_defect_survives_set_factory(tmp_path):
    old = _make_factory(tmp_path, "old")
    new = _make_factory(tmp_path, "new")
    spawner = ObjectSpawner(old, spacing_mm=(10.0, 10.0), scene_length_mm=1000.0)
    rng = np.random.default_rng(7)

    spawner.force_defect_next()
    assert old.force_defect_pending is True
    spawner.set_factory(new)

    assert new.force_defect_pending is True, "невыпущенный форс-брак старой фабрики потерян при подмене"
    obj = _spawn_one(spawner, 0.0, rng)
    assert obj.passport.defect == "damaged"
    assert new.force_defect_pending is False, "флаг новой фабрики не погашен успешным make()"


def test_set_factory_does_not_invent_forced_defect(tmp_path):
    old = _make_factory(tmp_path, "old")
    new = _make_factory(tmp_path, "new")
    spawner = ObjectSpawner(old, spacing_mm=(10.0, 10.0), scene_length_mm=1000.0)
    spawner.set_factory(new)
    assert new.force_defect_pending is False
    obj = _spawn_one(spawner, 0.0, np.random.default_rng(7))
    assert obj.passport.defect is None


def test_set_factory_keeps_active_objects_and_id_numbering(tmp_path):
    old = _make_factory(tmp_path, "old")
    new = _make_factory(tmp_path, "new")
    spawner = ObjectSpawner(old, spacing_mm=(10.0, 10.0), scene_length_mm=1000.0)
    rng = np.random.default_rng(7)

    first = _spawn_one(spawner, 0.0, rng)
    spawner.set_factory(new)
    assert spawner.active_objects()[0] is first, "подмена фабрики тронула уже активный объект"

    # 10_000 отсчётов — заведомо больше шага 10 мм (_spawn_one сам проверит, что объект появился)
    second = _spawn_one(spawner, 10_000.0, rng)
    assert first.passport.object_id == "obj-1"
    assert second.passport.object_id == "obj-2", "нумерация id сброшена подменой фабрики"
