"""Карта «путь -> модуль»: загрузка modules.yaml и резолвер (Task 0.3, plans/2026-10-04_atlas).

Формат и правила — plans/2026-10-04_atlas/tasks/0.3.md. Только stdlib и PyYAML,
кода проекта не импортирует (кроме `tree.AtlasError`, у `tree.py` импортов проекта нет): модуль читают адаптеры
атласа и хуки коммита.

Purpose: загрузка modules.yaml (строгая: нужен `purpose`), разбор текста (мягкий по умолчанию),
    юниты из каталогов-корней `roots`, резолвер «путь -> модуль», `norm_path` — путь с входа CLI.
Public API: OTHER, expand_roots, load_modules, norm_path, parse_modules, resolve, unit_ids.
Stability: lite

Элемент `paths` с «/» на конце — префикс каталога, без «/» — точный файл.
Побеждает САМЫЙ ДЛИННЫЙ совпавший элемент, порядок строк в списке не важен.

Юнит — прямой подкаталог корня из `roots` с `__init__.py`, кроме имён из `root_exclude` (Д5, Task 4.4b).
Строки юнитов идут первыми (корни как в `roots`, внутри — по имени), затем записи `modules:` как были.
Ключи `roots`, `root_exclude`, `tiers` необязательны: нет `roots` — юнитов нет, ревизии старого формата читаются.

Pre: `read_many(paths)` отдаёт `{path: bytes | None}` для каждого запрошенного пути; `files` — posix-пути
    ревизии или диска относительно корня репозитория.
Post: ошибка юнита — ValueError `<name>: юнит K: …` (K — id юнита), текст без содержимого файлов и без
    значений `tiers`; id юнитов уникальны между собой и против записей `modules:`.
"""

from __future__ import annotations

import ast
import os
import posixpath
import re
from collections.abc import Callable
from pathlib import Path

import yaml

from scripts.atlas.tree import AtlasError

__all__ = ["OTHER", "expand_roots", "load_modules", "norm_path", "parse_modules", "resolve", "unit_ids"]

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REQUIRED_KEYS = ("id", "paths", "layer", "tier", "docs", "parent")
_INIT = "__init__.py"
_DOC_FILES = ("README.md", "STATUS.md", "DECISIONS.md")
_TIERS = ("core", "optional")

OTHER = "other"
_DRIVE = re.compile(r"[A-Za-z]:/")  # диск Windows в пути после замены `\` на `/`


def norm_path(s: str, root: Path | None = None) -> str:
    """Путь с входа CLI -> posix-путь от корня репозитория: `\\` -> `/`, без ведущего `./`, `posixpath.normpath`.

    Pre: `root` — корень репозитория или None. Post: абсолютный путь внутри `root` -> путь от корня; `root is None`
    — любой абсолютный путь ошибка. Raises: `AtlasError` (CLI: код 2, строка `atlas: ...`, значение пути в тексте
    не печатается) — пустая строка, `..` выше корня, абсолютный путь вне `root`. Абсолютный путь сверяется с корнем
    как дан и через `os.path.realpath` (алиас-симлинк: macOS `/tmp` -> `/private/tmp`), корень — как дан и через
    `resolve()`. Регистр на Windows не сводится."""
    path = s.replace("\\", "/")
    if path == "":
        raise AtlasError("atlas: путь пуст")
    if path.startswith("/") or _DRIVE.match(path):
        norm = posixpath.normpath(path)
        bases = {root.as_posix().rstrip("/"), root.resolve().as_posix().rstrip("/")} if root is not None else set()
        # как дан, затем с развёрнутыми симлинками (путь и корень по обе стороны алиаса)
        for variant in (norm, os.path.realpath(norm).replace("\\", "/")) if bases else ():
            for base in sorted(bases, key=len, reverse=True):
                if variant == base:
                    return "."
                if variant.startswith(base + "/"):
                    return variant[len(base) + 1 :]
        raise AtlasError("atlas: абсолютный путь вне корня репозитория")
    norm = posixpath.normpath(path)
    if norm == ".." or norm.startswith("../"):
        raise AtlasError("atlas: путь выше корня репозитория")
    return norm


