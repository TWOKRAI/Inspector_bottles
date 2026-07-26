"""
Универсальный счётчик файлов / папок / строк / слов / символов с TOML-конфигом.

Принципы:
- stdlib-only (Python 3.12+): tomllib, fnmatch, pathlib, argparse, dataclasses.
- Strategy для подсчёта по типу файла (Python / Markdown / Shell / Plain).
- Pruning исключений на уровне обхода (не читаем то, что отброшено).
- Правдивость по умолчанию: `git_tracked` считает только то, что реально лежит
  в репозитории (сгенерированные кэши и всё из .gitignore не искажают цифры).
- CLI-флаги перекрывают TOML.

Запуск:
    python scripts/code_stats/code_stats.py
    python scripts/code_stats/code_stats.py multiprocess_framework Services
    python scripts/code_stats/code_stats.py --format json --group-by directory
    python scripts/code_stats/code_stats.py --group-by directory --dir-depth 1
    python scripts/code_stats/code_stats.py --config path/to/other.toml
"""

from __future__ import annotations

import argparse
import csv
import fnmatch
import io
import json
import os
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Iterable, Iterator


# --------------------------------------------------------------------------- #
# Конфигурация
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ScanCfg:
    # Одна или несколько папок для анализа. Первая — база для относительных путей.
    roots: tuple[Path, ...] = (Path("."),)
    recursive: bool = True
    follow_symlinks: bool = False
    # Считать только файлы, известные git (tracked + untracked не-ignored).
    # Это отсекает сгенерированные кэши/артефакты из .gitignore — цифры честнее.
    git_tracked: bool = False

    @property
    def root(self) -> Path:
        """База для относительных путей и обратная совместимость с одной папкой."""
        return self.roots[0]


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
    words: bool = True
    encoding: str = "utf-8"


