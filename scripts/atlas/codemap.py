"""Карта кода ревизии: выгрузка на диск, классы через griffe, «кто использует» (Task 1.6c, ADR-ATL-001 §1-3).

Purpose: griffe и grimp читают файлы с диска, а `--ref` — ревизия: `checkout` выгружает .py корней modules.yaml
    в `data/atlas/checkout/<ключ>` (переживает процесс, хранятся 3 новейших;
    кэш grimp лежит рядом), `code_of` отдаёт `Code` по выгрузке и держит его в памяти процесса;
    `Code` строит по выгрузке граф grimp и отвечает видам `ref`/`card`: `describe` (вид, базы, абстрактные члены
    класса интерфейса; griffe.visit по файлам), `usage` (кто использует символ: импорты и вызовы по имени),
    `module_users` (файлы, импортирующие модуль целиком). Граф не строится (синтаксическая ошибка в исходниках) ->
    `usage`/`module_users` возвращают None, вид печатает одну строку USAGE_UNKNOWN.
Public API: DUNDERS, USAGE_UNKNOWN, Code, checkout, code_of, dotted, forget, is_test.
Stability: lite
"""

from __future__ import annotations

import ast
import builtins
import hashlib
import importlib
import importlib.util
import io
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from scripts.atlas.modules import resolve as module_of
from scripts.atlas.tree import AtlasError, Tree, resolve, run_git

__all__ = ["DUNDERS", "USAGE_UNKNOWN", "Code", "checkout", "code_of", "dotted", "forget", "is_test"]

CHECKOUT_DIR = Path("data/atlas/checkout")
KEEP = 3
_STALE_SECONDS = 3600
_CODES_MAX = 3
_WIN_PATH_LIMIT = 259  # MAX_PATH без завершающего нуля
_CODES: dict[tuple[str, str], Code] = {}

USAGE_UNKNOWN = "Кто использует: не определено (исходники не разбираются)"
_TEST_FILE = re.compile(r"(?:^|/)(?:test_[^/]*|[^/]*_test)\.py$")
_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef)
DUNDERS = frozenset(
    "__init__ __call__ __enter__ __exit__ __aenter__ __aexit__ __iter__ __next__ __getitem__ __setitem__ __len__ "
    "__contains__".split()
)
_STD = sys.stdlib_module_names | {"typing_extensions"} | set(dir(builtins))


def is_test(path: str) -> bool:
    """Тестовый файл: каталог `tests` на любой глубине, `test_*.py` или `*_test.py`."""
    return "/tests/" in f"/{path}" or bool(_TEST_FILE.search(path))


def dotted(path: str) -> str:
    """`a/b/c.py` -> `a.b.c`; `a/b/__init__.py` -> `a.b`."""
    parts = path.removesuffix(".py").split("/")
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _roots(tree: Tree, rows: list[dict]) -> list[str]:
    """Верхние каталоги `paths` строк modules.yaml, в которых в ревизии есть .py (отсортированы)."""
    present = {f.split("/")[0] for f in tree.files() if f.endswith(".py") and "/" in f}
    return sorted({e.split("/")[0] for r in rows for e in r["paths"]} & present)


def _unpack(tar_input: bytes, target: Path) -> None:
    """Распаковка tar-потока в `target`: системный `tar -f -` в cwd, при сбое — tarfile (строка в stderr)."""
    tar = shutil.which("tar")
    if not tar:
        print("atlas: tar not found, fallback to tarfile", file=sys.stderr)
    else:
        rc = subprocess.run([tar, "-x", "-f", "-"], input=tar_input, cwd=target, capture_output=True).returncode
        if not rc:
            return
        print(f"atlas: tar failed (rc={rc}), fallback to tarfile", file=sys.stderr)
    with tarfile.open(fileobj=io.BytesIO(tar_input)) as archive:
        archive.extractall(target, filter="data")


def _has_py(directory: Path) -> bool:
    return any(directory.rglob("*.py"))