def load_modules(path: str | Path = "modules.yaml") -> list[dict]:
    """Читает modules.yaml. Относительный путь считается от корня репозитория, не от cwd.

    Нет файла -> FileNotFoundError. Остальные ошибки — как у parse_modules.
    """
    file = Path(path)
    if not file.is_absolute():
        file = _REPO_ROOT / file
    text = file.read_text(encoding="utf-8")
    rows = parse_modules(text, file.name, require_purpose=True)
    disk = _DiskTree(file.parent)
    return [*expand_roots(text, file.name, disk.files(text, file.name), disk.read_many), *rows]


def unit_ids(path: str | Path) -> list[str]:
    """id юнитов из `roots` файла `path` (диск от его каталога), без разбора докстрингов.

    Нет файла -> FileNotFoundError. Нет `roots` -> []. Неверная форма `roots`/`tiers` или повтор id -> ValueError.
    """
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    disk = _DiskTree(file.parent)
    return [row["id"] for row in _units(text, file.name, disk.files(text, file.name), None)]


def expand_roots(
    text: str, name: str, files: list[str], read_many: Callable[[list[str]], dict[str, bytes | None]]
) -> list[dict]:
    """Строки юнитов из `roots` текста modules.yaml; нет `roots` -> [].

    `files` — posix-пути ревизии или диска; `read_many` читает `__init__.py` юнитов одним вызовом.
    `purpose` — первая строка докстринга `__init__.py`. ValueError — как в модульном docstring.
    """
    return _units(text, name, files, read_many)


def parse_modules(text: str, name: str = "modules.yaml", require_purpose: bool = False) -> list[dict]:
    """Разбирает текст modules.yaml; `name` — префикс сообщений об ошибках.

    Неверная `version`, нет обязательного ключа строки или пустая строка в `paths` ->
    ValueError (в тексте ключ и 0-based индекс строки, значение не печатается).
    Ключ `purpose` обязателен только при `require_purpose` (ревизии без него читаются).
    """
    data = yaml.safe_load(text)
    version = data.get("version") if isinstance(data, dict) else None
    if type(version) is not int or version != 1:  # bool (True == 1) не годится
        raise ValueError(f"{name}: ключ 'version' должен быть равен 1")
    rows = data.get("modules")
    if not isinstance(rows, list):
        raise ValueError(f"{name}: ключ 'modules' должен быть списком")
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"{name}: строка {index} не является словарём")
        for key in _REQUIRED_KEYS:
            if key not in row:
                raise ValueError(f"{name}: в строке {index} нет ключа '{key}'")
        if not isinstance(row["paths"], list) or any(not isinstance(p, str) or p == "" for p in row["paths"]):
            raise ValueError(f"{name}: в строке {index} ключ 'paths' содержит пустой или нестроковый элемент")
        if require_purpose and "purpose" not in row:
            raise ValueError(f"{name}: в строке {index} нет ключа 'purpose'")
    return rows


def resolve(rel_path: str, modules: list[dict]) -> str:
    """id строки с самым длинным совпавшим элементом `paths`, иначе "other". Не бросает.

    `modules` — список, который вернул load_modules.
    """
    try:
        raw = str(rel_path).replace("\\", "/")
        path = norm_path(raw) + ("/" if raw.endswith("/") else "")  # `pkg/` — каталог: совпадает с элементом `pkg/`
    except AtlasError:  # пустой, выше корня, абсолютный: ни один элемент `paths` не совпадёт
        return OTHER
    best_id, best_len = OTHER, 0
    for row in modules:
        for element in row["paths"]:
            matched = path.startswith(element) if element.endswith("/") else path == element
            if matched and len(element) > best_len:
                best_id, best_len = row["id"], len(element)
    return best_id


class _DiskTree:
    """Диск как «ревизия»: файлы только под корнями `roots` (`<root>*/{__init__,README,STATUS,DECISIONS}`).

    Юнит — реальный каталог: симлинки пропускаются, как в ревизии (там это blob, не дерево).
    """

    def __init__(self, base: Path) -> None:
        self._base = base

    def files(self, text: str, name: str) -> list[str]:
        config = _config(text, name)
        found: list[str] = []
        for root in config[0] if config else []:
            top = self._base / root["path"]
            for unit in sorted(top.iterdir()) if top.is_dir() else []:
                found += [
                    f"{root['path']}{unit.name}/{item}"
                    for item in (_INIT, *_DOC_FILES)
                    if unit.is_dir() and not unit.is_symlink() and (unit / item).is_file()
                ]
        return found

    def read_many(self, paths: list[str]) -> dict[str, bytes | None]:
        out: dict[str, bytes | None] = {}
        for rel in paths:
            try:
                out[rel] = (self._base / rel).read_bytes()
            except OSError:
                out[rel] = None
        return out


