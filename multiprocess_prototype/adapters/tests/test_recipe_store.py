# -*- coding: utf-8 -*-
"""
adapters/tests/test_recipe_store.py — тесты для RecipeStoreFromManager.

Покрывает: Task C.5 Phase C (RecipeStore adapter с denormalization meta → top-level).

Acceptance criteria:
- Adapter satisfies Protocol RecipeStore.
- Backward-compatible YAML формат при write (top-level name/version/..., НЕ meta:).
- Legacy RecipeManager.set_active() продолжает работать.
- Round-trip lossless для критичных полей.
- Реальный demo_webcam_split_merge.yaml (если доступен) или минимальный YAML.

Refs: plans/2026-05-27_cross-tab-architecture/phase-c-adapters.md (Task C.5)
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any
import pytest
import yaml

from multiprocess_prototype.adapters.stores.recipe_store import RecipeStoreFromManager
from multiprocess_prototype.domain.entities.recipe import Recipe, RecipeMeta
from multiprocess_prototype.domain.protocols.recipe_store import RecipeStore


# ---------------------------------------------------------------------------
# Путь к live demo-рецепту (если существует)
# ---------------------------------------------------------------------------

_DEMO_YAML = Path(__file__).resolve().parents[2] / "recipes" / "demo_webcam_split_merge.yaml"


# ---------------------------------------------------------------------------
# Минимальный корректный рецепт для тестов
# ---------------------------------------------------------------------------


def _minimal_recipe_dict() -> dict[str, Any]:
    """Минимальный dict рецепта в формате v3 (top-level name/version)."""
    return {
        "name": "test-recipe",
        "version": 3,
        "description": "Тестовый рецепт для unit-тестов",
        "created_at": "2026-05-27T12:00:00",
        "blueprint": {
            "processes": [
                {
                    "process_name": "capture_proc",
                    "plugins": [{"plugin_name": "capture"}],
                },
            ],
            "wires": [],
        },
        "active_services": ["webcam_camera"],
        "display_bindings": [
            {"node_id": "capture_proc.capture.frame", "display_id": "main_output"},
        ],
    }


def _make_recipe() -> Recipe:
    """Создать Recipe entity из минимального dict."""
    return Recipe.from_dict(_minimal_recipe_dict())


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    """Записать dict в YAML-файл."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------


class FakeEngine:
    """Минимальный мок RecipeEngine для тестирования через RecipeManager."""

    def __init__(self, recipes_dir: Path) -> None:
        self.recipes_dir = recipes_dir
        self._active_name: str | None = None

    def get_active(self) -> str | None:
        return self._active_name

    def list(self) -> list[str]:
        return sorted(p.stem for p in self.recipes_dir.glob("*.yaml"))

    def load(self, name: str, remap: dict[str, str] | None = None) -> list:
        """Имитация загрузки: устанавливает active и возвращает пустые deltas."""
        path = self.recipes_dir / f"{name}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"Рецепт не найден: {path}")
        self._active_name = name
        return []


@pytest.fixture()
def recipe_dir(tmp_path: Path) -> Path:
    """Временная директория для рецептов."""
    d = tmp_path / "recipes"
    d.mkdir()
    return d


@pytest.fixture()
def fake_engine(recipe_dir: Path) -> FakeEngine:
    """FakeEngine привязанный к tmp recipe_dir."""
    return FakeEngine(recipe_dir)


@pytest.fixture()
def recipe_manager(fake_engine: FakeEngine) -> Any:
    """RecipeManager поверх FakeEngine (без state_proxy и logger)."""
    from multiprocess_prototype.recipes.manager import RecipeManager

    return RecipeManager(engine=fake_engine, state_proxy=None, logger=None)


@pytest.fixture()
def store(recipe_manager: Any, recipe_dir: Path) -> RecipeStoreFromManager:
    """RecipeStoreFromManager — adapter под тестирование."""
    return RecipeStoreFromManager(recipe_manager=recipe_manager, recipe_dir=recipe_dir)