def _long_paths_enabled() -> bool:
    """Windows: включены ли длинные пути (реестр HKLM, LongPathsEnabled == 1); ошибка реестра -> нет."""
    try:
        import winreg  # noqa: PLC0415 - модуль есть только в Windows

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem") as key:
            return winreg.QueryValueEx(key, "LongPathsEnabled")[0] == 1
    except (OSError, ImportError):
        return False


def _cache_dir(tree: Tree, roots: list[str], key: str) -> Path:
    """Каталог кэша выгрузок: `<repo>/data/atlas/checkout`; Windows без длинных путей и самый длинный файл выгрузки
    не влезает в MAX_PATH -> короткий корень `<temp>/atlas-checkout/<хэш корня репозитория>` (тоже постоянный);
    не влезает и он -> AtlasError (tar иначе падает молча)."""
    primary = tree.root / CHECKOUT_DIR
    if not roots or sys.platform != "win32" or _long_paths_enabled():
        return primary
    longest = max((len(f) for f in tree.files() if f.endswith(".py") and f.split("/")[0] in roots), default=0)

    def total(cache: Path) -> int:
        return len(os.path.abspath(cache / key)) + 1 + longest

    if total(primary) <= _WIN_PATH_LIMIT:
        return primary
    short = (
        Path(tempfile.gettempdir())
        / "atlas-checkout"
        / hashlib.sha256(str(tree.root.resolve()).encode()).hexdigest()[:8]
    )
    if total(short) <= _WIN_PATH_LIMIT:
        return short
    raise AtlasError(
        f"atlas: checkout path too long ({total(primary)} > {_WIN_PATH_LIMIT}): "
        "move the repository to a shorter path or enable LongPathsEnabled"
    )


def _discard(entry: Path) -> None:
    """Убрать запись кэша: сперва `rename` в `.del-*` (полу-удалённое под итоговым именем читалось бы как попадание)."""
    doomed = entry.parent / f".del-{uuid.uuid4().hex[:8]}"  # короче ключа: путь файлов внутри не растёт
    try:
        os.rename(entry, doomed)
    except OSError:  # внутри открытый файл (Windows PermissionError 5) или другой процесс уже убрал запись
        return
    shutil.rmtree(doomed, ignore_errors=True)


def _prune(cache: Path, current: str) -> None:
    """Оставить KEEP новейших выгрузок; лишние сперва переименовать в `.del-*` (полу-удалённое не должно читаться
    как попадание), потом удалить. Залежавшиеся `.tmp-*`/`.del-*` старше часа удаляются."""
    now = time.time()
    entries: list[tuple[float, Path]] = []
    for entry in cache.iterdir():
        try:
            mtime = entry.stat().st_mtime
        except OSError:
            continue
        if entry.name.startswith("."):
            if now - mtime > _STALE_SECONDS:
                shutil.rmtree(entry, ignore_errors=True)
        else:
            entries.append((mtime, entry))
    entries.sort(key=lambda e: e[0], reverse=True)
    for _, entry in entries[KEEP:]:
        if entry.name == current:
            continue
        _discard(entry)


def checkout(tree: Tree, rows: list[dict]) -> Path:
    """Выгрузка .py ревизии под верхние каталоги `paths` строк modules.yaml (только существующие в дереве).

    Каталог `<repo>/data/atlas/checkout/<sha[:12]>-<хэш корней>` (`_cache_dir`) живёт между процессами (хранятся
    KEEP новейших): есть каталог — это попадание, `git archive` не запускается. Распаковка идёт во временный
    каталог и одним `rename` встаёт под итоговое имя — недораспакованное дерево под итоговым именем не видно никому.
    """
    roots = _roots(tree, rows)
    digest = hashlib.sha256("\n".join(roots).encode()).hexdigest()[:8]
    key = f"{resolve(tree.root, tree.ref)[:12]}-{digest}"
    cache = _cache_dir(tree, roots, key)
    final = cache / key
    try:
        os.utime(final)
    except FileNotFoundError:
        pass  # нет выгрузки (или её только что убрали): промах
    else:
        if not roots or _has_py(final):
            return final
        _discard(final)  # пустая выгрузка при непустых корнях не должна залипнуть: промах
    cache.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".tmp-", dir=cache))  # короткое имя: самый длинный путь — итоговый
    try:
        if roots:  # `git archive` без путей выгрузил бы всё дерево
            specs = [f":(glob){r}/**/*.py" for r in roots]
            proc = run_git(tree.root, "-c", "core.autocrlf=false", "archive", "--format=tar", tree.ref, "--", *specs)
            if proc.returncode != 0:
                raise AtlasError("atlas: git archive failed")
            _unpack(proc.stdout, tmp)
            if not _has_py(tmp):
                raise AtlasError("atlas: empty checkout")
        try:
            os.rename(tmp, final)
        except OSError:
            if not final.exists():
                raise
            shutil.rmtree(tmp, ignore_errors=True)  # другой процесс успел раньше — берём его выгрузку
            return final
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    try:
        os.utime(final)  # tar мог восстановить время каталога из архива; для _prune нужно «сейчас»
    except OSError:
        pass
    _prune(cache, key)
    return final


