"""Слепые приёмочные тесты Task 4.5a: затенение, двусмысленный импорт, реэкспорт через фасад (`scripts/atlas/links.py`).

Purpose: проверяют НАБЛЮДАЕМЫЙ эффект `Links.of(...)` (`call_sites`, `call_sites_unresolved`, `subclasses`, `bases`,
    `used_by`), а не внутренние функции. Пункты поведения: A затенение (параметр, вложенный def/class), B параметр,
    совпавший с именем модуля, C двусмысленный импорт, D реэкспорт через `__init__` (прямой вызов, подкласс, ленивый
    фасад PEP 562, лимит звеньев, цикл), E нечитаемая сигнатура (`"("`), F «не меняется».
Public API: тесты test_*; публичных имён нет.
Stability: lite

Факты строятся `scan_text(исходник)` по фикстурам-строкам (как в test_links.py); пункт E собирает `FileFacts` вручную.
Номера строк берутся маркером `# @имя` в тексте фикстуры (не из кода под тестом); остальное — литералы. Построение
и опрос индекса идут в daemon-потоке с дедлайном (цикл реэкспортов не должен вешать прогон). Тесты пункта F —
регрессионные («не меняется»): на текущем дереве они зелёные по замыслу; тесты A-E на текущем дереве красные.
"""

from __future__ import annotations

import pytest

from scripts.atlas.tests.conftest import run_with_deadline

__all__: list[str] = []

DEADLINE_S = 30.0

# Виды параметров: позиционный, с умолчанием, keyword-only, *args, **kwargs, posonly (до и после `/`), с аннотацией.
_SIGNATURES = [
    "name",
    "a, name",
    "a, name=2",
    "*, name",
    "*name",
    "**name",
    "name, /",
    "a, /, name",
    "name: int",
]


def _links(files: dict[str, str]):
    from scripts.atlas.links import build_links
    from scripts.atlas.scan import scan_text

    return run_with_deadline(lambda: build_links({p: scan_text(s) for p, s in files.items()}), DEADLINE_S)


def _of(links, ident: str) -> dict:
    res = run_with_deadline(lambda: links.of(ident), DEADLINE_S)
    assert res is not None, f"нет записи для {ident}"
    return res


def _at(files: dict[str, str], path: str, marker: str) -> str:
    """`путь:строка` места с маркером `# @marker` в фикстуре `path` (ровно одно)."""
    hits = [i for i, text in enumerate(files[path].splitlines(), 1) if text.rstrip().endswith(f"# @{marker}")]
    assert len(hits) == 1, f"маркер {marker!r} в {path}: строк {len(hits)}"
    return f"{path}:{hits[0]}"


def _site(where: str, enclosing: str, same_file: bool) -> dict:
    return {"where": where, "how": "name-call", "scope": "prod", "enclosing": enclosing, "same_file": same_file}


# ================================================================ A. затенение

_A_SAME_FILE = """\
def name():
    pass


def run({sig}):
    name()  # @shadowed


def other():
    name()  # @ok
"""

_A_LIB = """\
def name():
    pass
"""

_A_FROM_IMPORT = """\
from lib import name


def run({sig}):
    name()  # @shadowed


def other():
    name()  # @ok
"""


@pytest.mark.parametrize("sig", _SIGNATURES)
def test_a_param_shadows_same_file_function(sig):
    """A: `name()` в функции с параметром `name` не относится к функции `name` того же файла."""
    files = {"mod.py": _A_SAME_FILE.format(sig=sig)}
    res = _of(_links(files), "mod.py::name")
    assert res["call_sites"] == [_site(_at(files, "mod.py", "ok"), "other", True)]
    assert res["call_sites_unresolved"] == 1


