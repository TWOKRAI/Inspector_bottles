# -*- coding: utf-8 -*-
"""recipe_displays.py — извлечение конфигурации мульти-дисплея из рецепта.

Pure Python, без Qt. Превращает raw-dict активного рецепта в:
  - список слотов главной панели (``build_panel_displays``) — id/label/enabled/x/y/fps_limit;
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

import math
import string
from collections.abc import Callable, Hashable

from multiprocess_framework.modules.logger_module import get_std_logger

logger = get_std_logger(__name__)

#: Предел показа по умолчанию (Гц), если fps_limit в рецепте нет или он не число.
DEFAULT_FPS_LIMIT = 30.0

#: Шаблон плашки тишины, если у дисплея нет ``plate_text``.
DEFAULT_PLATE_TEXT = "{title} · № {number} · {address}"

# Единственные имена, которые подставляет plate_text (шаблон — конфиг оператора, атрибуты не читаем).
_PLATE_FIELDS = frozenset({"title", "number", "address", "serial", "process"})

# Тексты неразбираемых шаблонов, о которых WARNING уже сказан.
_warned_templates: set[str] = set()

#: Порог тишины режима ``silence`` (с), если у дисплея нет годного ``plate_after_s``.
DEFAULT_PLATE_AFTER_S = 2

_PLATE_MODES = ("hold", "silence", "trigger")

_RUN_VIEWS = ("always", "running")

#: Плашки экрана с ``run_view: running`` (``{title}`` — название экрана).
PLATE_IDLE = "{title}\nЛиния не запущена: обработанный кадр появится после ЗАПУСТИТЬ"
PLATE_WAIT = "{title}\nРаботает: ждём первый обработанный кадр"
PLATE_FAULT = "{title}\nАвария: обработка остановлена"
PLATE_NO_STATE = "{title}\nНет данных о состоянии линии"

# Состояния системы, в которых обработки ещё или уже нет.
_IDLE_STATES = ("booting", "not_ready", "ready", "stopping", "shutting_down")

# Негодные plate_mode/plate_after_s/run_view, о которых WARNING уже сказан: (display_id, ключ, repr значения).
_warned_values: set[tuple] = set()


def _parse_fps_limit(raw: object) -> float:
    """Терпимый разбор ``fps_limit`` дисплея: число -> ``float``, иначе ``DEFAULT_FPS_LIMIT``.

    Отсутствует, ``None``, не число, NaN, ``bool`` -> 30.0. ``0`` проходит как ``0.0``
    (потолок 60 Гц применяет FramePump). Исключение конфиг не роняет.
    """
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return DEFAULT_FPS_LIMIT
    value = float(raw)
    return DEFAULT_FPS_LIMIT if math.isnan(value) else value


def build_panel_displays(recipe: dict | None) -> list[dict]:
    """Сформировать список слотов главной панели из определений дисплеев рецепта.

    Args:
        recipe: raw-dict активного рецепта (как из RecipeManager.read_recipe)
                или None.

    Returns:
        Список словарей ``{"id", "label", "enabled", "x", "y", "fps_limit"}`` для каждого
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
                "fps_limit": _parse_fps_limit(defn.get("fps_limit")),
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


def _as_list(value: object) -> list:
    return value if isinstance(value, list) else []


def _plugin_config(processes: list, process_name: str, plugin_name: str) -> dict:
    """Параметры плагина из ``blueprint.processes``: плоские ключи, поверх них ``config``; нет плагина -> {}."""
    for process in processes:
        if not isinstance(process, dict) or process.get("process_name") != process_name:
            continue
        for entry in _as_list(process.get("plugins")):
            if not isinstance(entry, dict) or entry.get("plugin_name") != plugin_name:
                continue
            config = entry.get("config")
            return {**entry, **(config if isinstance(config, dict) else {})}
    return {}


def _plate_setting(defn: dict, display_id: object, key: str, default: object, valid: Callable[[object], bool]):
    """Значение ``plate_*``/``run_view`` определения: ключа нет или оно негодное -> ``default``.

    О негодном — один WARNING на (дисплей, ключ, значение); само значение в лог не пишется.
    """
    if key not in defn:
        return default
    value = defn[key]
    if valid(value):
        return value
    seen = (display_id, key, repr(value))
    if seen not in _warned_values:
        _warned_values.add(seen)
        logger.warning("дисплей '%s': негодный %s, взят %s", display_id, key, default)
    return default


def _is_plate_mode(value: object) -> bool:
    return value in _PLATE_MODES


def _is_plate_after_s(value: object) -> bool:
    # то же правило, что валидатор DisplayDefinition: только int (не bool, не строка) 1..600
    return type(value) is int and 1 <= value <= 600


def _is_run_view(value: object) -> bool:
    return value in _RUN_VIEWS


