#!/usr/bin/env python3
"""lint_routing.py — строгая проверка консистентности агенты ↔ ROUTING.md.

Назначение:
    Каждое упоминание `mcp:server:tool` в `.claude/agents/**/*.md` должно
    присутствовать в `**Canonical refs:**` блоке соответствующей секции
    `### server` в `.claude/mcp/ROUTING.md`. Дрейф ломает оркестрацию.

Семантика:
    agents \\ canonical → ERROR ("agent references unknown tool")
    canonical \\ agents → WARNING ("orphan tool listed in routing")

Спецслучаи:
    - `github-mcp` имеет динамический набор tools — orphan'ы понижены
      до INFO (не ломают exit code).

Использование:
    python lint_routing.py [--quiet] [agents_dir] [routing_md]

    Дефолты путей: ../agents и ../mcp/ROUTING.md относительно скрипта.

Exit codes:
    0 — нет ERRORS (warnings — информационно, не блокируют CI; ROUTING.md
        задумана как superset документации, orphan-tools допустимы).
    1 — ERRORS найдены (агенты ссылаются на tool не описанный в ROUTING.md).
    2 — WARNINGS в `--strict` режиме (без ERRORS).

Stdlib-only. Python 3.11+. Кросс-платформа (Windows / WSL / Linux).
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

# Регексп MCP-tool ссылок в формате `mcp:server:tool`.
# server: lowercase + дефисы (qt-mcp, sequential-thinking).
# tool: alphanumeric + _- (qt_find_widget, resolve-library-id).
_TOOL_REF_RE = re.compile(r"mcp:([a-z][a-z0-9_-]*):([a-zA-Z][a-zA-Z0-9_-]*)")

# `### <server>` заголовок секции в ROUTING.md.
_SERVER_HEADING_RE = re.compile(r"^###\s+([a-z][a-z0-9_-]*)\b")

# Блок `**Canonical refs:**` после которого идёт inline-список бэктик-обёрнутых tools.
_CANONICAL_LINE_RE = re.compile(r"\*\*Canonical refs:\*\*\s*(.+)")

# Серверы с динамическим набором tools (orphan-warning подавляется).
_DYNAMIC_SERVERS: frozenset[str] = frozenset({"github-mcp", "github"})


def _parse_canonical_refs(routing_md: Path) -> dict[str, set[str]]:
    """Парсит ROUTING.md → {server: {tool, ...}} из Canonical refs блоков.

    Идём построчно, отслеживаем текущую секцию. Когда видим
    `**Canonical refs:** ...` — извлекаем все `mcp:server:tool` оттуда
    и приписываем к текущему server'у.
    """
    canonical: dict[str, set[str]] = defaultdict(set)
    current_server: str | None = None

    for line in routing_md.read_text(encoding="utf-8").splitlines():
        heading_match = _SERVER_HEADING_RE.match(line)
        if heading_match:
            current_server = heading_match.group(1)
            continue

        if current_server is None:
            continue

        canon_match = _CANONICAL_LINE_RE.search(line)
        if not canon_match:
            continue

        # Из строки Canonical refs вытаскиваем все mcp:server:tool токены.
        for tool_match in _TOOL_REF_RE.finditer(canon_match.group(1)):
            server, tool = tool_match.group(1), tool_match.group(2)
            canonical[server].add(tool)

    return dict(canonical)


def _collect_agent_refs(agents_dir: Path) -> dict[tuple[str, str], list[str]]:
    """Парсит agents/**/*.md → {(server, tool): [file:line, ...]}."""
    refs: dict[tuple[str, str], list[str]] = defaultdict(list)

    for md_path in sorted(agents_dir.rglob("*.md")):
        rel = md_path.relative_to(agents_dir.parent)
        for lineno, line in enumerate(
            md_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            for match in _TOOL_REF_RE.finditer(line):
                server, tool = match.group(1), match.group(2)
                refs[(server, tool)].append(f"{rel}:{lineno}")

    return dict(refs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "agents_dir",
        nargs="?",
        default=None,
        help="Путь к директории с агентами (default: ../agents от скрипта)",
    )
    parser.add_argument(
        "routing_md",
        nargs="?",
        default=None,
        help="Путь к ROUTING.md (default: ../mcp/ROUTING.md от скрипта)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Не печатать OK / INFO — только ERRORS / WARNINGS.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Считать WARNINGS блокирующими (exit 2 при orphan-tools). "
        "По умолчанию orphan'ы — информационно, не fail.",
    )
    args = parser.parse_args(argv)

    script_dir = Path(__file__).resolve().parent
    agents_dir = (
        Path(args.agents_dir) if args.agents_dir else script_dir.parent / "agents"
    )
    routing_md = (
        Path(args.routing_md)
        if args.routing_md
        else script_dir.parent / "mcp" / "ROUTING.md"
    )

    if not agents_dir.is_dir():
        print(f"[FAIL] agents_dir not found: {agents_dir}", file=sys.stderr)
        return 1
    if not routing_md.is_file():
        print(f"[FAIL] ROUTING.md not found: {routing_md}", file=sys.stderr)
        return 1

    canonical = _parse_canonical_refs(routing_md)
    agent_refs = _collect_agent_refs(agents_dir)

    errors: list[str] = []
    warnings: list[str] = []
    infos: list[str] = []

    # 1. agents → canonical (ERRORS)
    for (server, tool), locations in sorted(agent_refs.items()):
        if server not in canonical:
            errors.append(
                f"agent references unknown MCP server `{server}` "
                f"(tool: `{tool}`) — not in ROUTING.md\n    at: "
                + ", ".join(locations[:3])
                + ("" if len(locations) <= 3 else f" (+{len(locations) - 3} more)")
            )
            continue
        if tool not in canonical[server]:
            errors.append(
                f"agent references unknown tool `mcp:{server}:{tool}` "
                f"— not in Canonical refs for `### {server}`\n    at: "
                + ", ".join(locations[:3])
                + ("" if len(locations) <= 3 else f" (+{len(locations) - 3} more)")
            )

    # 2. canonical → agents (WARNINGS / INFOS)
    used_pairs = set(agent_refs.keys())
    for server, tools in sorted(canonical.items()):
        for tool in sorted(tools):
            if (server, tool) in used_pairs:
                continue
            msg = (
                f"orphan tool `mcp:{server}:{tool}` listed in ROUTING.md "
                f"but no agent references it"
            )
            if server in _DYNAMIC_SERVERS:
                infos.append(msg)
            else:
                warnings.append(msg)

    # Output
    n_agents = sum(len(v) for v in agent_refs.values())
    n_pairs = len(agent_refs)
    n_canon = sum(len(v) for v in canonical.values())

    if not args.quiet:
        print(
            f"[INFO] agents: {n_pairs} unique mcp:server:tool refs "
            f"({n_agents} total occurrences) across "
            f"{len(list(agents_dir.rglob('*.md')))} .md files"
        )
        print(f"[INFO] canonical: {n_canon} tools across {len(canonical)} servers")

    for msg in errors:
        print(f"[FAIL] {msg}")
    for msg in warnings:
        print(f"[WARN] {msg}")
    if not args.quiet:
        for msg in infos:
            print(f"[INFO] {msg}")

    if errors:
        print(f"\n[FAIL] {len(errors)} error(s), {len(warnings)} warning(s).")
        return 1
    if warnings and args.strict:
        print(f"\n[WARN] 0 errors, {len(warnings)} warning(s) (strict mode).")
        return 2
    if not args.quiet:
        suffix = (
            f" ({len(warnings)} orphan warning(s), non-blocking)" if warnings else ""
        )
        print(
            f"\n[OK] Routing consistency: {n_pairs} refs all canonical, 0 errors{suffix}."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
