"""G10: потолок обёрток совместимости.

Маркер — подстрока ``lifecycle-shim:`` в КОММЕНТАРИИ производственного файла (строковый
литерал не считается). ``SHIMS`` — путь -> разрешённое число маркеров; сумма значений <= 1.
Найдено 0 — не нарушение. Предел: обёртка без маркера не видна.
"""

from __future__ import annotations

import io
import tokenize
from pathlib import Path

from scripts.lifecycle_guards.tables import SHIMS, Finding, production_files

MARKER = "lifecycle-shim:"
MAX_SHIMS = 1


def _marker_lines(text: str) -> list[int]:
    lines = []
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        if tok.type == tokenize.COMMENT and MARKER in tok.string:
            lines.append(tok.start[0])
    return lines


def check_g10(root: Path, allowed: dict[str, int] = SHIMS, files: list[tuple[str, str]] | None = None) -> list[Finding]:
    findings: list[Finding] = []

    if sum(allowed.values()) > MAX_SHIMS:
        findings.append(
            Finding(
                "G10",
                "table-sum",
                "scripts/lifecycle_guards/tables.py",
                0,
                f"сумма SHIMS {sum(allowed.values())} больше потолка {MAX_SHIMS}",
            )
        )

    for rel in sorted(allowed):
        if not (root / rel).is_file():
            findings.append(Finding("G10", "table-row", rel, 0, "запись гнилая: пути нет в дереве"))

    for rel, text in files if files is not None else production_files(root):
        if MARKER not in text:
            continue
        try:
            lines = _marker_lines(text)
        except (tokenize.TokenError, SyntaxError) as exc:
            findings.append(Finding("G10", "tokenize", rel, 1, f"файл с маркером не токенизируется: {exc}"))
            continue
        budget = allowed.get(rel, 0)
        for line in lines[budget:]:
            where = "в файле вне таблицы SHIMS" if budget == 0 else f"сверх разрешённых {budget}"
            findings.append(Finding("G10", "shim", rel, line, f"маркер {MARKER} {where}"))

    return sorted(findings, key=lambda f: (f.path, f.line, f.rule))
