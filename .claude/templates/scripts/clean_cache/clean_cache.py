"""
Чистка Python-кэшей и артефактов инструментов (__pycache__, .pytest_cache,
.mypy_cache, .ruff_cache, *.pyc, .coverage и т.п.).

Безопасность:
    * по умолчанию — dry-run: только показать, что было бы удалено;
    * реальное удаление включается флагом --apply;
    * корни вида "/", "/Users/<u>", "$HOME" отклоняются (forbid_dangerous_roots);
    * каталоги из [exclude] не сканируются вовсе.

Запуск (из корня проекта):
    python scripts/clean_cache/clean_cache.py                  # dry-run по дефолту
    python scripts/clean_cache/clean_cache.py --apply          # реально удалить
    python scripts/clean_cache/clean_cache.py --root scripts   # только подпапку
    python scripts/clean_cache/clean_cache.py --format json    # для агентов
    python scripts/clean_cache/clean_cache.py --apply --quiet  # для CI

Exit-коды:
    0 — успех (в т.ч. "удалять нечего");
    1 — пройдено сканирование, но при --apply были ошибки удаления отдельных
        путей; в JSON будет поле "errors" с деталями;
    2 — ошибка конфига / отказ по slow-rails (forbid_dangerous_roots) / I/O
        корня. Ничего не удалялось.
"""

from __future__ import annotations

import argparse
import fnmatch
import io
import json
import os
import shutil
import sys
import tomllib
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG_PATH = Path(__file__).with_name("clean_cache.toml")


# --------------------------------------------------------------------------- #
# Конфиг
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Config:
    root: Path
    follow_symlinks: bool
    delete_dirs: tuple[str, ...]
    delete_files: tuple[str, ...]
    exclude_dirs: tuple[str, ...]
    exclude_paths: tuple[str, ...]
    output_format: str
    sort_by: str
    sort_order: str
    limit: int
    min_size: int
    forbid_dangerous_roots: bool


def load_config(path: Path) -> Config:
    with path.open("rb") as f:
        raw = tomllib.load(f)
    scan = raw.get("scan", {})
    dele = raw.get("delete", {})
    exc = raw.get("exclude", {})
    out = raw.get("output", {})
    saf = raw.get("safety", {})
    return Config(
        root=Path(scan.get("root", ".")).expanduser(),
        follow_symlinks=bool(scan.get("follow_symlinks", False)),
        delete_dirs=tuple(dele.get("dirs", [])),
        delete_files=tuple(dele.get("files", [])),
        exclude_dirs=tuple(exc.get("dirs", [])),
        exclude_paths=tuple(exc.get("path_patterns", [])),
        output_format=str(out.get("format", "table")).lower(),
        sort_by=str(out.get("sort_by", "size")).lower(),
        sort_order=str(out.get("sort_order", "desc")).lower(),
        limit=int(out.get("limit", 0)),
        min_size=int(out.get("min_size", 0)),
        forbid_dangerous_roots=bool(saf.get("forbid_dangerous_roots", True)),
    )


# --------------------------------------------------------------------------- #
# Slow-rails: проверка корня
# --------------------------------------------------------------------------- #


def _is_dangerous_root(root: Path) -> str | None:
    """Возвращает причину отказа или None если корень безопасный."""
    root = root.resolve()
    if root == Path(root.anchor) or str(root) in {"/", ""}:
        return f"refuse to scan filesystem root: {root}"
    home = Path.home().resolve()
    if root == home:
        return f"refuse to scan $HOME directly: {root}"
    if root == Path.cwd().resolve().anchor:
        return f"refuse to scan anchor: {root}"
    return None


# --------------------------------------------------------------------------- #
# Сканирование
# --------------------------------------------------------------------------- #


@dataclass
class Target:
    """Кандидат на удаление: путь + тип + размер в байтах + число файлов."""

    path: Path
    rel: str
    kind: str  # "dir" | "file"
    pattern: str  # какой паттерн сматчился
    size: int = 0
    files: int = 0  # для каталога — число файлов внутри, для файла — 1


def _match_name(name: str, patterns: tuple[str, ...]) -> str | None:
    for pat in patterns:
        if fnmatch.fnmatch(name, pat):
            return pat
    return None


def _excluded_path(rel: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(rel, pat) for pat in patterns)


def _dir_stats(path: Path, follow_symlinks: bool) -> tuple[int, int]:
    """Возвращает (total_size_bytes, total_file_count) для каталога."""
    total_size = 0
    total_files = 0
    for dirpath, _dirnames, filenames in os.walk(path, followlinks=follow_symlinks):
        for fname in filenames:
            fp = Path(dirpath) / fname
            try:
                st = fp.lstat()
            except OSError:
                continue
            total_size += st.st_size
            total_files += 1
    return total_size, total_files


