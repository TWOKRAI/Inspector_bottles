"""Слепые приёмочные тесты `build_map` и текста `map` (Task 4.2b-2, stage 2, RED до кода).

Purpose: REDS 1-4 задачи (члены юнита по `resolve`, ключи и значения обоих `kind`, `used_by` по юнитам-импортёрам,
    текст и срез по бюджету) плюс оговорки формы (`top` до 6 имён, `stale` > 5 путей, рантайм-записи, `exclude`,
    `frozen`, `doc_missing`, имена среза по `kind`). Контракт — файлы `plans/2026-11-06_atlas-passport/tasks/4.2b-2.md`
    и `map-form.md`, докстринги `scripts/atlas/passport.py` (модуль, `build_map`, `render_text`); реализации при записи
    тестов нет (`build_map` — заглушка `NotImplementedError`).
Public API: тесты test_*; помощники `_seed`, `_build`, `_render`, `_lines`, `_files_main`, `_full_text` для
    `test_passport_map_cli.py`.
Stability: lite

Фикстуры — мини-репозитории git во `tmp_path` (`repo` из conftest + `core.autocrlf=false`). Реестр юнитов — файл
`modules.yaml` ревизии (явные строки `modules:`; вложенный юнит и юниты из `roots:` — в тесте 1). Номера строк `where` —
маркеры `# @имя` в тексте фикстуры (`_at`), не значения из кода. Ожидаемые значения — литералы, не выводятся из кода под
тестом. Вызовы идут в daemon-потоке с дедлайном.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from scripts.atlas.tests.conftest import GitRepo, run_with_deadline
from scripts.atlas.tests.test_links import _at
from scripts.atlas.tests.test_modules_roots_4_4 import _yaml

__all__: list[str] = []

DEADLINE_S = 120.0
SECTIONS = ["purpose", "interface", "links", "runtime", "checks", "status"]
ENVELOPE = ["passport", "kind", "id", "path", "line", "sha", "scanner"]
SECTION_KEYS = {
    "purpose": ["text", "called_from", "called_from_more", "declared_at"],
    "interface": ["layer", "all", "signature", "members"],
    "links": ["used_by", "uses", "subclasses", "call_sites", "call_sites_unresolved", "bases", "structural"],
    "runtime": ["processes", "threads", "commands", "io"],
    "checks": ["findings", "tests"],
    "status": ["tier", "doc_missing", "dynamic", "stale", "frozen"],
}
# ключи, которые у `map` всегда `null` и в тексте не печатаются (map-form п. 3)
NULL_KEYS_NOT_IN_TEXT = (
    "declared_at",
    "called_from",
    "signature",
    "call_sites",
    "subclasses",
    "bases",
    "structural",
    "uses",
    "call_sites_unresolved",
    "processes",
    "findings",
)


# ---------------------------------------------------------------- помощники


def _commit(repo: GitRepo, files: dict[str, str]) -> str:
    repo.git("config", "core.autocrlf", "false")
    for rel, text in files.items():
        repo.write(rel, text)
    return repo.commit("fixture")


def _build(repo: GitRepo, target: str, ref: str = "HEAD", **kwargs: Any) -> dict:
    from scripts.atlas.passport import build_map

    return run_with_deadline(lambda: build_map(repo.path, ref, target, **kwargs), DEADLINE_S)


def _render(passport: dict, **kwargs: Any) -> str:
    from scripts.atlas.passport import render_text

    return run_with_deadline(lambda: render_text(passport, **kwargs), DEADLINE_S)


def _lines(text: str) -> list[str]:
    return [line.rstrip() for line in text.splitlines()]


def _stripped(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines()]


def _row(ident: str, path: str, *, tier: str = "null", docs: str = "", purpose: str = "") -> str:
    return (
        f"  - id: {ident}\n"
        f'    paths: ["{path}"]\n'
        "    layer: framework\n"
        f"    tier: {tier}\n"
        f"    docs: [{docs}]\n"
        "    parent: null\n"
        f'    purpose: "{purpose or ident}"\n'
    )


def _registry(*rows: str) -> str:
    return "version: 1\nmodules:\n" + "".join(rows)


# ---------------------------------------------------------------- фикстура «юнит u» (map-form п. 3)

_REG_MAIN = _registry(
    _row("u", "u/", tier="core", docs='"u/README.md"', purpose="Юнит u."),
    _row("v", "v/", purpose="Импортёр v."),
    _row("w", "w/", purpose="Импортёр w."),
)


def _files_main() -> dict[str, str]:
    """Юнит `u`: три prod-файла (`__init__` с `__all__`, `a`, `b`), тест-файл с 2 тестами и вспомогательный модуль
    без тестов; импортёры `v` (2 оператора в `v/x.py`, строки 3 и 4) и `w` (1 оператор через `u/__init__`,
    `w/y.py:5`)."""
    return {
        "modules.yaml": _REG_MAIN,
        "u/README.md": "# u\n",
        "u/__init__.py": '"""Пакет u."""\nfrom u.a import A, B\n\n__all__ = ["A", "B"]\n',
        "u/a.py": (
            '"""Модуль a."""\n\n\nclass A:  # @clsA\n    """Класс A."""\n\n\nclass B:  # @clsB\n    """Класс B."""\n'
        ),
        "u/b.py": (
            '"""Модуль b.\n\nTier: optional\n"""\n\n\n'
            "def run_b(x: int) -> int:  # @run_b\n    return x\n\n\n"
            "async def arun() -> None:  # @arun\n    return None\n\n\n"
            "def _hidden() -> None:  # @hidden\n    return None\n"
        ),
        "u/tests/test_a.py": "def test_one():\n    assert True\n\n\ndef test_two():\n    assert True\n",
        "u/tests/helpers.py": "def make():\n    return 1\n",
        "v/__init__.py": "",
        "v/x.py": '"""Импортёр v."""\n\nfrom u.a import A\nfrom u.a import B\n',
        "w/__init__.py": "",
        "w/y.py": '"""Импортёр w."""\n#\n#\n#\nfrom u import A\n',
    }


def _seed(repo: GitRepo, files: dict[str, str] | None = None) -> tuple[str, dict[str, str]]:
    """Фиксирует главную фикстуру с правками `files` (путь -> текст; `None` не бывает). Возвращает `(sha, файлы)`."""
    merged = {**_files_main(), **(files or {})}
    return _commit(repo, merged), merged


def _full_text(sha: str, scanner: str) -> str:
    """Полный текст юнита `u` (без среза): образец map-form п. 3, три члена, метки среза нет."""
    return "\n".join(
        [
            "== unit u ==",
            f"u/; sha {sha}; scanner {scanner}",
            "purpose: Юнит u.",
            "interface: layer u",
            "  all: A, B",
            "  members:",
            "    u/a.py — Модуль a.  (A, B)",
            "    u/__init__.py — Пакет u.",
            "    u/b.py — Модуль b.  (run_b, arun)",
            "links: найдено 3 (формы: import); не видно: динамика, аннотации, упоминания",
            "  used_by: 2",
            "    v — v/x.py:3 (import) ×2",
            "    w — w/y.py:5 (import) ×1",
            "runtime:",
            "  threads: —",
            "  commands: —",
            "  io: —",
            "checks:",
            "  tests: 1",
            "    u/tests/test_a.py — u/tests/test_a.py:1 ×2",
            "status: tier core; doc_missing нет; dynamic —",
            "  stale: —",
            "  frozen: —",
        ]
    )


def _cut_text(sha: str, scanner: str) -> str:
    """Образец map-form п. 3 буквально: `--budget 22` (полный текст — 23 строки, метка среза входит в бюджет) —
    1 член из 3 и метка, `used_by` и `tests` целиком; 22 строки. Решение лида 2026-11-10: «показано 2 из 3» при
    метке в бюджете недостижимо (23 строки > 22)."""
    lines = _full_text(sha, scanner).splitlines()
    lines.remove("    u/b.py — Модуль b.  (run_b, arun)")
    i = lines.index("    u/__init__.py — Пакет u.")
    lines[i] = "    показано 1 из 3; все: --all members"
    return "\n".join(lines)


# ---------------------------------------------------------------- 1. члены юнита по resolve, не по префиксу

_ROOTS_NESTED = _yaml(
    ("lib/", "framework", "fx/"),
    tail=(
        "modules:\n"
        "  - id: fx/inner\n"
        '    paths: ["lib/a/inner/"]\n'
        "    layer: framework\n"
        "    tier: null\n"
        "    docs: []\n"
        "    parent: fx/a\n"
        '    purpose: "Вложенный юнит"\n'
    ),
)
_NESTED = {
    "modules.yaml": _ROOTS_NESTED,
    "lib/a/__init__.py": '"""Внешний юнит."""\n',
    "lib/a/m.py": "def outer_fn():\n    return 1\n",
    "lib/a/inner/__init__.py": '"""Вложенный пакет."""\n',
    "lib/a/inner/deep.py": "def deep_fn():\n    return 2\n",
    "lib/a/tests/test_m.py": "def test_m():\n    assert True\n",
    "lib/a/inner/tests/test_i.py": "def test_i1():\n    assert True\n\n\ndef test_i2():\n    assert True\n",
}


def test_map_unit_members_by_resolve_not_prefix(repo: GitRepo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Члены юнита — файлы с `modules.resolve(путь) == id`: вложенный юнит (`lib/a/inner/`, строка `modules:`) в члены
    внешнего (`fx/a` из `roots:`) не входит и наоборот; тест-файлы вложенного не попадают в `checks.tests` внешнего.
    Реестр — из ревизии `root`, не из cwd (cwd — пустой каталог без `modules.yaml`)."""
    _commit(repo, _NESTED)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    outer = _build(repo, "fx/a")
    assert (outer["kind"], outer["id"], outer["path"]) == ("unit", "fx/a", "lib/a/")
    assert [m["name"] for m in outer["interface"]["members"]] == ["lib/a/__init__.py", "lib/a/m.py"]
    assert outer["checks"]["tests"] == [
        {"name": "lib/a/tests/test_m.py", "where": "lib/a/tests/test_m.py:1", "count": 1}
    ]
    assert outer["interface"]["layer"] == "fx/a"

    inner = _build(repo, "fx/inner")
    assert (inner["kind"], inner["id"], inner["path"]) == ("unit", "fx/inner", "lib/a/inner/")
    assert [m["name"] for m in inner["interface"]["members"]] == ["lib/a/inner/__init__.py", "lib/a/inner/deep.py"]
    assert inner["checks"]["tests"] == [
        {"name": "lib/a/inner/tests/test_i.py", "where": "lib/a/inner/tests/test_i.py:1", "count": 2}
    ]
    assert inner["interface"]["layer"] == "fx/inner"


