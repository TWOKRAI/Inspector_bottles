# -*- coding: utf-8 -*-
"""Приёмочная сюита RED (Task 1.1, plans/observability-closure/phase-1-invisible-failures.md).

Контракт — в спеке задачи (раздел «Контракт»), а не в отдельном interface.py
(MODULE_CONTRACT: new-lite). Источник истины для критериев A1–A8 — модуль
``multiprocess_framework/modules/logger_module/core/process_hooks.py``,
которого на этом HEAD ЕЩЁ НЕТ.

**Почему импорт ``process_hooks`` — ЛОКАЛЬНЫЙ, внутри каждого теста, а не
наверху файла.** Критерий A7 (класс :class:`TestA7ProcessModuleWiresHooks`)
обязан краснеть ``AssertionError`` («хуки не установлены»), а не
``ImportError`` модуля, которого ещё нет: у него другой предмет проверки —
проводка внутри ``ProcessModule.initialize()``/``shutdown()``, а не сам
``process_hooks``. Импорт на уровне модуля убивает СБОР всего файла разом
(``ModuleNotFoundError`` на collection), и pytest перестаёт видеть отдельные
тесты — A7 в такой сборке получил бы чужую причину красного. Поэтому каждый
тест, которому нужен ``process_hooks``, импортирует его сам, первой строкой
тела; единственное исключение — A7 (класс :class:`TestA7ProcessModuleWiresHooks`),
который вообще обходится без этого импорта (проверяет только идентичность
трёх глобальных хуков вокруг ``ProcessModule.initialize()``/``shutdown()``).
A8 (:class:`TestA8DiagCommands`) импорт использует, как и A1–A6, — там
``ModuleNotFoundError`` тоже правильная причина красного, см. докстринг класса
про смену полярности с ``pytest.raises(KeyError)``.

**Структурное свойство стора, не часть контракта задачи.** Через
``StoreTapChannel.write`` (``context: record_dict.get("extra", {})``) и
``hub_record_to_display`` (всё, что не «конверт» kind/process/module/ts/
severity/message — в extra) ЛЮБАЯ запись, прошедшая тег-стор, получает свои
поля extra ОДНИМ уровнем глубже, под ключом ``"context"``:
``row["extra"]["context"]["thread"]``, не ``row["extra"]["thread"]``.
Проверено скретч-прогоном на реальных ``ErrorManager``/``LoggerManager``/
``ObservabilityStore`` этого HEAD (не выведено из process_hooks — того, что
этот файл тестирует, а из уже существующего, независимого кода: tap+store).
Ту же обёртку даёт и ``track_error``'s собственный приём: ключ ``"context"``
внутри переданного словаря НЕ выталкивается, а остаётся среди extra-полей
(см. докстринг ``ErrorManager.track_error``) — отсюда у error-записей внутри
``extra["context"]`` СВОЙ вложенный ``"context"`` (сайт-тег), а не только
``thread``/``traceback``/``hook``.

Ни один тест не проверяет и не может проверить: реальный IPC до дочернего
процесса, гейт уровней наблюдаемости, троттл health (5 с) — эти свойства вне
досягаемости юнит-харнесса (см. отчёт тестировщика, раздел «недостижимо»).
"""

from __future__ import annotations

import sys
import threading
import uuid
import warnings
from unittest.mock import Mock

import pytest

from multiprocess_framework.modules.error_module.core.error_manager import ErrorManager
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.process_module.commands.builtin_commands import BuiltinCommands
from multiprocess_framework.modules.process_module.core.process_module import ProcessModule
from multiprocess_framework.modules.process_module.health.state import HealthState
from multiprocess_framework.modules.process_module.managers.observability_wiring import wire_observability_store


# ---------------------------------------------------------------------------
# Общие хелперы
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _restore_global_hooks():
    """Страховка поверх ``hooks.uninstall()`` каждого теста (правило задачи).

    Снимает три глобальных хука к значению ДО теста НЕЗАВИСИМО от того, что
    случилось внутри — иначе тест, упавший до собственной уборки, протекает в
    соседей по файлу.
    """
    prev_threading = threading.excepthook
    prev_sys = sys.excepthook
    prev_warn = warnings.showwarning
    yield
    threading.excepthook = prev_threading
    sys.excepthook = prev_sys
    warnings.showwarning = prev_warn


