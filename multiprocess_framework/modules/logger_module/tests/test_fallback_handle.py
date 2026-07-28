# -*- coding: utf-8 -*-
"""2.2 — ``FallbackLogger`` стал handle'ом к единственному виду, а не писателем.

План: plans/observability-unified-routing.md, задача 2.2 (решение владельца
«писателей как можно меньше»).

Проверяются ровно те свойства, ради которых класс вообще остался, и те, что
могли молча пропасть при переводе на вид:

  1. **Цикло-безопасность** — модуль импортируется и объект создаётся БЕЗ
     подтягивания ``logger_module``. Это единственная причина, по которой
     ``get_std_logger`` нельзя позвать напрямую из ``base_manager`` и соседей.
     Проверяется в ЧИСТОМ интерпретаторе: в текущем процессе всё давно
     импортировано, и тест здесь был бы вакуумным.
  2. **Имя stdlib-логгера точное** — без префикса ``mpf.``. Иначе записи
     «менеджера нет» уезжают под чужим именем ровно тогда, когда их ищут.
  3. **Склейка ``%`` НЕ до гейта** — прежний ``_fmt`` собирал строку перед
     передачей менеджеру, и 13 utility-классов платили форматирование за
     отклонённые записи (тот же дефект, что Ф1.5 чинила в фасаде).
  4. **Имя доезжает до файла** — то, ради чего Ф2.1 правила этот класс.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from typing import Iterator, List

import pytest

from multiprocess_framework.modules._fallback import FallbackLogger, emergency_log
from multiprocess_framework.modules.logger_module.core.error_floor import reset_error_floors
from multiprocess_framework.modules.logger_module.core.log_config import (
    LoggerChannelSchema,
    LoggerManagerConfig,
    LoggerScopeSchema,
)
from multiprocess_framework.modules.logger_module.core.logger_core import bump_observability_epoch
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    reset_error_floors()
    monkeypatch.setattr(LoggerManager, "_instance", None)
    bump_observability_epoch()
    yield
    reset_error_floors()


def _config(directory: Path) -> LoggerManagerConfig:
    return LoggerManagerConfig(
        app_name="fallback_handle",
        log_directory=str(directory),
        enable_batching=False,
        modules={},
        channels={
            "system_file": LoggerChannelSchema(
                name="system_file", type="file", enabled=True, file_path="system.log", rotate=False
            )
        },
        scopes={
            scope: LoggerScopeSchema(enabled=True, min_level="DEBUG", channels=["system_file"])
            for scope in ("SYSTEM", "BUSINESS", "DEBUG")
        },
    )


# =============================================================================
# 1. Цикло-безопасность
# =============================================================================


def test_module_has_no_top_level_import_of_logger_module() -> None:
    """У ``_fallback.py`` нет импорта ``logger_module`` НА УРОВНЕ МОДУЛЯ.

    Проверяется исходник разбором AST, а не ``sys.modules``. Первая редакция
    этого теста поднимала чистый интерпретатор и утверждала, что после
    ``from ..._fallback import FallbackLogger`` в ``sys.modules`` нет ни одного
    ``logger_module``. Прогон опроверг: их девятнадцать — и **ровно столько же
    было до правки**, потому что тянет их корневой ``multiprocess_framework``,
    а не этот файл. То есть тест утверждал свойство, которого никогда не было.

    Настоящее свойство другое и тоньше: опасен не сам импорт, а импорт в момент
    ЧАСТИЧНОЙ инициализации. Цепочка ``logger_module/__init__`` →
    ``channel_routing_module`` → ``base_manager`` → ``base_adapter`` →
    ``_fallback`` разворачивается, когда ``logger_module`` собран наполовину;
    модульный импорт оттуда полез бы в недостроенный модуль. Импорт внутри
    метода этого не делает — и именно это здесь и закреплено.
    """
    import ast

    source = Path(__import__("multiprocess_framework.modules._fallback", fromlist=["_"]).__file__)
    tree = ast.parse(source.read_text(encoding="utf-8"))
    top_level: List[str] = []
    for node in tree.body:  # ТОЛЬКО верхний уровень — вложенные импорты легальны
        if isinstance(node, ast.ImportFrom) and node.module and "logger_module" in node.module:
            top_level.append(node.module)
        elif isinstance(node, ast.ImportFrom) and node.level and node.module is None:
            top_level.extend(alias.name for alias in node.names if "logger_module" in alias.name)
        elif isinstance(node, ast.Import):
            top_level.extend(alias.name for alias in node.names if "logger_module" in alias.name)
    assert top_level == [], f"импорт logger_module поднялся на уровень модуля — цикл вернётся: {top_level}"


def test_cycle_consumer_imports_in_a_cold_interpreter() -> None:
    """Реальный потребитель из зоны цикла импортируется в ЧИСТОМ процессе.

    ``base_manager/adapters/base_adapter.py`` создаёт handle на уровне модуля и
    лежит ровно в той цепочке, ради которой ``_fallback.py`` вынесен из пакетов.
    Разбор AST выше говорит про форму кода, этот тест — про факт: цикла нет.
    Отдельный интерпретатор обязателен, в текущем всё импортировано задолго до
    сюда, и проверка была бы вакуумной.
    """
    result = subprocess.run(
        [sys.executable, "-c", "import multiprocess_framework.modules.base_manager.adapters.base_adapter"],
        cwd=str(Path(__file__).resolve().parents[4]),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    assert result.returncode == 0, f"цикл импорта вернулся:\n{result.stderr}"


def test_view_is_resolved_only_on_first_write() -> None:
    """Вид подтягивается при ПЕРВОЙ ЗАПИСИ, а не в ``__init__``.

    Ленивость здесь не оптимизация, и это ВОСПРОИЗВЕДЕНО, а не заявлено.
    Слом-инъекция «резолвить в ``__init__``» (импорт при этом остаётся внутри
    метода!) даёт::

        ImportError: cannot import name 'ObservableMixin' from partially
        initialized module 'multiprocess_framework.modules.base_manager'
        (most likely due to a circular import)

    Причина: ``base_adapter.py`` создаёт handle НА УРОВНЕ МОДУЛЯ, то есть сам
    ``__init__`` исполняется внутри окна частичной инициализации. Значит мало
    держать импорт в методе — нельзя резолвить и в конструкторе.
    """
    handle = FallbackLogger("проба.ленивости")
    assert handle._view is None
    handle.info("первая запись")
    assert handle._view is not None


# =============================================================================
# 2-3. Поведение без менеджера
# =============================================================================


def test_stdlib_name_stays_exact(caplog: pytest.LogCaptureFixture) -> None:
    """Без префикса ``mpf.``: имя — ровно то, что передали (обычно ``__name__``)."""
    name = "multiprocess_framework.modules.проба"
    with caplog.at_level(logging.WARNING):
        FallbackLogger(name).warning("расхождение")

    names = [record.name for record in caplog.records]
    assert name in names, names
    assert f"mpf.{name}" not in names


def test_message_is_not_swallowed_without_a_manager(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.ERROR):
        FallbackLogger("utility.проба").error("нечем писать")

    assert "нечем писать" in caplog.text


# =============================================================================
# 4. С менеджером — по артефакту
# =============================================================================


def test_name_reaches_the_file(tmp_path: Path) -> None:
    logger = LoggerManager(config=_config(tmp_path))
    try:
        FallbackLogger("multiprocess_framework.modules.spawner").info("процесс порождён")
    finally:
        logger.shutdown()

    line = (tmp_path / "system.log").read_text(encoding="utf-8").splitlines()[0]
    assert "multiprocess_framework.modules.spawner" in line, line
    assert "процесс порождён" in line


def test_percent_args_are_formatted_after_the_gate(tmp_path: Path) -> None:
    """Склейка происходит в менеджере, а не в handle'е.

    Прежний ``_fmt`` собирал строку ДО передачи — то есть цена форматирования
    платилась и за записи, которые гейт отклоняет. Здесь это видно по
    ``__str__``-счётчику аргумента: у отклонённой записи он обязан остаться в
    нуле, у принятой — ровно единица.
    """

    class _Counting:
        def __init__(self) -> None:
            self.calls = 0

        def __str__(self) -> str:
            self.calls += 1
            return "значение"

        __repr__ = __str__

    config = _config(tmp_path)
    config.scopes["DEBUG"].enabled = False  # DEBUG отклоняется гейтом
    logger = LoggerManager(config=config)
    rejected, accepted = _Counting(), _Counting()
    try:
        handle = FallbackLogger("utility.форматирование")
        handle.debug("отклонено: %s", rejected)
        handle.info("принято: %s", accepted)
    finally:
        logger.shutdown()

    assert rejected.calls == 0, "отклонённая гейтом запись всё равно склеила строку"
    assert accepted.calls == 1, f"принятая запись склеена {accepted.calls} раз вместо одного"
    assert "принято: значение" in (tmp_path / "system.log").read_text(encoding="utf-8")


# =============================================================================
# Аварийный выход
# =============================================================================


class TestEmergencyLog:
    """Второй (и последний) писатель: stdlib напрямую, никогда через менеджер."""

    def test_writes_to_stdlib_even_with_a_live_manager(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        """Ключевое свойство: наличие живого менеджера НЕ уводит запись в него.

        Иначе аварийный выход перестал бы быть выходом: о поломке маршрута
        сообщали бы этим же маршрутом.
        """
        logger = LoggerManager(config=_config(tmp_path))
        try:
            with caplog.at_level(logging.WARNING):
                emergency_log("аварийный.путь", "WARNING", "маршрут сломан")
        finally:
            logger.shutdown()

        assert "маршрут сломан" in caplog.text
        written = (tmp_path / "system.log").read_text(encoding="utf-8")
        assert "маршрут сломан" not in written, "аварийная запись ушла через менеджер — это рекурсия"

    def test_never_raises(self) -> None:
        """Падать здесь запрещено: деть исключение отсюда уже некуда."""
        emergency_log("аварийный.путь", "НЕТ_ТАКОГО_УРОВНЯ", "кривой уровень")
        emergency_log("аварийный.путь", "ERROR", "кривой шаблон %d", "не число")

    def test_unknown_level_still_writes(self, caplog: pytest.LogCaptureFixture) -> None:
        """Опечатка в уровне не имеет права проглотить аварийное сообщение."""
        with caplog.at_level(logging.WARNING):
            emergency_log("аварийный.путь", "варнинг", "опечатка в уровне")

        assert "опечатка в уровне" in caplog.text


def test_no_writer_left_behind() -> None:
    """Handle не должен обрастать собственной логикой записи.

    Страж против отката: если у ``FallbackLogger`` снова появится своё
    форматирование или свой резолв менеджера, он опять станет писателем, а
    правки имени снова придётся делать в двух местах (урок Ф2.1 — один дефект,
    три починки).
    """
    forbidden: List[str] = [
        name
        for name in ("_fmt", "_lm", "_stdlib")
        if hasattr(FallbackLogger, name) or name in getattr(FallbackLogger, "__slots__", ())
    ]
    assert forbidden == [], f"у handle снова появилась своя логика записи: {forbidden}"
