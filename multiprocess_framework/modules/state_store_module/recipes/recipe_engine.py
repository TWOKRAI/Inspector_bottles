"""RecipeEngine — snapshot/restore config-ветвей через TreeStore.

Рецепт = snapshot config-ветвей, сохранённый в YAML.
При load() все изменения применяются через Transaction → один batch подписчикам.

Версионирование:
    Текущая версия определяется параметром recipe_version (по умолчанию 2).
    Доменные миграции подключаются через параметры migration_fn/migration_check_fn
    (ADR-SS-003) — фреймворк не знает о доменных схемах рецептов.

Если при load() обнаружен legacy-формат (migration_check_fn возвращает True):
    - создаётся backup .bak рядом с файлом,
    - вызывается migration_fn для преобразования данных,
    - основной файл перезаписывается с meta.version = recipe_version.
"""
from __future__ import annotations

import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import yaml

from ..core.tree_store import TreeStore

logger = logging.getLogger(__name__)

# Ветви, которые snapshot'ятся по умолчанию (при save без paths).
# Список доменно-нейтральный — приложение может передать свой набор путей в save(paths=...).
DEFAULT_CONFIG_PATHS: list[str] = [
    "cameras",   # cameras.*.config + cameras.*.regions
    "renderer",  # renderer.config
    "robot",     # robot.config
    "database",  # database.config
]


def _flatten(data: dict, prefix: str = "") -> list[tuple[str, Any]]:
    """Рекурсивно разворачивает вложенный dict в список (dot.path, value).

    Используется для поэлементного сравнения в diff() и is_dirty().
    """
    items: list[tuple[str, Any]] = []
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            items.extend(_flatten(value, path))
        else:
            items.append((path, value))
    return items


def _remap_path(path: str, remap: dict[str, str]) -> str:
    """Применяет remap к пути.

    remap = {"cameras.0": "cameras.1"}
    path "cameras.0.config.fps" → "cameras.1.config.fps"

    Перебираем ключи remap от длиннейшего к кратчайшему,
    чтобы "cameras.0.regions.1" не матчился на "cameras.0" раньше
    чем на "cameras.0.regions" (если такой ключ есть).
    """
    # Сортируем по длине убывающе — длиннейший префикс первый
    for old_prefix in sorted(remap.keys(), key=len, reverse=True):
        new_prefix = remap[old_prefix]
        if path == old_prefix:
            return new_prefix
        if path.startswith(old_prefix + "."):
            return new_prefix + path[len(old_prefix):]
    return path


def _set_nested(target: dict, path: str, value: Any) -> None:
    """Устанавливает значение в nested dict по dot-пути.

    Создаёт промежуточные dict'ы при необходимости.
    """
    keys = path.split(".")
    node = target
    for key in keys[:-1]:
        if key not in node or not isinstance(node[key], dict):
            node[key] = {}
        node = node[key]
    node[keys[-1]] = value


