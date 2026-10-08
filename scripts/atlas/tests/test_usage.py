"""Приёмочные тесты «Кто использует» и честного счёта тестов (Task 1.6c, блок A, RED до кода).

Purpose: раздел «Кто использует» вывода `ref` — строка импорта (строка алиаса многострочного импорта), строка
    вызова, `as`-алиас, цепочка реэкспорта, файлы модуля не считаются, группа тестов считает функции (упоминание
    в docstring/комментарии = 0), дословная строка-ограничение, крышки 5/3/120, итог «без использований вне
    модуля»; синтаксическая ошибка в одном файле (Ф4); честное число «тестов N» и «пример» в заголовках интерфейсов
    (фикстура Ф1 и пин config_module: 1/1/1).
Public API: тесты test_*; публичных имён нет.
Stability: lite

Ожидаемые значения выведены ВРУЧНУЮ из текста фикстур по DESIGN п. 7-8 брифа plans/2026-10-04_atlas/tasks/1.6c.md.
Фикстура Ф1 и хелперы — из test_ref_code.py.
"""

from __future__ import annotations

from typing import Any

import pytest

from scripts.atlas.tests.conftest import GitRepo, RepoFactory
from scripts.atlas.tests.test_exam_k0 import _M, _ref, pin_db, pinned  # noqa: F401 - фикстуры пина
from scripts.atlas.tests.test_ref_code import (
    REFS,
    USAGE_HEADER,
    USAGE_UNKNOWN,
    block,
    commit,
    f1_repo,
    f4_repo,
    lines_of,
    modules_yaml,
    new_repo,
    put,
)

__all__: list[str] = []


def _usage_section(lines: list[str]) -> list[str]:
    start = next(i for i, line in enumerate(lines) if line.startswith("Кто использует"))
    return lines[start:]


# ---------------------------------------------------------------- Ф1: полный раздел


