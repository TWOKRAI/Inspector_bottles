"""Общий разбор уроков памяти для `tags.py` и `search.py` (план atlas, задача 2.4g.1).

Скрипты запускаются как файлы, поэтому `sys.path[0]` — это `scripts/memory`, и оба делают
простой `import _lessons`. Только stdlib: frontmatter разбирается построчно, без YAML-библиотеки
(в 4 файлах памяти он не разбирается `yaml.safe_load`).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

MEMORY_REL = "docs/claude/memory"
NON_LESSONS = ("MEMORY.md", "ARCHIVE.md")
CRAFT_PREFIX = "CRAFT"

# Ключи, которые читаются из frontmatter. `description` и `name` — одна строка, остальные — списки значений.
LIST_KEYS = ("module", "mechanism", "role")
SCALAR_KEYS = ("name", "description")
KEYS = ("name", "description", *LIST_KEYS)

_KEY_LINE = re.compile(r"^(?P<indent>[ \t]*)(?P<key>[A-Za-z_][\w-]*):(?P<value>.*)$")
_BARE_DQUOTE = re.compile(r'(?<!\\)"')  # `"` без экранирующего `\` перед ним
_ESCAPED = re.compile(r'\\(["\\])')  # `\"` и `\\` внутри "..."


def _is_quoted(value: str) -> bool:
    """Всё значение — один скаляр в кавычках (внутри нет такой же кавычки без экранирования)."""
    if len(value) < 2 or value[0] != value[-1] or value[0] not in "\"'":
        return False
    inner = value[1:-1]
    if value[0] == '"':
        return _BARE_DQUOTE.search(inner) is None
    return "'" not in inner.replace("''", "")


def _unquote(value: str) -> str:
    value = value.strip()
    return value[1:-1].strip() if _is_quoted(value) else value


def _unquote_scalar(value: str) -> str:
    r"""Скаляр `name`/`description`: в `"..."` снимаются `\"` и `\\`, в `'...'` — `''`."""
    value = value.strip()
    if not _is_quoted(value):
        return value
    inner = value[1:-1]
    if value[0] == '"':
        return _ESCAPED.sub(r"\1", inner).strip()
    return inner.replace("''", "'").strip()


def _split_list(raw: str) -> list[str]:
    """`a`, `"a"`, `"a, b"`, `a, b`, `[a, b]`, `["a", "b"]` -> список значений; пустое значение -> [].

    Значение целиком в кавычках (не `[...]`) сначала снимает кавычки, потом режется по запятым.
    """
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    else:
        raw = _unquote(raw)
    return [v for v in (_unquote(part) for part in raw.split(",")) if v]


def _add(out: dict[str, list[str]], key: str, raw: str) -> None:
    values = [v for v in [_unquote_scalar(raw)] if v] if key in SCALAR_KEYS else _split_list(raw)
    for v in values:
        if v not in out[key]:  # один ключ в двух местах — объединение, без дублей
            out[key].append(v)


def parse_frontmatter(text: str) -> dict[str, list[str]]:
    """Построчный разбор frontmatter урока.

    Возвращает `{}`, если frontmatter нет: первая строка файла не `---` или закрывающей `---` нет.
    Иначе — словарь со всеми ключами из `KEYS` (отсутствующий ключ = пустой список).
    Ключи читаются на верхнем уровне и с отступом под `metadata:` (блок кончается на строке
    без отступа). `description` и `name` не режутся по запятым: это текст, а не список.
    Ведущий BOM снимается; `\\r` снимается у каждой строки; `---` в теле после frontmatter
    игнорируется.
    """
    lines = [ln.rstrip("\r") for ln in text.lstrip("﻿").split("\n")]
    if not lines or lines[0].rstrip() != "---":
        return {}
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].rstrip() == "---")
    except StopIteration:
        return {}

    out: dict[str, list[str]] = {k: [] for k in KEYS}
    in_metadata = False
    for ln in lines[1:end]:
        m = _KEY_LINE.match(ln)
        if m is None:
            continue
        key, indented = m["key"], bool(m["indent"])
        if not indented:
            in_metadata = key == "metadata"
            if key in out:
                _add(out, key, m["value"])
        elif in_metadata and key in out:
            _add(out, key, m["value"])
    return out


def read_lesson(path: Path) -> dict[str, list[str]]:
    """Frontmatter файла урока; нечитаемые байты заменяются, а не роняют проверку."""
    return parse_frontmatter(path.read_bytes().decode("utf-8", errors="replace"))


def iter_lessons(memory_dir: Path) -> list[Path]:
    """`*.md` прямо в каталоге, кроме `MEMORY.md`, `ARCHIVE.md`, `CRAFT*.md`; по имени файла."""
    if not memory_dir.is_dir():
        return []
    return sorted(
        (
            p
            for p in memory_dir.glob("*.md")
            if p.is_file() and p.name not in NON_LESSONS and not p.name.startswith(CRAFT_PREFIX)
        ),
        key=lambda p: p.name,
    )


def _git(args: list[str]) -> str:
    cp = subprocess.run(["git", *args], capture_output=True, check=False)
    if cp.returncode != 0:
        sys.stderr.write(f"git {' '.join(args)}: {cp.stderr.decode('utf-8', 'replace').strip()}\n")
        raise SystemExit(2)
    return cp.stdout.decode("utf-8", "replace").strip()


def main_checkout_root() -> Path:
    """Корень main-checkout: родитель общего git-каталога (из любого worktree)."""
    return Path(_git(["rev-parse", "--path-format=absolute", "--git-common-dir"])).parent


def current_tree_root() -> Path:
    """Корень текущего дерева (для `tags.py --check` без `--root`)."""
    return Path(_git(["rev-parse", "--show-toplevel"]))
