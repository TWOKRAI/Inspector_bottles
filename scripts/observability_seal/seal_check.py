# -*- coding: utf-8 -*-
"""Проверка пломбы (задача 2.V1 плана ``observability-unified-routing``).

Что доказывает
--------------
Каждая запись, ПРОШЕДШАЯ ГЕЙТ, получает в точке эмиссии сквозной номер в
пределах процесса (``LoggerCore.log`` → ``LogRecord.seq``). Номер доезжает до
файла префиксом строки ``#<seq> `` (``SealFormatter``) и до
``errors_floor.jsonl`` полем ``seq``.

Отсюда свойство, которое считается ЗДЕСЬ, по байтам на диске:

    объединение номеров по всем файлам процесса непрерывно от min до max.

Дырка = запись прошла гейт, но не легла ни в один файл, — то есть потеря.
Счётчики самого логгера при этом не спрашиваются вовсе: в Ф0.9 счётчик
``errors_to_floor`` означал «передано», а не «записано», и верить его отчёту о
себе больше нельзя.

Чего проверка НЕ доказывает — названо, а не умолчано
----------------------------------------------------
1. **Предусловие: у каждой записи окна есть хотя бы один из проверяемых файлов
   в приёмниках.** Запись, ушедшая ТОЛЬКО в консоль или только в IPC-канал GUI,
   даст дырку, не будучи потерей. В дефолтном конфиге предусловие держится
   (у каждого включённого скоупа в списке каналов есть файловый) и закреплено
   тестом ``test_seal.py::test_default_scopes_all_have_file_channel``; в чужом
   конфиге — обязано проверяться отдельно. Полный учёт с отклонёнными и
   потерянными — задача 2.V3, здесь его нет.
2. **Ротация.** ``foo.log.1``/``foo.log.1.gz`` читаются, только если переданы
   явно или лежат в проверяемом каталоге; вытесненный ретеншеном бэкап уносит
   свои номера с собой, и это выглядит как дырка. Поэтому окно проверки — от
   старта процесса до первой ротации, либо каталог целиком.
3. **Подмену полей записи** (текст, уровень) — пломба про наличие, а не про
   содержимое. Это задача 2.V4.

Правила для самого проверяющего (шапка Ф2.V плана)
--------------------------------------------------
* радикально проще проверяемого: чтение, регулярка, арифметика на множестве —
  ни конфига, ни локов, ни батчинга, ни импорта фреймворка;
* не зависит от логгера ни в чём, включая отчёт о собственном сбое: вывод в
  ``stderr`` и в отдельный файл;
* **«не смог проверить» ≠ «проверил, всё хорошо»** — это разные коды возврата.

Коды возврата
-------------
``0`` — непрерывно; ``1`` — найдены дырки/дубликаты/записи без пломбы;
``2`` — проверить не удалось (нечего читать, файл нечитаем, ни одной пломбы).
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Set, Tuple

#: Префикс пломбы в текстовой строке лога. Держать в согласии с
#: ``logger_module/channels/log_channel.py::SealFormatter`` — согласие
#: закреплено тестом, а не надеждой (``test_seal.py::test_prefix_matches_framework``).
SEAL_RE = re.compile(r"^#(\d+) ")

#: Запись, дошедшая до файла БЕЗ номера (создана мимо ``LoggerCore.log``).
#: Отдельный признак: «пломбы нет» обязано отличаться от «строка не разобрана».
UNSEALED_RE = re.compile(r"^#- ")

#: Имена, которые читаются как JSON Lines (пол ошибок пишет запись целиком).
JSONL_SUFFIXES = (".jsonl",)

#: Что берём из каталога по умолчанию.
DEFAULT_PATTERNS = ("*.log", "*.log.*", "*.jsonl")


@dataclass
class SealReport:
    """Результат проверки. Пустой список дырок ≠ успех — смотри ``verifiable``."""

    files_read: List[str] = field(default_factory=list)
    unreadable: List[Tuple[str, str]] = field(default_factory=list)
    sealed_lines: int = 0
    unsealed_lines: int = 0
    seqs: Set[int] = field(default_factory=set)
    duplicates: Dict[int, int] = field(default_factory=dict)
    holes: List[int] = field(default_factory=list)

    @property
    def verifiable(self) -> bool:
        """Была ли проверка вообще возможна.

        ``False`` — читать оказалось нечего или ни одной пломбы не нашлось.
        Возвращать в этом случае «дырок нет» было бы четвёртым проглоченным
        сбоем: тишина оракула выглядела бы как его одобрение.
        """
        return bool(self.files_read) and self.sealed_lines > 0

    @property
    def ok(self) -> bool:
        return self.verifiable and not self.holes and not self.duplicates and not self.unsealed_lines

    @property
    def exit_code(self) -> int:
        if not self.verifiable:
            return 2
        return 0 if self.ok else 1

    def render(self) -> str:
        """Текст отчёта. Одна функция вывода — и для файла, и для stderr."""
        lines = ["ПЛОМБА 2.V1 — проверка непрерывности номеров на диске", ""]
        lines.append(f"файлов прочитано : {len(self.files_read)}")
        for path in self.files_read:
            lines.append(f"    {path}")
        if self.unreadable:
            lines.append(f"НЕ ПРОЧИТАНО     : {len(self.unreadable)}")
            for path, why in self.unreadable:
                lines.append(f"    {path}: {why}")
        lines.append(f"строк с пломбой  : {self.sealed_lines}")
        lines.append(f"строк без пломбы : {self.unsealed_lines}")

        if not self.verifiable:
            lines.append("")
            lines.append("ВЕРДИКТ: ПРОВЕРИТЬ НЕ УДАЛОСЬ.")
            if not self.files_read:
                lines.append("  Не прочитано ни одного файла — проверять нечего.")
            else:
                lines.append(
                    "  Ни одной пломбы не найдено. Файлы либо написаны до 2.V1, либо не логами этого фреймворка."
                )
            lines.append("  Это НЕ «всё хорошо». Код возврата 2.")
            return "\n".join(lines)

        lines.append(f"диапазон         : {min(self.seqs)}..{max(self.seqs)}")
        lines.append(f"дырок            : {len(self.holes)}")
        if self.holes:
            lines.append(f"    номера: {_compact(self.holes)}")
        lines.append(f"дубликатов       : {len(self.duplicates)}")
        if self.duplicates:
            shown = ", ".join(f"{seq}×{n}" for seq, n in sorted(self.duplicates.items())[:50])
            lines.append(f"    номера: {shown}")
        lines.append("")
        if self.ok:
            lines.append("ВЕРДИКТ: непрерывно — ни одна прошедшая гейт запись не потеряна.")
        else:
            lines.append("ВЕРДИКТ: ПОТЕРЯ. Перечисленные номера прошли гейт и не легли ни в один файл.")
        lines.append(
            "Предусловие (не проверяется здесь): у каждой записи окна есть хотя бы один "
            "из прочитанных файлов в приёмниках. Запись только в консоль/IPC даст дырку, "
            "не будучи потерей — полный учёт это задача 2.V3."
        )
        return "\n".join(lines)


def _compact(values: Sequence[int], limit: int = 200) -> str:
    """``[1,2,3,7]`` → ``1-3, 7``. Дырка в тысячу номеров должна читаться глазом."""
    if not values:
        return ""
    spans: List[Tuple[int, int]] = []
    start = prev = values[0]
    for value in values[1:]:
        if value == prev + 1:
            prev = value
            continue
        spans.append((start, prev))
        start = prev = value
    spans.append((start, prev))
    text = ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in spans[:limit])
    if len(spans) > limit:
        text += f", … (+{len(spans) - limit} диапазонов)"
    return text


def _open_text(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return path.open("r", encoding="utf-8", errors="replace")


def _scan_file(path: Path, report: SealReport, counts: Dict[int, int]) -> None:
    """Прочитать один файл. Любой сбой — в ``unreadable``, а не в тишину."""
    is_jsonl = path.suffix in JSONL_SUFFIXES or path.name.endswith(".jsonl.gz")
    try:
        with _open_text(path) as handle:
            for line in handle:
                if is_jsonl:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        seq = int((json.loads(line) or {}).get("seq") or 0)
                    except Exception:  # noqa: BLE001 — битая строка это не пломба
                        report.unsealed_lines += 1
                        continue
                    if seq:
                        counts[seq] = counts.get(seq, 0) + 1
                        report.sealed_lines += 1
                    else:
                        report.unsealed_lines += 1
                    continue

                match = SEAL_RE.match(line)
                if match:
                    seq = int(match.group(1))
                    counts[seq] = counts.get(seq, 0) + 1
                    report.sealed_lines += 1
                elif UNSEALED_RE.match(line):
                    report.unsealed_lines += 1
    except Exception as exc:  # noqa: BLE001 — «не смог» обязано быть слышно
        report.unreadable.append((str(path), f"{type(exc).__name__}: {exc}"))
        return
    report.files_read.append(str(path))


def collect_files(targets: Iterable[Path], patterns: Sequence[str] = DEFAULT_PATTERNS) -> List[Path]:
    """Развернуть аргументы в список файлов. Каталоги — рекурсивно."""
    found: List[Path] = []
    for target in targets:
        if target.is_dir():
            for pattern in patterns:
                found.extend(sorted(target.rglob(pattern)))
        elif target.exists():
            found.append(target)
    # Один и тот же файл мог прийти и явно, и из каталога.
    seen: Set[str] = set()
    unique: List[Path] = []
    for path in found:
        key = str(path.resolve())
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def check_seal(targets: Sequence[Path], patterns: Sequence[str] = DEFAULT_PATTERNS) -> SealReport:
    """Посчитать непрерывность номеров по файлам. Единственная точка правды тула."""
    report = SealReport()
    counts: Dict[int, int] = {}

    files = collect_files(targets, patterns)
    if not files:
        for target in targets:
            if not target.exists():
                report.unreadable.append((str(target), "не существует"))
        return report

    for path in files:
        _scan_file(path, report, counts)

    report.seqs = set(counts)
    report.duplicates = {seq: n for seq, n in counts.items() if n > 1}
    if report.seqs:
        low, high = min(report.seqs), max(report.seqs)
        report.holes = [seq for seq in range(low, high + 1) if seq not in report.seqs]
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="observability_seal",
        description=(
            "Проверка пломбы наблюдаемости (2.V1): читает логи С ДИСКА и ищет дырки "
            "в сквозной нумерации записей процесса. Счётчики логгера не спрашивает."
        ),
        epilog="Коды возврата: 0 — непрерывно; 1 — потеря; 2 — проверить не удалось.",
    )
    parser.add_argument("paths", nargs="+", type=Path, help="каталог логов процесса и/или отдельные файлы")
    parser.add_argument(
        "--pattern",
        action="append",
        default=None,
        help=f"маска файлов в каталоге (по умолчанию {' '.join(DEFAULT_PATTERNS)}); можно повторять",
    )
    parser.add_argument("--report", type=Path, default=None, help="записать отчёт ещё и в этот файл")
    args = parser.parse_args(argv)

    report = check_seal(args.paths, tuple(args.pattern) if args.pattern else DEFAULT_PATTERNS)
    text = report.render()

    # Вывод в stderr, а не в stdout: проверяющий не имеет права смешать свой
    # вердикт с данными, которые у него могут попросить в конвейере.
    print(text, file=sys.stderr)
    if args.report:
        try:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(text + "\n", encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            print(f"ОТЧЁТ НЕ ЗАПИСАН: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 2
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
