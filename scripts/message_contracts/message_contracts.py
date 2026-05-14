"""
Дамп контрактов сообщений: классы-наследники SchemaBase / Message / BaseModel
со списком type-annotated полей.

Чисто AST, без импорта проекта (безопасно — не запускает код).
Базовый класс сопоставляется по простому имени (последний сегмент),
поэтому aliasing типа `from x import SchemaBase as SB` не сработает —
такие случаи редки, и их видно вручную.

Запуск:
    python scripts/message_contracts/message_contracts.py
    python scripts/message_contracts/message_contracts.py --group-by base --format json
    python scripts/message_contracts/message_contracts.py --root multiprocess_framework
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

DEFAULT_CONFIG_PATH = Path(__file__).with_name("message_contracts.toml")


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
    base_classes: frozenset[str]
    ignore_name_prefixes: tuple[str, ...]
    include_nested: bool
    output_format: str
    group_by: str
    sort_by: str
    sort_order: str
    limit: int
    show_fields: bool
    max_fields_preview: int


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
        base_classes=frozenset(det.get("base_classes", ["SchemaBase"])),
        ignore_name_prefixes=tuple(det.get("ignore_name_prefixes", [])),
        include_nested=bool(det.get("include_nested", False)),
        output_format=str(out.get("format", "table")).lower(),
        group_by=str(out.get("group_by", "class")).lower(),
        sort_by=str(out.get("sort_by", "fields")).lower(),
        sort_order=str(out.get("sort_order", "desc")).lower(),
        limit=int(out.get("limit", 0)),
        show_fields=bool(out.get("show_fields", True)),
        max_fields_preview=int(out.get("max_fields_preview", 8)),
    )


# --------------------------------------------------------------------------- #
# Обход (как в channel_map)
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
class FieldInfo:
    name: str
    type: str
    default: str | None = None


@dataclass
class ClassContract:
    name: str
    file: str
    line: int
    bases: list[str]
    matched_base: str
    fields: list[FieldInfo] = field(default_factory=list)


def _base_name(node: ast.expr) -> str:
    """Имя базового класса для отображения и для матчинга по простому имени."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        # x.y.SchemaBase → SchemaBase
        parts = []
        cur: ast.AST = node
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
        return ".".join(reversed(parts))
    if isinstance(node, ast.Subscript):
        return _base_name(node.value)  # Generic[T] → имя контейнера
    return ast.unparse(node) if hasattr(ast, "unparse") else "<?>"


def _simple_name(full: str) -> str:
    return full.rsplit(".", 1)[-1]


def _type_str(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:
        return "<?>"


def _default_str(node: ast.AST | None) -> str | None:
    if node is None:
        return None
    try:
        return ast.unparse(node)
    except Exception:
        return "<?>"


def extract_contracts(path: Path, rel: str, cfg: Config) -> list[ClassContract]:
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(path))
    except (OSError, SyntaxError):
        return []

    contracts: list[ClassContract] = []

    def visit(node: ast.AST, depth: int) -> None:
        if isinstance(node, ast.ClassDef):
            if depth > 0 and not cfg.include_nested:
                return
            bases_full = [_base_name(b) for b in node.bases]
            simple_bases = {_simple_name(b) for b in bases_full}
            matched = simple_bases & cfg.base_classes
            if matched:
                if any(node.name.startswith(p) for p in cfg.ignore_name_prefixes):
                    pass  # игнор по префиксу — не добавляем
                else:
                    fields_list: list[FieldInfo] = []
                    for stmt in node.body:
                        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                            fields_list.append(
                                FieldInfo(
                                    name=stmt.target.id,
                                    type=_type_str(stmt.annotation),
                                    default=_default_str(stmt.value),
                                )
                            )
                    contracts.append(
                        ClassContract(
                            name=node.name,
                            file=rel,
                            line=node.lineno,
                            bases=bases_full,
                            matched_base=sorted(matched)[0],
                            fields=fields_list,
                        )
                    )
            # глубже — только если разрешено
            if cfg.include_nested:
                for child in ast.iter_child_nodes(node):
                    visit(child, depth + 1)
        else:
            for child in ast.iter_child_nodes(node):
                visit(child, depth)

    visit(tree, 0)
    return contracts


# --------------------------------------------------------------------------- #
# Группировка и рендер
# --------------------------------------------------------------------------- #