class RecipeEngine:
    """Управление рецептами через TreeStore.

    Рецепт = snapshot config-ветвей.
    Хранятся в YAML на диске (recipes_dir/).

    При load() — одна Transaction → один batch подписчикам.

    ADR-SS-003: миграции рецептов между версиями подключаются через параметры
        migration_fn(data: dict) -> dict
        migration_check_fn(data: dict) -> bool
    Это позволяет держать RecipeEngine generic-классом фреймворка,
    а доменную логику миграций (например, "regions.processing_blocks → regions.nodes")
    оставить в прикладном слое.
    """

    def __init__(
        self,
        store: TreeStore,
        recipes_dir: Path,
        migration_fn: Callable[[dict], dict] | None = None,
        migration_check_fn: Callable[[dict], bool] | None = None,
        recipe_version: int = 2,
    ) -> None:
        """
        Args:
            store: TreeStore, в который применяются загруженные рецепты.
            recipes_dir: директория с YAML-файлами рецептов.
            migration_fn: callback миграции legacy-данных (ADR-SS-003).
                Принимает старый recipe.data, возвращает новый recipe.data.
                Если None — миграция не выполняется (только проверка версии в meta).
            migration_check_fn: callback проверки legacy-формата.
                Принимает recipe.data, возвращает True если данные требуют миграции.
                Если None — проверяется только meta.version.
            recipe_version: текущая версия формата рецепта (записывается в meta).
        """
        self._store = store
        self._recipes_dir = Path(recipes_dir)
        self._migration_fn = migration_fn
        self._migration_check_fn = migration_check_fn
        self._recipe_version = recipe_version
        # Создаём директорию если не существует
        self._recipes_dir.mkdir(parents=True, exist_ok=True)

        # Имя последнего загруженного рецепта
        self._active_name: str | None = None
        # Snapshot данных на момент load (для is_dirty / diff)
        self._loaded_snapshot: dict[str, Any] | None = None
        # Пути, которые были загружены (для is_dirty — сравниваем только их)
        self._loaded_paths: list[str] | None = None

    # ------------------------------------------------------------------
    # save
    # ------------------------------------------------------------------

    def save(
        self,
        name: str,
        paths: list[str] | None = None,
    ) -> None:
        """Сохранить рецепт.

        paths=None → snapshot всех config-ветвей (DEFAULT_CONFIG_PATHS).
        paths=["cameras.0.regions"] → частичный snapshot.

        Записывает YAML: recipes_dir/{name}.yaml
        """
        snapshot_paths = paths if paths is not None else DEFAULT_CONFIG_PATHS

        # Собираем данные из store
        data: dict[str, Any] = {}
        for p in snapshot_paths:
            if self._store.has(p):
                value = self._store.get(p)
                _set_nested(data, p, value)

        recipe = {
            "meta": {
                "name": name,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "description": "",
                "version": self._recipe_version,
            },
            "data": data,
        }

        file_path = self._recipes_dir / f"{name}.yaml"
        with open(file_path, "w", encoding="utf-8") as f:
            yaml.dump(recipe, f, default_flow_style=False, allow_unicode=True)

        logger.info("Рецепт '%s' сохранён: %s", name, file_path)

    # ------------------------------------------------------------------
    # load
    # ------------------------------------------------------------------

    def load(
        self,
        name: str,
        remap: dict[str, str] | None = None,
    ) -> list:
        """Загрузить рецепт. Применить к TreeStore.

        remap: {"cameras.0": "cameras.1"} — перемаппинг путей.

        Использует Transaction для батчинга дельт.
        Если задан migration_check_fn и он возвращает True (или meta.version
        меньше recipe_version) — вызывается migration_fn (если задан),
        делается backup, файл перезаписывается с обновлённой meta.

        Returns:
            list of Delta — все изменения.
        """
        file_path = self._recipes_dir / f"{name}.yaml"
        if not file_path.exists():
            raise FileNotFoundError(f"Рецепт не найден: {file_path}")

        with open(file_path, "r", encoding="utf-8") as f:
            recipe = yaml.safe_load(f)

        data = recipe.get("data", {})

        # --- Проверка версии и миграция (ADR-SS-003) ---
        meta = recipe.get("meta", {}) or {}
        version = meta.get("version", 1)  # отсутствие поля = считаем legacy

        version_outdated = version < self._recipe_version
        domain_check = (
            self._migration_check_fn is not None
            and self._migration_check_fn(data)
        )

        if (version_outdated or domain_check) and self._migration_fn is not None:
            bak_path = file_path.with_suffix(".yaml.bak")
            shutil.copy2(file_path, bak_path)
            logger.info(
                "Рецепт '%s': обнаружен legacy-формат, создан backup: %s",
                name,
                bak_path,
            )

            migrated_data = self._migration_fn(data)

            # Обновляем meta и перезаписываем файл
            recipe["meta"] = dict(meta)
            recipe["meta"]["version"] = self._recipe_version
            recipe["meta"]["migrated_from_v1"] = True
            recipe["data"] = migrated_data

            with open(file_path, "w", encoding="utf-8") as f:
                yaml.dump(recipe, f, default_flow_style=False, allow_unicode=True)

            logger.info(
                "Рецепт '%s' мигрирован → v%d, backup: %s",
                name,
                self._recipe_version,
                bak_path,
            )
            data = migrated_data

        # Разворачиваем в плоские пути
        flat = _flatten(data)

        # Применяем remap если задан
        if remap:
            flat = [(_remap_path(path, remap), value) for path, value in flat]

        # Применяем через Transaction — один batch
        with self._store.transaction(label=f"recipe_load:{name}") as tx:
            for path, value in flat:
                tx.set(path, value)

        deltas = tx.deltas

        # Запоминаем для is_dirty / diff
        self._active_name = name
        # Собираем snapshot того, что было загружено (после remap)
        loaded_top_paths = self._extract_top_paths(flat)
        self._loaded_paths = loaded_top_paths
        self._loaded_snapshot = {}
        for p in loaded_top_paths:
            if self._store.has(p):
                self._loaded_snapshot[p] = self._store.get(p)

        logger.info(
            "Рецепт '%s' загружен, %d дельт", name, len(deltas)
        )
        return deltas

    # ------------------------------------------------------------------
    # list / delete / get_active
    # ------------------------------------------------------------------

    def list(self) -> list[str]:
        """Список имён рецептов (файлов без .yaml)."""
        return sorted(
            p.stem for p in self._recipes_dir.glob("*.yaml")
        )

    def delete(self, name: str) -> bool:
        """Удалить рецепт. True если удалён."""
        file_path = self._recipes_dir / f"{name}.yaml"
        if file_path.exists():
            file_path.unlink()
            logger.info("Рецепт '%s' удалён", name)
            # Сбрасываем active если удалили текущий
            if self._active_name == name:
                self._active_name = None
                self._loaded_snapshot = None
                self._loaded_paths = None
            return True
        return False

    def get_active(self) -> str | None:
        """Имя последнего загруженного рецепта (или None)."""
        return self._active_name

    # ------------------------------------------------------------------
    # is_dirty / diff
    # ------------------------------------------------------------------

    def is_dirty(self) -> bool:
        """True если config изменился после загрузки рецепта.

        Сравнивает текущее состояние store с запомненным snapshot
        по загруженным путям.
        """
        if self._loaded_snapshot is None or self._loaded_paths is None:
            return False

        for p in self._loaded_paths:
            current = self._store.get(p, default=None)
            saved = self._loaded_snapshot.get(p)
            if current != saved:
                return True
        return False

    def diff(self, name: str) -> list[tuple[str, Any, Any]]:
        """Показать различия: текущее состояние vs рецепт.

        Returns:
            list of (path, current_value, recipe_value)
        """
        file_path = self._recipes_dir / f"{name}.yaml"
        if not file_path.exists():
            raise FileNotFoundError(f"Рецепт не найден: {file_path}")

        with open(file_path, "r", encoding="utf-8") as f:
            recipe = yaml.safe_load(f)

        data = recipe.get("data", {})
        flat_recipe = _flatten(data)

        differences: list[tuple[str, Any, Any]] = []
        for path, recipe_value in flat_recipe:
            current_value = self._store.get(path, default=None)
            if current_value != recipe_value:
                differences.append((path, current_value, recipe_value))

        return differences

    # ------------------------------------------------------------------
    # Вспомогательные методы
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_top_paths(flat: list[tuple[str, Any]]) -> list[str]:
        """Извлекает уникальные top-level пути из плоского списка.

        ("cameras.0.config.fps", 30) → "cameras"
        ("renderer.config.draw", True) → "renderer"
        """
        seen: set[str] = set()
        result: list[str] = []
        for path, _ in flat:
            top = path.split(".")[0]
            if top not in seen:
                seen.add(top)
                result.append(top)
        return result