@dataclass(frozen=True)
class OutputCfg:
    format: str = "table"  # table | json | csv
    group_by: str = "extension"  # extension | directory | none
    sort_by: str = "lines"  # lines | words | chars | files | dirs | name
    sort_order: str = "desc"  # desc | asc
    show_total: bool = True
    limit: int = 0
    # Глубина группировки при group_by = "directory": 1 = только верхний
    # сегмент пути (зоны проекта), 2 = два сегмента, 0 = полный путь.
    dir_depth: int = 0


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

    # `paths` (список) — новый способ выбрать несколько папок; `root` (строка) —
    # старый, поддержан для совместимости. Пусто → текущая директория.
    raw_paths = scan_raw.get("paths") or ([scan_raw["root"]] if "root" in scan_raw else ["."])
    roots = tuple(Path(str(p)).expanduser() for p in raw_paths) or (Path("."),)

    return Config(
        scan=ScanCfg(
            roots=roots,
            recursive=bool(scan_raw.get("recursive", True)),
            follow_symlinks=bool(scan_raw.get("follow_symlinks", False)),
            git_tracked=bool(scan_raw.get("git_tracked", False)),
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
            words=bool(cnt_raw.get("words", True)),
            encoding=str(cnt_raw.get("encoding", "utf-8")),
        ),
        output=OutputCfg(
            format=str(out_raw.get("format", "table")).lower(),
            group_by=str(out_raw.get("group_by", "extension")).lower(),
            sort_by=str(out_raw.get("sort_by", "lines")).lower(),
            sort_order=str(out_raw.get("sort_order", "desc")).lower(),
            show_total=bool(out_raw.get("show_total", True)),
            limit=int(out_raw.get("limit", 0)),
            dir_depth=int(out_raw.get("dir_depth", 0)),
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
    if any(fnmatch.fnmatch(rel_path, pat) for pat in cfg.path_patterns):
        return True
    return False


def iter_files(scan: ScanCfg, formats: FormatsCfg, exclude: ExcludeCfg) -> Iterator[Path]:
    """
    Файлы всех выбранных папок, без дублей.

    Дубли реальны: `--path . --path scripts` даёт пересекающиеся деревья.
    Ключ дедупликации — resolved-путь.
    """
    seen: set[Path] = set()
    for raw_root in scan.roots:
        root = raw_root.resolve()
        if not root.exists():
            raise FileNotFoundError(f"Scan root not found: {root}")
        source = _iter_git_files(root, scan, exclude) if scan.git_tracked else _iter_walk_files(root, scan, exclude)
        for path in source:
            resolved = path.resolve()
            if resolved in seen:
                continue
            if not _accept_file(resolved, root, formats.include, exclude):
                continue
            seen.add(resolved)
            yield resolved


def _iter_walk_files(root: Path, scan: ScanCfg, exclude: ExcludeCfg) -> Iterator[Path]:
    """Обход файловой системы с pruning исключённых директорий."""
    if not scan.recursive:
        yield from (e for e in root.iterdir() if e.is_file())
        return

    # Ручной DFS вместо Path.rglob — даёт честный pruning директорий.
    stack: list[Path] = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except OSError as e:
            # Молча пропущенная папка = молча заниженная цифра: пользователь
            # увидит меньший счёт и не узнает, что часть дерева не читалась.
            print(f"warning: папка пропущена, нет доступа: {current} ({e})", file=sys.stderr)
            continue
        for entry in entries:
            if entry.is_symlink() and not scan.follow_symlinks:
                continue
            if entry.is_dir():
                if not _dir_excluded(entry.name, exclude.dirs):
                    stack.append(entry)
            elif entry.is_file():
                yield entry


def _iter_git_files(root: Path, scan: ScanCfg, exclude: ExcludeCfg) -> Iterator[Path]:
    """
    Файлы, о которых знает git: tracked + untracked, но НЕ попавшие в .gitignore.

    Зачем: сгенерированные кэши (graphify-out, дампы, датасеты) не должны
    попадать в оценку проекта. .gitignore — уже готовое и поддерживаемое
    описание «что тут не наше».

    Если git недоступен или папка не в репозитории — падаем обратно на обход ФС
    с явным предупреждением в stderr (тихая подмена метода = вранью в цифрах).
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as e:
        print(f"warning: git_tracked недоступен для {root} ({e}); обхожу файловую систему", file=sys.stderr)
        # Тот же exclude, что и в обычном режиме: без него обход заходит в
        # .git/ и __pycache__/ — результат тот же, но I/O впустую.
        yield from _iter_walk_files(root, scan, exclude)
        return

    for rel in proc.stdout.decode("utf-8", errors="replace").split("\0"):
        if not rel:
            continue
        path = root / rel
        # git знает и про удалённые из ФС, но ещё не закоммиченные удаления.
        if path.is_file():
            yield path


def _accept_file(path: Path, root: Path, include: frozenset[str], exclude: ExcludeCfg) -> bool:
    if include and path.suffix.lower() not in include:
        return False
    try:
        rel_parts = path.relative_to(root).parts
    except ValueError:
        rel_parts = path.parts
    # Исключённые папки проверяем и здесь: в git-режиме pruning обхода не было.
    if any(_dir_excluded(part, exclude.dirs) for part in rel_parts[:-1]):
        return False
    return not _file_excluded(path.name, "/".join(rel_parts), exclude)


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
    words: int = 0
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
                    # учитываем возможность открыть и закрыть на одной строке после входа
                    if stripped.count(doc_quote) >= 1:
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


def count_words(text: str) -> int:
    """
    Слова = последовательности непробельных символов (модель `wc -w`).

    Осознанно НЕ пытаемся понимать «слова кода»: любая умная эвристика
    (идентификаторы, snake_case → 2 слова) непереносима между языками и
    непроверяема. `wc -w` — определение, которое читатель отчёта уже знает.
    """
    return len(text.split())


def measure_file(path: Path, cfg: Config) -> FileStats | None:
    try:
        text = path.read_text(encoding=cfg.count.encoding, errors="replace")
    except (OSError, UnicodeDecodeError) as e:
        # Непрочитанный файл просто исчезает из отчёта — без этой строки
        # разница в цифрах ничем не объясняется.
        print(f"warning: файл не прочитан: {path} ({e})", file=sys.stderr)
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
        words=count_words(text) if cfg.count.words else 0,
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
    words: int = 0
    chars: int = 0
    # Папки считаем как множество, а не счётчиком: иначе TOTAL по группам
    # сложил бы одну и ту же папку столько раз, сколько в ней расширений.
    dir_paths: set[str] = field(default_factory=set)

    @property
    def dirs(self) -> int:
        return len(self.dir_paths)

    def add(self, s: FileStats, dir_key: str) -> None:
        self.files += s.files
        self.lines_total += s.lines_total
        self.lines_code += s.lines_code
        self.lines_blank += s.lines_blank
        self.lines_comment += s.lines_comment
        self.lines_docstring += s.lines_docstring
        self.words += s.words
        self.chars += s.chars
        self.dir_paths.add(dir_key)


def display_base(roots: tuple[Path, ...]) -> Path | None:
    """
    База, относительно которой строятся ключи отчёта.

    Одна папка → она сама. Несколько → их общий родитель: иначе `a/same.py` и
    `b/same.py` дают одинаковый ключ `same.py` и схлопываются в одну строку, а
    две разные папки считаются одной. None = общего родителя нет (разные диски),
    тогда ключи абсолютные.
    """
    resolved = [r.resolve() for r in roots]
    if len(resolved) == 1:
        return resolved[0]
    try:
        return Path(os.path.commonpath(resolved))
    except ValueError:
        return None


def _rel_to_base(path: Path, base: Path | None) -> str:
    """Путь относительно базы (иначе — абсолютный)."""
    if base is not None:
        try:
            return path.relative_to(base).as_posix()
        except ValueError:
            pass
    return path.as_posix()


def group_results(stats: Iterable[FileStats], cfg: Config) -> tuple[list[GroupRow], GroupRow]:
    """Возвращает (строки отчёта, TOTAL). TOTAL считается ДО обрезки limit'ом."""
    base = display_base(cfg.scan.roots)
    groups: dict[str, GroupRow] = {}

    for s in stats:
        rel_dir = _rel_to_base(s.path.parent.resolve(), base) or "."
        if cfg.output.group_by == "extension":
            key = s.ext
        elif cfg.output.group_by == "directory":
            key = _trim_depth(rel_dir, cfg.output.dir_depth)
        else:  # none — каждый файл отдельной строкой
            key = _rel_to_base(s.path.resolve(), base)

        row = groups.get(key)
        if row is None:
            row = GroupRow(key=key)
            groups[key] = row
        row.add(s, rel_dir)

    rows = list(groups.values())
    sort_key = {
        "lines": lambda r: r.lines_code,
        "words": lambda r: r.words,
        "chars": lambda r: r.chars,
        "files": lambda r: r.files,
        "dirs": lambda r: r.dirs,
        "name": lambda r: r.key,
    }.get(cfg.output.sort_by, lambda r: r.lines_code)
    rows.sort(key=sort_key, reverse=(cfg.output.sort_order != "asc"))

    total = total_row(rows)
    if cfg.output.limit > 0:
        rows = rows[: cfg.output.limit]
    return rows, total


def _trim_depth(rel_dir: str, depth: int) -> str:
    """`a/b/c` при depth=1 → `a`. depth <= 0 — полный путь."""
    if depth <= 0 or rel_dir == ".":
        return rel_dir
    return "/".join(rel_dir.split("/")[:depth])


def total_row(rows: list[GroupRow]) -> GroupRow:
    total = GroupRow(key="TOTAL")
    for r in rows:
        total.files += r.files
        total.lines_total += r.lines_total
        total.lines_code += r.lines_code
        total.lines_blank += r.lines_blank
        total.lines_comment += r.lines_comment
        total.lines_docstring += r.lines_docstring
        total.words += r.words
        total.chars += r.chars
        total.dir_paths |= r.dir_paths
    return total


# --------------------------------------------------------------------------- #
# Форматирование вывода
# --------------------------------------------------------------------------- #

_HEADERS = ["group", "files", "dirs", "lines", "code", "blank", "comment", "docstr", "words", "chars"]


def _row_to_list(r: GroupRow) -> list:
    return [
        r.key,
        r.files,
        r.dirs,
        r.lines_total,
        r.lines_code,
        r.lines_blank,
        r.lines_comment,
        r.lines_docstring,
        r.words,
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


def render(rows: list[GroupRow], cfg: Config, total: GroupRow | None = None) -> str:
    # total передаётся явно, когда он посчитан ДО обрезки limit'ом: иначе строка
    # TOTAL врала бы, показывая сумму только видимых строк.
    if cfg.output.show_total:
        total = total if total is not None else total_row(rows)
    else:
        total = None
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
        description="Подсчёт файлов, папок, строк, слов и символов по конфигу TOML.",
    )
    p.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Папки для анализа (можно несколько). Пусто — берётся scan.paths из конфига.",
    )
    p.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"Путь к TOML-конфигу (default: {DEFAULT_CONFIG_PATH}).",
    )
    p.add_argument(
        "--root", type=Path, default=None, help="Синоним одиночного позиционного пути (обратная совместимость)."
    )
    p.add_argument(
        "--git-tracked",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Считать только известное git (без .gitignore-артефактов).",
    )
    p.add_argument("--format", choices=["table", "json", "csv"], default=None, help="Перекрыть output.format.")
    p.add_argument(
        "--group-by", choices=["extension", "directory", "none"], default=None, help="Перекрыть output.group_by."
    )
    p.add_argument(
        "--dir-depth", type=int, default=None, help="Глубина группировки директорий (1 = зоны верхнего уровня)."
    )
    p.add_argument(
        "--sort-by",
        choices=["lines", "words", "chars", "files", "dirs", "name"],
        default=None,
        help="Перекрыть output.sort_by.",
    )
    p.add_argument(
        "--no-comments", action="store_true", help="Не считать комментарии строками кода (колонка code → SLOC)."
    )
    p.add_argument(
        "--no-docstrings",
        action="store_true",
        help="Не считать docstring строками кода (вместе с --no-comments = чистый SLOC).",
    )
    p.add_argument("--no-total", action="store_true", help="Скрыть строку TOTAL.")
    p.add_argument("--limit", type=int, default=None, help="Максимум строк в выводе.")
    return p


