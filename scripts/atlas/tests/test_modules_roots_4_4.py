"""Тесты Task 4.4b: юниты из `roots` в modules.yaml, исключения остаются в `modules:` (RED до кода).

Purpose: девять сценариев Д5 — строки юнитов, root_exclude, purpose из докстринга, ошибки без значений,
    число `git cat-file`, теги памяти без PYTHONPATH, `index` с битым юнитом, дубли id.
Public API: тесты test_*; публичных имён нет.
Stability: lite

Тесты 1–6, 8, 9 зовут `load_modules`/`modules_for`/CLI, а не `expand_roots`: красные по содержимому, не по ImportError.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts.atlas.tests.conftest import GitRepo, run_with_deadline

__all__: list[str] = []

_ROOT = Path(__file__).resolve().parents[3]
_TAGS_PY = _ROOT / "scripts" / "memory" / "tags.py"
_MEM = "docs/claude/memory"

_EXCEPTION = (
    'modules:\n  - id: exc\n    paths: ["exc/"]\n    layer: scripts\n    tier: null\n    docs: []\n'
    '    parent: null\n    purpose: "Исключение"\n'
)


def _yaml(*roots: tuple[str, str, str], exclude: str = "[tests, _shared]", extra: str = "", tail: str = "") -> str:
    lines = ["version: 1", "roots:"]
    for path, layer, prefix in roots:
        lines += [f'  - path: "{path}"', f"    layer: {layer}", f'    id_prefix: "{prefix}"']
    lines.append(f"root_exclude: {exclude}")
    return "\n".join(lines) + "\n" + extra + (tail or "modules: []\n")


def _put(base: Path, rel: str, data: bytes | str) -> None:
    target = base / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)


def _fill(base: Path, yaml_text: str, files: dict[str, bytes | str]) -> None:
    _put(base, "modules.yaml", yaml_text)
    for rel, data in files.items():
        _put(base, rel, data)


def _load(base: Path) -> list[dict]:
    from scripts.atlas.modules import load_modules

    return run_with_deadline(lambda: load_modules(base / "modules.yaml"), 60)


def _from_revision(repo: GitRepo) -> list[dict]:
    from scripts.atlas.adapters.modules import modules_for
    from scripts.atlas.tree import Tree

    return run_with_deadline(lambda: modules_for(Tree(repo.path, "HEAD")), 60)


_TWO_ROOTS = _yaml(("lib/", "framework", ""), ("tools/", "scripts", "s/"), extra="tiers:\n  a: core\n")
_TWO_ROOTS_FILES: dict[str, bytes | str] = {
    "tools/b/__init__.py": '"""Б."""\n',
    "tools/b/STATUS.md": "# s\n",
    "lib/a/__init__.py": '"""А."""\n',
    "lib/a/README.md": "# r\n",
    "lib/tests/__init__.py": '"""Тесты."""\n',
    "tools/tests/__init__.py": '"""Тесты."""\n',
    "lib/nopkg/README.md": "# нет __init__\n",
}


def test_roots_expand_to_literal_rows(tmp_path: Path) -> None:
    """2 корня, префиксы "" и "s/": строки-литералы; tests/ и каталог без __init__ не юниты."""
    _fill(tmp_path, _TWO_ROOTS, _TWO_ROOTS_FILES)
    assert _load(tmp_path) == [
        {
            "id": "a",
            "paths": ["lib/a/"],
            "layer": "framework",
            "tier": "core",
            "docs": ["lib/a/README.md"],
            "parent": None,
            "purpose": "А.",
        },
        {
            "id": "s/b",
            "paths": ["tools/b/"],
            "layer": "scripts",
            "tier": None,
            "docs": ["tools/b/STATUS.md"],
            "parent": None,
            "purpose": "Б.",
        },
    ]


def test_root_exclude_dirs_are_not_units(tmp_path: Path) -> None:
    """Без `tests` в root_exclude каталог tests/ с __init__.py становится юнитом; с ним — нет."""
    files = {
        "lib/a/__init__.py": '"""А."""\n',
        "lib/tests/__init__.py": '"""Т."""\n',
        "lib/_shared/__init__.py": '"""Ш."""\n',
    }
    _fill(tmp_path, _yaml(("lib/", "framework", "")), files)
    assert [row["id"] for row in _load(tmp_path)] == ["a"]
    _fill(tmp_path, _yaml(("lib/", "framework", ""), exclude="[]"), files)
    assert [row["id"] for row in _load(tmp_path)] == ["_shared", "a", "tests"]


def test_purpose_is_first_docstring_line(tmp_path: Path) -> None:
    """purpose — первая строка докстринга (не весь текст, не пустая строка до него)."""
    files = {"lib/a/__init__.py": '"""\nПервая строка.\n\nВторая строка.\n"""\n'}
    _fill(tmp_path, _yaml(("lib/", "framework", "")), files)
    assert [row["purpose"] for row in _load(tmp_path)] == ["Первая строка."]


def test_bad_init_error_hides_source(tmp_path: Path) -> None:
    """SyntaxError несёт текст строки (`exc.text`), но сообщение ошибки его не содержит."""
    with pytest.raises(SyntaxError) as syntax:
        ast.parse(b"SECRET SECRET\n")
    assert "SECRET" in (syntax.value.text or ""), "предпосылка: exc.text содержит исходник"
    _fill(tmp_path, _yaml(("lib/", "framework", "")), {"lib/x/__init__.py": b"SECRET SECRET\n"})
    with pytest.raises(ValueError) as caught:
        _load(tmp_path)
    assert str(caught.value) == "modules.yaml: юнит x: __init__.py не разобран"
    assert "SECRET" not in str(caught.value)


@pytest.mark.parametrize(
    ("tiers", "tail"),
    [
        pytest.param("ghost: SECRET", "ключ 'tiers': id ghost не юнит", id="id-is-not-a-unit"),
        pytest.param(
            "a: SECRET", "ключ 'tiers': у юнита a значение не core и не optional", id="value-not-core-or-optional"
        ),
    ],
)
def test_tier_errors_hide_value(tmp_path: Path, tiers: str, tail: str) -> None:
    """Ошибка tiers: id-ключ печатать можно, значение (`SECRET`) — нет; текст — точный литерал."""
    _fill(
        tmp_path,
        _yaml(("lib/", "framework", ""), extra=f"tiers:\n  {tiers}\n"),
        {"lib/a/__init__.py": '"""А."""\n'},
    )
    with pytest.raises(ValueError) as caught:
        _load(tmp_path)
    message = str(caught.value)
    assert message == f"modules.yaml: {tail}"
    assert "SECRET" not in message


def test_nested_package_is_not_a_unit_in_revision(repo: GitRepo) -> None:
    """`lib/nopkg/sub/__init__.py` без `lib/nopkg/__init__.py` — не юнит (фильтр глубины пути)."""
    _fill(
        repo.path,
        _yaml(("lib/", "framework", "")),
        {"lib/a/__init__.py": '"""А."""\n', "lib/nopkg/sub/__init__.py": '"""Вложенный."""\n'},
    )
    repo.commit("nested")
    assert [row["id"] for row in _from_revision(repo)] == ["a"]


def test_symlinked_dir_is_not_a_unit_on_disk(tmp_path: Path) -> None:
    """Симлинк на каталог с `__init__.py` не создаёт юнит на диске (в ревизии симлинк — не дерево)."""
    outside = tmp_path / "outside" / "evil"
    _put(outside, "__init__.py", '"""Чужой."""\n')
    base = tmp_path / "repo"
    _fill(base, _yaml(("lib/", "framework", "")), {"lib/a/__init__.py": '"""А."""\n'})
    try:
        (base / "lib" / "link").symlink_to(outside, target_is_directory=True)
    except OSError:  # Windows без права на симлинки
        pytest.skip("симлинки недоступны")
    assert [row["id"] for row in _load(base)] == ["a"]


def test_unparsable_deep_expression_is_reported_not_leaked(tmp_path: Path) -> None:
    """`__init__.py` с выражением, роняющим парсер (RecursionError/MemoryError), -> ValueError «не разобран»."""
    _fill(tmp_path, _yaml(("lib/", "framework", "")), {"lib/x/__init__.py": "x = " + "-" * 300000 + "\n"})
    with pytest.raises(ValueError) as caught:
        _load(tmp_path)
    assert str(caught.value) == "modules.yaml: юнит x: __init__.py не разобран"


def test_modules_for_reads_committed_blobs(repo: GitRepo, monkeypatch: pytest.MonkeyPatch) -> None:
    """Из ревизии: ровно 2 `git cat-file` (modules.yaml и один батч на все файлы юнитов), диск не читается."""
    _fill(repo.path, _TWO_ROOTS, _TWO_ROOTS_FILES)
    repo.commit("fixture")
    _put(repo.path, "lib/a/__init__.py", '"""Правка на диске."""\n')
    calls: list[list[str]] = []
    real_run = subprocess.run

    def counting_run(args: Any, *a: Any, **kw: Any) -> Any:
        if isinstance(args, (list, tuple)) and "cat-file" in [str(x) for x in args]:
            calls.append([str(x) for x in args])
        return real_run(args, *a, **kw)

    monkeypatch.setattr(subprocess, "run", counting_run)
    rows = _from_revision(repo)
    assert [(row["id"], row["purpose"]) for row in rows] == [("a", "А."), ("s/b", "Б.")]
    assert len(calls) == 2, calls


def test_tags_check_expands_units_without_pythonpath(tmp_path: Path) -> None:
    """tags.py из чужого cwd и без PYTHONPATH находит юниты корней; чужой id — код 1; `roots: 5` — код 2."""
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONUTF8", "PYTHONIOENCODING")}
    env["GIT_CEILING_DIRECTORIES"] = str(tmp_path.parent)

    def run(root: Path) -> tuple[int, str]:
        proc = subprocess.run(
            [sys.executable, str(_TAGS_PY), "--check", "--root", str(root)],
            cwd=str(tmp_path),
            env=env,
            capture_output=True,
            timeout=60,
            check=False,
        )
        return proc.returncode, proc.stdout.decode("utf-8", "replace")

    def lesson(root: Path, name: str, module: str) -> None:
        body = f"---\nname: {name}\ndescription: фикстура fixture\nmodule: {module}\n---\nBody.\n"
        _put(root, f"{_MEM}/{name}.md", body)

    root = tmp_path / "repo"
    _put(root, "modules.yaml", _yaml(("lib/", "framework", ""), tail=_EXCEPTION))
    _put(root, "lib/unitx/__init__.py", '"""Юнит."""\n')
    _put(root, ".claude/agents/dev/tester.md", "# tester\n")
    _put(root, f"{_MEM}/TAGS.yaml", 'mechanisms:\n  - id: break-injection\n    def: "d"\n')
    lesson(root, "ok", "unitx, exc")
    assert run(root) == (0, "")
    lesson(root, "bad", "unitzz")
    assert run(root) == (1, f"{_MEM}/bad.md: unknown-module: 'unitzz'\n")
    _put(root, "modules.yaml", "version: 1\nroots: 5\nmodules: []\n")
    assert run(root)[0] == 2


def test_index_bad_init_exit2(repo: GitRepo, atlas: Any) -> None:
    """`index` с юнитом `u/x` (SyntaxError в __init__.py): код 2 и одна строка в stderr без содержимого."""
    _fill(repo.path, _yaml(("u/", "scripts", "u/")), {"u/x/__init__.py": b"SECRET SECRET\n"})
    repo.commit("bad unit")
    res = atlas(repo, "index", "--ref", "HEAD", "--main-ref", "main")
    assert res.code == 2, res.err
    assert res.err == "modules.yaml: юнит u/x: __init__.py не разобран\n"


def test_duplicate_ids_across_units_and_exceptions(tmp_path: Path) -> None:
    """Дубль id: юнит против записи `modules:` и два корня с одним именем -> `юнит K: id повторяется`."""
    _fill(
        tmp_path,
        _yaml(("lib/", "framework", ""), tail=_EXCEPTION),
        {"lib/exc/__init__.py": '"""Юнит."""\n'},
    )
    with pytest.raises(ValueError) as unit_vs_exception:
        _load(tmp_path)
    assert str(unit_vs_exception.value) == "modules.yaml: юнит exc: id повторяется"
    files = {"lib/k/__init__.py": '"""Один."""\n', "lib2/k/__init__.py": '"""Два."""\n'}
    _fill(tmp_path, _yaml(("lib/", "framework", ""), ("lib2/", "scripts", "")), files)
    with pytest.raises(ValueError) as two_roots:
        _load(tmp_path)
    assert str(two_roots.value) == "modules.yaml: юнит k: id повторяется"
