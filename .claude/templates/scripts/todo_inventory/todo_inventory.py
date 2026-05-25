"""
Инвентаризация TODO/FIXME/HACK/XXX/BUG/NOTE в проекте.

Опционально привязывает автора и дату коммита через `git blame -L`.
Это даёт возраст комментария — основу для уборки техдолга.

Запуск:
    python scripts/todo_inventory/todo_inventory.py
    python scripts/todo_inventory/todo_inventory.py --no-blame --format json
    python scripts/todo_inventory/todo_inventory.py --group-by author --sort-by age
"""

from __future__ import annotations

import argparse
import csv
import fnmatch
import io
import json
import re
import subprocess
import sys
import tomllib
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_CONFIG_PATH = Path(__file__).with_name("todo_inventory.toml")


@dataclass(frozen=True)
class Config:
    root: Path
    recursive: bool
    follow_symlinks: bool
    include: frozenset[str]
    exclude_dirs: tuple[str, ...]
    exclude_files: tuple[str, ...]
    exclude_paths: tuple[str, ...]
    tags: tuple[str, ...]
    git_blame: bool
    output_format: str
    group_by: str
    sort_by: str
    sort_order: str
    limit: int
    max_text: int


def load_config(path: Path) -> Config:
    with path.open("rb") as f:
        raw = tomllib.load(f)
    scan = raw.get("scan", {})
    fmt = raw.get("formats", {})
    exc = raw.get("exclude", {})
    det = raw.get("detect", {})
    out = raw.get("output", {})
    return Config(
        root=Path(scan.get("root", ".")).expanduser(),
        recursive=bool(scan.get("recursive", True)),
        follow_symlinks=bool(scan.get("follow_symlinks", False)),
        include=frozenset(ext.lower() for ext in fmt.get("include", [])),
        exclude_dirs=tuple(exc.get("dirs", [])),
        exclude_files=tuple(exc.get("file_patterns", [])),
        exclude_paths=tuple(exc.get("path_patterns", [])),
        tags=tuple(det.get("tags", ["TODO", "FIXME"])),
        git_blame=bool(det.get("git_blame", True)),
        output_format=str(out.get("format", "table")).lower(),
        group_by=str(out.get("group_by", "tag")).lower(),
        sort_by=str(out.get("sort_by", "age")).lower(),
        sort_order=str(out.get("sort_order", "desc")).lower(),
        limit=int(out.get("limit", 0)),
        max_text=int(out.get("max_text", 80)),
    )


# --------------------------------------------------------------------------- #
# Поиск
# --------------------------------------------------------------------------- #


@dataclass
class Hit:
    file: str
    line: int
    tag: str
    text: str
    author: str = ""
    date: str = ""  # ISO YYYY-MM-DD
    age_days: int = -1


def _build_regex(tags: tuple[str, ...]) -> re.Pattern[str]:
    # Ищем TAG, окружённый word-boundary; допускаем `:`/пробел/`(` после тега
    alt = "|".join(re.escape(t) for t in tags)
    return re.compile(rf"\b({alt})\b\s*[:\-(]?\s*(.*)")


def iter_files(cfg: Config):
    root = cfg.root.resolve()
    if not root.exists():
        raise FileNotFoundError(f"Scan root not found: {root}")
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except (PermissionError, OSError):
            continue
        for entry in entries:
            if entry.is_symlink() and not cfg.follow_symlinks:
                continue
            if entry.is_dir():
                if any(fnmatch.fnmatch(entry.name, pat) for pat in cfg.exclude_dirs):
                    continue
                if cfg.recursive:
                    stack.append(entry)
            elif entry.is_file():
                ext = entry.suffix.lower()
                if cfg.include and ext not in cfg.include:
                    continue
                if any(fnmatch.fnmatch(entry.name, pat) for pat in cfg.exclude_files):
                    continue
                try:
                    rel = entry.relative_to(root).as_posix()
                except ValueError:
                    rel = entry.as_posix()
                if any(fnmatch.fnmatch(rel, pat) for pat in cfg.exclude_paths):
                    continue
                yield entry, rel


def scan_file(path: Path, rel: str, regex: re.Pattern[str], max_text: int) -> list[Hit]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    hits: list[Hit] = []
    for i, line in enumerate(text.splitlines(), start=1):
        m = regex.search(line)
        if not m:
            continue
        tag = m.group(1)
        rest = m.group(2).strip()
        if len(rest) > max_text:
            rest = rest[: max_text - 1] + "…"
        hits.append(Hit(file=rel, line=i, tag=tag, text=rest))
    return hits


# --------------------------------------------------------------------------- #
# Git blame
# --------------------------------------------------------------------------- #


_BLAME_CACHE: dict[tuple[str, int], tuple[str, str]] = {}


