"""Слепые приёмочные тесты `status.stale` / `status.frozen` паспорта символа (Task 4.2b-1, stage 2, RED до кода).

Purpose: четыре сценария REDS 1-4 (`stale` по рабочему дереву, `stale: null`, цепочка шапок `FREEZE`, текстовые строки
    `status`) плюс отдельные оговорки DESIGN 1-4: пути `bases`/`twins`/`subclasses`, имена с пробелом и кириллицей,
    граница юнита у цепочки, вход через CLI. Контракт — докстринг модуля `scripts/atlas/passport.py` (раздел
    `status`, образцы текста) и файл задачи `plans/2026-11-06_atlas-passport/tasks/4.2b-1.md`; реализации stale/frozen
    при записи тестов нет (INTERFACE: `status.stale` и `status.frozen` равны `null`, текст со старым хвостом).
Public API: тесты test_*; помощники `_commit`, `_build`, `_render`, `_lines` для `test_passport_schema.py`.
Stability: lite

Фикстуры — мини-репозитории git во `tmp_path` (`repo` из conftest + `core.autocrlf=false`, файлы с `\\n`). Номера строк
`where` — литералы, пересчитанные по тексту фикстуры вручную. Вызовы идут в daemon-потоке с дедлайном
(`run_with_deadline`). Ожидаемые значения — литералы, не выводятся из кода под тестом. Приватные `_stale`/`_frozen`
не вызываются: только `build_passport`, `render_text` и CLI.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from scripts.atlas.tests.conftest import GitRepo, RepoFactory, run_with_deadline
from scripts.atlas.tests.test_modules_roots_4_4 import _yaml

__all__: list[str] = []

DEADLINE_S = 120.0


# ---------------------------------------------------------------- помощники


def _put(repo: GitRepo, rel: str, text: str) -> None:
    target = repo.path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(text.encode("utf-8"))  # байты: переводы строк ровно `\n` на любой ОС


def _commit(repo: GitRepo, files: dict[str, str]) -> str:
    repo.git("config", "core.autocrlf", "false")
    repo.git("config", "init.defaultBranch", "main")
    _put(repo, ".gitignore", "data/\n")  # кэш фактов `data/atlas.sqlite` не должен попасть в коммит и в `git diff`
    for rel, text in files.items():
        _put(repo, rel, text)
    return repo.commit("fixture")


def _build(repo: GitRepo, ident: str, ref: str = "HEAD") -> dict:
    from scripts.atlas.passport import build_passport

    return run_with_deadline(lambda: build_passport(repo.path, ref, ident), DEADLINE_S)


def _build_at(root: Path, ident: str, ref: str = "HEAD") -> dict:
    from scripts.atlas.passport import build_passport

    return run_with_deadline(lambda: build_passport(root, ref, ident), DEADLINE_S)


def _render(passport: dict, **kwargs: Any) -> str:
    from scripts.atlas.passport import render_text

    return run_with_deadline(lambda: render_text(passport, **kwargs), DEADLINE_S)


def _lines(text: str) -> list[str]:
    return [line.rstrip() for line in text.splitlines()]


def _append(repo: GitRepo, rel: str, tail: str = "# edit\n") -> None:
    with (repo.path / rel).open("ab") as fh:
        fh.write(tail.encode("utf-8"))


def _status_at(lines: list[str]) -> int:
    hits = [i for i, line in enumerate(lines) if line.startswith("status:")]
    assert len(hits) == 1, f"строк `status:` — {len(hits)}: {hits}"
    return hits[0]


# ---------------------------------------------------------------- 1. stale: пути паспорта, правка в рабочем дереве

_STALE = {
    "pkg/__init__.py": "",
    "pkg/lib.py": "def target(a):\n    return a\n",
    "pkg/imp.py": "from pkg.lib import target  # noqa: F401\n",
    "pkg/caller.py": "from pkg.lib import target\n\n\ndef go():\n    target(1)\n",
    "pkg/unrelated.py": "X = 1\n",
    "tests/__init__.py": "",
    "tests/test_t.py": "from pkg.lib import target\n\n\ndef test_t():\n    target()\n",
}
_TARGET = "pkg/lib.py::target"


def test_stale_lists_changed_paths(repo: GitRepo) -> None:
    """`status.stale` — пути паспорта (`path`, `where` связей, `checks.tests`), чьё содержимое в рабочем дереве
    отличается от `sha`. Чисто -> `[]`; тот же текст, но новый mtime -> `[]`; правка файла связи и файла теста (не
    `path`) -> они в списке, посторонний файл — нет; `path` идёт первым; удалённый файл тоже в списке; порядок —
    как пути в паспорте."""
    _commit(repo, _STALE)
    base = _build(repo, _TARGET)
    assert any(t["where"].startswith("tests/test_t.py:") for t in base["checks"]["tests"])  # предусловие фикстуры
    assert {e["where"].split(":")[0] for e in base["links"]["used_by"]} == {
        "pkg/imp.py",
        "pkg/caller.py",
        "tests/test_t.py",
    }

    assert base["status"]["stale"] == []  # чистый репозиторий: искали, не нашли (не null)

    _put(repo, "pkg/caller.py", _STALE["pkg/caller.py"])  # тот же текст: содержимое не изменилось
    assert _build(repo, _TARGET)["status"]["stale"] == []

    _append(repo, "pkg/caller.py")  # файл связи (`call_sites`, `used_by`)
    _append(repo, "tests/test_t.py")  # файл `checks.tests`
    _append(repo, "pkg/unrelated.py")  # не в паспорте
    stale = _build(repo, _TARGET)["status"]["stale"]
    assert stale == ["pkg/caller.py", "tests/test_t.py"]  # `path` (pkg/lib.py) не правили; unrelated.py нет

    _append(repo, "pkg/imp.py")
    _append(repo, "pkg/lib.py")  # теперь правлен и `path`
    stale = _build(repo, _TARGET)["status"]["stale"]
    assert stale == ["pkg/lib.py", "pkg/caller.py", "pkg/imp.py", "tests/test_t.py"]  # `path` первый; без повторов

    repo.git("checkout", "--", ".")  # дерево снова чисто
    (repo.path / "tests" / "test_t.py").unlink()
    assert _build(repo, _TARGET)["status"]["stale"] == ["tests/test_t.py"]  # удалён -> отличается от `sha`


def test_stale_reads_only_worktree_not_the_passport_itself(repo: GitRepo) -> None:
    """Рабочее дерево читает только `stale`: правка файла символа не меняет остальной паспорт (`line`, `signature`,
    `links`) — они из ревизии `sha`."""
    _commit(repo, _STALE)
    clean = _build(repo, _TARGET)
    _put(repo, "pkg/lib.py", "# сдвиг\n# сдвиг\ndef target(a, b, c):\n    return a\n")  # в рабочем дереве, не в коммите
    _put(repo, "pkg/caller.py", "X = 2\n")  # связь пропала в рабочем дереве
    dirty = _build(repo, _TARGET)
    assert dirty["status"]["stale"] == ["pkg/lib.py", "pkg/caller.py"]
    clean["status"]["stale"] = dirty["status"]["stale"]
    assert dirty == clean  # всё прочее — из ревизии


_STALE_CLS = {
    "pkg/__init__.py": "",
    "pkg/proto.py": (
        "from typing import Protocol\n\n\nclass ITwo(Protocol):\n    def read(self): ...\n    def write(self): ...\n"
    ),
    "pkg/duck.py": "class Duck:\n    def write(self): ...\n    def read(self): ...\n",
    "pkg/base.py": "class Base:\n    pass\n",
    "pkg/child.py": "from pkg.base import Base\n\n\nclass Child(Base):\n    pass\n",
}


def test_stale_covers_twins_bases_and_subclasses_paths(repo: GitRepo) -> None:
    """DESIGN 1: пути берутся и из `structural.twins` (`путь::qualname`), и из `bases`, и из `subclasses`. Правка
    ТОЛЬКО файла двойника / основы / наследника -> он в `stale` (файл самого символа не правлен)."""
    _commit(repo, _STALE_CLS)
    twin = _build(repo, "pkg/proto.py::ITwo")
    assert twin["links"]["structural"]["twins"] == ["pkg/duck.py::Duck"]  # предусловие
    assert twin["status"]["stale"] == []
    child = _build(repo, "pkg/child.py::Child")
    assert child["links"]["bases"][0]["where"].startswith("pkg/base.py:")  # предусловие
    base = _build(repo, "pkg/base.py::Base")
    assert base["links"]["subclasses"][0]["where"].startswith("pkg/child.py:")  # предусловие

    _append(repo, "pkg/duck.py")
    assert _build(repo, "pkg/proto.py::ITwo")["status"]["stale"] == ["pkg/duck.py"]  # путь из `twins`, без `::Duck`
    _append(repo, "pkg/base.py")
    assert _build(repo, "pkg/child.py::Child")["status"]["stale"] == ["pkg/base.py"]  # путь из `bases`
    repo.git("checkout", "--", ".")
    _append(repo, "pkg/child.py")
    assert _build(repo, "pkg/base.py::Base")["status"]["stale"] == ["pkg/child.py"]  # путь из `subclasses`


_STALE_NAMES = {
    "pkg/__init__.py": "",
    "pkg/lib.py": "def target(a):\n    return a\n",
    "pkg/вызов один.py": "from pkg.lib import target\n\n\ndef ru():\n    target(2)\n",
    "pkg/unrelated.py": "X = 1\n",
}


def test_stale_path_with_space_and_cyrillic_is_listed_verbatim(repo: GitRepo) -> None:
    """Имя с пробелом и кириллицей приходит в `stale` как есть (не в кавычках и не с `\\321\\202…`): `git diff -z`."""
    _commit(repo, _STALE_NAMES)
    _append(repo, "pkg/вызов один.py")
    assert _build(repo, _TARGET)["status"]["stale"] == ["pkg/вызов один.py"]


# ---------------------------------------------------------------- 2. stale: null — не искали


def test_stale_null_when_sha_not_head_or_git_diff_fails(repo: GitRepo, repo_factory: RepoFactory) -> None:
    """`stale` = `null`, если `sha` != HEAD корня (ветка, sha, тег на старой ревизии) и если `git diff` упал (bare-клон
    без рабочего дерева); `sha` == HEAD (в т.ч. по имени ветки и тега) -> список. Правка в рабочем дереве при `sha` !=
    HEAD не превращает `null` в список. Переименование в рабочем дереве: старое имя — в списке."""
    first = _commit(repo, _STALE)
    _put(repo, "pkg/lib.py", _STALE["pkg/lib.py"] + "\n\ndef extra():\n    return 0\n")
    head = repo.commit("second")
    assert head != first
    repo.git("branch", "old", first)
    repo.git("tag", "v2", head)

    at_head = _build(repo, _TARGET)
    assert at_head["sha"] == head and at_head["status"]["stale"] == []
    assert _build(repo, _TARGET, ref="main")["status"]["stale"] == []  # имя ветки, что указывает на HEAD
    assert _build(repo, _TARGET, ref="v2")["status"]["stale"] == []  # тег на HEAD

    old = _build(repo, _TARGET, ref=first)
    assert old["sha"] == first and old["status"]["stale"] is None  # чужая ревизия: не искали, а не `[]`
    assert _build(repo, _TARGET, ref="old")["status"]["stale"] is None  # ветка на старой ревизии
    _append(repo, "pkg/caller.py")
    assert _build(repo, _TARGET, ref=first)["status"]["stale"] is None  # правка есть, но `sha` != HEAD
    assert _build(repo, _TARGET)["status"]["stale"] == ["pkg/caller.py"]
    repo.git("checkout", "--", ".")

    bare = repo_factory.base / "bare.git"
    repo.git("clone", "-q", "--bare", str(repo.path), str(bare))
    from_bare = _build_at(bare, _TARGET)  # HEAD разрешается, `git diff` без рабочего дерева падает
    assert from_bare["sha"] == head
    assert from_bare["status"]["stale"] is None

    repo.git("mv", "pkg/caller.py", "pkg/renamed.py")  # переименование: у `sha` файла `renamed.py` нет
    assert _build(repo, _TARGET)["status"]["stale"] == ["pkg/caller.py"]  # старое имя в списке, нового нет в паспорте


# ---------------------------------------------------------------- 3. frozen: ближайшие шапки FREEZE

_CHAIN = {
    "modules.yaml": _yaml(("lib/", "framework", "fx/")),
    "lib/a/__init__.py": '"""FREEZE 2026-01-01: пакет a заморожен\n\nПубличный вход юнита.\n"""\n',
    "lib/a/b/__init__.py": '"""Пакет b.\n\nFREEZE 2026-02-02: не трогать b\n"""\n',
    "lib/a/b/m.py": (
        '"""\n'  # 1: докстринг модуля начинается с `"""` и перевода строки
        "Модуль m.\n"  # 2
        "\n"  # 3
        "FREEZE 2026-03-03: файл m заморожен\n"  # 4
        "Заметка, см. FREEZE 2026-09-09: это не шапка\n"  # 5: FREEZE не в начале строки
        "FREEZE 2026-03-04: вторая шапка файла\n"  # 6
        '"""\n'  # 7
        "\n"  # 8
        "\n"  # 9
        "class K:\n"  # 10
        '    """Класс K."""\n'  # 11
        "\n"  # 12
        "    def meth(self):\n"  # 13
        "        return 1\n"  # 14
        "\n"  # 15
        "\n"  # 16
        "def f():\n"  # 17
        "    return 2\n"  # 18
    ),
    "lib/c/__init__.py": '"""Юнит c."""\n',
    "lib/c/n.py": "class Plain:\n    pass\n",
    "lib/d/__init__.py": '"""FREEZE 2026-07-07: чужой юнит"""\n',
    "lib/e/__init__.py": '"""Юнит e.\nFREEZE 2026-05-05: только пакет\n"""\n',
    "lib/e/x.py": "def only_pkg():\n    return 1\n",
    "lib/f/__init__.py": '"""Юнит f."""\n',
    "lib/f/y.py": '"""Файл y.\nFREEZE 2026-06-06: только файл\n"""\n\n\ndef only_file():\n    return 1\n',
}
_FROZEN_K = [  # сначала шапки файла символа (по строке), затем `__init__.py` от ближнего пакета к дальнему
    {"date": "2026-03-03", "text": "файл m заморожен", "where": "lib/a/b/m.py:4"},
    {"date": "2026-03-04", "text": "вторая шапка файла", "where": "lib/a/b/m.py:6"},
    {"date": "2026-02-02", "text": "не трогать b", "where": "lib/a/b/__init__.py:3"},
    {"date": "2026-01-01", "text": "пакет a заморожен", "where": "lib/a/__init__.py:1"},
]


