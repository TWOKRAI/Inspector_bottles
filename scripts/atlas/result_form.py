"""Форма итога задачи (форма 0.7): разбор разделов трёх видов и линт (Task 1.9a).

Purpose: один парсер раздела итога `tasks/<id>.result.md` для хвостов `pack` (views.py), `atlas lint-result`, хука
    `lint-result.sh` и находки RESULT_FORM (adapters/plans.py). Раздел бывает заголовком `## T`, абзацем `**T:**`
    или абзацем `**T.**`; писатель итога и читатель расходились в одном знаке (CTO_PLAN_REVISION §0) — теперь
    читают одним кодом. Только stdlib: модуль зовёт хук, тяжёлые модули Атласа он не импортирует.
Public API: REQUIRED, TAILS, is_none, lint, section, violations.
Stability: lite
"""

from __future__ import annotations

import re

__all__ = ["REQUIRED", "TAILS", "is_none", "lint", "section", "violations"]

REQUIRED = ("Сделано", "Осталось", "Не проверено", "Файлы", "SHA", "Инъекции", "Кому передано")
TAILS = ("Осталось", "Не проверено", "Для следующего брифа")


def section(lines: list[str], title: str) -> tuple[str, list[str]] | None:
    """(маркер как в файле, тело раздела `title`); None — раздела нет. Выигрывает первая найденная форма.

    `## T` (строка после rstrip): тело — до следующей строки `## `, непустые строки после strip. Абзац `**T:**` или
    `**T.**` (строка после strip НАЧИНАЕТСЯ с маркера; в середине строки маркер — не раздел): тело — одна строка из
    остатка и следующих строк до пустой строки или строки на `**`; пустой остаток и пустые строки дают `[]`.
    Конец строки CRLF и LF не различаются: каждая строка проходит rstrip/strip.
    """
    heading = f"## {title}"
    paragraphs = (f"**{title}:**", f"**{title}.**")
    for i, line in enumerate(lines):
        if line.rstrip() == heading:
            body = []
            for nxt in lines[i + 1 :]:
                if nxt.startswith("## "):
                    break
                body.append(nxt.strip())
            return heading, [b for b in body if b]
        text = line.strip()
        marker = next((m for m in paragraphs if text.startswith(m)), None)
        if marker:
            body = [text[len(marker) :].strip()]
            for nxt in lines[i + 1 :]:
                if not nxt.strip() or nxt.strip().startswith("**"):
                    break
                body.append(nxt.strip())
            return marker, [" ".join(b for b in body if b)] if any(body) else []
    return None


def is_none(body: list[str]) -> bool:
    """Тело из одного «нет» (`нет` или `- нет`): раздел заявлен пустым."""
    return len(body) == 1 and re.sub(r"^[-*]\s+", "", body[0]) == "нет"


def violations(text: str) -> list[tuple[str, str]]:
    """(раздел REQUIRED, сообщение) на каждое нарушение, в порядке REQUIRED."""
    lines = text.split("\n")
    out: list[tuple[str, str]] = []
    for title in REQUIRED:
        found = section(lines, title)
        if found is None:
            out.append((title, f"нет раздела «## {title}»"))
        elif found[0] != f"## {title}":
            out.append((title, f"раздел «{title}» абзацем «{found[0]}», нужен «## {title}»"))
        elif not found[1]:
            out.append((title, f"пустой раздел «## {title}»: пишут «нет»"))
        elif title == "Не проверено" and is_none(found[1]):
            out.append((title, "«## Не проверено» не бывает «нет»"))
    return out


def lint(text: str) -> list[str]:
    """Сообщения `violations` по одной строке на раздел; пусто — итог по форме."""
    return [message for _, message in violations(text)]