# ---------------------------------------------------------------------------
# Тест 1: list возвращает известные slug'и
# ---------------------------------------------------------------------------


def test_list_returns_known_slugs(store: RecipeStoreFromManager, recipe_dir: Path) -> None:
    """Положить 3 YAML в tmp_path → list() возвращает отсортированный tuple."""
    for name in ("beta-recipe", "alpha-recipe", "gamma-recipe"):
        _write_yaml(recipe_dir / f"{name}.yaml", _minimal_recipe_dict())

    result = store.list()

    assert isinstance(result, tuple)
    assert result == ("alpha-recipe", "beta-recipe", "gamma-recipe")


# ---------------------------------------------------------------------------
# Тест 2: list пустой директории → пустой tuple
# ---------------------------------------------------------------------------


def test_list_empty_dir_returns_empty_tuple(store: RecipeStoreFromManager) -> None:
    """Пустая директория → list() возвращает пустой tuple."""
    result = store.list()

    assert result == ()


# ---------------------------------------------------------------------------
# Тест 3: read demo-рецепта (или минимального тестового)
# ---------------------------------------------------------------------------


def test_read_demo_recipe_returns_valid_recipe(
    store: RecipeStoreFromManager,
    recipe_dir: Path,
) -> None:
    """Если live demo_webcam_split_merge.yaml существует — скопировать и прочитать.
    Иначе — использовать минимальный тестовый рецепт.
    """
    if _DEMO_YAML.exists():
        # Используем реальный demo-рецепт
        slug = "demo_webcam_split_merge"
        shutil.copy2(_DEMO_YAML, recipe_dir / f"{slug}.yaml")
    else:
        # Используем минимальный тестовый
        slug = "test-recipe"
        _write_yaml(recipe_dir / f"{slug}.yaml", _minimal_recipe_dict())

    result = store.read(slug)

    assert result is not None
    assert isinstance(result, Recipe)
    assert isinstance(result.meta, RecipeMeta)
    assert result.meta.name != ""  # имя должно быть непустым
    assert result.meta.version >= 2


# ---------------------------------------------------------------------------
# Тест 4: write → read round-trip
# ---------------------------------------------------------------------------


def test_write_recipe_roundtrips_through_disk(
    store: RecipeStoreFromManager,
    recipe_dir: Path,
) -> None:
    """write(slug, recipe) → read(slug) совпадает по критичным полям."""
    original = _make_recipe()
    slug = "roundtrip-test"

    store.write(slug, original)
    loaded = store.read(slug)

    assert loaded is not None
    # Критичные поля совпадают
    assert loaded.meta.name == original.meta.name
    assert loaded.meta.version == original.meta.version
    assert loaded.meta.description == original.meta.description
    assert loaded.meta.created_at == original.meta.created_at
    # Blueprint: количество процессов совпадает
    assert len(loaded.blueprint.processes) == len(original.blueprint.processes)
    assert loaded.blueprint.processes[0].process_name == original.blueprint.processes[0].process_name
    # Active services
    assert loaded.active_services == original.active_services
    # Display bindings: количество совпадает
    assert len(loaded.display_bindings) == len(original.display_bindings)


# ---------------------------------------------------------------------------
# Тест 5: write создаёт backward-compatible YAML (Q2 Variant A)
# ---------------------------------------------------------------------------


def test_write_backward_compatible_format(
    store: RecipeStoreFromManager,
    recipe_dir: Path,
) -> None:
    """После write() YAML содержит name, version, description на TOP LEVEL,
    а НЕ внутри meta: {...}. Это критерий decision Q2.
    """
    recipe = _make_recipe()
    slug = "compat-test"

    store.write(slug, recipe)

    # Читаем raw YAML для проверки формата (не через adapter)
    raw = yaml.safe_load((recipe_dir / f"{slug}.yaml").read_text(encoding="utf-8"))

    # Top-level поля должны присутствовать
    assert "name" in raw, "name должен быть на верхнем уровне YAML"
    assert "version" in raw, "version должен быть на верхнем уровне YAML"
    assert "description" in raw, "description должен быть на верхнем уровне YAML"

    # meta ключ НЕ должен присутствовать
    assert "meta" not in raw, "meta НЕ должен быть в YAML (денормализация Q2)"

    # Значения совпадают с оригиналом
    assert raw["name"] == "test-recipe"
    assert raw["version"] == 3
    assert raw["description"] == "Тестовый рецепт для unit-тестов"