def test_frozen_nearest_header_chain(repo: GitRepo) -> None:
    """`frozen` — шапки `FREEZE YYYY-MM-DD: текст` докстринга файла символа, затем `__init__.py` цепочки (ближний
    пакет первым). `where` — точный `путь:строка` сырой строки (докстринг с `\"\"\"` + перевод строки; FREEZE после
    другой строки; FREEZE на первой строке сразу после `\"\"\"`). `FREEZE` не в начале строки — не шапка. Класс и метод
    наследуют цепочку файла. Второй (тёплый, из `scan_cache`) вызов даёт то же. Шапок нет — `[]`; чужой юнит не
    входит; только пакет / только файл — по одной записи."""
    _commit(repo, _CHAIN)
    for ident in ("lib/a/b/m.py::K", "lib/a/b/m.py::K.meth", "lib/a/b/m.py::f"):
        cold = _build(repo, ident)["status"]["frozen"]
        assert cold == _FROZEN_K, ident
        warm = _build(repo, ident)["status"]["frozen"]  # кэш фактов `data/atlas.sqlite` уже записан
        assert warm == _FROZEN_K, f"{ident}: тёплый вызов"
    assert (repo.path / "data" / "atlas.sqlite").is_file()  # второй вызов шёл через кэш (модульный докстринг)

    assert _build(repo, "lib/c/n.py::Plain")["status"]["frozen"] == []  # шапок нет нигде; lib/d чужой
    assert _build(repo, "lib/e/x.py::only_pkg")["status"]["frozen"] == [
        {"date": "2026-05-05", "text": "только пакет", "where": "lib/e/__init__.py:2"}
    ]
    assert _build(repo, "lib/f/y.py::only_file")["status"]["frozen"] == [
        {"date": "2026-06-06", "text": "только файл", "where": "lib/f/y.py:2"}
    ]


