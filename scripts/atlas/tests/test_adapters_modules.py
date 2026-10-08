"""Приёмочные тесты адаптера `modules` и parse_modules (Task 1.3a, RED до кода).

Purpose: узлы module из modules.yaml дерева сборки, ошибка невалидного файла, parse_modules
    против load_modules, разрешение всех файлов checkout, регистрация адаптеров.
Public API: тесты test_*; публичных имён нет.
Stability: lite
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.atlas.tests.conftest import GitRepo, run_with_deadline

__all__: list[str] = []

_ROOT = Path(__file__).resolve().parents[3]

_MODULES = """version: 1
modules:
  - id: a
    paths: ["a/"]
    layer: scripts
    tier: null
    docs: []
    parent: null
  - id: a/sub
    paths: ["a/sub/"]
    layer: scripts
    tier: null
    docs: []
    parent: a
"""

_EXTRA_ROW = """  - id: b
    paths: ["b/"]
    layer: scripts
    tier: null
    docs: []
    parent: null
"""


def test_module_nodes_from_the_build_tree(repo: GitRepo, repo_factory: Any, atlas: Any) -> None:
    repo.write("modules.yaml", _MODULES)
    repo.commit("modules")
    repo.write("modules.yaml", _MODULES + _EXTRA_ROW)  # не закоммичено

    res = atlas(repo, "--json")
    assert res.code == 0, res.err
    nodes = [n for n in json.loads(res.out)["nodes"] if n["kind"] == "module"]
    assert [n["id"] for n in nodes] == ["a", "a/sub"]
    for node in nodes:
        assert node["path"] == "modules.yaml"
        assert node["status"] is None
        assert node["time"] is None

    bare = repo_factory.create("bare")
    bare.write("README.md", "# no modules\n")
    bare.commit("readme only")
    res = atlas(bare, "--json")
    assert res.code == 0, res.err
    assert [n for n in json.loads(res.out)["nodes"] if n["kind"] == "module"] == []


def test_invalid_modules_yaml_exits_2(repo: GitRepo, atlas: Any) -> None:
    repo.write("modules.yaml", _MODULES.replace("version: 1", "version: 2"))
    repo.commit("bad version")
    res = atlas(repo, "build")
    assert res.code == 2
    assert res.err == "modules.yaml: ключ 'version' должен быть равен 1\n"


@pytest.mark.parametrize(
    "payload",
    [
        b'version: 1\nmodules:\n  - id: a\n    paths: ["a/"\n    layer: SECRET_VALUE_42\n',
        b"version: 1\nmodules:\n  - id: a\xff\n",
    ],
    ids=["yaml-syntax", "non-utf8"],
)
def test_unparseable_modules_yaml_exits_2(repo: GitRepo, atlas: Any, payload: bytes) -> None:
    (repo.path / "modules.yaml").write_bytes(payload)
    repo.commit("broken modules")
    res = atlas(repo, "build")
    assert res.code == 2
    assert res.err == "modules.yaml: файл не разобран как YAML в UTF-8\n"
    assert "SECRET_VALUE_42" not in res.err


def test_parse_modules_matches_load_modules() -> None:
    import yaml

    from scripts.atlas.modules import parse_modules

    text = (_ROOT / "modules.yaml").read_text(encoding="utf-8")
    assert parse_modules(text) == yaml.safe_load(text)["modules"]
    with pytest.raises(ValueError):
        parse_modules("version: 2\nmodules: []\n")


def test_every_tracked_file_resolves_to_a_module_or_other() -> None:
    from scripts.atlas.adapters.modules import modules_for
    from scripts.atlas.modules import OTHER, resolve
    from scripts.atlas.tree import Tree

    def work() -> tuple[list[str], list[dict]]:
        tree = Tree(_ROOT, "HEAD")
        return tree.files(), modules_for(tree)

    files, modules = run_with_deadline(work, 120)
    ids = {row["id"] for row in modules}
    resolved = {path: resolve(path, modules) for path in files}
    others = sum(1 for value in resolved.values() if value == OTHER)
    stray = [p for p, v in resolved.items() if v != OTHER and v not in ids]
    assert stray == [], f"other={others}"
    assert resolved["scripts/atlas/build.py"] == "scripts/atlas", f"other={others}"
    assert resolved["README.md"] == "other", f"other={others}"
    generic = [p for p in files if p.startswith("multiprocess_framework/modules/process_module/generic/")]
    assert generic, "нет отслеживаемых файлов под process_module/generic/ — проверка пуста"
    assert {resolved[p] for p in generic} == {"process_module/generic"}, f"other={others}"


def _row(row_id: str) -> str:
    return f'  - id: {row_id}\n    paths: ["x/"]\n    layer: scripts\n    tier: null\n    docs: []\n    parent: null\n'


_BAD_ID = "modules.yaml: в строке {} ключ 'id' пустой, не строка или повторяется\n"


def test_bad_module_id_exits_2(repo_factory: Any, atlas: Any) -> None:
    cases = [
        (["a", "a"], 1),
        (["null"], 0),
        (["7"], 0),
        (["2026-01-05"], 0),
        (['""'], 0),
    ]
    for n, (ids, index) in enumerate(cases):
        repo = repo_factory.create(f"bad_id_{n}")
        repo.write("modules.yaml", "version: 1\nmodules:\n" + "".join(_row(i) for i in ids))
        repo.commit("bad module id")
        res = atlas(repo, "build", "--ref", "HEAD", "--main-ref", "main")
        assert res.code == 2, ids
        assert res.err == _BAD_ID.format(index), ids
        assert "Traceback" not in res.err, ids


def test_yaml_constructor_error_gets_the_file_prefix(repo: GitRepo, atlas: Any) -> None:
    repo.write("modules.yaml", "version: 1\nmodules:\n" + _row("2026-13-45"))
    repo.commit("impossible yaml date")
    res = atlas(repo, "build", "--ref", "HEAD", "--main-ref", "main")
    assert res.code == 2
    assert res.err == "modules.yaml: файл не разобран как YAML в UTF-8\n"


def test_adapters_registration() -> None:
    from scripts.atlas.build import ADAPTERS

    assert [(type(a).__name__, a.name) for a in ADAPTERS] == [
        ("ModulesAdapter", "modules"),
        ("PlansAdapter", "plans"),
        ("CommitsAdapter", "commits"),
        ("CodeAdapter", "code"),
        ("RulesAdapter", "rules"),
    ]
    assert ADAPTERS[0].version == 1
    for adapter in ADAPTERS[1:]:
        assert isinstance(adapter.version, int), adapter.name