def test_usage_section_on_f1_is_exact(repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = f1_repo(repo_factory, monkeypatch)
    section = _usage_section(lines_of(atlas(repo, "ref", "m", *REFS)))
    assert section == [
        USAGE_HEADER,
        "IA — вне модуля 0, тестов 2, файлов 0",
        "  тесты:",
        "    m/tests/test_x.py:1  импорт, тестов 1",
        "    m/tests/test_z.py:1  импорт, тестов 1",
        "IP — вне модуля 0, тестов 0, файлов 0",
        "  тесты:",
        "    m/tests/test_word.py:1  импорт, тестов 0",
        "pub — вне модуля 2, тестов 1, файлов 1",
        "  u/use.py:2  импорт",
        "  u/use.py:7  вызов",
        "  тесты:",
        "    u/tests/test_use.py:1  импорт, тестов 1",
        "без использований вне модуля: Child, Duck, IPlain, Impl, One, Qt1, Sized, Solo, Sub",
    ]


def test_usage_limitation_line_is_verbatim(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = f1_repo(repo_factory, monkeypatch)
    lines = lines_of(atlas(repo, "ref", "m", *REFS))
    assert (
        "Кто использует (статика: импорты и вызовы по имени; getattr, реестры, patch по строке,"
        " методы объектов и каналы роутера не видны):"
    ) in lines


def test_multiline_import_uses_the_alias_line_not_the_statement_line(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = f1_repo(repo_factory, monkeypatch)
    pub = block(_usage_section(lines_of(atlas(repo, "ref", "m", *REFS))), "pub — ")
    assert "  u/use.py:2  импорт" in pub  # оператор импорта на строке 1, алиас pub — на строке 2
    assert "  u/use.py:1  импорт" not in pub
    assert "  u/use.py:7  вызов" in pub


def test_module_own_files_and_reexport_chain(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = f1_repo(repo_factory, monkeypatch)
    pub = block(_usage_section(lines_of(atlas(repo, "ref", "m", *REFS))), "pub — ")
    joined = "\n".join(pub)
    # m/__init__.py и m/tools/__init__.py импортируют pub, но это файлы самого модуля
    assert "m/__init__.py" not in joined
    assert "m/tools/__init__.py" not in joined
    # тест импортирует pub как p из пакета m (цепочка m -> m.tools -> m.tools.helper) и вызывает p()
    assert "    u/tests/test_use.py:1  импорт, тестов 1" in pub


def test_tests_group_counts_functions_not_docstring_mentions(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = f1_repo(repo_factory, monkeypatch)
    section = _usage_section(lines_of(atlas(repo, "ref", "m", *REFS)))
    # test_mentions упоминает pub только в docstring: из двух функций файла считается одна
    assert "    u/tests/test_use.py:1  импорт, тестов 1" in section
    # test_word импортирует IP, но в теле — только docstring и комментарий: файл печатается с тестов 0
    assert "    m/tests/test_word.py:1  импорт, тестов 0" in section
    assert "IP — вне модуля 0, тестов 0, файлов 0" in section


# ---------------------------------------------------------------- честный счёт в заголовках интерфейсов


def test_honest_test_count_in_headers_on_f1(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = f1_repo(repo_factory, monkeypatch)
    lines = lines_of(atlas(repo, "ref", "m", *REFS))
    headers = {
        line.split(" — ")[0]: line
        for line in lines
        if line and not line.startswith(" ") and " — " in line and " — вне модуля " not in line
    }  # строки раздела «Кто использует» (`IA — вне модуля …`) не затирают заголовки
    # IA: две тестовые функции в двух файлах, «пример» — наименьший путь
    assert headers["IA"] == "IA — Контракт A — m/interfaces.py:10 — тестов 2, пример m/tests/test_x.py"
    # IP: слово только в docstring и комментарии теста — по слову было бы 1, честно 0
    assert headers["IP"] == "IP — Вызываемый контракт — m/interfaces.py:32 — тестов 0"


def test_honest_test_count_on_the_pin(pinned: GitRepo, atlas: Any) -> None:  # noqa: F811
    lines = _ref(atlas, pinned, "config_module")
    expected = {
        "IConfig — ": f" — тестов 1, пример {_M}/config_module/tests/test_iconfig_contract.py",
        "IConfigObserver — ": f" — тестов 1, пример {_M}/config_module/tests/test_iconfig_contract.py",
        "IConfigManager — ": f" — тестов 1, пример {_M}/config_module/tests/test_iconfig_manager_contract.py",
    }
    for prefix, suffix in expected.items():
        header = next(line for line in lines if line.startswith(prefix))
        assert header.endswith(suffix), header


# ---------------------------------------------------------------- Ф4: синтаксическая ошибка в одном файле


def test_unparsable_sources_give_one_line_and_other_sections_stay(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = f4_repo(repo_factory, monkeypatch)
    built = atlas(repo, "--json", *REFS)
    assert built.code == 0, built.err
    res = atlas(repo, "ref", "z", *REFS)
    lines = lines_of(res)
    assert lines.count(USAGE_UNKNOWN) == 1
    assert not any(line.startswith("Кто использует (") for line in lines)
    assert lines[0] == "Справочник модуля z — z/interfaces.py, интерфейсов 1"
    assert any(line.startswith("Код модуля (без tests/ и interfaces.py): ") for line in lines)
    assert "bad.py" not in res.out, "строка не содержит ни пути, ни значения ввода"
    card = lines_of(atlas(repo, "card", "z", *REFS))
    assert USAGE_UNKNOWN in card
    assert card[0].startswith("Модуль z — framework")


# ---------------------------------------------------------------- крышки 5 / 3 / 120


def _usage_caps_repo(factory: RepoFactory, mp: pytest.MonkeyPatch) -> GitRepo:
    repo = new_repo(factory, "usage_caps")
    repo.write("modules.yaml", modules_yaml([("hub", "framework"), ("hub2", "framework"), ("cons", "prototype")]))
    for pkg in ("hub", "hub2", "cons"):
        put(repo, f"{pkg}/__init__.py", "")
    put(repo, "hub/api.py", 'def ping() -> int:\n    """Пинг."""\n    return 1\n')
    calls = "".join(f"\n\ndef {name}() -> int:\n    return ping()\n" for name in ("a", "b", "c"))
    put(repo, "cons/c.py", "from hub.api import ping\n" + calls)
    put(repo, "cons/d.py", "from hub.api import ping\n\n\ndef d() -> int:\n    return ping()\n")
    for k in range(1, 5):
        put(repo, f"cons/tests/test_{k}.py", "from hub.api import ping\n\n\ndef test_p() -> None:\n    ping()\n")
    names = [f"g{i:02d}" for i in range(1, 46)]
    put(repo, "hub2/api.py", "\n\n".join(f"def {n}() -> int:\n    return 1\n" for n in names))
    body = "from hub2.api import (\n" + "".join(f"    {n},\n" for n in names) + ")\n\n\ndef run() -> None:\n"
    put(repo, "cons/e.py", body + "".join(f"    {n}()\n" for n in names))
    commit(repo, mp, "2026-10-01", "init")
    return repo


def test_rows_cap_is_five_and_tests_cap_is_three(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _usage_caps_repo(repo_factory, monkeypatch)
    section = _usage_section(lines_of(atlas(repo, "ref", "hub", *REFS)))
    assert section == [
        USAGE_HEADER,
        "ping — вне модуля 6, тестов 4, файлов 2",
        "  cons/c.py:1  импорт",
        "  cons/c.py:5  вызов",
        "  cons/c.py:9  вызов",
        "  cons/c.py:13  вызов",
        "  cons/d.py:1  импорт",
        "  … ещё 1",
        "  тесты:",
        "    cons/tests/test_1.py:1  импорт, тестов 1",
        "    cons/tests/test_2.py:1  импорт, тестов 1",
        "    cons/tests/test_3.py:1  импорт, тестов 1",
        "    … ещё 1",
    ]


def test_usage_section_is_capped_at_120_lines(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _usage_caps_repo(repo_factory, monkeypatch)
    section = _usage_section(lines_of(atlas(repo, "ref", "hub2", *REFS)))
    assert len(section) == 120, "в лимит входят строка-ограничение и строка «… ещё»"
    assert section[0] == USAGE_HEADER
    assert section[1:4] == ["g01 — вне модуля 2, тестов 0, файлов 1", "  cons/e.py:2  импорт", "  cons/e.py:51  вызов"]
    assert section[-1] == "… ещё 17 строк, сузить: ref hub2 --symbol ИМЯ"
    assert "g40 — вне модуля 2, тестов 0, файлов 1" in section
    assert not any(line.startswith("g41 — ") for line in section)


def test_no_uses_outside_the_module_is_one_line_with_a_name_cap(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts.atlas.tests.test_ref_code import caps_repo

    repo = caps_repo(repo_factory, monkeypatch)
    section = _usage_section(lines_of(atlas(repo, "ref", "wide", *REFS)))
    names = ", ".join(f"f{i:02d}" for i in range(1, 21))
    assert section == [USAGE_HEADER, f"без использований вне модуля: {names}, … ещё 60"]