def apply_overrides(cfg: Config, args: argparse.Namespace) -> Config:
    scan_updates: dict = {}
    roots = tuple(getattr(args, "paths", None) or ())
    if args.root is not None:
        roots = (*roots, args.root)
    if roots:
        scan_updates["roots"] = roots
    if args.git_tracked is not None:
        scan_updates["git_tracked"] = args.git_tracked

    count_updates: dict = {}
    if args.no_comments:
        count_updates["comments"] = False
    if args.no_docstrings:
        count_updates["docstrings"] = False

    out_updates: dict = {}
    if args.format is not None:
        out_updates["format"] = args.format
    if args.group_by is not None:
        out_updates["group_by"] = args.group_by
    if args.dir_depth is not None:
        out_updates["dir_depth"] = args.dir_depth
    if args.sort_by is not None:
        out_updates["sort_by"] = args.sort_by
    if args.no_total:
        out_updates["show_total"] = False
    if args.limit is not None:
        out_updates["limit"] = args.limit

    return replace(
        cfg,
        scan=replace(cfg.scan, **scan_updates),
        count=replace(cfg.count, **count_updates),
        output=replace(cfg.output, **out_updates),
    )


def _force_utf8_streams() -> None:
    """
    Вывод всегда в UTF-8, независимо от кодовой страницы консоли Windows.

    Без этого русские сообщения уходят в cp866/cp1251: потребитель, читающий
    stdout/stderr как UTF-8 (агент, CI, `subprocess(text=True)`), получает
    UnicodeDecodeError вместо отчёта — и это выглядит как «скрипт молчал».
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    _force_utf8_streams()
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

    rows, total = group_results(stats, cfg)
    sys.stdout.write(render(rows, cfg, total))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
