# -*- coding: utf-8 -*-
"""recipe_displays.py — извлечение конфигурации мульти-дисплея из рецепта.

Pure Python, без Qt. Превращает raw-dict активного рецепта в:
  - список слотов главной панели (``build_panel_displays``) — id/label/enabled/x/y;
  - карту маршрутизации кадров ``process_name -> display_id``
    (``build_frame_routing``) для классификации входящих кадров по полю ``sender``.

Контракт рецепта (v3):
  - Определения дисплеев — top-level секция ``displays`` (list[dict] с
    ключами id/name/enabled/position/...).
  - Привязки узлов к дисплеям — ``blueprint.displays`` (list[dict] с
    ключами node_id/display_id). node_id = ``process.plugin.port`` —
    первый сегмент (до первой точки) равен имени процесса-отправителя
    (``sender`` в IPC-сообщении кадра).

Транспорт мульти-дисплея (см. отчёт teamlead, ветка feat/dataset-circle-capture):
  кадры обоих процессов (draw/maskview) приходят в GUI через единый
  data_receiver-bridge. Различитель — ``sender`` (имя процесса). По привязкам
  рецепта строим map process->display_id и кладём кадр в нужный слот.

Бэк-совместимость:
  - Рецепт без ``displays`` → пустой список слотов (вызывающий код делает
    fallback на единственный слот "main").
  - Привязок нет → пустая карта → все кадры идут в "main".
  - enabled отсутствует у определения → True (показывать).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def build_panel_displays(recipe: dict | None) -> list[dict]:
    """Сформировать список слотов главной панели из определений дисплеев рецепта.

    Args:
        recipe: raw-dict активного рецепта (как из RecipeManager.read_recipe)
                или None.

    Returns:
        Список словарей ``{"id", "label", "enabled", "x", "y"}`` для каждого
        определения дисплея. Пустой список если рецепта/секции displays нет.
        Фильтрацию по enabled и сортировку делает ImagePanelWidget.set_displays.
    """
    if not isinstance(recipe, dict):
        return []

    definitions = recipe.get("displays")
    if not isinstance(definitions, list):
        return []

    result: list[dict] = []
    for defn in definitions:
        if not isinstance(defn, dict):
            continue
        display_id = defn.get("id")
        if not display_id:
            continue
        position = defn.get("position") if isinstance(defn.get("position"), dict) else {}
        result.append(
            {
                "id": display_id,
                "label": defn.get("name") or display_id,
                # enabled отсутствует → True (бэк-совместимо)
                "enabled": bool(defn.get("enabled", True)),
                "x": int(position.get("x", 0)),
                "y": int(position.get("y", 0)),
            }
        )
    return result


def build_frame_routing(recipe: dict | None) -> dict[str, str]:
    """Построить карту маршрутизации кадров ``process_name -> display_id``.

    Читает привязки ``blueprint.displays`` (node_id -> display_id) и
    извлекает имя процесса из node_id (первый сегмент ``process.plugin.port``).

    Если несколько привязок указывают на один процесс (теоретически возможно
    при fan-out), последняя выигрывает — логируется предупреждение.

    Args:
        recipe: raw-dict активного рецепта или None.

    Returns:
        dict ``{process_name: display_id}``. Пустой если привязок нет.
    """
    if not isinstance(recipe, dict):
        return {}

    blueprint = recipe.get("blueprint")
    if not isinstance(blueprint, dict):
        return {}

    bindings = blueprint.get("displays")
    if not isinstance(bindings, list):
        return {}

    routing: dict[str, str] = {}
    for binding in bindings:
        if not isinstance(binding, dict):
            continue
        node_id = binding.get("node_id")
        display_id = binding.get("display_id")
        if not node_id or not display_id:
            continue
        # node_id = "process.plugin.port" → process = первый сегмент
        process_name = str(node_id).split(".", 1)[0]
        if process_name in routing and routing[process_name] != display_id:
            logger.warning(
                "build_frame_routing: процесс '%s' привязан к нескольким дисплеям ('%s' и '%s') — побеждает последний",
                process_name,
                routing[process_name],
                display_id,
            )
        routing[process_name] = display_id
    return routing


def resolve_display_id(
    msg_dict: dict,
    routing: dict[str, str],
    *,
    default: str = "main",
) -> str:
    """Определить целевой слот для кадра по полю ``sender``.

    Args:
        msg_dict: IPC-сообщение кадра (содержит ``sender`` — имя процесса).
        routing:  карта ``process_name -> display_id`` (из build_frame_routing).
        default:  слот по умолчанию, если sender неизвестен или нет привязки.

    Returns:
        display_id целевого слота (или ``default``).
    """
    sender = msg_dict.get("sender")
    if isinstance(sender, str) and sender in routing:
        return routing[sender]
    return default


__all__ = [
    "build_panel_displays",
    "build_frame_routing",
    "resolve_display_id",
]
