# -*- coding: utf-8 -*-
"""Тесты StdLoggerFacade — моста «stdlib-стиль» → LoggerManager.

Ключевой инвариант: сообщение не исчезает ни в одном из режимов.
Есть LoggerManager — пишем в него; нет — в stdlib, но не в никуда.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest

from multiprocess_framework.modules.logger_module.adapters import std_facade
from multiprocess_framework.modules.logger_module.adapters.std_facade import (
    StdLoggerFacade,
    get_std_logger,
)
from multiprocess_framework.modules.logger_module.core.log_config import (
    LoggerChannelSchema,
    LoggerManagerConfig,
    LoggerScopeSchema,
    LogLevel,
    LogScope,
)
from multiprocess_framework.modules.logger_module.core.logger_core import bump_observability_epoch
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager, get_logger
from multiprocess_framework.modules.logger_module.utils import apply_format


def _real_config(directory: "Path") -> LoggerManagerConfig:
    """Настоящий менеджер с одним файловым каналом и без батчинга.

    Нужен там, где проверка обязана идти по артефакту: фейк доказывает форму
    вызова, файл — что запись доехала.
    """
    return LoggerManagerConfig(
        app_name="std_facade",
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
            for scope in ("SYSTEM", "BUSINESS", "PERFORMANCE", "DEBUG")
        },
    )


class _FakeLoggerManager:
    """Минимальный дубль LoggerManager: собирает (level, message, module).

    Ф1.5: сигнатура повторяет реальную — ``(message, module="main", *args)``.
    Форматирование фейк НЕ делает и делать не должен: с Ф1.4 ``%`` применяет
    менеджер уже за гейтом, и фейк, склеивающий строку сам, доказывал бы
    поведение фейка. Тесты на фактическую склейку живут там, где проводка
    настоящая — ``test_lazy_message.py::TestStdFacadeGatesBeforeFormatting``.
    """

    def __init__(self) -> None:
        self.records: list[tuple[str, str, str]] = []
        self.raw: list[tuple[str, str, str, tuple]] = []
        #: Пары (scope, level), с которыми пришёл связанный вид (2.2).
        self.scopes: list[tuple[LogScope, LogLevel]] = []
        #: Сколько раз запись пришла через удобный метод, а не через ``log()``.
        self.used_convenience: int = 0

    def _capture_convenience(self, level: str, message: str, module: str, args: tuple = ()) -> None:
        self.used_convenience += 1
        self._capture(level, message, module, args)

    def _capture(self, level: str, message: str, module: str, args: tuple = ()) -> None:
        # ``records`` хранит СКЛЕЕННЫЙ текст (как его увидит канал), ``raw`` —
        # то, что фасад передал на самом деле. Первое удобно проверять, второе
        # доказывает, что фасад ничего не склеил заранее.
        self.records.append((level, apply_format(message, args), module))
        self.raw.append((level, message, module, args))

    def debug(self, message: str, module: str = "main", *args: Any, **_extra: Any) -> None:
        self._capture_convenience("debug", message, module, args)

    def info(self, message: str, module: str = "main", *args: Any, **_extra: Any) -> None:
        self._capture_convenience("info", message, module, args)

    def warning(self, message: str, module: str = "main", *args: Any, **_extra: Any) -> None:
        self._capture_convenience("warning", message, module, args)

    def error(self, message: str, module: str = "main", *args: Any, **_extra: Any) -> None:
        self._capture_convenience("error", message, module, args)

    def critical(self, message: str, module: str = "main", *args: Any, **_extra: Any) -> None:
        self._capture_convenience("critical", message, module, args)

    def log(
        self,
        scope: LogScope,
        level: LogLevel,
        message: str,
        module: str = "main",
        *args: Any,
        **_extra: Any,
    ) -> None:
        """Путь, которым ходит связанный вид (2.2) — с парой (scope, level).

        Удобные методы выше ОСТАВЛЕНЫ намеренно, хотя вид их больше не зовёт:
        ``used_convenience`` ловит откат к ним, а вместе с ним и возврат
        219 нс на запись. Убрать их — значит потерять этот сигнал: вид,
        сползший обратно на ``debug()``, упал бы с ``AttributeError``, и
        причина читалась бы как «фейк неполный», а не «регресс».
        """
        self.scopes.append((scope, level))
        self._capture(level.value.lower(), message, module, args)


@pytest.fixture
def fake_lm(monkeypatch: pytest.MonkeyPatch) -> _FakeLoggerManager:
    """Подменить get_logger() внутри фасада на фейковый менеджер.

    2.2: вид связывается один раз и сверяется по эпохе — подмена ``get_logger``
    сама по себе его больше не переубедит. Поднимаем эпоху, иначе фикстура
    молча не действовала бы на вид, созданный в предыдущем тесте.
    """
    lm = _FakeLoggerManager()
    monkeypatch.setattr(std_facade, "get_logger", lambda: lm)
    bump_observability_epoch()
    return lm


@pytest.fixture
def no_lm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Режим «LoggerManager не поднят»."""
    monkeypatch.setattr(std_facade, "get_logger", lambda: None)
    bump_observability_epoch()


