"""Тесты вывесок scripts/arch_map/signboard.py.

Фикстура — маленькое дерево в tmp_path. Ожидаемые значения — литералы (имена, номера строк, nodeid),
а не результат расчёта тестируемого кода.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.arch_map import signboard

INTERFACES = '''\
from abc import ABC, abstractmethod
from typing import Any, Protocol


class IObserver(Protocol):
    """Подписчик на изменения.

    Второй абзац в карточку не попадает.
    """

    def __call__(self, key: str, old: Any) -> None: ...

    def _hidden(self) -> None: ...


class IStore(ABC):
    """Хранилище ключей."""

    @abstractmethod
    def get(self, key: str) -> Any: ...

    @abstractmethod
    def put(self, key: str, value: Any) -> None: ...

    def keys(self) -> list:
        return []
'''

STORE = '''\
from pkg.interfaces import IStore


class MemStore(IStore):
    def get(self, key):
        return None

    def put(self, key, value):
        return None


class DuckStore:
    def get(self, key):
        return 1

    def put(self, key, value):
        return 2


class HalfStore:
    def get(self, key):
        return 3


def build(name: str, retries: int = 3) -> bool:
    """Собрать хранилище."""
    return True


class Box:
    def __init__(self, size: int = 3, *, tag: str = "x") -> None:
        self.size = size
'''

IO_MOD = """\
import json
from pathlib import Path