def _config(text: str, name: str) -> tuple[list[dict], set[str], dict] | None:
    """(roots, root_exclude, tiers) или None, если ключа `roots` нет; неверная форма -> ValueError без значений."""
    data = yaml.safe_load(text)
    if not isinstance(data, dict) or "roots" not in data:
        return None
    roots, exclude, tiers = data["roots"], data.get("root_exclude", []), data.get("tiers", {})
    if not isinstance(roots, list):
        raise ValueError(f"{name}: ключ 'roots' должен быть списком")
    for index, root in enumerate(roots):
        shape_ok = (
            isinstance(root, dict)
            and isinstance(root.get("path"), str)
            and root["path"].endswith("/")
            and isinstance(root.get("layer"), str)
            and isinstance(root.get("id_prefix", ""), str)
        )
        if not shape_ok:
            raise ValueError(f"{name}: в 'roots' элемент {index} должен иметь path (с «/» на конце), layer, id_prefix")
    if not isinstance(exclude, list) or any(not isinstance(item, str) for item in exclude):
        raise ValueError(f"{name}: ключ 'root_exclude' должен быть списком строк")
    if not isinstance(tiers, dict):
        raise ValueError(f"{name}: ключ 'tiers' должен быть словарём")
    return roots, set(exclude), tiers


def _purpose(raw: bytes | None, unit_id: str, name: str) -> str:
    """Первая строка докстринга `__init__.py`; ошибка — ValueError без содержимого файла."""
    try:
        if raw is None:
            raise ValueError
        raw.decode("utf-8-sig")  # ast.parse пропускает невалидный UTF-8 внутри комментария
        docstring = ast.get_docstring(ast.parse(raw))
    except (SyntaxError, ValueError, MemoryError, RecursionError):  # UnicodeDecodeError — подкласс ValueError
        raise ValueError(f"{name}: юнит {unit_id}: {_INIT} не разобран") from None
    if docstring is None:
        raise ValueError(f"{name}: юнит {unit_id}: нет докстринга")
    if not docstring.strip():
        raise ValueError(f"{name}: юнит {unit_id}: {_INIT} не разобран")
    return docstring.splitlines()[0].rstrip()


def _units(
    text: str,
    name: str,
    files: list[str],
    read_many: Callable[[list[str]], dict[str, bytes | None]] | None,
) -> list[dict]:
    """Общая часть expand_roots и unit_ids: `read_many is None` — только id, докстринги не читаются."""
    config = _config(text, name)
    if config is None:
        return []
    roots, exclude, tiers = config
    present = set(files)
    units: list[tuple[str, dict]] = []
    for root in roots:
        prefix, path = root.get("id_prefix", ""), root["path"]
        names = sorted(
            {
                rest.split("/")[0]
                for rest in (item[len(path) :] for item in files if item.startswith(path))
                if rest.count("/") == 1 and rest.endswith(f"/{_INIT}")
            }
            - exclude
        )
        for unit_name in names:
            base = f"{path}{unit_name}/"
            row = {
                "id": prefix + unit_name,
                "paths": [base],
                "layer": root["layer"],
                "tier": tiers.get(prefix + unit_name),
                "docs": [base + item for item in _DOC_FILES if base + item in present],
                "parent": None,
                "purpose": None,
            }
            units.append((base + _INIT, row))
    ids = [row["id"] for _, row in units]
    for key, value in tiers.items():
        if key not in ids:
            raise ValueError(f"{name}: ключ 'tiers': id {key} не юнит")
        if value not in _TIERS:
            raise ValueError(f"{name}: ключ 'tiers': у юнита {key} значение не core и не optional")
    listed = yaml.safe_load(text).get("modules")
    taken = (
        {row["id"] for row in listed if isinstance(row, dict) and isinstance(row.get("id"), str)}
        if isinstance(listed, list)
        else set()
    )
    for unit_id in ids:
        if unit_id in taken:
            raise ValueError(f"{name}: юнит {unit_id}: id повторяется")
        taken.add(unit_id)
    if read_many is not None and units:
        blobs = read_many([init for init, _ in units])
        for init, row in units:
            row["purpose"] = _purpose(blobs.get(init), row["id"], name)
    return [row for _, row in units]