class TestRoutingToLoggerManager:
    """Есть LoggerManager — запись уходит в него с нужным module."""

    @pytest.mark.parametrize("level", ["debug", "info", "warning", "error", "critical"])
    def test_each_level_reaches_manager(self, fake_lm: _FakeLoggerManager, level: str) -> None:
        facade = StdLoggerFacade("gui")

        assert getattr(facade, level)("сообщение") is True

        assert fake_lm.records == [(level, "сообщение", "gui")]

    def test_percent_args_formatted(self, fake_lm: _FakeLoggerManager) -> None:
        """%-аргументы склеиваются, как в stdlib — но уже в менеджере (Ф1.5)."""
        StdLoggerFacade("gui").warning("процесс '%s' не найден (код %d)", "pult", 42)

        assert fake_lm.records[0][1] == "процесс 'pult' не найден (код 42)"

    def test_template_and_args_are_handed_over_unformatted(self, fake_lm: _FakeLoggerManager) -> None:
        """Ф1.5: фасад НЕ склеивает — иначе гейт менеджера уже опоздал.

        Здесь проверяется именно граница «фасад → менеджер»: шаблон приходит
        целым, аргументы отдельно. Что склейка потом действительно происходит,
        доказывает предыдущий тест и запись на диск в test_lazy_message.py.
        """
        StdLoggerFacade("gui").warning("процесс '%s' не найден (код %d)", "pult", 42)

        assert fake_lm.raw[0] == (
            "warning",
            "процесс '%s' не найден (код %d)",
            "gui",
            ("pult", 42),
        )

    def test_module_is_passed_through(self, fake_lm: _FakeLoggerManager) -> None:
        StdLoggerFacade("trace").info("x")

        assert fake_lm.records[0][2] == "trace"

    def test_broken_format_does_not_swallow_message(self, fake_lm: _FakeLoggerManager) -> None:
        """Кривой формат — не повод потерять запись целиком."""
        StdLoggerFacade("gui").warning("нет плейсхолдеров", "лишний")

        assert len(fake_lm.records) == 1
        assert "нет плейсхолдеров" in fake_lm.records[0][1]
        assert "лишний" in fake_lm.records[0][1]


class TestFallbackWithoutManager:
    """Нет LoggerManager — stdlib, а не тишина (иначе это второй проглот)."""

    def test_falls_back_to_stdlib(self, no_lm: None, caplog: pytest.LogCaptureFixture) -> None:
        facade = StdLoggerFacade("gui")

        with caplog.at_level(logging.WARNING, logger="mpf.gui"):
            emitted_to_manager = facade.warning("расхождение конфига и рантайма")

        assert emitted_to_manager is False, "без менеджера возвращаем False — запись ушла в фолбэк"
        assert "расхождение конфига и рантайма" in caplog.text

    def test_fallback_logger_name_is_derived_from_module(self, no_lm: None) -> None:
        assert StdLoggerFacade("camera")._fallback.name == "mpf.camera"

    def test_explicit_fallback_name(self, no_lm: None) -> None:
        assert StdLoggerFacade("gui", fallback_name="custom")._fallback.name == "custom"


