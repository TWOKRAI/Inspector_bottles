"""
Универсальный счётчик файлов / строк / символов с TOML-конфигом.

Принципы:
- stdlib-only (Python 3.12+): tomllib, fnmatch, pathlib, argparse, dataclasses.
- Strategy для подсчёта по типу файла (Python / Markdown / Shell / Plain).
- Pruning исключений на уровне обхода (не читаем то, что отброшено).
- CLI-флаги перекрывают TOML.

Запуск:
    python scripts/code_stats/code_stats.py
    python scripts/code_stats/code_stats.py --root src
    python scripts/code_stats/code_stats.py --format json --group-by directory
    python scripts/code_stats/code_stats.py --config path/to/other.toml
"""

from __future__ import annotations

import argparse
import csv
import fnmatch
import io
import json
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator


# --------------------------------------------------------------------------- #
# Конфигурация
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ScanCfg:
    root: Path
    recursive: bool = True
    follow_symlinks: bool = False


@dataclass(frozen=True)
class FormatsCfg:
    include: frozenset[str] = field(default_factory=frozenset)  # пустой = все


@dataclass(frozen=True)
class ExcludeCfg:
    dirs: tuple[str, ...] = ()
    file_patterns: tuple[str, ...] = ()
    path_patterns: tuple[str, ...] = ()


@dataclass(frozen=True)
class CountCfg:
    blank_lines: bool = False
    comments: bool = True
    docstrings: bool = True
    chars: bool = True
    encoding: str = "utf-8"


@dataclass(frozen=True)
class OutputCfg:
    format: str = "table"  # table | json | csv
    group_by: str = "extension"  # extension | directory | none
    sort_by: str = "lines"  # lines | chars | files | name
    sort_order: str = "desc"  # desc | asc
    show_total: bool = True
    limit: int = 0


@dataclass(frozen=True)
class Config:
    scan: ScanCfg
    formats: FormatsCfg
    exclude: ExcludeCfg
    count: CountCfg
    output: OutputCfg


DEFAULT_CONFIG_PATH = Path(__file__).with_name("code_stats.toml")


def load_config(path: Path) -> Config:
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    with path.open("rb") as f:
        raw = tomllib.load(f)

    scan_raw = raw.get("scan", {})
    fmt_raw = raw.get("formats", {})
    excl_raw = raw.get("exclude", {})
    cnt_raw = raw.get("count", {})
    out_raw = raw.get("output", {})

    return Config(
        scan=ScanCfg(
            root=Path(scan_raw.get("root", ".")).expanduser(),
            recursive=bool(scan_raw.get("recursive", True)),
            follow_symlinks=bool(scan_raw.get("follow_symlinks", False)),
        ),
        formats=FormatsCfg(
            include=frozenset(ext.lower() for ext in fmt_raw.get("include", [])),
        ),
        exclude=ExcludeCfg(
            dirs=tuple(excl_raw.get("dirs", [])),
            file_patterns=tuple(excl_raw.get("file_patterns", [])),
            path_patterns=tuple(excl_raw.get("path_patterns", [])),
        ),
        count=CountCfg(
            blank_lines=bool(cnt_raw.get("blank_lines", False)),
            comments=bool(cnt_raw.get("comments", True)),
            docstrings=bool(cnt_raw.get("docstrings", True)),
            chars=bool(cnt_raw.get("chars", True)),
            encoding=str(cnt_raw.get("encoding", "utf-8")),
        ),
        output=OutputCfg(
            format=str(out_raw.get("format", "table")).lower(),
            group_by=str(out_raw.get("group_by", "extension")).lower(),
            sort_by=str(out_raw.get("sort_by", "lines")).lower(),
            sort_order=str(out_raw.get("sort_order", "desc")).lower(),
            show_total=bool(out_raw.get("show_total", True)),
            limit=int(out_raw.get("limit", 0)),
        ),
    )


# --------------------------------------------------------------------------- #
# Обход и фильтрация
# --------------------------------------------------------------------------- #


def _dir_excluded(name: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(name, pat) for pat in patterns)


def _file_excluded(name: str, rel_path: str, cfg: ExcludeCfg) -> bool:
    if any(fnmatch.fnmatch(name, pat) for pat in cfg.file_patterns):
        return True
    return any(fnmatch.fnmatch(rel_path, pat) for pat in cfg.path_patterns)


