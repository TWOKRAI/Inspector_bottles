"""Слепые приёмочные тесты паспорта символа `scripts/atlas/passport.py` (Task 4.2a, stage 2, RED до кода).

Purpose: восемь сценариев REDS 1-8: постоянные ключи шести разделов, `null` против `[]`/`0`, текстовые образцы, срез по
    бюджету и рангу, раздельные счёты продукт/тесты, цепочка `interface.all`, «зовут из», объявленные команды.
    Контракт — модульный докстринг и докстринги четырёх функций `scripts/atlas/passport.py`; реализации при записи
    тестов нет (тела — `NotImplementedError`).
Public API: тесты test_*; публичных имён нет.
Stability: lite

Фикстуры — мини-репозитории git во `tmp_path` (фикстура `repo` из conftest), символы и адреса `путь:строка` берутся
маркером `# @имя` в конце строки фикстуры. Ожидаемые значения — литералы, не выводятся из кода под тестом. Вызовы идут
в daemon-потоке с дедлайном. Расположение образцов внутри раздела `links` тестами не утверждается.
"""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from scripts.atlas.tests.conftest import GitRepo, run_with_deadline
from scripts.atlas.tests.test_links import _at, _pad
from scripts.atlas.tests.test_modules_roots_4_4 import _yaml

__all__: list[str] = []

DEADLINE_S = 120.0
SECTIONS = ["purpose", "interface", "links", "runtime", "checks", "status"]
ENVELOPE = ["passport", "kind", "id", "path", "line", "sha", "scanner"]
SECTION_KEYS = {
    "purpose": {"text", "called_from", "called_from_more", "declared_at"},
    "interface": {"layer", "all", "signature", "members"},
    "links": {
        "used_by",
        "uses",
        "subclasses",
        "call_sites",
        "call_sites_unresolved",
        "bases",
        "structural",
        "call_sites_by_name",  # Task 4.5b
    },
    "runtime": {"processes", "threads", "commands", "io"},
    "checks": {"findings", "tests"},
    "status": {"tier", "doc_missing", "dynamic", "stale", "frozen"},
}
TOO_GENERIC = "слишком общий протокол: меньше двух обязательных методов"
_WHERE = re.compile(r"^[^:\s]+:\d+$")


# ---------------------------------------------------------------- помощники


def _commit(repo: GitRepo, files: dict[str, str]) -> str:
    for rel, text in files.items():
        repo.write(rel, text)
    return repo.commit("fixture")


def _build(repo: GitRepo, ident: str, ref: str = "HEAD", **kwargs: Any) -> dict:
    from scripts.atlas.passport import build_passport

    return run_with_deadline(lambda: build_passport(repo.path, ref, ident, **kwargs), DEADLINE_S)


def _render(passport: dict, **kwargs: Any) -> str:
    from scripts.atlas.passport import render_text

    return run_with_deadline(lambda: render_text(passport, **kwargs), DEADLINE_S)


def _lines(text: str) -> list[str]:
    return [line.rstrip() for line in text.splitlines()]