class TestLazyResolve:
    """Фасад создаётся до init_logging — связка обязана появиться позже.

    2.2 сменила механизм: раньше ``get_logger()` звался на КАЖДОЙ записи, теперь
    вид связывается один раз и пересвязывается по эпохе наблюдаемости. Поэтому
    проверка переехала с фейка на **реальный** ``LoggerManager``: подмена
    ``get_logger`` доказывала бы, что эпоха поднимается, когда её поднял сам
    тест, а нужно — что её поднимает продовый путь (``LoggerManager.__init__``).
    """

    def test_manager_appearing_later_is_picked_up(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(LoggerManager, "_instance", None)
        bump_observability_epoch()

        facade = StdLoggerFacade("gui")  # создан, когда менеджера ещё нет
        assert facade.warning("до init") is False, "без менеджера обязан быть фолбэк"

        logger = LoggerManager(config=_real_config(tmp_path))
        try:
            assert facade.warning("после init") is True, (
                "вид не заметил появления менеджера — эпоха не поднялась в LoggerManager.__init__"
            )
        finally:
            logger.shutdown()

        # Артефакт, а не возврат True: «ушло в менеджер» и «легло в файл» —
        # разные факты, и вся фаза стоит на том, что судить надо по второму.
        written = (tmp_path / "system.log").read_text(encoding="utf-8")
        assert "после init" in written
        assert "до init" not in written, "фолбэк-запись не имела права попасть в файл менеджера"

    def test_rebinds_after_the_manager_is_replaced(self, tmp_path: Path, monkeypatch) -> None:
        """Смена процессного менеджера обязана переключить уже живой вид.

        Без этого вид продолжил бы писать в закрытый менеджер — записи
        исчезали бы молча, и ровно в тот момент, когда систему переконфигурируют
        (switch рецепта, reconfigure), то есть когда логи нужнее всего.
        """
        monkeypatch.setattr(LoggerManager, "_instance", None)
        bump_observability_epoch()

        first = LoggerManager(config=_real_config(tmp_path / "первый"))
        facade = StdLoggerFacade("gui")
        facade.warning("в первый")
        first.shutdown()

        second = LoggerManager(config=_real_config(tmp_path / "второй"))
        try:
            facade.warning("во второй")
        finally:
            second.shutdown()

        assert "в первый" in (tmp_path / "первый" / "system.log").read_text(encoding="utf-8")
        written = (tmp_path / "второй" / "system.log").read_text(encoding="utf-8")
        assert "во второй" in written, "вид остался связан с закрытым менеджером"
        assert "в первый" not in written


class TestExceptionAndLog:
    def test_exception_appends_traceback(self, fake_lm: _FakeLoggerManager) -> None:
        facade = StdLoggerFacade("gui")
        try:
            raise ValueError("бум")
        except ValueError:
            facade.exception("операция упала")

        level, message, _ = fake_lm.records[0]
        assert level == "error"
        assert "операция упала" in message
        assert "ValueError: бум" in message, "traceback обязан попасть в текст: exc_info у LM нет"

    def test_exception_outside_handler_has_no_traceback_noise(self, fake_lm: _FakeLoggerManager) -> None:
        """Вне except traceback пустой — не приклеивать 'NoneType: None'."""
        StdLoggerFacade("gui").exception("просто ошибка")

        assert fake_lm.records[0][1] == "просто ошибка"

    def test_log_with_string_level(self, fake_lm: _FakeLoggerManager) -> None:
        StdLoggerFacade("gui").log("WARNING", "смешанный регистр")

        assert fake_lm.records[0][0] == "warning"

    def test_unknown_level_degrades_to_info(self, fake_lm: _FakeLoggerManager) -> None:
        """Опечатка в уровне не должна ронять или глотать запись."""
        StdLoggerFacade("gui").log("warninng", "опечатка")

        assert fake_lm.records[0] == ("info", "опечатка", "gui")


class TestBoundView:
    """2.2 — вид связан: зовёт ``log()`` напрямую и знает свою пару (scope, level)."""

    def test_view_does_not_go_through_the_convenience_method(self, fake_lm: _FakeLoggerManager) -> None:
        """Удобный метод стоит 219 нс на переупаковке — вид обязан его миновать.

        Считается ФАКТ вызова, а не имя метода в коде: подмена ``debug`` на
        эквивалент оставила бы проверку по имени зелёной, а цену — на месте.
        """
        facade = StdLoggerFacade("gui")
        for level in ("debug", "info", "warning", "error", "critical"):
            getattr(facade, level)("x")

        assert fake_lm.used_convenience == 0, "вид сполз обратно на удобные методы менеджера"
        assert len(fake_lm.scopes) == 5

    def test_scope_agrees_with_what_the_real_manager_would_choose(self, tmp_path: Path, monkeypatch) -> None:
        """Таблица вида согласна с ПОВЕДЕНИЕМ менеджера, а не с копией таблицы.

        Вид резолвит «уровень → скоуп» сам, и это ровно та развилка, где
        появляется второй гейт. Поэтому сверяется не с ``_LEVEL_DEFAULT_SCOPE``
        (это была бы проверка таблицы против себя же), а с тем, что реально
        передаёт в ``log()`` удобный метод настоящего ``LoggerManager``.
        """
        seen: list[tuple[LogScope, LogLevel]] = []

        class _SpyManager(LoggerManager):
            def log(self, scope, level, message, module="main", *args, **extra):  # type: ignore[override]
                seen.append((scope, level))
                return super().log(scope, level, message, module, *args, **extra)

        monkeypatch.setattr(LoggerManager, "_instance", None)
        bump_observability_epoch()
        logger = _SpyManager(config=_real_config(tmp_path))
        facade = StdLoggerFacade("gui")
        try:
            for level in ("debug", "info", "warning", "error", "critical"):
                seen.clear()
                getattr(logger, level)("через удобный метод")
                by_manager = list(seen)

                seen.clear()
                getattr(facade, level)("через вид")
                by_view = list(seen)

                assert by_view == by_manager, (
                    f"уровень {level!r}: вид выбрал {by_view}, менеджер — {by_manager}; "
                    "таблица скоупов вида разошлась с поведением менеджера"
                )
        finally:
            logger.shutdown()

    def test_epoch_check_costs_nothing_when_nothing_changed(self, fake_lm: _FakeLoggerManager) -> None:
        """Пересвязка происходит ОДИН раз, а не на каждой записи.

        Иначе вид не «связанный», а прежний ленивый с лишним сравнением.
        """
        calls = {"n": 0}

        def _counting_get_logger():
            calls["n"] += 1
            return fake_lm

        std_facade.get_logger = _counting_get_logger  # type: ignore[assignment]
        try:
            facade = StdLoggerFacade("gui")
            for _ in range(50):
                facade.info("x")
        finally:
            std_facade.get_logger = get_logger  # type: ignore[assignment]

        assert calls["n"] == 1, f"резолв менеджера произошёл {calls['n']} раз вместо одного"


class TestFactory:
    def test_same_module_returns_same_instance(self) -> None:
        assert get_std_logger("gui") is get_std_logger("gui")

    def test_different_modules_are_distinct(self) -> None:
        assert get_std_logger("gui") is not get_std_logger("trace")
        assert get_std_logger("trace").module == "trace"
