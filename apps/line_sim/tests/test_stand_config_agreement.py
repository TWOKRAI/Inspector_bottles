# -*- coding: utf-8 -*-
"""Согласованность настроек сим-стенда в ``apps/line_sim/pipeline.yaml``.

Одни и те же значения записаны в нескольких местах, и расхождение ничего не роняет:
превью слоёв молча показывает не тот пресет, что едет на ленте, а обучающие кропы
получают не тот фон. Тест читает только YAML; файлы ``data/`` (вне git) ему не нужны.

Относительные пути у двух описаний фона считаются от РАЗНЫХ баз, как в продукте:

- ``pipeline.yaml`` (``preset_path``, ``tile``) — от корня репозитория
  (``Services/line_sim/core/preset.py::resolve_repo_path``);
- ``train.background_layers[*].tile`` пресета — от каталога файла пресета
  (``ScenePreset.resolve_path``, ``base_dir`` ставит ``ScenePreset.from_yaml``).

Поэтому сравниваются не строки, а получившиеся абсолютные пути.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PIPELINE_YAML = _REPO_ROOT / "apps" / "line_sim" / "pipeline.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _plugin_config(process_name: str, plugin_name: str) -> dict[str, Any]:
    """Конфиг плагина из ``pipeline.yaml``; нет процесса/плагина (или их несколько) — падение."""
    processes = [p for p in _load_yaml(_PIPELINE_YAML)["processes"] if p["process_name"] == process_name]
    assert len(processes) == 1, f"pipeline.yaml: процесс {process_name!r} найден {len(processes)} раз, нужен 1"
    plugins = [p for p in processes[0]["plugins"] if p["plugin_name"] == plugin_name]
    assert len(plugins) == 1, (
        f"pipeline.yaml: плагин {plugin_name!r} в процессе {process_name!r} найден {len(plugins)} раз, нужен 1"
    )
    return plugins[0]


def _scene_source() -> dict[str, Any]:
    return _plugin_config("camera", "scene_source")


def _layer_preview() -> dict[str, Any]:
    return _plugin_config("layers", "layer_preview")


def _normalized_background(items: Any, base_dir: Path, where: str) -> list[tuple[str, Any]]:
    """Стек фона в сравнимой форме: ``(вид, значение)`` снизу вверх, путь тайла — абсолютный от ``base_dir``."""
    assert isinstance(items, list) and items, f"{where}: ожидался непустой список слоёв, получено {items!r}"
    layers: list[tuple[str, Any]] = []
    for item in items:
        assert len(item) == 1, f"{where}: у слоя ровно один ключ, получено {item!r}"
        ((kind, value),) = item.items()
        assert kind in ("solid", "tile"), f"{where}: неизвестный вид слоя {item!r}"
        # Абсолютный `value` оператор `/` оставляет как есть; resolve() не требует, чтобы файл был.
        layers.append((kind, (base_dir / value).resolve() if kind == "tile" else value))
    return layers


def test_preset_path_equal() -> None:
    """Превью слоёв читает тот же пресет, что и сцена."""
    scene = _scene_source()["preset_path"]
    preview = _layer_preview()["preset_path"]

    assert isinstance(scene, str) and scene, f"scene_source.preset_path пуст: {scene!r}"
    assert preview == scene, f"preset_path разошёлся: scene_source={scene!r}, layer_preview={preview!r}"


def test_defect_probability_equal() -> None:
    """Оба плагина задают ``defect_probability`` явно и одинаково (без ключа действует значение пресета)."""
    scene = _scene_source()
    preview = _layer_preview()

    for name, config in (("scene_source", scene), ("layer_preview", preview)):
        assert "defect_probability" in config, f"{name}: ключ defect_probability не задан"
        assert config["defect_probability"] is not None, f"{name}: defect_probability пуст"
    assert preview["defect_probability"] == scene["defect_probability"], (
        f"defect_probability разошёлся: scene_source={scene['defect_probability']!r}, "
        f"layer_preview={preview['defect_probability']!r}"
    )


def test_background_matches_preset_train() -> None:
    """Фон ленты стенда = фон обучения пресета: те же виды, порядок, цвета и файлы тайлов."""
    scene = _scene_source()
    preset_file = (_REPO_ROOT / scene["preset_path"]).resolve()
    train = _load_yaml(preset_file)["train"]

    stand = _normalized_background(scene["background_layers"], _REPO_ROOT, "scene_source.background_layers")
    trained = _normalized_background(
        train["background_layers"], preset_file.parent, f"{preset_file.name}: train.background_layers"
    )

    assert stand == trained, f"фон разошёлся:\n  стенд:    {stand}\n  обучение: {trained}"