def annotate_blame(hits: list[Hit], cwd: Path) -> None:
    today = datetime.now(timezone.utc).date()
    # Группируем по файлу — один subprocess на файл с --porcelain даёт все строки сразу,
    # но проще: один вызов на хит, кэш не нужен (хиты редко повторяются).
    by_file: dict[str, list[Hit]] = defaultdict(list)
    for h in hits:
        by_file[h.file].append(h)

    for file, file_hits in by_file.items():
        # Соберём только нужные строки
        line_args = []
        for h in file_hits:
            line_args.extend(["-L", f"{h.line},{h.line}"])
        try:
            proc = subprocess.run(
                ["git", "blame", "--porcelain", *line_args, "--", file],
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=20,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            continue
        if proc.returncode != 0:
            continue

        # Парсим --porcelain: блоки разделены строками "<sha> <orig> <final> <count>"
        # author, author-time встречаются в первом упоминании sha.
        info: dict[int, tuple[str, int]] = {}  # final_lineno -> (author, ts)
        cur_author = ""
        cur_ts = 0
        cur_final = -1
        for raw in proc.stdout.splitlines():
            if raw.startswith("\t"):
                # содержимое строки кода — фиксируем
                if cur_final >= 0:
                    info[cur_final] = (cur_author, cur_ts)
                cur_final = -1
                continue
            parts = raw.split(" ", 3)
            if (
                len(parts) >= 3
                and len(parts[0]) == 40
                and all(c in "0123456789abcdef" for c in parts[0])
            ):
                # sha original-line final-line [count]
                try:
                    cur_final = int(parts[2])
                except ValueError:
                    cur_final = -1
                continue
            if raw.startswith("author "):
                cur_author = raw[len("author ") :].strip()
            elif raw.startswith("author-time "):
                try:
                    cur_ts = int(raw[len("author-time ") :].strip())
                except ValueError:
                    cur_ts = 0

        for h in file_hits:
            if h.line in info:
                author, ts = info[h.line]
                h.author = author
                if ts:
                    d = datetime.fromtimestamp(ts, tz=timezone.utc).date()
                    h.date = d.isoformat()
                    h.age_days = (today - d).days


# --------------------------------------------------------------------------- #
# Рендеринг
# --------------------------------------------------------------------------- #


def _sort_hits(hits: list[Hit], cfg: Config) -> list[Hit]:
    sort_key = {
        "age": lambda h: h.age_days,
        "tag": lambda h: h.tag,
        "file": lambda h: (h.file, h.line),
        "author": lambda h: h.author,
    }.get(cfg.sort_by, lambda h: h.age_days)
    hits = sorted(hits, key=sort_key, reverse=(cfg.sort_order != "asc"))
    if cfg.limit > 0:
        hits = hits[: cfg.limit]
    return hits


def render_table(hits: list[Hit], cfg: Config) -> str:
    headers = ["tag", "age", "author", "file:line", "text"]
    data = []
    for h in hits:
        age = f"{h.age_days}d" if h.age_days >= 0 else "—"
        data.append([h.tag, age, h.author or "—", f"{h.file}:{h.line}", h.text])

    widths = [len(c) for c in headers]
    for row in data:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))

    out = io.StringIO()
    sep = "  "
    out.write(sep.join(h.ljust(widths[i]) for i, h in enumerate(headers)) + "\n")
    out.write(sep.join("-" * w for w in widths) + "\n")
    for row in data:
        out.write(
            sep.join(str(cell).ljust(widths[i]) for i, cell in enumerate(row)) + "\n"
        )
    return out.getvalue()


def render_summary(hits: list[Hit], cfg: Config) -> str:
    """Сводка по group_by (вызывается если group_by != none)."""
    if cfg.group_by == "tag":
        groups: dict[str, int] = defaultdict(int)
        for h in hits:
            groups[h.tag] += 1
        title = "Tag"
    elif cfg.group_by == "file":
        groups = defaultdict(int)
        for h in hits:
            groups[h.file] += 1
        title = "File"
    elif cfg.group_by == "author":
        groups = defaultdict(int)
        for h in hits:
            groups[h.author or "—"] += 1
        title = "Author"
    else:
        return ""

    rows = sorted(groups.items(), key=lambda kv: kv[1], reverse=True)
    width = max((len(k) for k, _ in rows), default=len(title))
    out = io.StringIO()
    out.write(f"{title.ljust(width)}  count\n")
    out.write("-" * width + "  -----\n")
    for k, v in rows:
        out.write(f"{k.ljust(width)}  {v}\n")
    out.write("\n")
    return out.getvalue()


def render_json(hits: list[Hit]) -> str:
    return json.dumps(
        [h.__dict__ for h in hits],
        ensure_ascii=False,
        indent=2,
    )


def render_csv(hits: list[Hit]) -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["tag", "age_days", "date", "author", "file", "line", "text"])
    for h in hits:
        w.writerow([h.tag, h.age_days, h.date, h.author, h.file, h.line, h.text])
    return out.getvalue()


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="todo_inventory", description="Инвентаризация TODO/FIXME с git blame."
    )
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    p.add_argument("--root", type=Path, default=None)
    p.add_argument("--format", choices=["table", "json", "csv"], default=None)
    p.add_argument(
        "--group-by", choices=["tag", "file", "author", "none"], default=None
    )
    p.add_argument("--sort-by", choices=["age", "tag", "file", "author"], default=None)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument(
        "--no-blame",
        action="store_true",
        help="Не запускать git blame (быстрее, но без автора/возраста).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cfg = load_config(args.config)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    overrides = {}
    if args.root is not None:
        overrides["root"] = args.root
    if args.format is not None:
        overrides["output_format"] = args.format
    if args.group_by is not None:
        overrides["group_by"] = args.group_by
    if args.sort_by is not None:
        overrides["sort_by"] = args.sort_by
    if args.limit is not None:
        overrides["limit"] = args.limit
    if args.no_blame:
        overrides["git_blame"] = False
    if overrides:
        cfg = Config(**{**cfg.__dict__, **overrides})

    regex = _build_regex(cfg.tags)
    hits: list[Hit] = []
    try:
        for path, rel in iter_files(cfg):
            hits.extend(scan_file(path, rel, regex, cfg.max_text))
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if cfg.git_blame and hits:
        annotate_blame(hits, cfg.root.resolve())

    hits = _sort_hits(hits, cfg)

    if cfg.output_format == "json":
        sys.stdout.write(render_json(hits))
    elif cfg.output_format == "csv":
        sys.stdout.write(render_csv(hits))
    else:
        if cfg.group_by != "none":
            sys.stdout.write(render_summary(hits, cfg))
        sys.stdout.write(render_table(hits, cfg))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