def _manager_config(tmp_path, app: str) -> dict:
    """Тот же конфиг для LoggerManager/ErrorManager, что в test_incident_pair_carries_source.py."""
    return {
        "app_name": app,
        "log_directory": str(tmp_path),
        "enable_batching": False,
        "modules": {},
        "channels": {"a": {"type": "file", "enabled": True, "file_path": str(tmp_path / f"{app}.log")}},
        "scopes": {
            "SYSTEM": {"channels": ["a"]},
            "BUSINESS": {"channels": ["a"]},
            "DEBUG": {"channels": ["a"]},
        },
    }


def _raise_named_error(message: str) -> None:
    """Именованная (НЕ lambda) цель потока — её имя обязано попасть в traceback."""
    raise RuntimeError(message)


def _join_or_fail(thread: threading.Thread, timeout: float = 5.0) -> None:
    thread.join(timeout=timeout)
    assert not thread.is_alive(), f"поток {thread.name!r} завис вместо падения — хук не имеет права блокировать"


class _FakeCommandManager:
    """Тот же приём, что в test_observability_commands.py: dispatch — обычный
    dict[command], KeyError на незарегистрированном имени (а не на молчаливый
    no-op) — ровно то, что нужно A8 для правильной причины красного."""

    def __init__(self) -> None:
        self.handlers: dict = {}

    def register_command(self, name, handler, metadata=None, tags=None) -> None:
        self.handlers[name] = handler

    def dispatch(self, command: str, data: dict | None = None):
        return self.handlers[command](data or {})


def _dispatch_with_timeout(cm, command: str, data: dict, timeout: float = 5.0):
    """dispatch через watchdog-поток — A8 обязан не виснуть, даже если будущая
    diag.* реализация внутри сама держит поток и ждёт (контракт п.10: «≤ 2 с»,
    но это обещание реализации, а не гарантия теста). Исключение диспетчера
    (сегодня — KeyError) пробрасывается наружу как есть, роняя тест."""
    box: dict = {}

    def _run() -> None:
        try:
            box["value"] = cm.dispatch(command, data)
        except BaseException as exc:  # noqa: BLE001 — прокинуть наружу, не проглотить
            box["error"] = exc

    thread = threading.Thread(target=_run, name=f"dispatch-{command}", daemon=True)
    thread.start()
    thread.join(timeout=timeout)
    assert not thread.is_alive(), f"{command} завис вместо ответа за {timeout} с"
    if "error" in box:
        raise box["error"]
    return box["value"]


class _FakeServices:
    """Утиный протокол ``services`` из контракта (report_error/_log_warning/get_manager/name)
    + минимум, нужный ``BuiltinCommands`` (command_manager/get_config/_log_debug/_log_info) —
    один фейк на весь файл, чтобы A8 могла ставить настоящие хуки на ТОТ ЖЕ
    services, на котором регистрирует команды (без этого diag.* негде было бы
    брать thread_exceptions/warnings_captured — счётчики живут на hooks,
    привязанных к конкретному services).

    ``report_error`` держит все три обещания контракта («health-счётчик +
    плоскость ошибок + строка журнала»), не полагаясь на
    ``HealthState.report_error(**fields)`` — которого на этом HEAD ещё нет
    (задача его тоже не вводит: контракт называет это будущим свойством
    ``ProcessModule.report_error``, не общего утиного протокола ``services``).
    Поэтому health и error_manager наполняются РАЗДЕЛЬНО, но за один вызов:
    ``self.health`` — чистый счётчик (без track-колбэка — иначе тот же
    инцидент ушёл бы в error_manager ВТОРОЙ раз, уже без полей), а
    ``error_manager.track_error`` получает словарь ровно той формы, которую
    контракт называет для будущего ``HealthState._track_error``:
    ``{"context": ctx, **fields}``.
    """

    def __init__(self, name: str, *, error_manager=None, logger_manager=None) -> None:
        self.name = name
        self._error_manager = error_manager
        self._logger_manager = logger_manager
        self.health = HealthState()
        self.command_manager = _FakeCommandManager()
        self._config: dict = {}

    def report_error(self, exc: BaseException, context: str | None = None, **fields) -> None:
        self.health.report_error(exc, context=context)
        if self._error_manager is not None:
            ctx = {"module": self.name, "context": context, **fields}
            self._error_manager.track_error(exc, ctx)

    def _log_warning(self, message: str, **kwargs) -> None:
        if self._logger_manager is not None:
            self._logger_manager.warning(message, **kwargs)

    def get_manager(self, name: str):
        if name == "error":
            return self._error_manager
        return None

    def get_config(self, key, default=None):
        return self._config.get(key, default)

    def _log_debug(self, *a, **k) -> None: ...

    def _log_info(self, *a, **k) -> None: ...