def scan(cfg: Config) -> list[Target]:
    root = cfg.root.resolve()
    if not root.exists():
        raise FileNotFoundError(f"Scan root not found: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Scan root is not a directory: {root}")

    targets: list[Target] = []
    # Используем os.walk с topdown=True, чтобы фильтровать обход и не входить
    # в exclude_dirs и в delete-каталоги (их мы сразу регистрируем целиком,
    # внутрь не лезем — экономит вызовы lstat).
    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=cfg.follow_symlinks):
        current = Path(dirpath)
        # 1) каталоги — отфильтровать to-delete и to-exclude
        keep: list[str] = []
        for d in dirnames:
            sub = current / d
            try:
                rel = sub.relative_to(root).as_posix()
            except ValueError:
                rel = sub.as_posix()

            # exclude: не входим и не удаляем
            if _match_name(d, cfg.exclude_dirs):
                continue
            if _excluded_path(rel, cfg.exclude_paths):
                continue

            # delete: регистрируем и не входим внутрь
            pat = _match_name(d, cfg.delete_dirs)
            if pat:
                size, n = _dir_stats(sub, cfg.follow_symlinks)
                targets.append(
                    Target(
                        path=sub,
                        rel=rel,
                        kind="dir",
                        pattern=pat,
                        size=size,
                        files=n,
                    )
                )
                continue

            keep.append(d)
        dirnames[:] = keep  # in-place — os.walk будет уважать

        # 2) файлы
        for fname in filenames:
            fp = current / fname
            try:
                rel = fp.relative_to(root).as_posix()
            except ValueError:
                rel = fp.as_posix()
            if _excluded_path(rel, cfg.exclude_paths):
                continue
            pat = _match_name(fname, cfg.delete_files)
            if not pat:
                continue
            try:
                size = fp.lstat().st_size
            except OSError:
                size = 0
            targets.append(
                Target(
                    path=fp,
                    rel=rel,
                    kind="file",
                    pattern=pat,
                    size=size,
                    files=1,
                )
            )

    return targets


# --------------------------------------------------------------------------- #
# Удаление
# --------------------------------------------------------------------------- #


@dataclass
class ApplyResult:
    removed: list[Target] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)  # (rel, message)


def apply_deletions(targets: list[Target]) -> ApplyResult:
    res = ApplyResult()
    for t in targets:
        try:
            if t.kind == "dir":
                shutil.rmtree(t.path)
            else:
                t.path.unlink()
            res.removed.append(t)
        except OSError as e:
            res.errors.append((t.rel, f"{type(e).__name__}: {e}"))
    return res


# --------------------------------------------------------------------------- #
# Отчёт
# --------------------------------------------------------------------------- #


def _human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f}{unit}" if unit != "B" else f"{n}B"
        n /= 1024
    return f"{n}GB"


def _sort_targets(targets: list[Target], cfg: Config) -> list[Target]:
    keyfn = {
        "size": lambda t: t.size,
        "files": lambda t: t.files,
        "path": lambda t: t.rel,
    }.get(cfg.sort_by, lambda t: t.size)
    reverse = cfg.sort_order != "asc"
    sorted_t = sorted(targets, key=keyfn, reverse=reverse)
    if cfg.min_size > 0:
        sorted_t = [t for t in sorted_t if t.size >= cfg.min_size]
    if cfg.limit > 0:
        sorted_t = sorted_t[: cfg.limit]
    return sorted_t


def render_table(
    targets: list[Target],
    apply: bool,
    result: ApplyResult | None,
) -> str:
    out = io.StringIO()

    # Сводка по паттернам
    groups: dict[str, tuple[int, int, int]] = defaultdict(lambda: (0, 0, 0))
    # pattern -> (count, total_size, total_files)
    for t in targets:
        c, s, f = groups[t.pattern]
        groups[t.pattern] = (c + 1, s + t.size, f + t.files)

    if groups:
        rows = sorted(groups.items(), key=lambda kv: kv[1][1], reverse=True)
        width = max(len(p) for p, _ in rows)
        out.write(f"{'pattern'.ljust(width)}  count  files   size\n")
        out.write(f"{'-' * width}  -----  -----  -------\n")
        for pat, (c, s, f) in rows:
            out.write(f"{pat.ljust(width)}  {c:5d}  {f:5d}  {_human(s):>7}\n")
        total_count = sum(c for c, _, _ in groups.values())
        total_size = sum(s for _, s, _ in groups.values())
        total_files = sum(f for _, _, f in groups.values())
        out.write(f"{'-' * width}  -----  -----  -------\n")
        out.write(f"{'TOTAL'.ljust(width)}  {total_count:5d}  {total_files:5d}  {_human(total_size):>7}\n")
        out.write("\n")
    else:
        out.write("nothing to clean — already tidy.\n")
        return out.getvalue()

    # Топ-цели
    head = "REMOVED" if apply else "WOULD REMOVE"
    out.write(f"{head} (top {len(targets)}):\n")
    for t in targets:
        marker = "D" if t.kind == "dir" else "F"
        out.write(f"  [{marker}] {_human(t.size):>7}  {t.rel}\n")

    # Ошибки
    if result and result.errors:
        out.write("\nERRORS:\n")
        for rel, msg in result.errors:
            out.write(f"  ! {rel}: {msg}\n")

    return out.getvalue()