# ---------------------------------------------------------------- 2. ключи и значения таблицы п. 2 у unit и file


def _envelope(sha: str, scanner: str, kind: str, ident: str, path: str) -> dict:
    return {"passport": 1, "kind": kind, "id": ident, "path": path, "line": None, "sha": sha, "scanner": scanner}


def test_map_unit_and_file_constant_keys_and_values(repo: GitRepo) -> None:
    """Шесть разделов с постоянными ключами и значения таблицы map-form п. 2 у `unit u` и `file u/b.py` (литералы):
    `line: null`; `layer` юнита — id (не колонка реестра `framework`), `all` юнита — `["A", "B"]` из `u/__init__.py`,
    `all` файла — `null`; `top` юнита без `_`, члены файла — с `_`; `tier` юнита из реестра, файла — из шапки `Tier:`;
    у файла `tests` — `null`; паспорт JSON-совместим."""
    from scripts.atlas import scan

    sha, files = _seed(repo)
    unit = _build(repo, "u")
    file = _build(repo, "u/b.py")

    for p in (unit, file):
        assert list(p) == ENVELOPE + SECTIONS
        for section, keys in SECTION_KEYS.items():
            assert list(p[section]) == keys, section
        assert p["scanner"] == scan.SCANNER and p["sha"] == sha
        assert json.loads(json.dumps(p)) == p

    assert unit == {
        **_envelope(sha, scan.SCANNER, "unit", "u", "u/"),
        "purpose": {"text": "Юнит u.", "called_from": None, "called_from_more": 0, "declared_at": None},
        "interface": {
            "layer": "u",
            "all": ["A", "B"],
            "signature": None,
            "members": [
                {"name": "u/a.py", "signature": None, "where": "u/a.py:1", "top": ["A", "B"], "doc": "Модуль a."},
                {"name": "u/__init__.py", "signature": None, "where": "u/__init__.py:1", "top": [], "doc": "Пакет u."},
                {
                    "name": "u/b.py",
                    "signature": None,
                    "where": "u/b.py:1",
                    "top": ["run_b", "arun"],
                    "doc": "Модуль b.",
                },
            ],
        },
        "links": {
            "used_by": [
                {"name": "v", "where": "v/x.py:3", "how": "import", "count": 2},
                {"name": "w", "where": "w/y.py:5", "how": "import", "count": 1},
            ],
            "uses": None,
            "subclasses": None,
            "call_sites": None,
            "call_sites_unresolved": None,
            "bases": None,
            "structural": None,
        },
        "runtime": {"processes": None, "threads": [], "commands": [], "io": []},
        "checks": {
            "findings": None,
            "tests": [{"name": "u/tests/test_a.py", "where": "u/tests/test_a.py:1", "count": 2}],
        },
        "status": {"tier": "core", "doc_missing": False, "dynamic": 0, "stale": [], "frozen": []},
    }
    assert file == {
        **_envelope(sha, scan.SCANNER, "file", "u/b.py", "u/b.py"),
        "purpose": {"text": "Модуль b.", "called_from": None, "called_from_more": 0, "declared_at": None},
        "interface": {
            "layer": "u",
            "all": None,
            "signature": None,
            "members": [
                {"name": "run_b", "signature": "(x: int) -> int", "where": _at(files, "u/b.py", "run_b")},
                {"name": "arun", "signature": "async () -> None", "where": _at(files, "u/b.py", "arun")},
                {"name": "_hidden", "signature": "() -> None", "where": _at(files, "u/b.py", "hidden")},
            ],
        },
        "links": {
            "used_by": [],
            "uses": None,
            "subclasses": None,
            "call_sites": None,
            "call_sites_unresolved": None,
            "bases": None,
            "structural": None,
        },
        "runtime": {"processes": None, "threads": [], "commands": [], "io": []},
        "checks": {"findings": None, "tests": None},
        "status": {"tier": "optional", "doc_missing": False, "dynamic": 0, "stale": [], "frozen": []},
    }


