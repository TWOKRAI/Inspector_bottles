"""
Одноразовая/повторяемая пересборка DECISIONS.md: сортировка ADR по номеру,
исправление дубля номера, раздел актуальных и устаревших.

Запуск из корня проекта: python scripts/reorganize_decisions.py
"""

from __future__ import annotations

import re
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DECISIONS = BASE / "multiprocess_framework" / "DECISIONS.md"


def split_adrs(text: str) -> tuple[str, list[tuple[int, str]]]:
    m = re.search(r"\n(?=## ADR-\d+:)", text)
    if not m:
        raise ValueError("Не найдено ни одного ADR")
    header = text[: m.start()].strip()
    body = text[m.start() + 1 :]
    raw_blocks = re.split(r"\n(?=## ADR-\d+:)", body)
    blocks: list[tuple[int, str]] = []
    seen_028_shared = False
    for raw in raw_blocks:
        raw = raw.strip()
        if not raw:
            continue
        m2 = re.match(r"^## ADR-(\d+):\s*(.+)$", raw, re.MULTILINE)
        if not m2:
            continue
        num = int(m2.group(1))
        title_first = m2.group(2).split("\n", 1)[0].strip()
        # Дубль ADR-028: второй блок — «Memory config…»
        if num == 28 and "Memory config" in title_first:
            num = 110
            raw = re.sub(r"^## ADR-028:", "## ADR-110:", raw, count=1)
            if "- Примечание: номер **ADR-110**" not in raw:
                raw = raw.replace(
                    "- Дата: 2026-03-16",
                    "- Дата: 2026-03-16\n- Примечание: номер **ADR-110** присвоен при рефакторинге журнала (раньше ошибочно дублировался **ADR-028**).",
                    1,
                )
        blocks.append((num, raw))
    blocks.sort(key=lambda x: x[0])
    return header, blocks


def is_obsolete(block: str) -> bool:
    return bool(re.search(r"^- Статус:\s*устарело\s*$", block, re.MULTILINE))


def main() -> None:
    text = DECISIONS.read_text(encoding="utf-8")
    header, blocks = split_adrs(text)

    active = [(n, b) for n, b in blocks if not is_obsolete(b)]
    obsolete = [(n, b) for n, b in blocks if is_obsolete(b)]

    lines: list[str] = []
    lines.append("# DECISIONS.md — Журнал архитектурных решений")
    lines.append("")
    lines.append(
        "Записи отсортированы по номеру **ADR-NNN**. Актуальные правила — в разделе «Принято»; "
        "заменённые решения — в «Устарело» (полный текст сохранён для истории)."
    )
    lines.append("")
    lines.append("Формат одной записи:")
    lines.append("```")
    lines.append("## ADR-NNN: Заголовок")
    lines.append("- Дата: YYYY-MM-DD")
    lines.append("- Статус: принято | отклонено | устарело")
    lines.append("- Контекст: …")
    lines.append("- Решение: …")
    lines.append("- Причина: …")
    lines.append("- Отклонённые альтернативы: …")
    lines.append("```")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Оглавление (по номеру)")
    lines.append("")
    for num, block in blocks:
        title_line = block.split("\n", 1)[0]
        lines.append(f"- {title_line}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Принято (актуальные ADR)")
    lines.append("")
    for num, block in active:
        lines.append(block)
        lines.append("")
        lines.append("---")
        lines.append("")
    # убрать лишний разделитель перед «Устарело»
    while lines and lines[-1] == "":
        lines.pop()
    while lines and lines[-1] == "---":
        lines.pop()
        if lines and lines[-1] == "":
            lines.pop()
    lines.append("")
    lines.append("## Устарело")
    lines.append("")
    lines.append(
        "Ниже — решения, явно помеченные как устаревшие; обычно указан преемник (**Суперсед**)."
    )
    lines.append("")
    for num, block in obsolete:
        lines.append(block)
        lines.append("")
        lines.append("---")
        lines.append("")

    out = "\n".join(lines).rstrip() + "\n"
    DECISIONS.write_text(out, encoding="utf-8")
    print(f"OK: {DECISIONS} — ADR: всего {len(blocks)}, принято {len(active)}, устарело {len(obsolete)}")


if __name__ == "__main__":
    main()