# ---------------------------------------------------------------------------
# A1 — исключение в потоке → одна запись kind=error
# ---------------------------------------------------------------------------


class TestA1ThreadExceptionWritesOneErrorRecord:
    """A1: RuntimeError в потоке → ровно одна запись kind=error, extra.context.thread
    == имя потока, трасса называет вызвавшую функцию, оба счётчика (hooks и
    error_manager.get_stats()) сходятся на 1, health.error_count вырос на 1.

    Красный на этом HEAD: ``ModuleNotFoundError`` на локальном импорте
    ``process_hooks`` (модуля не существует).
    """

    @pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
    def test_thread_runtime_error_produces_single_error_row(self, tmp_path) -> None:
        from multiprocess_framework.modules.logger_module.core.process_hooks import install_process_hooks

        error_mgr = ErrorManager(manager_name="a1-error", config=_manager_config(tmp_path, "a1_error"))
        error_mgr.initialize()
        store, _taps = wire_observability_store(error_mgr, None, db_path=str(tmp_path / "obs_a1.db"), process="a1")
        services = _FakeServices("a1", error_manager=error_mgr)

        hooks = install_process_hooks(services)
        try:
            message = f"boom-{uuid.uuid4().hex}"
            thread = threading.Thread(target=_raise_named_error, args=(message,), name="hooked-worker", daemon=True)
            thread.start()
            _join_or_fail(thread)

            assert store.count() == 1
            assert store.count(kind="error") == 1
            rows = [r for r in store.list_records(kind="error") if message in r["message"]]
            assert len(rows) == 1, f"ожидалась ровно одна запись с {message!r}"
            row = rows[0]

            # Структурная обёртка стора (см. докстринг модуля) — поля лежат
            # под extra["context"], не extra напрямую.
            inner = row["extra"].get("context", {})
            assert inner.get("thread") == "hooked-worker", f"extra.context = {inner}"
            traceback_text = inner.get("traceback") or row["message"]
            assert "_raise_named_error" in traceback_text, "трасса не называет вызвавшую функцию"

            counters = hooks.counters()
            assert counters["thread_exceptions"] == 1
            assert error_mgr.get_stats()["thread_exceptions"] == 1
            assert services.health.error_count == 1
        finally:
            hooks.uninstall()
            store.close()
            error_mgr.shutdown()


# ---------------------------------------------------------------------------
# A2 — warnings.warn → одна запись kind=log
# ---------------------------------------------------------------------------


