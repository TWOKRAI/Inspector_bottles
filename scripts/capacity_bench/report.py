"""Отчёт бенча: `<host>_<YYYY-MM-DD>.md` (для людей) и `.json` (result как есть)."""

from __future__ import annotations

import datetime
import json
import re
from pathlib import Path

UNRELIABLE = "CPU-числа на этой машине ненадёжны"
TESTS_FAILED = "сборка не прошла тесты"

_COLUMNS = (
    ("ext_cores", "ядра снаружи"),
    ("inner_cores", "ядра изнутри"),
    ("hz", "Гц"),
    ("queue_wait_ms", "queue_wait_ms"),
    ("transport_ms", "transport_ms"),
    ("pacer_late", "pacer_late"),
    ("plugin_ms", "plugin_ms"),
    ("shm", "shm"),
)


def _fmt(value, digits: int = 2) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    if isinstance(value, dict):
        return ", ".join(f"{k}={_fmt(v)}" for k, v in value.items()) or "—"
    return str(value)


def _passport_md(passport: dict) -> list[str]:
    lines = ["## Паспорт", "", "| поле | значение |", "|---|---|"]
    lines += [f"| {k} | {_fmt(v)} |" for k, v in passport.items()]
    return lines


def _selfcheck_md(selfcheck: dict) -> list[str]:
    ok = selfcheck.get("ok")
    lines = [
        "## Самопроверка часов CPU",
        "",
        f"Busy-цикл на одном ядре: измерено {_fmt(selfcheck.get('measured'), 3)} ядра (ожидается 1.0), "
        f"метод `{selfcheck.get('method')}`, {'ок' if ok else 'ОТКЛОНЕНИЕ'}.",
    ]
    if not ok:
        lines += ["", f"**{UNRELIABLE}** — сверять числа с другими машинами нельзя."]
    return lines


def _tests_md(tests: dict | None) -> list[str]:
    if tests is None:
        return []
    lines = [
        "## Тесты",
        "",
        f"rc={tests.get('rc')}, passed={tests.get('passed')}, failed={tests.get('failed')}, "
        f"{_fmt(tests.get('duration_s'), 1)} с.",
    ]
    if tests.get("rc") != 0:
        lines += ["", f"**{TESTS_FAILED}** — замер ниже снят на непроверенной сборке."]
    return lines


def _case_md(case: dict) -> list[str]:
    head = f"### {case.get('height')}p @ {case.get('fps')} fps, {case.get('secs')} с — {case.get('tree')}"
    lines = [
        head,
        "",
        f"sha `{case.get('sha')}`, сумма ядер снаружи: {_fmt(case.get('total_ext_cores'))}",
        "",
        "| процесс | " + " | ".join(title for _, title in _COLUMNS) + " |",
        "|---|" + "---|" * len(_COLUMNS),
    ]
    for name, fields in (case.get("processes") or {}).items():
        lines.append(f"| {name} | " + " | ".join(_fmt(fields.get(key)) for key, _ in _COLUMNS) + " |")
    return lines


def _markdown(result: dict) -> str:
    passport = result.get("passport") or {}
    blocks = [
        [f"# Бенч ёмкости — {passport.get('host')}", "", f"Профиль: `{result.get('profile')}`."],
        _passport_md(passport),
        _selfcheck_md(result.get("selfcheck") or {}),
        _tests_md(result.get("tests")),
    ]
    cases = result.get("cases") or []
    if cases:
        blocks.append(["## Матрица стенда"])
        blocks += [_case_md(c) for c in cases]
    else:
        blocks.append(["## Матрица стенда", "", "Кейсов нет (dry-run или пустой профиль)."])
    return "\n\n".join("\n".join(b) for b in blocks if b) + "\n"


def _free_stem(out_dir: Path, stem: str) -> str:
    """`stem`, а при занятости `stem_2`, `stem_3`… — старый отчёт не перезаписывается."""
    candidate, n = stem, 1
    while (out_dir / f"{candidate}.md").exists() or (out_dir / f"{candidate}.json").exists():
        n += 1
        candidate = f"{stem}_{n}"
    return candidate


def write_report(result: dict, out_dir: Path) -> tuple[Path, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    host = re.sub(r"[^\w.-]", "_", str((result.get("passport") or {}).get("host") or "unknown"))
    stem = _free_stem(out_dir, f"{host}_{datetime.date.today().isoformat()}")
    md_path, json_path = out_dir / f"{stem}.md", out_dir / f"{stem}.json"
    md_path.write_text(_markdown(result), encoding="utf-8")
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return md_path, json_path
