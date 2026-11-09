"""Слепые приёмочные тесты Task 4.4b: `modules.yaml` с `roots` и исключениями (RED до кода).

Purpose: юниты из `roots` (диск и ревизия), порядок строк, ошибки без значений, число вызовов
    `git cat-file`, теги памяти, репозиторный приём (размер yaml, равенство строк со старым yaml, скорость).
Public API: тесты test_*; публичных имён нет.
Stability: lite

Тесты написаны по наблюдаемому поведению из брифа, кода реализации автор не видел.
Ожидаемые значения — литералы. Код проекта импортируется внутри тестов (кроме conftest),
чтобы красный был по содержанию, а не ошибкой сбора.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from scripts.atlas.tests.conftest import GitRepo, run_with_deadline

__all__: list[str] = []

_ROOT = Path(__file__).resolve().parents[3]
_OLD_COMMIT = "35e68f3d5"  # последний коммит, где modules.yaml ещё плоский (1035 строк)
_TAGS_PY = _ROOT / "scripts" / "memory" / "tags.py"

# --------------------------------------------------------------------------- фикстурное дерево

_FIXTURE_YAML = """version: 1
roots:
  - path: "tools/"
    layer: scripts
    id_prefix: "s/"
  - path: "lib/"
    layer: framework
    id_prefix: ""
root_exclude: [tests, _shared]
tiers:
  alpha: core
  beta: optional
  s/gamma: core
modules:
  - id: m_b
    paths: ["mb/"]
    layer: framework
    tier: core
    docs: []
    parent: null
    purpose: "Исключение Б"
  - id: m_a
    paths: ["ma/"]
    layer: scripts
    tier: optional
    docs: ["ma/README.md"]
    parent: m_b
    purpose: "Исключение А"
