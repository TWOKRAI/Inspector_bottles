# -*- coding: utf-8 -*-
"""Ф6.3 — регресс-страж: голый stdlib-логгер не возвращается в прикладной код.

Что защищает. У stdlib-root в процессах фреймворка нет хендлеров, поэтому
``logging.getLogger(...)`` пишет в никуда. Ровно на этом стояли инцидент 645 МБ
(молчащая ротация) и 23% невидимых ошибок: 100 файлов писали, и ни одна запись
не доезжала ни до файла, ни до троттлинга, ни до ретеншена. Ф6.2 перевела их на
вид ``get_std_logger(__name__)``; этот тест не даёт им вернуться.

Почему по AST, а не грепом. Греп по ``logging.getLogger`` ловит одну форму из
трёх. Мимо него проходят ``import logging as _log`` + ``_log.getLogger(...)``
и ``from logging import getLogger`` + ``getLogger(...)`` — а именно алиасные
формы и пришлось править руками в Ф6.2 (`domain/__init__.py`, `frontend/app.py`),
то есть это не гипотетическая развилка, а та, по которой уже ходили.

Почему whitelist проверяется на протухание. Whitelist без проверки становится
свалкой: файл переехал или запись из него ушла, а строка осталась и молча
разрешает то, чего уже нет. Поэтому мёртвая строка whitelist'а — такой же
красный, как и новое нарушение.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterator, NamedTuple

import pytest

#: Корень репозитория: .../multiprocess_framework/modules/logger_module/tests/файл
REPO_ROOT = Path(__file__).resolve().parents[4]

#: Деревья прикладного кода. Ф6.2 вычистила три из них полностью — на 2026-08-03
#: `Services`, `Plugins` и `multiprocess_prototype` не содержат ни одной точки.
TREES = ("multiprocess_framework", "Services", "Plugins", "multiprocess_prototype")

#: Директории, целиком выведенные из-под правила: путь → причина. Ф6.х.4:
#: те же две защиты, что у WHITELIST (живое нарушение внутри + причина по
#: существу) — прежде это был второй механизм разрешения без обеих защит,
#: и добавить сюда что угодно можно было молча.
EXEMPT_DIRS: dict[str, str] = {
    "multiprocess_framework/modules/logger_module": (
        "Сам модуль логгера нельзя мигрировать на себя же: его stdlib-фолбэк "
        "(std_facade._fallback) и есть та точка, куда вид пишет, пока "
        "процессный LoggerManager не поднят."
    ),
}

#: Исключения-по-устройству: путь → причина. Причина обязательна и проверяется
#: тестом ниже — строка без неё не имеет права на существование (условие
#: приёмки 6.5: «whitelist с обоснованием у КАЖДОЙ строки, иначе он свалка»).
WHITELIST: dict[str, str] = {
    "multiprocess_framework/modules/_fallback.py": (
        "Сам аварийный выход фреймворка: единственная функция, которой разрешено "
        "писать, когда штатный маршрут сломан. Писать о поломке логгера через "
        "логгер нельзя."
    ),
    "multiprocess_framework/modules/base_manager/mixins/observable_mixin.py": (
        "_note_manager_call_failure сообщает о ПОЛОМКЕ менеджера и обязан идти "
        "мимо него. Проба импорта (Ф6.5) даёт цикл: partially initialized "
        "base_manager."
    ),
    "multiprocess_framework/modules/data_schema_module/registry/discovery.py": (
        "Ниже слоя логгера: logger_module импортирует data_schema_module, "
        "обратная зависимость даёт цикл (проба Ф6.5: SchemaBase из partially "
        "initialized модуля)."
    ),
    "multiprocess_framework/modules/data_schema_module/registry/process_registry.py": (
        "То же, что discovery.py: ниже слоя логгера, проба даёт тот же цикл."
    ),
    "multiprocess_framework/modules/frontend_module/core/diagnostics.py": (
        "Имя логгера приходит из КОНФИГА (ui_diagnostics.logger_name) и его "
        "смысл — отдать записи во внешне настроенный stdlib-логгер. Вид "
        "принимает только __name__, миграция обессмыслила бы поле конфига. "
        "Долг: решить вместе с судьбой ui_diagnostics."
    ),
    "multiprocess_framework/modules/state_store_module/middleware/logging_mw.py": (
        "Принимает stdlib-Logger параметром конструктора, а уровень держит "
        "ЦЕЛЫМ числом stdlib (getattr(logging, 'DEBUG')). Вид требует уровень "
        "строкой — facade.log() зовёт level.lower() и упал бы AttributeError. "
        "Миграция = смена публичного контракта конструктора, не правка строки."
    ),
}


class Hit(NamedTuple):
    """Одна точка получения stdlib-логгера."""

    path: str  # относительный, со слэшами — чтобы совпадал на Windows и POSIX
    lineno: int
    arg: str


def _stdlib_getlogger_calls(path: Path) -> Iterator[tuple[int, str]]:
    """Все вызовы stdlib getLogger в файле — во всех трёх формах написания."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    except (SyntaxError, UnicodeDecodeError):  # pragma: no cover — битый файл не наше дело
        return

    module_aliases = {"logging"}
    direct_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "logging":
                    module_aliases.add(alias.asname or "logging")
        elif isinstance(node, ast.ImportFrom) and node.module == "logging":
            for alias in node.names:
                if alias.name == "getLogger":
                    direct_names.add(alias.asname or "getLogger")

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        via_module = (
            isinstance(func, ast.Attribute)
            and func.attr == "getLogger"
            and isinstance(func.value, ast.Name)
            and func.value.id in module_aliases
        )
        via_direct = isinstance(func, ast.Name) and func.id in direct_names
        if via_module or via_direct:
            yield node.lineno, (ast.unparse(node.args[0]) if node.args else "<без аргумента>")


