"""Статический манифест плагина (Ф4 Task 4.4).

Образец — VS Code ``package.json`` / Home Assistant ``manifest.json``: набор
классовых полей, которые описывают плагин БЕЗ импорта его кода и без живого
бэкенда (``VERSION``/``API_VERSION``/``REQUIRES`` на :class:`ProcessModulePlugin`,
см. ``plugins/base.py``), плюс канонический словарь категорий (находка C-2
ревью 2026-07-11: 10 фактических значений против 3 задекларированных).

Три независимые вещи живут здесь:

1. **`PLUGIN_API_VERSION`** — версия КОНТРАКТА плагин↔фреймворк (не версия
   плагина). Меняется, когда меняется сам контракт :class:`ProcessModulePlugin`
   (сигнатуры lifecycle-методов, семантика ``PluginContext`` и т.п.), а не при
   каждом релизе фреймворка.
2. **`PluginCategory`** — канонический Enum категорий + карта легаси-алиасов
   (``rendering`` → ``render``, ``output`` → ``sink``) для 6 существующих
   плагинов, использующих устаревшие строки. :func:`canonicalize_category`
   применяется В `PluginRegistry.register()` — сами файлы плагинов не трогаем
   (Принцип №1: только аддитивно).
3. **`check_requires`** — boot-проверка декларации `REQUIRES` плагина против
   фактически доступных менеджеров/сервисов на :class:`PluginContext` (вызывается
   из `PluginOrchestrator.boot()` ДО `configure()` — иначе рассинхрон всплывает
   поздним немым `AttributeError` от `getattr(ctx, ..., None)`).
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .base import PluginContext

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# API_VERSION — версия контракта плагин↔фреймворк
# ---------------------------------------------------------------------------

#: Текущий контракт `ProcessModulePlugin` (major.minor). Дефолт `ProcessModulePlugin.API_VERSION`.
#: Major меняется при breaking-изменении контракта (сигнатуры lifecycle, семантика ctx);
#: minor — при аддитивных расширениях. Boot-проверка (`check_api_version_mismatch`)
#: сравнивает ТОЛЬКО major — см. `plugin_orchestrator.boot()`.
PLUGIN_API_VERSION = "1.0"


def _major(version: str) -> int:
    """Major-компонент семвер-подобной строки ('1.2' -> 1). Мусор/пусто -> 0 (не роняем boot)."""
    try:
        return int(str(version).split(".", 1)[0])
    except (ValueError, TypeError):
        return 0


def api_version_major_mismatch(plugin_api_version: str, framework_api_version: str = PLUGIN_API_VERSION) -> bool:
    """True, если major-версии контракта плагина и фреймворка расходятся.

    Boot-политика (план Ф4.4: «boot mismatch → WARNING») — НЕ отказ, только
    громкое предупреждение: плагин мог быть написан под другой major контракта
    и молча сломаться на несовместимости, которую сейчас нечем поймать точнее.
    """
    return _major(plugin_api_version) != _major(framework_api_version)


# ---------------------------------------------------------------------------
# category — канонический Enum + легаси-алиасы
# ---------------------------------------------------------------------------


class PluginCategory(str, Enum):
    """Канонический словарь категорий плагина (C-2, review-2026-07-11).

    Выровнен с доменными папками `Plugins/*` (source← sources/, sink← sinks/,
    остальные — 1:1 с именем папки). `str`-подмешивание — категория остаётся
    сравнимой/хэшируемой как обычная строка (``entry.category == "processing"``,
    ``dict[entry.category]``, f-строки) — весь существующий код, читающий
    `entry.category`/`plugin.category` как `str`, продолжает работать без правок.
    """

    SOURCE = "source"
    PROCESSING = "processing"
    RENDER = "render"
    IO = "io"
    SINK = "sink"
    HUB = "hub"
    CONTROL = "control"
    FILTER = "filter"
    CALIBRATION = "calibration"
    RUNTIME = "runtime"
    UTILITY = "utility"


#: Легаси-значения, фактически встречающиеся в 51 существующем плагине (аудит
#: 2026-07-11: `rendering`×3, `output`×3) → канон. Плагины НЕ правим (Принцип
#: №1) — маппинг применяется централизованно в `PluginRegistry.register()`.
CATEGORY_LEGACY_ALIASES: dict[str, str] = {
    "rendering": "render",  # contour_draw, overlay_draw, circle_draw
    "output": "sink",  # database, frame_saver, telemetry_sink — терминальные писатели
}

_CANONICAL_CATEGORY_VALUES = {c.value for c in PluginCategory}


def canonicalize_category(raw: str) -> str:
    """Канонизировать значение `category`: легаси-алиас → канон; неизвестное → WARNING (не отказ).

    Пустая строка возвращается как есть (плагин без объявленной категории —
    существующий legacy-паттерн, не наша забота здесь). Неканоничное
    (не входит ни в `PluginCategory`, ни в `CATEGORY_LEGACY_ALIASES`) значение
    ГРОМКО логируется, но НЕ отклоняется — Принцип №1 (ничего не удалять/ломать,
    только аддитивно): регистрация плагина не должна падать из-за таксономии.
    """
    if not raw:
        return raw
    mapped = CATEGORY_LEGACY_ALIASES.get(raw, raw)
    if mapped not in _CANONICAL_CATEGORY_VALUES:
        logger.warning(
            "PluginRegistry: category='%s' не входит в канонический список PluginCategory (%s) "
            "и не покрыта CATEGORY_LEGACY_ALIASES — регистрация продолжена как есть (ADR-PM-013)",
            raw,
            ", ".join(sorted(_CANONICAL_CATEGORY_VALUES)),
        )
        return raw
    return mapped


# ---------------------------------------------------------------------------
# REQUIRES — boot fail-fast проверка зависимостей плагина
# ---------------------------------------------------------------------------


def _check_one_requirement(ctx: "PluginContext | Any", requirement: str) -> str | None:
    """Проверить одно REQUIRES-значение против ctx. None = удовлетворено, иначе — текст, чего не хватает.

    Форматы:
      - ``"shm"``             — ``ctx.memory_manager`` должен быть не None.
      - ``"manager:<attr>"``  — ``getattr(ctx, attr, None)`` должен быть не None
                                 (напр. ``manager:worker_manager``, ``manager:command_manager``).
      - ``"service:<name>"``  — ``getattr(ctx.services, name, None)`` должен быть не None
                                 (framework-менеджер, который плагин вешает на `services`
                                 в `configure_managers()`, напр. SQLManager — см. docstring
                                 `ProcessModulePlugin.configure_managers`).
    """
    if requirement == "shm":
        if getattr(ctx, "memory_manager", None) is None:
            return "shm (ctx.memory_manager отсутствует)"
        return None

    kind, sep, name = requirement.partition(":")
    if not sep:
        return f"неизвестный формат REQUIRES: '{requirement}' (ожидается 'manager:<attr>' | 'service:<name>' | 'shm')"

    if kind == "manager":
        if getattr(ctx, name, None) is None:
            return f"manager:{name} (ctx.{name} отсутствует)"
        return None

    if kind == "service":
        services = getattr(ctx, "services", None)
        if getattr(services, name, None) is None:
            return f"service:{name} (ctx.services.{name} отсутствует)"
        return None

    return f"неизвестный вид REQUIRES: '{kind}' в '{requirement}' (ожидается 'manager:' | 'service:' | 'shm')"


def check_requires(ctx: "PluginContext | Any", requires: tuple[str, ...]) -> list[str]:
    """Проверить REQUIRES плагина против ctx. Пустой список = все требования удовлетворены.

    Вызывается из `PluginOrchestrator.boot()` ДО `plugin._do_configure(ctx)` —
    вместо позднего немого `AttributeError` от `getattr(ctx, ..., None)` внутри
    `configure()`/`start()` плагин с недостающей зависимостью получает внятную
    ошибку с именем плагина и тем, чего не хватает (см. `check_requires` вызов
    в `plugin_orchestrator.py`).
    """
    missing: list[str] = []
    for requirement in requires:
        problem = _check_one_requirement(ctx, requirement)
        if problem is not None:
            missing.append(problem)
    return missing