"""

# Файлы фикстуры в порядке, НЕ совпадающем с алфавитом: порядок строк не должен зависеть от порядка создания.
_FIXTURE_FILES: dict[str, bytes | str] = {
    "lib/zulu/__init__.py": '"""Зулу."""\n'.encode(),
    "lib/zulu/STATUS.md": b"# status\n",
    "lib/mid/__init__.py": b'"""Mid unit."""\n',
    "lib/beta/__init__.py": b'"""Beta unit."""\nx = 1\n',
    "lib/beta/README.md": b"# r\n",
    "lib/beta/STATUS.md": b"# s\n",
    "lib/beta/DECISIONS.md": b"# d\n",
    "lib/alpha/__init__.py": '"""Альфа: первая строка.\n\nВторая строка про детали.\n"""\n'.encode(),
    "lib/alpha/README.md": b"# r\n",
    "lib/alpha/DECISIONS.md": b"# d\n",
    "lib/alpha/sub/__init__.py": '"""Вложенный пакет — не юнит."""\n',
    "lib/tests/__init__.py": '"""Тесты — исключены."""\n',
    "lib/_shared/__init__.py": '"""Общее — исключено."""\n',
    "lib/nopkg/README.md": b"# no init\n",
    "lib/nopkg/mod.py": '"""Модуль без пакета."""\n',
    "lib/loose.py": '"""Файл, не каталог."""\n',
    "tools/gamma/__init__.py": b'"""Gamma tool."""\n',
    "tools/gamma/STATUS.md": b"# s\n",
    "tools/delta/__init__.py": b'"""Delta tool."""\n',
    "tools/tests/__init__.py": '"""Тесты — исключены."""\n',
}

_EXPECTED_ROWS: list[dict[str, Any]] = [
    {
        "id": "s/delta",
        "paths": ["tools/delta/"],
        "layer": "scripts",
        "tier": None,
        "docs": [],
        "parent": None,
        "purpose": "Delta tool.",
    },
    {
        "id": "s/gamma",
        "paths": ["tools/gamma/"],
        "layer": "scripts",
        "tier": "core",
        "docs": ["tools/gamma/STATUS.md"],
        "parent": None,
        "purpose": "Gamma tool.",
    },
    {
        "id": "alpha",
        "paths": ["lib/alpha/"],
        "layer": "framework",
        "tier": "core",
        "docs": ["lib/alpha/README.md", "lib/alpha/DECISIONS.md"],
        "parent": None,
        "purpose": "Альфа: первая строка.",
    },
    {
        "id": "beta",
        "paths": ["lib/beta/"],
        "layer": "framework",
        "tier": "optional",
        "docs": ["lib/beta/README.md", "lib/beta/STATUS.md", "lib/beta/DECISIONS.md"],
        "parent": None,
        "purpose": "Beta unit.",
    },
    {
        "id": "mid",
        "paths": ["lib/mid/"],
        "layer": "framework",
        "tier": None,
        "docs": [],
        "parent": None,
        "purpose": "Mid unit.",
    },
    {
        "id": "zulu",
        "paths": ["lib/zulu/"],
        "layer": "framework",
        "tier": None,
        "docs": ["lib/zulu/STATUS.md"],
        "parent": None,
        "purpose": "Зулу.",
    },
    {
        "id": "m_b",
        "paths": ["mb/"],
        "layer": "framework",
        "tier": "core",
        "docs": [],
        "parent": None,
        "purpose": "Исключение Б",
    },
    {
        "id": "m_a",
        "paths": ["ma/"],
        "layer": "scripts",
        "tier": "optional",
        "docs": ["ma/README.md"],
        "parent": "m_b",
        "purpose": "Исключение А",
    },
]


def _put(base: Path, rel: str, data: bytes | str) -> None:
    target = base / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)


def _fill(base: Path, yaml_text: str, files: dict[str, bytes | str]) -> None:
    _put(base, "modules.yaml", yaml_text.encode("utf-8"))
    for rel, data in files.items():
        _put(base, rel, data)


def _commit_all(repo: GitRepo) -> None:
    repo.commit("fixture")


def _load(base: Path) -> list[dict]:
    from scripts.atlas.modules import load_modules

    return run_with_deadline(lambda: load_modules(base / "modules.yaml"), 60)


def _from_revision(repo: GitRepo) -> list[dict]:
    from scripts.atlas.adapters.modules import modules_for
    from scripts.atlas.tree import Tree

    return run_with_deadline(lambda: modules_for(Tree(repo.path, "HEAD")), 60)


def _roots_yaml(*pairs: tuple[str, str, str], tail: str = "") -> str:
    """yaml с корнями `(path, layer, id_prefix)`, пустым `modules` и произвольным хвостом."""
    lines = ["version: 1", "roots:"]
    for path, layer, prefix in pairs:
        lines += [f'  - path: "{path}"', f"    layer: {layer}", f'    id_prefix: "{prefix}"']
    return "\n".join(lines) + "\n" + (tail or "modules: []\n")


# --------------------------------------------------------------------------- 1. строки юнитов


def test_load_modules_expands_units_in_documented_order(tmp_path: Path) -> None:
    """Строка юнита: поля, docs в порядке README/STATUS/DECISIONS, tier из tiers; порядок roots, units, modules."""
    _fill(tmp_path, _FIXTURE_YAML, _FIXTURE_FILES)
    assert _load(tmp_path) == _EXPECTED_ROWS


def test_no_units_for_excluded_or_package_less_or_nested_dirs(tmp_path: Path) -> None:
    """Юнит = прямой подкаталог корня с __init__.py вне root_exclude; вложенные пакеты и файлы — нет."""
    _fill(tmp_path, _FIXTURE_YAML, _FIXTURE_FILES)
    ids = [row["id"] for row in _load(tmp_path)]
    for absent in ("tests", "_shared", "nopkg", "loose", "alpha/sub", "sub", "s/tests", "s/_shared"):
        assert absent not in ids, absent
    assert ids == ["s/delta", "s/gamma", "alpha", "beta", "mid", "zulu", "m_b", "m_a"]


def test_roots_order_is_the_yaml_order_not_alphabetical(tmp_path: Path) -> None:
    """Порядок корней — как в `roots`; юниты внутри корня — по имени каталога."""
    files = {
        "a/b/__init__.py": b'"""B."""\n',
        "a/a/__init__.py": b'"""A."""\n',
        "z/y/__init__.py": b'"""Y."""\n',
        "z/x/__init__.py": b'"""X."""\n',
    }
    _fill(tmp_path, _roots_yaml(("z/", "scripts", "z_"), ("a/", "scripts", "a_")), files)
    assert [row["id"] for row in _load(tmp_path)] == ["z_x", "z_y", "a_a", "a_b"]


def test_yaml_without_roots_ignores_directories_on_disk(tmp_path: Path) -> None:
    """Без `roots` ничего не меняется: на диске пакеты есть, строк-юнитов нет."""
    old = (
        'version: 1\nmodules:\n  - id: only\n    paths: ["lib/"]\n    layer: framework\n    tier: null\n'
        '    docs: []\n    parent: null\n    purpose: "Единственная"\n'
    )
    _fill(tmp_path, old, _FIXTURE_FILES)
    assert _load(tmp_path) == [
        {
            "id": "only",
            "paths": ["lib/"],
            "layer": "framework",
            "tier": None,
            "docs": [],
            "parent": None,
            "purpose": "Единственная",
        }
    ]


def test_bom_prefixed_init_is_a_valid_unit(tmp_path: Path) -> None:
    """BOM в начале __init__.py не делает юнит невалидным (utf-8-sig)."""
    files = {"lib/bom/__init__.py": b'\xef\xbb\xbf"""\xd0\xae\xd0\xbd\xd0\xb8\xd1\x82 \xd1\x81 BOM."""\n'}
    _fill(tmp_path, _roots_yaml(("lib/", "framework", "")), files)
    assert _load(tmp_path) == [
        {
            "id": "bom",
            "paths": ["lib/bom/"],
            "layer": "framework",
            "tier": None,
            "docs": [],
            "parent": None,
            "purpose": "Юнит с BOM.",
        }
    ]


# --------------------------------------------------------------------------- 2. диск против ревизии


def test_load_modules_reads_units_from_disk(repo: GitRepo) -> None:
    """load_modules видит рабочий каталог: правка докстринга, новый каталог, удалённый README."""
    _fill(repo.path, _FIXTURE_YAML, _FIXTURE_FILES)
    _commit_all(repo)
    _put(repo.path, "lib/alpha/__init__.py", '"""Правка на диске."""\n'.encode())
    _put(repo.path, "lib/fresh/__init__.py", '"""Свежий."""\n')
    (repo.path / "lib/beta/README.md").unlink()
    rows = {row["id"]: row for row in _load(repo.path)}
    assert rows["alpha"]["purpose"] == "Правка на диске."
    assert rows["fresh"]["paths"] == ["lib/fresh/"]
    assert rows["beta"]["docs"] == ["lib/beta/STATUS.md", "lib/beta/DECISIONS.md"]


def test_modules_for_reads_units_from_the_committed_revision(repo: GitRepo) -> None:
    """modules_for читает blobs коммита: те же правки на диске строки не меняют."""
    _fill(repo.path, _FIXTURE_YAML, _FIXTURE_FILES)
    _commit_all(repo)
    _put(repo.path, "lib/alpha/__init__.py", '"""Правка на диске."""\n'.encode())
    _put(repo.path, "lib/fresh/__init__.py", '"""Свежий."""\n')
    (repo.path / "lib/beta/README.md").unlink()
    assert _from_revision(repo) == _EXPECTED_ROWS


def test_modules_for_uses_exactly_two_git_cat_file_calls(repo: GitRepo, monkeypatch: pytest.MonkeyPatch) -> None:
    """Скорость: одна `cat-file` на modules.yaml и одна пакетная на все файлы юнитов (не по вызову на файл)."""
    _fill(repo.path, _FIXTURE_YAML, _FIXTURE_FILES)
    _commit_all(repo)
    calls: list[list[str]] = []
    real_run = subprocess.run

    def counting_run(args: Any, *a: Any, **kw: Any) -> Any:
        if isinstance(args, (list, tuple)) and "cat-file" in [str(x) for x in args]:
            calls.append([str(x) for x in args])
        return real_run(args, *a, **kw)

    monkeypatch.setattr(subprocess, "run", counting_run)
    rows = _from_revision(repo)
    assert rows == _EXPECTED_ROWS, "строки юнитов не получены — счёт вызовов ничего не доказывает"
    assert len(calls) == 2, calls


def test_modules_for_matches_load_modules_on_a_clean_tree(repo: GitRepo) -> None:
    """Оба пути чтения дают одно и то же на чистом дереве (диск == ревизия)."""
    _fill(repo.path, _FIXTURE_YAML, _FIXTURE_FILES)
    _commit_all(repo)
    assert _from_revision(repo) == _load(repo.path) == _EXPECTED_ROWS


def test_bom_prefixed_init_is_a_valid_unit_from_revision(repo: GitRepo) -> None:
    """BOM допустим и при чтении из ревизии."""
    files = {"lib/bom/__init__.py": b'\xef\xbb\xbf"""\xd0\xae\xd0\xbd\xd0\xb8\xd1\x82 \xd1\x81 BOM."""\n'}
    _fill(repo.path, _roots_yaml(("lib/", "framework", "")), files)
    _commit_all(repo)
    assert [(r["id"], r["purpose"]) for r in _from_revision(repo)] == [("bom", "Юнит с BOM.")]


# --------------------------------------------------------------------------- 3. ошибки без значений

_NOT_PARSED = "юнит x: __init__.py не разобран"
_NO_DOC = "юнит x: нет докстринга"
_BAD_INITS = [
    pytest.param(b"SECRET SECRET\n", _NOT_PARSED, id="syntax-error"),
    pytest.param(b'"""ok"""\n# SECRET \xff\xfe\n', _NOT_PARSED, id="invalid-utf8"),
    pytest.param(b'""""""\nSECRET = 1\n', _NOT_PARSED, id="empty-docstring"),
    pytest.param(b"SECRET = 1\n", _NO_DOC, id="no-docstring"),
]


@pytest.mark.parametrize(("init_bytes", "tail"), _BAD_INITS)
def test_bad_unit_init_raises_value_error_without_contents(tmp_path: Path, init_bytes: bytes, tail: str) -> None:
    """Плохой __init__.py -> ValueError с литералом и без содержимого файла."""
    _fill(tmp_path, _roots_yaml(("lib/", "framework", "")), {"lib/x/__init__.py": init_bytes})
    with pytest.raises(ValueError) as caught:
        _load(tmp_path)
    message = str(caught.value)
    assert message == f"modules.yaml: {tail}"
    assert "SECRET" not in message


@pytest.mark.parametrize(("init_bytes", "tail"), _BAD_INITS)
def test_bad_unit_init_raises_atlas_error_from_revision(repo: GitRepo, init_bytes: bytes, tail: str) -> None:
    """То же из ревизии: AtlasError с тем же литералом и без содержимого."""
    from scripts.atlas.tree import AtlasError

    _fill(repo.path, _roots_yaml(("lib/", "framework", "")), {"lib/x/__init__.py": init_bytes})
    _commit_all(repo)
    with pytest.raises(AtlasError) as caught:
        _from_revision(repo)
    message = str(caught.value)
    assert message == f"modules.yaml: {tail}"
    assert "SECRET" not in message


_DUP_MODULE_ROW = (
    'modules:\n  - id: dup\n    paths: ["z/"]\n    layer: framework\n    tier: null\n    docs: []\n'
    '    parent: null\n    purpose: "Исключение"\n'
)
_DUP_CASES = [
    pytest.param(
        _roots_yaml(("lib/", "framework", ""), ("lib2/", "scripts", "")),
        {"lib/dup/__init__.py": '"""Один."""\n', "lib2/dup/__init__.py": '"""Два."""\n'},
        id="two-roots-same-id",
    ),
    pytest.param(
        _roots_yaml(("lib/", "framework", ""), tail=_DUP_MODULE_ROW),
        {"lib/dup/__init__.py": '"""Юнит."""\n'},
        id="unit-equals-modules-entry",
    ),
]


@pytest.mark.parametrize(("yaml_text", "files"), _DUP_CASES)
def test_duplicate_unit_id_is_rejected(tmp_path: Path, yaml_text: str, files: dict[str, bytes | str]) -> None:
    """Повтор id (два корня или юнит против записи modules) -> ValueError `юнит dup: id повторяется`."""
    _fill(tmp_path, yaml_text, files)
    with pytest.raises(ValueError) as caught:
        _load(tmp_path)
    assert str(caught.value) == "modules.yaml: юнит dup: id повторяется"


@pytest.mark.parametrize(("yaml_text", "files"), _DUP_CASES)
def test_duplicate_unit_id_is_rejected_from_revision(
    repo: GitRepo, yaml_text: str, files: dict[str, bytes | str]
) -> None:
    """Повтор id из ревизии -> AtlasError с тем же текстом."""
    from scripts.atlas.tree import AtlasError

    _fill(repo.path, yaml_text, files)
    _commit_all(repo)
    with pytest.raises(AtlasError) as caught:
        _from_revision(repo)
    assert str(caught.value) == "modules.yaml: юнит dup: id повторяется"


_TIER_FILES = {"lib/alpha/__init__.py": '"""Альфа."""\n', "lib/tests/__init__.py": '"""Исключён."""\n'}
_BAD_TIERS = [
    pytest.param("tiers:\n  ghost: core\n", id="tier-for-non-unit"),
    pytest.param("tiers:\n  tests: core\n", id="tier-for-excluded-dir"),
    pytest.param("tiers:\n  alpha: SECRET\n", id="tier-value-not-core-or-optional"),
    pytest.param("tiers:\n  ghost: SECRET\n", id="non-unit-and-bad-value"),
    pytest.param("roots: 5\n", id="roots-not-a-list"),
    pytest.param("roots: SECRET\n", id="roots-a-string"),
    pytest.param("tiers: 5\n", id="tiers-not-a-mapping"),
    pytest.param("tiers: [alpha, SECRET]\n", id="tiers-a-list"),
]


def _bad_tier_yaml(fragment: str) -> str:
    base = '  - path: "lib/"\n    layer: framework\n    id_prefix: ""\n'
    if fragment.startswith("roots:"):
        return f"version: 1\n{fragment}modules: []\n"
    return f"version: 1\nroots:\n{base}root_exclude: [tests]\n{fragment}modules: []\n"


@pytest.mark.parametrize("fragment", _BAD_TIERS)
def test_bad_tiers_or_roots_shape_raise_value_error_without_values(tmp_path: Path, fragment: str) -> None:
    """tiers/roots неверной формы или со значением вне core|optional -> ValueError `modules.yaml: ...` без значений."""
    _fill(tmp_path, _bad_tier_yaml(fragment), _TIER_FILES)
    with pytest.raises(ValueError) as caught:
        _load(tmp_path)
    message = str(caught.value)
    assert message.startswith("modules.yaml: "), message
    assert "SECRET" not in message


@pytest.mark.parametrize("fragment", _BAD_TIERS)
def test_bad_tiers_or_roots_shape_raise_atlas_error_from_revision(repo: GitRepo, fragment: str) -> None:
    """То же из ревизии: AtlasError с префиксом и без значений."""
    from scripts.atlas.tree import AtlasError

    _fill(repo.path, _bad_tier_yaml(fragment), _TIER_FILES)
    _commit_all(repo)
    with pytest.raises(AtlasError) as caught:
        _from_revision(repo)
    message = str(caught.value)
    assert message.startswith("modules.yaml: "), message
    assert "SECRET" not in message


def test_valid_tiers_still_load(tmp_path: Path) -> None:
    """Контроль для предыдущих тестов: корректные tiers не вызывают ошибку (иначе «красный» ничего не значит)."""
    _fill(tmp_path, _bad_tier_yaml("tiers:\n  alpha: optional\n"), _TIER_FILES)
    rows = _load(tmp_path)
    assert [(r["id"], r["tier"]) for r in rows] == [("alpha", "optional")]


# --------------------------------------------------------------------------- 5. CLI index


def _run_cli(repo: GitRepo, *argv: str) -> subprocess.CompletedProcess[bytes]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(_ROOT)
    env["PYTHONUTF8"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "scripts.atlas", *argv],
        cwd=str(repo.path),
        env=env,
        capture_output=True,
        timeout=120,
        check=False,
    )


def test_cli_index_syntax_error_in_unit_exits_2_with_exact_stderr(repo: GitRepo) -> None:
    """`python -m scripts.atlas index` с юнитом без валидного __init__.py: код 2 и ровно одна строка в stderr."""
    _fill(repo.path, _roots_yaml(("u/", "scripts", "u/")), {"u/x/__init__.py": b"SECRET SECRET\n"})
    _commit_all(repo)
    proc = _run_cli(repo, "index", "--ref", "HEAD", "--main-ref", "main")
    err = proc.stderr.decode("utf-8", "replace")
    assert proc.returncode == 2, err
    assert err == "modules.yaml: юнит u/x: __init__.py не разобран\n"


# --------------------------------------------------------------------------- 6. теги памяти

_MEM = "docs/claude/memory"
_TAGS_YAML = (
    "version: 1\n"
    "roots:\n"
    '  - path: "lib/"\n    layer: framework\n    id_prefix: ""\n'
    '  - path: "tools/"\n    layer: scripts\n    id_prefix: "s/"\n'
    "root_exclude: [tests]\n"
    "modules:\n"
    "  - id: logger_module\n"
    '    paths: ["logger_module/"]\n    layer: framework\n    tier: null\n    docs: []\n    parent: null\n'
    '    purpose: "Логгер"\n'
)


def _tags_root(base: Path, yaml_text: str, lessons: dict[str, str]) -> Path:
    root = base / "repo"
    _put(root, "modules.yaml", yaml_text.encode("utf-8"))
    _put(root, "lib/unitx/__init__.py", '"""Юнит икс."""\n'.encode())
    _put(root, "tools/tool/__init__.py", b'"""Tool unit."""\n')
    _put(root, ".claude/agents/dev/tester.md", b"# tester\n")
    _put(root, f"{_MEM}/TAGS.yaml", b'mechanisms:\n  - id: break-injection\n    def: "d"\n')
    for name, module in lessons.items():
        text = f"---\nname: {name}\ndescription: фикстура fixture\nmodule: {module}\n---\nBody.\n"
        _put(root, f"{_MEM}/{name}.md", text.encode("utf-8"))
    return root


def _run_tags(base: Path, root: Path) -> tuple[int, str, str]:
    """tags.py как подпроцесс: cwd вне репозитория, PYTHONPATH снят — скрипт сам находит свой пакет."""
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONUTF8", "PYTHONIOENCODING")}
    env["GIT_CEILING_DIRECTORIES"] = str(base.parent)
    proc = subprocess.run(
        [sys.executable, str(_TAGS_PY), "--check", "--root", str(root)],
        cwd=str(base),
        env=env,
        capture_output=True,
        timeout=60,
        check=False,
    )
    return proc.returncode, proc.stdout.decode("utf-8", "replace"), proc.stderr.decode("utf-8", "replace")


def test_tags_check_accepts_unit_ids_from_roots(tmp_path: Path) -> None:
    """Урок с id юнита из roots (с префиксом и без) и с id из modules: проходит, код 0."""
    root = _tags_root(tmp_path, _TAGS_YAML, {"u1": "unitx", "u2": "s/tool", "u3": "logger_module"})
    rc, out, err = _run_tags(tmp_path, root)
    assert (rc, out) == (0, ""), err


def test_tags_check_rejects_unknown_id_next_to_unit_ids(tmp_path: Path) -> None:
    """Неизвестный id по-прежнему ошибка (код 1, одна строка), а id юнита рядом — нет."""
    root = _tags_root(tmp_path, _TAGS_YAML, {"good": "unitx", "bad": "unitzz"})
    rc, out, err = _run_tags(tmp_path, root)
    assert rc == 1, err
    assert out.splitlines() == [f"{_MEM}/bad.md: unknown-module: 'unitzz'"]


def test_tags_check_excluded_dir_is_not_a_known_module(tmp_path: Path) -> None:
    """Каталог из root_exclude не юнит: тег с его именем — unknown-module."""
    _put(tmp_path, "repo/lib/tests/__init__.py", '"""Исключён."""\n')
    root = _tags_root(tmp_path, _TAGS_YAML, {"ex": "tests"})
    rc, out, err = _run_tags(tmp_path, root)
    assert rc == 1, err
    assert out.splitlines() == [f"{_MEM}/ex.md: unknown-module: 'tests'"]


def test_tags_check_exits_2_on_malformed_roots(tmp_path: Path) -> None:
    """`roots: 5` -> код 2 (ошибка входа, не «урок с неверным тегом»)."""
    root = _tags_root(tmp_path, "version: 1\nroots: 5\nmodules: []\n", {"u1": "logger_module"})
    rc, _, _ = _run_tags(tmp_path, root)
    assert rc == 2


# --------------------------------------------------------------------------- 7. репозиторный приём
# закреплено на 984cc5799 по решению лида 2026-11-09: тесты раздела читают коммит с yaml 4.4b, а не HEAD и не
# рабочий файл, чтобы обычная правка докстринга юнита или новой записи `modules:` не красила CI-джоб atlas.

_PINNED = "984cc5799"  # закреплено на 984cc5799 по решению лида 2026-11-09


def _git_show(commit: str) -> str:
    proc = subprocess.run(["git", "-C", str(_ROOT), "show", f"{commit}:modules.yaml"], capture_output=True, check=False)
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    return proc.stdout.decode("utf-8")


def _old_text() -> str:
    return _git_show(_OLD_COMMIT)


def _canon(rows: list[dict]) -> set[str]:
    return {json.dumps(row, sort_keys=True, ensure_ascii=False, default=str) for row in rows}


def test_repo_modules_yaml_is_at_most_450_lines() -> None:
    """Файл ужат: <= 450 строк (было 1035), версия остаётся 1, ключ roots есть."""
    raw = _git_show(_PINNED).encode("utf-8")  # закреплено на 984cc5799 по решению лида 2026-11-09
    assert raw.count(b"\n") <= 450
    data = yaml.safe_load(raw.decode("utf-8"))
    assert data["version"] == 1
    assert isinstance(data["roots"], list) and data["roots"]


def test_repo_pinned_revision_rows_equal_the_old_flat_yaml() -> None:
    """Строки ревизии 984cc5799 (юниты + исключения) = строки плоского yaml 35e68f3d5: 89 = 57 + 32."""
    from scripts.atlas.adapters.modules import modules_for
    from scripts.atlas.tree import Tree

    old_rows = yaml.safe_load(_old_text())["modules"]
    exceptions = yaml.safe_load(_git_show(_PINNED))["modules"]  # закреплено на 984cc5799 по решению лида 2026-11-09
    rows = run_with_deadline(lambda: modules_for(Tree(_ROOT, _PINNED)), 120)
    assert (len(old_rows), len(rows), len(exceptions)) == (89, 89, 32)
    assert len(rows) - len(exceptions) == 57
    assert _canon(rows) == _canon(old_rows)


def test_repo_exceptions_keep_their_relative_order() -> None:
    """Записи `modules:` ревизии 984cc5799 идут в конце и в старом относительном порядке; юниты — перед ними."""
    from scripts.atlas.adapters.modules import modules_for
    from scripts.atlas.tree import Tree

    old_ids = [row["id"] for row in yaml.safe_load(_old_text())["modules"]]
    data = yaml.safe_load(_git_show(_PINNED))  # закреплено на 984cc5799 по решению лида 2026-11-09
    exception_ids = [row["id"] for row in data["modules"]]
    assert exception_ids, "в modules.yaml не осталось исключений — проверка порядка пуста"
    assert set(exception_ids) <= set(old_ids)
    assert exception_ids == [i for i in old_ids if i in set(exception_ids)]
    rows = run_with_deadline(lambda: modules_for(Tree(_ROOT, _PINNED)), 120)
    ids = [row["id"] for row in rows]
    assert ids[-len(exception_ids) :] == exception_ids
    assert len(ids) == len(set(ids))


# скорость — одноразовая приёмка (медиана 0,103 с, 2026-11-09); постоянно защищено счётчиком cat-file
# (test_modules_for_uses_exactly_two_git_cat_file_calls)
