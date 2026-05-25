"""
Аудит утечек secrets в исходниках по regex-паттернам.

Ловит:
- API-ключи популярных сервисов (AWS, GCP, GitHub, Slack, Stripe, OpenAI, Anthropic)
- JWT, private keys (PEM), basic-auth в URL
- Generic password/secret/token-присваивания
- High-entropy строки (опционально, для generic-паттернов)

Выход:
- exit 0 — находок нет
- exit 1 — есть утечки (для CI-pre-commit / pre-push)
- exit 2 — ошибка конфигурации/I/O (ничего не сканировалось)

Запуск:
    python scripts/secrets_audit/secrets_audit.py
    python scripts/secrets_audit/secrets_audit.py --format json
    python scripts/secrets_audit/secrets_audit.py --root src --limit 10

Allowlist в строке (inline-suppression):
    api_key = "AKIAEXAMPLE..."  # secrets-audit: ignore
"""

from __future__ import annotations

import argparse
import csv
import fnmatch
import io
import json
import math
import re
import sys
import tomllib
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG_PATH = Path(__file__).with_name("secrets_audit.toml")
INLINE_SUPPRESS = "secrets-audit: ignore"


@dataclass(frozen=True)
class Pattern:
    name: str
    regex: re.Pattern[str]
    entropy_check: bool
    min_entropy: float


@dataclass(frozen=True)
class Config:
    root: Path
    recursive: bool
    follow_symlinks: bool
    include: frozenset[str]
    exclude_dirs: tuple[str, ...]
    exclude_files: tuple[str, ...]
    exclude_paths: tuple[str, ...]
    patterns: tuple[Pattern, ...]
    default_min_entropy: float
    output_format: str
    group_by: str
    sort_by: str
    limit: int
    max_text: int
    strict: bool


def _shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    freq: dict[str, int] = defaultdict(int)
    for c in s:
        freq[c] += 1
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in freq.values())


def load_config(path: Path) -> Config:
    with path.open("rb") as f:
        raw = tomllib.load(f)
    scan = raw.get("scan", {})
    fmt = raw.get("formats", {})
    exc = raw.get("exclude", {})
    det = raw.get("detect", {})
    out = raw.get("output", {})

    default_min_entropy = float(det.get("default_min_entropy", 4.0))
    patterns_raw = det.get("patterns", [])
    patterns: list[Pattern] = []
    for p in patterns_raw:
        name = str(p.get("name", "unnamed"))
        regex_str = p.get("regex")
        if not regex_str:
            continue
        try:
            flags = re.IGNORECASE if p.get("ignore_case", False) else 0
            compiled = re.compile(regex_str, flags)
        except re.error as e:
            print(f"warn: bad regex for pattern {name!r}: {e}", file=sys.stderr)
            continue
        patterns.append(
            Pattern(
                name=name,
                regex=compiled,
                entropy_check=bool(p.get("entropy_check", False)),
                min_entropy=float(p.get("min_entropy", default_min_entropy)),
            )
        )

    return Config(
        root=Path(scan.get("root", ".")).expanduser(),
        recursive=bool(scan.get("recursive", True)),
        follow_symlinks=bool(scan.get("follow_symlinks", False)),
        include=frozenset(ext.lower() for ext in fmt.get("include", [])),
        exclude_dirs=tuple(exc.get("dirs", [])),
        exclude_files=tuple(exc.get("file_patterns", [])),
        exclude_paths=tuple(exc.get("path_patterns", [])),
        patterns=tuple(patterns),
        default_min_entropy=default_min_entropy,
        output_format=str(out.get("format", "table")).lower(),
        group_by=str(out.get("group_by", "pattern")).lower(),
        sort_by=str(out.get("sort_by", "file")).lower(),
        limit=int(out.get("limit", 0)),
        max_text=int(out.get("max_text", 80)),
        strict=bool(out.get("strict", True)),
    )


# --------------------------------------------------------------------------- #
# Сканирование
# --------------------------------------------------------------------------- #


@dataclass
class Finding:
    file: str
    line: int
    pattern: str
    match: str
    entropy: float
    text: str


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


