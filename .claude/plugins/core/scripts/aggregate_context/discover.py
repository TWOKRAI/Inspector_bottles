"""discover.py — auto-discovery per-module markdown файлов.

Сканирует проект и находит per-module:
- CONTEXT.md   — лёгкий per-module документ (Purpose / Gotchas / Glossary / …)
- DECISIONS.md — формальные ADR (нумерованные ADR-{CODE}-NNN)

Конвенция: папка с одним из этих файлов = модуль. Имя модуля = имя папки.
Module code (для DECISIONS): из frontmatter `module_code:` либо
uppercase-инициалы папки (`base_manager` → `BM`).

Pre:
  - root существует и читаемый
Post:
  - возвращает отсортированный по name список ModuleEntry
  - exclusions применены к ПУТИ ОТНОСИТЕЛЬНО root (не absolute), default:
    _archive, node_modules, .venv, venv, __pycache__, .git, кеши, dist, build
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


DEFAULT_EXCLUDE_DIRS: tuple[str, ...] = (
    "_archive",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "dist",
    "build",
)


@dataclass(frozen=True)
class ModuleEntry:
    """Найденный модуль.

    Attributes:
        name: имя папки (например, 'base_manager').
        path: абсолютный путь к директории модуля.
        context_file: путь к CONTEXT.md если есть, иначе None.
        decisions_file: путь к DECISIONS.md если есть, иначе None.
        module_code: код модуля (из frontmatter или auto-derived).
    """

    name: str
    path: Path
    context_file: Path | None
    decisions_file: Path | None
    module_code: str


_FRONTMATTER_RE = re.compile(
    r"^---\s*\n(.*?)\n---\s*\n",
    re.DOTALL,
)
_MODULE_CODE_RE = re.compile(r"^module_code:\s*([A-Z][A-Z0-9]*)\s*$", re.MULTILINE)


def _read_module_code(decisions_file: Path | None, folder_name: str) -> str:
    """Извлекает module_code из frontmatter DECISIONS.md или строит из имени папки.

    Frontmatter format:
        ---
        module_code: BM
        ---

    Fallback: uppercase initials папки.
        base_manager → BM
        process_manager_module → PMM
        api → API
        actions → ACT  (если короче 2 слов — берём первые 3 буквы)
    """
    if decisions_file and decisions_file.exists():
        text = decisions_file.read_text(encoding="utf-8")
        fm_match = _FRONTMATTER_RE.match(text)
        if fm_match:
            code_match = _MODULE_CODE_RE.search(fm_match.group(1))
            if code_match:
                return code_match.group(1)

    parts = folder_name.split("_")
    if len(parts) >= 2:
        return "".join(p[0].upper() for p in parts if p)
    return folder_name[:3].upper()


def discover_modules(
    root: Path,
    *,
    exclude_dirs: Iterable[str] = DEFAULT_EXCLUDE_DIRS,
    extra_excludes: Iterable[str] = (),
) -> list[ModuleEntry]:
    """Сканирует *root* и находит модули с CONTEXT.md и/или DECISIONS.md.

    Args:
        root: корень проекта (обычно cwd).
        exclude_dirs: имена директорий для исключения (anywhere in path).
        extra_excludes: дополнительные относительные пути (от root) для
            исключения. Пример: ['apps/legacy', 'scripts/_old'].

    Returns:
        Отсортированный по name список ModuleEntry.
    """
    root = Path(root).resolve()
    excludes = set(exclude_dirs)
    extras = {(root / p).resolve() for p in extra_excludes}

    found: dict[Path, ModuleEntry] = {}

    for pattern in ("CONTEXT.md", "DECISIONS.md"):
        for file_path in root.rglob(pattern):
            # Проверяем exclusion ТОЛЬКО относительно root, а не absolute parts.
            # Иначе проект, лежащий в D:/build/... или ~/venv/proj/..., получит
            # ложный exclude всех модулей по совпадению с именем выше root.
            try:
                rel_parts = file_path.relative_to(root).parts
            except ValueError:
                continue
            if any(part in excludes for part in rel_parts):
                continue
            if any(file_path.is_relative_to(ex) for ex in extras):
                continue

            module_dir = file_path.parent
            name = module_dir.name

            if module_dir in found:
                entry = found[module_dir]
                if pattern == "CONTEXT.md":
                    entry = ModuleEntry(
                        name=entry.name,
                        path=entry.path,
                        context_file=file_path,
                        decisions_file=entry.decisions_file,
                        module_code=entry.module_code,
                    )
                else:
                    entry = ModuleEntry(
                        name=entry.name,
                        path=entry.path,
                        context_file=entry.context_file,
                        decisions_file=file_path,
                        module_code=_read_module_code(file_path, name),
                    )
                found[module_dir] = entry
            else:
                ctx = file_path if pattern == "CONTEXT.md" else None
                dec = file_path if pattern == "DECISIONS.md" else None
                code = _read_module_code(dec, name)
                found[module_dir] = ModuleEntry(
                    name=name,
                    path=module_dir,
                    context_file=ctx,
                    decisions_file=dec,
                    module_code=code,
                )

    return sorted(found.values(), key=lambda m: m.name)
