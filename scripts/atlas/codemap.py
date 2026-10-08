"""Карта кода ревизии: выгрузка на диск, классы через griffe, «кто использует» (Task 1.6c, ADR-ATL-001 §1-3).

Purpose: griffe и grimp читают файлы с диска, а `--ref` — ревизия: `checkout` выгружает .py корней modules.yaml;
    `Code` строит по выгрузке граф grimp и отвечает видам `ref`/`card`: `describe` (вид, базы, абстрактные члены
    класса интерфейса; griffe.visit по файлам), `usage` (кто использует символ: импорты и вызовы по имени),
    `module_users` (файлы, импортирующие модуль целиком). Граф не строится (синтаксическая ошибка в исходниках) ->
    `usage`/`module_users` возвращают None, вид печатает одну строку USAGE_UNKNOWN.
Public API: DUNDERS, USAGE_UNKNOWN, Code, checkout, dotted, is_test.
Stability: lite
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import io
import logging
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from scripts.atlas.modules import resolve as module_of
from scripts.atlas.tree import AtlasError, Tree, run_git

__all__ = ["DUNDERS", "USAGE_UNKNOWN", "Code", "checkout", "dotted", "is_test"]

USAGE_UNKNOWN = "Кто использует: не определено (исходники не разбираются)"
_TEST_FILE = re.compile(r"(?:^|/)(?:test_[^/]*|[^/]*_test)\.py$")
_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef)
DUNDERS = frozenset(
    "__init__ __call__ __enter__ __exit__ __aenter__ __aexit__ __iter__ __next__ __getitem__ __setitem__ __len__ "
    "__contains__".split()
)
_STD = sys.stdlib_module_names | {"typing_extensions"}


def is_test(path: str) -> bool:
    """Тестовый файл: каталог `tests` на любой глубине, `test_*.py` или `*_test.py`."""
    return "/tests/" in f"/{path}" or bool(_TEST_FILE.search(path))


def dotted(path: str) -> str:
    """`a/b/c.py` -> `a.b.c`; `a/b/__init__.py` -> `a.b`."""
    parts = path.removesuffix(".py").split("/")
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


@contextmanager
def checkout(tree: Tree, rows: list[dict]) -> Iterator[Path]:
    """Выгрузка .py ревизии под верхние каталоги `paths` строк modules.yaml (только существующие в дереве).

    Каталог — в /dev/shm, если он есть (создание тысяч файлов на диске в разы дольше); распаковка системным `tar`,
    без него — tarfile с фильтром `data`, как Tree.materialize.
    """
    present = {f.split("/")[0] for f in tree.files() if f.endswith(".py") and "/" in f}
    roots = sorted({e.split("/")[0] for r in rows for e in r["paths"]} & present)
    base = Path(tempfile.mkdtemp(prefix="atlas-", dir="/dev/shm" if os.access("/dev/shm", os.W_OK) else None))
    try:
        if roots:  # `git archive` без путей выгрузил бы всё дерево
            specs = [f":(glob){r}/**/*.py" for r in roots]
            proc = run_git(tree.root, "-c", "core.autocrlf=false", "archive", "--format=tar", tree.ref, "--", *specs)
            if proc.returncode != 0:
                raise AtlasError("atlas: git archive failed")
            tar = shutil.which("tar")
            if (
                not tar
                or subprocess.run([tar, "-x", "-C", str(base)], input=proc.stdout, capture_output=True).returncode
            ):
                with tarfile.open(fileobj=io.BytesIO(proc.stdout)) as archive:
                    archive.extractall(base, filter="data")
        yield base
    finally:
        shutil.rmtree(base, ignore_errors=True)


def _short(base: Any) -> str:
    return str(base).split("[")[0].rpartition(".")[2]


def _marked(m: Any) -> bool:
    return not m.is_alias and m.is_function and any(d.callable_path.endswith("abstractmethod") for d in m.decorators)


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
            self._graph = grimp.build_graph(*tops, include_external_packages=False, cache_dir=None)
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

    def test_names(self, path: str) -> list[set[str]]:
        """Локальные имена по тест-функциям файла (`test*` верхнего уровня и в `Test*`)."""

        def make() -> list[set[str]]:
            body = self.info(path)["tree"].body  # type: ignore[index]
            funcs = [n for n in body if isinstance(n, _DEFS)]
            for cls in (n for n in body if isinstance(n, ast.ClassDef) and n.name.startswith("Test")):
                funcs += [n for n in cls.body if isinstance(n, _DEFS)]
            return [_names(fn) for fn in funcs if fn.name.startswith("test")]

        return self._memo(f"n:{path}", make)

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

        `defs`: имя -> точечное имя модуля определения. Символ без использований вне модуля и без тестов не попадает
        в итог. None — граф не строится (синтаксическая ошибка в исходниках).
        """
        self.graph()
        if not self.parsable:
            return None
        out: dict[str, dict] = {}
        for name in sorted(defs):
            chain = {defs[name]}
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
                    tests.append((path, min(ln for _, ln in hits), sum(bool(local & t) for t in self.test_names(path))))  # type: ignore[index]
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
        if obj is not None and obj.is_alias:
            return None if path in seen else self._class(obj.target_path, seen | {path})
        return obj if obj is not None and obj.is_class else None

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
            path = getattr(base, "canonical_path", str(base))
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
