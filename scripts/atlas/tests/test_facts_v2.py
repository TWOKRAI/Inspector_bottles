"""Слепые приёмочные тесты фактов v2 сканера (Task 4.1, stage 1, RED до кода).

Purpose: `scan_text` отдаёт новые поля `FileFacts` — `defs`, `calls`, `io`, `thread_sites` (кортежи dataclass'ов
    `DefFact`, `CallFact`, `IoFact`, `ThreadSite`); кэш фактов по `(oid, SCANNER)` хранит их и принимает за промах
    тело старой формы. Контракт — докстринги `scripts/atlas/scan.py`; реализации при записи тестов нет.
Public API: тесты test_*; публичных имён нет.
Stability: lite

Каждый тест — одно свойство, граничные случаи — негативными утверждениями внутри. Источники — строки кода;
номера строк берутся маркером `# @имя` в самой фикстуре (строка с маркером ищется в тексте фикстуры, а не в
ответе сканера). Ожидаемые значения (пути, имена, сигнатуры, флаги) — литералы. Диск и git не нужны:
кэш-тест — `DictSource` и sqlite во `tmp_path`.
"""

from __future__ import annotations

import json
from pathlib import Path

__all__: list[str] = []


def _line(src: str, marker: str) -> int:
    """Номер строки фикстуры с маркером `# @marker` (ровно одной)."""
    hits = [i for i, text in enumerate(src.splitlines(), 1) if text.rstrip().endswith(f"# @{marker}")]
    assert len(hits) == 1, f"маркер {marker!r}: строк {len(hits)}"
    return hits[0]


# ---------------------------------------------------------------- 1. io: watch и replaces

_IO_SRC = """\
import os
import shutil
from watchdog.observers import Observer


class Watcher:
    def __init__(self):
        self._obs = Observer()

    def start(self):
        self._obs.schedule(self._h, str(self._path.parent), recursive=False)  # @w_self_pos
        self._obs.start()

    def restart(self):
        self._obs.schedule(self._h, path=self._cfg)  # @w_self_kw

    def save(self, tmp, dst):
        os.replace(tmp, dst)  # @r_replace
        os.rename(tmp, dst + ".bak")  # @r_rename
        shutil.move(tmp, self._dir)  # @r_move


class NotAWatcher:
    def go(self):
        self._sch.schedule(self._h, "never")  # @n_self_attr


def local_watch(h):
    obs = Observer()
    obs.schedule(h, "/data/in", True)  # @w_local_pos
    obs.schedule(h, path="/data/kw")  # @w_local_kw


def fake(sch, a, b):
    sch.schedule(a, b, 1, "p")  # @n_fake
    other = make()
    other.schedule(a, b)  # @n_other_ctor


def no_path(h):
    obs = Observer()
    obs.schedule(h)  # @n_nopath


def other_scope(h):
    obs.schedule(h, "/elsewhere")  # @n_other_scope


def not_replace(p, q, s):
    p.replace(q)  # @n_path_replace
    s.replace("a", "b")  # @n_str_replace


os.rename("a.tmp", "a.txt")  # @r_module
"""


def test_io_schedule_watch_only_on_observer_and_replaces():
    """F3/P4: `watch` — только `schedule` на объекте, которому в той же функции (`self.<a>` — в том же классе)
    присвоен `Observer(...)`; путь = 2-й позиционный, иначе `path=`, иначе записи нет. `replaces` — `os.replace`,
    `os.rename`, `shutil.move`, путь = 2-й аргумент; `Path.replace` и `str.replace` — не `replaces`."""
    from scripts.atlas.scan import scan_text

    facts = scan_text(_IO_SRC)
    ln = lambda m: _line(_IO_SRC, m)  # noqa: E731
    got = sorted((f.op, f.path, f.line, f.enclosing) for f in facts.io)
    expected = sorted(
        [
            ("watch", "str(self._path.parent)", ln("w_self_pos"), "Watcher.start"),
            ("watch", "self._cfg", ln("w_self_kw"), "Watcher.restart"),
            ("replaces", "dst", ln("r_replace"), "Watcher.save"),
            ("replaces", "dst + '.bak'", ln("r_rename"), "Watcher.save"),
            ("replaces", "self._dir", ln("r_move"), "Watcher.save"),
            ("watch", "'/data/in'", ln("w_local_pos"), "local_watch"),
            ("watch", "'/data/kw'", ln("w_local_kw"), "local_watch"),
            ("replaces", "'a.txt'", ln("r_module"), "<module>"),
        ]
    )
    # точный набор: лишних записей нет (`sch.schedule(a, b, 1, "p")`, `self._sch` без Observer, `obs` из другой
    # функции, `schedule(h)` без пути, `p.replace(q)`, `s.replace("a", "b")` — не попадают)
    assert got == expected
    assert isinstance(facts.io, tuple)