def save(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def dump(data, target):
    with open(target, "w", encoding="utf-8") as f:
        json.dump(data, f)


def watch(observer, folder):
    observer.schedule(folder)
"""

TEST_STORE = """\
from pkg.store import build


def test_build_ok():
    assert build("x")


class TestBuild:
    def test_retry(self):
        build("y", 2)


def test_unrelated():
    assert 1
"""

NL = chr(10)
CALLER = "from pkg.store import build\n\nbuild('x')\n"
CALLER_ALIAS = "from pkg.store import build as make\n\nmake('x')\n"
DECOY = "from elsewhere import build\n\nbuild(1)\n"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    files = {
        "pkg/__init__.py": '"""Пакет-фикстура."""\n',
        "pkg/interfaces.py": INTERFACES,
        "pkg/store.py": STORE,
        "pkg/io_mod.py": IO_MOD,
        "tests/test_store.py": TEST_STORE,
        "a.py": CALLER,
        "bb.py": CALLER,
        "ccc.py": CALLER,
        "dddd.py": CALLER_ALIAS,
        "eeeee.py": CALLER,
        "decoy.py": DECOY,
    }
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


def house(repo: Path, path: str, qualname: str) -> dict:
    return signboard.house_spec(repo, path, qualname)


def test_protocol_dunder_member_kept(repo: Path) -> None:
    spec = house(repo, "pkg/interfaces.py", "IObserver")
    assert spec["kind"] == "Protocol"
    assert [m["name"] for m in spec["members"]] == ["__call__"]  # дандер остался, _hidden отброшен
    assert spec["members"][0]["signature"] == "__call__(self, key: str, old: Any) -> None"


def test_abstractmethod_flag(repo: Path) -> None:
    spec = house(repo, "pkg/interfaces.py", "IStore")
    assert spec["kind"] == "ABC"
    assert [(m["name"], m["abstract"]) for m in spec["members"]] == [("get", True), ("put", True), ("keys", False)]


def test_structural_match_not_subclass(repo: Path) -> None:
    spec = house(repo, "pkg/interfaces.py", "IStore")
    assert [s["name"] for s in spec["subclasses"]] == ["MemStore"]
    assert spec["subclasses"][0]["where"] == "pkg/store.py:4"
    assert [s["name"] for s in spec["structural_matches"]] == ["DuckStore"]  # HalfStore без put, MemStore наследует


def test_signature_with_default_and_annotation(repo: Path) -> None:
    # так пишет ast.unparse: без пробелов вокруг "=" у аннотированного параметра
    assert house(repo, "pkg/store.py", "build")["signature"] == "build(name: str, retries: int=3) -> bool"
    box = house(repo, "pkg/store.py", "Box")
    assert box["signature"] == "Box(size: int=3, *, tag: str='x')"
    assert box["init_from"] == "own"


def test_doc_first_paragraph_and_missing(repo: Path) -> None:
    observer = house(repo, "pkg/interfaces.py", "IObserver")
    assert observer["doc_first_paragraph"] == "Подписчик на изменения."
    assert observer["doc_missing"] is False
    half = house(repo, "pkg/store.py", "HalfStore")
    assert half["doc_first_paragraph"] == ""
    assert half["doc_missing"] is True
    assert half["line1"] == "class — докстринга нет"


def test_call_sites_shortest_first_cap_three(repo: Path) -> None:
    spec = house(repo, "pkg/store.py", "build")
    assert spec["call_sites"] == ["a.py:3", "bb.py:3", "ccc.py:3"]
    assert spec["call_sites_total"] == 5  # decoy.py импортирует другой build и не считается; alias make() считается
    assert "0 не значит" in spec["call_sites_note"]
    assert spec["line2"] == "использует меня 5 (вызовы по имени) / использую 0"


def test_io_write_text_path_expr(repo: Path) -> None:
    spec = house(repo, "pkg/io_mod.py", "save")
    assert spec["io"] == [{"op": "writes", "path_expr": "path", "line": 6}]


def test_io_open_with_json_dump_is_one_write_and_schedule_watches(repo: Path) -> None:
    assert house(repo, "pkg/io_mod.py", "dump")["io"] == [{"op": "writes", "path_expr": "target", "line": 10}]
    assert house(repo, "pkg/io_mod.py", "watch")["io"] == [{"op": "watches", "path_expr": "folder", "line": 15}]


def test_tests_as_nodeids(repo: Path) -> None:
    spec = house(repo, "pkg/store.py", "build")
    assert spec["tests"] == ["tests/test_store.py::TestBuild::test_retry", "tests/test_store.py::test_build_ok"]
    assert spec["tests_total"] == 2  # test_unrelated не упоминает build


def test_test_file_fallback_needs_name_import(repo: Path) -> None:
    alias_body = "import pkg" + NL * 3 + "def test_x():" + NL + "    assert pkg" + NL
    fix_body = "from pkg.store import build" + NL * 3 + "def test_y(fx):" + NL + "    pass" + NL
    (repo / "tests" / "test_alias.py").write_text(alias_body, encoding="utf-8")
    (repo / "tests" / "test_fix.py").write_text(fix_body, encoding="utf-8")
    spec = house(repo, "pkg/store.py", "build")
    assert spec["tests"] == [
        "tests/test_fix.py",  # импорт есть, упоминания в test-функции нет — файл целиком
        "tests/test_store.py::TestBuild::test_retry",
        "tests/test_store.py::test_build_ok",
    ]  # test_alias.py (только `import pkg`) не назван


def test_method_call_sites_need_importing_file(repo: Path) -> None:
    (repo / "user.py").write_text("from pkg.store import Box\n\nBox().size_up()\n", encoding="utf-8")
    (repo / "stranger.py").write_text("x = object()\nx.get(1)\n", encoding="utf-8")
    spec = house(repo, "pkg/store.py", "MemStore.get")
    assert spec["kind"] == "method"
    assert spec["call_sites"] == []  # user.py не импортирует MemStore; stranger.py не импортирует вообще


def write_model(repo: Path, findings: list[dict]) -> None:
    layers = ["multiprocess_framework", "Services", "Plugins", "multiprocess_prototype", "backend_ctl"]
    nodes = [{"id": n, "kind": "layer", "parent": None, "name": n, "order": i} for i, n in enumerate(layers)]
    nodes.append(
        {"id": "multiprocess_framework.modules.x", "kind": "unit", "parent": "multiprocess_framework", "name": "x",
         "path": "multiprocess_framework/modules/x",
         "spec": {"fan_in": 1, "fan_out": 2, "all": None, "card": {"purpose": "Икс."}}}
    )  # fmt: skip
    nodes.append(
        {"id": "multiprocess_framework.modules.x.core", "kind": "file", "parent": "multiprocess_framework.modules.x",
         "name": "core", "path": "multiprocess_framework/modules/x/core.py", "loc": 10, "classes": [], "functions": []}
    )  # fmt: skip
    model = {"meta": {"layers": layers}, "nodes": nodes, "edges": [], "findings": findings}
    target = repo / "docs" / "arch-map" / "model.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(model, ensure_ascii=False), encoding="utf-8")
    (repo / "multiprocess_framework").mkdir(exist_ok=True)
    (repo / "multiprocess_framework" / "__init__.py").write_text('"""Фреймворк."""\n', encoding="utf-8")


def test_layer_card_shows_zero_violations(repo: Path) -> None:
    write_model(repo, [])
    spec = signboard.layer_spec(repo, "multiprocess_framework")
    assert spec["line3"] == "нарушений направления: 0"
    assert spec["red"] is False
    assert spec["line1"] == "Фреймворк."
    assert spec["import_rule"] == "можно → никого; нельзя ← Services, Plugins, multiprocess_prototype, backend_ctl"
    assert spec["counts"]["units"] == 1


def test_layer_card_red_when_direction_violated(repo: Path) -> None:
    finding = {"rule": "layer-reverse", "severity": "error", "src_unit": "multiprocess_framework.modules.x",
               "dst_unit": "Services.y", "src": None, "dst": None, "where": None, "detail": "d"}  # fmt: skip
    write_model(repo, [finding])
    spec = signboard.layer_spec(repo, "multiprocess_framework")
    assert spec["line3"] == "нарушений направления: 1"
    assert spec["red"] is True
    assert spec["findings_by_severity"] == {"error": 1, "warn": 0, "info": 0}
    unit = signboard.unit_spec(repo, "multiprocess_framework.modules.x")
    assert unit["line1"] == "Икс."
    assert unit["line3"] == "нарушений направления: 1"
    assert signboard.card_view(unit)["sections"][-2] == ("Витрина __all__", ["нет"])  # __all__ = None не падает


def test_district_lists_houses(repo: Path) -> None:
    spec = signboard.district_spec(repo, "pkg/store.py")
    assert [(h["name"], h["kind"], h["public"]) for h in spec["houses"]] == [
        ("MemStore", "class", True),
        ("DuckStore", "class", True),
        ("HalfStore", "class", True),
        ("build", "function", True),
        ("Box", "class", True),
    ]
    assert {h["name"]: h["call_sites"] for h in spec["houses"]}["build"] == 5


def test_cli_show_on_fixture(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = signboard.main(["--root", str(repo), "show", "pkg/interfaces.py::IStore", "--format", "json"])
    assert code == 0
    spec = json.loads(capsys.readouterr().out)
    assert spec["kind"] == "ABC"
    assert spec["line"] == 16
    code = signboard.main(["--root", str(repo), "show", "pkg/interfaces.py::IStore"])
    text = capsys.readouterr().out
    assert code == 0
    assert text.splitlines()[1] == "ABC — Хранилище ключей"
    assert "[abstract] get(self, key: str) -> Any" in text


def test_cli_unknown_symbol_is_exit_2(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert signboard.main(["--root", str(repo), "show", "pkg/store.py::Nope"]) == 2
    assert "символ не найден: Nope" in capsys.readouterr().err