def test_frozen_chain_stops_at_unit_boundary(repo: GitRepo) -> None:
    """Цепочка идёт до юнита (как `interface.all`), не выше: `lib/__init__.py` над юнитом `lib/a` в неё не входит."""
    files = {
        "modules.yaml": _yaml(("lib/", "framework", "fx/")),
        "lib/__init__.py": '"""FREEZE 2026-12-12: над юнитом"""\n',
        "lib/a/__init__.py": '"""FREEZE 2026-01-01: юнит a"""\n',
        "lib/a/sub/__init__.py": '"""FREEZE 2026-02-02: пакет sub"""\n',
        "lib/a/sub/impl.py": "class W:\n    pass\n",
    }
    _commit(repo, files)
    assert _build(repo, "lib/a/sub/impl.py::W")["status"]["frozen"] == [
        {"date": "2026-02-02", "text": "пакет sub", "where": "lib/a/sub/__init__.py:1"},
        {"date": "2026-01-01", "text": "юнит a", "where": "lib/a/__init__.py:1"},
    ]


# ---------------------------------------------------------------- 4. текст: строки stale / frozen после `status:`

_TXT = {
    "pkg/__init__.py": "",
    "pkg/lib.py": (
        '"""Модуль.\n\nTier: core\n"""\n\n\ndef target(a: int) -> int:\n    """Цель.\n\n    Второй."""\n    return a\n'
    ),
    "pkg/caller.py": "from pkg.lib import target\n\n\ndef go():\n    target(1)\n",
}


