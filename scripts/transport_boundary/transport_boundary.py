"""
Транспортный инвариант: прямой queue/SHM-транспорт — только внутри хаба.

Инвариант плана transport-router-hub (P4.3): единственный способ отправки между
компонентами — `router.send(message)`. Прямые низкоуровневые вызовы транспорта
(`queue_registry.send_to_queue`, `broadcast_message`, инстанцирование SHM-примитивов
RingBufferWriter/Reader/MemoryHandle) разрешены ТОЛЬКО внутри слоя-хаба
(`router_module/**`) и транспортной библиотеки (`shared_resources_module/**`).
Всё остальное обязано идти через `router.send`.

Ratchet-режим. На текущем коде живые нарушители (broadcast B7) перечислены в
секции `[[debt]]` конфига — они печатаются как `KNOWN DEBT`, но НЕ роняют чекер.
Любой НОВЫЙ прямой вызов вне allow/debt → exit 1. Удаление долгов — в P5
(см. plans/2026-05-31_transport-router-hub/plan.md, recon_p4.md).

Детектор — AST по имени вызываемого символа (call-site), а не текст/импорт:
sentrux так не умеет (его правила — import-boundaries между путями), а транспорт
зовут через атрибут `router_manager.queue_registry.send_to_queue(...)` без импорта.

Выход:
- exit 0 — новых нарушений нет (долги допускаются)
- exit 1 — есть нарушение вне allow/debt (для CI/pre-push)
- exit 2 — ошибка конфигурации/I-O (ничего не сканировалось)

Запуск:
    python scripts/transport_boundary/transport_boundary.py
    python scripts/transport_boundary/transport_boundary.py --format json
    python scripts/transport_boundary/transport_boundary.py --root multiprocess_framework
    python scripts/transport_boundary/transport_boundary.py --no-strict   # только отчёт

Inline-suppression (точечно, с обоснованием в комментарии рядом):
    qr.send_to_queue(...)  # transport-boundary: ignore
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import io
import json
import sys
import tomllib
import warnings
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG_PATH = Path(__file__).with_name("transport_boundary.toml")
INLINE_SUPPRESS = "transport-boundary: ignore"


@dataclass(frozen=True)
class DebtEntry:
    path: str  # glob по относительному posix-пути
    reason: str


@dataclass(frozen=True)
class Config:
    roots: tuple[str, ...]
    exclude_dirs: tuple[str, ...]
    exclude_paths: tuple[str, ...]
    forbidden_calls: frozenset[str]
    allow_paths: tuple[str, ...]
    debts: tuple[DebtEntry, ...]
    output_format: str
    strict: bool


def load_config(path: Path) -> Config:
    with path.open("rb") as f:
        raw = tomllib.load(f)
    scan = raw.get("scan", {})
    exc = raw.get("exclude", {})
    det = raw.get("detect", {})
    allow = raw.get("allow", {})
    out = raw.get("output", {})

    debts: list[DebtEntry] = []
    for d in raw.get("debt", []):
        p = d.get("path")
        if not p:
            continue
        debts.append(DebtEntry(path=str(p), reason=str(d.get("reason", ""))))

    return Config(
        roots=tuple(scan.get("roots", ["."])),
        exclude_dirs=tuple(exc.get("dirs", [])),
        exclude_paths=tuple(exc.get("path_patterns", [])),
        forbidden_calls=frozenset(det.get("forbidden_calls", [])),
        allow_paths=tuple(allow.get("paths", [])),
        debts=tuple(debts),
        output_format=str(out.get("format", "table")).lower(),
        strict=bool(out.get("strict", True)),
    )


# --------------------------------------------------------------------------- #
# Сканирование
# --------------------------------------------------------------------------- #

# Вердикт классификации находки.
VERDICT_VIOLATION = "violation"  # вне allow/debt → роняет чекер
VERDICT_DEBT = "debt"  # известный долг (P5) → печатается, не роняет
# (allow-находки не материализуются — легитимный транспорт внутри хаба)


@dataclass
class Finding:
    file: str
    line: int
    symbol: str
    verdict: str
    reason: str  # для debt — причина из конфига


def _call_name(node: ast.Call) -> str | None:
    """Имя вызываемого символа: `a.b.send_to_queue(...)` → 'send_to_queue',
    `RingBufferWriter(...)` → 'RingBufferWriter'."""
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _match_any(rel: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(rel, pat) for pat in patterns)


def _debt_for(rel: str, debts: tuple[DebtEntry, ...]) -> DebtEntry | None:
    for d in debts:
        if fnmatch.fnmatch(rel, d.path):
            return d
    return None


def iter_py_files(cfg: Config, base: Path):
    """Обходит .py-файлы под cfg.roots, уважая exclude."""
    for root_name in cfg.roots:
        root = (base / root_name).resolve()
        if not root.exists():
            continue
        stack = [root]
        while stack:
            current = stack.pop()
            try:
                entries = list(current.iterdir())
            except (PermissionError, OSError):
                continue
            for entry in entries:
                if entry.is_symlink():
                    continue
                if entry.is_dir():
                    if any(fnmatch.fnmatch(entry.name, pat) for pat in cfg.exclude_dirs):
                        continue
                    stack.append(entry)
                elif entry.is_file() and entry.suffix == ".py":
                    rel = entry.relative_to(base).as_posix()
                    if _match_any(rel, cfg.exclude_paths):
                        continue
                    yield entry, rel


def scan_file(path: Path, rel: str, cfg: Config) -> list[Finding]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    try:
        # Чужие файлы могут содержать invalid-escape и т.п. — глушим SyntaxWarning,
        # чтобы не засорять отчёт чекера предупреждениями не про транспорт.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return []

    # Строки с inline-suppression — пропускаем по номеру строки.
    suppressed = {i for i, line in enumerate(text.splitlines(), start=1) if INLINE_SUPPRESS in line}
    allowed = _match_any(rel, cfg.allow_paths)
    debt = _debt_for(rel, cfg.debts)

    findings: list[Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name is None or name not in cfg.forbidden_calls:
            continue
        if node.lineno in suppressed:
            continue
        if allowed:
            # Легитимный транспорт внутри хаба/библиотеки — не находка.
            continue
        if debt is not None:
            findings.append(Finding(rel, node.lineno, name, VERDICT_DEBT, debt.reason))
        else:
            findings.append(Finding(rel, node.lineno, name, VERDICT_VIOLATION, ""))
    return findings


# --------------------------------------------------------------------------- #
# Рендеринг
# --------------------------------------------------------------------------- #


def _render_block(title: str, rows: list[Finding]) -> str:
    if not rows:
        return ""
    out = io.StringIO()
    out.write(f"\n{title} ({len(rows)}):\n")
    width = max(len(f"{r.file}:{r.line}") for r in rows)
    for r in sorted(rows, key=lambda f: (f.file, f.line)):
        loc = f"{r.file}:{r.line}".ljust(width)
        suffix = f"  — {r.reason}" if r.reason else ""
        out.write(f"  {loc}  {r.symbol}{suffix}\n")
    return out.getvalue()


def render_table(violations: list[Finding], debts: list[Finding]) -> str:
    out = io.StringIO()
    out.write(_render_block("KNOWN DEBT (P5, не роняет)", debts))
    out.write(_render_block("VIOLATIONS (прямой транспорт вне хаба)", violations))
    if not violations and not debts:
        out.write("OK: прямого queue/SHM-транспорта вне хаба не найдено.\n")
    elif not violations:
        out.write("\nOK: новых нарушений нет (только известные долги P5).\n")
    else:
        out.write(
            "\nFAIL: транспорт в обход router.send — используйте router.send(message)\n"
            "или зарегистрируйте долг в transport_boundary.toml [[debt]] (только с ADR/планом).\n"
        )
    return out.getvalue()


def render_json(violations: list[Finding], debts: list[Finding]) -> str:
    return json.dumps(
        {
            "summary": {"violations": len(violations), "debts": len(debts)},
            "violations": [f.__dict__ for f in violations],
            "debts": [f.__dict__ for f in debts],
        },
        ensure_ascii=False,
        indent=2,
    )


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="transport_boundary",
        description="Инвариант: прямой queue/SHM-транспорт только внутри хаба (router_module/shared_resources_module).",
    )
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    p.add_argument("--root", type=str, default=None, help="Сканировать только один корень (override scan.roots).")
    p.add_argument("--format", choices=["table", "json"], default=None)
    p.add_argument("--no-strict", action="store_true", help="Не падать с exit 1 при нарушениях (только отчёт).")
    return p


def main(argv: list[str] | None = None) -> int:
    # Windows-консоль по умолчанию cp1251 — не кодирует '→'/'…' в отчёте.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    try:
        cfg = load_config(args.config)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    overrides: dict = {}
    if args.root is not None:
        overrides["roots"] = (args.root,)
    if args.format is not None:
        overrides["output_format"] = args.format
    if args.no_strict:
        overrides["strict"] = False
    if overrides:
        cfg = Config(**{**cfg.__dict__, **overrides})

    if not cfg.forbidden_calls:
        print("error: пустой detect.forbidden_calls в конфиге", file=sys.stderr)
        return 2

    base = Path(__file__).resolve().parent.parent.parent  # корень репо
    findings: list[Finding] = []
    scanned = 0
    for path, rel in iter_py_files(cfg, base):
        scanned += 1
        findings.extend(scan_file(path, rel, cfg))

    if scanned == 0:
        print("error: ни одного файла не просканировано (проверьте scan.roots)", file=sys.stderr)
        return 2

    violations = [f for f in findings if f.verdict == VERDICT_VIOLATION]
    debts = [f for f in findings if f.verdict == VERDICT_DEBT]

    if cfg.output_format == "json":
        sys.stdout.write(render_json(violations, debts))
    else:
        sys.stdout.write(render_table(violations, debts))

    if violations and cfg.strict:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