class TestA2WarningBecomesLogRecord:
    """A2: warnings.warn под simplefilter('always') → ровно одна запись kind=log,
    severity ('warning' — store нормализует регистр, см. store_tap.py:67, это
    НЕ переопределяется этой задачей), extra.context.category == 'UserWarning',
    warnings_captured == 1.

    Красный на этом HEAD: ``ModuleNotFoundError`` на локальном импорте.
    """

    def test_user_warning_produces_single_log_row_with_category(self, tmp_path) -> None:
        from multiprocess_framework.modules.logger_module.core.process_hooks import install_process_hooks

        logger_mgr = LoggerManager(manager_name="a2-logger", config=_manager_config(tmp_path, "a2_logger"))
        logger_mgr.initialize()
        store, _taps = wire_observability_store(
            None, logger_mgr, db_path=str(tmp_path / "obs_a2.db"), process="a2", min_level="WARNING"
        )
        services = _FakeServices("a2", logger_manager=logger_mgr)

        hooks = install_process_hooks(services)
        try:
            text = f"w-{uuid.uuid4().hex}"
            with warnings.catch_warnings():
                warnings.simplefilter("always")
                warnings.warn(text, UserWarning)

            rows = [r for r in store.list_records(kind="log") if text in r["message"]]
            assert len(rows) == 1, f"ожидалась ровно одна запись с {text!r}, получено {len(rows)}"
            row = rows[0]
            assert row["severity"] == "warning", f"severity = {row['severity']!r}"
            inner = row["extra"].get("context", {})
            assert inner.get("category") == "UserWarning", f"extra.context = {inner}"

            assert hooks.counters()["warnings_captured"] == 1
        finally:
            hooks.uninstall()
            store.close()
            logger_mgr.shutdown()


# ---------------------------------------------------------------------------
# A3 — дорога мертва (services.report_error бросает)
# ---------------------------------------------------------------------------


class TestA3DeadRoadCountsAsHookDeliveryFailure:
    """A3: services.report_error бросает → hook_delivery_failures==1 И
    thread_exceptions==1 (сам факт исключения в потоке всё равно посчитан),
    ERROR-запись в стандартном логгере ``process_hooks`` с именем потока
    (``caplog``). Тест не падает и не виснет (join с таймаутом).

    Красный на этом HEAD: ``ModuleNotFoundError`` на локальном импорте.
    """

    @pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
    def test_report_error_raising_counts_as_delivery_failure_and_logs_emergency(self, caplog) -> None:
        from multiprocess_framework.modules.logger_module.core.process_hooks import install_process_hooks

        class _BrokenServices:
            name = "a3-broken"

            def report_error(self, exc, context=None, **fields):
                raise RuntimeError("road is dead")

            def _log_warning(self, message, **kwargs):
                pass

            def get_manager(self, name):
                return None

        services = _BrokenServices()
        message = f"dead-road-{uuid.uuid4().hex}"
        thread_name = f"dead-road-worker-{uuid.uuid4().hex[:8]}"

        hooks = install_process_hooks(services)
        try:
            with caplog.at_level("ERROR", logger="multiprocess_framework.modules.logger_module.core.process_hooks"):
                thread = threading.Thread(target=_raise_named_error, args=(message,), name=thread_name, daemon=True)
                thread.start()
                _join_or_fail(thread)

            counters = hooks.counters()
            assert counters["hook_delivery_failures"] == 1
            assert counters["thread_exceptions"] == 1

            error_records = [r for r in caplog.records if r.levelname == "ERROR"]
            assert any(thread_name in r.getMessage() for r in error_records), (
                f"ожидалась ERROR-запись с именем потока {thread_name!r}, получено: "
                f"{[r.getMessage() for r in caplog.records]}"
            )
        finally:
            hooks.uninstall()


# ---------------------------------------------------------------------------
# A4 — снятые хуки не доставляют и не считают
# ---------------------------------------------------------------------------


class TestA4UninstallStopsDelivery:
    """A4: после uninstall() то же исключение НЕ растит счётчики и не пишет
    новых записей в стор, а stderr всё равно получает трассу (снятые хуки
    вернули дефолтный/прежний обработчик, печатающий в stderr).

    Красный на этом HEAD: ``ModuleNotFoundError`` на локальном импорте.
    """

    @pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
    def test_after_uninstall_counters_frozen_and_traceback_reaches_stderr(self, capfd, tmp_path) -> None:
        from multiprocess_framework.modules.logger_module.core.process_hooks import install_process_hooks

        error_mgr = ErrorManager(manager_name="a4-error", config=_manager_config(tmp_path, "a4_error"))
        error_mgr.initialize()
        store, _taps = wire_observability_store(error_mgr, None, db_path=str(tmp_path / "obs_a4.db"), process="a4")
        services = _FakeServices("a4", error_manager=error_mgr)

        try:
            hooks = install_process_hooks(services)
            hooks.uninstall()
            assert hooks.installed is False

            before_counters = dict(hooks.counters())
            before_store_count = store.count()

            message = f"after-uninstall-{uuid.uuid4().hex}"
            thread = threading.Thread(
                target=_raise_named_error, args=(message,), name="after-uninstall-worker", daemon=True
            )
            thread.start()
            _join_or_fail(thread)

            assert hooks.counters() == before_counters
            assert store.count() == before_store_count

            captured = capfd.readouterr()
            assert "Traceback" in captured.err, "снятый хук обязан вернуть трассу в stderr дефолтным путём"
        finally:
            store.close()
            error_mgr.shutdown()