@pytest.mark.parametrize("sig", _SIGNATURES)
def test_a_param_shadows_from_imported_function(sig):
    """A: то же для `name`, импортированной из внутреннего модуля: вызов при параметре `name` не отнесён."""
    files = {"lib.py": _A_LIB, "use.py": _A_FROM_IMPORT.format(sig=sig)}
    res = _of(_links(files), "lib.py::name")
    assert res["call_sites"] == [_site(_at(files, "use.py", "ok"), "other", False)]
    assert res["call_sites_unresolved"] == 1


def test_a_param_of_method_shadows_function():
    """A: параметр метода (не `self`) тоже затеняет: `class Svc: def run(self, name): name()`."""
    files = {
        "mod.py": """\
def name():
    pass


class Svc:
    def run(self, name):
        name()  # @shadowed

    def other(self):
        name()  # @ok
"""
    }
    res = _of(_links(files), "mod.py::name")
    assert res["call_sites"] == [_site(_at(files, "mod.py", "ok"), "Svc.other", True)]
    assert res["call_sites_unresolved"] == 1


def test_a_param_of_async_function_shadows():
    """A: `async def run(name)` затеняет так же, как `def`."""
    files = {
        "mod.py": """\
def name():
    pass


async def run(name):
    name()  # @shadowed


def other():
    name()  # @ok
"""
    }
    res = _of(_links(files), "mod.py::name")
    assert res["call_sites"] == [_site(_at(files, "mod.py", "ok"), "other", True)]
    assert res["call_sites_unresolved"] == 1


def test_a_nested_def_shadows_same_file_function():
    """A: вложенный `def name` внутри `run` затеняет верхнеуровневую `name` для вызова в `run`."""
    files = {
        "mod.py": """\
def name():
    pass


def run():
    def name():
        pass

    name()  # @shadowed


def other():
    name()  # @ok
"""
    }
    res = _of(_links(files), "mod.py::name")
    assert res["call_sites"] == [_site(_at(files, "mod.py", "ok"), "other", True)]
    assert res["call_sites_unresolved"] == 1


def test_a_nested_def_shadows_from_imported_function():
    """A: вложенный `def name` затеняет и from-импортированную `name`."""
    files = {
        "lib.py": _A_LIB,
        "use.py": """\
from lib import name


def run():
    def name():
        pass

    name()  # @shadowed


def other():
    name()  # @ok
""",
    }
    res = _of(_links(files), "lib.py::name")
    assert res["call_sites"] == [_site(_at(files, "use.py", "ok"), "other", False)]
    assert res["call_sites_unresolved"] == 1


def test_a_nested_class_shadows_function():
    """A: вложенный `class name` в функции затеняет одноимённую верхнеуровневую функцию."""
    files = {
        "mod.py": """\
def name():
    pass


def run():
    class name:
        pass

    name()  # @shadowed


def other():
    name()  # @ok
"""
    }
    res = _of(_links(files), "mod.py::name")
    assert res["call_sites"] == [_site(_at(files, "mod.py", "ok"), "other", True)]
    assert res["call_sites_unresolved"] == 1


def test_a_nested_def_inside_method_shadows():
    """A: вложенный `def name` внутри метода затеняет для вызова в этом методе."""
    files = {
        "mod.py": """\
def name():
    pass


class Svc:
    def run(self):
        def name():
            pass

        name()  # @shadowed

    def other(self):
        name()  # @ok
"""
    }
    res = _of(_links(files), "mod.py::name")
    assert res["call_sites"] == [_site(_at(files, "mod.py", "ok"), "Svc.other", True)]
    assert res["call_sites_unresolved"] == 1


def test_a_outer_nested_def_shadows_call_in_deeper_function():
    """A: вызов в `run.inner` затенён `def name`, объявленным в охватывающей `run` (цепочка охватывающих функций)."""
    files = {
        "mod.py": """\
def name():
    pass


def run():
    def name():
        pass

    def inner():
        name()  # @shadowed

    return inner


def other():
    name()  # @ok
"""
    }
    res = _of(_links(files), "mod.py::name")
    assert res["call_sites"] == [_site(_at(files, "mod.py", "ok"), "other", True)]
    assert res["call_sites_unresolved"] == 1


