#!/usr/bin/env python3
"""lint_routing.py — строгая проверка консистентности агенты ↔ ROUTING.md.

Назначение:
    Каждое упоминание `mcp:server:tool` в `.claude/plugins/*/agents/**/*.md`
    должно присутствовать в `**Canonical refs:**` блоке соответствующей секции
    `### server` в `.claude/plugins/core/mcp/ROUTING.md`. Дрейф ломает оркестрацию.

Семантика:
    agents \\ canonical → ERROR ("agent references unknown tool")
    agents → disabled plugin → ERROR ("server from a plugin not enabled in
        enabled.yaml") — enabled-gate, план 2026-06-24 Task 3.2 / C1.
    canonical \\ agents → WARNING ("orphan tool listed in routing")

Обе нотации ссылок распознаются (`mcp:server:tool` и `mcp__server__tool`,
коррекция C3). Enabled-gate берёт включённый набор из enabled.yaml (авто-локация
в plugin-layout или флаг `--enabled`); если файла нет — встроенный default-on
набор (`_DEFAULT_ENABLED_PLUGINS`).

Спецслучаи:
    - `github-mcp` имеет динамический набор tools — orphan'ы понижены
      до INFO (не ломают exit code).

Использование:
    python lint_routing.py [--quiet] [agents_dir] [routing_md]

    Дефолты: агенты из .claude/plugins/*/agents/ (все плагины),
    ROUTING.md из ../mcp/ROUTING.md относительно скрипта.

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

# Вторая форма тех же ссылок: `mcp__server__tool` (двойное подчёркивание) —
# так Claude Code именует MCP-инструменты в `settings.local`, командах и у
# некоторых агентов (sci-searcher, investigator). Enabled-gate ОБЯЗАН ловить обе
# формы (план 2026-06-24, коррекция C3), иначе dunder-ссылки молча проскакивают.
# server здесь — lowercase + дефисы (без `_`, чтобы `__` оставался разделителем),
# поэтому дефисные имена (qt-mcp, ast-grep, sequential-thinking) распознаются
# корректно; tool — alphanumeric + `_-`. Не покрыт лишь гипотетический server с
# подчёркиванием внутри (в дереве таких нет).
_TOOL_REF_DUNDER_RE = re.compile(r"mcp__([a-z][a-z0-9-]*)__([a-zA-Z][a-zA-Z0-9_-]*)")

# `### <server>` заголовок секции в ROUTING.md.
_SERVER_HEADING_RE = re.compile(r"^###\s+([a-z][a-z0-9_-]*)\b")

# Блок `**Canonical refs:**` после которого идёт inline-список бэктик-обёрнутых tools.
_CANONICAL_LINE_RE = re.compile(r"\*\*Canonical refs:\*\*\s*(.+)")

# Серверы с динамическим набором tools (orphan-warning подавляется).
_DYNAMIC_SERVERS: frozenset[str] = frozenset({"github-mcp", "github"})

# ---------------------------------------------------------------------------
# Enabled-gate (план 2026-06-24, Task 3.2): ссылка агента на `mcp:*` должна
# резолвиться во ВКЛЮЧЁННЫЙ плагин (enabled.yaml), а не просто присутствовать в
# canonical ROUTING.md. Иначе агент тянет «висячий» сервер, которого нет в
# собранном `.mcp.json`.
# ---------------------------------------------------------------------------

# server_name -> plugin_id. Stdlib-дубль реестра
# `claude_kit_project.mcp_routing_block.MCP_ROUTING_REGISTRY` (этот скрипт —
# stdlib-only и едет в проект, импортировать пакет он не может). Синхронность
# гарантирует guard-тест `tests/test_lint_routing.py::test_server_plugin_map_matches_registry`.
_SERVER_TO_PLUGIN: dict[str, str] = {
    "qex": "mcp-qex",
    "sentrux": "mcp-sentrux",
    "context7": "mcp-context7",
    "serena": "mcp-serena",
    "codegraph": "mcp-codegraph",
    "ast-grep": "mcp-ast-grep",
    "graphify": "mcp-graphify",
    "github-mcp": "mcp-github",
    "qt-mcp": "mcp-qt",
    "playwright": "mcp-playwright",
    "sequential-thinking": "mcp-sequential-thinking",
    "backend-ctl": "mcp-backend-ctl",
}

# Fallback-набор включённых плагинов, когда enabled.yaml не найден (например при
# линте чистого template-дерева через синтетический agents_dir). Совпадает с
# default-on MCP-плагинами в `src/claude_kit_claude/template/enabled.yaml`
# (guard-тест `test_default_enabled_matches_template_enabled_yaml`).
_DEFAULT_ENABLED_PLUGINS: frozenset[str] = frozenset(
    {
        "mcp-qex",
        "mcp-sentrux",
        "mcp-serena",
        "mcp-context7",
        # Phase 0 (seed-max-improvement, 2026-06-29): flipped default-on.
        "mcp-ast-grep",
        "mcp-github",
    }
)


def _parse_enabled_plugin_ids(enabled_yaml: Path) -> frozenset[str] | None:
    """Минимальный stdlib-парсер enabled.yaml → set включённых plugin-id.

    Возвращает ``None``, если файл отсутствует (тогда вызывающий берёт
    :data:`_DEFAULT_ENABLED_PLUGINS`). Понимает жёсткую 2-уровневую структуру,
    которую пишет ``save_enabled`` (без PyYAML — скрипт stdlib-only):

        plugins:
          <plugin-id>:        # отступ 2
            enabled: false    # отступ 4; по умолчанию (нет строки) — enabled
            source: ...
          core: {}            # inline-пустой dict — тоже enabled

    Плагин считается включённым, если у него нет строки ``enabled: false``.
    """
    if not enabled_yaml.is_file():
        return None

    enabled: set[str] = set()
    in_plugins = False
    current: str | None = None
    current_enabled = True

    def _flush() -> None:
        nonlocal current, current_enabled
        if current is not None and current_enabled:
            enabled.add(current)
        current = None
        current_enabled = True

    for raw in enabled_yaml.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))

        if indent == 0:
            _flush()
            in_plugins = stripped.startswith("plugins:")
            continue
        if not in_plugins:
            continue

        if indent == 2 and ":" in stripped:
            # New plugin entry: `  <id>:` or inline `  <id>: {...}`. Strip a
            # trailing `# comment` first so it can't be mistaken for an inline
            # `enabled:` and so a commented inline value parses as its boolean.
            _flush()
            code = stripped.split("#", 1)[0].rstrip()
            current = code.split(":", 1)[0].strip()
            current_enabled = True
            if "enabled:" in code:  # inline `{enabled: false}` (rare)
                tail = code.split("enabled:", 1)[1].strip().rstrip("}").strip()
                current_enabled = tail.lower() not in ("false", "no", "off", "0")
        elif indent >= 4 and current is not None and stripped.startswith("enabled:"):
            # `enabled: false  # off` is False — drop the trailing comment first
            # (PyYAML reads it as the boolean; the hand parser must agree).
            val = stripped.split(":", 1)[1].split("#", 1)[0].strip().lower()
            current_enabled = val not in ("false", "no", "off", "0")

    _flush()
    return frozenset(enabled)


def _resolve_enabled_plugin_ids(
    enabled_arg: str | None, script_dir: Path, explicit_agents: bool
) -> frozenset[str]:
    """Determine the enabled plugin-id set for the enabled-gate.

    Priority: explicit ``--enabled`` path → auto-located ``enabled.yaml`` (plugin
    layout, default mode) → :data:`_DEFAULT_ENABLED_PLUGINS` fallback.
    """
    candidate: Path | None = None
    if enabled_arg:
        candidate = Path(enabled_arg)
    elif not explicit_agents:
        # Plugin layout: .claude/plugins/core/scripts/ → .claude/enabled.yaml
        plugins_root = script_dir.parent.parent
        if plugins_root.name == "plugins":
            candidate = plugins_root.parent / "enabled.yaml"

    if candidate is not None:
        parsed = _parse_enabled_plugin_ids(candidate)
        if parsed is not None:
            return parsed
    return _DEFAULT_ENABLED_PLUGINS


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


def _collect_agent_refs(
    agent_dirs: list[Path], rel_base: Path
) -> dict[tuple[str, str], list[str]]:
    """Парсит agents/**/*.md по всем плагинам → {(server, tool): [file:line, ...]}.

    *agent_dirs* — список каталогов с агентами (по одному на плагин).
    *rel_base* — база для относительных меток file:line в выводе.
    """
    refs: dict[tuple[str, str], list[str]] = defaultdict(list)

    for agents_dir in agent_dirs:
        for md_path in sorted(agents_dir.rglob("*.md")):
            try:
                rel = md_path.relative_to(rel_base)
            except ValueError:
                rel = md_path
            for lineno, line in enumerate(
                md_path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                # Both notations resolve to the same (server, tool) pair so the
                # canonical/enabled checks are form-agnostic (correction C3).
                for regex in (_TOOL_REF_RE, _TOOL_REF_DUNDER_RE):
                    for match in regex.finditer(line):
                        server, tool = match.group(1), match.group(2)
                        refs[(server, tool)].append(f"{rel.as_posix()}:{lineno}")

    return dict(refs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "agents_dir",
        nargs="?",
        default=None,
        help="Путь к директории с агентами (default: .claude/plugins/*/agents)",
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
    parser.add_argument(
        "--enabled",
        default=None,
        help="Путь к enabled.yaml для enabled-gate (default: ../../enabled.yaml "
        "от скрипта в plugin-layout; иначе встроенный default-on набор).",
    )
    args = parser.parse_args(argv)

    script_dir = Path(__file__).resolve().parent
    enabled_plugin_ids = _resolve_enabled_plugin_ids(
        args.enabled, script_dir, explicit_agents=bool(args.agents_dir)
    )
    if args.agents_dir:
        agent_dirs = [Path(args.agents_dir)]
    else:
        # Plugin layout: agents spread across .claude/plugins/<id>/agents/.
        # script lives at .claude/plugins/core/scripts/ → parent.parent == plugins/.
        plugins_root = script_dir.parent.parent
        if plugins_root.name == "plugins":
            agent_dirs = sorted(plugins_root.glob("*/agents"))
        else:
            # Legacy flat fallback: ../agents relative to the script.
            flat = script_dir.parent / "agents"
            agent_dirs = [flat] if flat.is_dir() else []
    routing_md = (
        Path(args.routing_md)
        if args.routing_md
        else script_dir.parent / "mcp" / "ROUTING.md"
    )

    agent_dirs = [d for d in agent_dirs if d.is_dir()]
    if not agent_dirs:
        print("[FAIL] agent dirs not found (.claude/plugins/*/agents)", file=sys.stderr)
        return 1
    if not routing_md.is_file():
        print(f"[FAIL] ROUTING.md not found: {routing_md}", file=sys.stderr)
        return 1

    canonical = _parse_canonical_refs(routing_md)
    agent_refs = _collect_agent_refs(agent_dirs, Path.cwd())

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

    # 1b. agents → enabled.yaml (ERRORS) — capability-driven gate (C1/C3).
    # A ref must resolve to an *enabled* plugin, not merely a canonical ROUTING
    # entry. Unknown servers (no registry mapping) are already covered by §1.
    for (server, tool), locations in sorted(agent_refs.items()):
        plugin_id = _SERVER_TO_PLUGIN.get(server)
        if plugin_id is None:
            continue
        if plugin_id not in enabled_plugin_ids:
            errors.append(
                f"agent references MCP server `{server}` from plugin `{plugin_id}` "
                f"which is not enabled in enabled.yaml — drop the ref or enable "
                f"the plugin\n    at: "
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
        n_files = sum(len(list(d.rglob("*.md"))) for d in agent_dirs)
        print(
            f"[INFO] agents: {n_pairs} unique mcp:server:tool refs "
            f"({n_agents} total occurrences) across "
            f"{n_files} .md files"
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