# ---------------------------------------------------------------------------
# Тест 6: get_active возвращает текущий slug
# ---------------------------------------------------------------------------


def test_get_active_returns_current_slug(
    store: RecipeStoreFromManager,
    recipe_dir: Path,
) -> None:
    """set_active("foo") → get_active() == "foo"."""
    # Создаём файл рецепта (set_active проверяет существование)
    slug = "foo"
    _write_yaml(recipe_dir / f"{slug}.yaml", _minimal_recipe_dict())

    store.set_active(slug)

    assert store.get_active() == slug


# ---------------------------------------------------------------------------
# Тест 7: set_active(None) сбрасывает active
# ---------------------------------------------------------------------------


def test_set_active_none_clears_active(
    store: RecipeStoreFromManager,
    recipe_dir: Path,
) -> None:
    """set_active(None) сбрасывает активный рецепт → get_active() == None."""
    slug = "bar"
    _write_yaml(recipe_dir / f"{slug}.yaml", _minimal_recipe_dict())

    # Сначала активируем
    store.set_active(slug)
    assert store.get_active() == slug

    # Затем деактивируем
    store.set_active(None)
    assert store.get_active() is None


# ---------------------------------------------------------------------------
# Тест 8: delete удаляет файл
# ---------------------------------------------------------------------------


def test_delete_removes_file(
    store: RecipeStoreFromManager,
    recipe_dir: Path,
) -> None:
    """delete(slug) удаляет файл рецепта с диска."""
    slug = "to-delete"
    yaml_path = recipe_dir / f"{slug}.yaml"
    _write_yaml(yaml_path, _minimal_recipe_dict())
    assert yaml_path.exists()

    store.delete(slug)

    assert not yaml_path.exists()


# ---------------------------------------------------------------------------
# Тест 9: read несуществующего slug → None
# ---------------------------------------------------------------------------


def test_unknown_slug_read_returns_none(store: RecipeStoreFromManager) -> None:
    """read() для несуществующего slug возвращает None."""
    result = store.read("nonexistent-recipe")

    assert result is None


# ---------------------------------------------------------------------------
# Тест 10: Protocol-совместимость (assignment check)
# ---------------------------------------------------------------------------


def test_satisfies_protocol(store: RecipeStoreFromManager) -> None:
    """RecipeStoreFromManager удовлетворяет Protocol RecipeStore."""
    # Структурная проверка: assignment к Protocol-типизированной переменной
    typed_store: RecipeStore = store  # noqa: F841 — проверяет наличие методов

    # Проверяем что все методы Protocol callable
    assert callable(store.list)
    assert callable(store.read)
    assert callable(store.write)
    assert callable(store.delete)
    assert callable(store.get_active)
    assert callable(store.set_active)
    # Phase F: новые методы Protocol
    assert callable(store.read_raw)
    assert callable(store.save_raw)
    assert callable(store.duplicate)
    assert callable(store.deactivate)


# ---------------------------------------------------------------------------
# Тест 11: delete несуществующего файла не падает
# ---------------------------------------------------------------------------


def test_delete_nonexistent_does_not_raise(store: RecipeStoreFromManager) -> None:
    """delete() для несуществующего slug не выбрасывает исключение."""
    # Не должно быть исключения
    store.delete("phantom-recipe")


# ---------------------------------------------------------------------------
# Тест 12: write перезаписывает существующий файл
# ---------------------------------------------------------------------------