def render_json(
    targets: list[Target],
    apply: bool,
    result: ApplyResult | None,
) -> str:
    payload: dict[str, object] = {
        "mode": "apply" if apply else "dry-run",
        "summary": {
            "count": len(targets),
            "total_size": sum(t.size for t in targets),
            "total_files": sum(t.files for t in targets),
        },
        "targets": [
            {
                "path": t.rel,
                "kind": t.kind,
                "pattern": t.pattern,
                "size": t.size,
                "files": t.files,
            }
            for t in targets
        ],
    }
    if result:
        payload["removed_count"] = len(result.removed)
        payload["errors"] = [{"path": rel, "message": msg} for rel, msg in result.errors]
    return json.dumps(payload, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="clean_cache",
        description="Чистка Python-кэшей и артефактов инструментов (__pycache__, .pytest_cache, *.pyc и т.п.).",
        epilog="По умолчанию работает в dry-run. Реальное удаление — флаг --apply.",
    )
    p.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="Путь к TOML-конфигу (по умолчанию рядом со скриптом).",
    )
    p.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Корень сканирования (перекрывает [scan].root).",
    )
    p.add_argument(
        "--format",
        choices=["table", "json"],
        default=None,
        help="Формат вывода (перекрывает [output].format).",
    )
    p.add_argument("--sort-by", choices=["size", "files", "path"], default=None)
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Сколько строк показать в детализации (0 = все).",
    )
    p.add_argument(
        "--min-size",
        type=int,
        default=None,
        help="Минимальный размер цели в байтах для показа.",
    )
    p.add_argument(
        "--apply",
        action="store_true",
        help="РЕАЛЬНО удалить найденное (по умолчанию — только показать).",
    )
    p.add_argument(
        "--quiet",
        action="store_true",
        help="Подавить отчёт; только exit-код. Полезно в CI.",
    )
    p.add_argument(
        "--no-safety",
        action="store_true",
        help="Отключить forbid_dangerous_roots. Использовать осознанно.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        cfg = load_config(args.config)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except tomllib.TOMLDecodeError as e:
        print(f"error: invalid TOML in {args.config}: {e}", file=sys.stderr)
        return 2

    # CLI overrides
    overrides = {}
    if args.root is not None:
        overrides["root"] = args.root
    if args.format is not None:
        overrides["output_format"] = args.format
    if args.sort_by is not None:
        overrides["sort_by"] = args.sort_by
    if args.limit is not None:
        overrides["limit"] = args.limit
    if args.min_size is not None:
        overrides["min_size"] = args.min_size
    if args.no_safety:
        overrides["forbid_dangerous_roots"] = False
    if overrides:
        cfg = Config(**{**cfg.__dict__, **overrides})

    # Slow-rails
    if cfg.forbid_dangerous_roots:
        reason = _is_dangerous_root(cfg.root)
        if reason:
            print(f"error: {reason} (use --no-safety to override)", file=sys.stderr)
            return 2

    try:
        targets = scan(cfg)
    except (FileNotFoundError, NotADirectoryError, PermissionError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    result: ApplyResult | None = None
    if args.apply and targets:
        result = apply_deletions(targets)
        # Для отчёта пересортируем по тем же правилам, но из result.removed,
        # чтобы видеть, что реально ушло. Ошибки идут отдельной секцией.
        targets_sorted = _sort_targets(result.removed, cfg)
    else:
        targets_sorted = _sort_targets(targets, cfg)

    if not args.quiet:
        if cfg.output_format == "json":
            sys.stdout.write(render_json(targets_sorted, args.apply, result))
            sys.stdout.write("\n")
        else:
            sys.stdout.write(render_table(targets_sorted, args.apply, result))

    if result and result.errors:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
