# -*- coding: utf-8 -*-
"""Тесты StdLoggerFacade — моста «stdlib-стиль» → LoggerManager.

Ключевой инвариант: сообщение не исчезает ни в одном из режимов.
Есть LoggerManager — пишем в него; нет — в stdlib, но не в никуда.
"""

from __future__ import annotations

import gc
import logging
import sys
import threading
import weakref
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
        #
        # Отложенное сообщение (``Callable``) резолвится здесь, как это делает
        # настоящий ``LoggerCore.log`` — после гейта и ровно один раз. Без этого
        # фейк складывал бы в ``records`` само замыкание, и любая проверка
        # текста на пути ``exc_info`` (6.1) сравнивала бы строку с функцией.
        resolved = message() if callable(message) else message
        self.records.append((level, apply_format(resolved, args), module))
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

    def test_closed_manager_stops_being_the_process_logger(
        self, tmp_path: Path, monkeypatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Закрытый менеджер обязан ОТЦЕПИТЬСЯ, а не остаться синглтоном (Ф6.8).

        До правки ``LoggerManager._instance`` переживал собственный
        ``shutdown()``: ``get_logger()`` продолжал отдавать труп, и всё, что
        писало через связанный вид, уходило в закрытые каналы — молча. Пока на
        виде жили два вызывающих, это не всплывало; переезд ``QueueRegistry`` на
        вид (6.8) сделал дефект наблюдаемым — записи о потере кадров начали
        исчезать в прогоне, где до этого успел закрыться чужой менеджер.

        Пара: пока менеджер жив — пишем в файл; после ``shutdown`` — в
        stdlib-фолбэк, но НЕ в никуда.
        """
        monkeypatch.setattr(LoggerManager, "_instance", None)
        bump_observability_epoch()

        manager = LoggerManager(config=_real_config(tmp_path))
        facade = StdLoggerFacade("gui")
        assert facade.warning("при живом менеджере") is True
        manager.shutdown()

        assert get_logger() is None, "закрытый менеджер остался процессным логгером"
        with caplog.at_level("WARNING"):
            assert facade.warning("после закрытия") is False, "вид всё ещё пишет в закрытый менеджер"
        assert "после закрытия" in caplog.text, "запись после закрытия исчезла совсем"

        written = (tmp_path / "system.log").read_text(encoding="utf-8")
        assert "при живом менеджере" in written
        assert "после закрытия" not in written


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


class TestExcInfoHazards:
    """6.1, тесты АВТОРА: опасные места самого механизма отложенного traceback'а.

    Контрактные проверки (принимает ли фасад ``exc_info``/``extra``, что видно в
    тексте) живут в ``test_std_facade_kwargs.py`` и написаны независимо. Здесь —
    только то, что видно изнутри устройства: захват разъехался с рендером во
    времени, и у этого разъезда четыре способа сломаться.
    """

    def test_traceback_survives_rendering_after_the_except_block_ended(self, fake_lm: _FakeLoggerManager) -> None:
        """Главный хазард: рендер идёт ПОЗЖЕ, а ``sys.exc_info()`` к тому моменту пуст.

        Отложенность и означает, что сообщение соберут не в кадре ``except``.
        Фейк здесь нарочно откладывает вызов ``message()`` до выхода из
        обработчика — если бы фасад захватывал исключение лениво (внутри
        замыкания), traceback пропал бы именно так, а не в тесте, где всё
        происходит на одной строке.
        """
        pending: list = []
        fake_lm.log = lambda scope, level, message, module="main", *a, **k: pending.append(message)  # type: ignore[assignment]

        facade = StdLoggerFacade("gui")
        try:
            raise ValueError("бум из except")
        except ValueError:
            facade.error("операция упала", exc_info=True)

        assert sys.exc_info()[0] is None, "тест обязан рендерить УЖЕ вне обработчика"
        text = pending[0]() if callable(pending[0]) else pending[0]
        assert "ValueError: бум из except" in text, (
            "захват exc_info оказался ленивым: к моменту рендера исключение уже размотано"
        )

    def test_thread_without_its_own_exception_does_not_borrow_a_foreign_one(self, fake_lm: _FakeLoggerManager) -> None:
        """``sys.exc_info()`` — состояние ПОТОКА, и чужое исключение брать нельзя.

        Пока главный поток стоит в ``except``, рабочий поток пишет свою запись с
        ``exc_info=True``. Своего исключения у него нет — значит и traceback'а
        быть не должно. Иначе запись обвинила бы посторонний код.
        """
        facade = StdLoggerFacade("gui")
        done = threading.Event()

        def _worker() -> None:
            facade.warning("из чужого потока", exc_info=True)
            done.set()

        try:
            raise RuntimeError("исключение главного потока")
        except RuntimeError:
            thread = threading.Thread(target=_worker, daemon=True)
            thread.start()
            assert done.wait(timeout=5.0), "поток не дошёл до записи — тест обязан падать, а не висеть"
            thread.join(timeout=5.0)

        text = fake_lm.records[0][1]
        assert text == "из чужого потока", f"поток подобрал чужое исключение: {text!r}"

    def test_percent_in_traceback_does_not_corrupt_the_text(self, fake_lm: _FakeLoggerManager) -> None:
        """Traceback содержит исходник — а в нём бывают свои ``%``.

        Порядок «сначала ``%``-формат, потом склейка с traceback'ом» выбран
        именно поэтому. Обратный порядок прошёлся бы ``%`` по тексту
        исключения: аргументов не хватило бы, и ``apply_format`` отдал бы
        шаблон целиком — то есть запись потеряла бы подставленные значения.
        """
        facade = StdLoggerFacade("gui")
        try:
            raise ValueError("прогресс 50%s и ещё %d")
        except ValueError:
            facade.error("код %s", 42, exc_info=True)

        text = fake_lm.records[0][1]
        assert "код 42" in text, f"аргумент не подставился: {text!r}"
        assert "прогресс 50%s и ещё %d" in text, f"текст исключения покорёжен: {text!r}"

    def test_view_does_not_retain_the_exception_after_the_record(self, fake_lm: _FakeLoggerManager) -> None:
        """Замыкание держит кадры стека — но только на время вызова ``log()``.

        Traceback тянет за собой локальные переменные всех кадров: кадры GUI,
        массивы numpy, объекты Qt. Если бы вид сохранил замыкание (кэш
        «последней ошибки», ссылка на вызов), каждая ошибка удерживала бы этот
        хвост до следующей — утечка того же класса, что и в Ф0.3.
        """

        class _Tracked(Exception):
            """Своё исключение: на встроенный ``ValueError`` weakref не ставится."""

        # Приёмник СРАЗУ резолвит сообщение и хранит только текст — как
        # настоящий менеджер, у которого в ``LogRecord`` лежит строка. Дубль из
        # фикстуры сохраняет ещё и сам объект сообщения (``raw``), то есть
        # замыкание, и тест мерил бы удержание фейком, а не видом.
        texts: list[str] = []
        fake_lm.log = lambda scope, level, message, module="main", *a, **k: texts.append(  # type: ignore[assignment]
            message() if callable(message) else message
        )

        facade = StdLoggerFacade("gui")
        try:
            raise _Tracked("временное")
        except _Tracked as caught:
            facade.error("упало", exc_info=True)
            ref = weakref.ref(caught)

        gc.collect()
        assert ref() is None, "вид удержал исключение вместе со всеми кадрами стека"

    def test_reserved_extra_key_does_not_raise_from_inside_except(self, fake_lm: _FakeLoggerManager) -> None:
        """``extra={"module": …}`` — столкновение с позиционным именем ``log()``.

        Без разведения это ``TypeError: got multiple values for argument
        'module'``, брошенный ИЗ обработчика ошибки: исходное исключение
        подменяется отказом логгера. Ровно тот класс, ради которого 6.1 стоит
        гейтом перед кодмодом.
        """
        seen: dict = {}
        fake_lm.log = lambda scope, level, message, module="main", *a, **k: seen.update(k)  # type: ignore[assignment]

        facade = StdLoggerFacade("gui")
        try:
            raise ValueError("исходное")
        except ValueError:
            facade.error("упало", extra={"module": "чужое", "trace_id": "abc"})

        assert seen["trace_id"] == "abc", "обычный ключ не доехал"
        assert seen["module_"] == "чужое", f"столкнувшийся ключ потерян: {seen!r}"

    def test_fallback_survives_reserved_extra_key(self, no_lm: None, caplog: pytest.LogCaptureFixture) -> None:
        """У stdlib свой список зарезервированных имён — фолбэк тоже не имеет права падать.

        ``logging`` кидает ``KeyError`` на ``extra={"message": …}``. Фолбэк
        работает ровно тогда, когда менеджера нет (ранний старт, авария), —
        уронить в этот момент вызывающего значит потерять и исходную ошибку.
        """
        with caplog.at_level("WARNING"):
            assert StdLoggerFacade("gui").warning("шаблон", extra={"message": "x"}) is False

        assert "шаблон" in caplog.text


class TestDeferredTracebackCost:
    """Отложенность как ЦЕНА, а не как текст: пара «гейт закрыт / гейт открыт».

    Проверка идёт по наблюдаемому эффекту — исключение считает, сколько раз его
    превращали в строку. Шпион на имя ``traceback.format_exception`` сторожил бы
    имя функции: замена на ``TracebackException`` оставила бы его зелёным, а
    цену — на месте.
    """

    class _CountingError(Exception):
        calls = 0

        def __str__(self) -> str:
            type(self).calls += 1
            return "дорогое исключение"

    @pytest.fixture(autouse=True)
    def _reset(self):
        TestDeferredTracebackCost._CountingError.calls = 0
        yield

    def _manager(self, tmp_path: Path) -> LoggerManager:
        mgr = LoggerManager(
            manager_name="DeferProbe",
            config={
                "app_name": "defer",
                "log_directory": str(tmp_path),
                "enable_batching": False,
                "modules": {},
                "channels": {"a": {"type": "file", "enabled": True, "file_path": str(tmp_path / "a.log")}},
                "scopes": {
                    "SYSTEM": {"enabled": True, "min_level": "WARNING", "channels": ["a"]},
                    "DEBUG": {"enabled": False, "min_level": "DEBUG", "channels": ["a"]},
                },
            },
        )
        mgr.initialize()
        return mgr

    def test_rejected_record_does_not_render_the_traceback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Гейт закрыт (DEBUG выключен) — ``format_exception`` не звался ни разу."""
        mgr = self._manager(tmp_path)
        monkeypatch.setattr(std_facade, "get_logger", lambda: mgr)
        bump_observability_epoch()
        try:
            try:
                raise self._CountingError()
            except self._CountingError:
                StdLoggerFacade("probe").debug("отклонённая", exc_info=True)
        finally:
            mgr.shutdown()

        assert self._CountingError.calls == 0, "traceback собран ДО гейта — отложенность 6.1 не работает"

    def test_accepted_record_does_render_the_traceback(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Вторая половина пары: при открытом гейте рендер обязан произойти.

        Без неё первый тест зелен и на фасаде, который ``exc_info`` просто
        игнорирует, — «молчащий детектор не доказывает».
        """
        mgr = self._manager(tmp_path)
        monkeypatch.setattr(std_facade, "get_logger", lambda: mgr)
        bump_observability_epoch()
        try:
            try:
                raise self._CountingError()
            except self._CountingError:
                StdLoggerFacade("probe").warning("принятая", exc_info=True)
            mgr.flush()
        finally:
            mgr.shutdown()

        assert self._CountingError.calls > 0, "traceback не собран и на принятой записи"
        written = (tmp_path / "a.log").read_text(encoding="utf-8")
        assert "дорогое исключение" in written, f"traceback не доехал до файла: {written!r}"


class TestFactory:
    def test_same_module_returns_same_instance(self) -> None:
        assert get_std_logger("gui") is get_std_logger("gui")

    def test_different_modules_are_distinct(self) -> None:
        assert get_std_logger("gui") is not get_std_logger("trace")
        assert get_std_logger("trace").module == "trace"
