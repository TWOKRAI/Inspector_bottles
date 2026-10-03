"""Пресет сцены линии: `ScenePreset` живёт в `Services.layer_render.preset` (Task 2.4a), здесь — реэкспорт.

Определено ЗДЕСЬ — конфиг стенда, не механизм: `REPO_ROOT` (от расположения ЭТОГО файла,
`parents[3]`), `DEFAULT_DEFECT_PROBABILITY`, `resolve_repo_path`, `apply_defect_override`,
`load_scene_preset`. `REPO_ROOT` и `resolve_repo_path` обязаны оставаться в одном модуле:
тесты подменяют `REPO_ROOT` на этом модуле и ждут, что `resolve_repo_path` увидит подмену.
"""

from __future__ import annotations

import os  # noqa: F401  (строка-цель патча "Services.line_sim.core.preset.os.path.relpath" в test_hazards_1_0_paths.py)
from pathlib import Path

from Services.layer_render.preset import CLASS_SPRITE_SOURCE, ScenePreset

__all__ = [
    "CLASS_SPRITE_SOURCE",
    "DEFAULT_DEFECT_PROBABILITY",
    "REPO_ROOT",
    "ScenePreset",
    "apply_defect_override",
    "load_scene_preset",
    "resolve_repo_path",
]

#: Корень репозитория от расположения ЭТОГО файла (Services/line_sim/core/preset.py -> parents[3]).
#: Относительные пути конфига стенда (`preset_path`, `tile` слоя фона) резолвятся от него,
#: а не от CWD процесса (фикс ревью P5 плагина `scene_source`).
REPO_ROOT = Path(__file__).resolve().parents[3]

#: Вероятность брака каталожного пресета (не `.yaml`), если конфиг стенда её не задал.
DEFAULT_DEFECT_PROBABILITY = 0.0


def resolve_repo_path(path: str | None) -> str | None:
    """Относительный путь конфига — от `REPO_ROOT` (resolve); `None` и абсолютный — как есть."""
    if path is None or Path(path).is_absolute():
        return path
    return str((REPO_ROOT / path).resolve())


def apply_defect_override(preset: ScenePreset, override: float | None) -> ScenePreset:
    """Явный `defect_probability` конфига стенда перекрывает пресет; `None` — без изменений.
    Через `from_dict`, чтобы отработали валидаторы frozen-модели."""
    if override is None:
        return preset
    return ScenePreset.from_dict({**preset.to_dict(), "defect_probability": override})


def load_scene_preset(preset_path: str | None, defect_probability: float | None) -> ScenePreset:
    """Пресет сцены по УЖЕ резолвленному `preset_path` конфига стенда (см. `resolve_repo_path`).

    `.yaml`/`.yml` — файл пресета слоёв (`ScenePreset.from_yaml`, свои относительные пути — от
    каталога файла) + `apply_defect_override(defect_probability)`: `None` — значение файла.
    Иначе (нет пути, каталог классов, путь без расширения) — `ScenePreset(catalog_dir=...,
    defect_probability=...)` с `DEFAULT_DEFECT_PROBABILITY`, если `defect_probability is None`.
    """
    if preset_path is not None and preset_path.lower().endswith((".yaml", ".yml")):
        return apply_defect_override(ScenePreset.from_yaml(preset_path), defect_probability)
    probability = DEFAULT_DEFECT_PROBABILITY if defect_probability is None else float(defect_probability)
    return ScenePreset(catalog_dir=preset_path, defect_probability=probability)
