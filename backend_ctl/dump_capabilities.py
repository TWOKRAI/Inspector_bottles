# -*- coding: utf-8 -*-
"""Статический дамп «контактной книжки» бэкенда (Ф1 Task 1.9, capability manifest v1).

Поднимает прототип headless через :class:`BackendHarness`, собирает свод
``driver.capabilities()`` (fan-out introspect.capabilities по всем процессам)
и пишет два артефакта:

  - ``docs/contracts/CAPABILITIES.yaml`` — машиночитаемый каталог (для агентов/CI);
  - ``docs/contracts/CAPABILITIES.md``  — «книжка» для людей и агентов.

Правило (capability-manifest-idea.md): книжка ГЕНЕРИРУЕТСЯ, руками не пишется.
Дамп детерминирован: только контракт (команды+descriptions, регистры-поля,
handlers, топология, каналы), никаких runtime-значений и timestamp'ов.

Запуск:
    python -m backend_ctl.dump_capabilities              # перегенерировать файлы
    python -m backend_ctl.dump_capabilities --check      # CI-gate: дрейф = exit 2

CI-gate: live-тест ``test_capabilities.py::test_dump_matches_committed`` сравнивает
runtime-свод с закоммиченным YAML — дрейф код⇄документ валит сьют.
"""

from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from backend_ctl.driver import Capabilities

#: Версия схемы дампа (v1 — с params_schema из реестра контрактов, Ф4.2 шаг 6).
DUMP_VERSION = 1

#: Дефолтное место артефактов (относительно корня репозитория).
DEFAULT_OUT_DIR = Path("docs/contracts")
YAML_NAME = "CAPABILITIES.yaml"
MD_NAME = "CAPABILITIES.md"


# ---------------------------------------------------------------------------
# Чистые преобразования: Capabilities → dump-dict → yaml/md (тестируются юнитом)
# ---------------------------------------------------------------------------


def _command_dump(c: Dict[str, Any]) -> Dict[str, Any]:
    """Детерминированная запись одной команды для дампа.

    ``params_schema`` (Ф4.2 шаг 6) добавляется ТОЛЬКО если карточка его несёт —
    команды без контракта остаются {name, description, tags} (обратная совместимость).
    """
    entry: Dict[str, Any] = {
        "name": str(c.get("name") or ""),
        "description": str(c.get("description") or ""),
        "tags": sorted(c.get("tags") or []),
    }
    ps = c.get("params_schema")
    if isinstance(ps, list) and ps:
        entry["params_schema"] = sorted(
            (
                {
                    "name": str(f.get("name") or ""),
                    "type": str(f.get("type") or ""),
                    "required": bool(f.get("required")),
                }
                for f in ps
                if isinstance(f, dict)
            ),
            key=lambda f: f["name"],
        )
    return entry


def to_dump(caps: Capabilities) -> Dict[str, Any]:
    """Свести :class:`Capabilities` к детерминированному dump-dict.

    Только контракт: сортированные команды/поля/каналы, без runtime-значений.
    Порядок ключей фиксируется сортировкой при сериализации (sort_keys).
    """
    processes: Dict[str, Any] = {}
    for name in sorted(caps.processes):
        card = caps.processes[name]
        processes[name] = {
            "commands": sorted(
                (_command_dump(c) for c in card.commands if c.get("name")),
                key=lambda c: c["name"],
            ),
            "router_handlers": sorted(card.router_handlers),
            "registers": {reg: sorted(fields) for reg, fields in sorted(card.registers.items())},
        }
    return {
        "version": DUMP_VERSION,
        "source": "python -m backend_ctl.dump_capabilities",
        "topology": {
            name: {"class": str((cfg or {}).get("class") or "")} for name, cfg in sorted(caps.topology.items())
        },
        "channels": sorted(
            ({"name": str(c.get("name") or ""), "kind": str(c.get("kind") or "")} for c in caps.channels),
            key=lambda c: c["name"],
        ),
        "processes": processes,
    }


def render_yaml(dump: Dict[str, Any]) -> str:
    """Сериализовать dump-dict в детерминированный YAML (sort_keys, unicode)."""
    import yaml

    header = (
        "# CAPABILITIES.yaml — «контактная книжка» бэкенда (capability manifest v1).\n"
        "# ГЕНЕРИРУЕТСЯ: python -m backend_ctl.dump_capabilities — руками не править.\n"
        "# CI-gate: backend_ctl/tests/test_capabilities.py сверяет с runtime (дрейф = красный).\n"
    )
    return header + yaml.safe_dump(dump, allow_unicode=True, sort_keys=True, width=100)