def test_map_file_used_by_ignores_reexport_and_layer_other(repo: GitRepo) -> None:
    """`used_by` файла `u/a.py`: оператор `v` ×2 (прямой импорт), а импорт `w` через `u/__init__` у файла не виден;
    файл без докстринга: `purpose.text == ""` и `doc_missing: true`; файл вне юнитов: `layer == "other"`."""
    _seed(repo, {"scripts/__init__.py": "", "scripts/tool.py": "def run():\n    return 1\n"})
    a = _build(repo, "u/a.py")
    assert a["links"]["used_by"] == [{"name": "v", "where": "v/x.py:3", "how": "import", "count": 2}]
    assert a["purpose"]["text"] == "Модуль a." and a["status"]["doc_missing"] is False
    assert a["interface"]["all"] is None and a["checks"]["tests"] is None
    tool = _build(repo, "scripts/tool.py")
    assert tool["kind"] == "file" and tool["interface"]["layer"] == "other"
    assert tool["purpose"]["text"] == "" and tool["status"]["doc_missing"] is True
    assert tool["status"]["tier"] is None


# ---------------------------------------------------------------- 3. used_by: группы по юниту-импортёру

_REG_USED = _registry(
    _row("u", "u/", purpose="Юнит u."),
    _row("a_unit", "a_unit/"),
    _row("b_unit", "b_unit/"),
    _row("c_unit", "c_unit/"),
    _row("d_unit", "d_unit/"),
)
_USED = {
    "modules.yaml": _REG_USED,
    "u/__init__.py": '"""Пакет u."""\nfrom u.a import A, B\n\n__all__ = ["A", "B"]\n',
    "u/a.py": '"""Модуль a."""\n\n\nclass A:\n    pass\n\n\nclass B:\n    pass\n',
    "c_unit/__init__.py": "",
    "c_unit/y.py": '"""Модуль y."""\n#\nfrom u.a import A\n',
    "c_unit/x.py": '"""Модуль x."""\n#\n#\n#\n#\nfrom u.a import B\n',
    "a_unit/__init__.py": "",
    "a_unit/m.py": '"""Модуль m."""\nfrom u import A\n',
    "b_unit/__init__.py": "",
    "b_unit/m.py": '"""Модуль m."""\nfrom u.a import A\n',
    "d_unit/__init__.py": "",
    "d_unit/tests/test_d.py": "from u.a import A\n\n\ndef test_d():\n    assert A\n",
}