# ---------------------------------------------------------------- 2. thread_sites

_THREAD_SRC = """\
import threading
from threading import Thread, Timer
from watchdog.observers import Observer


def started(f):
    t = threading.Thread(target=f, daemon=True)  # @t_started
    t.start()


def chained(f):
    Thread(target=f, daemon=True).start()  # @t_chain


def never_started(f):
    t = Thread(target=f)  # @t_never
    return t


def timer(f):
    t = Timer(1.5, f)  # @t_timer
    t.start()


def non_daemon(f):
    t = Thread(target=f, daemon=False)  # @t_false
    t.start()


def dynamic(f, flag):
    t = Thread(  # @t_dyn
        target=f,
        daemon=flag,
    )
    t.start()


def attr_daemon(f):
    t = Thread(target=f)  # @t_attr
    t.daemon = True
    t.start()


def other_target(f):
    t = Thread(target=f)  # @t_other
    u = make()
    u.start()


def build(f):
    return Thread(target=f)  # @t_build


def run(f):
    t = build(f)
    t.start()


class Svc:
    def go(self):
        self._o = Observer()  # @t_obs
        self._o.start()
"""


def test_thread_site_needs_constructor_and_start():
    """P5 (Task 4.5b): запись `ThreadSite` — у КАЖДОГО вызова конструктора из `THREAD_PATTERNS`, `.start()` не нужен;
    цепочка `Thread(...).start()` — одна запись; `line` — строка конструктора, не `.start()`; `daemon` —
    литерал `daemon=` у конструктора (True/False), иначе None."""
    from scripts.atlas import scan as scan_mod

    assert scan_mod.THREAD_PATTERNS == ("Thread", "Timer", "Observer")
    facts = scan_mod.scan_text(_THREAD_SRC)
    ln = lambda m: _line(_THREAD_SRC, m)  # noqa: E731
    got = sorted((s.pattern, s.line, s.enclosing, s.daemon) for s in facts.thread_sites)
    expected = sorted(
        [
            ("Thread", ln("t_started"), "started", True),
            ("Thread", ln("t_chain"), "chained", True),
            ("Thread", ln("t_never"), "never_started", None),  # без .start(): запись есть (Task 4.5b)
            ("Timer", ln("t_timer"), "timer", None),
            ("Thread", ln("t_false"), "non_daemon", False),
            ("Thread", ln("t_dyn"), "dynamic", None),  # конструктор на нескольких строках: строка `Thread(`
            ("Thread", ln("t_attr"), "attr_daemon", None),  # `t.daemon = True` — не литерал в конструкторе
            ("Thread", ln("t_other"), "other_target", None),  # .start() чужой цели: запись есть (Task 4.5b)
            ("Thread", ln("t_build"), "build", None),  # конструктор в `build`, .start() в `run` (Task 4.5b)
            ("Observer", ln("t_obs"), "Svc.go", None),
        ]
    )
    # нет записей: `run` (`t = build(f)` — не конструктор), `u = make()` в `other_target`
    assert got == expected
    assert isinstance(facts.thread_sites, tuple)


_SPLIT_THREAD_SRC = """\
import threading


class Worker:
    def __init__(self, f):
        self._t = threading.Thread(target=f, daemon=True)  # @ctor

    def begin(self):
        self._t.start()
"""


def test_thread_without_start_in_same_function_recorded():
    """RED Task 4.5b п. 1: `self._t = threading.Thread(...)` в `__init__`, `.start()` в другом методе -> одна запись
    у конструктора (`enclosing` — `Worker.__init__`, строка 6); запуск в `begin` записи не даёт."""
    from scripts.atlas.scan import scan_text

    assert _line(_SPLIT_THREAD_SRC, "ctor") == 6
    got = [(s.pattern, s.line, s.enclosing, s.daemon) for s in scan_text(_SPLIT_THREAD_SRC).thread_sites]
    assert got == [("Thread", 6, "Worker.__init__", True)]


# ---------------------------------------------------------------- 3. defs