def _rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _scan(root: Path = REPO_ROOT) -> list[Hit]:
    """Нарушения во всех деревьях, кроме tests/, exempt-директорий и whitelist'а."""
    hits: list[Hit] = []
    for tree in TREES:
        tree_root = root / tree
        if not tree_root.is_dir():
            continue
        for py in tree_root.rglob("*.py"):
            rel = _rel(py, root)
            # Тесты: stdlib-логгер там ПРЕДМЕТ теста, а не способ логировать.
            if "tests" in rel.split("/"):
                continue
            if any(rel == d or rel.startswith(d + "/") for d in EXEMPT_DIRS):
                continue
            if rel in WHITELIST:
                continue
            hits.extend(Hit(rel, lineno, arg) for lineno, arg in _stdlib_getlogger_calls(py))
    return hits


def test_no_bare_stdlib_logger_outside_whitelist() -> None:
    """Ноль голых stdlib-логгеров в четырёх деревьях. Литерал, не вывод из кода."""
    hits = _scan()
    assert hits == [], "голый stdlib-логгер вернулся:\n" + "\n".join(
        f"  {h.path}:{h.lineno}  getLogger({h.arg}) — "
        f"заменить на get_std_logger(__name__) либо внести в WHITELIST с причиной"
        for h in hits
    )


@pytest.mark.parametrize("path", sorted(WHITELIST))
def test_whitelist_entry_is_not_stale(path: str) -> None:
    """Строка whitelist'а обязана указывать на живое нарушение.

    Иначе whitelist растёт, а защита сжимается: файл переехал или запись из него
    ушла, а разрешение осталось и молча покрывает уже другой код.
    """
    target = REPO_ROOT / path
    assert target.is_file(), f"whitelist указывает на несуществующий файл: {path}"
    calls = list(_stdlib_getlogger_calls(target))
    assert calls, f"строка whitelist'а протухла: в {path} больше нет stdlib getLogger — удалить её"