def iter_files(scan: ScanCfg, formats: FormatsCfg, exclude: ExcludeCfg) -> Iterator[Path]:
    """Итеративный обход с pruning исключённых директорий."""
    root = scan.root.resolve()
    if not root.exists():
        raise FileNotFoundError(f"Scan root not found: {root}")

    include = formats.include  # пустой -> все

    if not scan.recursive:
        for entry in root.iterdir():
            if entry.is_file() and _accept_file(entry, root, include, exclude):
                yield entry
        return

    # Ручной DFS вместо Path.rglob — даёт честный pruning директорий.
    stack: list[Path] = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except (PermissionError, OSError):
            continue
        for entry in entries:
            if entry.is_symlink() and not scan.follow_symlinks:
                continue
            if entry.is_dir():
                if _dir_excluded(entry.name, exclude.dirs):
                    continue
                stack.append(entry)
            elif entry.is_file():
                if _accept_file(entry, root, include, exclude):
                    yield entry


def _accept_file(path: Path, root: Path, include: frozenset[str], exclude: ExcludeCfg) -> bool:
    if include and path.suffix.lower() not in include:
        return False
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:
        rel = path.as_posix()
    return not _file_excluded(path.name, rel, exclude)


# --------------------------------------------------------------------------- #
# Счётчики (Strategy)
# --------------------------------------------------------------------------- #


@dataclass
class FileStats:
    path: Path
    ext: str
    files: int = 1
    lines_total: int = 0  # все физические строки
    lines_code: int = 0  # эффективные строки (с учётом флагов конфига)
    lines_blank: int = 0
    lines_comment: int = 0
    lines_docstring: int = 0
    chars: int = 0


class Counter:
    """База — простой подсчёт строк/символов без понимания комментариев."""

    def count(self, text: str, cnt: CountCfg) -> tuple[int, int, int, int, int]:
        # Возвращает: total, code, blank, comment, docstring
        total = 0
        blank = 0
        for line in text.splitlines():
            total += 1
            if not line.strip():
                blank += 1
        code = total if cnt.blank_lines else total - blank
        return total, code, blank, 0, 0


class HashCommentCounter(Counter):
    """Языки с `#` комментариями: Python (без docstrings), Shell, TOML, YAML."""

    def count(self, text: str, cnt: CountCfg) -> tuple[int, int, int, int, int]:
        total = 0
        blank = 0
        comment = 0
        for line in text.splitlines():
            total += 1
            stripped = line.strip()
            if not stripped:
                blank += 1
            elif stripped.startswith("#"):
                comment += 1

        code = total
        if not cnt.blank_lines:
            code -= blank
        if not cnt.comments:
            code -= comment
        return total, max(code, 0), blank, comment, 0


class PythonCounter(Counter):
    """
    Python: понимает блоки тройных кавычек как docstring/строковый литерал.
    Эвристика: тройные кавычки на отдельной строке (либо обёрнуты вокруг блока).
    Достаточно точно для статистики, без полноценного парсинга AST.
    """

    def count(self, text: str, cnt: CountCfg) -> tuple[int, int, int, int, int]:
        total = 0
        blank = 0
        comment = 0
        docstring = 0
        in_doc = False
        doc_quote = ""

        for raw in text.splitlines():
            total += 1
            stripped = raw.strip()
            if not stripped:
                blank += 1
                if in_doc:
                    docstring += 1
                continue

            if in_doc:
                docstring += 1
                if doc_quote in stripped:
                    in_doc = False
                continue

            # Не внутри docstring
            if stripped.startswith("#"):
                comment += 1
                continue

            # Поиск открытия тройных кавычек
            for quote in ('"""', "'''"):
                if quote in stripped:
                    # сколько раз встретилась — чётное = открыли и закрыли на одной строке
                    occurrences = stripped.count(quote)
                    if occurrences % 2 == 1:
                        in_doc = True
                        doc_quote = quote
                        docstring += 1
                    else:
                        # однострочный docstring/литерал — считаем как docstring,
                        # если строка состоит только из него
                        if stripped.startswith(quote) and stripped.endswith(quote):
                            docstring += 1
                        # иначе это inline-строка в коде, не трогаем
                    break

        code = total
        if not cnt.blank_lines:
            code -= blank
        if not cnt.comments:
            code -= comment
        if not cnt.docstrings:
            code -= docstring
        return total, max(code, 0), blank, comment, docstring


class MarkdownCounter(Counter):
    """Markdown: HTML-комментарии <!-- ... -->, многострочные."""

    def count(self, text: str, cnt: CountCfg) -> tuple[int, int, int, int, int]:
        total = 0
        blank = 0
        comment = 0
        in_comment = False

        for raw in text.splitlines():
            total += 1
            stripped = raw.strip()
            if not stripped:
                blank += 1
                if in_comment:
                    comment += 1
                continue

            if in_comment:
                comment += 1
                if "-->" in stripped:
                    in_comment = False
                continue

            if stripped.startswith("<!--"):
                comment += 1
                if "-->" not in stripped[4:]:
                    in_comment = True

        code = total
        if not cnt.blank_lines:
            code -= blank
        if not cnt.comments:
            code -= comment
        return total, max(code, 0), blank, comment, 0


