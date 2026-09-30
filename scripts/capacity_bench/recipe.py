"""Рендер рецепта стенда: закреплённая база `recipes/stand.yaml` + разрешение камеры и fps."""

from __future__ import annotations

from pathlib import Path

import yaml

_BASE = Path(__file__).parent / "recipes" / "stand.yaml"
_RESOLUTION = {480: (640, 480), 1080: (1920, 1080)}
_CAMERA_SUFFIX = "CameraServicePlugin"


def _camera(recipe: dict) -> tuple[dict, dict]:
    """(процесс, плагин) первой камеры рецепта; нет камеры -> RuntimeError."""
    for proc in recipe.get("processes") or []:
        for plugin in proc.get("plugins") or []:
            if str(plugin.get("plugin_class", "")).endswith(_CAMERA_SUFFIX):
                return proc, plugin
    raise RuntimeError(f"в {_BASE} нет плагина *{_CAMERA_SUFFIX}")


def _require(container: dict, key: str) -> None:
    # Не setdefault: если база потеряла поле, бенч не должен молча его выдумать.
    if key not in container:
        raise RuntimeError(f"в базе {_BASE} у камеры нет ключа {key!r}")


def render_recipe(height: int, fps: int, out_dir: Path) -> Path:
    if height not in _RESOLUTION:
        raise ValueError(f"высота {height} не поддерживается: {sorted(_RESOLUTION)}")
    width = _RESOLUTION[height][0]
    recipe = yaml.safe_load(_BASE.read_text(encoding="utf-8"))
    proc, plugin = _camera(recipe)
    for container, key in ((plugin, "resolution_width"), (plugin, "resolution_height"), (proc, "source_target_fps")):
        _require(container, key)
    plugin["resolution_width"], plugin["resolution_height"] = width, height
    proc["source_target_fps"] = fps

    out = Path(out_dir) / f"stand_{height}_{fps}.yaml"
    out.write_text(yaml.safe_dump(recipe, allow_unicode=True, sort_keys=False), encoding="utf-8")

    back_proc, back_plugin = _camera(yaml.safe_load(out.read_text(encoding="utf-8")))
    got = (
        back_plugin.get("resolution_width"),
        back_plugin.get("resolution_height"),
        back_proc.get("source_target_fps"),
    )
    if got != (width, height, fps):
        raise RuntimeError(f"{out}: после записи камера {got}, ожидалось {(width, height, fps)}")
    return out