_DEFS_SRC = '''\
"""Модульный докстринг."""
import abc
import functools
from abc import abstractmethod


def top(a: int, b: str = "x", *args, **kw) -> bool:  # @top
    """Краткое описание top.

    Второй абзац не входит.
    """

    def inner():  # @inner
        return 1

    return True


async def coro(x) -> None:  # @coro
    pass


@functools.lru_cache(maxsize=1)
@a.b.c
@d(x)
def deco():  # @deco
    pass


class Base(abc.ABC, Generic[T]):  # @Base
    """Класс-основа.

    Детали.
    """

    @abstractmethod
    def must(self) -> int:  # @must
        ...

    @property
    def prop(self):  # @prop
        return 1

    def __call__(self, x: int = 0):  # @call
        return x

    async def am(self, *, k=None) -> list[int]:  # @am
        ...

    class Nested:  # @Nested
        def deep(self):  # @deep
            ...


class Child(Base, metaclass=Meta):  # @Child
    pass
'''


def test_def_facts_have_qualname_line_signature_doc():
    """`defs`: каждый class/def на любой глубине; qualname через точку; `kind` class|function|method (dunder —
    тоже method, со своей `line`); `line` — строка `def`/`class`, не декоратора; сигнатура — `ast.unparse(args)` +
    ` -> <returns>`, у класса `""`; декораторы — листовые имена; `doc` — первый абзац или None; `bases` — только
    основы, без `metaclass=`. Поля A1 не меняются."""
    from scripts.atlas.scan import scan_text

    facts = scan_text(_DEFS_SRC)
    ln = lambda m: _line(_DEFS_SRC, m)  # noqa: E731
    #            qualname: (kind, line, signature, decorators, abstract, is_async, doc, bases)
    expected = {
        "top": (
            "function",
            ln("top"),
            "a: int, b: str='x', *args, **kw -> bool",
            (),
            False,
            False,
            "Краткое описание top.",
            (),
        ),
        "top.inner": ("function", ln("inner"), "", (), False, False, None, ()),
        "coro": ("function", ln("coro"), "x -> None", (), False, True, None, ()),
        "deco": ("function", ln("deco"), "", ("lru_cache", "c", "d"), False, False, None, ()),
        "Base": ("class", ln("Base"), "", (), False, False, "Класс-основа.", ("abc.ABC", "Generic[T]")),
        "Base.must": ("method", ln("must"), "self -> int", ("abstractmethod",), True, False, None, ()),
        "Base.prop": ("method", ln("prop"), "self", ("property",), False, False, None, ()),
        "Base.__call__": ("method", ln("call"), "self, x: int=0", (), False, False, None, ()),
        "Base.am": ("method", ln("am"), "self, *, k=None -> list[int]", (), False, True, None, ()),
        "Base.Nested": ("class", ln("Nested"), "", (), False, False, None, ()),
        "Base.Nested.deep": ("method", ln("deep"), "self", (), False, False, None, ()),
        "Child": ("class", ln("Child"), "", (), False, False, None, ("Base",)),
    }
    got = {
        d.qualname: (d.kind, d.line, d.signature, d.decorators, d.abstract, d.is_async, d.doc, d.bases)
        for d in facts.defs
    }
    assert isinstance(facts.defs, tuple)
    assert len(facts.defs) == len(got), "qualname не повторяются"
    assert got == expected
    # A1 не тронут: `methods` — имена без строк, dunder остаются, вложенный класс — не метод
    base = next(c for c in facts.classes if c.name == "Base")
    assert base.methods == ("must", "prop", "__call__", "am")
    assert facts.functions == ("top", "coro", "deco")
    assert facts.v2_error is None


# ---------------------------------------------------------------- 4. calls

_CALLS_SRC = """\
import os


def top():
    helper(1)  # @c_top


class C:
    attr = make()  # @c_attr

    def m(self):
        self.go()  # @c_self
        os.path.join("a")  # @c_join

        def inner():
            deep()  # @c_inner

        return inner

    class In:
        def n(self):
            p()  # @c_in


async def arun():
    await fetch()  # @c_await


outer(inner_call())  # @c_nest
a.b().c()  # @c_chain
module_level()  # @c_mod
"""