# ---------------------------------------------------------------------------
# A5 — двойной install идемпотентен
# ---------------------------------------------------------------------------


class TestA5DoubleInstallIsIdempotent:
    """A5: повторный install_process_hooks на установленных хуках — тот же
    объект; хуки не наслаиваются (одно исключение → одна запись); после
    uninstall() — три хука ``is`` тем, что было до установки.

    Красный на этом HEAD: ``ModuleNotFoundError`` на локальном импорте.
    """

    def test_second_install_returns_the_same_instance(self) -> None:
        from multiprocess_framework.modules.logger_module.core.process_hooks import install_process_hooks

        services = _FakeServices("a5-identity")
        hooks_1 = install_process_hooks(services)
        try:
            hooks_2 = install_process_hooks(services)
            assert hooks_1 is hooks_2
        finally:
            hooks_1.uninstall()

    @pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
    def test_hooks_do_not_stack_one_exception_one_record(self, tmp_path) -> None:
        from multiprocess_framework.modules.logger_module.core.process_hooks import install_process_hooks

        prev_threading = threading.excepthook
        prev_sys = sys.excepthook
        prev_warn = warnings.showwarning

        error_mgr = ErrorManager(manager_name="a5-error", config=_manager_config(tmp_path, "a5_error"))
        error_mgr.initialize()
        store, _taps = wire_observability_store(error_mgr, None, db_path=str(tmp_path / "obs_a5.db"), process="a5")
        services = _FakeServices("a5-stack", error_manager=error_mgr)

        try:
            hooks_1 = install_process_hooks(services)
            install_process_hooks(services)  # второй install — не должен наслоить хук поверх первого

            message = f"double-{uuid.uuid4().hex}"
            thread = threading.Thread(
                target=_raise_named_error, args=(message,), name="double-install-worker", daemon=True
            )
            thread.start()
            _join_or_fail(thread)

            assert store.count(kind="error") == 1, "повторный install не должен задваивать доставку"
            assert hooks_1.counters()["thread_exceptions"] == 1

            hooks_1.uninstall()
            assert threading.excepthook is prev_threading
            assert sys.excepthook is prev_sys
            assert warnings.showwarning is prev_warn
        finally:
            store.close()
            error_mgr.shutdown()


# ---------------------------------------------------------------------------
# A6 — счётчики: всегда три ключа, дефолт ноль
# ---------------------------------------------------------------------------