def test_status_text_lines(repo: GitRepo, repo_factory: RepoFactory) -> None:
    """Хвост `; stale …; frozen …` ушёл из строки `status:` (остались `tier`, `doc_missing`, `dynamic`); следом, с
    отступом в 2 пробела: `  stale: —` (`[]`), `  stale: не искали` (`null`), `  stale: a.py, b.py` (без среза даже
    при `budget=1`), `  frozen: —` или по строке на шапку `  frozen: <date> <text> (<путь:строка>)`. Первая строка
    `purpose` не меняется."""
    _commit(repo, _TXT)
    clean = _build(repo, "pkg/lib.py::target")
    lines = _lines(_render(clean))
    i = _status_at(lines)
    assert lines[i] == "status: tier core; doc_missing нет; dynamic —"  # tier/doc_missing/dynamic остались, хвоста нет
    assert lines[i + 1] == "  stale: —"
    assert lines[i + 2] == "  frozen: —"
    assert "purpose: Цель." in lines  # первая строка purpose как была
    assert not any("; stale" in line or "; frozen" in line for line in lines)

    for budget in (1, 40):  # служебный минимум: строки не режутся
        small = _lines(_render(clean, budget=budget))
        j = _status_at(small)
        assert small[j + 1 : j + 3] == ["  stale: —", "  frozen: —"], budget
    full = _lines(_render(clean, full=True))
    assert full[_status_at(full) + 1] == "  stale: —"

    unsearched = copy.deepcopy(clean)
    unsearched["status"]["stale"] = None
    got = _lines(_render(unsearched))
    k = _status_at(got)
    assert got[k + 1] == "  stale: не искали" and got[k + 2] == "  frozen: —"

    two = copy.deepcopy(clean)
    two["status"]["stale"] = ["a.py", "b.py"]
    got = _lines(_render(two))
    assert got[_status_at(got) + 1] == "  stale: a.py, b.py"

    many = copy.deepcopy(clean)
    many["status"]["stale"] = [f"pkg/m{n:02d}.py" for n in range(1, 13)]
    got = _lines(_render(many, budget=1))
    expected = (
        "  stale: pkg/m01.py, pkg/m02.py, pkg/m03.py, pkg/m04.py, pkg/m05.py, pkg/m06.py, "
        "pkg/m07.py, pkg/m08.py, pkg/m09.py, pkg/m10.py, pkg/m11.py, pkg/m12.py"
    )
    assert got[_status_at(got) + 1] == expected  # без среза

    heads = copy.deepcopy(clean)
    heads["status"]["frozen"] = [
        {"date": "2026-03-03", "text": "файл m заморожен", "where": "lib/a/b/m.py:4"},
        {"date": "2026-02-02", "text": "не трогать b", "where": "lib/a/b/__init__.py:3"},
    ]
    for budget in (1, 40):
        got = _lines(_render(heads, budget=budget))
        n = _status_at(got)
        assert got[n + 1] == "  stale: —", budget
        assert got[n + 2] == "  frozen: 2026-03-03 файл m заморожен (lib/a/b/m.py:4)", budget
        assert got[n + 3] == "  frozen: 2026-02-02 не трогать b (lib/a/b/__init__.py:3)", budget

    _append(repo, "pkg/caller.py")  # сквозной случай: правка файла связи -> строка `stale` реального паспорта
    live = _lines(_render(_build(repo, "pkg/lib.py::target")))
    assert live[_status_at(live) + 1] == "  stale: pkg/caller.py"

    frozen_repo = repo_factory.create("frozen")  # сквозной случай: шапки из докстринга файла и пакета
    _commit(frozen_repo, _CHAIN)
    shown = _lines(_render(_build(frozen_repo, "lib/a/b/m.py::K")))
    s = _status_at(shown)
    assert shown[s] == "status: tier нет шапки; doc_missing нет; dynamic —"
    assert shown[s + 1] == "  stale: —"
    assert shown[s + 2 : s + 6] == [
        "  frozen: 2026-03-03 файл m заморожен (lib/a/b/m.py:4)",
        "  frozen: 2026-03-04 вторая шапка файла (lib/a/b/m.py:6)",
        "  frozen: 2026-02-02 не трогать b (lib/a/b/__init__.py:3)",
        "  frozen: 2026-01-01 пакет a заморожен (lib/a/__init__.py:1)",
    ]