def test_a_class_method_does_not_shadow_bare_call():
    """A-граница: метод охватывающего класса `Svc.name` голый вызов `name()` не затеняет (он зовётся через self)."""
    files = {
        "mod.py": """\
def name():
    pass


class Svc:
    def name(self):
        pass

    def run(self):
        name()  # @bare
"""
    }
    res = _of(_links(files), "mod.py::name")
    assert res["call_sites"] == [_site(_at(files, "mod.py", "bare"), "Svc.run", True)]
    assert res["call_sites_unresolved"] == 0


def test_a_sibling_nested_def_does_not_shadow():
    """A-граница: `def name`, вложенный в `a`, не затеняет вызов `name()` в соседней `b` (не в цепочке охватывающих)."""
    files = {
        "mod.py": """\
def name():
    pass


def a():
    def name():
        pass

    return name


def b():
    name()  # @bare
"""
    }
    res = _of(_links(files), "mod.py::name")
    assert res["call_sites"] == [_site(_at(files, "mod.py", "bare"), "b", True)]
    assert res["call_sites_unresolved"] == 0


# ================================================================ B. параметр, совпавший с именем модуля

_B_LIB = """\
def func():
    pass
"""


def test_b_param_named_like_imported_module_not_attributed():
    """B: `lib.func()` в функции с параметром `lib` не относится к `lib.func` по `import lib`."""
    files = {
        "lib.py": _B_LIB,
        "use.py": """\
import lib


def run(lib):
    lib.func()  # @shadowed


def other():
    lib.func()  # @ok
""",
    }
    res = _of(_links(files), "lib.py::func")
    assert [c["where"] for c in res["call_sites"]] == [_at(files, "use.py", "ok")]


def test_b_param_named_like_imported_module_counted_unresolved():
    """B (вывод из «x.m() по произвольному получателю считается»): затенённый `lib.func()` растит unresolved на 1."""
    files = {
        "lib.py": _B_LIB,
        "use.py": """\
import lib


def run(lib):
    lib.func()  # @shadowed


def other():
    lib.func()  # @ok
""",
    }
    res = _of(_links(files), "lib.py::func")
    assert res["call_sites_unresolved"] == 1


def test_b_param_named_like_from_imported_submodule_not_attributed():
    """B: `from pkg import mod` + параметр `mod`: `mod.func()` в этой функции не относится к `pkg/mod.py::func`."""
    files = {
        "pkg/__init__.py": "",
        "pkg/mod.py": _B_LIB,
        "use.py": """\
from pkg import mod


def run(mod):
    mod.func()  # @shadowed


def other():
    mod.func()  # @ok
""",
    }
    res = _of(_links(files), "pkg/mod.py::func")
    assert [c["where"] for c in res["call_sites"]] == [_at(files, "use.py", "ok")]


def test_b_param_named_like_import_alias_not_attributed():
    """B: `import lib as alias` + параметр `alias`: `alias.func()` не приписывается `lib.py::func`."""
    files = {
        "lib.py": _B_LIB,
        "use.py": """\
import lib as alias


def run(alias):
    alias.func()  # @shadowed
""",
    }
    res = _of(_links(files), "lib.py::func")
    assert res["call_sites"] == []
    assert res["call_sites_unresolved"] == 1


# ================================================================ C. двусмысленный импорт

_C_A = """\
def X():
    pass
"""

_C_USE_AB = """\
from a import X
from b import X


def run():
    X()  # @in_run


X()  # @at_module
"""

_C_USE_BA = """\
from b import X
from a import X


def run():
    X()  # @in_run


X()  # @at_module
"""