class TestA6CountersAlwaysThreeKeysAndDefaultToZero:
    """A6: HOOK_COUNTER_KEYS фиксирует три имени контракта; observability_counters
    отдаёт их под error теми же именами; свежий ErrorManager без хуков видит их
    нулями в get_stats(); hooks.counters() несёт РОВНО эти три ключа.
    """

    def test_hook_counter_keys_constant_matches_the_contract(self) -> None:
        """Красный: ModuleNotFoundError (локальный импорт)."""
        from multiprocess_framework.modules.logger_module.core.process_hooks import HOOK_COUNTER_KEYS

        assert HOOK_COUNTER_KEYS == ("thread_exceptions", "warnings_captured", "hook_delivery_failures")

    def test_fresh_error_manager_has_the_three_keys_at_zero(self, tmp_path) -> None:
        """Красный: KeyError — ключей нет в get_stats() свежего ErrorManager (без хуков).

        НЕ импортирует process_hooks: свойство наблюдается на уже существующем
        ErrorManager/LoggerCore, независимо от того, есть модуль хуков или нет.
        """
        error_mgr = ErrorManager(manager_name="a6-fresh", config=_manager_config(tmp_path, "a6_fresh"))
        error_mgr.initialize()
        try:
            stats = error_mgr.get_stats()
            assert stats["thread_exceptions"] == 0
            assert stats["warnings_captured"] == 0
            assert stats["hook_delivery_failures"] == 0
        finally:
            error_mgr.shutdown()

    def test_observability_counters_surface_the_three_keys_for_error_plane(self, tmp_path) -> None:
        """Красный: KeyError — PLANE_COUNTER_KEYS ещё не знает эти три имени.

        НЕ импортирует process_hooks: наблюдается через уже существующий
        observability_counters()/PLANE_COUNTER_KEYS.
        """
        from multiprocess_framework.modules.process_module.managers.observability_reload import (
            observability_counters,
        )

        error_mgr = ErrorManager(manager_name="a6-oc", config=_manager_config(tmp_path, "a6_oc"))
        error_mgr.initialize()
        try:
            section = observability_counters(error=error_mgr)["error"]
            assert section["thread_exceptions"] == 0
            assert section["warnings_captured"] == 0
            assert section["hook_delivery_failures"] == 0
        finally:
            error_mgr.shutdown()

    def test_installed_hooks_counters_have_exactly_the_three_keys(self) -> None:
        """Красный: ModuleNotFoundError (локальный импорт)."""
        from multiprocess_framework.modules.logger_module.core.process_hooks import install_process_hooks

        services = _FakeServices("a6-shape")
        hooks = install_process_hooks(services)
        try:
            assert set(hooks.counters().keys()) == {
                "thread_exceptions",
                "warnings_captured",
                "hook_delivery_failures",
            }
        finally:
            hooks.uninstall()


# ---------------------------------------------------------------------------
# A7 — проводка в ProcessModule.initialize()/shutdown()
# ---------------------------------------------------------------------------


class TestA7ProcessModuleWiresHooks:
    """A7: ProcessModule.initialize() ставит хуки после подъёма менеджеров,
    shutdown() их снимает.

    ВАЖНО: этот класс намеренно НЕ импортирует process_hooks — красный обязан
    быть ``AssertionError`` (хуки не установлены), а не ``ImportError`` модуля,
    которого ещё нет. Проверяется только идентичность трёх глобальных хуков
    вокруг реального ``ProcessModule.initialize()``/``shutdown()`` — тот же
    мок shared_resources, что в test_process_lifecycle.py/
    test_builtin_commands_in_command_manager_after_run (проверено вручную:
    initialize() сегодня возвращает True и хуков НЕ трогает).
    """

    @staticmethod
    def _mock_shared_resources():
        sr = Mock()
        sr.get_process_data = Mock(return_value=None)
        sr.queue_registry = None
        sr.memory_manager = None
        sr.event_manager = Mock()
        sr.event_manager.set_router_manager = Mock()
        sr.process_state_registry = Mock()
        sr.process_state_registry.get_process_names = Mock(return_value=[])
        sr.process_state_registry.register_process = Mock(return_value=True)
        sr.process_state_registry.update_state = Mock(return_value=True)
        return sr

    def test_initialize_installs_hooks_and_shutdown_restores_them(self) -> None:
        prev_threading = threading.excepthook
        prev_sys = sys.excepthook
        prev_warn = warnings.showwarning

        process = ProcessModule("hook_wiring_probe", shared_resources=self._mock_shared_resources(), config={})
        assert process.initialize() is True
        try:
            # Контракт п.9: initialize() ставит хуки ПОСЛЕ подъёма менеджеров.
            # На этом HEAD process_hooks не существует и вызвать его некому —
            # хуки обязаны остаться ПРЕЖНИМИ, поэтому это падает.
            assert threading.excepthook is not prev_threading, (
                "ожидался установленный хук threading.excepthook после initialize()"
            )
            assert sys.excepthook is not prev_sys, "ожидался установленный хук sys.excepthook после initialize()"
            assert warnings.showwarning is not prev_warn, "ожидался установленный хук warnings.showwarning"
        finally:
            process.shutdown()

        assert threading.excepthook is prev_threading
        assert sys.excepthook is prev_sys
        assert warnings.showwarning is prev_warn