def run_plate_text(state: object, run_gate: object, run_view: str, title: str) -> str | None:
    """Плашка вместо кадра по состоянию линии; ``None`` — кадр показывать.

    Args:
        state: значение ``system.run.state`` (``None`` — листа нет).
        run_gate: значение ``system.run.run_gate``; ``False`` отключает правило.
        run_view: ``run_view`` экрана; ``always`` отключает правило.
        title: название экрана (подставляется в текст как есть).
    """
    if run_gate is False or run_view == "always":
        return None
    if state == "running":
        return None
    if state == "fault":
        template = PLATE_FAULT
    elif state in _IDLE_STATES:
        template = PLATE_IDLE
    else:
        template = PLATE_NO_STATE
    return template.format(title=title)


def build_plate_sources(recipe: dict | None) -> dict[str, dict]:
    """Поля плашки тишины по каждому дисплею рецепта.

    Источник дисплея — ``plate_source`` определения, иначе ``process.plugin`` ПЕРВОЙ привязки
    этого ``display_id`` в ``blueprint.displays``.

    Args:
        recipe: raw-dict активного рецепта или None. Кривые куски пропускаются без исключения.

    Returns:
        ``{display_id: {"source", "process", "number", "address", "serial", "template", "mode",
        "after_s", "run_view"}}``; чего в рецепте нет — ``None`` (``source``/``process``/``template`` — пустая
        строка). ``mode`` — ``hold`` | ``silence`` | ``trigger`` (умолчание ``hold``), ``after_s`` —
        целое 1..600 (умолчание 2), ``run_view`` — ``always`` | ``running`` (умолчание ``always``).
    """
    if not isinstance(recipe, dict):
        return {}
    blueprint = recipe.get("blueprint")
    if not isinstance(blueprint, dict):
        blueprint = {}
    bindings = _as_list(blueprint.get("displays"))
    processes = _as_list(blueprint.get("processes"))

    result: dict[str, dict] = {}
    for defn in _as_list(recipe.get("displays")):
        if not isinstance(defn, dict):
            continue
        display_id = defn.get("id")
        if not display_id or not isinstance(display_id, Hashable):
            continue
        source = str(defn.get("plate_source") or "")
        if not source:
            for binding in bindings:
                if isinstance(binding, dict) and binding.get("display_id") == display_id and binding.get("node_id"):
                    source = ".".join(str(binding["node_id"]).split(".")[:2])
                    break
        process_name, _, plugin_name = source.partition(".")
        config = _plugin_config(processes, process_name, plugin_name) if source else {}
        number = config.get("camera_id")
        result[display_id] = {
            "source": source,
            "process": process_name,
            "number": number if number is not None else config.get("reader_id"),
            "address": config.get("device_ip"),
            "serial": config.get("device_serial"),
            "template": str(defn.get("plate_text") or ""),
            "mode": _plate_setting(defn, display_id, "plate_mode", "hold", _is_plate_mode),
            "after_s": _plate_setting(defn, display_id, "plate_after_s", DEFAULT_PLATE_AFTER_S, _is_plate_after_s),
            "run_view": _plate_setting(defn, display_id, "run_view", "always", _is_run_view),
        }
    return result


def plate_text(template: str, fields: dict) -> str:
    """Подставить поля в шаблон плашки.

    Подставляются только ``title``/``number``/``address``/``serial``/``process`` без спецификатора и
    конверсии; всё прочее остаётся в тексте как написано. ``None`` и ``""`` -> ``—``. Пустой или
    неразбираемый шаблон -> ``DEFAULT_PLATE_TEXT`` (о неразбираемом один WARNING на его текст).
    """
    template = template or DEFAULT_PLATE_TEXT
    try:
        parts = list(string.Formatter().parse(template))
    except ValueError:
        if template not in _warned_templates:
            _warned_templates.add(template)
            logger.warning("plate_text: шаблон плашки %r не разбирается, взят шаблон по умолчанию", template)
        parts = list(string.Formatter().parse(DEFAULT_PLATE_TEXT))

    out: list[str] = []
    for literal, name, spec, conversion in parts:
        out.append(literal)
        if name is None:
            continue
        if name in _PLATE_FIELDS and not spec and not conversion:
            value = fields.get(name)
            out.append("—" if value is None or value == "" else str(value))
        else:
            bang = f"!{conversion}" if conversion else ""
            colon = f":{spec}" if spec else ""
            out.append("{" + name + bang + colon + "}")
    return "".join(out)


def plate_status(link_state: str | None, age_s: float) -> str:
    """Вторая строка плашки: ``нет связи`` только при ``link_state == "lost"``, иначе ``нет кадров``."""
    word = "нет связи" if link_state == "lost" else "нет кадров"
    return f"{word}, {int(age_s)} с"


__all__ = [
    "build_panel_displays",
    "build_frame_routing",
    "resolve_display_id",
    "build_plate_sources",
    "DEFAULT_PLATE_TEXT",
    "plate_text",
    "plate_status",
    "run_plate_text",
    "PLATE_IDLE",
    "PLATE_WAIT",
    "PLATE_FAULT",
    "PLATE_NO_STATE",
]
