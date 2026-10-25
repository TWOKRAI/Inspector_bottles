"""Тесты persist_pipeline_choice — CLI-рецепт пишется в состояние ``app.state.yaml``.

Гарантируют, что `run.py <recipe>` делает рецепт «последним активным» в состоянии
рядом с манифестом, чтобы бэкенд и дочерний GUI-процесс читали ОДИН и тот же рецепт
(фикс рассинхрона рецептов → пустых дисплеев). ``app.yaml`` (умолчание) не меняется.
"""

from __future__ import annotations

import os
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
    # Ф6.х.6: persist валидирует существование рецепта ДО записи — рецепты,
    # на которые ссылаются тесты, обязаны существовать рядом с манифестом.
    recipes = tmp_path / "recipes"
    recipes.mkdir(exist_ok=True)
    (recipes / "phone_sketch.yaml").write_text("processes: []\n", encoding="utf-8")
    (recipes / "webcam_sketch.yaml").write_text("processes: []\n", encoding="utf-8")
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
    state = yaml.safe_load(manifest.with_name("app.state.yaml").read_text(encoding="utf-8"))
    assert state == {"pipeline": "recipes/phone_sketch.yaml"}
    # Умолчание в app.yaml остаётся прежним.
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    assert data["pipeline"] == "recipes/webcam_sketch.yaml"


def test_persist_preserves_comments(tmp_path: Path) -> None:
    manifest = _write_manifest(tmp_path)
    bytes_before = manifest.read_bytes()

    persist_pipeline_choice(manifest, "phone_sketch")

    # app.yaml не открывается на запись: комментарии и остальные ключи — байт в байт.
    assert manifest.read_bytes() == bytes_before
    state = yaml.safe_load(manifest.with_name("app.state.yaml").read_text(encoding="utf-8"))
    assert state == {"pipeline": "recipes/phone_sketch.yaml"}


def test_missing_recipe_raises_and_leaves_the_manifest_alone(tmp_path: Path) -> None:
    """Ф6.х.6 — опечатка в CLI не имеет права ломать следующий запуск.

    Прежде persist шёл ДО проверки существования: ``app.yaml`` перезаписывался
    на битый путь, и падал уже И запуск без аргументов (живая репродукция
    ревью 2026-08-03: ``run.py --help`` записал ``recipes/--help.yaml``).
    """
    manifest = _write_manifest(tmp_path)
    text_before = manifest.read_text(encoding="utf-8")

    with pytest.raises(FileNotFoundError):
        persist_pipeline_choice(manifest, "опечатка_нет_такого")

    assert manifest.read_text(encoding="utf-8") == text_before, (
        "манифест изменён при несуществующем рецепте — следующий запуск сломан"
    )


def test_persist_is_idempotent_no_rewrite(tmp_path: Path) -> None:
    manifest = _write_manifest(tmp_path)
    bytes_before = manifest.read_bytes()
    state_path = manifest.with_name("app.state.yaml")

    # Первый вызов создаёт состояние (даже если значение равно умолчанию app.yaml).
    written = persist_pipeline_choice(manifest, "webcam_sketch")
    assert written == "recipes/webcam_sketch.yaml"
    assert yaml.safe_load(state_path.read_text(encoding="utf-8")) == {"pipeline": "recipes/webcam_sketch.yaml"}

    # Состояние отодвигаем в прошлое: повторный вызов с тем же значением не должен его переписывать.
    t0 = 1_000_000_000_000_000_000
    os.utime(state_path, ns=(t0, t0))
    persist_pipeline_choice(manifest, "webcam_sketch")

    assert state_path.stat().st_mtime_ns == t0
    assert manifest.read_bytes() == bytes_before