# ---------------------------------------------------------------------------
# A8 — diag.thread_raise / diag.warn: форма ответа по контракту (п.10)
# ---------------------------------------------------------------------------


class TestA8DiagCommands:
    """A8: diag.thread_raise / diag.warn регистрируются ВМЕСТЕ с health.*.

    ВАЖНО про полярность. Первая редакция этого класса оборачивала dispatch в
    ``pytest.raises(KeyError)`` — а это ЗЕЛЁНЫЙ тест, когда команды нет
    (ровно сегодняшнее состояние): проверка «команда бросает KeyError»
    проходит уже сейчас, что запрещено правилом «все тесты красны». Здесь
    вместо этого тест ПРЯМО вызывает dispatch и утверждает форму ответа по
    контракту п.10 — KeyError сегодняшнего dispatch («команды ещё нет»)
    просто пробрасывается наружу НЕПОЙМАННЫМ и роняет тест, как и остальные
    тесты файла.

    Хуки установлены на ТОМ ЖЕ services, где регистрируются команды — иначе
    diag.* негде брать thread_exceptions/warnings_captured (счётчики живут на
    конкретном инстансе ProcessHooks). dispatch — через
    ``_dispatch_with_timeout``: контракт обещает «≤ 2 с» внутри самой
    команды, но это её обещание, не гарантия теста, а тест обязан не виснуть
    сам по себе.

    Красный на этом HEAD: ``ModuleNotFoundError`` — process_hooks ещё не
    существует, импортируется первой строкой каждого теста.
    """

    @staticmethod
    def _make(services):
        bc = BuiltinCommands(services)
        bc._register_health_commands()
        return services.command_manager

    def test_diag_thread_raise_returns_success_with_thread_name_and_counter(self) -> None:
        from multiprocess_framework.modules.logger_module.core.process_hooks import install_process_hooks

        services = _FakeServices("diag_probe")
        hooks = install_process_hooks(services)
        try:
            cm = self._make(services)
            res = _dispatch_with_timeout(cm, "diag.thread_raise", {"message": f"probe-{uuid.uuid4().hex}"})
            assert res["success"] is True
            assert res["process"] == "diag_probe"
            assert res["thread"] == "diag-thread-raise", "дефолтное имя потока из контракта п.10"
            assert res["thread_exceptions"] >= 1
        finally:
            hooks.uninstall()

    def test_diag_thread_raise_uses_the_given_thread_name(self) -> None:
        from multiprocess_framework.modules.logger_module.core.process_hooks import install_process_hooks

        services = _FakeServices("diag_probe_named")
        hooks = install_process_hooks(services)
        try:
            cm = self._make(services)
            thread_name = f"probe-thread-{uuid.uuid4().hex[:8]}"
            res = _dispatch_with_timeout(
                cm, "diag.thread_raise", {"message": "custom name probe", "thread_name": thread_name}
            )
            assert res["thread"] == thread_name
        finally:
            hooks.uninstall()

    def test_diag_warn_returns_success_with_counter(self) -> None:
        from multiprocess_framework.modules.logger_module.core.process_hooks import install_process_hooks

        services = _FakeServices("diag_probe_warn")
        hooks = install_process_hooks(services)
        try:
            cm = self._make(services)
            res = _dispatch_with_timeout(cm, "diag.warn", {"message": f"probe-{uuid.uuid4().hex}"})
            assert res["success"] is True
            assert res["process"] == "diag_probe_warn"
            assert res["warnings_captured"] >= 1
        finally:
            hooks.uninstall()

    def test_diag_warn_rejects_unknown_category(self) -> None:
        from multiprocess_framework.modules.logger_module.core.process_hooks import install_process_hooks

        services = _FakeServices("diag_probe_bad_category")
        hooks = install_process_hooks(services)
        try:
            cm = self._make(services)
            res = _dispatch_with_timeout(cm, "diag.warn", {"message": "x", "category": "NoSuchWarning"})
            assert res["success"] is False
            assert "reason" in res
        finally:
            hooks.uninstall()
