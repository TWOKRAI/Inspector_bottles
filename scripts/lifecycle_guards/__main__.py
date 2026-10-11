"""CLI стражей жизненного цикла: ``python -m scripts.lifecycle_guards check [--root PATH] [--only g2,g6,g10]``.

Код возврата: 0 при нуле findings, иначе 1. Здесь же ``run_all`` — им пользуется и ``scripts/validate.py``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from scripts.lifecycle_guards import tables
from scripts.lifecycle_guards.g2 import check_g2
from scripts.lifecycle_guards.g6 import check_g6
from scripts.lifecycle_guards.g10 import check_g10
from scripts.lifecycle_guards.tables import Finding

GUARDS = ("g2", "g6", "g10")


def has_repo_tables(root: Path) -> bool:
    """Таблицы описывают наше дерево: на чужом корне (без ``multiprocess_framework/modules``) они пусты.

    Иначе каждая строка таблицы была бы «гнилой» на любом постороннем каталоге.
    """
    return (root / "multiprocess_framework" / "modules").is_dir()


def run_all(root: Path, only: frozenset[str] = frozenset(GUARDS)) -> list[Finding]:
    real = has_repo_tables(root)
    findings: list[Finding] = []
    if "g2" in only:
        findings += check_g2(root, tables.PUBLISHERS if real else [])
    if "g6" in only:
        findings += check_g6(root, tables.ALLOWLIST if real else {})
    if "g10" in only:
        findings += check_g10(root, tables.SHIMS if real else {})
    return findings


def format_finding(f: Finding) -> str:
    return f"{f.guard} {f.rule} {f.path}:{f.line} — {f.message}"


def summary_line(findings: list[Finding], root: Path) -> str:
    by_guard = {g: sum(1 for f in findings if f.guard == g) for g in ("G2", "G6", "G10")}
    real = has_repo_tables(root)
    pending = sum(1 for p in tables.PUBLISHERS if p.status.startswith("pending:")) if real else 0
    entries = len(tables.ALLOWLIST) if real else 0
    return (
        f"lifecycle-guards: {len(findings)} findings "
        f"(G2 {by_guard['G2']}, G6 {by_guard['G6']}, G10 {by_guard['G10']}); "
        f"G2 pending: {pending}; allowlist: {entries} entries"
    )


def _parse_only(value: str) -> frozenset[str]:
    names = frozenset(part.strip().lower() for part in value.split(",") if part.strip())
    unknown = names - set(GUARDS)
    if unknown or not names:
        raise argparse.ArgumentTypeError(f"--only: ожидается список из {','.join(GUARDS)}, получено {value!r}")
    return names


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.lifecycle_guards")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="статические стражи G2, G6, G10")
    check.add_argument("--root", type=Path, default=tables.REPO_ROOT, help="корень дерева (по умолчанию репозиторий)")
    check.add_argument("--only", type=_parse_only, default=frozenset(GUARDS), help="g2,g6,g10 (по умолчанию все)")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    root = args.root.resolve()
    findings = run_all(root, args.only)
    for f in findings:
        print(format_finding(f))
    if not has_repo_tables(root):
        print("lifecycle-guards: корень без multiprocess_framework/modules — таблицы репозитория не применяются")
    print(summary_line(findings, root))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