def test_map_unit_used_by_grouped_by_importer_unit(repo: GitRepo) -> None:
    """Группы по юниту-импортёру: `count` — число операторов (c_unit: два оператора в двух файлах), `how: "import"`,
    порядок `(-count, name)` (a_unit и b_unit по 1 — по имени), `where` — min по `(путь, строка)` (`c_unit/x.py:6`, хотя
    в `c_unit/y.py` строка меньше); импорт через `u/__init__.py` (`from u import A`) учтён; импорт из тест-файла
    (`d_unit/tests/`) — нет."""
    _commit(repo, _USED)
    used_by = _build(repo, "u")["links"]["used_by"]
    assert used_by == [
        {"name": "c_unit", "where": "c_unit/x.py:6", "how": "import", "count": 2},
        {"name": "a_unit", "where": "a_unit/m.py:2", "how": "import", "count": 1},
        {"name": "b_unit", "where": "b_unit/m.py:2", "how": "import", "count": 1},
    ]


# ---------------------------------------------------------------- 4. текст: образец, срез по бюджету, --all, --full


def test_map_text_budget_cut_shows_k_of_n(repo: GitRepo) -> None:
    """Текст `unit u`: образец map-form п. 3 буквально при `budget=22` (1 член из 3: полный текст — 23 строки, метка
    входит в бюджет), без среза при `budget=60` и `full=True`; `show_all={"members"}` при 22 — члены целиком, их строки
    идут в расход бюджета, поэтому режется `used_by` (как у `ref`); минимум при `budget=1`: по
    одной записи на непустой список + метки `показано K из N; все: --all <раздел>`; ключи, всегда `null` у `map`,
    не печатаются; строки «из продукта/из тестов» нет; импорт через `u/__init__` (`w`) — в `used_by`."""
    sha, _ = _seed(repo)
    p = _build(repo, "u")
    scanner = p["scanner"]
    full = _full_text(sha, scanner)

    assert _lines(_render(p, budget=22)) == _lines(_cut_text(sha, scanner))
    assert _lines(_render(p, budget=60)) == _lines(full)
    assert _lines(_render(p, budget=1, full=True)) == _lines(full)
    lifted = full.replace("    w — w/y.py:5 (import) ×1", "    показано 1 из 2; все: --all used_by")
    assert _lines(_render(p, budget=22, show_all=frozenset({"members"}))) == _lines(lifted)
    assert len(_lines(_render(p, budget=22))) == 22  # строк <= max(budget, минимум)

    minimum = _render(p, budget=1)
    stripped = _stripped(minimum)
    assert "показано 1 из 3; все: --all members" in stripped
    assert "показано 1 из 2; все: --all used_by" in stripped
    assert not [s for s in stripped if s.startswith("показано") and "--all tests" in s]  # тест один — не режется
    assert [s for s in stripped if s.startswith(("u/a.py —", "u/__init__.py —", "u/b.py —"))] == [
        "u/a.py — Модуль a.  (A, B)"
    ]
    assert [s for s in stripped if s.startswith(("v —", "w —"))] == ["v — v/x.py:3 (import) ×2"]
    assert "u/tests/test_a.py — u/tests/test_a.py:1 ×2" in stripped
    for kept in ("threads: —", "commands: —", "io: —", "stale: —", "frozen: —", "purpose: Юнит u."):
        assert kept in stripped  # служебные строки минимума не режутся
    assert len(stripped) == 22

    both = _lines(_render(p, budget=1, show_all=frozenset({"members", "used_by"})))
    assert "    u/b.py — Модуль b.  (run_b, arun)" in both and "    w — w/y.py:5 (import) ×1" in both
    assert not [x for x in both if x.lstrip().startswith("показано")]

    for key in NULL_KEYS_NOT_IN_TEXT:
        assert not re.search(rf"\b{key}\b", full), key
    assert "из продукта" not in full and "из тестов" not in full


