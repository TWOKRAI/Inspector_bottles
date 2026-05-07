"""adr_obsolete.py — sync-модуль для генерации раздела «Устарело».

Генерирует список ссылок-заголовков для раздела «Устарело» между маркерами
``<!-- ADR-OBSOLETE:BEGIN/END -->`` в ``multiprocess_framework/DECISIONS.md``.

Переиспользует ``scan_global_adrs`` и ``GlobalAdr`` из ``adr_toc``.
Фильтрует только ADR с ``is_obsolete=True`` и генерирует **только ссылки**,
без полных тел ADR.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .adr_toc import GlobalAdr, scan_global_adrs
from .registry import SyncModule

# Корень репозитория (три уровня вверх от этого файла)
REPO_ROOT = Path(__file__).parent.parent.parent


# ---------------------------------------------------------------------------
# Рендеринг раздела «Устарело»
# ---------------------------------------------------------------------------


def render_obsolete(adrs: list[GlobalAdr]) -> str:
    """Рендерит bullet-список устаревших ADR.

    Фильтрует переданный список по ``is_obsolete=True`` и сортирует по ``num``.
    Для каждого устаревшего ADR формирует одну строку:
    - с ``superseded_by`` → ``- **ADR-NNN**: Title *(Суперсед: **ADR-YYY**)*``
    - без ``superseded_by`` → ``- **ADR-NNN**: Title *(устарело)*``

    Args:
        adrs: список ``GlobalAdr`` (порядок не важен — будет отсортирован).

    Returns:
        Строка с bullet-списком, строки разделены ``\\n``.
        Без ведущих и концевых пустых строк.
        Пустая строка, если устаревших ADR нет.
    """
    # Фильтруем только устаревшие и сортируем по номеру
    obsolete = sorted(
        (adr for adr in adrs if adr.is_obsolete),
        key=lambda a: a.num,
    )

    if not obsolete:
        return ""

    lines: list[str] = []
    for adr in obsolete:
        nnn = f"{adr.num:03d}"
        if adr.superseded_by is not None:
            sup_nnn = f"{adr.superseded_by:03d}"
            line = f"- **ADR-{nnn}**: {adr.title} *(Суперсед: **ADR-{sup_nnn}**)*"
        else:
            line = f"- **ADR-{nnn}**: {adr.title} *(устарело)*"
        lines.append(line)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# SyncModule-реализация
# ---------------------------------------------------------------------------


@dataclass
class _AdrObsoleteSyncModule:
    """Реализация SyncModule Protocol для adr_obsolete."""

    name: str = "adr_obsolete"
    description: str = "Раздел «Устарело» в multiprocess_framework/DECISIONS.md (только ссылки)"

    def render(self) -> dict[Path, dict[str, str]]:
        """Сканирует DECISIONS.md и возвращает сгенерированный раздел «Устарело».

        Returns:
            Словарь ``{путь_к_файлу: {ключ_маркера: контент}}``.
        """
        decisions_path = REPO_ROOT / "multiprocess_framework" / "DECISIONS.md"
        adrs = scan_global_adrs(decisions_path)
        return {decisions_path: {"ADR-OBSOLETE": render_obsolete(adrs)}}


def module() -> SyncModule:
    """Фабрика sync-модуля adr_obsolete.

    Returns:
        Экземпляр ``_AdrObsoleteSyncModule``, соответствующий Protocol ``SyncModule``.
    """
    return _AdrObsoleteSyncModule()