def scan_file(path: Path, rel: str, cfg: Config) -> list[Finding]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    findings: list[Finding] = []
    for i, line in enumerate(text.splitlines(), start=1):
        if INLINE_SUPPRESS in line:
            continue
        for pat in cfg.patterns:
            for m in pat.regex.finditer(line):
                matched = m.group(0)
                entropy = _shannon_entropy(matched)
                if pat.entropy_check and entropy < pat.min_entropy:
                    continue
                rest = line.strip()
                if len(rest) > cfg.max_text:
                    rest = rest[: cfg.max_text - 1] + "…"
                findings.append(
                    Finding(
                        file=rel,
                        line=i,
                        pattern=pat.name,
                        match=matched[:40] + "…" if len(matched) > 40 else matched,
                        entropy=round(entropy, 2),
                        text=rest,
                    )
                )
    return findings


# --------------------------------------------------------------------------- #
# Рендеринг
# --------------------------------------------------------------------------- #


def _sort_findings(findings: list[Finding], cfg: Config) -> list[Finding]:
    sort_key = {
        "file": lambda f: (f.file, f.line),
        "pattern": lambda f: f.pattern,
        "entropy": lambda f: -f.entropy,
    }.get(cfg.sort_by, lambda f: (f.file, f.line))
    findings = sorted(findings, key=sort_key)
    if cfg.limit > 0:
        findings = findings[: cfg.limit]
    return findings


def render_table(findings: list[Finding]) -> str:
    if not findings:
        return "OK: утечек не найдено.\n"
    headers = ["pattern", "entropy", "file:line", "match", "text"]
    data = [[f.pattern, f"{f.entropy:.2f}", f"{f.file}:{f.line}", f.match, f.text] for f in findings]
    widths = [len(c) for c in headers]
    for row in data:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    out = io.StringIO()
    sep = "  "
    out.write(sep.join(h.ljust(widths[i]) for i, h in enumerate(headers)) + "\n")
    out.write(sep.join("-" * w for w in widths) + "\n")
    for row in data:
        out.write(sep.join(str(cell).ljust(widths[i]) for i, cell in enumerate(row)) + "\n")
    return out.getvalue()


def render_summary(findings: list[Finding], cfg: Config) -> str:
    if not findings or cfg.group_by == "none":
        return ""
    if cfg.group_by == "pattern":
        groups: dict[str, int] = defaultdict(int)
        for f in findings:
            groups[f.pattern] += 1
        title = "Pattern"
    elif cfg.group_by == "file":
        groups = defaultdict(int)
        for f in findings:
            groups[f.file] += 1
        title = "File"
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


def render_json(findings: list[Finding]) -> str:
    return json.dumps(
        {
            "summary": {"total": len(findings)},
            "findings": [f.__dict__ for f in findings],
        },
        ensure_ascii=False,
        indent=2,
    )


def render_csv(findings: list[Finding]) -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["pattern", "entropy", "file", "line", "match", "text"])
    for f in findings:
        w.writerow([f.pattern, f.entropy, f.file, f.line, f.match, f.text])
    return out.getvalue()


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="secrets_audit", description="Аудит утечек secrets по regex.")
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    p.add_argument("--root", type=Path, default=None)
    p.add_argument("--format", choices=["table", "json", "csv"], default=None)
    p.add_argument("--group-by", choices=["pattern", "file", "none"], default=None)
    p.add_argument("--sort-by", choices=["file", "pattern", "entropy"], default=None)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument(
        "--no-strict",
        action="store_true",
        help="Не падать с exit 1 при находках (только отчёт).",
    )
    return p


def _force_utf8_stdout() -> None:
    """Зафиксировать UTF-8 для stdout/stderr (Windows cp1251 fix)."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdout()
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
    if args.no_strict:
        overrides["strict"] = False
    if overrides:
        cfg = Config(**{**cfg.__dict__, **overrides})

    if not cfg.patterns:
        print("error: ни одного паттерна не загружено из конфига", file=sys.stderr)
        return 2

    findings: list[Finding] = []
    try:
        for path, rel in iter_files(cfg):
            findings.extend(scan_file(path, rel, cfg))
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    findings = _sort_findings(findings, cfg)

    if cfg.output_format == "json":
        sys.stdout.write(render_json(findings))
    elif cfg.output_format == "csv":
        sys.stdout.write(render_csv(findings))
    else:
        sys.stdout.write(render_summary(findings, cfg))
        sys.stdout.write(render_table(findings))

    if findings and cfg.strict:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
