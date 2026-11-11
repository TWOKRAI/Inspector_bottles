"""Приёмочные тесты строки `классы:` вида `index` (Task IDX1, слепой RED до кода).

Purpose: `python -m scripts.atlas index` печатает после строки `id — purpose` и строки интерфейсов строку
    `  классы: A, B, C` — публичные классы верхнего уровня нетестовых `.py` юнита слоёв framework, services,
    plugins, tools: по алфавиту `str`, без повторов, без классов, уже напечатанных в строке интерфейсов (первые 5);
    имена за «… ещё N» входят. REDS 1-9: порядок строк, реэкспорт, «… ещё N», юнит без классов, вложенные юниты и
    файловые `paths`, исключения (тесты, вложенность, функция, `if`), белый список слоёв, сбойные файлы (синтаксис,
    не utf-8, > MAX_BLOB_BYTES, BOM), порядок и дубли, PYTHONHASHSEED.
Public API: нет (только test_*).
Stability: lite

Спецификация — только plans/2026-11-06_atlas-passport/tasks/IDX1.md (DESIGN 1-5, REDS 1-9). Мини-репозиторий через
`repo_factory` + `modules.yaml`; слой юнита задан ЯВНО (умолчание `scripts` вне охвата). Каждый тест сравнивает ВЕСЬ
вывод `index` списком строк с литералом, в том числе положительный якорь (строка `классы:` соседа). Файлы с
особыми байтами (BOM, не utf-8, > 1 МиБ) пишутся байтами. Все вызовы git, main() и subprocess идут через дедлайн
conftest.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts.atlas.tests.conftest import GitRepo, RepoFactory, run_with_deadline

__all__: list[str] = []

_REFS = ("--ref", "main", "--main-ref", "main")
_ROOT = Path(__file__).resolve().parents[3]
_HEADER = "# Индекс проекта — собран командой `python -m scripts.atlas index --write`, руками не править"
_NO_PURPOSE = "нет purpose в modules.yaml"
MAX_BLOB = 1_048_576

# ---------------------------------------------------------------- хелперы


def _yaml(rows: list[tuple[str, list[str], str]]) -> str:
    """rows: (id, paths, layer); tier null, docs [], parent null; порядок строк = порядок в yaml."""
    text = "version: 1\nmodules:\n"
    for module_id, paths, layer in rows:
        quoted = ", ".join(f'"{p}"' for p in paths)
        text += f"  - id: {module_id}\n    paths: [{quoted}]\n    layer: {layer}\n"
        text += "    tier: null\n    docs: []\n    parent: null\n"
    return text


def _put(repo: GitRepo, rel: str, data: bytes | str) -> None:
    """Файл с точными байтами (без перевода строк ОС)."""
    target = repo.path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)


def _repo(
    factory: RepoFactory,
    name: str,
    rows: list[tuple[str, list[str], str]],
    files: dict[str, bytes | str],
) -> GitRepo:
    repo = factory.create(name)
    exclude = repo.path / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    exclude.write_text("data/\n", encoding="utf-8")
    _put(repo, "modules.yaml", _yaml(rows))
    for rel, data in files.items():
        _put(repo, rel, data)
    repo.commit("init")
    return repo


def _index(atlas: Any, repo: GitRepo) -> list[str]:
    res = atlas(repo, "index", *_REFS)
    assert res.code == 0, res.err
    return res.out.splitlines()


def _m(*lines: str) -> list[str]:
    """Ожидаемый вывод для одного юнита `m`: шапка, `m — …`, затем строки юнита."""
    return [_HEADER, f"m — {_NO_PURPOSE}", *lines]


def _cls(*names: str) -> str:
    return "  классы: " + ", ".join(names)


def _one_unit(factory: RepoFactory, name: str, files: dict[str, bytes | str], layer: str = "framework") -> GitRepo:
    return _repo(factory, name, [("m", ["m/"], layer)], files)


# ---------------------------------------------------------------- RED 1: публичные классы рядом с интерфейсами


def test_public_classes_follow_the_interface_line_private_is_skipped(repo_factory, atlas):
    repo = _one_unit(
        repo_factory,
        "r1",
        {
            "m/interfaces.py": (
                '__all__ = ["IFoo"]\n\n\nclass IFoo:\n    def a(self) -> None:\n        pass\n\n'
                "    def b(self) -> None:\n        pass\n"
            ),
            "m/impl.py": "class Foo:\n    pass\n\n\nclass _Hidden:\n    pass\n\n\nclass Bar:\n    pass\n",
        },
    )
    assert _index(atlas, repo) == _m("  IFoo (2)", _cls("Bar", "Foo"))


# ---------------------------------------------------------------- RED 2: реэкспорт вычитается, определение остаётся


def test_reexported_class_is_printed_once_without_counter_and_not_repeated_in_classes(repo_factory, atlas):
    repo = _one_unit(
        repo_factory,
        "r2",
        {
            "m/interfaces.py": 'from .impl import Foo\n\n__all__ = ["Foo"]\n',
            "m/impl.py": "class Foo:\n    def go(self) -> None:\n        pass\n\n\nclass Bar:\n    pass\n",
        },
    )
    assert _index(atlas, repo) == _m("  Foo", _cls("Bar"))


# ---------------------------------------------------------------- RED 3: имена за «… ещё N» входят в классы


def test_interface_names_hidden_behind_more_go_into_classes_line(repo_factory, atlas):
    counts = {"I3": 5, "I7": 1, "I1": 7, "I6": 2, "I5": 3, "I2": 6, "I4": 4}  # порядок файла перемешан
    body = ""
    for name, count in counts.items():
        methods = "".join(f"    def m{k}(self) -> None:\n        pass\n\n" for k in range(count))
        body += f"\n\nclass {name}:\n{methods}"
    repo = _one_unit(
        repo_factory,
        "r3",
        {"m/interfaces.py": '__all__ = ["I1", "I2", "I3", "I4", "I5", "I6", "I7"]\n' + body},
    )
    assert _index(atlas, repo) == _m("  I1 (7), I2 (6), I3 (5), I4 (4), I5 (3), … ещё 2", "  классы: I6, I7")


# ---------------------------------------------------------------- RED 4: нет классов — нет строки


def test_unit_with_only_functions_has_no_classes_line_neighbour_has(repo_factory, atlas):
    repo = _repo(
        repo_factory,
        "r4a",
        [("m", ["m/"], "framework"), ("n", ["n/"], "framework")],
        {"m/funcs.py": "def run():\n    return 1\n\n\nVALUE = 2\n", "n/impl.py": "class Keep:\n    pass\n"},
    )
    assert _index(atlas, repo) == [_HEADER, f"m — {_NO_PURPOSE}", f"n — {_NO_PURPOSE}", _cls("Keep")]


def test_unit_without_interfaces_file_still_gets_classes_line_without_interface_line(repo_factory, atlas):
    repo = _one_unit(repo_factory, "r4b", {"m/impl.py": "class Solo:\n    pass\n"})
    assert _index(atlas, repo) == _m(_cls("Solo"))


# ---------------------------------------------------------------- RED 5: вложенные юниты и файловые paths


def test_nested_unit_and_file_paths_unit_take_their_own_classes(repo_factory, atlas):
    repo = _repo(
        repo_factory,
        "r5",
        [("m", ["m/"], "framework"), ("m/sub", ["m/sub/"], "framework"), ("ex", ["m/special.py"], "framework")],
        {
            "m/keep.py": "class Keep:\n    pass\n",
            "m/sub/deep.py": "class Deep:\n    pass\n",
            "m/special.py": "class Special:\n    pass\n",
        },
    )
    assert _index(atlas, repo) == [
        _HEADER,
        f"m — {_NO_PURPOSE}",
        _cls("Keep"),
        f"m/sub — {_NO_PURPOSE}",
        _cls("Deep"),
        f"ex — {_NO_PURPOSE}",
        _cls("Special"),
    ]


# ---------------------------------------------------------------- RED 6: что в классы не берётся

_KEEP = "class Keep:\n    pass\n"
_EXCLUDED: dict[str, tuple[str, str]] = {  # id -> (путь файла, содержимое); в юните ещё m/keep.py с `Keep`
    "test_file": ("m/tests/test_x.py", "class TestHidden:\n    pass\n"),
    "nested": ("m/nested.py", "class _Outer:\n    class Inner:\n        pass\n"),
    "inside_function": ("m/func.py", "def make():\n    class Local:\n        pass\n\n    return Local\n"),
    "type_checking_if": (
        "m/typing_only.py",
        "from typing import TYPE_CHECKING\n\nif TYPE_CHECKING:\n    class Typed:\n        pass\n",
    ),
    # Дополнительно к четырём параметрам Task: DESIGN п. 3 прямо перечисляет «под любым if, в try».
    "plain_if": ("m/cond.py", "import os\n\nif os.name:\n    class Cond:\n        pass\n"),
    "try_body": ("m/guard.py", "try:\n    class Guarded:\n        pass\nexcept ImportError:\n    pass\n"),
}


@pytest.mark.parametrize("case", list(_EXCLUDED))
def test_excluded_class_forms_leave_only_keep(repo_factory, atlas, case):
    rel, text = _EXCLUDED[case]
    repo = _one_unit(repo_factory, f"r6_{case}", {"m/keep.py": _KEEP, rel: text})
    assert _index(atlas, repo) == _m(_cls("Keep"))


# ---------------------------------------------------------------- RED 7: белый список слоёв


@pytest.mark.parametrize("layer", ["prototype", "scripts", "docs"])
def test_out_of_scope_layer_has_no_classes_line_framework_neighbour_has(repo_factory, atlas, layer):
    repo = _repo(
        repo_factory,
        f"r7_{layer}",
        [("m", ["m/"], "framework"), ("n", ["n/"], layer)],
        {"m/keep.py": _KEEP, "n/hidden.py": "class Hidden:\n    pass\n"},
    )
    assert _index(atlas, repo) == [_HEADER, f"m — {_NO_PURPOSE}", _cls("Keep"), f"n — {_NO_PURPOSE}"]


@pytest.mark.parametrize("layer", ["services", "plugins", "tools"])
def test_in_scope_layer_gets_classes_line(repo_factory, atlas, layer):
    repo = _one_unit(repo_factory, f"r7_{layer}", {"m/seen.py": "class Seen:\n    pass\n"}, layer=layer)
    assert _index(atlas, repo) == _m(_cls("Seen"))


# ---------------------------------------------------------------- RED 8: сбойные файлы не роняют index


def _big(size: int) -> bytes:
    head = b"class Big:\n    pass\n"
    return head + b"#" * (size - len(head) - 1) + b"\n"


_BAD_FILES: dict[str, tuple[str, bytes, list[str]]] = {  # id -> (путь, байты, ожидаемые классы)
    "syntax_error": ("m/bad.py", b"class Before:\n    pass\n\n\ndef broken(:\n    pass\n", ["Keep"]),
    "not_utf8": ("m/latin.py", b"class Latin:\n    x = '\xff'\n", ["Keep"]),
    "over_limit": ("m/big.py", _big(MAX_BLOB + 1), ["Keep"]),
    "bom": ("m/bom.py", b"\xef\xbb\xbfclass Bomm:\n    pass\n", ["Bomm", "Keep"]),
    # Граница: ровно MAX_BLOB_BYTES байт разбирается (дополнительно к REDS: DESIGN п. 2 «размер > MAX_BLOB_BYTES»).
    "at_limit": ("m/edge.py", _big(MAX_BLOB), ["Big", "Keep"]),
}


@pytest.mark.parametrize("case", list(_BAD_FILES))
def test_failing_file_is_skipped_and_index_exits_zero(repo_factory, atlas, case):
    rel, data, expected = _BAD_FILES[case]
    if case in ("over_limit", "at_limit"):
        assert len(data) == (MAX_BLOB + 1 if case == "over_limit" else MAX_BLOB)  # размер фикстуры задан точно
    repo = _one_unit(repo_factory, f"r8_{case}", {"m/keep.py": _KEEP, rel: data})
    res = atlas(repo, "index", *_REFS)
    assert res.code == 0, res.err
    assert res.out.splitlines() == _m(_cls(*expected))


# ---------------------------------------------------------------- RED 9: порядок, дубли, место, детерминизм


def test_classes_sorted_by_str_uppercase_before_lowercase(repo_factory, atlas):
    repo = _one_unit(
        repo_factory, "r9a", {"m/mix.py": "class b:\n    pass\n\n\nclass B:\n    pass\n\n\nclass a:\n    pass\n"}
    )
    assert _index(atlas, repo) == _m(_cls("B", "a", "b"))


def test_class_in_two_files_of_unit_is_printed_once(repo_factory, atlas):
    repo = _one_unit(
        repo_factory,
        "r9b",
        {"m/one.py": "class Dup:\n    pass\n", "m/two.py": "class Dup:\n    pass\n\n\nclass Keep:\n    pass\n"},
    )
    assert _index(atlas, repo) == _m(_cls("Dup", "Keep"))


def test_class_in_init_and_class_outside_all_are_counted(repo_factory, atlas):
    repo = _one_unit(
        repo_factory,
        "r9c",
        {
            "m/__init__.py": "class InInit:\n    pass\n",
            "m/mod.py": '__all__ = ["Listed"]\n\n\nclass Listed:\n    pass\n\n\nclass Outside:\n    pass\n',
        },
    )
    assert _index(atlas, repo) == _m(_cls("InInit", "Listed", "Outside"))


def _class_file(*names: str) -> str:
    return "\n\n".join(f"class {name}:\n    pass\n" for name in names)


_MANY = {  # имена в файлах идут против алфавита
    "m/a.py": _class_file("Zulu", "Yankee", "Xray", "Whiskey"),
    "m/b.py": _class_file("Victor", "Uniform", "Tango", "Sierra"),
    "m/c.py": _class_file("Romeo", "Quebec", "Papa", "Oscar"),
    "m/d.py": _class_file("November", "Mike", "Lima", "Kilo"),
}
_MANY_EXPECTED = _m(
    "  классы: Kilo, Lima, Mike, November, Oscar, Papa, Quebec, Romeo, "
    "Sierra, Tango, Uniform, Victor, Whiskey, Xray, Yankee, Zulu"
)


def _cli(repo: GitRepo, seed: str) -> bytes:
    env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(_ROOT), "PYTHONUTF8": "1"}
    proc = run_with_deadline(
        lambda: subprocess.run(
            [sys.executable, "-m", "scripts.atlas", "index", *_REFS],
            cwd=repo.path,
            env=env,
            capture_output=True,
            check=False,
        )
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    return proc.stdout


def test_output_is_byte_equal_under_different_hash_seeds(repo_factory):
    repo = _one_unit(repo_factory, "r9d", _MANY)
    first = _cli(repo, "0")
    assert first.decode("utf-8").splitlines() == _MANY_EXPECTED
    for seed in ("12345", "7"):
        shutil.rmtree(repo.path / "data", ignore_errors=True)  # каждый процесс — на свежей базе
        assert _cli(repo, seed) == first
