"""REDS Task 4.5a (автор — исполнитель): `ref` видит вызовы и наследников через фасад `__init__.py`.

Purpose: голый вызов и основа класса по `from pkg import X`, где `pkg/__init__.py` реэкспортирует `X` (прямо или
    лениво в `__getattr__`, PEP 562), относятся к файлу определения; предел — 5 звеньев `__init__` (решение лида а);
    цикл реэкспортов не вешает разбор и даёт неотнесённый вызов.
Public API: тесты test_*; публичных имён нет.
Stability: lite

Факты — `scan_text(исходник)`. Ожидаемые адреса — литералы `путь:строка`. Построение и опрос — в daemon-потоке с
дедлайном (`run_with_deadline`): цикл реэкспортов не должен вешать прогон.
"""

from __future__ import annotations

import pytest

from scripts.atlas.tests.conftest import run_with_deadline

__all__: list[str] = []

DEADLINE_S = 30.0

_USE = "from pkg import X\n\n\ndef run():\n    X()\n"  # вызов — use.py:5 в `run`


def _links(files: dict[str, str]):
    from scripts.atlas.links import build_links
    from scripts.atlas.scan import scan_text

    return run_with_deadline(lambda: build_links({p: scan_text(s) for p, s in files.items()}), DEADLINE_S)


def _of(links, ident: str) -> dict:
    res = run_with_deadline(lambda: links.of(ident), DEADLINE_S)
    assert res is not None, f"нет записи для {ident}"
    return res


_CALL = {"where": "use.py:5", "how": "name-call", "scope": "prod", "enclosing": "run", "same_file": False}


def test_call_through_init_reexport_attributed():
    """`from pkg import X; X()`, `pkg/__init__.py`: `from .core import X` -> вызов в `call_sites` `pkg/core.py::X`."""
    files = {"pkg/__init__.py": "from .core import X\n", "pkg/core.py": "def X():\n    pass\n", "use.py": _USE}
    res = _of(_links(files), "pkg/core.py::X")
    assert res["call_sites"] == [_CALL]
    assert res["call_sites_unresolved"] == 0


def test_subclass_through_init_reexport():
    """`from pkg import Base; class Sub(Base)` -> `Sub` в `subclasses` `pkg/core.py::Base`, `bases[].where` — core."""
    files = {
        "pkg/__init__.py": "from pkg.core import Base\n",
        "pkg/core.py": "\n\nclass Base:\n    pass\n",  # class Base — pkg/core.py:3
        "use.py": "from pkg import Base\n\n\nclass Sub(Base):\n    pass\n",  # class Sub — use.py:4
    }
    links = _links(files)
    assert _of(links, "pkg/core.py::Base")["subclasses"] == [
        {"where": "use.py:4", "how": "import", "scope": "prod", "enclosing": "Sub"}
    ]
    assert _of(links, "use.py::Sub")["bases"] == [
        {"name": "Base", "where": "pkg/core.py:3", "how": "import", "scope": "prod"}
    ]


def test_lazy_getattr_facade_resolved():
    """Импорт внутри `def __getattr__` фасада (PEP 562, `kind == "lazy"`) тоже реэкспорт."""
    facade = (
        "def __getattr__(name):\n"
        '    if name == "X":\n'
        "        from .core import X\n"
        "\n"
        "        return X\n"
        "    raise AttributeError(name)\n"
    )
    files = {"pkg/__init__.py": facade, "pkg/core.py": "def X():\n    pass\n", "use.py": _USE}
    res = _of(_links(files), "pkg/core.py::X")
    assert res["call_sites"] == [_CALL]
    assert res["call_sites_unresolved"] == 0


@pytest.mark.parametrize(("hops", "resolved"), [(2, True), (5, True), (6, False)])
def test_reexport_hop_limit(hops, resolved):
    """Звено — один `__init__.py` на пути `use -> p1/__init__ -> ... -> pN/__init__ -> pN/core.py` (решение лида а):
    2 и 5 звеньев -> адрес есть, 6 -> вызов неотнесён."""
    files = {f"p{i}/__init__.py": f"from p{i + 1} import X\n" for i in range(1, hops)}
    files[f"p{hops}/__init__.py"] = "from .core import X\n"
    files[f"p{hops}/core.py"] = "def X():\n    pass\n"
    files["use.py"] = "from p1 import X\n\n\ndef run():\n    X()\n"
    res = _of(_links(files), f"p{hops}/core.py::X")
    if resolved:
        assert res["call_sites"] == [_CALL]
        assert res["call_sites_unresolved"] == 0
    else:
        assert res["call_sites"] == []
        assert res["call_sites_unresolved"] == 1


def test_reexport_cycle_stops():
    """`a/__init__` <- `b/__init__` <- `a/__init__`: разбор кончается (дедлайн), `call_sites == []`, unresolved 1."""
    files = {
        "a/__init__.py": "from b import X\n",
        "b/__init__.py": "from a import X\n",
        "decoy.py": "def X():\n    pass\n",  # одноимённая функция: по ней читается ответ
        "use.py": "from a import X\n\n\ndef run():\n    X()\n",
    }
    res = _of(_links(files), "decoy.py::X")
    assert res["call_sites"] == []
    assert res["call_sites_unresolved"] == 1