def test_write_overwrites_existing_file(
    store: RecipeStoreFromManager,
    recipe_dir: Path,
) -> None:
    """Повторный write() перезаписывает YAML без ошибок."""
    recipe = _make_recipe()
    slug = "overwrite-test"

    store.write(slug, recipe)

    # Модифицируем рецепт (frozen → создаём новый)
    modified_data = _minimal_recipe_dict()
    modified_data["description"] = "Обновлённое описание"
    modified_recipe = Recipe.from_dict(modified_data)

    store.write(slug, modified_recipe)

    # Проверяем что последняя версия на диске
    raw = yaml.safe_load((recipe_dir / f"{slug}.yaml").read_text(encoding="utf-8"))
    assert raw["description"] == "Обновлённое описание"


# ---------------------------------------------------------------------------
# Тест 13: _denormalize корректно обрабатывает все поля meta
# ---------------------------------------------------------------------------


def test_denormalize_extracts_all_meta_fields() -> None:
    """_denormalize вытаскивает name, version, description, created_at из meta."""
    data = {
        "meta": {
            "name": "my-recipe",
            "version": 2,
            "description": "desc",
            "created_at": "2026-01-01",
        },
        "blueprint": {"processes": [], "wires": []},
        "active_services": [],
        "display_bindings": [],
        "gui_positions": {},
    }

    result = RecipeStoreFromManager._denormalize(data)

    assert "meta" not in result
    assert result["name"] == "my-recipe"
    assert result["version"] == 2
    assert result["description"] == "desc"
    assert result["created_at"] == "2026-01-01"
    # Blueprint и другие поля сохранены
    assert "blueprint" in result
    assert "active_services" in result


# ---------------------------------------------------------------------------
# Тест 14: _denormalize при отсутствии meta — данные без изменений
# ---------------------------------------------------------------------------


def test_denormalize_without_meta_passes_through() -> None:
    """_denormalize с data без meta — возвращает данные как есть (без meta ключа)."""
    data = {
        "name": "already-flat",
        "version": 2,
        "blueprint": {"processes": []},
    }

    result = RecipeStoreFromManager._denormalize(data)

    assert result["name"] == "already-flat"
    assert result["version"] == 2
    assert "meta" not in result


# ---------------------------------------------------------------------------
# Тест 15: live demo YAML round-trip (если файл существует)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _DEMO_YAML.exists(), reason="demo_webcam_split_merge.yaml не найден")
def test_live_demo_yaml_roundtrip(
    store: RecipeStoreFromManager,
    recipe_dir: Path,
) -> None:
    """Полный round-trip с реальным demo-рецептом: copy → read → write → read."""
    slug = "demo_webcam_split_merge"
    shutil.copy2(_DEMO_YAML, recipe_dir / f"{slug}.yaml")

    # Первое чтение
    recipe_v1 = store.read(slug)
    assert recipe_v1 is not None

    # Write (денормализованный формат)
    store.write(slug, recipe_v1)

    # Второе чтение
    recipe_v2 = store.read(slug)
    assert recipe_v2 is not None

    # Критичные поля совпадают
    assert recipe_v2.meta.name == recipe_v1.meta.name
    assert recipe_v2.meta.version == recipe_v1.meta.version
    assert len(recipe_v2.blueprint.processes) == len(recipe_v1.blueprint.processes)
    assert len(recipe_v2.blueprint.wires) == len(recipe_v1.blueprint.wires)
    assert recipe_v2.active_services == recipe_v1.active_services
    assert len(recipe_v2.display_bindings) == len(recipe_v1.display_bindings)


# ===========================================================================
# Phase F: тесты read_raw / save_raw / duplicate / deactivate / set_active->bool
# ===========================================================================


# ---------------------------------------------------------------------------
# Тест 16: read_raw возвращает raw dict
# ---------------------------------------------------------------------------


def test_read_raw_returns_dict(
    store: RecipeStoreFromManager,
    recipe_dir: Path,
) -> None:
    """read_raw() возвращает dict из YAML (без конвертации в Recipe entity)."""
    slug = "raw-test"
    _write_yaml(recipe_dir / f"{slug}.yaml", _minimal_recipe_dict())

    result = store.read_raw(slug)

    assert isinstance(result, dict)
    assert result["name"] == "test-recipe"
    assert result["version"] == 3
    assert "blueprint" in result


