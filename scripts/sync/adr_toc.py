"""adr_toc.py — sync-модуль для генерации оглавления глобальных ADR.

Генерирует раздел «Оглавление (по номеру)» между маркерами
``<!-- ADR-TOC:BEGIN/END -->`` в ``multiprocess_framework/DECISIONS.md``.

Источник истины — заголовки ``## ADR-NNN: ...`` (числовые номера, без
кодовых префиксов вида ``ADR-CHN-001``) в теле того же файла.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .registry import SyncModule

# Корень репозитория (три уровня вверх от этого файла)
REPO_ROOT = Path(__file__).parent.parent.parent

# Регэксп для глобальных ADR-заголовков вида: ## ADR-NNN: Заголовок
# Числовой NNN — ровно цифры (без буквенных префиксов).
_ADR_HEADER_RE = re.compile(r"^## ADR-(\d+): (.+)$")

# Регэксп строки статуса «устарело» — точное совпадение (без суффиксов).
_STATUS_OBSOLETE_RE = re.compile(r"^- Статус:\s*устарело\s*$")

# Регэксп строки «Суперсед» с числовым номером преемника.
_SUPERSEDED_RE = re.compile(r"^- Суперсед:\s*\*\*ADR-(\d+)\*\*")


# ---------------------------------------------------------------------------
# Структуры данных
# ---------------------------------------------------------------------------


@dataclass
class GlobalAdr:
    """Одна запись глобального ADR из ``multiprocess_framework/DECISIONS.md``.

    Атрибуты:
        num: числовой номер ADR (например, 99 для ``ADR-099``).
        title: заголовок после двоеточия.
        is_obsolete: True, если ADR помечен как устаревший.
        superseded_by: номер ADR-преемника (из строки ``Суперсед: **ADR-Y**``),
            или None если преемник не указан.
    """

    num: int
    title: str
    is_obsolete: bool
    superseded_by: int | None


# ---------------------------------------------------------------------------
# Парсинг
# ---------------------------------------------------------------------------


def scan_global_adrs(decisions_path: Path) -> list[GlobalAdr]:
    """Читает ``DECISIONS.md`` и возвращает список глобальных ADR-записей.

    Алгоритм — два прохода (один логически):

    1. Первый проход: сканируем строки файла, фиксируем позиции строк с
       заголовками ``## ADR-NNN: ...`` (только числовые NNN).
       Заголовки с кодовым префиксом (``## ADR-CHN-001``) игнорируются.

    2. Для каждого заголовка берём срез строк от его позиции до следующего
       ``## ADR-`` заголовка (или конца файла) и ищем в нём:

       - Строку ``^- Статус: устарело$`` (точное совпадение, без суффиксов).
         Строка ``Статус: принято (частично устарело по схемам ...)``
         НЕ считается устаревшей.
       - Строку ``^- Суперсед: **ADR-N**`` — парсим номер преемника.
         Наличие ``Суперсед`` само по себе устанавливает ``is_obsolete=True``.

    Функция переиспользуется в ``adr_obsolete.py`` (T1.3.4).

    Args:
        decisions_path: путь к ``multiprocess_framework/DECISIONS.md``.

    Returns:
        Список ``GlobalAdr`` в порядке появления в файле
        (НЕ сортированный — сортировку выполняет ``render_toc``).

    Raises:
        FileNotFoundError: если файл не найден.
    """
    text = decisions_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    # --- Шаг 1: собираем позиции заголовков ---
    # Каждый элемент: (line_index, num, title)
    headers: list[tuple[int, int, str]] = []
    for idx, line in enumerate(lines):
        m = _ADR_HEADER_RE.match(line)
        if m:
            headers.append((idx, int(m.group(1)), m.group(2).strip()))

    if not headers:
        return []

    # --- Шаг 2: парсим тело каждого ADR-блока ---
    result: list[GlobalAdr] = []

    for i, (start_idx, num, title) in enumerate(headers):
        # Тело блока — строки от следующей после заголовка до следующего заголовка
        if i + 1 < len(headers):
            end_idx = headers[i + 1][0]
        else:
            end_idx = len(lines)

        body_lines = lines[start_idx + 1 : end_idx]

        is_obsolete = False
        superseded_by: int | None = None

        for body_line in body_lines:
            # Проверяем точное совпадение «Статус: устарело»
            if _STATUS_OBSOLETE_RE.match(body_line):
                is_obsolete = True

            # Проверяем наличие «Суперсед: **ADR-NNN**»
            sup_m = _SUPERSEDED_RE.match(body_line)
            if sup_m:
                superseded_by = int(sup_m.group(1))
                is_obsolete = True  # наличие Суперсед → тоже устарело

        result.append(GlobalAdr(
            num=num,
            title=title,
            is_obsolete=is_obsolete,
            superseded_by=superseded_by,
        ))

    return result


# ---------------------------------------------------------------------------
# Slugify
# ---------------------------------------------------------------------------


def _slugify(title: str) -> str:
    """Преобразует заголовок ADR в GitHub-совместимый anchor-slug.

    Правила:
    - Всё в нижний регистр.
    - Удаляются символы: ``:`` ``,`` ``.`` ``/`` ``(`` ``)`` ``«`` ``»``.
    - Пробелы заменяются на ``-``.
    - Не-ASCII символы (например, русские) сохраняются.

    Args:
        title: заголовок ADR (без номера).

    Returns:
        Строка-slug для использования в Markdown-ссылке.
    """
    # GitHub-стиль anchor: lowercase, удаляем пунктуацию и markdown-метасимволы,
    # пробелы → дефисы, схлопываем повторяющиеся дефисы.
    # Whitelist-подход: оставляем буквы (включая русские), цифры, пробел и дефис;
    # всё прочее удаляется. Это покрывает backticks, em/en dash, !, =, %, & и т.п.
    slug = title.lower()
    slug = re.sub(r"[^\w\s-]", "", slug, flags=re.UNICODE)
    slug = slug.replace(" ", "-")
    slug = re.sub(r"-{2,}", "-", slug)
    slug = slug.strip("-")
    return slug


# ---------------------------------------------------------------------------
# Рендеринг TOC
# ---------------------------------------------------------------------------


def render_toc(adrs: list[GlobalAdr]) -> str:
    """Рендерит bullet-список оглавления глобальных ADR.

    Список сортируется по возрастанию ``num`` (стабильная сортировка).
    Каждая строка имеет вид::

        - [ADR-NNN](#adr-nnn-slug): Title  *(устарело, см. ADR-YYY)*

    Args:
        adrs: список ``GlobalAdr`` (порядок не важен — будет отсортирован).

    Returns:
        Строка с bullet-списком, строки разделены ``\\n``.
        Без ведущей и конечной пустой строки (их добавляет ``replace_between_markers``).
    """
    sorted_adrs = sorted(adrs, key=lambda a: a.num)

    lines: list[str] = []
    for adr in sorted_adrs:
        nnn = f"{adr.num:03d}"
        # Формируем anchor: adr-NNN-slug-заголовка
        slug = _slugify(adr.title)
        anchor = f"adr-{nnn}-{slug}" if slug else f"adr-{nnn}"

        line = f"- [ADR-{nnn}](#{anchor}): {adr.title}"

        # Добавляем пометку об устаревании
        if adr.is_obsolete:
            if adr.superseded_by is not None:
                line += f" *(устарело, см. ADR-{adr.superseded_by:03d})*"
            else:
                line += " *(устарело)*"

        lines.append(line)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# SyncModule-реализация
# ---------------------------------------------------------------------------


@dataclass
class _AdrTocSyncModule:
    """Реализация SyncModule Protocol для adr_toc."""

    name: str = "adr_toc"
    description: str = "Оглавление глобальных ADR в multiprocess_framework/DECISIONS.md"

    def render(self) -> dict[Path, dict[str, str]]:
        """Сканирует DECISIONS.md и возвращает сгенерированное оглавление.

        Returns:
            Словарь ``{путь_к_файлу: {ключ_маркера: контент}}``.
        """
        decisions_path = REPO_ROOT / "multiprocess_framework" / "DECISIONS.md"
        adrs = scan_global_adrs(decisions_path)
        return {decisions_path: {"ADR-TOC": render_toc(adrs)}}


def module() -> SyncModule:
    """Фабрика sync-модуля adr_toc.

    Returns:
        Экземпляр ``_AdrTocSyncModule``, соответствующий Protocol ``SyncModule``.
    """
    return _AdrTocSyncModule()