_COUNTERS: dict[str, Counter] = {
    ".py": PythonCounter(),
    ".md": MarkdownCounter(),
    ".sh": HashCommentCounter(),
    ".bash": HashCommentCounter(),
    ".zsh": HashCommentCounter(),
    ".toml": HashCommentCounter(),
    ".yaml": HashCommentCounter(),
    ".yml": HashCommentCounter(),
}
_DEFAULT_COUNTER = Counter()


def counter_for(ext: str) -> Counter:
    return _COUNTERS.get(ext.lower(), _DEFAULT_COUNTER)


# --------------------------------------------------------------------------- #
# Главный обработчик
# --------------------------------------------------------------------------- #


def measure_file(path: Path, cfg: Config) -> FileStats | None:
    try:
        text = path.read_text(encoding=cfg.count.encoding, errors="replace")
    except (OSError, UnicodeDecodeError):
        return None

    ext = path.suffix.lower()
    total, code, blank, comment, doc = counter_for(ext).count(text, cfg.count)
    stats = FileStats(
        path=path,
        ext=ext or "(no-ext)",
        lines_total=total,
        lines_code=code,
        lines_blank=blank,
        lines_comment=comment,
        lines_docstring=doc,
        chars=len(text) if cfg.count.chars else 0,
    )
    return stats


def collect(cfg: Config) -> list[FileStats]:
    results: list[FileStats] = []
    for path in iter_files(cfg.scan, cfg.formats, cfg.exclude):
        stats = measure_file(path, cfg)
        if stats is not None:
            results.append(stats)
    return results


# --------------------------------------------------------------------------- #
# Группировка и сортировка
# --------------------------------------------------------------------------- #


@dataclass
class GroupRow:
    key: str
    files: int = 0
    lines_total: int = 0
    lines_code: int = 0
    lines_blank: int = 0
    lines_comment: int = 0
    lines_docstring: int = 0
    chars: int = 0

    def add(self, s: FileStats) -> None:
        self.files += s.files
        self.lines_total += s.lines_total
        self.lines_code += s.lines_code
        self.lines_blank += s.lines_blank
        self.lines_comment += s.lines_comment
        self.lines_docstring += s.lines_docstring
        self.chars += s.chars


def group_results(stats: Iterable[FileStats], cfg: Config) -> list[GroupRow]:
    root = cfg.scan.root.resolve()
    groups: dict[str, GroupRow] = {}

    for s in stats:
        if cfg.output.group_by == "extension":
            key = s.ext
        elif cfg.output.group_by == "directory":
            try:
                rel_dir = s.path.parent.resolve().relative_to(root).as_posix() or "."
            except ValueError:
                rel_dir = s.path.parent.as_posix()
            key = rel_dir
        else:  # none — каждый файл отдельной строкой
            try:
                key = s.path.resolve().relative_to(root).as_posix()
            except ValueError:
                key = s.path.as_posix()

        row = groups.get(key)
        if row is None:
            row = GroupRow(key=key)
            groups[key] = row
        row.add(s)

    rows = list(groups.values())
    sort_key = {
        "lines": lambda r: r.lines_code,
        "chars": lambda r: r.chars,
        "files": lambda r: r.files,
        "name": lambda r: r.key,
    }.get(cfg.output.sort_by, lambda r: r.lines_code)
    rows.sort(key=sort_key, reverse=(cfg.output.sort_order != "asc"))

    if cfg.output.limit > 0:
        rows = rows[: cfg.output.limit]
    return rows


def total_row(rows: list[GroupRow]) -> GroupRow:
    total = GroupRow(key="TOTAL")
    for r in rows:
        total.files += r.files
        total.lines_total += r.lines_total
        total.lines_code += r.lines_code
        total.lines_blank += r.lines_blank
        total.lines_comment += r.lines_comment
        total.lines_docstring += r.lines_docstring
        total.chars += r.chars
    return total


# --------------------------------------------------------------------------- #
# Форматирование вывода
# --------------------------------------------------------------------------- #

_HEADERS = ["group", "files", "lines", "code", "blank", "comment", "docstr", "chars"]


def _row_to_list(r: GroupRow) -> list:
    return [
        r.key,
        r.files,
        r.lines_total,
        r.lines_code,
        r.lines_blank,
        r.lines_comment,
        r.lines_docstring,
        r.chars,
    ]


