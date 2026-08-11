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
    "Services/modbus/sdk/client.py": (
        "D7: единственная точка привязки logging.Handler к сторонним логгерам "
        "'pymodbus'/'pymodbus_internal' — сама библиотека логирует через stdlib "
        "(pymodbus.logging.Log), обращение к ЕЁ логгеру по имени обязательно для "
        "handler'а-моста, это не вызов на запись прикладного сообщения."
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


# ==============================================================================
# Задача 4.3 (Н-10): второй писатель мимо разъёма — loguru
# ==============================================================================
#
# Страж выше видел ОДНОГО обходчика — голый stdlib. Loguru — такой же писатель
# мимо разъёма и хуже тем, что он не молчит: у него свой sink в stderr, поэтому
# запись выглядит доставленной, а на деле идёт вторым форматом мимо файлов,
# ротации, троттлинга и ретеншена. Класс тот же, симптом противоположный, и
# именно поэтому его не поймал ни один прогон: искали тишину.
#
# Ловится ИМПОРТ, а не вызов. Импортировать loguru незачем, кроме как чтобы им
# писать, и импорт нельзя спрятать за алиасом переменной: `logger = get_thing()`
# страж по вызовам не увидел бы, а импорт виден всегда.

#: Исключения для loguru — та же пара защит, что у stdlib-whitelist'а: живое
#: нарушение внутри и причина по существу. Пусто: после 4.3 обходчиков нет.
LOGURU_WHITELIST: dict[str, str] = {}


def _loguru_imports(path: Path) -> Iterator[tuple[int, str]]:
    """Все импорты loguru в файле — во всех формах написания."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    except (SyntaxError, UnicodeDecodeError):  # pragma: no cover — битый файл не наше дело
        return

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "loguru" or alias.name.startswith("loguru."):
                    yield node.lineno, f"import {alias.name}" + (f" as {alias.asname}" if alias.asname else "")
        elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "loguru":
            names = ", ".join(a.name + (f" as {a.asname}" if a.asname else "") for a in node.names)
            yield node.lineno, f"from {node.module} import {names}"


def _scan_loguru(root: Path = REPO_ROOT) -> list[Hit]:
    """Импорты loguru во всех деревьях, кроме tests/ и whitelist'а.

    ``EXEMPT_DIRS`` здесь НЕ применяется: та причина — «модуль логгера нельзя
    мигрировать на себя же» — про stdlib-фолбэк и к loguru отношения не имеет.
    Переиспользовать чужое исключение значило бы расширить его молча.
    """
    hits: list[Hit] = []
    for tree in TREES:
        tree_root = root / tree
        if not tree_root.is_dir():
            continue
        for py in tree_root.rglob("*.py"):
            rel = _rel(py, root)
            if "tests" in rel.split("/"):
                continue
            if rel in LOGURU_WHITELIST:
                continue
            hits.extend(Hit(rel, lineno, form) for lineno, form in _loguru_imports(py))
    return hits


def test_no_loguru_outside_whitelist() -> None:
    """Ноль импортов loguru в четырёх деревьях.

    До 4.3 таких точек было две — обе в прототипе (``domain/entities/process.py``
    и ``frontend/.../sandbox_presenter.py``), и обе писали предупреждения вторым
    форматом мимо плоскости логов.
    """
    hits = _scan_loguru()
    assert hits == [], "loguru пишет мимо разъёма:\n" + "\n".join(
        f"  {h.path}:{h.lineno}  {h.arg} — заменить на get_std_logger(__name__) "
        f"либо внести в LOGURU_WHITELIST с причиной"
        for h in hits
    )


#: Формы написания, которые страж loguru обязан видеть. Как и у stdlib: частичное
#: покрытие форм даёт ложный зелёный на первой же правке с алиасом.
_PLANTED_LOGURU_FORMS: dict[str, str] = {
    "from-импорт": "from loguru import logger\nlogger.warning('мимо разъёма')\n",
    "алиас имени": "from loguru import logger as log\nlog.warning('мимо разъёма')\n",
    "модульный импорт": "import loguru\nloguru.logger.warning('мимо разъёма')\n",
    "алиас модуля": "import loguru as lg\nlg.logger.warning('мимо разъёма')\n",
    "подмодуль": "from loguru._logger import Logger\n",
}


@pytest.mark.parametrize("form_name,code", sorted(_PLANTED_LOGURU_FORMS.items()))
@pytest.mark.parametrize("tree", TREES)
def test_loguru_guard_sees_a_planted_violation(tmp_path: Path, tree: str, form_name: str, code: str) -> None:
    """Страж loguru показан красным на каждой форме и в каждом дереве."""
    for t in TREES:
        (tmp_path / t).mkdir(parents=True)
    planted = tmp_path / tree / "нарушитель.py"
    planted.write_text(code, encoding="utf-8")

    hits = _scan_loguru(tmp_path)

    assert [h.path for h in hits] == [f"{tree}/нарушитель.py"], (
        f"страж loguru не увидел форму «{form_name}» в дереве {tree}"
    )


@pytest.mark.parametrize("tree", TREES)
def test_loguru_guard_exempts_tests_dir(tmp_path: Path, tree: str) -> None:
    """Негативный контроль: в tests/ loguru — предмет теста, а не способ писать."""
    for t in TREES:
        (tmp_path / t / "tests").mkdir(parents=True)
    (tmp_path / tree / "tests" / "нарушитель.py").write_text("from loguru import logger\n", encoding="utf-8")

    assert _scan_loguru(tmp_path) == [], "импорт внутри tests/ не должен считаться"


def test_the_two_guards_do_not_cover_each_other(tmp_path: Path) -> None:
    """Страж stdlib слеп к loguru, страж loguru слеп к stdlib — и это проверено.

    Иначе один из них казался бы лишним слоем: «оба зелёные» ничего не говорит о
    том, что каждый видит своё. Ровно эта слепота и была Н-10 — writer'ов два,
    правило стояло на одном.
    """
    (tmp_path / TREES[0]).mkdir(parents=True)
    (tmp_path / TREES[0] / "только_loguru.py").write_text("from loguru import logger\n", encoding="utf-8")

    assert _scan(tmp_path) == [], "страж stdlib не должен реагировать на loguru"
    assert len(_scan_loguru(tmp_path)) == 1, "страж loguru обязан видеть свой импорт"


@pytest.mark.parametrize("path", sorted(LOGURU_WHITELIST))
def test_loguru_whitelist_entry_is_not_stale(path: str) -> None:
    """Строка whitelist'а обязана указывать на живой импорт loguru."""
    target = REPO_ROOT / path
    assert target.is_file(), f"LOGURU_WHITELIST указывает на несуществующий файл: {path}"
    assert list(_loguru_imports(target)), f"строка протухла: в {path} больше нет импорта loguru — удалить её"


@pytest.mark.parametrize("path,reason", sorted(LOGURU_WHITELIST.items()))
def test_loguru_whitelist_entry_has_a_real_reason(path: str, reason: str) -> None:
    """Причина — по существу: свалка начинается с одной пустой строки."""
    assert len(reason) >= 40, f"причина для {path} слишком короткая, чтобы быть причиной"


def test_loguru_is_not_a_dependency_while_nobody_imports_it() -> None:
    """Нет потребителей — нет и зависимости (решение владельца 2026-08-11).

    Пара к стражу импортов, а не его дубль. Страж выше запрещает ПИСАТЬ через
    loguru; этот следит, чтобы пакет не лежал в зависимостях «на всякий случай»:
    объявленная зависимость без потребителя читается как разрешение — поставил,
    значит можно, — и первый же новый файл вернёт второго писателя, а страж
    импортов узнает об этом только на следующем прогоне.

    Связка честная в обе стороны: появится законный потребитель — он попадёт в
    ``LOGURU_WHITELIST`` с причиной, и тогда зависимость снова обязана быть
    объявлена. Именно поэтому проверка условная, а не «loguru запрещена навсегда».
    """
    import tomllib

    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = [dep for dep in pyproject["project"]["dependencies"] if dep.split(">=")[0].strip().lower() == "loguru"]

    if LOGURU_WHITELIST:
        assert declared, (
            f"в LOGURU_WHITELIST есть законные потребители {sorted(LOGURU_WHITELIST)}, "
            "а зависимость loguru снята — они упадут ImportError'ом"
        )
    else:
        assert not declared, (
            f"loguru объявлена зависимостью ({declared}), но её никто не импортирует. "
            "Либо снять из pyproject, либо внести потребителя в LOGURU_WHITELIST с причиной"
        )
