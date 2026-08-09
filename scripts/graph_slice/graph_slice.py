"""
Срез графа graphify по границе модуля: тихая внутренность + явная граница.

Единый граф проекта (`graphify-out/graph.json`) содержит ~30k узлов, и поиск по
ключевому слову утаскивает выдачу в чужие модули через омонимы символов
(`.rollback()` есть и в logger_module, и в VersionManager). Скрипт режет граф по
префиксу пути и показывает то, что нужно перед рефакторингом:

- КТО ЗАВИСИТ ОТ МОДУЛЯ (входящие рёбра) — список тех, кого заденешь;
- ОТ ЧЕГО ЗАВИСИТ МОДУЛЬ (исходящие рёбра);
- внутренние рёбра (по флагу) — структура без внешнего шума.

Граф — снимок на момент сборки, поэтому срез всегда сверяет `built_at_commit`
с HEAD и с рабочим деревом: устаревший срез молча врёт, и это хуже отсутствия
среза.

Запуск:
    python scripts/graph_slice/graph_slice.py channel_routing_module
    python scripts/graph_slice/graph_slice.py logger_module --symbol .flush()
    python scripts/graph_slice/graph_slice.py Services/sql --format json
    python scripts/graph_slice/graph_slice.py --list
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

# Рёбра, отражающие связи в коде. Остальное (`rationale_for`, `references`) —
# рёбра из документации: полезны для чтения ADR, но при рефакторинге шумят.
CODE_RELATIONS = frozenset(
    {
        "calls",
        "indirect_call",
        "imports",
        "imports_from",
        "inherits",
        "uses",
        "re_exports",
        "method",
        "contains",
        "defines",
    }
)

DOC_RELATIONS = frozenset({"rationale_for", "references"})

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GRAPH = REPO_ROOT / "graphify-out" / "graph.json"

# Каталоги, внутри которых лежат «модули» проекта: modules/<X>, Services/<X>, …
MODULE_CONTAINERS = (
    "multiprocess_framework/modules",
    "Services",
    "Plugins",
)


# --------------------------------------------------------------------------- #
# Модель
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Node:
    id: str
    label: str
    path: str
    kind: str


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    relation: str
    path: str
    loc: str


@dataclass
class Slice:
    """Готовый срез: узлы модуля плюс рёбра, разложенные по границе."""

    target: str
    prefix: str
    nodes: dict[str, Node]
    inner: list[Edge] = field(default_factory=list)
    inbound: list[Edge] = field(default_factory=list)
    outbound: list[Edge] = field(default_factory=list)
    # владелец символа → сколько входящих рёбер у него (см. filter_by_symbol)
    owner_hint: dict[str, int] = field(default_factory=dict)


def normalize(path: str) -> str:
    return path.replace("\\", "/")


def module_of(path: str) -> str:
    """Имя модуля по пути файла — для группировки внешних зависимостей."""
    if not path:
        return "<без файла>"
    parts = normalize(path).split("/")
    for container in MODULE_CONTAINERS:
        segments = container.split("/")
        head = segments[-1]
        if head in parts:
            idx = parts.index(head)
            if idx + 1 < len(parts) and parts[: idx + 1][-len(segments) :] == segments:
                prefix = container if container != "multiprocess_framework/modules" else ""
                name = parts[idx + 1]
                return f"{prefix}/{name}".lstrip("/") if prefix else name
    return "/".join(parts[:2]) if len(parts) > 1 else parts[0]


# --------------------------------------------------------------------------- #
# Загрузка графа
# --------------------------------------------------------------------------- #


def load_graph(graph_path: Path) -> tuple[dict[str, Node], list[Edge], str]:
    if not graph_path.exists():
        raise SystemExit(
            f"[graph_slice] нет графа: {graph_path}\n"
            "  Собери его: graphify build .   (или graphify update . для обновления)"
        )
    raw = json.loads(graph_path.read_text(encoding="utf-8"))
    nodes = {
        n["id"]: Node(
            id=n["id"],
            label=n.get("label", n["id"]),
            path=normalize(n.get("source_file") or ""),
            kind=(n.get("metadata") or {}).get("kind", ""),
        )
        for n in raw["nodes"]
    }
    edges = [
        Edge(
            source=link["source"],
            target=link["target"],
            relation=link.get("relation", "?"),
            path=normalize(link.get("source_file") or ""),
            loc=link.get("source_location") or "",
        )
        for link in raw["links"]
    ]
    return nodes, edges, raw.get("built_at_commit") or ""


def discover_modules(nodes: dict[str, Node]) -> dict[str, str]:
    """Имя модуля → общий префикс пути. Только то, что реально есть в графе."""
    prefixes: dict[str, set[str]] = defaultdict(set)
    for node in nodes.values():
        if not node.path:
            continue
        for container in MODULE_CONTAINERS:
            if node.path.startswith(container + "/"):
                tail = node.path[len(container) + 1 :].split("/")
                if tail:
                    name = tail[0]
                    key = name if container.endswith("modules") else f"{container}/{name}"
                    prefixes[key].add(f"{container}/{name}")
    return {name: sorted(paths)[0] for name, paths in prefixes.items() if paths}


def resolve_target(target: str, modules: dict[str, str]) -> str:
    """Аргумент — либо имя модуля, либо произвольный префикс пути."""
    if target in modules:
        return modules[target]
    normalized = normalize(target).rstrip("/")
    for name, prefix in modules.items():
        if normalized in (prefix, name):
            return prefix
    return normalized


# --------------------------------------------------------------------------- #
# Построение среза
# --------------------------------------------------------------------------- #


def build_slice(
    target: str,
    prefix: str,
    nodes: dict[str, Node],
    edges: list[Edge],
    *,
    include_docs: bool,
    relations: frozenset[str],
) -> Slice:
    inside = {
        node_id: node
        for node_id, node in nodes.items()
        if node.path == prefix or node.path.startswith(prefix + "/")
        if include_docs or not node.path.endswith(".md")
    }
    result = Slice(target=target, prefix=prefix, nodes=inside)
    for edge in edges:
        if edge.relation not in relations:
            continue
        src_in, dst_in = edge.source in inside, edge.target in inside
        if src_in and dst_in:
            result.inner.append(edge)
        elif dst_in:
            result.inbound.append(edge)
        elif src_in:
            result.outbound.append(edge)
    return result


def filter_by_symbol(sl: Slice, symbol: str, nodes: dict[str, Node]) -> Slice:
    """Сузить срез до одного символа модуля — «кого заденет правка вот этого»."""
    needle = symbol.lower()
    picked = {
        node_id: node
        for node_id, node in sl.nodes.items()
        if needle == node.label.lower() or needle in node.label.lower()
    }
    if not picked:
        raise SystemExit(
            f"[graph_slice] символ {symbol!r} не найден в {sl.target}.\n"
            f"  Проверь имя: python {Path(__file__).name} {sl.target} --list-symbols"
        )
    narrowed = Slice(target=f"{sl.target} :: {symbol}", prefix=sl.prefix, nodes=picked)
    narrowed.inner = [e for e in sl.inner if e.source in picked or e.target in picked]
    narrowed.inbound = [e for e in sl.inbound if e.target in picked]
    narrowed.outbound = [e for e in sl.outbound if e.source in picked]

    # Граф вешает внешние вызовы на класс/файл, а не на метод: у `.flush()`
    # прямых входящих рёбер не будет, хотя снаружи её зовут. Пустой список без
    # этой оговорки читается как «никто не зависит» — и правка уезжает в прод.
    if not narrowed.inbound:
        owners: dict[str, int] = {}
        for edge in sl.inner:
            if edge.target in picked and edge.relation in ("method", "contains", "defines"):
                owner = nodes.get(edge.source)
                if owner:
                    owners[owner.label] = sum(1 for e in sl.inbound if nodes.get(e.target) is owner)
        narrowed.owner_hint = owners
    return narrowed


# --------------------------------------------------------------------------- #
# Свежесть графа
# --------------------------------------------------------------------------- #


def in_graph_scope(path: str) -> bool:
    """Тесты исключены из графа (.graphifyignore) — их правки не делают срез старым."""
    normalized = normalize(path)
    name = normalized.rsplit("/", 1)[-1]
    if "/tests/" in normalized or normalized.startswith("tests/"):
        return False
    return not (name.startswith("test_") or name.endswith("_test.py"))


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    # Только хвостовые переводы строк: `strip()` съедал ведущий пробел первой
    # строки `git status --porcelain` (" M path" → "M path"), из-за чего разбор
    # терял первый символ пути — и ровно у одного файла из списка.
    return out.stdout.strip("\r\n")


def freshness(built_at: str, prefix: str) -> dict[str, object]:
    """Насколько срез отстал от рабочего дерева именно по этому модулю."""
    head = _git("rev-parse", "HEAD")
    info: dict[str, object] = {
        "built_at": built_at[:8] if built_at else None,
        "head": head[:8] if head else None,
        "changed_since_build": [],
        "uncommitted": [],
        "stale": False,
    }
    if not built_at or not head:
        return info
    if built_at.startswith(head) or head.startswith(built_at):
        pass
    else:
        diff = _git("diff", "--name-only", built_at, "HEAD", "--", prefix)
        if diff is None:
            info["unknown_commit"] = True
        elif diff:
            info["changed_since_build"] = [f for f in diff.splitlines() if in_graph_scope(f)]
    dirty = _git("status", "--porcelain", "--", prefix)
    if dirty:
        dirty = "\n".join(line for line in dirty.splitlines() if in_graph_scope(line[2:].strip()))
    if dirty:
        # Формат porcelain: два символа статуса, дальше путь. Резать фиксированным
        # срезом нельзя — у staged-строк ширина отличается и путь теряет первый символ.
        info["uncommitted"] = [line[2:].strip() for line in dirty.splitlines() if len(line) > 2]
    info["stale"] = bool(info["changed_since_build"] or info["uncommitted"])
    return info


# --------------------------------------------------------------------------- #
# Вывод
# --------------------------------------------------------------------------- #


def group_edges(
    edges: list[Edge], nodes: dict[str, Node], inside: dict[str, Node], *, inbound: bool
) -> list[tuple[str, list[Edge]]]:
    """Сгруппировать граничные рёбра по внешнему модулю, крупные — первыми."""
    groups: dict[str, list[Edge]] = defaultdict(list)
    for edge in edges:
        outer_id = edge.source if inbound else edge.target
        outer = nodes.get(outer_id)
        groups[module_of(outer.path) if outer and outer.path else "<внешние символы>"].append(edge)
    return sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))


def describe(node_id: str, nodes: dict[str, Node]) -> str:
    node = nodes.get(node_id)
    return node.label if node else node_id


def render_text(sl: Slice, nodes: dict[str, Node], fresh: dict, args) -> str:
    out: list[str] = []
    built, head = fresh.get("built_at"), fresh.get("head")
    line = f"ГРАФ: собран на {built or '?'} | HEAD {head or '?'}"
    if fresh.get("stale"):
        parts = []
        if fresh["changed_since_build"]:
            parts.append(f"{len(fresh['changed_since_build'])} файлов изменено после сборки")
        if fresh["uncommitted"]:
            parts.append(f"{len(fresh['uncommitted'])} несохранённых")
        line += f"\n  ВНИМАНИЕ: срез может врать — {', '.join(parts)}. Обнови: graphify update ."
    elif fresh.get("unknown_commit"):
        line += "\n  (коммит сборки не найден в репозитории — свежесть не проверена)"
    out.append(line)

    out.append("")
    out.append(f"СРЕЗ {sl.target}  —  {sl.prefix}")
    out.append(
        f"  узлов {len(sl.nodes)} | внутри {len(sl.inner)} | входящих {len(sl.inbound)} | наружу {len(sl.outbound)}"
    )

    sections = []
    if not args.outbound_only:
        sections.append(("КТО ЗАВИСИТ ОТ МОДУЛЯ (входящие)", sl.inbound, True))
    if not args.inbound_only:
        sections.append(("ОТ ЧЕГО ЗАВИСИТ МОДУЛЬ (наружу)", sl.outbound, False))
    if args.inner:
        sections.append(("ВНУТРЕННИЕ СВЯЗИ", sl.inner, False))

    for title, edges, inbound in sections:
        out.append("")
        out.append(f"{title}: {len(edges)}")
        if not edges:
            out.append("  — нет")
            if inbound and sl.owner_hint:
                out.append("  ВАЖНО: это НЕ значит «никто не зависит». Граф вешает внешние вызовы")
                out.append("  на класс/файл, а не на метод. Смотри владельца символа:")
                for owner, count in sorted(sl.owner_hint.items(), key=lambda kv: -kv[1]):
                    out.append(f"      --symbol {owner}   (входящих у владельца: {count})")
            continue
        groups = group_edges(edges, nodes, sl.nodes, inbound=inbound)
        shown_groups = groups if args.all else groups[: args.top]
        for name, items in shown_groups:
            kinds = ", ".join(f"{rel} {cnt}" for rel, cnt in Counter(e.relation for e in items).most_common(4))
            out.append(f"  {name}  [{len(items)}]  {kinds}")
            limit = len(items) if args.all else args.examples
            for edge in items[:limit]:
                # Стрелка всегда по направлению самого ребра (источник → цель),
                # иначе «наружу» читается задом наперёд.
                where = f"{edge.path}:{edge.loc}" if edge.path else ""
                out.append(
                    f"      {describe(edge.source, nodes)} → {describe(edge.target, nodes)}  [{edge.relation}]  {where}"
                )
            if len(items) > limit:
                out.append(f"      … ещё {len(items) - limit} (--all)")
        if len(groups) > len(shown_groups):
            out.append(f"  … ещё {len(groups) - len(shown_groups)} групп (--top N / --all)")
    return "\n".join(out)


def render_json(sl: Slice, nodes: dict[str, Node], fresh: dict) -> str:
    def edge_dict(edge: Edge, inbound: bool) -> dict:
        outer_id = edge.source if inbound else edge.target
        outer = nodes.get(outer_id)
        return {
            # from/to — направление самого ребра; outer_* — какая сторона снаружи модуля
            "from": describe(edge.source, nodes),
            "to": describe(edge.target, nodes),
            "outer": describe(outer_id, nodes),
            "outer_module": module_of(outer.path) if outer and outer.path else None,
            "outer_file": (outer.path if outer else None) or None,
            "inner": describe(edge.target if inbound else edge.source, nodes),
            "relation": edge.relation,
            "at": f"{edge.path}:{edge.loc}" if edge.path else None,
        }

    payload = {
        "target": sl.target,
        "prefix": sl.prefix,
        "freshness": fresh,
        "counts": {
            "nodes": len(sl.nodes),
            "inner": len(sl.inner),
            "inbound": len(sl.inbound),
            "outbound": len(sl.outbound),
        },
        "dependents": [edge_dict(e, True) for e in sl.inbound],
        "dependencies": [edge_dict(e, False) for e in sl.outbound],
        "owner_hint": sl.owner_hint,
        "dependent_modules": dict(
            Counter(module_of(nodes[e.source].path) for e in sl.inbound if e.source in nodes).most_common()
        ),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="graph_slice",
        description="Срез графа graphify по границе модуля (кто зависит / от чего зависит).",
    )
    parser.add_argument("target", nargs="?", help="имя модуля или префикс пути")
    parser.add_argument("--list", action="store_true", help="показать доступные модули")
    parser.add_argument("--list-symbols", action="store_true", help="символы модуля в графе")
    parser.add_argument("--symbol", help="сузить до одного символа модуля")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--inner", action="store_true", help="показать и внутренние связи")
    parser.add_argument("--inbound-only", action="store_true", help="только зависимые от модуля")
    parser.add_argument("--outbound-only", action="store_true", help="только зависимости модуля")
    parser.add_argument("--docs", action="store_true", help="включить .md-узлы (по умолчанию нет)")
    parser.add_argument("--relations", help="фильтр рёбер через запятую, например calls,imports_from")
    parser.add_argument("--top", type=int, default=12, help="сколько групп показать (по умолч. 12)")
    parser.add_argument("--examples", type=int, default=4, help="примеров рёбер в группе")
    parser.add_argument("--all", action="store_true", help="без ограничений")
    parser.add_argument("--graph", type=Path, default=DEFAULT_GRAPH, help="путь к graph.json")
    return parser


def main(argv: list[str] | None = None) -> int:
    # Windows-консоль по умолчанию cp866: без этого русский вывод превращается
    # в мусор у любого потребителя, включая агента.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    args = build_parser().parse_args(argv)
    nodes, edges, built_at = load_graph(args.graph)
    modules = discover_modules(nodes)

    if args.list:
        counts = Counter(
            name
            for node in nodes.values()
            if node.path
            for name, prefix in modules.items()
            if node.path.startswith(prefix + "/")
        )
        for name, count in counts.most_common():
            print(f"{count:6d}  {name}")
        return 0

    if not args.target:
        build_parser().print_help()
        return 2

    prefix = resolve_target(args.target, modules)
    relations = CODE_RELATIONS | (DOC_RELATIONS if args.docs else frozenset())
    if args.relations:
        relations = frozenset(r.strip() for r in args.relations.split(",") if r.strip())

    sl = build_slice(
        args.target,
        prefix,
        nodes,
        edges,
        include_docs=args.docs,
        relations=relations,
    )
    if not sl.nodes:
        close = [name for name in modules if args.target.lower() in name.lower()]
        hint = f" Похожие: {', '.join(sorted(close)[:5])}" if close else ""
        print(
            f"[graph_slice] в графе нет узлов под префиксом {prefix!r}.{hint}\n  Список целей: --list",
            file=sys.stderr,
        )
        return 2

    if args.list_symbols:
        for node in sorted(sl.nodes.values(), key=lambda n: (n.path, n.label)):
            print(f"{node.label}\t{node.path}")
        return 0

    if args.symbol:
        sl = filter_by_symbol(sl, args.symbol, nodes)

    fresh = freshness(built_at, prefix)
    if args.format == "json":
        print(render_json(sl, nodes, fresh))
    else:
        print(render_text(sl, nodes, fresh, args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
