"""store.py — центральное хранилище калибровки камера↔робот.

Калибровка привязана к физической паре камера+робот, НЕ к рецепту (P8): хранится в
``config/calibration/<camera_id>.yaml``, рецепты ссылаются по ``camera_id``. Файл —
машинно-генерируемый артефакт (комментарии сохранять не нужно), поэтому пишем
обычным PyYAML с атомарной заменой (tmp + ``os.replace``), как
``Services/device_hub/registry/store.py``.

Слой Plugins НЕ импортирует ``multiprocess_prototype.*`` (граница архитектуры) —
поэтому YAML пишем напрямую, без ``recipes/yaml_io.py``.

Формат::

    camera_id: cam0
    robot_id: robot_main
    created_utc: "2026-06-13T..."
    transform: homography
    px_to_mm: [[...],[...],[...]]        # 3×3 гомография
    encoder: {e_capture: int, mm_per_count: float, belt_dir_mm: [dx, dy]}
    reproj_error_mm: {center: float, mean: float, max: float}
    points: [{px: [x,y], mm: [x,y], enc: int, role: corner_tl|...|center}, ...]
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import yaml

DEFAULT_BASE_DIR = "config/calibration"

_REQUIRED_TOP = ("camera_id", "robot_id", "transform", "px_to_mm", "encoder", "reproj_error_mm", "points")


def calibration_path(camera_id: str, base_dir: str | Path = DEFAULT_BASE_DIR) -> Path:
    """Путь к файлу калибровки для камеры. Raises ValueError при пустом camera_id."""
    safe = str(camera_id).strip()
    if not safe:
        raise ValueError("calibration_path: пустой camera_id")
    return Path(base_dir) / f"{safe}.yaml"


def validate_payload(payload: Any) -> list[str]:
    """Структурная проверка payload. Возвращает список проблем (пустой = ок).

    Проверяет наличие обязательных полей, размерность ``px_to_mm`` (3×3),
    структуру ``encoder``/``points``. Семантический гейт (reproj < порога) — на
    стороне плагина (порог — register-параметр), не здесь.
    """
    if not isinstance(payload, dict):
        return ["payload не является словарём"]
    problems: list[str] = []
    for key in _REQUIRED_TOP:
        if key not in payload:
            problems.append(f"отсутствует обязательное поле '{key}'")

    h = payload.get("px_to_mm")
    if not (isinstance(h, list) and len(h) == 3 and all(isinstance(row, list) and len(row) == 3 for row in h)):
        problems.append("px_to_mm должна быть матрицей 3×3 (list[list[float]])")

    enc = payload.get("encoder")
    if isinstance(enc, dict):
        for key in ("e_capture", "mm_per_count", "belt_dir_mm"):
            if key not in enc:
                problems.append(f"encoder.{key} отсутствует")
        belt = enc.get("belt_dir_mm")
        if not (isinstance(belt, list) and len(belt) == 2):
            problems.append("encoder.belt_dir_mm должен быть [dx, dy]")
    else:
        problems.append("encoder должен быть словарём")

    points = payload.get("points")
    if not (isinstance(points, list) and len(points) >= 1):
        problems.append("points должен быть непустым списком")
    return problems


def save_calibration(camera_id: str, payload: dict, base_dir: str | Path = DEFAULT_BASE_DIR) -> Path:
    """Атомарно записать калибровку. Raises ValueError при некорректном payload.

    Numpy-типы (H как ``np.ndarray``, скаляры) приводятся к стандартным Python ДО
    валидации — проверяется ровно то, что будет записано.
    """
    plain = _to_plain(payload)
    problems = validate_payload(plain)
    if problems:
        raise ValueError("save_calibration: некорректный payload: " + "; ".join(problems))

    path = calibration_path(camera_id, base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(plain, allow_unicode=True, sort_keys=False)

    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:  # no-health: best-effort подчистка tmp, исходная ошибка уходит через raise ниже
            pass
        raise
    return path


def load_calibration(camera_id: str, base_dir: str | Path = DEFAULT_BASE_DIR) -> dict | None:
    """Прочитать калибровку (для прод-рецепта). None, если файла нет или он пуст/битый."""
    path = calibration_path(camera_id, base_dir)
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return None
    data = yaml.safe_load(text)
    return data if isinstance(data, dict) else None


def _to_plain(obj: Any) -> Any:
    """Рекурсивно привести numpy-типы к стандартным Python (PyYAML их не умеет)."""
    import numpy as np  # локально: чтение калибровки не должно требовать numpy

    if isinstance(obj, dict):
        return {k: _to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_plain(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    return obj
