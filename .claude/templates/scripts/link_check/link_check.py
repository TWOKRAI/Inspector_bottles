"""
Проверка Markdown-ссылок: относительные пути, anchor'ы, опционально внешние URL.

Запуск:
    python scripts/link_check/link_check.py
    python scripts/link_check/link_check.py --external          # включить HEAD-запросы
    python scripts/link_check/link_check.py --format json --no-strict

Inline-suppression: HTML-комментарий <!-- link-check: ignore --> в той же строке.

Exit:
    0 — все ссылки валидны
    1 — найдены битые (под strict=true)
    2 — ошибка конфигурации/I/O
"""

from __future__ import annotations

import argparse
import csv
import fnmatch
import io
import json
import re
import sys
import time
import tomllib
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlparse

DEFAULT_CONFIG_PATH = Path(__file__).with_name("link_check.toml")
INLINE_SUPPRESS = "link-check: ignore"

# [text](url)  +  [text](url "title")
_MD_LINK = re.compile(r"\[(?P<text>[^\]]*)\]\((?P<url>[^)\s]+)(?:\s+\"[^\"]*\")?\)")
# <url> autolink (только URL, не email)
_AUTOLINK = re.compile(r"<(?P<url>https?://[^>]+)>")
# Markdown заголовки (## Heading)
_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)
# Inline-код: `...` — содержимое не парсится как ссылка.
# Парные backticks (`` ` ``) подхватываются как пары одиночных совпадений.
_INLINE_CODE = re.compile(r"`[^`]*`")


@dataclass(frozen=True)
class Config:
    root: Path
    recursive: bool
    follow_symlinks: bool
    include: frozenset[str]
    exclude_dirs: tuple[str, ...]
    exclude_files: tuple[str, ...]
    exclude_paths: tuple[str, ...]
    check_relative: bool
    check_anchor: bool
    check_external: bool
    timeout_sec: int
    user_agent: str
    allowed_schemes: frozenset[str]
    exclude_url_patterns: tuple[re.Pattern[str], ...]
    output_format: str
    group_by: str
    sort_by: str
    limit: int
    max_text: int
    strict: bool


def load_config(path: Path) -> Config:
    with path.open("rb") as f:
        raw = tomllib.load(f)
    scan = raw.get("scan", {})
    fmt = raw.get("formats", {})
    exc = raw.get("exclude", {})
    chk = raw.get("check", {})
    out = raw.get("output", {})

    url_excludes = []
    for s in chk.get("exclude_url_patterns", []):
        try:
            url_excludes.append(re.compile(s))
        except re.error as e:
            print(f"warn: bad URL exclude regex {s!r}: {e}", file=sys.stderr)

    return Config(
        root=Path(scan.get("root", ".")).expanduser(),
        recursive=bool(scan.get("recursive", True)),
        follow_symlinks=bool(scan.get("follow_symlinks", False)),
        include=frozenset(ext.lower() for ext in fmt.get("include", [".md"])),
        exclude_dirs=tuple(exc.get("dirs", [])),
        exclude_files=tuple(exc.get("file_patterns", [])),
        exclude_paths=tuple(exc.get("path_patterns", [])),
        check_relative=bool(chk.get("relative", True)),
        check_anchor=bool(chk.get("anchor", True)),
        check_external=bool(chk.get("external", False)),
        timeout_sec=int(chk.get("timeout_sec", 5)),
        user_agent=str(chk.get("user_agent", "link_check/1.0")),
        allowed_schemes=frozenset(chk.get("allowed_schemes", ["http", "https"])),
        exclude_url_patterns=tuple(url_excludes),
        output_format=str(out.get("format", "table")).lower(),
        group_by=str(out.get("group_by", "kind")).lower(),
        sort_by=str(out.get("sort_by", "file")).lower(),
        limit=int(out.get("limit", 0)),
        max_text=int(out.get("max_text", 80)),
        strict=bool(out.get("strict", True)),
    )


@dataclass
class Issue:
    file: str
    line: int
    url: str
    kind: str  # missing_file | missing_anchor | http_error | bad_scheme | timeout
    detail: str


@dataclass
class FileIndex:
    headings: dict[str, set[str]] = field(default_factory=dict)  # rel_path → set(slug)


def _slugify(heading: str) -> str:
    h = heading.strip().lower()
    h = re.sub(r"[^\w\s-]", "", h, flags=re.UNICODE)
    h = re.sub(r"[\s_]+", "-", h)
    return h.strip("-")