def render_md(dump: Dict[str, Any]) -> str:
    """Отрендерить человекочитаемую «книжку» из dump-dict.

    Самодостаточна для агента: как подключиться driver'ом, какие процессы есть,
    какие команды у каждого (имя+описание+теги), регистры и события.
    """
    lines: list[str] = [
        "# Контактная книжка бэкенда (capability manifest v1)",
        "",
        "> ГЕНЕРИРУЕТСЯ: `python -m backend_ctl.dump_capabilities` — руками не править.",
        "> Дрейф с runtime ловит CI (`backend_ctl/tests/test_capabilities.py`).",
        "",
        "## Как пользоваться (агенту)",
        "",
        "```python",
        "from backend_ctl import BackendDriver          # или BackendHarness для headless-старта",
        "",
        "with BackendDriver() as drv:                   # порт: env BACKEND_CTL_PORT → DEFAULT_PORT",
        '    res = drv.send_command("<процесс>", "<команда>", {<аргументы>})',
        "    caps = drv.capabilities()                  # этот же свод, но runtime",
        "```",
        "",
        "Команда адресуется процессу по имени (колонка «Процесс» ниже). Ответ приходит",
        "request-response (dict). События (push без request_id) читаются `drv.events()`.",
        "",
        "## Топология (управляемые процессы)",
        "",
        "| Процесс | Класс |",
        "|---|---|",
    ]
    for name, cfg in sorted(dump.get("topology", {}).items()):
        lines.append(f"| `{name}` | `{cfg.get('class', '')}` |")

    channels = dump.get("channels", [])
    lines += ["", "## Каналы router'а ProcessManager", ""]
    if channels:
        lines += ["| Канал | Тип |", "|---|---|"]
        lines += [f"| `{c.get('name', '')}` | `{c.get('kind', '')}` |" for c in channels]
    else:
        lines.append("_нет зарегистрированных каналов_")

    for proc, card in sorted(dump.get("processes", {}).items()):
        lines += ["", f"## Процесс `{proc}`", ""]
        commands = card.get("commands", [])
        if commands:
            lines += ["### Команды", "", "| Команда | Описание | Теги |", "|---|---|---|"]
            for c in commands:
                tags = ", ".join(c.get("tags", []))
                lines.append(f"| `{c.get('name', '')}` | {c.get('description', '')} | {tags} |")
        registers = card.get("registers", {})
        if registers:
            lines += ["", "### Регистры (поля — цели `register_update`)", ""]
            for reg, fields in sorted(registers.items()):
                joined = ", ".join(f"`{f}`" for f in fields)
                lines.append(f"- **{reg}**: {joined}")
        handlers = card.get("router_handlers", [])
        if handlers:
            lines += ["", "### Router-handlers (события, не команды)", ""]
            lines.append(", ".join(f"`{h}`" for h in handlers))
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Сбор с живого headless-бэкенда + CLI
# ---------------------------------------------------------------------------


def collect_live(
    *,
    recipe: Optional[str] = None,
    with_base: bool = True,
    port: Optional[int] = None,
    timeout: float = 8.0,
) -> Capabilities:
    """Поднять headless-бэкенд (harness) и собрать свод capabilities.

    with_base=True — та же топология, что у session-фикстуры ``headless_backend``:
    дамп и CI-gate сравнивают like-for-like.
    """
    from backend_ctl.harness import BackendHarness

    with BackendHarness(recipe=recipe, with_base=with_base, port=port) as drv:
        return drv.capabilities(timeout=timeout)


def _diff(expected: str, actual: str, name: str) -> str:
    """unified diff «на диске» vs «runtime» (пусто = совпадает)."""
    return "".join(
        difflib.unified_diff(
            expected.splitlines(keepends=True),
            actual.splitlines(keepends=True),
            fromfile=f"{name} (на диске)",
            tofile=f"{name} (runtime)",
        )
    )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Дамп «контактной книжки» бэкенда (capability manifest v1)")
    parser.add_argument("--check", action="store_true", help="не писать, а сравнить с файлами (дрейф → exit 2)")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="куда писать YAML+MD")
    parser.add_argument("--recipe", default=None, help="путь к рецепту топологии (None → дефолт harness)")
    parser.add_argument("--port", type=int, default=None, help="port backend_ctl endpoint'a (None -> env/DEFAULT_PORT)")
    args = parser.parse_args(argv)

    print("[dump] поднимаю headless-бэкенд и собираю capabilities...")
    caps = collect_live(recipe=args.recipe, port=args.port)
    bad = sorted(name for name, card in caps.processes.items() if not card.ok)
    if bad:
        print(f"[dump] FAIL: процессы не ответили на introspect.capabilities: {bad}")
        return 1

    dump = to_dump(caps)
    yaml_text = render_yaml(dump)
    md_text = render_md(dump)

    out_dir = Path(args.out_dir)
    yaml_path = out_dir / YAML_NAME
    md_path = out_dir / MD_NAME

    if args.check:
        drift = ""
        for path, actual in ((yaml_path, yaml_text), (md_path, md_text)):
            expected = path.read_text(encoding="utf-8") if path.exists() else ""
            drift += _diff(expected, actual, str(path))
        if drift:
            print(drift)
            print("[dump] DRIFT: книжка отстала от кода — перегенерируй: python -m backend_ctl.dump_capabilities")
            return 2
        print("[dump] OK: книжка совпадает с runtime")
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    yaml_path.write_text(yaml_text, encoding="utf-8")
    md_path.write_text(md_text, encoding="utf-8")
    print(f"[dump] записано: {yaml_path} + {md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