def _module_key(rel: str) -> str:
    parts = rel.split("/")
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


def _sort_contracts(contracts: list[ClassContract], cfg: Config) -> list[ClassContract]:
    sort_key = {
        "fields": lambda c: len(c.fields),
        "name": lambda c: c.name,
        "module": lambda c: _module_key(c.file),
    }.get(cfg.sort_by, lambda c: len(c.fields))
    contracts = sorted(contracts, key=sort_key, reverse=(cfg.sort_order != "asc"))
    if cfg.limit > 0:
        contracts = contracts[: cfg.limit]
    return contracts


def render_table(contracts: list[ClassContract], cfg: Config) -> str:
    headers = ["class", "base", "module", "fields"]
    if cfg.show_fields:
        headers.append("preview")

    rows = []
    for c in contracts:
        preview = ""
        if cfg.show_fields:
            shown = c.fields[: cfg.max_fields_preview]
            preview = ", ".join(f"{f.name}:{f.type}" for f in shown)
            if len(c.fields) > cfg.max_fields_preview:
                preview += f", … (+{len(c.fields) - cfg.max_fields_preview})"
        row = [c.name, c.matched_base, _module_key(c.file), len(c.fields)]
        if cfg.show_fields:
            row.append(preview)
        rows.append(row)

    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(f"{cell:,}" if isinstance(cell, int) else str(cell)))

    out = io.StringIO()
    sep = "  "
    out.write(sep.join(h.ljust(widths[i]) for i, h in enumerate(headers)) + "\n")
    out.write(sep.join("-" * w for w in widths) + "\n")
    for row in rows:
        cells = []
        for i, cell in enumerate(row):
            if isinstance(cell, int):
                cells.append(f"{cell:,}".rjust(widths[i]))
            else:
                cells.append(str(cell).ljust(widths[i]))
        out.write(sep.join(cells) + "\n")
    return out.getvalue()


def render_json(contracts: list[ClassContract], cfg: Config) -> str:
    if cfg.group_by == "base":
        groups: dict[str, list] = {}
        for c in contracts:
            groups.setdefault(c.matched_base, []).append(c.name)
        return json.dumps({"by_base": groups, "count": len(contracts)}, ensure_ascii=False, indent=2)
    if cfg.group_by == "module":
        groups: dict[str, list] = {}
        for c in contracts:
            groups.setdefault(_module_key(c.file), []).append(
                {
                    "name": c.name,
                    "fields": [f.__dict__ for f in c.fields],
                }
            )
        return json.dumps({"by_module": groups, "count": len(contracts)}, ensure_ascii=False, indent=2)
    payload = [
        {
            "name": c.name,
            "base": c.matched_base,
            "bases": c.bases,
            "file": c.file,
            "line": c.line,
            "fields": [f.__dict__ for f in c.fields],
        }
        for c in contracts
    ]
    return json.dumps(payload, ensure_ascii=False, indent=2)


def render_csv(contracts: list[ClassContract]) -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["class", "base", "file", "line", "field", "type", "default"])
    for c in contracts:
        if not c.fields:
            w.writerow([c.name, c.matched_base, c.file, c.line, "", "", ""])
            continue
        for f in c.fields:
            w.writerow([c.name, c.matched_base, c.file, c.line, f.name, f.type, f.default or ""])
    return out.getvalue()


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="message_contracts", description="Дамп контрактов SchemaBase/Message/BaseModel.")
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    p.add_argument("--root", type=Path, default=None)
    p.add_argument("--format", choices=["table", "json", "csv"], default=None)
    p.add_argument("--group-by", choices=["class", "module", "base"], default=None)
    p.add_argument("--sort-by", choices=["fields", "name", "module"], default=None)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--no-fields", action="store_true", help="Не показывать превью полей в table.")
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
    if args.no_fields:
        overrides["show_fields"] = False
    if overrides:
        cfg = Config(**{**cfg.__dict__, **overrides})

    contracts: list[ClassContract] = []
    try:
        for path, rel in iter_py_files(cfg):
            contracts.extend(extract_contracts(path, rel, cfg))
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    contracts = _sort_contracts(contracts, cfg)

    if cfg.output_format == "json":
        sys.stdout.write(render_json(contracts, cfg))
    elif cfg.output_format == "csv":
        sys.stdout.write(render_csv(contracts))
    else:
        sys.stdout.write(render_table(contracts, cfg))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
