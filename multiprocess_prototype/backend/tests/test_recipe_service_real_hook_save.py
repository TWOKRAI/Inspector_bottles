"""``RecipeService.save`` с настоящим ``InspectorRecipeFormatHook`` на копиях реальных рецептов.

Framework-тесты гоняют ``save`` только с ``FakeHook`` (ADR-120). Здесь хук реальный: ломающая правка
``normalize`` (перенос ключей, миграции) не должна менять байты файла при неизменном теле и не должна
стирать комментарии при правке поля. Ожидания — байты исходного файла и литералы, не значения из кода под тестом.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest
import yaml

from multiprocess_framework.modules.recipe.service import RecipeService
from multiprocess_prototype.backend.recipe_format_hook import InspectorRecipeFormatHook

_RECIPES = Path(__file__).resolve().parents[2] / "recipes"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize("recipe", ["camera_robot_calibration", "webcam_sketch"])
def test_real_hook_save_identical_body_keeps_bytes_and_changed_field_keeps_comments(
    tmp_path: Path, recipe: str
) -> None:
    path = tmp_path / f"{recipe}.yaml"
    shutil.copyfile(_RECIPES / f"{recipe}.yaml", path)
    original = path.read_bytes()
    comments = original.decode("utf-8").count("#")
    assert comments > 0  # литерал-охрана: рецепт с комментариями, иначе тест вхолостую
    service = RecipeService(
        recipes_dir=tmp_path,
        hook=InspectorRecipeFormatHook(),
        apply_topology=lambda args: {"success": True},
        persist_active=lambda p: None,
        read_active=lambda: None,
    )

    got = service.get({"name": recipe})
    assert got["success"] is True
    assert got["rev"] == _sha(original)

    # 1) тело без изменений -> файл не тронут, rev прежний (+0/-0)
    same = service.save({"name": recipe, "base_rev": got["rev"], "body": got["body"]})
    assert same == {"success": True, "name": recipe, "rev": _sha(original)}
    assert path.read_bytes() == original

    # 2) правка поля -> комментарии на месте, rev ответа от байтов после записи
    body = dict(got["body"])
    body["description"] = "changed by test"
    res = service.save({"name": recipe, "base_rev": same["rev"], "body": body})
    assert res["success"] is True
    after = path.read_bytes()
    assert after != original
    assert after.decode("utf-8").count("#") == comments
    assert res["rev"] == _sha(after)
    assert yaml.safe_load(after)["description"] == "changed by test"
    # 3) ключ убран из тела -> убран из файла (дельта считается от нормализованного ТЕКУЩЕГО файла, не от {})
    body = dict(body)
    del body["description"]
    res = service.save({"name": recipe, "base_rev": res["rev"], "body": body})
    assert res["success"] is True
    assert "description" not in yaml.safe_load(path.read_bytes())

    if recipe == "camera_robot_calibration":
        # legacy top-level gui_positions остался в файле (normalize его переносит, но не стирает)
        assert "gui_positions" in yaml.safe_load(after)
