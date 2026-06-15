"""Тесты persist_pipeline_choice — CLI-рецепт пишется в манифест (app.yaml).

Гарантируют, что `run.py <recipe>` делает рецепт «последним активным» в конфиге,
чтобы бэкенд и дочерний GUI-процесс читали ОДИН и тот же рецепт (фикс рассинхрона
рецептов → пустых дисплеев).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from multiprocess_prototype.backend.launch import (
    _manifest_pipeline_value,
    persist_pipeline_choice,
)

_MANIFEST_TEXT = """\
# Заголовок-комментарий манифеста (должен сохраниться).
system: backend/config/system.yaml
styles:
  dir: frontend/styles/themes
  active: innotech_theme
base: backend/topology/base.yaml
# Активный pipeline (комментарий к ключу).
pipeline: recipes/webcam_sketch.yaml
recipes: recipes
"""


def _write_manifest(tmp_path: Path) -> Path:
    path = tmp_path / "app.yaml"
    path.write_text(_MANIFEST_TEXT, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("override", "expected"),
    [
        ("phone_sketch", "recipes/phone_sketch.yaml"),  # голое имя → recipes/<name>.yaml
        ("recipes/color_inspect.yaml", "recipes/color_inspect.yaml"),  # явный путь — как есть
        ("backend\\topology\\demo.yaml", "backend/topology/demo.yaml"),  # нормализация разделителей
    ],
)
def test_manifest_pipeline_value(override: str, expected: str) -> None:
    assert _manifest_pipeline_value(override) == expected


def test_persist_writes_bare_name_as_recipe_path(tmp_path: Path) -> None:
    manifest = _write_manifest(tmp_path)

    written = persist_pipeline_choice(manifest, "phone_sketch")

    assert written == "recipes/phone_sketch.yaml"
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    assert data["pipeline"] == "recipes/phone_sketch.yaml"


def test_persist_preserves_comments(tmp_path: Path) -> None:
    manifest = _write_manifest(tmp_path)

    persist_pipeline_choice(manifest, "phone_sketch")

    text = manifest.read_text(encoding="utf-8")
    # Комментарии (ruamel round-trip) сохранены, остальные ключи не тронуты.
    assert "Заголовок-комментарий манифеста" in text
    assert "Активный pipeline (комментарий к ключу)." in text
    assert "active: innotech_theme" in text


def test_persist_is_idempotent_no_rewrite(tmp_path: Path) -> None:
    manifest = _write_manifest(tmp_path)
    # Значение уже совпадает с текущим → файл не должен переписываться (mtime тот же).
    mtime_before = manifest.stat().st_mtime_ns

    written = persist_pipeline_choice(manifest, "webcam_sketch")

    assert written == "recipes/webcam_sketch.yaml"
    assert manifest.stat().st_mtime_ns == mtime_before