def _headings_in(path: Path) -> set[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    return {_slugify(m.group(1)) for m in _HEADING.finditer(text)}


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
                if any(fnmatch.fnmatch(entry.name, p) for p in cfg.exclude_dirs):
                    continue
                if cfg.recursive:
                    stack.append(entry)
            elif entry.is_file():
                ext = entry.suffix.lower()
                if cfg.include and ext not in cfg.include:
                    continue
                if any(fnmatch.fnmatch(entry.name, p) for p in cfg.exclude_files):
                    continue
                try:
                    rel = entry.relative_to(root).as_posix()
                except ValueError:
                    rel = entry.as_posix()
                if any(fnmatch.fnmatch(rel, p) for p in cfg.exclude_paths):
                    continue
                yield entry, rel


def _check_external(url: str, cfg: Config, cache: dict[str, tuple[int, str]]) -> tuple[bool, str]:
    if url in cache:
        ok, detail = cache[url]
        return bool(ok), detail
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": cfg.user_agent})
    try:
        with urllib.request.urlopen(req, timeout=cfg.timeout_sec) as resp:
            ok = 200 <= resp.status < 400
            detail = f"HTTP {resp.status}"
    except urllib.error.HTTPError as e:
        # Many sites reject HEAD — retry GET
        if e.code in (403, 405):
            try:
                req2 = urllib.request.Request(url, headers={"User-Agent": cfg.user_agent})
                with urllib.request.urlopen(req2, timeout=cfg.timeout_sec) as resp:
                    ok = 200 <= resp.status < 400
                    detail = f"HTTP {resp.status}"
            except Exception as e2:
                ok = False
                detail = f"{type(e2).__name__}: {e2}"
        else:
            ok = False
            detail = f"HTTP {e.code}"
    except urllib.error.URLError as e:
        ok = False
        detail = f"URLError: {e.reason}"
    except (TimeoutError, OSError) as e:
        ok = False
        detail = f"{type(e).__name__}: {e}"
    cache[url] = (1 if ok else 0, detail)
    return ok, detail


def check_file(
    path: Path,
    rel: str,
    cfg: Config,
    headings_cache: dict[Path, set[str]],
    http_cache: dict[str, tuple[int, str]],
) -> list[Issue]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    issues: list[Issue] = []
    in_fence = False
    for i, line in enumerate(text.splitlines(), start=1):
        # Fenced code блоки ``` или ~~~ — содержимое пропускаем
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if INLINE_SUPPRESS in line:
            continue
        # Inline-код `...` → стираем, чтобы не ловить ссылки в примерах синтаксиса
        clean = _INLINE_CODE.sub("", line)
        urls: list[str] = []
        urls.extend(m.group("url") for m in _MD_LINK.finditer(clean))
        urls.extend(m.group("url") for m in _AUTOLINK.finditer(clean))
        for url in urls:
            issue = _check_one(url, path, rel, i, cfg, headings_cache, http_cache)
            if issue is not None:
                issues.append(issue)
    return issues


def _check_one(
    url: str,
    file: Path,
    rel: str,
    lineno: int,
    cfg: Config,
    headings_cache: dict[Path, set[str]],
    http_cache: dict[str, tuple[int, str]],
) -> Issue | None:
    if any(p.search(url) for p in cfg.exclude_url_patterns):
        return None

    # fragment-only: #anchor → check in same file
    if url.startswith("#"):
        if not cfg.check_anchor:
            return None
        slug = url[1:]
        if file not in headings_cache:
            headings_cache[file] = _headings_in(file)
        if slug and slug not in headings_cache[file]:
            return Issue(rel, lineno, url, "missing_anchor", f"anchor #{slug} not in {rel}")
        return None

    parsed = urlparse(url)
    if parsed.scheme in ("mailto", "tel"):
        return None
    if parsed.scheme in ("http", "https"):
        if not cfg.check_external:
            return None
        if parsed.scheme not in cfg.allowed_schemes:
            return Issue(rel, lineno, url, "bad_scheme", f"scheme {parsed.scheme!r} not allowed")
        ok, detail = _check_external(url, cfg, http_cache)
        if not ok:
            return Issue(rel, lineno, url, "http_error", detail)
        return None
    if parsed.scheme and parsed.scheme not in cfg.allowed_schemes:
        return Issue(rel, lineno, url, "bad_scheme", f"scheme {parsed.scheme!r} not allowed")

    # relative path (no scheme, no host)
    if not cfg.check_relative:
        return None
    path_part, _, anchor = url.partition("#")
    path_part = unquote(path_part)
    if not path_part:
        return None
    target = (file.parent / path_part).resolve()
    if not target.exists():
        return Issue(rel, lineno, url, "missing_file", f"path {path_part!r} not found")
    if anchor and cfg.check_anchor and target.suffix.lower() == ".md":
        if target not in headings_cache:
            headings_cache[target] = _headings_in(target)
        if anchor not in headings_cache[target]:
            return Issue(
                rel,
                lineno,
                url,
                "missing_anchor",
                f"anchor #{anchor} not in {path_part}",
            )
    return None


def _sort_issues(issues: list[Issue], cfg: Config) -> list[Issue]:
    key = {
        "file": lambda x: (x.file, x.line),
        "kind": lambda x: x.kind,
        "url": lambda x: x.url,
    }.get(cfg.sort_by, lambda x: (x.file, x.line))
    out = sorted(issues, key=key)
    return out[: cfg.limit] if cfg.limit > 0 else out


def render_table(issues: list[Issue]) -> str:
    if not issues:
        return "OK: битых ссылок не найдено.\n"
    headers = ["kind", "file:line", "url", "detail"]
    data = [[i.kind, f"{i.file}:{i.line}", i.url, i.detail] for i in issues]
    widths = [len(h) for h in headers]
    for row in data:
        for j, c in enumerate(row):
            widths[j] = max(widths[j], len(str(c)))
    buf = io.StringIO()
    sep = "  "
    buf.write(sep.join(h.ljust(widths[j]) for j, h in enumerate(headers)) + "\n")
    buf.write(sep.join("-" * w for w in widths) + "\n")
    for row in data:
        buf.write(sep.join(str(c).ljust(widths[j]) for j, c in enumerate(row)) + "\n")
    return buf.getvalue()


def render_summary(issues: list[Issue], cfg: Config) -> str:
    if not issues or cfg.group_by == "none":
        return ""
    counts: dict[str, int] = defaultdict(int)
    key_fn = (lambda i: i.kind) if cfg.group_by == "kind" else (lambda i: i.file)
    for i in issues:
        counts[key_fn(i)] += 1
    title = "Kind" if cfg.group_by == "kind" else "File"
    rows = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    width = max((len(k) for k, _ in rows), default=len(title))
    buf = io.StringIO()
    buf.write(f"{title.ljust(width)}  count\n")
    buf.write("-" * width + "  -----\n")
    for k, v in rows:
        buf.write(f"{k.ljust(width)}  {v}\n")
    buf.write("\n")
    return buf.getvalue()


def render_json(issues: list[Issue]) -> str:
    return json.dumps(
        {"summary": {"total": len(issues)}, "issues": [i.__dict__ for i in issues]},
        ensure_ascii=False,
        indent=2,
    )


def render_csv(issues: list[Issue]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["kind", "file", "line", "url", "detail"])
    for i in issues:
        w.writerow([i.kind, i.file, i.line, i.url, i.detail])
    return buf.getvalue()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="link_check", description="Проверка Markdown-ссылок.")
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    p.add_argument("--root", type=Path, default=None)
    p.add_argument("--format", choices=["table", "json", "csv"], default=None)
    p.add_argument("--group-by", choices=["kind", "file", "none"], default=None)
    p.add_argument("--sort-by", choices=["file", "kind", "url"], default=None)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--external", action="store_true", help="Включить HEAD-проверку HTTP-ссылок.")
    p.add_argument(
        "--no-external",
        action="store_true",
        help="Не проверять HTTP (перекрывает --external и конфиг).",
    )
    p.add_argument("--no-anchor", action="store_true", help="Не проверять anchor'ы.")
    p.add_argument("--no-strict", action="store_true", help="Не падать с exit 1 при находках.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cfg = load_config(args.config)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    overrides: dict = {}
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
    if args.external:
        overrides["check_external"] = True
    if args.no_external:
        overrides["check_external"] = False
    if args.no_anchor:
        overrides["check_anchor"] = False
    if args.no_strict:
        overrides["strict"] = False
    if overrides:
        cfg = Config(**{**cfg.__dict__, **overrides})

    headings_cache: dict[Path, set[str]] = {}
    http_cache: dict[str, tuple[int, str]] = {}
    started = time.time()

    issues: list[Issue] = []
    try:
        for path, rel in iter_files(cfg):
            issues.extend(check_file(path, rel, cfg, headings_cache, http_cache))
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    issues = _sort_issues(issues, cfg)
    elapsed = time.time() - started

    if cfg.output_format == "json":
        sys.stdout.write(render_json(issues))
    elif cfg.output_format == "csv":
        sys.stdout.write(render_csv(issues))
    else:
        sys.stdout.write(render_summary(issues, cfg))
        sys.stdout.write(render_table(issues))
        if cfg.check_external:
            sys.stdout.write(f"\nElapsed: {elapsed:.1f}s, HTTP-checks: {len(http_cache)}\n")

    if issues and cfg.strict:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