@pytest.mark.parametrize("use_src", [_C_USE_AB, _C_USE_BA], ids=["a-then-b", "b-then-a"])
@pytest.mark.parametrize("target", ["a.py::X", "b.py::X"])
def test_c_same_name_from_two_defining_files_not_attributed(target, use_src):
    """C: `X` импортирован из двух разных файлов, оба определяют `X`: два голых вызова не отнесены никому."""
    files = {"a.py": _C_A, "b.py": _C_A, "use.py": use_src}
    res = _of(_links(files), target)
    assert res["call_sites"] == []
    assert res["call_sites_unresolved"] == 2


_FACADE = {
    "pkg/__init__.py": "from .core import X\n",
    "pkg/core.py": "def X():\n    pass\n",
}


@pytest.mark.parametrize(
    "imports",
    ["from pkg import X\nfrom pkg.core import X\n", "from pkg.core import X\nfrom pkg import X\n"],
    ids=["facade-first", "core-first"],
)
def test_c_facade_and_core_to_one_definition_not_ambiguous(imports):
    """C: `from pkg import X` вместе с `from pkg.core import X` ведут к ОДНОМУ определению: вызов отнесён."""
    files = {**_FACADE, "use.py": imports + "\n\ndef run():\n    X()  # @call\n"}
    res = _of(_links(files), "pkg/core.py::X")
    assert res["call_sites"] == [_site(_at(files, "use.py", "call"), "run", False)]
    assert res["call_sites_unresolved"] == 0


def test_c_same_import_twice_from_one_file_not_ambiguous():
    """C: `from a import X` дважды (второй раз лениво) — один файл, одно определение: вызов отнесён."""
    files = {
        "a.py": _C_A,
        "use.py": """\
from a import X


def run():
    from a import X

    X()  # @call
""",
    }
    res = _of(_links(files), "a.py::X")
    assert res["call_sites"] == [_site(_at(files, "use.py", "call"), "run", False)]
    assert res["call_sites_unresolved"] == 0


# ================================================================ D. реэкспорт через фасад


@pytest.mark.parametrize(
    "facade_import", ["from .core import X", "from pkg.core import X"], ids=["relative", "absolute"]
)
def test_d_call_through_facade_attributed_to_core_definition(facade_import):
    """D: `from pkg import X; X()`, где `pkg/__init__.py` реэкспортирует `X` из `pkg/core.py`: вызов — в `call_sites`
    определения в `pkg/core.py`."""
    files = {
        "pkg/__init__.py": facade_import + "\n",
        "pkg/core.py": "def X():\n    pass\n",
        "use.py": "from pkg import X\n\n\ndef run():\n    X()  # @call\n",
    }
    res = _of(_links(files), "pkg/core.py::X")
    assert res["call_sites"] == [_site(_at(files, "use.py", "call"), "run", False)]
    assert res["call_sites_unresolved"] == 0


def test_d_subclass_through_facade_listed_in_subclasses():
    """D: `from pkg import Base; class Sub(Base)` — `Sub` в `subclasses` `Base` из `pkg/core.py`."""
    files = {
        "pkg/__init__.py": "from .core import Base\n",
        "pkg/core.py": "class Base:  # @base\n    pass\n",
        "use.py": "from pkg import Base\n\n\nclass Sub(Base):  # @sub\n    pass\n",
    }
    res = _of(_links(files), "pkg/core.py::Base")
    assert res["subclasses"] == [
        {"where": _at(files, "use.py", "sub"), "how": "import", "scope": "prod", "enclosing": "Sub"}
    ]


def test_d_subclass_through_facade_bases_where_points_to_core_class():
    """D: у `bases[]` подкласса `where` указывает на `pkg/core.py:<строка class Base>` (раньше было null)."""
    files = {
        "pkg/__init__.py": "from .core import Base\n",
        "pkg/core.py": "class Base:  # @base\n    pass\n",
        "use.py": "from pkg import Base\n\n\nclass Sub(Base):  # @sub\n    pass\n",
    }
    res = _of(_links(files), "use.py::Sub")
    assert res["bases"] == [
        {"name": "Base", "where": _at(files, "pkg/core.py", "base"), "how": "import", "scope": "prod"}
    ]


