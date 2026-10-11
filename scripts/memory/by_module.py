"""Генерируемый индекс уроков `BY-MODULE*.md` (план atlas, задача 2.4j).

Вызывается из `search.py --by-module --write|--check`. Уроки — только через `_lessons`
(`iter_lessons` + `read_lesson`), второго разбора frontmatter нет. Файлы без дат, UTF-8, LF.

Stability: lite
"""

from __future__ import annotations

import sys
from pathlib import Path

import _lessons

MAX_FILE_BYTES = 80000
DESC_LIMIT = 80
GLOB = "BY-MODULE*.md"
HUB = "BY-MODULE.md"
MECH = "BY-MODULE-mechanism.md"
LAYERS = ("framework", "services", "plugins", "prototype", "tools", "other")
NO_MODULE = "(без module)"
NO_MECHANISM = "(без mechanism)"
NOTICE = "Сгенерировано: `python scripts/memory/search.py --by-module --write`; не править вручную"

_SEG_LAYER = {
    "services": "services",
    "plugins": "plugins",
    "plugins_shared": "plugins",
    "prototype": "prototype",
    "tools": "tools",
    "scripts": "tools",
}

type Entry = tuple[str, list[str], list[str], str]  # (имя файла, module, mechanism, описание)


def layer_of(module: str) -> str:
    return _SEG_LAYER.get(module.split("/")[0], "framework")


def layer_file(layer: str) -> str:
    return f"BY-MODULE-{layer}.md"


def short_description(fm: dict[str, list[str]]) -> str:
    desc = " ".join(fm.get("description", []))
    return desc if len(desc) <= DESC_LIMIT else desc[: DESC_LIMIT - 1] + "…"


def collect(root: Path) -> list[Entry]:
    entries: list[Entry] = []
    for path in _lessons.iter_lessons(root / _lessons.MEMORY_REL):
        fm = _lessons.read_lesson(path) or {k: [] for k in _lessons.KEYS}
        entries.append((path.name, fm["module"], fm["mechanism"], short_description(fm)))
    return entries


def _item(name: str, desc: str | None) -> str:
    stem = name.removesuffix(".md")
    line = f"- [{stem}]({name})"
    return f"{line} — {desc}" if desc else line


def _sections(groups: dict[str, list[str]], fallback: tuple[str, list[str]] | None = None) -> list[str]:
    out: list[str] = []
    blocks = [(key, groups[key]) for key in sorted(groups)]
    if fallback and fallback[1]:
        blocks.append(fallback)
    for key, lines in blocks:
        out += [f"## {key} ({len(lines)})", "", *lines, ""]
    return out


def _join(lines: list[str]) -> str:
    return "\n".join(lines).rstrip("\n") + "\n"


def _layer_text(layer: str, items: dict[str, list[str]]) -> str:
    head = [f"# Уроки по модулям — {layer}", "", f"{NOTICE}. Хаб: [{HUB}]({HUB})", ""]
    if layer == "other":
        fallback = (NO_MODULE, items.get(NO_MODULE, []))
        return _join(head + _sections({}, fallback))
    return _join(head + _sections(items))


def _mech_text(groups: dict[str, list[str]], without: list[str]) -> str:
    head = ["# Уроки по механизму", "", f"{NOTICE}. Хаб: [{HUB}]({HUB})", ""]
    return _join(head + _sections(groups, (NO_MECHANISM, without)))


def _hub_text(rows: list[tuple[str, int, int]]) -> str:
    lines = [
        "# Индекс уроков по модулям",
        "",
        NOTICE,
        "",
        "| слой | файл | модулей | уроков |",
        "|---|---|---|---|",
    ]
    for layer, modules, lessons in rows:
        name = layer_file(layer)
        lines.append(f"| {layer} | [{name}]({name}) | {modules} | {lessons} |")
    lines += ["", f"По механизму: [{MECH}]({MECH})", ""]
    return _join(lines)


def generate(entries: list[Entry]) -> dict[str, str]:
    """Имя файла индекса -> текст."""
    by_layer: dict[str, dict[str, list[str]]] = {}  # слой -> module -> строки уроков
    layer_lessons: dict[str, set[str]] = {}
    mech: dict[str, list[str]] = {}
    no_mech: list[str] = []
    for name, modules, mechanisms, desc in entries:
        line = _item(name, desc)
        for layer, module in [(layer_of(m), m) for m in modules] or [("other", NO_MODULE)]:
            by_layer.setdefault(layer, {}).setdefault(module, []).append(line)
            layer_lessons.setdefault(layer, set()).add(name)
        mline = _item(name, None)
        for m in mechanisms:
            mech.setdefault(m, []).append(mline)
        if not mechanisms:
            no_mech.append(mline)

    files: dict[str, str] = {}
    rows: list[tuple[str, int, int]] = []
    for layer in LAYERS:
        if layer not in by_layer:
            continue
        files[layer_file(layer)] = _layer_text(layer, by_layer[layer])
        modules = 0 if layer == "other" else len(by_layer[layer])
        rows.append((layer, modules, len(layer_lessons[layer])))
    files[MECH] = _mech_text(mech, no_mech)
    files[HUB] = _hub_text(rows)
    return files


def _too_big(encoded: dict[str, bytes]) -> bool:
    big = [(n, len(b)) for n, b in sorted(encoded.items()) if len(b) > MAX_FILE_BYTES]
    for name, size in big:
        print(f"too big: {name} {size}", file=sys.stderr)
    return bool(big)


def run(root: Path, *, write: bool) -> int:
    """`--write` (`write=True`) или `--check`; код выхода процесса."""
    encoded = {n: t.encode("utf-8") for n, t in generate(collect(root)).items()}
    if _too_big(encoded):
        return 2
    mem = root / _lessons.MEMORY_REL
    # glob на Windows не различает регистр, а iter_lessons исключает `BY-MODULE` по регистру: фильтр по префиксу
    on_disk = (
        {p.name: p for p in mem.glob(GLOB) if p.is_file() and p.name.startswith(_lessons.BY_MODULE_PREFIX)}
        if mem.is_dir()
        else {}
    )
    if write:
        mem.mkdir(parents=True, exist_ok=True)
        for name, path in on_disk.items():
            if name not in encoded:
                path.unlink()
        for name, data in encoded.items():
            (mem / name).write_bytes(data)  # байты: на Windows write_text подменил бы \n
        print(f"wrote {len(encoded)} files")
        return 0
    problems: list[str] = []
    for name in sorted(encoded.keys() | on_disk.keys()):
        if name not in on_disk:
            problems.append(f"missing: {name}")
        elif name not in encoded:
            problems.append(f"extra: {name}")
        elif on_disk[name].read_bytes() != encoded[name]:
            problems.append(f"stale: {name}")
    for line in problems:
        print(line)
    return 1 if problems else 0