def test_call_carries_enclosing_qualname():
    """`calls`: `name` — последнее имя вызываемого, `receiver` — None у голого имени, иначе `ast.unparse(func.value)`;
    `enclosing` — qualname ближайшего def/class, на уровне модуля `<module>`, в теле класса — имя класса."""
    from scripts.atlas.scan import scan_text

    facts = scan_text(_CALLS_SRC)
    ln = lambda m: _line(_CALLS_SRC, m)  # noqa: E731
    got = sorted((c.line, c.name, c.enclosing, c.receiver) for c in facts.calls)
    expected = sorted(
        [
            (ln("c_top"), "helper", "top", None),
            (ln("c_attr"), "make", "C", None),  # тело класса: объемлющий — сам класс
            (ln("c_self"), "go", "C.m", "self"),
            (ln("c_join"), "join", "C.m", "os.path"),
            (ln("c_inner"), "deep", "C.m.inner", None),  # вложенный def: qualname через точку
            (ln("c_in"), "p", "C.In.n", None),
            (ln("c_await"), "fetch", "arun", None),
            (ln("c_nest"), "outer", "<module>", None),
            (ln("c_nest"), "inner_call", "<module>", None),
            (ln("c_chain"), "b", "<module>", "a"),
            (ln("c_chain"), "c", "<module>", "a.b()"),  # получатель — выражение, не только имя
            (ln("c_mod"), "module_level", "<module>", None),
        ]
    )
    assert got == expected
    assert isinstance(facts.calls, tuple)


# ---------------------------------------------------------------- 5. кэш: тело старой формы — промах

_CACHE_SRC = """\
import os
import threading


def test_t():
    os.replace("a", "b")


def work(f):
    t = threading.Thread(target=f, daemon=True)
    t.start()
"""

# Тело кэша формы A1 (до v2): одиннадцать старых ключей, ни одного нового.
_OLD_FORM_BODY = (
    '{"loc":1,"doc":null,"all":null,"classes":[],"functions":[],"imports":[],"commands":[],'
    '"threads":[],"tier":null,"contour":null,"error":null}'
)
_NEW_KEYS = ("defs", "calls", "io", "thread_sites", "test_defs", "v2_error")


def test_old_form_cache_body_is_miss(tmp_path: Path):
    """Тело кэша старой формы (без ключей v2) — промах: `parsed 1, hits 0`, факты v2 пересчитаны и записаны;
    следующий проход — попадание с теми же фактами (v2 переживает JSON). Тело без любого одного нового ключа — тоже
    промах (`from_json` читает ключи через `d[...]`, не `d.get`)."""
    from scripts.atlas import scan as scan_mod
    from scripts.atlas.store import connect, get_scans, put_scans

    source = scan_mod.DictSource({"m.py": _CACHE_SRC})
    oid = source.oids()["m.py"]
    con = connect(tmp_path / "cache.db")
    try:
        put_scans(con, scan_mod.SCANNER, [(oid, _OLD_FORM_BODY)])
        first = scan_mod.scan(source, ["m.py"], con)
        assert (first.parsed, first.hits) == (1, 0)
        fresh = first.facts["m.py"]
        assert [d.qualname for d in fresh.defs] == ["test_t", "work"]  # факты v2 пришли из разбора, не из старого тела
        assert [(i.op, i.path) for i in fresh.io] == [("replaces", "'b'")]
        assert [(s.pattern, s.daemon) for s in fresh.thread_sites] == [("Thread", True)]
        assert fresh.test_defs == (("test_t", 5),)

        second = scan_mod.scan(source, ["m.py"], con)
        assert (second.parsed, second.hits) == (0, 1)
        assert second.facts["m.py"] == fresh  # кортежи dataclass'ов, не списки словарей

        for key in _NEW_KEYS:
            body = json.loads(get_scans(con, scan_mod.SCANNER, [oid])[oid])
            assert key in body, f"to_json не пишет ключ {key!r}"
            del body[key]
            put_scans(con, scan_mod.SCANNER, [(oid, json.dumps(body))])
            redo = scan_mod.scan(source, ["m.py"], con)
            assert (redo.parsed, redo.hits) == (1, 0), f"тело без {key!r} принято как попадание"
            assert redo.facts["m.py"] == fresh
    finally:
        con.close()


_SAME_LINE_SRC = """\
from threading import Thread, Timer


def pair(f):
    a, b = Thread(target=f), Timer(1.0, f)  # @pair
    return a, b


def other(f):
    return Thread(target=f, daemon=False)  # @other
"""


def test_thread_sites_dedup_by_enclosing_and_line():
    """Task 4.5b п. 1: два конструктора в одной строке одной функции -> одна запись (первая в порядке обхода);
    в другой функции — своя запись."""
    from scripts.atlas.scan import scan_text

    got = sorted((s.pattern, s.line, s.enclosing, s.daemon) for s in scan_text(_SAME_LINE_SRC).thread_sites)
    assert got == [("Thread", 5, "pair", None), ("Thread", 10, "other", False)]