def test_d_lazy_facade_getattr_resolves_to_core_definition():
    """D (PEP 562): `__getattr__` в `pkg/__init__.py` лениво импортирует `X` из `.core`: вызов — в `call_sites` core."""
    files = {
        "pkg/__init__.py": (
            "def __getattr__(name):\n"
            '    if name == "X":\n'
            "        from .core import X\n"
            "\n"
            "        return X\n"
            "    raise AttributeError(name)\n"
        ),
        "pkg/core.py": "def X():\n    pass\n",
        "use.py": "from pkg import X\n\n\ndef run():\n    X()  # @call\n",
    }
    res = _of(_links(files), "pkg/core.py::X")
    assert res["call_sites"] == [_site(_at(files, "use.py", "call"), "run", False)]
    assert res["call_sites_unresolved"] == 0


def _chain(n: int) -> dict[str, str]:
    """`n` пакетов-звеньев: a1/__init__ -> a2/__init__ -> ... -> an/__init__ -> an/core.py (определение `X`)."""
    files = {f"a{i}/__init__.py": f"from a{i + 1} import X\n" for i in range(1, n)}
    files[f"a{n}/__init__.py"] = "from .core import X\n"
    files[f"a{n}/core.py"] = "def X():\n    pass\n"
    files["use.py"] = "from a1 import X\n\n\ndef run():\n    X()  # @call\n"
    return files


@pytest.mark.parametrize("n", [2, 5])
def test_d_reexport_chain_within_limit_resolved(n):
    """D: цепочка из `n` (2 и 5) звеньев `__init__` разрешается: адрес вызова в `call_sites` определения."""
    files = _chain(n)
    res = _of(_links(files), f"a{n}/core.py::X")
    assert res["call_sites"] == [_site(_at(files, "use.py", "call"), "run", False)]
    assert res["call_sites_unresolved"] == 0


def test_d_reexport_chain_of_six_not_resolved():
    """D: при 6 звеньях адреса нет: вызов не в `call_sites`, а неотнесённый (`call_sites_unresolved` == 1)."""
    files = _chain(6)
    res = _of(_links(files), "a6/core.py::X")
    assert res["call_sites"] == []
    assert res["call_sites_unresolved"] == 1


def test_d_reexport_cycle_does_not_hang_and_stays_unresolved():
    """D: `a/__init__` реэкспортирует из `b`, `b/__init__` из `a`, определения нет: разбор не зацикливается,
    вызов неотнесён (`call_sites == []`, `call_sites_unresolved == 1`). Опрос — по одноимённой функции-приманке."""
    files = {
        "a/__init__.py": "from b import X\n",
        "b/__init__.py": "from a import X\n",
        "other.py": "def X():\n    pass\n",
        "use.py": "from a import X\n\n\ndef run():\n    X()  # @call\n",
    }
    res = _of(_links(files), "other.py::X")  # _links/_of идут в daemon-потоке с дедлайном: зависание = падение
    assert res["call_sites"] == []
    assert res["call_sites_unresolved"] == 1


# ================================================================ E. нечитаемая сигнатура


def _facts_e(signature: str, local_def: bool):
    """Факты вручную: `lib.py::name`; `use.py` с `run(signature)` и `other`, оба зовут `name()`."""
    from scripts.atlas.scan import CallFact, DefFact, FileFacts, ImportRec

    lib = FileFacts(defs=(DefFact("name", "function", 1),))
    run = DefFact("run", "function", 4, signature=signature)
    other = DefFact("other", "function", 8)
    calls = (CallFact("name", 5, "run"), CallFact("name", 9, "other"))
    if local_def:
        use = FileFacts(defs=(DefFact("name", "function", 1), run, other), calls=calls)
        return {"use.py": use}
    imp = ImportRec(kind="hard", line=1, level=0, module="lib", names=("name",), is_from=True, guarded=False)
    return {"lib.py": lib, "use.py": FileFacts(imports=(imp,), defs=(run, other), calls=calls)}


