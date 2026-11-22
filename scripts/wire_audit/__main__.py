"""CLI аудита провода: ``python -m scripts.wire_audit --exchange … --layout … --registers … [--words …]``.

Читает файлы журналов, печатает таблицу PASS/FAIL по каждому ``CVT_JOB`` (stdout; при ``--out`` ещё и в файл).
Коды возврата: 0 — все PASS (допускается ``PASS~``); 1 — хотя бы один FAIL, включая ноль заданий при взятиях > 0;
2 — ошибка аргументов или «не поддержано»; 3 — файл обмена или диска не читается или пуст.
Тексты отказов кодов 2 и 3 идут в stderr и не содержат значений аргументов.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from scripts.wire_audit.commands import render_commands
from scripts.wire_audit.core import AuditError, audit, render

_ZONE_DEFAULT = "500"
_PICK_MARGIN_DEFAULT = "5"


class _Parser(argparse.ArgumentParser):
    """argparse печатает значение аргумента в тексте ошибки; здесь текст фиксированный, код 2."""

    def error(self, message: str) -> None:  # noqa: ARG002 - текст argparse содержит значения аргументов
        print("ошибка аргументов: см. --help", file=sys.stderr)
        raise SystemExit(2)


def _build_parser() -> argparse.ArgumentParser:
    p = _Parser(prog="python -m scripts.wire_audit", description=__doc__, allow_abbrev=False)
    p.add_argument("--exchange", required=True, help="журнал обмена robot_exchange.log")
    p.add_argument("--layout", required=True, help="журнал диска layout/messages.log")
    p.add_argument("--registers", required=True, help="JSON регистров укладки (word_layout)")
    p.add_argument("--words", help="слова заливок через запятую, по порядку появления в журнале диска")
    p.add_argument("--zone-max-mm", default=_ZONE_DEFAULT, help="радиус досягаемости, мм (умолчание 500)")
    p.add_argument(
        "--pick-margin-mm", default=_PICK_MARGIN_DEFAULT, help="запас за окном α для pick x/y, мм (умолчание 5)"
    )
    p.add_argument("--sim-objects", help="JSONL паспортов сима (столбец Б)")
    p.add_argument("--sim-journal", help="JSONL журнала сим-робота (третий наблюдатель)")
    p.add_argument("--out", help="файл для копии отчёта")
    return p


def _read(path: str, what: str, *, must_have_text: bool) -> str:
    """Текст файла; не читается или пуст — AuditError(3) без пути в тексте."""
    try:
        text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        raise AuditError(3, f"{what} не читается") from exc
    if must_have_text and not text.strip():
        raise AuditError(3, f"{what} пуст")
    return text


def _read_jsonl(path: str, what: str) -> list[dict]:
    """JSONL: строки, не разобранные как JSON-объект, пропускаются (остальное судья отбрасывает сам)."""
    items: list[dict] = []
    for line in _read(path, what, must_have_text=False).splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            items.append(item)
    return items


def _load_registers(path: str) -> dict:
    text = _read(path, "файл регистров", must_have_text=True)
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise AuditError(2, "файл регистров не JSON") from exc
    if not isinstance(data, dict):
        raise AuditError(2, "файл регистров не словарь")
    return data


def _non_negative(raw: str, flag: str) -> float:
    try:
        value = float(raw)
    except ValueError as exc:
        raise AuditError(2, f"{flag} не число") from exc
    if not math.isfinite(value) or value < 0:
        raise AuditError(2, f"{flag} вне допустимого диапазона")
    return value


_COMMANDS_FILE = "wire_commands.md"


def _run(ns: argparse.Namespace) -> tuple[int, str, str | None]:
    zone = _non_negative(ns.zone_max_mm, "--zone-max-mm")
    margin = _non_negative(ns.pick_margin_mm, "--pick-margin-mm")
    words = None if ns.words is None else [w.strip() for w in ns.words.split(",")]
    exchange = _read(ns.exchange, "журнал обмена", must_have_text=True)
    layout = _read(ns.layout, "журнал диска", must_have_text=True)
    registers = _load_registers(ns.registers)
    objects = _read_jsonl(ns.sim_objects, "файл паспортов сима") if ns.sim_objects else None
    journal = _read_jsonl(ns.sim_journal, "журнал сима") if ns.sim_journal else None
    result = audit(
        exchange,
        layout,
        registers,
        words=words,
        zone_max_mm=zone,
        pick_margin_mm=margin,
        sim_objects=objects,
        sim_journal=journal,
    )
    commands = render_commands(exchange, layout, registers, result, journal) if ns.out else None
    return result.exit_code, render(result, _COMMANDS_FILE if ns.out else None), commands


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ns = _build_parser().parse_args(argv)
    try:
        code, report, commands = _run(ns)
    except AuditError as exc:
        print(exc.message, file=sys.stderr)
        return exc.code
    sys.stdout.write(report)
    if ns.out:
        try:
            Path(ns.out).write_text(report, encoding="utf-8")
            if commands is not None:
                Path(ns.out).with_name(_COMMANDS_FILE).write_text(commands, encoding="utf-8")
        except OSError:
            print("отчёт не записан в --out", file=sys.stderr)
            return 2
    return code


if __name__ == "__main__":
    sys.exit(main())
