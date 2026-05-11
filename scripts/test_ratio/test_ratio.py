"""
Отношение объёма тестов к продакшен-коду на каждый модуль.

Алгоритм:
1. Из конфига берём список module_roots (multiprocess_framework/modules, Services, …).
2. Для каждого root: его прямые подкаталоги = модули.
3. Внутри модуля рекурсивно считаем LOC, разделяя на:
   - test:  файлы в test_dir/ ИЛИ имена по test_file_patterns
   - code:  всё остальное .py
4. ratio = test_loc / code_loc (0.0 если кода нет; "—" если тестов нет)

Запуск:
    python scripts/test_ratio/test_ratio.py
    python scripts/test_ratio/test_ratio.py --format json
    python scripts/test_ratio/test_ratio.py --sort-by ratio --sort-order asc
"""

from __future__ import annotations

import argparse
import csv
import fnmatch
import io
import json
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG_PATH = Path(__file__).with_name("test_ratio.toml")


@dataclass(frozen=True)
class Config:
    module_roots: tuple[Path, ...]
    test_dir: str
    test_file_patterns: tuple[str, ...]
    exclude_dirs: tuple[str, ...]
    exclude_files: tuple[str, ...]
    count_mode: str
    encoding: str
    output_format: str
    sort_by: str
    sort_order: str
    limit: int
    warn_threshold: float


def load_config(path: Path) -> Config:
    with path.open("rb") as f:
        raw = tomllib.load(f)
    scan = raw.get("scan", {})
    det = raw.get("detect", {})
    exc = raw.get("exclude", {})
    cnt = raw.get("count", {})
    out = raw.get("output", {})
    return Config(
        module_roots=tuple(Path(p) for p in scan.get("module_roots", [])),
        test_dir=str(det.get("test_dir", "tests")),
        test_file_patterns=tuple(det.get("test_file_patterns", [])),
        exclude_dirs=tuple(exc.get("dirs", [])),
        exclude_files=tuple(exc.get("file_patterns", [])),
        count_mode=str(cnt.get("mode", "non_blank_non_comment")),
        encoding=str(cnt.get("encoding", "utf-8")),
        output_format=str(out.get("format", "table")).lower(),
        sort_by=str(out.get("sort_by", "ratio")).lower(),
        sort_order=str(out.get("sort_order", "asc")).lower(),
        limit=int(out.get("limit", 0)),
        warn_threshold=float(out.get("warn_threshold", 0.3)),
    )


# --------------------------------------------------------------------------- #
# Подсчёт LOC
# --------------------------------------------------------------------------- #


def count_lines(path: Path, mode: str, encoding: str) -> int:
    try:
        text = path.read_text(encoding=encoding, errors="replace")
    except OSError:
        return 0

    if mode == "all":
        return len(text.splitlines())

    count = 0
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if mode == "non_blank_non_comment" and stripped.startswith("#"):
            continue
        count += 1
    return count


# --------------------------------------------------------------------------- #
# Обход модулей
# --------------------------------------------------------------------------- #


@dataclass
class ModuleRow:
    name: str            # "modules/X" или "Services/Y"
    code_loc: int = 0
    test_loc: int = 0
    code_files: int = 0
    test_files: int = 0

    @property
    def ratio(self) -> float:
        if self.code_loc == 0:
            return 0.0
        return self.test_loc / self.code_loc

    @property
    def has_tests(self) -> bool:
        return self.test_loc > 0


def _is_test_path(rel_in_module: str, name: str, cfg: Config) -> bool:
    parts = rel_in_module.split("/")
    if cfg.test_dir and cfg.test_dir in parts:
        return True
    return any(fnmatch.fnmatch(name, pat) for pat in cfg.test_file_patterns)


def scan_module(module_dir: Path, cfg: Config) -> ModuleRow:
    row = ModuleRow(name="")
    stack = [module_dir]
    while stack:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except (PermissionError, OSError):
            continue
        for entry in entries:
            if entry.is_dir():
                if any(fnmatch.fnmatch(entry.name, pat) for pat in cfg.exclude_dirs):
                    continue
                stack.append(entry)
            elif entry.is_file() and entry.suffix == ".py":
                if any(fnmatch.fnmatch(entry.name, pat) for pat in cfg.exclude_files):
                    continue
                rel = entry.relative_to(module_dir).as_posix()
                loc = count_lines(entry, cfg.count_mode, cfg.encoding)
                if _is_test_path(rel, entry.name, cfg):
                    row.test_loc += loc
                    row.test_files += 1
                else:
                    row.code_loc += loc
                    row.code_files += 1
    return row