def _links_facts(facts):
    from scripts.atlas.links import build_links

    return run_with_deadline(lambda: build_links(facts), DEADLINE_S)


def test_e_unparsable_signature_shadows_all_bare_calls_from_import():
    """E: у `run` signature == "(" -> голые вызовы в `run` затенены: `lib.py::name` получает только вызов из `other`."""
    res = _of(_links_facts(_facts_e("(", local_def=False)), "lib.py::name")
    assert res["call_sites"] == [_site("use.py:9", "other", False)]
    assert res["call_sites_unresolved"] == 1


def test_e_unparsable_signature_shadows_all_bare_calls_same_file():
    """E: то же для функции из своего файла: вызов в `run` с signature == "(" не отнесён."""
    res = _of(_links_facts(_facts_e("(", local_def=True)), "use.py::name")
    assert res["call_sites"] == [_site("use.py:9", "other", True)]
    assert res["call_sites_unresolved"] == 1


def test_e_control_empty_signature_resolves_both_calls():
    """E-контроль: signature == "" (функция без параметров) не затеняет: оба вызова отнесены."""
    res = _of(_links_facts(_facts_e("", local_def=False)), "lib.py::name")
    assert res["call_sites"] == [_site("use.py:5", "run", False), _site("use.py:9", "other", False)]
    assert res["call_sites_unresolved"] == 0


# ================================================================ F. не меняется (регрессия, зелёные на текущем дереве)


def test_f_used_by_stays_at_init_import_record():
    """F: `used_by` определения в core — запись импорта в `pkg/__init__.py`; импортёр фасада `use.py` не добавляется."""
    files = {
        "pkg/__init__.py": "from .core import X  # @reexport\n",
        "pkg/core.py": "def X():\n    pass\n",
        "use.py": "from pkg import X\n\n\ndef run():\n    X()\n",
    }
    res = _of(_links(files), "pkg/core.py::X")
    assert res["used_by"] == [
        {"where": _at(files, "pkg/__init__.py", "reexport"), "how": "import", "scope": "prod", "enclosing": "<module>"}
    ]


def test_f_receiver_call_not_touched_by_param_shadowing():
    """F: `obj.name()` с получателем в функции с параметром `name`: как раньше unresolved +1, не в call_sites."""
    files = {
        "mod.py": """\
def name():
    pass


def run(name, obj):
    obj.name()  # @recv
"""
    }
    res = _of(_links(files), "mod.py::name")
    assert res["call_sites"] == []
    assert res["call_sites_unresolved"] == 1


def test_f_self_method_call_not_touched_by_param_named_like_method():
    """F: `self.helper()` в методе с параметром `helper` — по-прежнему вызов `Svc.helper` (получатель, не голое имя)."""
    files = {
        "mod.py": """\
class Svc:
    def helper(self):
        pass

    def run(self, helper):
        self.helper()  # @selfcall
"""
    }
    res = _of(_links(files), "mod.py::Svc.helper")
    assert res["call_sites"] == [_site(_at(files, "mod.py", "selfcall"), "Svc.run", True)]


def test_f_plain_calls_without_shadowing_attributed_as_before():
    """F: голый вызов в своём файле, по from-импорту и `m.f()` по импорту модуля — отнесены, как раньше."""
    files = {
        "lib.py": "def name():\n    pass\n\n\ndef func():\n    pass\n",
        "mod.py": (
            "from lib import name\nimport lib\n\n\ndef run(x):\n    name()  # @bare\n    lib.func()  # @modcall\n"
        ),
    }
    links = _links(files)
    assert _of(links, "lib.py::name")["call_sites"] == [_site(_at(files, "mod.py", "bare"), "run", False)]
    assert _of(links, "lib.py::func")["call_sites"] == [_site(_at(files, "mod.py", "modcall"), "run", False)]