def test_map_text_file_header_and_member_lines(repo: GitRepo) -> None:
    """`== file u/b.py ==`, вторая строка без `:line`; члены файла: `def name(sig) -> T  :строка`,
    `async def ...`, имена на `_` тоже; класс — `class A  :строка` без скобок."""
    sha, files = _seed(repo)
    b = _build(repo, "u/b.py")
    lines = _lines(_render(b, budget=60))
    assert lines[0] == "== file u/b.py ==" and lines[1] == f"u/b.py; sha {sha}; scanner {b['scanner']}"
    stripped = _stripped(_render(b, full=True))
    line = lambda marker: _at(files, "u/b.py", marker).split(":")[1]  # noqa: E731
    assert f"def run_b(x: int) -> int  :{line('run_b')}" in stripped
    assert f"async def arun() -> None  :{line('arun')}" in stripped
    assert f"def _hidden() -> None  :{line('hidden')}" in stripped
    a_stripped = _stripped(_render(_build(repo, "u/a.py"), full=True))
    assert f"class A  :{_at(files, 'u/a.py', 'clsA').split(':')[1]}" in a_stripped
    assert f"class B  :{_at(files, 'u/a.py', 'clsB').split(':')[1]}" in a_stripped


def test_map_text_top_cut_to_six_with_remainder_and_no_brackets_without_public(repo: GitRepo) -> None:
    """`top` — до 6 имён через запятую, остаток `+N` (8 имён -> шесть и `+2`); приватные `_` в `top` не входят; файл без
    неприватного `top` — строка без скобок."""
    names = [f"f{i}" for i in range(1, 9)]
    c_src = (
        '"""Модуль c."""\n'
        + "".join(f"\n\ndef {n}():\n    return 0\n" for n in names)
        + "\n\ndef _p():\n    return 0\n"
    )
    _seed(repo, {"u/c.py": c_src, "u/priv.py": '"""Модуль p."""\n\n\ndef _only():\n    return 0\n'})
    stripped = _stripped(_render(_build(repo, "u"), full=True))
    row = [s for s in stripped if s.startswith("u/c.py —")]
    assert len(row) == 1, stripped
    assert re.fullmatch(r"u/c\.py — Модуль c\.  \(f1, f2, f3, f4, f5, f6,? ?\+2\)", row[0]), row[0]
    assert "u/priv.py — Модуль p." in stripped  # без скобок: неприватного top нет