def collect(cfg: Config, base: Path) -> list[ModuleRow]:
    rows: list[ModuleRow] = []
    for root_rel in cfg.module_roots:
        root = (base / root_rel).resolve()
        if not root.exists():
            continue
        for entry in sorted(root.iterdir()):
            if not entry.is_dir():
                continue
            if any(fnmatch.fnmatch(entry.name, pat) for pat in cfg.exclude_dirs):
                continue
            row = scan_module(entry, cfg)
            row.name = f"{root_rel.as_posix()}/{entry.name}"
            rows.append(row)
    return rows


# --------------------------------------------------------------------------- #
# Рендеринг
# --------------------------------------------------------------------------- #


def _health_mark(row: ModuleRow, cfg: Config) -> str:
    if not row.has_tests:
        return "x"   # без тестов
    if row.ratio >= cfg.warn_threshold:
        return "ok"
    return "!"


def render_table(rows: list[ModuleRow], cfg: Config) -> str:
    headers = ["health", "module", "code_loc", "test_loc", "ratio", "code_files", "test_files"]
    data = []
    for r in rows:
        ratio_str = f"{r.ratio:.2f}" if r.code_loc else "—"
        data.append([_health_mark(r, cfg), r.name, r.code_loc, r.test_loc, ratio_str,
                     r.code_files, r.test_files])

    widths = [len(h) for h in headers]
    for row in data:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(f"{cell:,}" if isinstance(cell, int) else str(cell)))

    out = io.StringIO()
    sep = "  "
    out.write(sep.join(h.ljust(widths[i]) for i, h in enumerate(headers)) + "\n")
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


def render_json(rows: list[ModuleRow], cfg: Config) -> str:
    payload = [
        {
            "module": r.name,
            "code_loc": r.code_loc,
            "test_loc": r.test_loc,
            "ratio": round(r.ratio, 4),
            "code_files": r.code_files,
            "test_files": r.test_files,
            "health": _health_mark(r, cfg),
        }
        for r in rows
    ]
    return json.dumps(payload, ensure_ascii=False, indent=2)


def render_csv(rows: list[ModuleRow]) -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["module", "code_loc", "test_loc", "ratio", "code_files", "test_files"])
    for r in rows:
        w.writerow([r.name, r.code_loc, r.test_loc, f"{r.ratio:.4f}", r.code_files, r.test_files])
    return out.getvalue()


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="test_ratio",
                                description="Отношение объёма тестов к коду на модуль.")
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    p.add_argument("--base", type=Path, default=Path("."),
                   help="База, к которой относятся module_roots (default: текущая директория).")
    p.add_argument("--format", choices=["table", "json", "csv"], default=None)
    p.add_argument("--sort-by", choices=["ratio", "code", "tests", "name"], default=None)
    p.add_argument("--sort-order", choices=["asc", "desc"], default=None)
    p.add_argument("--limit", type=int, default=None)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cfg = load_config(args.config)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    overrides = {}
    if args.format is not None: overrides["output_format"] = args.format
    if args.sort_by is not None: overrides["sort_by"] = args.sort_by
    if args.sort_order is not None: overrides["sort_order"] = args.sort_order
    if args.limit is not None: overrides["limit"] = args.limit
    if overrides:
        cfg = Config(**{**cfg.__dict__, **overrides})

    rows = collect(cfg, args.base.resolve())

    sort_key = {
        "ratio": lambda r: r.ratio,
        "code": lambda r: r.code_loc,
        "tests": lambda r: r.test_loc,
        "name": lambda r: r.name,
    }.get(cfg.sort_by, lambda r: r.ratio)
    rows.sort(key=sort_key, reverse=(cfg.sort_order != "asc"))

    if cfg.limit > 0:
        rows = rows[: cfg.limit]

    if cfg.output_format == "json":
        sys.stdout.write(render_json(rows, cfg))
    elif cfg.output_format == "csv":
        sys.stdout.write(render_csv(rows))
    else:
        sys.stdout.write(render_table(rows, cfg))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