def forget() -> None:
    """Сбросить память процесса о разобранных ревизиях (тесты имитируют так новый процесс)."""
    _CODES.clear()


def code_of(tree: Tree, rows: list[dict]) -> Code:
    """`Code` выгрузки ревизии; повторный вызов в процессе берёт уже разобранный `Code` из памяти (до 3 штук).

    Запись с `parsable=False` пересобирается (сбой разбора не залипает, как в 1.6e). Непустые корни при пустой
    выгрузке — `AtlasError`: пустое дерево иначе закэшировалось бы видом «файлов 0».
    """
    base = checkout(tree, rows)
    key = (str(base), json.dumps(rows, sort_keys=True, default=str))
    code = _CODES.get(key)
    if code is not None and code.parsable:
        return code
    code = Code(base, rows)
    if not code.files and _roots(tree, rows):
        raise AtlasError("atlas: empty checkout")
    _CODES.pop(key, None)
    _CODES[key] = code
    while len(_CODES) > _CODES_MAX:
        del _CODES[next(iter(_CODES))]
    return code


def _short(base: Any) -> str:
    return str(base).split("[")[0].rpartition(".")[2]


def _marked(m: Any) -> bool:
    """Член с abstractmethod: у `@property` + `@abstractmethod` griffe даёт Attribute с меткой, без decorators."""
    return not m.is_alias and "abstractmethod" in m.labels


def _defines(node: ast.stmt, name: str) -> bool:
    if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
        return node.name == name
    targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
    return any(isinstance(t, ast.Name) and t.id == name for t in targets)


def _names(fn: ast.AST) -> set[str]:
    """Локальные имена тела функции: Name, Attribute.attr, импорт-алиасы (docstring и комментарии не считаются)."""
    out: set[str] = set()
    for sub in ast.walk(fn):
        if isinstance(sub, ast.Name | ast.Attribute | ast.alias):
            out |= (
                {sub.id}
                if isinstance(sub, ast.Name)
                else {sub.attr}
                if isinstance(sub, ast.Attribute)
                else {sub.name, sub.asname or sub.name}
            )
    return out