def _walk(node: Any, label: str = "") -> Iterator[tuple[str, Any]]:
    yield label, node
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _walk(value, f"{label}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk(value, f"{label}[{index}]")


def _is_int(value: Any) -> bool:
    return type(value) is int


# ---------------------------------------------------------------- 1. шесть разделов, ключи постоянны

_T1 = {
    "pkg/__init__.py": "",
    "pkg/mod.py": _pad(
        '''\
"""Модуль обработчиков.

Tier: core
"""
from typing import Any


class Handler:  # @cls
    """Обработчик ключей.

    Второй абзац в purpose не входит.
    """

    def __call__(self, key: str, old_value: Any, new_value: Any) -> None:  # @call
        """Вызов."""

    def run(self, x: int, n: int = 3) -> str:  # @run
        """Запуск."""
        return str(x)

    def _hidden(self) -> None:  # @hidden
        return None

    @property
    def size(self) -> int:  # @size
        return 1


def helper(a: int, b: str) -> bool:  # @helper
    return True
'''
    ),
    "pkg/other.py": _pad(
        """\
from pkg.mod import Handler, helper  # @imp


def go(obj):
    obj.helper(1)
    helper(1, "x")  # @call
"""
    ),
}


def _check_constant_shape(p: dict, kind: str, ident: str, sha: str) -> None:
    assert set(p) == set(ENVELOPE) | set(SECTIONS), sorted(p)
    assert [k for k in p if k in SECTIONS] == SECTIONS  # порядок разделов верхнего уровня
    assert p["passport"] == 1 and _is_int(p["passport"])
    assert p["kind"] == kind
    assert p["id"] == ident
    assert p["path"] == ident.split("::")[0]
    assert _is_int(p["line"])
    assert p["sha"] == sha and len(sha) == 40  # полный sha, не имя ветки, которым вызвали
    assert re.fullmatch(r"1-[0-9a-f]{12}", p["scanner"]), p["scanner"]
    for section, keys in SECTION_KEYS.items():
        assert set(p[section]) == keys, (section, sorted(p[section]))
    json.dumps(p)  # без default=
    for label, node in _walk({s: p[s] for s in SECTIONS}):
        if isinstance(node, dict):
            assert "line" not in node, f"{label}: line отдельно от пути в разделах не пишется"
            if "where" in node:
                assert node["where"] is None or _WHERE.fullmatch(node["where"]), (label, node["where"])
    # правило пустого, всегда-null ключи
    assert p["purpose"]["declared_at"] is None
    assert p["links"]["uses"] is None
    assert p["runtime"]["processes"] is None
    assert p["checks"]["findings"] is None  # node реестра не путь::qualname
    assert p["status"]["stale"] == [] and p["status"]["frozen"] == []
    assert p["interface"]["layer"] == "other"  # строка, не null; modules.yaml в ревизии нет
    assert p["interface"]["all"] is None  # литерального __all__ нет


def test_six_sections_constant_keys_class_function_method(repo: GitRepo) -> None:
    """Класс, функция, метод: конверт и шесть разделов с одним набором ключей; что не про вид — `null`;
    `where` члена и связи — одна строка `путь:строка`; `line` отдельно в разделах нет; `status.dynamic` есть."""
    sha = _commit(repo, _T1)
    at = lambda path, marker: _at(_T1, path, marker)  # noqa: E731
    imp = {"where": at("pkg/other.py", "imp"), "how": "import", "scope": "prod", "enclosing": "<module>"}

    cls = _build(repo, "pkg/mod.py::Handler", ref="main")  # имя ветки: sha в конверте всё равно полный
    _check_constant_shape(cls, "class", "pkg/mod.py::Handler", sha)
    assert cls["line"] == int(at("pkg/mod.py", "cls").rsplit(":", 1)[1])
    assert cls["purpose"]["text"] == "Обработчик ключей."  # первый абзац
    assert cls["status"]["doc_missing"] is False and cls["status"]["tier"] == "core"
    assert cls["interface"]["signature"] == ""
    members = cls["interface"]["members"]
    assert [m["name"] for m in members] == ["__call__", "run", "size"]  # порядок исходника; _hidden не входит
    assert members[0] == {
        "name": "__call__",
        "signature": "(key: str, old_value: Any, new_value: Any) -> None",
        "where": at("pkg/mod.py", "call"),
    }
    assert members[1] == {"name": "run", "signature": "(x: int, n: int = 3) -> str", "where": at("pkg/mod.py", "run")}
    assert members[2]["where"] == at("pkg/mod.py", "size") and members[2]["signature"].strip() == "-> int"
    assert cls["links"]["used_by"] == [imp]
    assert cls["links"]["subclasses"] == [] and cls["links"]["bases"] == []
    assert set(cls["links"]["structural"]) == {"required", "twins", "note"}  # у класса — dict
    assert cls["links"]["call_sites_unresolved"] == 0 and cls["status"]["dynamic"] == 0

    fn = _build(repo, "pkg/mod.py::helper")
    _check_constant_shape(fn, "function", "pkg/mod.py::helper", sha)
    assert fn["purpose"]["text"] == "" and fn["status"]["doc_missing"] is True  # докстринга нет
    assert fn["interface"]["signature"] == "(a: int, b: str) -> bool"
    assert fn["interface"]["members"] is None
    assert fn["links"]["bases"] is None and fn["links"]["structural"] is None
    assert fn["links"]["used_by"] == [imp]
    # ключи записи — по контракту; лишний ключ (например, `rank` для среза) дизайном не запрещён и не утверждается
    documented = ("where", "how", "scope", "enclosing", "same_file")
    assert [{k: e[k] for k in documented} for e in fn["links"]["call_sites"]] == [
        {
            "where": at("pkg/other.py", "call"),
            "how": "name-call",
            "scope": "prod",
            "enclosing": "go",
            "same_file": False,
        }
    ]
    assert fn["links"]["call_sites_unresolved"] == 1  # obj.helper(1) — не отнесён
    assert fn["status"]["dynamic"] == 1  # call_sites_unresolved + 0 динамических command_specs

    method = _build(repo, "pkg/mod.py::Handler.run")
    _check_constant_shape(method, "method", "pkg/mod.py::Handler.run", sha)
    assert method["interface"]["signature"] == "(x: int, n: int = 3) -> str"  # без self
    assert method["interface"]["members"] is None
    assert method["links"]["bases"] is None and method["links"]["structural"] is None
    assert method["purpose"]["text"] == "Запуск."

    plain = _build(repo, "pkg/other.py::go")
    assert plain["status"]["tier"] is None  # шапки `Tier:` нет
    assert _build(repo, "pkg/mod.py::Handler", ref="main") == cls  # детерминирован


# ---------------------------------------------------------------- 2. не искали = null, искали и нет = []/0

_T2 = {
    "pkg/__init__.py": "",
    "pkg/lonely.py": _pad(
        '''\
from typing import Protocol


class Lonely:
    """Одинокий класс."""


def lonely_fn():
    """Одинокая функция."""
    return 1


class Tiny(Protocol):
    def only(self) -> None: ...


class Declared:
    def command_specs(self):
        return []
'''
    ),
}


def test_unsearched_is_null_searched_empty_is_zero(repo: GitRepo) -> None:
    """Связей, пусков, тестов нет -> `[]`/`0` (искали, не нашли); источника нет -> `null`; нет `def command_specs` ->
    `runtime.commands: null`, объявлен без литералов -> `[]`."""
    _commit(repo, _T2)

    fn = _build(repo, "pkg/lonely.py::lonely_fn")
    links = fn["links"]
    assert links["used_by"] == [] and links["subclasses"] == [] and links["call_sites"] == []
    assert links["call_sites_unresolved"] == 0 and _is_int(links["call_sites_unresolved"])
    assert links["uses"] is None  # null, не [] и не 0
    assert links["bases"] is None and links["structural"] is None  # не про вид: null
    assert fn["purpose"]["called_from"] == [] and fn["purpose"]["called_from_more"] == 0
    assert _is_int(fn["purpose"]["called_from_more"]) and fn["purpose"]["declared_at"] is None
    assert fn["runtime"]["threads"] == [] and fn["runtime"]["io"] == []
    assert fn["runtime"]["commands"] is None  # нет def command_specs: не искали значения
    assert fn["runtime"]["processes"] is None
    assert fn["checks"]["tests"] == [] and fn["checks"]["findings"] is None
    assert fn["status"]["dynamic"] == 0 and _is_int(fn["status"]["dynamic"])
    assert fn["status"]["doc_missing"] is False and fn["interface"]["members"] is None

    cls = _build(repo, "pkg/lonely.py::Lonely")
    assert cls["interface"]["members"] == []  # членов нет: искали
    assert cls["links"]["bases"] == [] and cls["links"]["subclasses"] == []
    assert cls["runtime"]["commands"] is None

    tiny = _build(repo, "pkg/lonely.py::Tiny")
    assert tiny["links"]["structural"] == {"required": [], "twins": [], "note": TOO_GENERIC}

    declared = _build(repo, "pkg/lonely.py::Declared")
    assert declared["runtime"]["commands"] == []  # объявлена, литералов нет
    assert declared["status"]["dynamic"] == 0


# ---------------------------------------------------------------- 3. текст: образцы

_T3 = {
    "pkg/__init__.py": "",
    "pkg/base.py": _pad('class Base:  # @base\n    """Основа."""\n'),
    "pkg/mod.py": _pad(
        '''\
import abc
from typing import Any

from pkg.base import Base


class Handler(Base, abc.ABC):  # @cls
    """Обработчик."""

    def __call__(self, key: str, old_value: Any, new_value: Any) -> None:  # @call
        return None

    def run(self, x: int) -> str:  # @run
        return str(x)


def write_companion(x):  # @fn
    return x
'''
    ),
    "pkg/other.py": _pad(
        """\
from pkg.mod import write_companion  # @imp


def run_a():
    write_companion(1)  # @c1


def run_b():
    write_companion(2)  # @c2
"""
    ),
}


def test_text_found_n_with_forms_literal(repo: GitRepo) -> None:
    """Образцы DESIGN 2 дословно: `найдено 3 (формы: import, name-call); не видно: …`, `не искали`, член
    `имя(сигнатура)  :строка`, основа `— путь:строка (import)`, неразрешённая основа `— строка не указана`;
    порядок строк: `== id ==`, конверт, шесть заголовков."""
    sha = _commit(repo, _T3)
    at = lambda path, marker: _at(_T3, path, marker)  # noqa: E731
    line_no = lambda path, marker: at(path, marker).rsplit(":", 1)[1]  # noqa: E731

    cls = _build(repo, "pkg/mod.py::Handler")
    text = _render(cls)
    lines = _lines(text)
    stripped = [line.strip() for line in lines]
    assert lines[0] == "== pkg/mod.py::Handler =="
    heads = []
    for section in SECTIONS:
        hits = [i for i, line in enumerate(lines) if line.startswith(f"{section}:")]
        assert len(hits) == 1, f"заголовок {section}: строк {len(hits)}"
        heads.append(hits[0])
    assert heads == sorted(heads)  # порядок разделов
    envelope = "\n".join(lines[1 : heads[0]])
    assert at("pkg/mod.py", "cls") in envelope and sha in envelope and cls["scanner"] in envelope
    call_row = f"__call__(key: str, old_value: Any, new_value: Any) -> None  :{line_no('pkg/mod.py', 'call')}"
    assert call_row in stripped
    assert f"run(x: int) -> str  :{line_no('pkg/mod.py', 'run')}" in stripped
    assert f"Base — {at('pkg/base.py', 'base')} (import)" in stripped  # адрес строки class основы
    assert "abc.ABC — строка не указана" in stripped  # where: null
    assert "форма command_specs() не объявлена" in text  # commands: null
    assert any(line.endswith(": не искали") for line in lines), "null раздел/ключ должен читаться «не искали»"
    assert any(line.endswith("—") for line in lines), "искали и нет (`[]`/`0`) должно читаться «—»"

    fn = _build(repo, "pkg/mod.py::write_companion")
    fn_lines = [line.strip() for line in _lines(_render(fn))]
    assert any(
        "найдено 3 (формы: import, name-call); не видно: динамика, аннотации, упоминания" in line for line in fn_lines
    )
    assert f"<module> — {at('pkg/other.py', 'imp')} (import)" in fn_lines
    assert f"run_a — {at('pkg/other.py', 'c1')} (name-call)" in fn_lines
    assert f"run_b — {at('pkg/other.py', 'c2')} (name-call)" in fn_lines


# ---------------------------------------------------------------- 4. бюджет: срез по рангу, «показано K из N»

_CALLERS_N = 45
_T4 = {
    "pkg/__init__.py": "",
    "pkg/target.py": "def target():\n    return 1\n",
    "pkg/callers.py": "from pkg.target import target\n\n\n"
    + "\n\n".join(f"def caller_{i:02d}():\n    target()\n" for i in range(1, _CALLERS_N + 1)),
    "pkg/users.py": """\
from pkg.callers import caller_43, caller_44, caller_45


def use_a():
    caller_45()


def use_b():
    caller_45()


def use_c():
    caller_45()


def use_d():
    caller_44()


def use_e():
    caller_44()


def use_f():
    caller_43()
""",
    "tests/__init__.py": "",
    "tests/test_callers.py": """\
from pkg.callers import caller_43


def test_one():
    caller_43()


def test_two():
    caller_43()
""",
}
_RANKED = ["caller_45", "caller_44", "caller_43", *(f"caller_{i:02d}" for i in range(1, _CALLERS_N - 2))]
_CALL_ROW = re.compile(r"^(caller_\d\d) — pkg/callers\.py:(\d+) \(name-call\)$")


def _call_rows(text: str) -> list[str]:
    return [m.group(1) for line in _lines(text) if (m := _CALL_ROW.match(line.strip()))]


def test_budget_cuts_by_rank_and_says_shown_k_of_n(repo: GitRepo) -> None:
    """45 вызовов `target()`: ранг вызывающего — вызовы и импорты из продукта (тесты не считаются); при бюджете 40
    срез — первые K по `(-rank, path, line)`, раздел помечен `показано K из 45; все: --all call_sites`;
    `--all call_sites` и `--full` (сильнее бюджета) снимают срез; неизвестный раздел в `show_all` -> ValueError."""
    _commit(repo, _T4)
    p = _build(repo, "pkg/target.py::target")
    assert len(p["links"]["call_sites"]) == _CALLERS_N
    before = copy.deepcopy(p)

    text = _render(p, budget=40)
    marks = re.findall(r"показано (\d+) из (\d+); все: --all call_sites", text)
    assert len(marks) == 1, text
    shown_k, total_n = int(marks[0][0]), int(marks[0][1])
    assert total_n == _CALLERS_N and 1 <= shown_k < _CALLERS_N
    shown = _call_rows(text)
    assert len(shown) == shown_k
    assert shown == _RANKED[:shown_k], "порядок среза — (-rank, path, line); ранг считает только продукт"
    assert len(_lines(text)) <= 40

    all_text = _render(p, budget=40, show_all=frozenset({"call_sites"}))
    assert sorted(_call_rows(all_text)) == sorted(_RANKED)  # раздел не режется: все 45
    assert "все: --all call_sites" not in all_text

    full_text = _render(p, budget=5, full=True)  # full сильнее budget
    assert sorted(_call_rows(full_text)) == sorted(_RANKED)
    assert "все: --all call_sites" not in full_text

    assert p == before  # паспорт не меняется
    with pytest.raises(ValueError):
        _render(p, show_all=frozenset({"nope"}))


# ---------------------------------------------------------------- 5. текст: продукт и тесты раздельно

_T5 = {
    "pkg/__init__.py": "",
    "pkg/lib.py": """\
def f():
    return 1


def a():
    f()


def b():
    f()
""",
    "tests/__init__.py": "",
    "tests/test_f.py": """\
from pkg.lib import f


def test_one():
    f()


def test_two():
    f()


def test_three():
    f()
""",
}


def test_text_splits_prod_and_test_counts(repo: GitRepo) -> None:
    """Записи раздела связей: 2 из продукта (вызовы a, b) и 4 из тестов (импорт + 3 вызова) -> `из продукта 2, из
    тестов 4`, не суммой."""
    _commit(repo, _T5)
    p = _build(repo, "pkg/lib.py::f")
    assert [e["scope"] for e in p["links"]["used_by"]] == ["test"]
    assert sorted(e["scope"] for e in p["links"]["call_sites"]) == ["prod", "prod", "test", "test", "test"]
    text = _render(p)
    assert "из продукта 2, из тестов 4" in text
    assert "из продукта 6" not in text and "из тестов 6" not in text  # не одна сумма


# ---------------------------------------------------------------- 6. interface.all: цепочка от ближайшего пакета

_T6 = {
    "modules.yaml": _yaml(("lib/", "framework", "fx/")),
    "lib/a/__init__.py": '"""Юнит А."""\n__all__ = ["Deep"]\n',
    "lib/a/sub/__init__.py": '"""Вложенный пакет."""\n__all__ = ["Widget", "Deep"]\n',
    "lib/a/sub/impl.py": """\
__all__ = ["Widget", "Deep"]


class Widget:
    pass


class Deep:
    pass


class Hidden:
    pass
""",
    "lib/b/__init__.py": '"""Юнит Б."""\n',
    "lib/b/mod.py": "class Thing:\n    pass\n",
    "scripts/__init__.py": "",
    "scripts/tool.py": "def run():\n    return 1\n",
}


def test_interface_all_chain_from_nearest_package(
    repo: GitRepo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`all` — файл символа (если его `__all__` с именем), затем `__init__.py` от ближайшего пакета до юнита, где имя в
    `__all__` (не `__all__` одного юнита); `[]` —
    `__all__` есть, имени нет; `null` — `__all__` нет. `layer` — id юнита из `roots:` ревизии фикстуры (`fx/a`), не
    из cwd; путь вне юнитов — `other`."""
    _commit(repo, _T6)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)  # корень — аргумент, не cwd

    widget = _build(repo, "lib/a/sub/impl.py::Widget")["interface"]
    # файл символа со своим `__all__` с именем — первое звено (Task 4.5c, В14); lib/a/__init__.py имени Widget не знает
    assert widget["all"] == ["lib/a/sub/impl.py", "lib/a/sub/__init__.py"]
    assert widget["layer"] == "fx/a"
    deep = _build(repo, "lib/a/sub/impl.py::Deep")["interface"]
    assert deep["all"] == ["lib/a/sub/impl.py", "lib/a/sub/__init__.py", "lib/a/__init__.py"]  # файл, затем пакеты
    assert _build(repo, "lib/a/sub/impl.py::Hidden")["interface"]["all"] == []
    thing = _build(repo, "lib/b/mod.py::Thing")["interface"]
    assert thing["all"] is None and thing["layer"] == "fx/b"
    assert _build(repo, "scripts/tool.py::run")["interface"]["layer"] == "other"


# ---------------------------------------------------------------- 7. purpose: «зовут из»

_T7 = {
    "pkg/__init__.py": "",
    "pkg/lib.py": "def target():\n    return 1\n\n\ndef target2():\n    return 2\n",
    "pkg/a.py": '''\
from pkg.lib import target


def alpha():
    """Первый абзац alpha.

    Второй абзац alpha.
    """
    target()


def beta():
    target()


def delta():
    """Дельта."""
    target()
''',
    "pkg/entry.py": """\
from pkg.a import alpha, beta


def entry1():
    alpha()


def entry2():
    alpha()


def entry3():
    beta()
""",
    "pkg/c.py": "from pkg.lib import target2\n\ntarget2()\n",
    "pkg/d.py": "from pkg.lib import target2\n\n\ndef gamma():\n    target2()\n",
    "tests/__init__.py": "",
    "tests/test_t.py": "from pkg.lib import target\n\n\ndef test_t():\n    target()\n",
}


def test_purpose_has_called_from_enclosing_paragraph(repo: GitRepo) -> None:
    """`called_from` — вызывающий из продукта с высшим рангом: `{qualname, text}` (первый абзац его докстринга),
    `called_from_more` — прочие вызывающие из продукта (тесты не считаются); `<module>` не выбирается и при равном
    ранге с раньше стоящим по пути; нет докстринга -> `text: ""`."""
    _commit(repo, _T7)
    top = _build(repo, "pkg/lib.py::target")["purpose"]
    assert top["called_from"] == [{"qualname": "alpha", "text": "Первый абзац alpha."}]
    assert top["called_from_more"] == 2  # beta, delta; test_t из тестов не в счёте

    skip_module = _build(repo, "pkg/lib.py::target2")["purpose"]
    assert skip_module["called_from"] == [{"qualname": "gamma", "text": ""}]  # pkg/c.py:<module> раньше по пути

    text = _render(_build(repo, "pkg/lib.py::target"))
    row = [line for line in _lines(text) if "зовут из:" in line]
    assert len(row) == 1, text
    assert "alpha" in row[0] and "Первый абзац alpha." in row[0] and "ещё 2" in row[0]
    assert "Второй абзац" not in text


# ---------------------------------------------------------------- 8. runtime.commands: обе литеральные формы

_T8 = {
    "pkg/__init__.py": "",
    "pkg/svc.py": _pad(
        """\
class CommandSpec:
    def __init__(self, name, help=""):
        self.name = name


class Service:
    def command_specs(self):
        return [
            ("start", "Запустить"),  # @tuple
            CommandSpec("stop", help="Остановить"),  # @call
            make_spec(),
            spec_var,
        ]


class Plain:
    def other(self):
        return 1


def build():
    def command_specs():
        return [("go", "Идти")]  # @nested

    return command_specs
"""
    ),
}


def test_commands_declared_both_forms_with_where(repo: GitRepo) -> None:
    """Кортеж литералов и `CommandSpec(...)` -> `{name, where, how: "declared"}` в порядке исходника; вызов и
    переменная -> не запись, а `status.dynamic`; без `def command_specs` -> `null`; вложенный `def command_specs` в
    функции — её команды."""
    _commit(repo, _T8)
    at = lambda marker: _at(_T8, "pkg/svc.py", marker)  # noqa: E731

    svc = _build(repo, "pkg/svc.py::Service")
    assert svc["runtime"]["commands"] == [
        {"name": "start", "where": at("tuple"), "how": "declared"},
        {"name": "stop", "where": at("call"), "how": "declared"},
    ]
    assert svc["links"]["call_sites_unresolved"] == 0
    assert svc["status"]["dynamic"] == 2  # make_spec() и spec_var

    plain = _build(repo, "pkg/svc.py::Plain")
    assert plain["runtime"]["commands"] is None and plain["status"]["dynamic"] == 0

    build = _build(repo, "pkg/svc.py::build")
    assert build["runtime"]["commands"] == [{"name": "go", "where": at("nested"), "how": "declared"}]
    assert build["status"]["dynamic"] == 0
