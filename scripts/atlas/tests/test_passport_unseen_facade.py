"""Слепые приёмочные тесты подвала `links:` паспорта символа (Task B1, RED 1-4): «импорт через фасад __init__».

Purpose: строка `links:` паспорта символа (`ref <Класс|функция> --format passport`, привязка
    `ref пакет/файл.py::ИМЯ --format passport`) заканчивается `не видно: динамика, аннотации, упоминания, импорт
    через фасад __init__`; строка `links:` карты юнита и файла (`map <юнит>`, `map <файл>`) по-прежнему заканчивается
    старым литералом `не видно: динамика, аннотации, упоминания` без хвоста про фасад. Контракт — только
    `plans/2026-11-06_atlas-passport/tasks/B1.md` (DESIGN 1, REDS 1-4); реализации при записи тестов эти тесты не видят.
Public API: тесты test_*; публичных имён нет.
Stability: lite

Фикстура — главная фикстура юнита `u` из `test_passport_map.py` (`_seed`) плюс константа `u/consts.py::LIMIT` с
импортёром `v/z.py` (для RED 4). Вызовы CLI — через фикстуру `atlas` из conftest (daemon-поток с дедлайном). Проверка
по КОНЦУ строки (`endswith` / regex `$`), не подстрокой: новый литерал начинается со старого. Ожидаемые значения —
литералы, не выводятся из кода под тестом.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from scripts.atlas.tests.conftest import GitRepo
from scripts.atlas.tests.test_passport_map import _seed

__all__: list[str] = []

# старый литерал (карта юнита и файла): конец строки `links:` БЕЗ хвоста про фасад
OLD_TAIL = "не видно: динамика, аннотации, упоминания"
# новый литерал (паспорт символа и привязки)
NEW_TAIL = "не видно: динамика, аннотации, упоминания, импорт через фасад __init__"

_BINDING = "u/consts.py::LIMIT"
_EXTRA_FILES = {
    "u/consts.py": "LIMIT = 16\n",
    "v/z.py": '"""Импортёр константы."""\n\nfrom u.consts import LIMIT\n',
}
# цели `ref`: класс, функция, привязка (константа модуля)
_REF_TARGETS = ["u/a.py::A", "u/b.py::run_b", _BINDING]


def _links_lines(out: str) -> list[str]:
    """Все строки вывода, начинающиеся с `links:` (концевые пробелы срезаны)."""
    return [line.rstrip() for line in out.splitlines() if line.startswith("links:")]


def _ref_links(repo: GitRepo, atlas: Any, ident: str, *extra: str) -> list[str]:
    res = atlas(repo, "ref", ident, "--format", "passport", *extra)
    assert res.code == 0, (ident, res.err)
    lines = _links_lines(res.out)
    assert len(lines) == 1, (ident, res.out)
    return lines


def _map_links(repo: GitRepo, atlas: Any, target: str, *extra: str) -> list[str]:
    res = atlas(repo, "map", target, "--format", "passport", *extra)
    assert res.code == 0, (target, res.err)
    lines = _links_lines(res.out)
    assert lines, (target, res.out)
    return lines


def test_ref_class_links_ends_with_facade_tail(repo: GitRepo, atlas: Any) -> None:
    """RED 1: `ref <Класс> --format passport` — строка `links:` заканчивается новым литералом с хвостом про
    фасад (и при `--full`)."""
    _seed(repo, _EXTRA_FILES)
    for extra in ((), ("--full",)):
        [line] = _ref_links(repo, atlas, "u/a.py::A", *extra)
        assert line.startswith("links: найдено "), line
        assert line.endswith(NEW_TAIL), (extra, line)
        assert re.search(r"; не видно: динамика, аннотации, упоминания, импорт через фасад __init__$", line), line


def test_map_unit_and_file_links_keep_old_tail(repo: GitRepo, atlas: Any) -> None:
    """RED 2 (ЗАЩИТНЫЙ: зелёный и до правки, и после; красен только при переводе рендера юнита/файла на новый
    литерал): `map <юнит>` и `map <файл>` — каждая строка `links:` заканчивается СТАРЫМ литералом без хвоста про
    фасад (по концу строки, не подстрокой)."""
    _seed(repo, _EXTRA_FILES)
    for target in ("u", "u/a.py", "u/b.py", "u/__init__.py"):
        for line in _map_links(repo, atlas, target):
            assert line.endswith(OLD_TAIL), (target, line)
            assert re.search(r"упоминания$", line), (target, line)
            assert "фасад" not in line, (target, line)


@pytest.mark.parametrize("ident", _REF_TARGETS)
def test_ref_links_line_never_ends_with_old_literal(repo: GitRepo, atlas: Any, ident: str) -> None:
    """RED 3: ни одна строка `links:` в выводе `ref` (класс, функция, привязка) не заканчивается старым литералом
    без хвоста (`endswith`, не подстрока: новый литерал начинается со старого)."""
    _seed(repo, _EXTRA_FILES)
    lines = _ref_links(repo, atlas, ident)
    for line in lines:
        assert not line.endswith(OLD_TAIL), (ident, line)
        assert not re.search(r"упоминания$", line), (ident, line)


def test_binding_links_ends_with_facade_tail(repo: GitRepo, atlas: Any) -> None:
    """RED 4: привязка `ref <пакет/файл.py::ИМЯ> --format passport` — строка `links:` заканчивается новым
    литералом."""
    _seed(repo, _EXTRA_FILES)
    [line] = _ref_links(repo, atlas, _BINDING)
    assert line.startswith("links: найдено "), line
    assert line.endswith(NEW_TAIL), line
