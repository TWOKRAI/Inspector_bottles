"""Отчёт стенд-гейта: строки stdout и Markdown-файл ``<out-dir>/<host>_<дата>_<время>.md`` (Task 5.6)."""

from __future__ import annotations

import socket
import time
from pathlib import Path
from typing import Iterable

from .analyze import CaseResult


def stdout_lines(results: Iterable[CaseResult]) -> list[str]:
    """Строки для stdout: заголовок кейса, затем ``PASS|FAIL|REPORT <имя>: <факт> vs <порог>``."""
    lines: list[str] = []
    for res in results:
        lines.append(f"== {res.label} (case {res.case})")
        lines.extend(c.line() for c in res.checks)
    return lines


def _unique_path(out_dir: Path, host: str, now: float) -> Path:
    stamp = time.strftime("%Y-%m-%d_%H%M%S", time.localtime(now))
    path = out_dir / f"{host}_{stamp}.md"
    n = 1
    while path.exists():  # второй прогон в ту же секунду не затирает первый
        path = out_dir / f"{host}_{stamp}_{n}.md"
        n += 1
    return path


def write_report(
    results: list[CaseResult],
    out_dir: Path,
    *,
    exit_code: int,
    command: str = "",
    host: str | None = None,
    now: float | None = None,
) -> Path:
    """Записать Markdown-отчёт; вернуть путь. Каталог создаётся, существующий файл не затирается."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    now = time.time() if now is None else now
    host = host or socket.gethostname()
    path = _unique_path(out_dir, host, now)
    verdict = {0: "все пороги зелёные", 1: "нарушен хотя бы один порог"}.get(exit_code, "сбой прогона")
    out = [
        "# Стенд-гейт фазы 5",
        "",
        f"- хост: `{host}`; время: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now))}",
        f"- команда: `{command}`" if command else "- команда: —",
        f"- код выхода: **{exit_code}** ({verdict})",
        "",
    ]
    for res in results:
        out += [f"## {res.label} — кейс {res.case}", "", "| Статус | Порог | Факт | Граница |", "|---|---|---|---|"]
        for c in res.checks:
            out.append(f"| {c.status} | {c.name} | {c.fact} | {c.threshold} |")
        out += ["", "Числа без порога:", ""]
        out += [f"- {k}: {v}" for k, v in res.numbers.items()]
        out.append("")
    path.write_text("\n".join(out), encoding="utf-8")
    return path
