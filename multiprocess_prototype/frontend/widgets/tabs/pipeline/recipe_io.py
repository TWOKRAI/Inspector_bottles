# -*- coding: utf-8 -*-
"""Распаковка рецептов для вкладки Pipeline (Трек F, Task F.2).

Единая READ-точка разбора формата рецепта (SC-12). Раньше presenter содержал
разъехавшиеся or-цепочки вида ``raw.get("blueprint") or raw.get("data", {})...``
в нескольких методах (diff / launch); при добавлении нового формата их надо было
править синхронно. Здесь они сведены к одному разбору, делегирующему
:func:`multiprocess_prototype.backend.launch.unwrap_recipe` — тот же контракт,
что грузит ``SystemBuilder`` без GUI (модель владельца: GUI лишь формирует
топологию, бэкенд её запускает).

Поддерживаемые формы сырого рецепта (``store.read_raw``):
- **v3** — ``blueprint`` на верхнем уровне (``{"blueprint": {...}, "displays": [...]}``);
- **legacy v2** — ``blueprint`` во вложении ``data`` (``{"data": {"blueprint": {...}}}``);
- прочее (нет blueprint-секции) → ``{}`` (валидация отклонит запуск/диф).

Полный переход на движок миграций dict-документов — Ф4.6/4.5 (там же
``recipes/presenter.py``); здесь закрыт остаток READ-сайта presenter.
"""

from __future__ import annotations

from typing import Any, Mapping

from multiprocess_prototype.backend.launch import unwrap_recipe


def recipe_blueprint(raw: "Mapping[str, Any] | None") -> dict:
    """Blueprint-секция рецепта (processes/wires/…) для diff и валидации запуска.

    Нормализует legacy-вложение ``data.blueprint`` к верхнему уровню и делегирует
    :func:`unwrap_recipe` (разворачивает display_bindings/определения дисплеев в
    границу dict, как при запуске бэкендом). Возвращает ``{}``, если blueprint-
    секции нет (сырая topology без blueprint сюда не попадает — это отдельный вход
    бэкенда, не редакторский рецепт).

    Args:
        raw: сырой рецепт из ``store.read_raw`` (или ``None``).

    Returns:
        dict запускаемого blueprint либо ``{}``.
    """
    if not isinstance(raw, dict):
        return {}
    if "blueprint" in raw:
        return unwrap_recipe(raw)
    data = raw.get("data")
    if isinstance(data, dict) and "blueprint" in data:
        return unwrap_recipe(data)
    return {}


def launch_topology_source(raw: "Mapping[str, Any]") -> Any:
    """Что передать в ``proxy.apply_topology`` для запуска рецепта.

    v3 (blueprint на верхнем уровне) → передаём ПОЛНЫЙ raw-dict: бэкендовский
    ``unwrap_recipe`` сам извлечёт ``display_definitions`` (top-level ``displays``)
    и привязки. legacy v2 / прочее → извлечённый blueprint (backward-compat, как
    было в presenter). Валидность (наличие blueprint) проверяет
    :func:`recipe_blueprint` ДО вызова.
    """
    if isinstance(raw, dict) and "blueprint" in raw:
        return raw
    return recipe_blueprint(raw)


__all__ = ["recipe_blueprint", "launch_topology_source"]