# ---------------------------------------------------------------------------
# Тест 17: read_raw для несуществующего slug -> None
# ---------------------------------------------------------------------------


def test_read_raw_unknown_slug_returns_none(store: RecipeStoreFromManager) -> None:
    """read_raw() для несуществующего slug возвращает None."""
    assert store.read_raw("phantom") is None


# ---------------------------------------------------------------------------
# Тест 18: save_raw -> read_raw round-trip
# ---------------------------------------------------------------------------


def test_save_raw_roundtrip(
    store: RecipeStoreFromManager,
    recipe_dir: Path,
) -> None:
    """save_raw(slug, data) -> read_raw(slug) возвращает эквивалентный dict."""
    slug = "raw-roundtrip"
    data = {
        "version": 2,
        "name": "round",
        "data": {
            "blueprint": {"processes": [{"process_name": "p1"}], "wires": []},
            "gui_positions": {"p1": [100, 200]},
        },
    }

    store.save_raw(slug, data)
    loaded = store.read_raw(slug)

    assert loaded is not None
    assert loaded["version"] == 2
    assert loaded["name"] == "round"
    assert loaded["data"]["gui_positions"]["p1"] == [100, 200]


# ---------------------------------------------------------------------------
# Тест 19: duplicate создаёт копию
# ---------------------------------------------------------------------------


def test_duplicate_creates_copy(
    store: RecipeStoreFromManager,
    recipe_dir: Path,
) -> None:
    """duplicate() создаёт копию рецепта с обновлённым именем."""
    slug = "original"
    _write_yaml(recipe_dir / f"{slug}.yaml", _minimal_recipe_dict())

    result = store.duplicate(slug, "cloned")

    assert result is True
    assert (recipe_dir / "cloned.yaml").exists()
    # Оригинал на месте
    assert (recipe_dir / f"{slug}.yaml").exists()


# ---------------------------------------------------------------------------
# Тест 20: duplicate несуществующего -> False
# ---------------------------------------------------------------------------


def test_duplicate_nonexistent_returns_false(store: RecipeStoreFromManager) -> None:
    """duplicate() для несуществующего source -> False."""
    assert store.duplicate("phantom", "new") is False


# ---------------------------------------------------------------------------
# Тест 21: deactivate сбрасывает active
# ---------------------------------------------------------------------------


def test_deactivate_clears_active(
    store: RecipeStoreFromManager,
    recipe_dir: Path,
) -> None:
    """deactivate() -> get_active() == None."""
    slug = "active-test"
    _write_yaml(recipe_dir / f"{slug}.yaml", _minimal_recipe_dict())

    store.set_active(slug)
    assert store.get_active() == slug

    store.deactivate()
    assert store.get_active() is None


# ---------------------------------------------------------------------------
# Тест 22: set_active возвращает bool
# ---------------------------------------------------------------------------


def test_set_active_returns_bool(
    store: RecipeStoreFromManager,
    recipe_dir: Path,
) -> None:
    """set_active() возвращает True при успехе, False при отсутствии рецепта."""
    slug = "bool-test"
    _write_yaml(recipe_dir / f"{slug}.yaml", _minimal_recipe_dict())

    assert store.set_active(slug) is True
    assert store.get_active() == slug

    assert store.set_active("nonexistent") is False


# ---------------------------------------------------------------------------
# Тест 23: set_active(None) сбрасывает через deactivate, возвращает True
# ---------------------------------------------------------------------------


def test_set_active_none_returns_true(
    store: RecipeStoreFromManager,
    recipe_dir: Path,
) -> None:
    """set_active(None) -> True и active сброшен."""
    slug = "deact-test"
    _write_yaml(recipe_dir / f"{slug}.yaml", _minimal_recipe_dict())
    store.set_active(slug)

    result = store.set_active(None)

    assert result is True
    assert store.get_active() is None
