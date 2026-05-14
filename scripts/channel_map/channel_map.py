"""
Карта IPC-каналов: кто объявляет каналы и кто шлёт сообщения.

AST-обход .py-файлов проекта. Извлекает:
- Декларации каналов:  FieldRouting(channel="X")  →  ("declaration", "X")
- Отправки:            send_message("target", msg) или send_message(target="target", ...) → ("send", "target")
- Подписки:            subscribe("X"), on_channel("X")  →  ("subscribe", "X")

Имена функций/методов конфигурируются в channel_map.toml.

Запуск:
    python scripts/channel_map/channel_map.py
    python scripts/channel_map/channel_map.py --group-by file --format json
"""

from __future__ import annotations

import argparse
import ast
import csv
import fnmatch
import io
import json
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG_PATH = Path(__file__).with_name("channel_map.toml")


# --------------------------------------------------------------------------- #
# Конфиг
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Config:
    root: Path
    recursive: bool
    follow_symlinks: bool
    exclude_dirs: tuple[str, ...]
    exclude_files: tuple[str, ...]
    exclude_paths: tuple[str, ...]
    channel_constructors: frozenset[str]
    send_methods: frozenset[str]
    subscribe_methods: frozenset[str]
    output_format: str
    group_by: str
    sort_by: str
    sort_order: str
    limit: int
    show_empty: bool


def load_config(path: Path) -> Config:
    with path.open("rb") as f:
        raw = tomllib.load(f)
    scan = raw.get("scan", {})
    exc = raw.get("exclude", {})
    det = raw.get("detect", {})
    out = raw.get("output", {})
    return Config(
        root=Path(scan.get("root", ".")).expanduser(),
        recursive=bool(scan.get("recursive", True)),
        follow_symlinks=bool(scan.get("follow_symlinks", False)),
        exclude_dirs=tuple(exc.get("dirs", [])),
        exclude_files=tuple(exc.get("file_patterns", [])),
        exclude_paths=tuple(exc.get("path_patterns", [])),
        channel_constructors=frozenset(det.get("channel_constructors", ["FieldRouting"])),
        send_methods=frozenset(det.get("send_methods", ["send_message"])),
        subscribe_methods=frozenset(det.get("subscribe_methods", [])),
        output_format=str(out.get("format", "table")).lower(),
        group_by=str(out.get("group_by", "module")).lower(),
        sort_by=str(out.get("sort_by", "total")).lower(),
        sort_order=str(out.get("sort_order", "desc")).lower(),
        limit=int(out.get("limit", 0)),
        show_empty=bool(out.get("show_empty", False)),
    )


# --------------------------------------------------------------------------- #
# Обход
# --------------------------------------------------------------------------- #


def iter_py_files(cfg: Config):
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
            elif entry.is_file() and entry.suffix == ".py":
                if any(fnmatch.fnmatch(entry.name, pat) for pat in cfg.exclude_files):
                    continue
                try:
                    rel = entry.relative_to(root).as_posix()
                except ValueError:
                    rel = entry.as_posix()
                if any(fnmatch.fnmatch(rel, pat) for pat in cfg.exclude_paths):
                    continue
                yield entry, rel


# --------------------------------------------------------------------------- #
# AST extraction
# --------------------------------------------------------------------------- #


@dataclass
class Finding:
    file: str  # relative POSIX path
    line: int
    kind: str  # "declaration" | "send" | "subscribe"
    name: str  # channel / target string ("?" если не литерал)