def test_map_text_stale_over_five_paths_shows_rest_count(repo: GitRepo) -> None:
    """Шесть изменённых в рабочем дереве путей цели: JSON `status.stale` — все шесть; текст — первые 5 через запятую и
    `; ещё 1`. Два изменённых пути — оба, без `ещё`. Порядок путей формой не задан: сравнение как множеств."""
    _seed(repo)
    six = ["u/a.py", "u/__init__.py", "u/b.py", "v/x.py", "w/y.py", "u/tests/test_a.py"]
    for rel in six[:2]:
        repo.write(rel, (repo.path / rel).read_text(encoding="utf-8") + "# правка\n")
    two = _build(repo, "u")
    assert sorted(two["status"]["stale"]) == sorted(six[:2])
    two_lines = [s for s in _stripped(_render(two, full=True)) if s.startswith("stale:")]
    assert len(two_lines) == 1 and "ещё" not in two_lines[0]
    assert set(two_lines[0].removeprefix("stale: ").split(", ")) == set(six[:2])

    for rel in six[2:]:
        repo.write(rel, (repo.path / rel).read_text(encoding="utf-8") + "# правка\n")
    p = _build(repo, "u")
    assert sorted(p["status"]["stale"]) == sorted(six)
    rows = [line for line in _lines(_render(p, budget=1)) if line.startswith("  stale:")]
    assert len(rows) == 1, rows
    match = re.fullmatch(r"  stale: (.+); ещё 1", rows[0])
    assert match, rows[0]
    shown = match.group(1).split(", ")
    assert len(shown) == 5 and len(set(shown)) == 5 and set(shown) <= set(six)


