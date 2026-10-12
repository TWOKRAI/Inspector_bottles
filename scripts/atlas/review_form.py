"""Читатель отчёта ревью по форме ADR-ATL-004 §5 (Task 1.9f).

Purpose: разобрать `reports/<id>.review-r<N>.md` в `Review` (вердикт, счета Итог и Классы, пункты замечаний) и
    собрать все нарушения формы разом; читает `atlas metrics` (M2, M3). Только stdlib, без реестра и git.
    Разбор по `splitlines()`: CRLF рабочего дерева Windows и LF дают одно и то же.
Public API: Review, parse, SEVERITIES, CLASSES.
Stability: lite
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["CLASSES", "SEVERITIES", "Review", "parse"]

SEVERITIES = ("blocker", "major", "minor", "nit")
CLASSES = ("fact", "dryrun", "form", "context", "design", "scope", "process")
_TITLE = re.compile(r"^# \S+ — ревью (стадии 0|после кода), раунд \d+$")
_VERDICT = re.compile(r"^Вердикт: (APPROVED|CHANGES REQUESTED)$")
_TOTAL = re.compile(r"^Итог: blocker (\d+), major (\d+), minor (\d+), nit (\d+)$")
_BY_CLASS = re.compile(
    r"^Классы: fact (\d+), dryrun (\d+), form (\d+), context (\d+), design (\d+), scope (\d+), process (\d+)$"
)
_BULLET = re.compile(r"^- \[(" + "|".join(SEVERITIES) + r")/(" + "|".join(CLASSES) + r")\] \S")
_NOTES = "## Замечания"
_OPEN = "## Что я оставил открытым / ненадёжным"


@dataclass(frozen=True)
class Review:
    """Разобранный отчёт: порядок `severities` и `classes` — как в строках Итог и Классы."""

    verdict: str
    severities: tuple[int, ...]
    classes: tuple[int, ...]
    findings: tuple[tuple[str, str], ...]  # (степень, класс) в порядке строк файла


def _head(lines: list[str], errors: list[str]) -> tuple[str | None, tuple[int, ...] | None, tuple[int, ...] | None]:
    """Строки 1–4: нарушения -> errors; (вердикт, Итог, Классы), у нечитаемой строки None."""
    if not _TITLE.match(lines[0] if lines else ""):
        errors.append("строка 1: нет заголовка `# <id> — ревью стадии 0|после кода, раунд <N>`")
    if len(lines) < 4:
        errors.append("строки 2–4: отчёт короче 4 строк (Вердикт, Итог, Классы)")
        return None, None, None
    verdict = _VERDICT.match(lines[1])
    total = _TOTAL.match(lines[2])
    by_class = _BY_CLASS.match(lines[3])
    for number, found, form in (
        (2, verdict, "Вердикт: APPROVED|CHANGES REQUESTED"),
        (3, total, "Итог: blocker <n>, …"),
        (4, by_class, "Классы: fact <n>, …"),
    ):
        if not found:
            errors.append(f"строка {number}: не по форме `{form}`")
    return (
        verdict.group(1) if verdict else None,
        tuple(int(g) for g in total.groups()) if total else None,
        tuple(int(g) for g in by_class.groups()) if by_class else None,
    )


def _open_section_empty(lines: list[str]) -> bool:
    after = lines[lines.index(_OPEN) + 1 :]
    section = after[: next((i for i, ln in enumerate(after) if ln.startswith("## ")), len(after))]
    return not any(ln.strip() for ln in section)


def parse(text: str) -> tuple[Review | None, list[str]]:
    """(Review, []) без нарушений формы §5, иначе (None, нарушения в порядке файла); текст — `строка N: …`."""
    lines = text.splitlines()
    errors: list[str] = []
    verdict, declared_sev, declared_cls = _head(lines, errors)
    findings: list[tuple[str, str]] = []
    for number, line in enumerate(lines, 1):
        found = _BULLET.match(line)
        if found:
            findings.append((found.group(1), found.group(2)))
        elif line.lstrip().startswith("- ["):
            errors.append(f"строка {number}: пункт вне формы `- [степень/класс] текст`: {line.strip()[:60]}")
    for names, declared, key, row in (
        (SEVERITIES, declared_sev, 0, "Итог"),
        (CLASSES, declared_cls, 1, "Классы"),
    ):
        if declared is None:
            continue
        for name, count in zip(names, declared):
            actual = sum(1 for item in findings if item[key] == name)
            if actual != count:
                errors.append(f"{row}: {name} {count}, пунктов {actual}")
    if _NOTES not in lines:
        errors.append(f"нет раздела `{_NOTES}`")
    if _OPEN not in lines:
        errors.append(f"нет раздела `{_OPEN}`")
    elif _open_section_empty(lines):
        errors.append(f"раздел `{_OPEN}` пуст")
    if errors or verdict is None or declared_sev is None or declared_cls is None:
        return None, errors
    return Review(verdict, declared_sev, declared_cls, tuple(findings)), []
