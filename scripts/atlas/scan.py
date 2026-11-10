"""Сканер исходников: неизменяемые факты о `.py`-файлах ревизии git или фикстуры в памяти, кэш по oid блоба (map-A1).

Purpose: один код читает дерево git (`Tree`) и словарь в памяти (`DictSource`) и отдаёт `FileFacts`: импорты
    (hard / lazy / tc), классы, функции, `__all__`, шапку `Tier:`/`Contour:`, команды и потоки. Факты зависят только от
    содержимого блоба, поэтому хранятся в `scan_cache` по `(oid, SCANNER)`: новый SHA разбирает лишь изменённые файлы.
    `ImportIndex` разрешает импорты в пути файлов индекса. Модуль не импортирует `scripts.arch_map` (карта удаляется)
    и адаптеры atlas; разбор перенесён копией из `scripts/arch_map/build.py`.
Public API: Source, DictSource, ImportRec, ClassFact, DefFact, CallFact, IoFact, ThreadSite, FileFacts, ScanResult,
    Resolved, ImportIndex, scan, scan_text, resolve_relative, SCANNER, MAX_BLOB_BYTES, THREAD_PATTERNS.
    Правило ошибок: `scan_text` и разбор блоба не бросают; непарсящийся файл — `FileFacts(error=<имя исключения>)`.
Stability: lite

Правка этого файла меняет `SCANNER` и тем самым сбрасывает кэш фактов (цена — один холодный скан).

Объявленные команды (R2, Task 4.2a): `FileFacts.command_specs` — записи `(name, line, form, scope)` по каждому
`def command_specs` файла на любой глубине; `scope` — qualname самого `def command_specs` (`Service.command_specs`,
`build.command_specs`), `line` — строка элемента. Разбираются элементы литеральной коллекции каждого `return` тела
(вложенные def не в счёте): кортеж с первым строковым литералом -> `form: "tuple"`; `CommandSpec(...)` с литеральным
именем (первый позиционный или `name=`) -> `"call"`; прочее (вызов, имя, `*x`) и `return` не литеральной коллекции ->
`"dynamic"` с `name == ""`. `None` — в файле нет `def command_specs`; `()` — есть, элементов нет.
`command_specs_dynamic` — число записей `dynamic`. Записи `dynamic` адреса имени не дают: паспорт их только считает
(`status.dynamic`), в `runtime.commands` идут только `tuple` и `call`.

Шапка модуля (R8): в очищенном докстринге модуля строки `Tier: core|optional|frozen` (значение без учёта регистра;
другое значение — None; побеждает первая допустимая строка) и `Contour: a, b` (элементы через запятую, пустые
отброшены; первая подходящая строка побеждает).

Шапки заморозки (Task 4.2b-1): `FileFacts.freeze` — `(date, text, line)` каждой строки СЫРОГО докстринга модуля,
что начинается с `FREEZE YYYY-MM-DD:` (`read_freeze`); поле A1 (`v2_error` его не трогает), `doc` не меняется.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal, Protocol

from scripts.atlas.store import get_scans, put_scans

__all__ = [
    "MAX_BLOB_BYTES",
    "SCANNER",
    "THREAD_PATTERNS",
    "CallFact",
    "ClassFact",
    "DefFact",
    "DictSource",
    "FileFacts",
    "ImportIndex",
    "ImportRec",
    "IoFact",
    "Resolved",
    "ScanResult",
    "Source",
    "ThreadSite",
    "resolve_relative",
    "scan",
    "scan_text",
]

SCANNER = "1-" + hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12]
MAX_BLOB_BYTES = 1_048_576  # блоб длиннее не декодируется и не разбирается (D1)

IMPORT_GUARDS = frozenset({"ImportError", "ModuleNotFoundError", "Exception", "BaseException"})
TIERS = ("core", "optional", "frozen")
# конструкторы для `ThreadSite`; константа, не конфиг (ключ кэша — хеш файла)
THREAD_PATTERNS = ("Thread", "Timer", "Observer")
DOC_HEADER = re.compile(r"^(Tier|Contour):[ \t]*(.+)$", re.MULTILINE)
FREEZE_HEADER = re.compile(r"FREEZE (\d{4}-\d{2}-\d{2}):(.*)", re.ASCII)  # `match` по сырой строке: только с начала


# --------------------------------------------------------------------------- факты


@dataclass(frozen=True)
class ImportRec:
    kind: Literal["hard", "lazy", "tc"]
    line: int
    level: int
    module: str | None
    names: tuple[str, ...]
    is_from: bool
    guarded: bool  # внутри try, чьи обработчики ловят ImportError/Exception


@dataclass(frozen=True)
class ClassFact:
    name: str
    bases: tuple[str, ...]
    line: int
    methods: tuple[str, ...]  # def/async def прямо в теле, без `_private` (dunder остаются), без повторов
    style: Literal["Protocol", "ABC", "class"]


@dataclass(frozen=True)
class DefFact:
    """Определение (v2, Task 4.1): класс, функция или метод — каждый `def`/`class` на любой глубине вложенности.

    qualname: имя через точку от модуля (`Cls.method`, `func`, `func.inner`); у метода всегда с классом.
    kind: `class`, `function` (вне класса) или `method` (def прямо в теле класса, dunder тоже).
    line: строка `def`/`class` (не декоратора).
    signature: `ast.unparse(args)` + ` -> <returns>` при аннотации возврата; у класса `""`.
    decorators: листовые имена декораторов (`a.b.c` -> `c`, вызов `d(x)` -> `d`).
    abstract: есть декоратор `abstractmethod`; у класса — основа `ABC`/`Protocol` не считается, всегда False.
    is_async: `async def`.
    doc: первый абзац докстринга (до пустой строки), иначе None.
    bases: `ast.unparse` каждой основы класса; у функции и метода `()`.
    """

    qualname: str
    kind: Literal["class", "function", "method"]
    line: int
    signature: str = ""
    decorators: tuple[str, ...] = ()
    abstract: bool = False
    is_async: bool = False
    doc: str | None = None
    bases: tuple[str, ...] = ()


@dataclass(frozen=True)
class CallFact:
    """Вызов `name(...)` (v2): какое имя, где и откуда.

    name: последнее имя вызываемого (`f` в `f()`, `m` в `x.m()`).
    line: строка вызова.
    enclosing: qualname ближайшего объемлющего def/class; на уровне модуля `<module>`.
    receiver: None у голого имени (`f()`), иначе `ast.unparse(func.value)` (`self`, `os.path`, `a.b`).
    """

    name: str
    line: int
    enclosing: str = "<module>"
    receiver: str | None = None


@dataclass(frozen=True)
class IoFact:
    """Побочный эффект на файловой системе (v2); `open`/`read_text` сюда не входят.

    op: `watch` — `X.schedule(handler, path, ...)`, где `X` присвоен `Observer(...)` в той же функции
        (`self.<a>` — в том же классе); путь = второй позиционный аргумент, иначе `path=`, иначе записи нет
        (`sch.schedule(a, b, 1, "p")` без `Observer` — не watch).
        `replaces` — `os.replace` / `os.rename` / `shutil.move`; путь = второй позиционный аргумент
        (`Path.replace` и `str.replace` — нет: путь в получателе).
    path: `ast.unparse` аргумента пути (источник, не значение: `str(self._path.parent)`).
    line: строка вызова.
    enclosing: как у `CallFact`.
    """

    op: Literal["watch", "replaces"]
    path: str
    line: int
    enclosing: str = "<module>"


@dataclass(frozen=True)
class ThreadSite:
    """Место запуска потока (v2): конструктор из `THREAD_PATTERNS` с `.start()` той же цели в той же функции.

    pattern: имя конструктора из `THREAD_PATTERNS` (`Thread`, `Timer`, `Observer`).
    line: строка КОНСТРУКТОРА (не `.start()`).
    enclosing: как у `CallFact`.
    daemon: литерал `daemon=` у конструктора: True / False; не задан или не литерал -> None.
    Запись есть только при `.start()`: конструктор без запуска записи не даёт; цепочка
    `Thread(target=f, daemon=True).start()` запись даёт.
    """

    pattern: str
    line: int
    enclosing: str = "<module>"
    daemon: bool | None = None


_KIND_CODE = {"class": "c", "function": "f", "method": "m"}  # вид DefFact в теле кэша
_KIND_NAME = {v: k for k, v in _KIND_CODE.items()}


@dataclass(frozen=True)
class FileFacts:
    loc: int = 0  # непустые строки
    doc: str | None = None  # первая непустая строка докстринга модуля
    all: tuple[str, ...] | None = None  # литеральный __all__, иначе None
    classes: tuple[ClassFact, ...] = ()
    functions: tuple[str, ...] = ()  # публичные функции верхнего уровня
    imports: tuple[ImportRec, ...] = ()
    commands: tuple[str, ...] = ()
    threads: tuple[tuple[str, int], ...] = ()  # (имя, строка) вызовов Thread(name=...)
    tier: str | None = None
    contour: tuple[str, ...] | None = None
    error: str | None = None  # имя исключения разбора или "BlobTooLarge"
    # --- v2 (Task 4.1); поля A1 выше не меняются. Разбор v2 — в своём `try`: сбой не трогает поля A1.
    defs: tuple[DefFact, ...] = ()  # все class/def/method с qualname; ClassFact.methods A1 — имена без строк, остаётся
    calls: tuple[CallFact, ...] = ()  # все вызовы файла
    io: tuple[IoFact, ...] = ()  # watch и replaces
    thread_sites: tuple[ThreadSite, ...] = ()  # пуски потоков по `THREAD_PATTERNS`
    test_defs: tuple[tuple[str, int], ...] = ()  # (qualname, строка): функции с префиксом `test` и методы в `Test*`
    v2_error: str | None = None  # имя исключения разбора полей v2 (поля A1 при этом целы), иначе None
    # --- Task 4.2a: (name, line, form, scope) по `def command_specs`; None — объявления в файле нет (докстринг модуля)
    command_specs: tuple[tuple[str, int, str, str], ...] | None = None
    # --- Task 4.2b-1: шапки `FREEZE YYYY-MM-DD: текст` в докстринге модуля — (date, text, line), порядок строк файла.
    # `date` — `YYYY-MM-DD`, `text` — всё после `FREEZE YYYY-MM-DD: ` (без хвостовых пробелов), `line` — строка файла
    # (`Constant.lineno` докстринга + индекс сырой строки; `get_docstring` строк не даёт). `()` — шапок нет или файла
    # с докстрингом нет. Не меняет `doc`; в `to_json`/`from_json` попадает (иначе тёплый вызов даст `()`).
    freeze: tuple[tuple[str, str, int], ...] = ()

    @property
    def command_specs_dynamic(self) -> int:
        """Число динамических элементов `command_specs` (не литерал): паспорт кладёт их в `status.dynamic`."""
        return sum(1 for _, _, form, _ in self.command_specs or () if form == "dynamic")

    def to_json(self) -> str:
        strs: list[str] = []
        index: dict[str, int] = {}

        def ix(text: str) -> int:
            if text not in index:
                index[text] = len(strs)
                strs.append(text)
            return index[text]

        data = {
            "loc": self.loc,
            "doc": self.doc,
            "all": self.all,
            "classes": [[c.name, c.bases, c.line, c.methods, c.style] for c in self.classes],
            "functions": self.functions,
            "imports": [[i.kind, i.line, i.level, i.module, i.names, i.is_from, i.guarded] for i in self.imports],
            "commands": self.commands,
            "threads": self.threads,
            "tier": self.tier,
            "contour": self.contour,
            "error": self.error,
            # v2 — сжатая форма (гейт размера `scan_cache` ≤ 4× A1): строки имён, qualname и получателей — одна
            # таблица `strs` на файл, записи ссылаются на неё индексом; `calls` и `test_defs` — плоские массивы
            # целых фиксированного шага (4 и 2). В памяти — те же dataclass'ы.
            "strs": strs,
            "defs": [
                [ix(d.qualname), _KIND_CODE[d.kind], d.line, d.signature, d.decorators, int(d.abstract)]
                + [int(d.is_async), d.doc, d.bases]
                for d in self.defs
            ],
            "calls": [
                v
                for c in self.calls
                for v in (ix(c.name), c.line, ix(c.enclosing), -1 if c.receiver is None else ix(c.receiver))
            ],
            "io": [[i.op, i.path, i.line, ix(i.enclosing)] for i in self.io],
            "thread_sites": [[t.pattern, t.line, ix(t.enclosing), t.daemon] for t in self.thread_sites],
            "test_defs": [v for q, ln in self.test_defs for v in (ix(q), ln)],
            "v2_error": self.v2_error,
            "command_specs": None
            if self.command_specs is None
            else [[n, ln, f, ix(sc)] for n, ln, f, sc in self.command_specs],
            "freeze": [[date, text, ln] for date, text, ln in self.freeze],
        }
        # UTF-8 без экранирования: кириллица в `doc` иначе стоит 6 байт на букву (гейт размера `scan_cache`, Task 4.1).
        body = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
        try:
            body.encode("utf-8")
        except UnicodeEncodeError:  # одиночный суррогат: тело не кодируется в UTF-8
            body = json.dumps(data, separators=(",", ":"))  # ASCII: одиночный суррогат не ломает запись в sqlite
        return body

    @classmethod
    def from_json(cls, text: str) -> FileFacts:
        """Обратное к `to_json`; тело неверной формы -> исключение (для `scan` это промах кэша).

        v2: читает d["strs"], d["defs"], d["calls"], d["io"], d["thread_sites"], d["test_defs"], d["v2_error"],
        d["command_specs"], d["freeze"] через `d[...]` (не `d.get`): тело старой формы без этих ключей бросает,
        `scan()` считает это промахом и разбирает заново.
        """
        d = json.loads(text)
        strs, calls, tests = d["strs"], d["calls"], d["test_defs"]
        return cls(
            loc=d["loc"],
            doc=d["doc"],
            all=None if d["all"] is None else tuple(d["all"]),
            classes=tuple(ClassFact(n, tuple(b), ln, tuple(m), s) for n, b, ln, m, s in d["classes"]),
            functions=tuple(d["functions"]),
            imports=tuple(
                ImportRec(k, ln, lv, mod, tuple(names), frm, grd) for k, ln, lv, mod, names, frm, grd in d["imports"]
            ),
            commands=tuple(d["commands"]),
            threads=tuple((n, ln) for n, ln in d["threads"]),
            tier=d["tier"],
            contour=None if d["contour"] is None else tuple(d["contour"]),
            error=d["error"],
            defs=tuple(
                DefFact(strs[q], _KIND_NAME[k], ln, sig, tuple(dec), bool(ab), bool(asy), doc, tuple(b))
                for q, k, ln, sig, dec, ab, asy, doc, b in d["defs"]
            ),
            calls=tuple(
                CallFact(
                    strs[calls[i]], calls[i + 1], strs[calls[i + 2]], None if calls[i + 3] < 0 else strs[calls[i + 3]]
                )
                for i in range(0, len(calls), 4)
            ),
            io=tuple(IoFact(op, p, ln, strs[enc]) for op, p, ln, enc in d["io"]),
            thread_sites=tuple(ThreadSite(p, ln, strs[enc], dmn) for p, ln, enc, dmn in d["thread_sites"]),
            test_defs=tuple((strs[tests[i]], tests[i + 1]) for i in range(0, len(tests), 2)),
            v2_error=d["v2_error"],
            command_specs=None
            if d["command_specs"] is None
            else tuple((n, ln, f, strs[sc]) for n, ln, f, sc in d["command_specs"]),
            freeze=tuple((date, text, ln) for date, text, ln in d["freeze"]),
        )


# --------------------------------------------------------------------------- разбор одного файла (порт из карты)


def is_type_checking(test: ast.expr) -> bool:
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
    )


def catches_import_error(handler: ast.ExceptHandler) -> bool:
    """Обработчик ловит ImportError / ModuleNotFoundError / Exception (или голый except)."""
    if handler.type is None:
        return True
    types = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return any(leaf_name(x) in IMPORT_GUARDS for x in types)


def collect_imports(tree: ast.Module) -> tuple[ImportRec, ...]:
    """Все импорты модуля с классом hard / lazy / tc (обход с пометкой контекста).

    `tc` побеждает на любой глубине, в том числе во вложенном `def` (отступление от карты, R9).
    """
    found: list[ImportRec] = []

    def handle(stmt: ast.AST, kind: str, guarded: bool) -> None:
        if isinstance(stmt, ast.Import):
            found.extend(ImportRec(kind, stmt.lineno, 0, a.name, (), False, guarded) for a in stmt.names)  # type: ignore[arg-type]
        elif isinstance(stmt, ast.ImportFrom):
            names = tuple(a.name for a in stmt.names)
            found.append(ImportRec(kind, stmt.lineno, stmt.level, stmt.module, names, True, guarded))  # type: ignore[arg-type]
        elif isinstance(stmt, ast.If):
            inner = "tc" if is_type_checking(stmt.test) else kind
            for sub in stmt.body:
                handle(sub, inner, guarded)
            for sub in stmt.orelse:
                handle(sub, kind, guarded)
        elif isinstance(stmt, (ast.Try, ast.TryStar)):
            protected = guarded or any(catches_import_error(h) for h in stmt.handlers)
            for sub in stmt.body:
                handle(sub, kind, protected)
            for sub in [*stmt.handlers, *stmt.orelse, *stmt.finalbody]:
                handle(sub, kind, guarded)
        elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            # тело def выполняется позже: try вокруг него импорт не защищает;
            # под `if TYPE_CHECKING` функции в рантайме нет -> tc
            visit(stmt, "tc" if kind == "tc" else "lazy", False)
        else:
            visit(stmt, kind, guarded)

    def visit(node: ast.AST, kind: str, guarded: bool) -> None:
        for child in ast.iter_child_nodes(node):
            handle(child, kind, guarded)

    visit(tree, "hard", False)
    return tuple(found)


def leaf_name(expr: ast.expr) -> str:
    while isinstance(expr, ast.Subscript):
        expr = expr.value
    if isinstance(expr, ast.Name):
        return expr.id
    return expr.attr if isinstance(expr, ast.Attribute) else ""


def class_style(node: ast.ClassDef, known: dict[str, str]) -> str:
    """Protocol / ABC / class; наследование от интерфейса того же файла передаёт его стиль."""
    leaves = [leaf_name(b) for b in node.bases]
    if "Protocol" in leaves:
        return "Protocol"
    metas = [leaf_name(k.value) for k in node.keywords if k.arg == "metaclass"]
    if "ABC" in leaves or "ABCMeta" in metas:
        return "ABC"
    for leaf in leaves:
        if known.get(leaf, "class") != "class":
            return known[leaf]
    return "class"


def read_all(tree: ast.Module) -> tuple[str, ...] | None:
    """Литеральный `__all__` (в т. ч. с `+=`); нет или не литерал — None."""
    value: tuple[str, ...] | None = None
    for stmt in tree.body:
        if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
            if any(isinstance(t, ast.Name) and t.id == "__all__" for t in targets):
                value = literal_names(stmt.value)
        elif isinstance(stmt, ast.AugAssign) and isinstance(stmt.target, ast.Name) and stmt.target.id == "__all__":
            extra = literal_names(stmt.value) if isinstance(stmt.op, ast.Add) else None
            value = None if value is None or extra is None else value + extra
        elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            func = stmt.value.func  # __all__.extend(...) и т. п. — не разбираем, считаем не литералом
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "__all__":
                return None
    return value


def literal_names(expr: ast.expr | None) -> tuple[str, ...] | None:
    if not isinstance(expr, (ast.List, ast.Tuple)):
        return None
    if all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in expr.elts):
        return tuple(e.value for e in expr.elts)  # type: ignore[union-attr]
    return None


def literal_str(expr: ast.expr | None) -> str | None:
    return expr.value if isinstance(expr, ast.Constant) and isinstance(expr.value, str) else None


def collect_derived(tree: ast.Module) -> tuple[tuple[str, ...], tuple[tuple[str, int], ...]]:
    """Команды (commands = {...} в классах, register_command("...")) и потоки Thread(name=...)."""
    commands: set[str] = set()
    threads: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for stmt in node.body:
                if isinstance(stmt, ast.Assign):
                    targets, value = stmt.targets, stmt.value
                elif isinstance(stmt, ast.AnnAssign):
                    targets, value = [stmt.target], stmt.value
                else:
                    continue
                if isinstance(value, ast.Dict) and any(isinstance(x, ast.Name) and x.id == "commands" for x in targets):
                    commands.update(k for k in map(literal_str, value.keys) if k)
        elif isinstance(node, ast.Call):
            func = node.func
            if leaf_name(func) == "register_command" and node.args:
                name = literal_str(node.args[0])
                if name:
                    commands.add(name)
            is_thread = (isinstance(func, ast.Name) and func.id == "Thread") or (
                isinstance(func, ast.Attribute)
                and func.attr == "Thread"
                and isinstance(func.value, ast.Name)
                and func.value.id == "threading"
            )
            if is_thread:
                for kw in node.keywords:
                    if kw.arg == "name":
                        threads.append((literal_str(kw.value) or ast.unparse(kw.value), node.lineno))
    threads.sort(key=lambda x: x[1])  # sort устойчив: порядок обхода внутри строки сохраняется
    return tuple(sorted(commands)), tuple(threads)


def read_doc_headers(doc: str) -> tuple[str | None, tuple[str, ...] | None]:
    """Строки `Tier: core|optional|frozen` и `Contour: a, b` из докстринга; первая подходящая побеждает."""
    tier: str | None = None
    contour: tuple[str, ...] | None = None
    for match in DOC_HEADER.finditer(doc):
        value = match.group(2).strip()
        if match.group(1) == "Tier":
            if tier is None and value.lower() in TIERS:
                tier = value.lower()
        elif contour is None:
            contour = tuple(x.strip() for x in value.split(",") if x.strip()) or None
    return tier, contour


def read_freeze(tree: ast.Module) -> tuple[tuple[str, str, int], ...]:
    """Шапки `FREEZE YYYY-MM-DD: текст` докстринга модуля: `(date, text, line)` в порядке строк файла.

    Строки — сырой `value.split("\\n")` константы докстринга (не `get_docstring`: тот чистит отступы и строк не даёт);
    `line` = `Constant.lineno` + индекс строки. Шапка — строка, что начинается с `FREEZE YYYY-MM-DD:`; `text` — хвост
    после `FREEZE YYYY-MM-DD: ` без хвостовых пробелов. Докстринга нет — `()`.
    Ограничения: `line` точен, пока в докстринге нет `\\`-продолжений строк и литералов `\\n` (иначе строка исходника
    и индекс расходятся); дата проверяется регэкспом, не календарём; пробелы после первого остаются в `text`.
    """
    first = tree.body[0] if tree.body else None
    if not (
        isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str)
    ):
        return ()
    heads: list[tuple[str, str, int]] = []
    for index, raw in enumerate(first.value.value.split("\n")):
        match = FREEZE_HEADER.match(raw)
        if match:
            heads.append((match.group(1), match.group(2).removeprefix(" ").rstrip(), first.value.lineno + index))
    return tuple(heads)


def _is_dunder(name: str) -> bool:
    return len(name) > 4 and name.startswith("__") and name.endswith("__")


def _class_fact(node: ast.ClassDef, styles: dict[str, str]) -> ClassFact:
    names = (m.name for m in node.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)))
    methods = tuple(dict.fromkeys(n for n in names if not n.startswith("_") or _is_dunder(n)))
    styles[node.name] = style = class_style(node, styles)
    return ClassFact(node.name, tuple(ast.unparse(b) for b in node.bases), node.lineno, methods, style)  # type: ignore[arg-type]


def _loc(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.strip())


# --------------------------------------------------------------------------- факты v2 (Task 4.1)

_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)
_REPLACES = frozenset({("os", "replace"), ("os", "rename"), ("shutil", "move")})


def _decorator_name(expr: ast.expr) -> str:
    """Листовое имя декоратора: `a.b.c` -> `c`, `d(x)` -> `d`; иное выражение — его исходник."""
    if isinstance(expr, ast.Call):
        expr = expr.func
    return leaf_name(expr) or ast.unparse(expr)


def _first_paragraph(node: ast.AST) -> str | None:
    doc = ast.get_docstring(node)  # type: ignore[arg-type]
    if not doc:
        return None
    lines: list[str] = []
    for line in doc.splitlines():
        if not line.strip():
            break
        lines.append(line.strip())
    return " ".join(lines) or None


def _ctor_pattern(expr: ast.expr | None) -> str | None:
    """Имя конструктора из `THREAD_PATTERNS`, если `expr` — его вызов (`Thread(...)`, `threading.Thread(...)`)."""
    if isinstance(expr, ast.Call) and isinstance(expr.func, (ast.Name, ast.Attribute)):
        name = leaf_name(expr.func)
        if name in THREAD_PATTERNS:
            return name
    return None


def _daemon_literal(call: ast.Call) -> bool | None:
    for kw in call.keywords:
        if kw.arg == "daemon":
            value = kw.value
            return value.value if isinstance(value, ast.Constant) and isinstance(value.value, bool) else None
    return None


class _V2Collector:
    """Один обход дерева: `defs`, `calls`, `test_defs` по ходу; `io` и `thread_sites` — после, по собранным местам.

    Стек областей — список `(имя, вид)`, вид `class` или `def`. Декораторы, умолчания, аннотации и основы класса
    вычисляются во внешней области и обходятся до входа в тело.
    """

    def __init__(self) -> None:
        self.defs: list[DefFact] = []
        self.calls: list[CallFact] = []
        self.test_defs: list[tuple[str, int]] = []
        self.replaces: list[IoFact] = []
        self.sites: list[ThreadSite] = []  # цепочки `Thread(...).start()`
        self.ctors: list[tuple[str, str, ast.Call, str]] = []  # (область, цель, вызов, шаблон) из присваиваний
        self.observer_attrs: set[tuple[str, str]] = set()  # (класс, `self.<a>`) с `Observer(...)`
        self.starts: set[tuple[str, str]] = set()  # (область, получатель) вызовов `.start()`
        self.schedules: list[tuple[str, str | None, str, ast.Call]] = []  # (область, класс, получатель, вызов)
        self.command_specs: list[tuple[str, int, str, str]] | None = None  # None — `def command_specs` не встречен

    @staticmethod
    def _enclosing(stack: list[tuple[str, str]]) -> str:
        return ".".join(name for name, _ in stack) or "<module>"

    @staticmethod
    def _class_of(stack: list[tuple[str, str]]) -> str | None:
        for i in range(len(stack) - 1, -1, -1):
            if stack[i][1] == "class":
                return ".".join(name for name, _ in stack[: i + 1])
        return None

    def visit(self, node: ast.AST, stack: list[tuple[str, str]]) -> None:
        if isinstance(node, _FUNC_NODES):
            self._visit_def(node, stack)
        elif isinstance(node, ast.ClassDef):
            self._visit_class(node, stack)
        else:
            if isinstance(node, ast.Call):
                self._call(node, stack)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                self._assign(node, stack)
            for child in ast.iter_child_nodes(node):
                self.visit(child, stack)

    def _visit_def(self, node: ast.FunctionDef | ast.AsyncFunctionDef, stack: list[tuple[str, str]]) -> None:
        for outer in (*node.decorator_list, node.args, node.returns):
            if outer is not None:
                self.visit(outer, stack)
        qualname = ".".join([*(name for name, _ in stack), node.name])
        signature = ast.unparse(node.args)
        if node.returns is not None:
            signature += " -> " + ast.unparse(node.returns)
        decorators = tuple(_decorator_name(d) for d in node.decorator_list)
        kind = "method" if stack and stack[-1][1] == "class" else "function"
        self.defs.append(
            DefFact(
                qualname,
                kind,
                node.lineno,
                signature,
                decorators,
                "abstractmethod" in decorators,
                isinstance(node, ast.AsyncFunctionDef),
                _first_paragraph(node),
            )
        )
        if node.name.startswith("test") and all(k == "class" and n.startswith("Test") for n, k in stack):
            self.test_defs.append((qualname, node.lineno))
        if node.name == "command_specs":
            if self.command_specs is None:
                self.command_specs = []
            self.command_specs.extend((name, line, form, qualname) for name, line, form in _command_entries(node))
        inner = [*stack, (node.name, "def")]
        for stmt in node.body:
            self.visit(stmt, inner)

    def _visit_class(self, node: ast.ClassDef, stack: list[tuple[str, str]]) -> None:
        for outer in (*node.decorator_list, *node.bases, *node.keywords):
            self.visit(outer, stack)
        qualname = ".".join([*(name for name, _ in stack), node.name])
        decorators = tuple(_decorator_name(d) for d in node.decorator_list)
        bases = tuple(ast.unparse(b) for b in node.bases)
        self.defs.append(
            DefFact(qualname, "class", node.lineno, "", decorators, False, False, _first_paragraph(node), bases)
        )
        inner = [*stack, (node.name, "class")]
        for stmt in node.body:
            self.visit(stmt, inner)

    def _call(self, node: ast.Call, stack: list[tuple[str, str]]) -> None:
        func = node.func
        if isinstance(func, ast.Name):
            name, receiver = func.id, None
        elif isinstance(func, ast.Attribute):
            name, receiver = func.attr, ast.unparse(func.value)
        else:
            return  # `f()()`, `d[k]()`: имени нет
        enclosing = self._enclosing(stack)
        self.calls.append(CallFact(name, node.lineno, enclosing, receiver))
        if receiver is None:
            return
        if name == "start":
            self.starts.add((enclosing, receiver))
            pattern = _ctor_pattern(func.value)  # type: ignore[union-attr]
            if pattern is not None:  # цепочка `Thread(...).start()`
                ctor: ast.Call = func.value  # type: ignore[union-attr,assignment]
                self.sites.append(ThreadSite(pattern, ctor.lineno, enclosing, _daemon_literal(ctor)))
        elif name == "schedule":
            self.schedules.append((enclosing, self._class_of(stack), receiver, node))
        elif (receiver, name) in _REPLACES and len(node.args) >= 2:
            self.replaces.append(IoFact("replaces", ast.unparse(node.args[1]), node.lineno, enclosing))

    def _assign(self, node: ast.Assign | ast.AnnAssign, stack: list[tuple[str, str]]) -> None:
        pattern = _ctor_pattern(node.value)
        if pattern is None:
            return
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        enclosing = self._enclosing(stack)
        cls = self._class_of(stack)
        for target in targets:
            if not isinstance(target, (ast.Name, ast.Attribute)):
                continue
            text = ast.unparse(target)
            self.ctors.append((enclosing, text, node.value, pattern))  # type: ignore[arg-type]
            if pattern == "Observer" and cls is not None and text.startswith("self."):
                self.observer_attrs.add((cls, text))

    def finish(self) -> tuple[tuple[IoFact, ...], tuple[ThreadSite, ...]]:
        observer_locals = {(enc, text) for enc, text, _, pattern in self.ctors if pattern == "Observer"}
        io = list(self.replaces)
        for enclosing, cls, receiver, call in self.schedules:
            if receiver.startswith("self."):
                known = cls is not None and (cls, receiver) in self.observer_attrs
            else:
                known = (enclosing, receiver) in observer_locals
            if not known:
                continue
            if len(call.args) >= 2:
                path: ast.expr | None = call.args[1]
            else:
                path = next((kw.value for kw in call.keywords if kw.arg == "path"), None)
            if path is not None:
                io.append(IoFact("watch", ast.unparse(path), call.lineno, enclosing))
        sites = list(self.sites)
        for enclosing, text, ctor, pattern in self.ctors:
            if (enclosing, text) in self.starts:
                sites.append(ThreadSite(pattern, ctor.lineno, enclosing, _daemon_literal(ctor)))
        io.sort(key=lambda f: f.line)
        sites.sort(key=lambda s: s.line)
        return tuple(io), tuple(sites)


def _own_returns(node: ast.AST) -> list[ast.Return]:
    """`return` тела функции без вложенных def/class/lambda, в порядке исходника."""
    found: list[ast.Return] = []
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (*_FUNC_NODES, ast.ClassDef, ast.Lambda)):
            continue
        if isinstance(child, ast.Return):
            found.append(child)
        found.extend(_own_returns(child))
    return found


def _spec_name(elt: ast.expr) -> tuple[str, str] | None:
    """`(имя, форма)` литерального элемента `command_specs`: кортеж или `CommandSpec(...)`; иначе None."""
    if isinstance(elt, ast.Tuple) and elt.elts:
        name = literal_str(elt.elts[0])
        return None if name is None else (name, "tuple")
    if isinstance(elt, ast.Call) and leaf_name(elt.func) == "CommandSpec":
        arg = elt.args[0] if elt.args else next((k.value for k in elt.keywords if k.arg == "name"), None)
        name = literal_str(arg)
        return None if name is None else (name, "call")
    return None


def _command_entries(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[tuple[str, int, str]]:
    """Элементы `def command_specs`: `(name, line, form)`; динамический элемент — `("", line, "dynamic")`."""
    out: list[tuple[str, int, str]] = []
    for ret in sorted(_own_returns(node), key=lambda r: (r.lineno, r.col_offset)):
        value = ret.value
        if value is None or (isinstance(value, ast.Constant) and value.value is None):
            continue
        if not isinstance(value, (ast.List, ast.Tuple, ast.Set)):
            out.append(("", value.lineno, "dynamic"))
            continue
        for elt in value.elts:
            hit = _spec_name(elt)
            out.append(("", elt.lineno, "dynamic") if hit is None else (hit[0], elt.lineno, hit[1]))
    return out


def _collect_v2(tree: ast.Module) -> dict[str, tuple | None]:
    """Поля v2 `FileFacts` из дерева модуля; может бросить (ловит `scan_text` в своём `try`)."""
    collector = _V2Collector()
    for stmt in tree.body:
        collector.visit(stmt, [])
    io, sites = collector.finish()
    return {
        "defs": tuple(collector.defs),
        "calls": tuple(collector.calls),
        "io": io,
        "thread_sites": sites,
        "test_defs": tuple(collector.test_defs),
        "command_specs": None if collector.command_specs is None else tuple(collector.command_specs),
    }


def scan_text(text: str) -> FileFacts:
    """Факты исходника; не бросает никогда. Зависят только от текста (R5): ни пути, ни `is_init`."""
    text = text.removeprefix("﻿")
    try:
        loc = _loc(text)
    except Exception:  # noqa: BLE001 — контракт «не бросает»
        loc = 0
    try:
        tree = ast.parse(text)
        styles: dict[str, str] = {}
        classes: list[ClassFact] = []
        functions: list[str] = []
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                classes.append(_class_fact(node, styles))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
                functions.append(node.name)
        imports = collect_imports(tree)
        commands, threads = collect_derived(tree)
        doc = ast.get_docstring(tree) or ""
        tier, contour = read_doc_headers(doc)
        a1 = FileFacts(
            loc=loc,
            doc=next((x.strip() for x in doc.splitlines() if x.strip()), None),
            all=read_all(tree),
            classes=tuple(classes),
            functions=tuple(functions),
            imports=imports,
            commands=commands,
            threads=threads,
            tier=tier,
            contour=contour,
            freeze=read_freeze(tree),
        )
    except Exception as exc:  # noqa: BLE001 — SyntaxError, ValueError, RecursionError, MemoryError, ...
        return FileFacts(loc=loc, error=type(exc).__name__)
    try:  # v2 — свой `try`: сбой разбора v2 оставляет поля A1 как есть
        return replace(a1, **_collect_v2(tree))
    except Exception as exc:  # noqa: BLE001 — RecursionError на глубоком дереве и т. п.
        return replace(a1, v2_error=type(exc).__name__)


def _facts_of_bytes(data: bytes) -> FileFacts:
    """Байты блоба -> факты: предел размера ДО декодирования, потом utf-8 строго."""
    if len(data) > MAX_BLOB_BYTES:
        return FileFacts(error="BlobTooLarge")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return FileFacts(error="UnicodeDecodeError")
    return scan_text(text)


# --------------------------------------------------------------------------- источники и scan


class Source(Protocol):
    def files(self) -> list[str]: ...

    def oids(self) -> dict[str, str]: ...

    def read_many(self, paths: Sequence[str]) -> dict[str, bytes | None]: ...


def _blob_oid(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


class DictSource:
    """Файлы в памяти; oid — sha1 блоба git, так что `oids()` совпадает с `Tree.oids()` для того же содержимого."""

    def __init__(self, files: dict[str, str | bytes]) -> None:
        self._data = {p: v.encode("utf-8") if isinstance(v, str) else bytes(v) for p, v in files.items()}
        self._oids = {p: _blob_oid(v) for p, v in self._data.items()}

    def files(self) -> list[str]:
        return list(self._data)

    def oids(self) -> dict[str, str]:
        return dict(self._oids)

    def read_many(self, paths: Sequence[str]) -> dict[str, bytes | None]:
        return {p: self._data.get(p) for p in paths}


@dataclass(frozen=True)
class ScanResult:
    facts: dict[str, FileFacts]  # только прочитанные пути, порядок как в `paths`
    missing: tuple[str, ...]  # запрошены, но не прочитаны (нет в oids: ссылка, gitlink, путь с переводом строки)
    parsed: int  # различных oid, разобранных заново
    hits: int  # различных oid из кэша


_ENV_ERRORS = frozenset({"RecursionError", "MemoryError"})  # ошибки окружения: в кэш не кладутся


def scan(source: Source, paths: Sequence[str], cache: sqlite3.Connection | None = None) -> ScanResult:
    """Факты файлов `paths`; разбор — по одному разу на oid, кэш `scan_cache` — по `(oid, SCANNER)`."""
    scanner = SCANNER  # читается при вызове: тест подменяет константу модуля
    wanted = list(dict.fromkeys(paths))
    oids = source.oids()
    missing = [p for p in wanted if "\n" in p or p not in oids]  # перенос в пути сдвинул бы ответы cat-file
    skip = set(missing)
    present = [p for p in wanted if p not in skip]

    by_oid: dict[str, FileFacts] = {}
    first_path: dict[str, str] = {}  # oid -> первый путь с этим блобом: два пути с одним oid разбираются один раз
    for p in present:
        first_path.setdefault(oids[p], p)
    cached = get_scans(cache, scanner, list(first_path)) if cache is not None and first_path else {}
    for oid, body in cached.items():
        try:
            by_oid[oid] = FileFacts.from_json(body)
        except Exception:  # noqa: BLE001 — битое тело кэша: промах, строку перезапишет put_scans
            continue
    hits = len(by_oid)

    todo = {oid: p for oid, p in first_path.items() if oid not in by_oid}
    parsed = 0
    to_cache: list[tuple[str, str]] = []
    if todo:
        blobs = source.read_many(list(todo.values()))
        for oid, path in todo.items():
            data = blobs.get(path)
            if data is None:  # файл исчез между oids() и чтением
                continue
            if len(oid) == 40 and _blob_oid(data) != oid:  # содержимое сменилось между oids() и чтением (F2)
                continue
            facts = by_oid[oid] = _facts_of_bytes(data)
            parsed += 1
            # зависят от стека/памяти, а не от блоба (R5): в кэш нельзя (F1); то же для сбоя разбора v2
            if facts.error not in _ENV_ERRORS and facts.v2_error not in _ENV_ERRORS:
                to_cache.append((oid, facts.to_json()))
    if to_cache and cache is not None:
        put_scans(cache, scanner, to_cache)

    gone = [p for p in present if oids[p] not in by_oid]
    gone_set = set(gone)
    facts_by_path = {p: by_oid[oids[p]] for p in present if p not in gone_set}
    missing += gone
    return ScanResult(facts_by_path, tuple(missing), parsed, hits)


# --------------------------------------------------------------------------- разрешение импортов


def resolve_relative(level: int, module: str | None, current: str, is_init: bool) -> str | None:
    """Абсолютное имя цели относительного импорта.

    У `__init__.py` одна точка — сам пакет, у обычного файла — его каталог.
    """
    base = current.split(".")
    drop = level - 1 if is_init else level
    if drop > len(base):
        return None
    trimmed = base[: len(base) - drop] if drop else base
    if not trimmed:
        return None
    return ".".join(trimmed + ([module] if module else []))


@dataclass(frozen=True)
class Resolved:
    status: Literal["internal", "external", "unresolved"]
    targets: tuple[tuple[str, tuple[str, ...]], ...] = ()  # ((путь-цель, имена), ...)


class ImportIndex:
    """Индекс модулей по путям `*.py`; каталог без `__init__.py` модулем не считается (D2)."""

    def __init__(self, paths: Iterable[str]) -> None:
        self._module_of: dict[str, str] = {}  # путь -> имя модуля
        self._path_of: dict[str, str] = {}  # имя модуля -> путь
        for path in paths:
            if not path.endswith(".py"):
                continue
            name = path[: -len(".py")].replace("/", ".")
            if path == "__init__.py" or path.endswith("/__init__.py"):
                name = name[: -len("__init__")].rstrip(".")
            if not name:
                continue
            self._module_of[path] = name
            known = self._path_of.get(name)
            if known is None or not self._is_init(known):  # пакет побеждает модуль при любом порядке (F4)
                self._path_of[name] = path
        self.roots: frozenset[str] = frozenset(name.split(".")[0] for name in self._module_of.values())

    @staticmethod
    def _is_init(path: str) -> bool:
        return path == "__init__.py" or path.endswith("/__init__.py")

    def resolve(self, path: str, rec: ImportRec) -> Resolved:
        if rec.level:
            current = self._module_of.get(path)
            if current is None:
                return Resolved("unresolved")
            base = resolve_relative(rec.level, rec.module, current, self._is_init(path))
        else:
            base = rec.module
            if not base or base.split(".")[0] not in self.roots:
                return Resolved("external")
        target = self._path_of.get(base) if base else None
        if target is None:
            return Resolved("unresolved")
        if not rec.is_from:
            return Resolved("internal", ((target, ()),))
        hits: dict[str, list[str]] = {}
        for name in rec.names:
            sub = self._path_of.get(f"{base}.{name}") if self._is_init(target) else None
            hits.setdefault(sub or target, []).append(name)  # `from pkg import sub` -> файл sub
        return Resolved("internal", tuple((p, tuple(names)) for p, names in hits.items()))