# ---------------------------------------------------------------- рантайм, динамика, срез threads/io

_REG_RUN = _REG_MAIN
_RUN_FILES = {
    "u/aux.py": '"""Модуль aux."""\nimport threading\n\n\ndef go():\n    threading.Thread(target=print).start()\n',
    "u/svc.py": """\
import os
import threading


class Svc:
    def start(self):
        threading.Thread(target=self.run, daemon=True).start()

    def save(self, tmp, dst):
        os.replace(tmp, dst)


def other(a, b):
    t = threading.Timer(1.0, print)
    t.start()
    os.rename(a, b)
""",
    "u/cmd.py": (
        "class Cmds:\n    def command_specs(self):\n        return [\n"
        '            ("go", "Идти"),\n            ("stop", "Стоп"),\n        ]\n'
    ),
    "u/dyn.py": "class Dyn:\n    def command_specs(self):\n        return build()\n",
    "v/x.py": '"""Импортёр v."""\n\nfrom u.a import A\nfrom u.a import B\nfrom u.svc import Svc\n',
}


def test_map_unit_runtime_records_by_path_line_and_dynamic_sum(repo: GitRepo) -> None:
    """`runtime.threads/io/commands` юнита — записи prod-файлов по `(путь, строка)` (не в порядке членов: `svc.py`
    импортируется, значит идёт в членах раньше `aux.py`); `commands` — только литералы; `status.dynamic` — сумма
    `command_specs_dynamic` (один нелитеральный `command_specs` в `u/dyn.py`); у файла `u/dyn.py` — `dynamic 1`,
    `commands []`; у `u/svc.py` — две записи `threads` и `io`."""
    _seed(repo, _RUN_FILES)
    unit = _build(repo, "u")
    assert unit["runtime"]["threads"] == [
        {"pattern": "Thread", "daemon": None, "where": "u/aux.py:6"},
        {"pattern": "Thread", "daemon": True, "where": "u/svc.py:7"},
        {"pattern": "Timer", "daemon": None, "where": "u/svc.py:14"},
    ]
    assert unit["runtime"]["io"] == [
        {"op": "replaces", "path": "dst", "where": "u/svc.py:10"},
        {"op": "replaces", "path": "b", "where": "u/svc.py:16"},
    ]
    assert unit["runtime"]["commands"] == [
        {"name": "go", "where": "u/cmd.py:4", "how": "declared"},
        {"name": "stop", "where": "u/cmd.py:5", "how": "declared"},
    ]
    assert unit["status"]["dynamic"] == 1
    svc = _build(repo, "u/svc.py")
    assert [t["where"] for t in svc["runtime"]["threads"]] == ["u/svc.py:7", "u/svc.py:14"]
    assert [i["where"] for i in svc["runtime"]["io"]] == ["u/svc.py:10", "u/svc.py:16"]
    assert svc["status"]["dynamic"] == 0 and svc["runtime"]["commands"] == []
    dyn = _build(repo, "u/dyn.py")
    assert dyn["status"]["dynamic"] == 1 and dyn["runtime"]["commands"] == []