def _str_arg(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _callable_name(node: ast.Call) -> tuple[str, str]:
    """Возвращает (full_name, simple_name). full_name для отображения, simple — для матчинга."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id, func.id
    if isinstance(func, ast.Attribute):
        # x.y.send_message → simple = 'send_message', full примерное
        parts = []
        cur: ast.AST = func
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
        full = ".".join(reversed(parts))
        return full, func.attr
    return "<expr>", "<expr>"


def extract_findings(path: Path, rel: str, cfg: Config) -> list[Finding]:
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(path))
    except (OSError, SyntaxError):
        return []

    findings: list[Finding] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        _, simple = _callable_name(node)

        # 1) FieldRouting(channel="X")
        if simple in cfg.channel_constructors:
            for kw in node.keywords:
                if kw.arg == "channel":
                    val = _str_arg(kw.value)
                    findings.append(Finding(rel, node.lineno, "declaration", val or "?"))
                    break

        # 2) send_message(target, msg) или send_message(target="...", ...)
        if simple in cfg.send_methods:
            target: str | None = None
            # Сначала positional[0]
            if node.args:
                target = _str_arg(node.args[0])
            # Затем kwarg target / targets
            if target is None:
                for kw in node.keywords:
                    if kw.arg in ("target", "targets"):
                        if isinstance(kw.value, ast.List):
                            for elt in kw.value.elts:
                                v = _str_arg(elt)
                                if v:
                                    findings.append(Finding(rel, node.lineno, "send", v))
                            target = "<list>"  # помечено, чтобы не записать ещё раз ниже
                        else:
                            target = _str_arg(kw.value)
                        break
            if target is not None and target != "<list>":
                findings.append(Finding(rel, node.lineno, "send", target or "?"))

        # 3) subscribe("X") / on_channel("X") / register_handler("X", ...)
        if simple in cfg.subscribe_methods:
            channel: str | None = None
            if node.args:
                channel = _str_arg(node.args[0])
            if channel is None:
                for kw in node.keywords:
                    if kw.arg == "channel":
                        channel = _str_arg(kw.value)
                        break
            findings.append(Finding(rel, node.lineno, "subscribe", channel or "?"))

    return findings


# --------------------------------------------------------------------------- #
# Группировка и сводка
# --------------------------------------------------------------------------- #


@dataclass
class GroupRow:
    key: str
    declarations: set[str] = field(default_factory=set)
    sends: set[str] = field(default_factory=set)
    subscribes: set[str] = field(default_factory=set)
    files: set[str] = field(default_factory=set)

    @property
    def total(self) -> int:
        return len(self.declarations) + len(self.sends) + len(self.subscribes)


def _module_key(rel: str) -> str:
    """Эвристика группировки по модулям, инвариантная к корню сканирования.

    multiprocess_framework/modules/X/...  →  modules/X
    modules/X/...                          →  modules/X
    Services/Y/...                         →  Services/Y
    Plugins/Y/...                          →  Plugins/Y
    multiprocess_prototype/...             →  multiprocess_prototype
    Иначе — верхняя директория.
    """
    parts = rel.split("/")
    # strip prefix "multiprocess_framework" — он всё равно один на проект
    if parts and parts[0] == "multiprocess_framework":
        parts = parts[1:]
    if not parts:
        return "."
    if parts[0] == "modules" and len(parts) >= 2:
        return f"modules/{parts[1]}"
    if parts[0] in ("Services", "Plugins") and len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}"
    if parts[0] == "multiprocess_prototype":
        return "multiprocess_prototype"
    return parts[0]


def group_findings(findings: list[Finding], cfg: Config) -> list[GroupRow]:
    groups: dict[str, GroupRow] = {}

    if cfg.group_by == "role":
        # Спец-случай: суммарно по типу события, без файлов.
        roles = {"declarations": set(), "sends": set(), "subscribes": set()}
        for f in findings:
            roles[f.kind + ("s" if not f.kind.endswith("s") else "")].add(f.name)
        rows = []
        for key, names in roles.items():
            row = GroupRow(key=key)
            if key == "declarations":
                row.declarations = names
            elif key == "sends":
                row.sends = names
            else:
                row.subscribes = names
            rows.append(row)
        return rows

    for f in findings:
        if cfg.group_by == "file":
            key = f.file
        else:  # module
            key = _module_key(f.file)
        row = groups.setdefault(key, GroupRow(key=key))
        row.files.add(f.file)
        if f.kind == "declaration":
            row.declarations.add(f.name)
        elif f.kind == "send":
            row.sends.add(f.name)
        elif f.kind == "subscribe":
            row.subscribes.add(f.name)

    rows = list(groups.values())
    sort_key = {
        "total": lambda r: r.total,
        "declarations": lambda r: len(r.declarations),
        "sends": lambda r: len(r.sends),
        "subscribes": lambda r: len(r.subscribes),
        "name": lambda r: r.key,
    }.get(cfg.sort_by, lambda r: r.total)
    rows.sort(key=sort_key, reverse=(cfg.sort_order != "asc"))
    if not cfg.show_empty:
        rows = [r for r in rows if r.total > 0]
    if cfg.limit > 0:
        rows = rows[: cfg.limit]
    return rows


# --------------------------------------------------------------------------- #
# Рендеринг
# --------------------------------------------------------------------------- #


_HEADERS = ["group", "files", "decl", "sends", "subs", "channels"]


def _row_data(r: GroupRow) -> list:
    channels = sorted(r.declarations | r.sends | r.subscribes)
    preview = ", ".join(channels[:6])
    if len(channels) > 6:
        preview += f", … (+{len(channels) - 6})"
    return [r.key, len(r.files), len(r.declarations), len(r.sends), len(r.subscribes), preview]


def render_table(rows: list[GroupRow]) -> str:
    data = [_row_data(r) for r in rows]
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


def render_json(rows: list[GroupRow], findings: list[Finding]) -> str:
    payload = {
        "groups": [
            {
                "group": r.key,
                "files": sorted(r.files),
                "declarations": sorted(r.declarations),
                "sends": sorted(r.sends),
                "subscribes": sorted(r.subscribes),
            }
            for r in rows
        ],
        "findings": [{"file": f.file, "line": f.line, "kind": f.kind, "name": f.name} for f in findings],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def render_csv(findings: list[Finding]) -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["file", "line", "kind", "name"])
    for f in findings:
        w.writerow([f.file, f.line, f.kind, f.name])
    return out.getvalue()


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="channel_map", description="Карта IPC-каналов проекта.")
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    p.add_argument("--root", type=Path, default=None)
    p.add_argument("--format", choices=["table", "json", "csv"], default=None)
    p.add_argument("--group-by", choices=["file", "module", "role"], default=None)
    p.add_argument("--sort-by", choices=["total", "declarations", "sends", "subscribes", "name"], default=None)
    p.add_argument("--limit", type=int, default=None)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cfg = load_config(args.config)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    # CLI-перекрытия
    if args.root is not None:
        cfg = Config(**{**cfg.__dict__, "root": args.root})
    if args.format is not None:
        cfg = Config(**{**cfg.__dict__, "output_format": args.format})
    if args.group_by is not None:
        cfg = Config(**{**cfg.__dict__, "group_by": args.group_by})
    if args.sort_by is not None:
        cfg = Config(**{**cfg.__dict__, "sort_by": args.sort_by})
    if args.limit is not None:
        cfg = Config(**{**cfg.__dict__, "limit": args.limit})

    findings: list[Finding] = []
    try:
        for path, rel in iter_py_files(cfg):
            findings.extend(extract_findings(path, rel, cfg))
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    rows = group_findings(findings, cfg)

    if cfg.output_format == "json":
        sys.stdout.write(render_json(rows, findings))
    elif cfg.output_format == "csv":
        sys.stdout.write(render_csv(findings))
    else:
        sys.stdout.write(render_table(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
