"""Контракт-тесты ярусной карты и публичного API модулей (Ф8 H.1 + NEW-10).

Смысл: «ярусная карта = код». Документ
`multiprocess_framework/docs/MODULE_TIERS.md` — единственный источник ярусов, и
он обязан совпадать с тем, что физически лежит в `modules/`. Дрейф вида
«20/21/22/25 модулей», из-за которого H.1 и появился, ловится здесь красным
тестом, а не следующей ручной сверкой через полгода.

Проверяем (см. MODULE_TIERS.md §4):
  1. карта ↔ диск: у каждого модуля ровно одна строка, у каждой строки — каталог;
  2. ярус — из разрешённого множества core/optional/frozen;
  3. `interfaces.py` есть у каждого модуля (NEW-10, «один вход» для типов);
  4. `__all__` объявлен и в `__init__.py`, и в `interfaces.py` — публичный
     контракт перечислен явно;
  5. каждый каталог `*/tests` под `modules/` виден прогону (`testpaths` в
     `modules/pytest.ini`) — иначе тесты молча не гоняются.

Проверки статические (AST + чтение файлов), без импорта 27 модулей: тест обязан
быть быстрым и свободным от побочных эффектов boot'а. Резолвинг имён из
`__all__` — забота контракт-тестов конкретного модуля (пример:
`app_module/tests/test_contract.py`).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

_MODULES_ROOT = Path(__file__).resolve().parents[1]
_TIERS_DOC = _MODULES_ROOT.parent / "docs" / "MODULE_TIERS.md"
_PYTEST_INI = _MODULES_ROOT / "pytest.ini"

_ALLOWED_TIERS = {"core", "optional", "frozen"}

# Строка карты: | `имя_модуля` | ярус | критерий |
_TIER_ROW = re.compile(r"^\|\s*`(?P<name>[a-z_]+)`\s*\|\s*(?P<tier>[a-z]+)\s*\|")


def _documented_tiers() -> dict[str, str]:
    """Ярусы из таблицы §1 документа MODULE_TIERS.md."""
    tiers: dict[str, str] = {}
    in_map_section = False
    for line in _TIERS_DOC.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            # §1 — единственная секция с картой; §2/§3 содержат похожие таблицы,
            # но с другим смыслом (отличия от G0, замороженные фичи).
            in_map_section = line.startswith("## 1.")
            continue
        if not in_map_section:
            continue
        match = _TIER_ROW.match(line)
        if match:
            name = match.group("name")
            assert name not in tiers, f"модуль {name} встречается в карте дважды"
            tiers[name] = match.group("tier")
    return tiers


def _disk_modules() -> set[str]:
    """Каталоги-модули на диске: подкаталог `modules/` с `__init__.py`.

    Критерий отсекает служебные каталоги (`logs/` — рантайм-вывод логов,
    `__pycache__`, `tests/` этого пакета) без списка исключений.
    """
    return {
        path.name
        for path in _MODULES_ROOT.iterdir()
        if path.is_dir() and (path / "__init__.py").is_file() and path.name != "tests"
    }


def _declares_dunder_all(py_file: Path) -> bool:
    """Есть ли в файле присваивание `__all__` на верхнем уровне."""
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    for node in tree.body:
        targets = (
            node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        )
        if any(isinstance(t, ast.Name) and t.id == "__all__" for t in targets):
            return True
    return False


_DOCUMENTED = _documented_tiers()
_ON_DISK = sorted(_disk_modules())


def test_tier_map_matches_disk() -> None:
    """Карта ярусов и файловая система описывают один и тот же набор модулей."""
    documented = set(_DOCUMENTED)
    on_disk = set(_ON_DISK)

    missing_rows = on_disk - documented
    phantom_rows = documented - on_disk

    assert not missing_rows, (
        f"модули без строки в MODULE_TIERS.md §1: {sorted(missing_rows)}. "
        "Новый модуль обязан получить ярус — иначе карта снова разойдётся с кодом."
    )
    assert not phantom_rows, (
        f"строки карты без каталога на диске: {sorted(phantom_rows)}. "
        "Модуль удалён или переименован — обновите MODULE_TIERS.md §1."
    )


def test_tier_values_are_allowed() -> None:
    """Ярус каждого модуля — из множества core/optional/frozen."""
    wrong = {name: tier for name, tier in _DOCUMENTED.items() if tier not in _ALLOWED_TIERS}
    assert not wrong, f"недопустимые ярусы: {wrong} (разрешено: {sorted(_ALLOWED_TIERS)})"


def test_module_count_is_stated_correctly() -> None:
    """Числовой итог в §1 совпадает с числом строк карты.

    Дрейф счётчика («25» в доке при 27 на диске) — ровно то, что чинит H.1.
    """
    text = _TIERS_DOC.read_text(encoding="utf-8")
    match = re.search(r"## 1\. Карта \((?P<count>\d+) модулей\)", text)
    assert match, "в MODULE_TIERS.md §1 нет заголовка вида «## 1. Карта (N модулей)»"
    assert int(match.group("count")) == len(_DOCUMENTED), (
        f"заголовок §1 обещает {match.group('count')} модулей, в таблице {len(_DOCUMENTED)}"
    )


@pytest.mark.parametrize("module_name", _ON_DISK)
def test_module_has_interfaces_module(module_name: str) -> None:
    """NEW-10: у каждого модуля есть `interfaces.py` — единый вход для типов."""
    interfaces = _MODULES_ROOT / module_name / "interfaces.py"
    assert interfaces.is_file(), (
        f"{module_name}: нет interfaces.py. Внешний потребитель должен брать "
        "протоколы/типы оттуда, а не из глубины пакета."
    )


@pytest.mark.parametrize("module_name", _ON_DISK)
def test_module_declares_public_api(module_name: str) -> None:
    """NEW-10: публичный контракт перечислен явно — `__all__` в обоих входах."""
    for filename in ("__init__.py", "interfaces.py"):
        py_file = _MODULES_ROOT / module_name / filename
        assert _declares_dunder_all(py_file), (
            f"{module_name}/{filename}: нет `__all__`. Без него публичным считается "
            "всё, что не начинается с подчёркивания, — контракт неотличим от утечки."
        )


def test_frozen_frontend_flagship_has_no_consumers() -> None:
    """Ярус frozen: у флагмана Gen-1 `frontend_module.application` нет потребителей.

    Дублирует boundary из `.sentrux/rules.toml` намеренно: бесплатный тариф sentrux
    проверяет не все объявленные правила, а заморозка должна держаться независимо
    от тарифа. Из публичного фасада framework флагман уже убран
    (`multiprocess_framework/__init__.py.__getattr__` кидает AttributeError).
    """
    repo_root = _MODULES_ROOT.parents[2]
    needle = "frontend_module.application"
    consumers: list[str] = []
    for area in ("multiprocess_prototype", "Services", "Plugins", "examples"):
        area_path = repo_root / area
        if not area_path.is_dir():
            continue
        for py_file in area_path.rglob("*.py"):
            if "__pycache__" in py_file.parts:
                continue
            if needle in py_file.read_text(encoding="utf-8", errors="ignore"):
                consumers.append(py_file.relative_to(repo_root).as_posix())

    assert not consumers, (
        f"новые потребители замороженного флагмана Gen-1: {consumers}. "
        "Вердикт G0 №5 — FREEZE: код остаётся рабочим, но новых потребителей не заводим "
        "(MODULE_TIERS.md §3)."
    )


def _testpaths_from_ini() -> set[str]:
    """Каталоги из секции `testpaths` файла modules/pytest.ini."""
    lines = _PYTEST_INI.read_text(encoding="utf-8").splitlines()
    paths: set[str] = set()
    collecting = False
    for line in lines:
        if line.startswith("testpaths"):
            collecting = True
            continue
        if collecting:
            stripped = line.strip()
            if not stripped or stripped.startswith("[") or "=" in stripped:
                break
            if not stripped.startswith("#"):
                paths.add(stripped)
    return paths


def test_every_test_dir_is_collected() -> None:
    """Каждый каталог тестов под `modules/` виден прогону.

    Найдено в H.1: `telemetry_readmodel_module/tests`, `config_module/tools/tests`
    и `frontend_module/actions/handlers/tests` (58 зелёных тестов) лежали на диске,
    но отсутствовали в `testpaths` — то есть не гонялись вообще. Тест-невидимка
    хуже отсутствующего: он создаёт ложное чувство покрытия.
    """
    on_disk = {
        path.relative_to(_MODULES_ROOT).as_posix()
        for path in _MODULES_ROOT.rglob("tests")
        if path.is_dir() and "__pycache__" not in path.parts
    }
    uncollected = on_disk - _testpaths_from_ini()
    assert not uncollected, (
        f"каталоги тестов вне testpaths (modules/pytest.ini): {sorted(uncollected)}. "
        "Эти тесты не гоняются — добавьте путь в testpaths."
    )