def test_map_text_threads_io_cut_commands_not_cut(repo: GitRepo) -> None:
    """При бюджете 1: `threads` (3) и `io` (2) режутся с метками `показано 1 из 3; все: --all threads` и
    `показано 1 из 2; все: --all io`; `commands` (2 записи) не режется и метки не имеет; `--all threads io` метки
    снимает."""
    _seed(repo, _RUN_FILES)
    p = _build(repo, "u")
    cut = _stripped(_render(p, budget=1))
    assert "показано 1 из 3; все: --all threads" in cut
    assert "показано 1 из 2; все: --all io" in cut
    assert not [s for s in cut if "--all commands" in s]
    assert any("go" in s and "u/cmd.py:4" in s for s in cut) and any("stop" in s and "u/cmd.py:5" in s for s in cut)
    lifted = _stripped(_render(p, budget=1, show_all=frozenset({"threads", "io"})))
    assert not [s for s in lifted if "--all threads" in s or "--all io" in s]
    assert sum("u/svc.py:7" in s or "u/svc.py:14" in s or "u/aux.py:6" in s for s in lifted) == 3


# ---------------------------------------------------------------- exclude, frozen, реестр, имена среза


def test_map_unit_exclude_drops_files_everywhere(repo: GitRepo) -> None:
    """`exclude` убирает файлы под префиксом: из членов (`u/b.py`), из `checks.tests` (`u/tests/`) и из `used_by`
    (импортёр `v/`); остальное на месте."""
    _seed(repo)
    p = _build(repo, "u", exclude=("u/b.py", "u/tests/", "v/"))
    # порядок `(-операторов с целью в файле, путь)`: без `v/` у `u/a.py` 0, у `u/__init__.py` 1 (`w/y.py:5`)
    assert [m["name"] for m in p["interface"]["members"]] == ["u/__init__.py", "u/a.py"]
    assert p["checks"]["tests"] == []
    assert p["links"]["used_by"] == [{"name": "w", "where": "w/y.py:5", "how": "import", "count": 1}]


def test_map_unit_frozen_from_init_header_and_registry_status(repo: GitRepo) -> None:
    """`status.frozen` юнита — шапка `FREEZE` из `u/__init__.py` (`where` — строка шапки); текст
    `  frozen: <date> <text> (<путь:строка>)`. Строка реестра без `README.md` в `docs` и без `tier`:
    `doc_missing: true`, `tier: null`."""
    init = '"""Пакет u.\n\nFREEZE 2026-10-01: заморожен до 1.0\n"""\nfrom u.a import A, B\n\n__all__ = ["A", "B"]\n'
    reg = _registry(
        _row("u", "u/", purpose="Юнит u."),
        _row("v", "v/", purpose="Импортёр v."),
        _row("w", "w/", purpose="Импортёр w."),
    )
    _seed(repo, {"u/__init__.py": init, "modules.yaml": reg})
    p = _build(repo, "u")
    assert p["status"]["frozen"] == [{"date": "2026-10-01", "text": "заморожен до 1.0", "where": "u/__init__.py:3"}]
    assert p["status"]["doc_missing"] is True and p["status"]["tier"] is None
    assert "  frozen: 2026-10-01 заморожен до 1.0 (u/__init__.py:3)" in _lines(_render(p, full=True))


def test_map_render_show_all_names_by_kind(repo: GitRepo) -> None:
    """Имена среза берутся по `kind`: у `unit` и `file` `members` допустим, `call_sites` — `ValueError`; у паспорта
    символа (`class`) `members` вне набора — `ValueError` (`ref --all members` остаётся ошибкой)."""
    from scripts.atlas.passport import MAP_SHOW_ALL, build_passport

    _seed(repo)
    assert tuple(MAP_SHOW_ALL) == ("members", "used_by", "tests", "threads", "io")
    unit = _build(repo, "u")
    assert _render(unit, show_all=frozenset({"members", "used_by", "tests", "threads", "io"})).startswith(
        "== unit u =="
    )
    with pytest.raises(ValueError):
        _render(unit, show_all=frozenset({"call_sites"}))
    file = _build(repo, "u/b.py")
    assert _render(file, show_all=frozenset({"members"})).startswith("== file u/b.py ==")
    with pytest.raises(ValueError):
        _render(file, show_all=frozenset({"call_sites"}))
    symbol = run_with_deadline(lambda: build_passport(repo.path, "HEAD", "u/a.py::A"), DEADLINE_S)
    assert symbol["kind"] == "class"
    with pytest.raises(ValueError):
        _render(symbol, show_all=frozenset({"members"}))
