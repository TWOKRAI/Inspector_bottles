"""adr_modules.py — sync-модуль для генерации таблиц ADR.

Генерирует два раздела:
- «Модульные решения» в multiprocess_framework/DECISIONS.md (маркер ADR-INDEX)
- «Коды модулей» в multiprocess_framework/docs/ADR_REGISTRY.md (маркер ADR-CODES)

Источник истины — заголовки `## ADR-{CODE}-NNN: ...` в локальных
modules/*/DECISIONS.md. Порядок строк — из _adr_layers.MODULE_LAYERS.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .registry import SyncModule
from . import _adr_layers

# Корень репозитория (три уровня вверх от этого файла)
REPO_ROOT = Path(__file__).parent.parent.parent

# Регэксп для заголовков ADR уровня ## в модульных DECISIONS.md:
# ## ADR-{CODE}-{NNN}[( was ADR-...)]: {title}
_ADR_HEADER_RE = re.compile(
    r"^## ADR-([A-Z]+)-(\d+)(?:\s+\(was ADR-[\w-]+\))?: (.+)$",
    re.MULTILINE,
)


# ---------------------------------------------------------------------------
# Структуры данных
# ---------------------------------------------------------------------------


@dataclass
class AdrEntry:
    """Одна запись ADR из заголовка модульного DECISIONS.md."""

    num: int    # Числовой номер (например, 1 для ADR-SS-001)
    title: str  # Заголовок после двоеточия


@dataclass
class ModuleAdrs:
    """Результат сканирования одного modules/X/DECISIONS.md."""

    module_name: str        # Имя модуля (равно decisions_path.parent.name)
    code: str               # Код ADR (например "SS"); пустая строка если ADR-заголовков нет
    adrs: list[AdrEntry] = field(default_factory=list)  # Отсортированный список ADR


# ---------------------------------------------------------------------------
# Парсинг
# ---------------------------------------------------------------------------


def scan_module(decisions_path: Path) -> ModuleAdrs:
    """Сканирует DECISIONS.md одного модуля и возвращает его ADR.

    Если файл не существует — возвращает пустой ModuleAdrs (не падает).
    Если в файле встречаются два разных {CODE} — поднимает ValueError.

    Args:
        decisions_path: путь к modules/X/DECISIONS.md.

    Returns:
        ModuleAdrs с заполненными code и adrs.

    Raises:
        ValueError: если в одном файле два разных ADR-кода.
    """
    module_name = decisions_path.parent.name

    # Если файл отсутствует — возвращаем пустую структуру
    if not decisions_path.exists():
        return ModuleAdrs(module_name=module_name, code="", adrs=[])

    text = decisions_path.read_text(encoding="utf-8")
    matches = _ADR_HEADER_RE.findall(text)

    if not matches:
        return ModuleAdrs(module_name=module_name, code="", adrs=[])

    # Проверяем, что все вхождения используют один и тот же код
    codes_found = {code for code, _num, _title in matches}
    if len(codes_found) > 1:
        raise ValueError(
            f"В файле '{decisions_path}' обнаружено несколько ADR-кодов: "
            f"{sorted(codes_found)}. Каждый модуль должен использовать ровно один код."
        )

    code = codes_found.pop()
    adrs = [
        AdrEntry(num=int(num), title=title.strip())
        for _code, num, title in matches
    ]
    # Сортируем по номеру ADR
    adrs.sort(key=lambda e: e.num)

    return ModuleAdrs(module_name=module_name, code=code, adrs=adrs)


# ---------------------------------------------------------------------------
# Валидация
# ---------------------------------------------------------------------------


def validate_all(
    all_modules: list[ModuleAdrs],
    *,
    module_layers: list[tuple[str, str]] | None = None,
    modules_without_local_adr: set[str] | None = None,
) -> None:
    """Валидирует список отсканированных модулей.

    Проверки:
    1. Каждый модуль из all_modules зарегистрирован в MODULE_LAYERS или
       MODULES_WITHOUT_LOCAL_ADR. Иначе ValueError с подсказкой.
    2. Ни один ADR-код не используется в двух разных модулях.
    3. Модуль из MODULES_WITHOUT_LOCAL_ADR не имеет непустого кода (иначе
       ValueError — это указывает на несоответствие реестра и файла).

    Args:
        all_modules: результаты сканирования.
        module_layers: переопределение _adr_layers.MODULE_LAYERS (для тестов).
        modules_without_local_adr: переопределение _adr_layers.MODULES_WITHOUT_LOCAL_ADR.

    Raises:
        ValueError: при любом нарушении.
    """
    if module_layers is None:
        module_layers = _adr_layers.MODULE_LAYERS
    if modules_without_local_adr is None:
        modules_without_local_adr = _adr_layers.MODULES_WITHOUT_LOCAL_ADR

    # Множество всех зарегистрированных имён модулей
    known_names: set[str] = {name for name, _layer in module_layers}
    known_names |= modules_without_local_adr

    # Проверка 1: каждый отсканированный модуль зарегистрирован
    for mod in all_modules:
        if mod.module_name not in known_names:
            raise ValueError(
                f"Модуль '{mod.module_name}' не зарегистрирован: "
                f"добавь строку в MODULE_LAYERS или в MODULES_WITHOUT_LOCAL_ADR "
                f"в scripts/sync/_adr_layers.py"
            )

    # Проверка 2: глобальная уникальность кодов (среди модулей с непустым кодом)
    code_to_modules: dict[str, list[str]] = {}
    for mod in all_modules:
        if mod.code:
            code_to_modules.setdefault(mod.code, []).append(mod.module_name)
    for code, names in code_to_modules.items():
        if len(names) > 1:
            raise ValueError(
                f"Дубликат кода ADR: '{code}' используется в модулях {names}. "
                f"Каждый модуль должен иметь уникальный ADR-код."
            )

    # Проверка 3: модуль из MODULES_WITHOUT_LOCAL_ADR не должен иметь кода
    for mod in all_modules:
        if mod.module_name in modules_without_local_adr and mod.code:
            raise ValueError(
                f"Модуль '{mod.module_name}' находится в MODULES_WITHOUT_LOCAL_ADR, "
                f"но его DECISIONS.md содержит ADR-код '{mod.code}'. "
                f"Либо добавь модуль в MODULE_LAYERS, либо удали ADR-заголовки из файла."
            )


# ---------------------------------------------------------------------------
# Форматирование статуса
# ---------------------------------------------------------------------------


def _format_status(adrs: list[AdrEntry], code: str) -> str:
    """Форматирует содержимое столбца «Статус» для таблицы модульных решений.

    Правила:
    - 0 ADR или пустой code: возвращает пустую строку.
    - 1 ADR: "ADR-{CODE}-{NNN} ({title})".
    - 2 ADR: "ADR-{CODE}-{first}…{last} ({title1}, {title2})".
    - 3+ ADR: "ADR-{CODE}-{first}…{last} ({first_title}, ..., {last_title})".

    Все номера форматируются с нулевым дополнением до 3 цифр.

    Args:
        adrs: список ADR-записей (должны быть отсортированы по num).
        code: ADR-код модуля (например "SS").

    Returns:
        Строка статуса для ячейки таблицы.
    """
    if not adrs or not code:
        return ""

    def fmt_num(n: int) -> str:
        """Форматирует номер с zero-padding до 3 цифр."""
        return str(n).zfill(3)

    if len(adrs) == 1:
        entry = adrs[0]
        return f"ADR-{code}-{fmt_num(entry.num)} ({entry.title})"

    first = adrs[0]
    last = adrs[-1]
    range_str = f"ADR-{code}-{fmt_num(first.num)}…{fmt_num(last.num)}"

    if len(adrs) == 2:
        return f"{range_str} ({first.title}, {last.title})"

    # 3+ ADR
    return f"{range_str} ({first.title}, ..., {last.title})"


# ---------------------------------------------------------------------------
# Рендеринг таблиц
# ---------------------------------------------------------------------------


def render_index(
    all_modules: list[ModuleAdrs],
    *,
    module_layers: list[tuple[str, str]] | None = None,
) -> str:
    """Рендерит Markdown таблицу «Модульные решения».

    Порядок строк — из module_layers (по умолчанию _adr_layers.MODULE_LAYERS).
    Модули из MODULES_WITHOUT_LOCAL_ADR не включаются (они не в module_layers).

    Args:
        all_modules: результаты сканирования модулей.
        module_layers: переопределение порядка (для тестов).

    Returns:
        Строка Markdown-таблицы.
    """
    if module_layers is None:
        module_layers = _adr_layers.MODULE_LAYERS

    # Индекс по имени для быстрого поиска
    by_name: dict[str, ModuleAdrs] = {m.module_name: m for m in all_modules}

    lines = [
        "| Модуль | Файл | Слой | Статус |",
        "|--------|------|------|--------|",
    ]
    for module_name, layer_label in module_layers:
        mod = by_name.get(module_name)
        if mod is None:
            # Модуль есть в MODULE_LAYERS, но физически отсутствует — пропускаем
            # (validate_all должен был это поймать, но render не должен падать)
            continue

        col_module = f"`{module_name}`"
        col_file = (
            f"[`modules/{module_name}/DECISIONS.md`]"
            f"(modules/{module_name}/DECISIONS.md)"
        )
        col_layer = layer_label
        col_status = _format_status(mod.adrs, mod.code)

        lines.append(f"| {col_module} | {col_file} | {col_layer} | {col_status} |")

    return "\n".join(lines) + "\n"


def render_codes(
    all_modules: list[ModuleAdrs],
    *,
    module_layers: list[tuple[str, str]] | None = None,
) -> str:
    """Рендерит Markdown таблицу «Коды модулей» для ADR_REGISTRY.md.

    Включает только модули с непустым ADR-кодом, в порядке module_layers.

    Args:
        all_modules: результаты сканирования модулей.
        module_layers: переопределение порядка (для тестов).

    Returns:
        Строка Markdown-таблицы.
    """
    if module_layers is None:
        module_layers = _adr_layers.MODULE_LAYERS

    by_name: dict[str, ModuleAdrs] = {m.module_name: m for m in all_modules}

    lines = [
        "| Код | Модуль | Файл решений |",
        "|-----|--------|--------------|",
    ]
    for module_name, _layer in module_layers:
        mod = by_name.get(module_name)
        if mod is None or not mod.code:
            # Пропускаем модули без кода или отсутствующие
            continue

        col_code = f"**{mod.code}**"
        col_module = f"`{module_name}`"
        col_file = f"`modules/{module_name}/DECISIONS.md`"

        lines.append(f"| {col_code} | {col_module} | {col_file} |")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# SyncModule-реализация
# ---------------------------------------------------------------------------


@dataclass
class _AdrModulesSyncModule:
    """Реализация SyncModule Protocol для adr_modules."""

    name: str = "adr_modules"
    description: str = (
        'Таблицы «Модульные решения» (DECISIONS.md) и «Коды модулей» (ADR_REGISTRY.md)'
    )

    def render(self) -> dict[Path, dict[str, str]]:
        """Сканирует модули, валидирует и возвращает сгенерированные таблицы.

        Returns:
            Словарь {путь_к_файлу: {ключ_маркера: контент}}.
        """
        # Сканируем все существующие DECISIONS.md в modules/*/
        modules_dir = REPO_ROOT / "multiprocess_framework" / "modules"
        scanned: list[ModuleAdrs] = []
        for decisions_file in sorted(modules_dir.glob("*/DECISIONS.md")):
            mod = scan_module(decisions_file)
            scanned.append(mod)

        validate_all(scanned)

        return {
            REPO_ROOT / "multiprocess_framework" / "DECISIONS.md": {
                "ADR-INDEX": render_index(scanned),
            },
            REPO_ROOT / "multiprocess_framework" / "docs" / "ADR_REGISTRY.md": {
                "ADR-CODES": render_codes(scanned),
            },
        }


def module() -> SyncModule:
    """Фабрика sync-модуля adr_modules.

    Returns:
        Экземпляр _AdrModulesSyncModule, соответствующий Protocol SyncModule.
    """
    return _AdrModulesSyncModule()
