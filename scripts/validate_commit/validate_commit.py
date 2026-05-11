#!/usr/bin/env python3
"""Валидатор commit-сообщений Inspector_bottles.

Проверяет:
1. Subject в формате Conventional Commits: `<type>(<scope>): <subject>`
2. Subject ≤ 72 символа.
3. Между subject и body — пустая строка.
4. Обязательные trailers: `Why:` и `Layer:` (с допустимыми значениями).
5. Опциональные trailers (если есть) — корректный формат: `Risk:`, `Reversible:`, `Tested:`, `Refs:`, `Rejected:`.

Запуск:
    python scripts/validate_commit/validate_commit.py <path-to-commit-msg-file>
    git log -1 --format=%B | python scripts/validate_commit/validate_commit.py -

Используется как git commit-msg hook (см. scripts/validate_commit/install_hook.sh).
Exit 0 — OK, exit 1 — ошибка.

Игнорируются: merge-коммиты (Merge ...), revert-коммиты, fixup!/squash!, пустые
сообщения. Это сделано осознанно — git/rebase должны работать без трения.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ────────────────────────── Конфигурация ──────────────────────────

ALLOWED_TYPES = {
    "feat", "fix", "refactor", "docs", "test",
    "chore", "perf", "build", "ci", "style", "revert",
}

ALLOWED_LAYERS = {
    "framework", "services", "plugins", "prototype",
    "docs", "scripts", "tests", "infra", "mixed",
}

ALLOWED_RISK = {"low", "medium", "high"}
ALLOWED_REVERSIBLE = {"yes", "no", "migration-needed"}

SUBJECT_RE = re.compile(
    r"^(?P<type>[a-z]+)(?:\((?P<scope>[a-z0-9_\-/,\s]+)\))?(?P<breaking>!)?: (?P<subject>.+)$"
)
TRAILER_RE = re.compile(r"^([A-Z][A-Za-z\-]*): (.+)$")

REQUIRED_TRAILERS = {"Why", "Layer"}
KNOWN_TRAILERS = REQUIRED_TRAILERS | {
    "Refs", "Risk", "Reversible", "Tested", "Rejected",
    "Co-Authored-By", "Signed-off-by", "Reviewed-by",
}

SKIP_PREFIXES = ("Merge ", "Revert ", "fixup!", "squash!", "amend!")
SUBJECT_MAX_LEN = 72


# ────────────────────────── Структуры ──────────────────────────

@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


# ────────────────────────── Парсинг ──────────────────────────

def parse_message(text: str) -> tuple[str, list[str], dict[str, list[str]]]:
    """Вернуть (subject, body_lines, trailers).

    Логика: разбиваем на параграфы (по пустым строкам). Идём с конца — пока
    последний параграф состоит ИСКЛЮЧИТЕЛЬНО из trailer-строк, считаем его
    trailer-блоком. Это позволяет иметь несколько trailer-параграфов
    (например, business-trailers + отдельный Co-Authored-By внизу).

    trailers — dict[key -> list[values]] (один ключ может встречаться многократно).
    """
    # Убираем git-комментарии (строки `#...`) и хвостовые пустые.
    lines = [ln for ln in text.splitlines() if not ln.startswith("#")]
    while lines and not lines[-1].strip():
        lines.pop()

    if not lines:
        return "", [], {}

    subject = lines[0]
    rest = lines[1:]
    # Убираем ведущую пустую строку (между subject и body)
    if rest and not rest[0].strip():
        rest = rest[1:]

    # Разбиваем на параграфы по пустым строкам.
    paragraphs: list[list[str]] = []
    current: list[str] = []
    for ln in rest:
        if not ln.strip():
            if current:
                paragraphs.append(current)
                current = []
        else:
            current.append(ln)
    if current:
        paragraphs.append(current)

    # С конца: пока последний параграф полностью trailer-only — это trailer-блок.
    trailers: dict[str, list[str]] = {}
    while paragraphs:
        last = paragraphs[-1]
        if all(TRAILER_RE.match(line) for line in last):
            for line in last:
                m = TRAILER_RE.match(line)
                if m:
                    key, val = m.group(1), m.group(2).strip()
                    trailers.setdefault(key, []).append(val)
            paragraphs.pop()
        else:
            break

    # Остатки склеиваем обратно через пустую строку для body
    body: list[str] = []
    for i, p in enumerate(paragraphs):
        if i > 0:
            body.append("")
        body.extend(p)

    return subject, body, trailers


# ────────────────────────── Валидация ──────────────────────────

def validate(text: str) -> ValidationResult:
    result = ValidationResult()
    text = text.strip()

    if not text:
        result.errors.append("Пустое commit-сообщение")
        return result

    first_line = text.splitlines()[0]
    if any(first_line.startswith(p) for p in SKIP_PREFIXES):
        return result  # merge/revert/fixup — не валидируем

    subject, body, trailers = parse_message(text)

    # 1. Subject формат
    if not subject:
        result.errors.append("Пустой subject (первая строка)")
        return result

    if len(subject) > SUBJECT_MAX_LEN:
        result.warnings.append(
            f"Subject длиннее {SUBJECT_MAX_LEN} символов ({len(subject)}). "
            f"Сократи: «{subject[:60]}…»"
        )

    m = SUBJECT_RE.match(subject)
    if not m:
        result.errors.append(
            f"Subject не в Conventional Commits формате.\n"
            f"  Получено: «{subject}»\n"
            f"  Ожидается: <type>(<scope>): <description>\n"
            f"  Пример: feat(auth): добавить wildcard в has_permission"
        )
        return result

    t = m.group("type")
    if t not in ALLOWED_TYPES:
        result.errors.append(
            f"Неизвестный type «{t}». Разрешено: {sorted(ALLOWED_TYPES)}"
        )

    # 2. Пустая строка между subject и body (если body есть)
    full_lines = [ln for ln in text.splitlines() if not ln.startswith("#")]
    if len(full_lines) >= 2 and full_lines[1].strip():
        result.errors.append(
            "Между subject и body должна быть пустая строка"
        )

    # 3. Обязательные trailers
    missing = REQUIRED_TRAILERS - set(trailers.keys())
    if missing:
        result.errors.append(
            f"Отсутствуют обязательные trailers: {sorted(missing)}.\n"
            f"  Добавь в конец сообщения (после пустой строки):\n"
            f"    Why: одна строка про мотивацию\n"
            f"    Layer: framework | services | plugins | prototype | docs | scripts | tests"
        )

    # 4. Валидация значений trailer'ов
    if "Layer" in trailers:
        for val in trailers["Layer"]:
            layers = {x.strip() for x in val.split(",") if x.strip()}
            unknown = layers - ALLOWED_LAYERS
            if unknown:
                result.errors.append(
                    f"Layer: неизвестные значения {sorted(unknown)}. "
                    f"Разрешено: {sorted(ALLOWED_LAYERS)}"
                )

    if "Risk" in trailers:
        for val in trailers["Risk"]:
            # Формат: "<level> — пояснение" или просто "<level>"
            level = val.split("—")[0].split("-")[0].strip().lower()
            if level not in ALLOWED_RISK:
                result.warnings.append(
                    f"Risk: «{val}». Ожидается начало с low/medium/high"
                )

    if "Reversible" in trailers:
        for val in trailers["Reversible"]:
            level = val.split("—")[0].strip().lower()
            if level not in ALLOWED_REVERSIBLE:
                result.warnings.append(
                    f"Reversible: «{val}». Ожидается: yes | no | migration-needed"
                )

    # 5. Неизвестные trailers — warning (не блокируем, расширяемо)
    for key in trailers:
        if key not in KNOWN_TRAILERS:
            result.warnings.append(
                f"Неизвестный trailer «{key}:». "
                f"Известные: {sorted(KNOWN_TRAILERS)}"
            )

    if "Why" in trailers:
        for val in trailers["Why"]:
            if len(val) < 5:
                result.warnings.append(
                    f"Why: слишком кратко («{val}»). Опиши мотивацию хотя бы одной фразой"
                )

    return result


# ────────────────────────── CLI ──────────────────────────

def main(argv: list[str]) -> int:
    if len(argv) != 2:
        sys.stderr.write(
            "Usage: validate_commit.py <file>\n"
            "       echo '...' | validate_commit.py -\n"
        )
        return 2

    src = argv[1]
    text = sys.stdin.read() if src == "-" else Path(src).read_text(encoding="utf-8")

    result = validate(text)

    if result.warnings:
        sys.stderr.write("⚠️  Warnings:\n")
        for w in result.warnings:
            sys.stderr.write(f"  • {w}\n")

    if result.errors:
        sys.stderr.write("\n❌ Commit-сообщение не валидно:\n")
        for e in result.errors:
            sys.stderr.write(f"  • {e}\n")
        sys.stderr.write(
            "\nШаблон: .gitmessage  •  Гайд: docs/claude/COMMIT_GUIDE.md\n"
            "Bypass (только для merge/rebase): git commit --no-verify\n"
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
