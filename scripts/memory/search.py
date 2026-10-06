"""Поиск по урокам памяти main-checkout:
`python scripts/memory/search.py [WORD...] [--module M] [--mechanism X] [--role R] [--limit N] [--list]`.

Контракт — plans/2026-10-04_atlas/tasks/2.4g.md, раздел «2.4g.1» и Р1/Р4. Строка вывода:
`<абсолютный путь> — <description>`; нет совпадений — ровно `none`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import _lessons

DEFAULT_LIMIT = 8


def _module_matches(values: list[str], wanted: str) -> bool:
    """Точное совпадение или префикс до `/`: `frontend_module` находит `frontend_module/widgets`."""
    return any(v == wanted or v.startswith(wanted + "/") for v in values)


def _matches_filters(fm: dict[str, list[str]], args: argparse.Namespace) -> bool:
    if args.module and not _module_matches(fm["module"], args.module):
        return False
    if args.mechanism and args.mechanism not in fm["mechanism"]:
        return False
    if args.role and args.role not in fm["role"]:
        return False
    return True


def _haystack(path: Path, fm: dict[str, list[str]]) -> str:
    parts = [path.stem, *fm["name"], *fm["description"], *fm["module"], *fm["mechanism"]]
    return "\n".join(parts).lower()


def search(root: Path, args: argparse.Namespace) -> list[tuple[Path, str]]:
    words = [w.lower() for w in args.words]
    ranked: list[tuple[int, str, Path, str]] = []
    for path in _lessons.iter_lessons(root / _lessons.MEMORY_REL):
        fm = _lessons.read_lesson(path)
        if not fm:
            fm = {k: [] for k in _lessons.KEYS}  # без frontmatter: ищется только по имени файла
        if not _matches_filters(fm, args):
            continue
        hay = _haystack(path, fm)
        rank = sum(1 for w in words if w in hay)
        if words and rank == 0:
            continue
        ranked.append((-rank, path.name, path, " ".join(fm["description"])))
    ranked.sort(key=lambda r: (r[0], r[1]))
    hits = [(path, desc) for _, _, path, desc in ranked]
    return hits if args.list else hits[: args.limit]


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Search lesson memory of the main checkout.")
    parser.add_argument("words", nargs="*", metavar="WORD")
    parser.add_argument("--module")
    parser.add_argument("--mechanism")
    parser.add_argument("--role")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--list", action="store_true", help="print all lessons, ignore --limit")
    parser.add_argument("--root", type=Path, default=None, help="repo root (default: main checkout)")
    args = parser.parse_args(argv)
    if not (args.words or args.module or args.mechanism or args.role or args.list):
        parser.error("need a WORD, a filter or --list")  # exit 2

    root = (args.root or _lessons.main_checkout_root()).resolve()
    hits = search(root, args)
    if not hits:
        print("none")
        return 0
    for path, desc in hits:
        print(f"{path.as_posix()} — {desc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