@pytest.mark.parametrize("path,reason", sorted(WHITELIST.items()))
def test_whitelist_entry_has_a_real_reason(path: str, reason: str) -> None:
    """Причина — по существу, а не «так надо»: свалка начинается с одной пустой строки."""
    assert len(reason) >= 40, f"причина для {path} слишком короткая, чтобы быть причиной"


#: Ф6.х.4: все четыре формы написания, которые страж обязан видеть. Ручная
#: матрица И-1…И-9 из плана (задача 6.3) переехала в CI: прежде planted-тест
#: покрывал одну форму на одном дереве, остальное жило только текстом плана.
_PLANTED_FORMS: dict[str, str] = {
    "модульная": "import logging\nlog = logging.getLogger(__name__)\n",
    "алиас модуля": "import logging as _log\nlog = _log.getLogger('корзина')\n",
    "прямой импорт": "from logging import getLogger\nlog = getLogger(__name__)\n",
    "алиас имени": "from logging import getLogger as gl\nlog = gl(__name__)\n",
}


@pytest.mark.parametrize("form_name,code", sorted(_PLANTED_FORMS.items()))
@pytest.mark.parametrize("tree", TREES)
def test_guard_sees_a_violation_when_one_is_planted(tmp_path: Path, tree: str, form_name: str, code: str) -> None:
    """Страж, который не показан красным, не отличим от отсутствующего.

    Матрица «4 формы × 4 дерева»: частичная инъекция даёт ложный зелёный —
    правило, разучившееся видеть одну форму или одно дерево, обязано упасть
    здесь, а не жить текстом плана. Проверка идёт на подставном дереве, а не
    правкой репозитория: тест, который пишет в рабочую копию, оставляет её
    грязной при падении.
    """
    for t in TREES:
        (tmp_path / t).mkdir(parents=True)
    planted = tmp_path / tree / "нарушитель.py"
    planted.write_text(code, encoding="utf-8")

    hits = _scan(tmp_path)

    assert [h.path for h in hits] == [f"{tree}/нарушитель.py"], f"страж не увидел форму «{form_name}» в дереве {tree}"


@pytest.mark.parametrize("tree", TREES)
def test_tests_dir_is_exempt_in_every_tree(tmp_path: Path, tree: str) -> None:
    """Негативный контроль (И-5): исключение tests/ настоящее, а не случайное."""
    for t in TREES:
        (tmp_path / t / "tests").mkdir(parents=True)
    planted = tmp_path / tree / "tests" / "нарушитель.py"
    planted.write_text("import logging as _log\nlog = _log.getLogger('корзина')\n", encoding="utf-8")

    assert _scan(tmp_path) == [], "нарушение внутри tests/ не должно считаться"


@pytest.mark.parametrize("dir_path", sorted(EXEMPT_DIRS))
def test_exempt_dir_is_not_stale(dir_path: str) -> None:
    """Exempt-директория обязана существовать и держать живое нарушение.

    Иначе исключение молча покрывает код, которого нет, — та же гниль, от
    которой защищён WHITELIST.
    """
    root = REPO_ROOT / dir_path
    assert root.is_dir(), f"EXEMPT_DIRS указывает на несуществующую директорию: {dir_path}"
    calls = [
        hit
        for py in root.rglob("*.py")
        if "tests" not in _rel(py, REPO_ROOT).split("/")
        for hit in _stdlib_getlogger_calls(py)
    ]
    assert calls, f"exempt-директория протухла: в {dir_path} нет живого stdlib getLogger — снять исключение"


@pytest.mark.parametrize("dir_path,reason", sorted(EXEMPT_DIRS.items()))
def test_exempt_dir_has_a_real_reason(dir_path: str, reason: str) -> None:
    """Причина exempt-директории — по существу, как у whitelist'а."""
    assert len(reason) >= 40, f"причина для {dir_path} слишком короткая, чтобы быть причиной"