# ---------------------------------------------------------------- CLI


def test_cli_ref_json_and_passport_carry_stale_and_frozen(repo: GitRepo, atlas: Any) -> None:
    """`ref <id> --format json` и `--format passport` несут те же `stale`/`frozen`, что `build_passport`: чисто ->
    `stale: []` и шапки цепочки; после правки файла связи — путь в `stale` и строка `  stale: …` в тексте."""
    _commit(repo, {**_CHAIN, "lib/a/b/user.py": "from lib.a.b.m import f\n\n\ndef go():\n    f()\n"})
    out = atlas(repo, "ref", "lib/a/b/m.py::K", "--format", "json")
    assert out.code == 0, out.err
    status = json.loads(out.out)[0]["status"]
    assert status["stale"] == [] and status["frozen"] == _FROZEN_K

    _append(repo, "lib/a/b/m.py")  # файл символа правлен в рабочем дереве
    text = atlas(repo, "ref", "lib/a/b/m.py::f", "--format", "passport")
    assert text.code == 0, text.err
    lines = _lines(text.out)
    i = _status_at(lines)
    assert lines[i + 1].startswith("  stale: lib/a/b/m.py")
    assert lines[i + 2] == "  frozen: 2026-03-03 файл m заморожен (lib/a/b/m.py:4)"
