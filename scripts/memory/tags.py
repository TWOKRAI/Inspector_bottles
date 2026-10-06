"""Проверка тегов уроков памяти: `python scripts/memory/tags.py --check [--root DIR]`.

Контракт — plans/2026-10-04_atlas/tasks/2.4g.md, раздел «2.4g.1». Строка на ошибку:
`<путь от DIR>: <код>: <repr(значения)[:80]>`; выход 1 при любой ошибке, иначе 0.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

import _lessons

MAX_MECHANISMS = 30
MAX_ROLE_INDEX_LINES = 3
_CYRILLIC = re.compile(r"[А-Яа-яЁё]{3,}")
_LATIN = re.compile(r"[A-Za-z]{3,}")


def _fail(msg: str) -> None:
    sys.stderr.write(msg + "\n")
    raise SystemExit(2)


def _load_yaml(path: Path):
    if not path.is_file():
        _fail(f"vocabulary file not found: {path}")
    return yaml.safe_load(path.read_bytes().decode("utf-8"))


def _ids(items) -> list[str]:
    return [str(it["id"]) for it in items or [] if isinstance(it, dict) and "id" in it]


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _error(root: Path, path: Path, code: str, value) -> str:
    return f"{_rel(root, path)}: {code}: {repr(value)[:80]}"


def check(root: Path) -> list[str]:
    modules = set(_ids((_load_yaml(root / "modules.yaml") or {}).get("modules")))
    tags_path = root / _lessons.MEMORY_REL / "TAGS.yaml"
    mechanism_ids = _ids((_load_yaml(tags_path) or {}).get("mechanisms"))
    mechanisms = set(mechanism_ids)
    roles = {p.stem for p in (root / ".claude" / "agents" / "dev").glob("*.md")}

    errors: list[str] = []
    if len(mechanism_ids) > MAX_MECHANISMS:
        errors.append(_error(root, tags_path, "vocab-too-big", len(mechanism_ids)))

    for path in _lessons.iter_lessons(root / _lessons.MEMORY_REL):
        fm = _lessons.read_lesson(path)
        if not fm:
            errors.append(_error(root, path, "no-tag", path.name))
            continue
        for key, vocab, code in (
            ("module", modules, "unknown-module"),
            ("mechanism", mechanisms, "unknown-mechanism"),
            ("role", roles, "unknown-role"),
        ):
            errors.extend(_error(root, path, code, v) for v in fm[key] if v not in vocab)
        if not fm["module"] and not fm["mechanism"]:
            errors.append(_error(root, path, "no-tag", path.name))
        description = " ".join(fm["description"])
        if not (_CYRILLIC.search(description) and _LATIN.search(description)):
            errors.append(_error(root, path, "desc-lang", description))

    agent_memory = root / ".claude" / "agent-memory"
    for role_dir in sorted(p for p in agent_memory.glob("*") if p.is_dir()):
        for f in sorted(p for p in role_dir.rglob("*") if p.is_file()):
            if f.parent == role_dir and f.name == "MEMORY.md":
                body = f.read_bytes().decode("utf-8", errors="replace")
                lines = [ln for ln in body.splitlines() if ln.strip()]
                if len(lines) > MAX_ROLE_INDEX_LINES:
                    errors.append(_error(root, f, "role-index-too-long", len(lines)))
            else:
                errors.append(_error(root, f, "stray-role-lesson", f.name))
    return errors


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Check lesson tags against the vocabularies.")
    parser.add_argument("--check", action="store_true", required=True)
    parser.add_argument("--root", type=Path, default=None, help="repo root (default: git toplevel of cwd)")
    args = parser.parse_args(argv)
    root = (args.root or _lessons.current_tree_root()).resolve()

    errors = check(root)
    for line in errors:
        print(line)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