def render_table(rows: list[GroupRow], total: GroupRow | None) -> str:
    data = [_row_to_list(r) for r in rows]
    if total is not None:
        data.append(_row_to_list(total))

    widths = [len(h) for h in _HEADERS]
    for row in data:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(f"{cell:,}" if isinstance(cell, int) else str(cell)))

    out = io.StringIO()
    sep = "  "
    out.write(sep.join(h.ljust(widths[i]) for i, h in enumerate(_HEADERS)) + "\n")
    out.write(sep.join("-" * w for w in widths) + "\n")

    for row in data:
        cells = []
        for i, cell in enumerate(row):
            if isinstance(cell, int):
                cells.append(f"{cell:,}".rjust(widths[i]))
            else:
                cells.append(str(cell).ljust(widths[i]))
        out.write(sep.join(cells) + "\n")
    return out.getvalue()


def render_json(rows: list[GroupRow], total: GroupRow | None) -> str:
    payload = {
        "rows": [dict(zip(_HEADERS, _row_to_list(r))) for r in rows],
    }
    if total is not None:
        payload["total"] = dict(zip(_HEADERS, _row_to_list(total)))
    return json.dumps(payload, ensure_ascii=False, indent=2)


def render_csv(rows: list[GroupRow], total: GroupRow | None) -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(_HEADERS)
    for r in rows:
        w.writerow(_row_to_list(r))
    if total is not None:
        w.writerow(_row_to_list(total))
    return out.getvalue()


def render(rows: list[GroupRow], cfg: Config) -> str:
    total = total_row(rows) if cfg.output.show_total else None
    fmt = cfg.output.format
    if fmt == "json":
        return render_json(rows, total)
    if fmt == "csv":
        return render_csv(rows, total)
    return render_table(rows, total)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="code_stats",
        description="Подсчёт файлов, строк и символов по конфигу TOML.",
    )
    p.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"Путь к TOML-конфигу (default: {DEFAULT_CONFIG_PATH}).",
    )
    p.add_argument("--root", type=Path, default=None, help="Перекрыть scan.root.")
    p.add_argument(
        "--format",
        choices=["table", "json", "csv"],
        default=None,
        help="Перекрыть output.format.",
    )
    p.add_argument(
        "--group-by",
        choices=["extension", "directory", "none"],
        default=None,
        help="Перекрыть output.group_by.",
    )
    p.add_argument(
        "--sort-by",
        choices=["lines", "chars", "files", "name"],
        default=None,
        help="Перекрыть output.sort_by.",
    )
    p.add_argument("--no-total", action="store_true", help="Скрыть строку TOTAL.")
    p.add_argument("--limit", type=int, default=None, help="Максимум строк в выводе.")
    return p


def apply_overrides(cfg: Config, args: argparse.Namespace) -> Config:
    scan = cfg.scan
    out = cfg.output
    if args.root is not None:
        scan = ScanCfg(
            root=args.root,
            recursive=scan.recursive,
            follow_symlinks=scan.follow_symlinks,
        )
    if args.format is not None:
        out = OutputCfg(
            format=args.format,
            group_by=out.group_by,
            sort_by=out.sort_by,
            sort_order=out.sort_order,
            show_total=out.show_total,
            limit=out.limit,
        )
    if args.group_by is not None:
        out = OutputCfg(
            format=out.format,
            group_by=args.group_by,
            sort_by=out.sort_by,
            sort_order=out.sort_order,
            show_total=out.show_total,
            limit=out.limit,
        )
    if args.sort_by is not None:
        out = OutputCfg(
            format=out.format,
            group_by=out.group_by,
            sort_by=args.sort_by,
            sort_order=out.sort_order,
            show_total=out.show_total,
            limit=out.limit,
        )
    if args.no_total:
        out = OutputCfg(
            format=out.format,
            group_by=out.group_by,
            sort_by=out.sort_by,
            sort_order=out.sort_order,
            show_total=False,
            limit=out.limit,
        )
    if args.limit is not None:
        out = OutputCfg(
            format=out.format,
            group_by=out.group_by,
            sort_by=out.sort_by,
            sort_order=out.sort_order,
            show_total=out.show_total,
            limit=args.limit,
        )
    return Config(scan=scan, formats=cfg.formats, exclude=cfg.exclude, count=cfg.count, output=out)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cfg = load_config(args.config)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    cfg = apply_overrides(cfg, args)

    try:
        stats = collect(cfg)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    rows = group_results(stats, cfg)
    sys.stdout.write(render(rows, cfg))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