class Code:
    """Выгрузка ревизии `base`: граф grimp, разбор файлов (кэш) и griffe-классы."""

    def __init__(self, base: Path, rows: list[dict]) -> None:
        self.base, self.rows, self.parsable = base, rows, True
        cut = len(str(base)) + 1
        self.files = sorted(
            os.path.join(d, f)[cut:].replace(os.sep, "/") for d, _, fs in os.walk(base) for f in fs if f.endswith(".py")
        )
        self.path_of = {dotted(f): f for f in self.files}
        self._graph: Any = False  # False — не строился, None — нет пакетов
        self._cache: dict[str, Any] = {}

    def _memo(self, key: str, make: Any) -> Any:
        if key not in self._cache:
            self._cache[key] = make()
        return self._cache[key]

    def text(self, path: str) -> str:
        return self._memo(
            f"t:{path}", lambda: (self.base / path).read_bytes().decode("utf-8", "replace").removeprefix("﻿")
        )

    def words(self, path: str) -> set[str]:
        return self._memo(f"w:{path}", lambda: set(re.findall(r"[A-Za-z_]\w*", self.text(path))))

    def own(self, module: str) -> list[str]:
        row = next(r for r in self.rows if r["id"] == module)
        near = tuple(row["paths"])
        return self._memo(
            f"o:{module}", lambda: [f for f in self.files if f.startswith(near) and module_of(f, self.rows) == module]
        )

    # ------------------------------------------------------------------ граф и разбор файлов

    def graph(self) -> Any:
        """Граф grimp по выгрузке; None — нет пакетов; сбой разбора -> parsable=False."""
        if self._graph is not False:
            return self._graph
        tops = sorted(
            {f.split("/")[0] for f in self.files if "/" in f and (self.base / f.split("/")[0] / "__init__.py").exists()}
        )
        self._graph = None
        if not tops:
            return None
        import grimp  # noqa: PLC0415 - тяжёлый импорт нужен только видам с графом

        logger, level = logging.getLogger("grimp"), logging.getLogger("grimp").level
        sys.path.insert(0, str(self.base))
        # find_spec берёт уже импортированный пакет из sys.modules (рабочее дерево): на время сборки убираем
        saved = {k: sys.modules.pop(k) for k in [k for k in sys.modules if k.split(".")[0] in tops]}
        logger.setLevel(logging.ERROR)  # «skipping module with too many dots» — logger.warning, не вывод Rust
        try:
            importlib.invalidate_caches()
            for top in tops:  # иначе --ref молча читал бы рабочее дерево
                spec = importlib.util.find_spec(top)
                if spec is None or not str(spec.origin or "").startswith(str(self.base)):
                    raise AtlasError("atlas: package found outside the checkout")
            self._graph = grimp.build_graph(
                *tops, include_external_packages=False, cache_dir=str(self.base / ".grimp_cache")
            )
        except AtlasError:
            raise
        except Exception:  # noqa: BLE001 - SourceSyntaxError и любой сбой разбора: вид печатает USAGE_UNKNOWN
            self.parsable = False
        finally:
            sys.path.remove(str(self.base))
            sys.modules.update(saved)
            logger.setLevel(level)
        return self._graph

    def _importers(self, mods: set[str]) -> set[str]:
        """Файлы, прямо импортирующие любой из модулей `mods` (граф), плюс файлы вне графа (каталог без __init__.py)."""
        graph = self.graph()
        found = set(
            self._memo("loose", lambda: [f for f in self.files if graph is None or dotted(f) not in graph.modules])
        )
        for mod in sorted(mods):
            if graph is not None and mod in graph.modules:
                found.update(p for m in graph.find_modules_that_directly_import(mod) if (p := self.path_of.get(m)))
        return found

    def info(self, path: str) -> dict | None:
        """Импорты (модуль, имя | None, локальное имя, строка) и вызовы по имени; None — файл не разбирается."""

        def make() -> dict | None:
            try:
                tree = ast.parse(self.text(path))
            except (SyntaxError, ValueError):
                return None
            pkg = dotted(path) if path.endswith("__init__.py") else dotted(path).rpartition(".")[0]
            imports, calls = [], []
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    head = pkg.split(".")[: len(pkg.split(".")) - node.level + 1] if node.level else []
                    mod = ".".join([*[h for h in head if h], *([node.module] if node.module else [])])
                    imports += [(mod, a.name, a.asname or a.name, a.lineno) for a in node.names]
                elif isinstance(node, ast.Import):
                    imports += [(a.name, None, a.asname or a.name, a.lineno) for a in node.names]
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    calls.append((node.func.id, node.lineno))
            return {"imports": imports, "calls": calls, "tree": tree}

        return self._memo(f"i:{path}", make)

    def count_tests(self, path: str, local: set[str]) -> int:
        """Число тест-функций файла (`test*` верхнего уровня и в `Test*`), в теле которых есть локальное имя."""
        body = self.info(path)["tree"].body  # type: ignore[index]
        funcs = [n for n in body if isinstance(n, _DEFS)]
        for cls in (n for n in body if isinstance(n, ast.ClassDef) and n.name.startswith("Test")):
            funcs += [n for n in cls.body if isinstance(n, _DEFS)]
        lines = self._memo(f"l:{path}", lambda: self.text(path).split("\n"))
        count = 0
        for fn in (f for f in funcs if f.name.startswith("test")):
            segment = "\n".join(lines[fn.lineno - 1 : fn.end_lineno])
            # текстовый отсев (docstring и комментарии не считаются — решает AST)
            count += any(n in segment for n in local) and bool(local & _names(fn))
        return count

    def defined_in(self, module: str, name: str, depth: int = 0) -> str:
        """Модуль, где `name` определён (class/def/присваивание): импорты `module` прослеживаются до определения."""
        file = self.path_of.get(module)
        tree = (self.info(file) or {}).get("tree") if file else None
        if tree is None or depth > 6 or any(_defines(n, name) for n in tree.body):
            return module
        target = self._imported(file).get(name)
        return self.defined_in(target.rpartition(".")[0], name, depth + 1) if target else module

    def _hits(self, path: str, mods: set[str], name: str) -> list[tuple[str, int]]:
        """(локальное имя, строка) импортов `name` из любого модуля `mods` в файле."""
        words = self.words(path)
        # импорт из модуля цепочки содержит имя и последний компонент модуля (или он относительный)
        if name not in words or not ({m.rpartition(".")[2] for m in mods} & words or "from ." in self.text(path)):
            return []
        if not (i := self.info(path)):
            return []
        return [(n, ln) for m, s, n, ln in i["imports"] if m in mods and s == name]

    # ------------------------------------------------------------------ кто использует

    def usage(self, module: str, defs: dict[str, str]) -> dict[str, dict] | None:
        """Имя -> {rows: [(путь, строка, 'импорт'|'вызов')], tests: [(путь, строка импорта, число тестов)]}.

        `defs`: имя -> модуль определения (или кортеж: определение и реэкспортёры). Символ без использований и тестов
        не попадает в итог. None — граф не строится (синтаксическая ошибка в исходниках).
        """
        self.graph()
        if not self.parsable:
            return None
        out: dict[str, dict] = {}
        for name in sorted(defs):
            chain = {defs[name]} if isinstance(defs[name], str) else set(defs[name])
            while grown := {  # реэкспорт: пакеты, чей __init__.py импортирует символ из цепочки
                dotted(p)
                for p in self._importers(chain)
                if p.endswith("__init__.py") and dotted(p) not in chain and self._hits(p, chain, name)
            }:
                chain |= grown
            rows: list[tuple[str, int, str]] = []
            tests: list[tuple[str, int, int]] = []
            for path in sorted(self._importers(chain)):
                test = is_test(path)
                if (module_of(path, self.rows) == module and not test) or not (hits := self._hits(path, chain, name)):
                    continue
                local, info = {n for n, _ in hits}, self.info(path)
                if test:
                    tests.append((path, min(ln for _, ln in hits), self.count_tests(path, local)))  # type: ignore[index]
                else:
                    rows += [(path, ln, "импорт") for _, ln in hits]
                    rows += [(path, ln, "вызов") for n, ln in info["calls"] if n in local]  # type: ignore[index]
            if rows or tests:
                out[name] = {"rows": sorted(rows), "tests": tests}
        return out

    def module_users(self, module: str) -> list[tuple[str, int]] | None:
        """(путь, строка первого импорта) файлов вне модуля, импортирующих его целиком; None — граф не строится."""
        self.graph()
        if not self.parsable:
            return None
        own, row = self.own(module), next(r for r in self.rows if r["id"] == module)
        needles = {e.rstrip("/").removesuffix(".py").rsplit("/", 1)[-1] for e in row["paths"]}
        targets, found = {dotted(f) for f in own}, []
        for path in sorted(self._importers(targets) - set(own)):
            if needles & self.words(path) and (i := self.info(path)):
                lines = [ln for m, n, _, ln in i["imports"] if m in targets or (n and f"{m}.{n}" in targets)]
                found += [(path, min(lines))] if lines else []
        return found

    # ------------------------------------------------------------------ классы интерфейсов (griffe)

    def _class(self, path: str, seen: frozenset[str] = frozenset()) -> Any:
        """Класс по точечному пути (griffe.visit по файлу); алиас раскрывается по target_path."""
        import griffe  # noqa: PLC0415

        *head, last = path.split(".")
        rel = "/".join(head)
        file = next((c for c in (f"{rel}.py", f"{rel}/__init__.py") if c in self.files), None)
        if file is None:
            return None
        mod = self._memo(
            f"g:{file}", lambda: griffe.visit(".".join(head), filepath=self.base / file, code=self.text(file))
        )
        obj = mod.members.get(last)
        if obj is not None and obj.is_alias:  # griffe.visit по одному файлу неверно считает относительные импорты
            target = self._imported(file).get(last, obj.target_path)
            return None if path in seen else self._class(target, seen | {path})
        return obj if obj is not None and obj.is_class else None

    def _imported(self, file: str) -> dict[str, str]:
        """Локальное имя -> абсолютное имя цели импорта файла (относительные уровни разрешены разбором AST)."""
        info = self.info(file) or {"imports": []}
        return {n: f"{m}.{s}" if s else m for m, s, n, _ in info["imports"] if s or "." not in n}

    def _base_path(self, cls: Any, base: Any) -> str:
        """Абсолютный путь базы: голова имени — по импортам файла класса, иначе (локальный класс) путь griffe."""
        text = str(base).split("[")[0]
        head, _, rest = text.partition(".")
        file = Path(cls.filepath).relative_to(self.base).as_posix()
        target = self._imported(file).get(head)
        return f"{target}.{rest}" if target and rest else target or getattr(base, "canonical_path", text)

    def _abstract(
        self, cls: Any, seen: frozenset[str] = frozenset()
    ) -> tuple[set[str], set[str], list[tuple[str, set[str]]]]:
        """(все абстрактные имена, свои, [(база, её новые имена)]); база не из stdlib и не разрешена -> LookupError.

        У Protocol абстрактны все публичные члены и значимые dunder тела, у ABC — члены с abstractmethod.
        """
        proto = any(_short(b) == "Protocol" for b in cls.bases)
        own = {
            n
            for n, m in cls.members.items()
            if (not n.startswith("_") or n in DUNDERS)
            and not m.is_alias
            and ((m.is_function or m.is_attribute) if proto else _marked(m))
        }
        names, per_base = set(own), []
        for base in cls.bases:
            path = self._base_path(cls, base)
            if (target := self._class(path)) is None:
                if path.split(".")[0] not in _STD:
                    raise LookupError
            elif target.path not in seen:
                got = self._abstract(target, seen | {cls.path})[0]
                per_base.append((_short(base), got - names))
                names |= got
        return names, own, per_base

    def describe(self, path: str, name: str) -> tuple[str, list[tuple[str, list[str]]]] | None:
        """(строка после `вид: `, [(база, унаследованные абстрактные)]) класса `name` из `path`; None — не определён."""
        try:
            cls = self._class(f"{dotted(path)}.{name}")
            names, own, per_base = self._abstract(cls)
            bases = [_short(b) for b in cls.bases]
            if "Protocol" in bases:
                kind = "Protocol" + (
                    ", runtime_checkable" if any("runtime_checkable" in d.callable_path for d in cls.decorators) else ""
                )
            else:
                kind = "ABC" if {"ABC", "ABCMeta"} & set(bases) or any(map(_marked, cls.members.values())) else "класс"
            head = f"{kind}; базы: {', '.join(bases) or '—'}; абстрактных {len(names)} (своих {len(own)})"
            return head, [(b, sorted(n)) for b, n in per_base if n]
        except Exception:  # noqa: BLE001 - LookupError (база не разрешена) и любой сбой griffe: вид не определён
            return None
